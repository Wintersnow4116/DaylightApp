import sys
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from select_simulator import SimulatorUnavailable, command, eligible_ids, main, select_device


class SimulatorSelectionTests(unittest.TestCase):
    def runtime(self, version, available=True, platform="iOS"):
        return {"identifier": f"com.apple.CoreSimulator.SimRuntime.{platform}-{version.replace('.', '-')}",
                "version": version, "isAvailable": available}

    def device(self, udid, family="iPhone", available=True, state="Shutdown"):
        return {"udid": udid, "name": "Any installed model",
                "deviceTypeIdentifier": f"com.apple.CoreSimulator.SimDeviceType.{family}-arbitrary",
                "isAvailable": available, "state": state}

    def test_newest_eligible_runtime_without_fixed_model(self):
        old, new = self.runtime("17.5"), self.runtime("27.1")
        runtimes = {"runtimes": [old, new]}
        devices = {"devices": {old["identifier"]: [self.device("old")],
                               new["identifier"]: [self.device("new")]}}
        runtime, device = select_device(runtimes, devices, {"old", "new"}, "17.0")
        self.assertEqual(runtime["version"], "27.1")
        self.assertEqual(device["udid"], "new")

    def test_unavailable_old_and_non_ios_runtimes_are_rejected(self):
        for runtime in [self.runtime("27.1", False), self.runtime("16.4"),
                        self.runtime("27.1", platform="watchOS")]:
            with self.subTest(runtime=runtime):
                with self.assertRaisesRegex(SimulatorUnavailable, "No installed available iOS"):
                    select_device({"runtimes": [runtime]}, {"devices": {}}, set(), "17.0")

    def test_ipad_unavailable_and_xcode_ineligible_devices_are_rejected(self):
        runtime = self.runtime("27.1")
        devices = {"devices": {runtime["identifier"]: [
            self.device("ipad", family="iPad"), self.device("unavailable", available=False),
            self.device("ineligible")
        ]}}
        with self.assertRaisesRegex(SimulatorUnavailable, "No installed available iPhone"):
            select_device({"runtimes": [runtime]}, devices, {"ipad", "unavailable"}, "17.0")

    def test_already_booted_device_is_preferred_for_same_runtime(self):
        runtime = self.runtime("27.1")
        devices = {"devices": {runtime["identifier"]: [
            self.device("shutdown"), self.device("booted", state="Booted")
        ]}}
        _, device = select_device({"runtimes": [runtime]}, devices, {"shutdown", "booted"}, "17.0")
        self.assertEqual(device["udid"], "booted")

    def test_destinations_parser_excludes_ineligible_section(self):
        good = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
        bad = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
        text = (f"Available destinations for the scheme:\n{{ platform:iOS Simulator, id:{good}, name:Phone }}\n"
                f"Ineligible destinations for the scheme:\n{{ platform:iOS Simulator, id:{bad}, name:Old }}")
        self.assertEqual(eligible_ids(text), {good})
        with self.assertRaisesRegex(SimulatorUnavailable, "Unknown or ambiguous"):
            eligible_ids("No destinations")

    def test_captured_xcode_27_1_destinations(self):
        # Unmodified ui-diagnostics/destinations.log from run 43676314178,
        # artifact 14145908296 (Xcode 27.1, build 27A9275).
        fixture = Path(__file__).parent / "fixtures/xcode-27.1-destinations.log"
        eligible = eligible_ids(fixture.read_text(encoding="utf-8-sig"))
        self.assertEqual(len(eligible), 24)
        self.assertIn("24E299B4-C77B-4426-AC2B-71243825F07C", eligible)
        self.assertIn("CD90C719-F4A8-40D6-9AC3-51BE522C2705", eligible)
        self.assertNotIn("59D98431-6DC6-4BA6-90DE-5EA5F59715D1", eligible)
        self.assertNotIn("D5A34E37-AA68-44E2-89EA-0F9AEA7732E8", eligible)

    def test_modern_sections_exclude_incompatible_and_non_simulator_destinations(self):
        good = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
        bad = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
        text = (f'Destinations compatible with the "DaylightUITests" scheme:\n'
                f'{{ platform:iOS Simulator, id:{good}, OS:27.1, name:iPhone 17 }}\n'
                f'{{ platform:iOS, id:{bad}, name:Physical iPhone }}\n'
                f'Destinations incompatible with the "DaylightUITests" scheme:\n'
                f'{{ platform:iOS Simulator, id:{bad}, name:iPhone 18 Pro, error:Unsupported }}')
        self.assertEqual(eligible_ids(text), {good})
        runtime = self.runtime("27.1")
        # An incompatible booted phone must not beat the compatible shutdown phone.
        devices = {"devices": {runtime["identifier"]: [
            self.device(bad, state="Booted"), self.device(good)]}}
        _, selected = select_device({"runtimes": [runtime]}, devices, eligible_ids(text), "17.0")
        self.assertEqual(selected["udid"], good)

    def test_multiple_compatible_phones_remain_deterministic(self):
        first = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
        second = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
        text = ('Destinations compatible with the "DaylightUITests" scheme:\n'
                f'{{ platform:iOS Simulator, id:{first}, OS:27.1, name:iPhone 17 }}\n'
                f'{{ platform:iOS Simulator, id:{second}, OS:27.1, name:iPhone 18 Pro }}')
        runtime = self.runtime("27.1")
        for order in ([first, second], [second, first]):
            devices = {"devices": {runtime["identifier"]: [self.device(i) for i in order]}}
            _, selected = select_device({"runtimes": [runtime]}, devices, eligible_ids(text), "17.0")
            self.assertEqual(selected["udid"], second)

    def test_duplicate_ids_are_deduplicated_and_incompatible_exclusion_wins(self):
        good = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
        bad = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
        row = f'{{ platform:iOS Simulator, id:{good}, name:iPhone 17 }}\n'
        text = ('Available destinations for the scheme:\n' + row + row
                + f'{{ platform:iOS Simulator, id:{bad}, name:iPhone 18 Pro }}\n'
                + 'Ineligible destinations for the scheme:\n'
                + f'{{ platform:iOS Simulator, id:{bad}, name:iPhone 18 Pro, error:Unavailable }}')
        self.assertEqual(eligible_ids(text), {good})

    def test_unknown_malformed_or_ambiguous_headers_fail_explicitly(self):
        row = '{ platform:iOS Simulator, id:AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA, name:iPhone 17 }\n'
        available = 'Available destinations for the scheme:\n'
        incompatible = 'Ineligible destinations for the scheme:\n'
        for text in ('', row, available.rstrip(':\n') + '\n' + row,
                     'Destinations compatible with:\n' + row,
                     incompatible + row + available + row,
                     available + row + available + row,
                     available + row + 'Destinations incompatible with the scheme:\n' + row,
                     available + row + 'Unsupported destinations for the scheme:\n' + row,
                     available + row + incompatible + row + incompatible + row):
            with self.subTest(text=text), self.assertRaises(SimulatorUnavailable):
                eligible_ids(text)

    def test_only_actual_id_field_is_extracted(self):
        row = ('{ platform:iOS Simulator, id:AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA, '
               'name:Reference id:BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB }')
        text = 'Destinations compatible with the "DaylightUITests" scheme:\n' + row
        self.assertEqual(eligible_ids(text), {"AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"})

    def test_text_attributes_cannot_introduce_or_exclude_ids(self):
        good = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
        unrelated = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
        for field in (f'name:Reference, id:{unrelated}',
                      f'error:Diagnostic, id:{unrelated}',
                      f'variant:Reference id:{unrelated}, name:iPhone 17'):
            text = ('Available destinations for the scheme:\n'
                    f'{{ platform:iOS Simulator, id:{good}, {field} }}\n'
                    'Ineligible destinations for the scheme:\n'
                    f'{{ platform:iOS Simulator, id:{unrelated}, error:Reference id:{good} }}')
            with self.subTest(field=field):
                self.assertEqual(eligible_ids(text), {good})
        # An unknown structural attribute is rejected, never searched for IDs.
        with self.assertRaises(SimulatorUnavailable):
            eligible_ids('Available destinations for the scheme:\n'
                         f'{{ platform:iOS Simulator, note:id:{unrelated}, name:iPhone 17 }}')

    def test_malformed_missing_and_duplicate_destination_ids_are_rejected(self):
        good = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
        for attributes in ('platform:iOS Simulator, name:iPhone 17',
                           'platform:iOS Simulator, id:not-a-uuid, name:iPhone 17',
                           f'platform:iOS Simulator, id:{good} trailing, name:iPhone 17',
                           f'platform:iOS Simulator, id:{good}, id:{good}, name:iPhone 17',
                           f'platform:iOS Simulator, id:{good}, id:BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB',
                           f'platform:iOS Simulator, variant:[iPad,iPhone, id:{good}, name:iPhone 17'):
            with self.subTest(attributes=attributes), self.assertRaises(SimulatorUnavailable):
                eligible_ids('Available destinations for the scheme:\n{ ' + attributes + ' }')

    def test_incompatible_uuid_exclusion_ignores_case(self):
        identifier = "ABCDEFAB-ABCD-ABCD-ABCD-ABCDEFABCDEF"
        text = ('Destinations compatible with the "DaylightUITests" scheme:\n'
                f'{{ platform:iOS Simulator, id:{identifier}, name:iPhone 17 }}\n'
                'Destinations incompatible with the "DaylightUITests" scheme:\n'
                f'{{ platform:iOS Simulator, id:{identifier.lower()}, name:iPhone 17 }}')
        self.assertEqual(eligible_ids(text), set())
        runtime = self.runtime("27.1")
        devices = {"devices": {runtime["identifier"]: [self.device(identifier, state="Booted")]}}
        with self.assertRaisesRegex(SimulatorUnavailable, "No installed available iPhone"):
            select_device({"runtimes": [runtime]}, devices, eligible_ids(text), "17.0")

    def test_mixed_case_inventory_ids_match_canonical_destinations(self):
        identifier = "ABCDEFAB-ABCD-ABCD-ABCD-ABCDEFABCDEF"
        runtime = self.runtime("27.1")
        for inventory_id, destination_id in ((identifier.lower(), identifier),
                                             (identifier, identifier.lower()),
                                             ("aBcDeFaB-aBcD-AbCd-aBcD-aBcDeFaBcDeF", identifier)):
            text = ('Available destinations for the scheme:\n'
                    f'{{ platform:iOS Simulator, id:{destination_id}, name:iPhone 17 }}')
            devices = {"devices": {runtime["identifier"]: [self.device(inventory_id)]}}
            with self.subTest(inventory_id=inventory_id, destination_id=destination_id):
                _, selected = select_device({"runtimes": [runtime]}, devices, eligible_ids(text), "17.0")
                self.assertEqual(selected["udid"], inventory_id)

    def test_case_variants_of_duplicate_uuid_are_deduplicated(self):
        identifier = "ABCDEFAB-ABCD-ABCD-ABCD-ABCDEFABCDEF"
        text = ('Available destinations for the scheme:\n'
                f'{{ platform:iOS Simulator, id:{identifier}, name:iPhone 17 }}\n'
                f'{{ platform:iOS Simulator, id:{identifier.lower()}, name:iPhone 17 }}')
        self.assertEqual(eligible_ids(text), {identifier})

    def test_section_scheme_identity_is_preserved_and_must_match(self):
        row = '{ platform:iOS Simulator, id:AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA, name:iPhone 17 }\n'
        for compatible, incompatible in (("Available destinations for", "Ineligible destinations for"),
                                         ("Destinations compatible with", "Destinations incompatible with")):
            text = f'{compatible} the "DaylightUITests" scheme:\n' + row
            with self.subTest(format=compatible):
                self.assertEqual(eligible_ids(text + f'{incompatible} the "DaylightUITests" scheme:\n'),
                                 {"AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"})
                for suffix in (f'{incompatible} the "OtherTests" scheme:\n',
                               f'{compatible} the "OtherTests" scheme:\n' + row,
                               f'{incompatible} the scheme:\n',
                               f'{incompatible} the "DaylightUITests" scheme:\n'
                               + f'{incompatible} the "OtherTests" scheme:\n'):
                    with self.subTest(suffix=suffix), self.assertRaises(SimulatorUnavailable):
                        eligible_ids(text + suffix)

    def test_missing_devices_is_a_blocker(self):
        with self.assertRaisesRegex(SimulatorUnavailable, "No installed available iPhone"):
            select_device({"runtimes": [self.runtime("27.1")]}, {"devices": {}}, set(), "17.0")

    def test_boot_uses_one_idempotent_bootstatus_command(self):
        runtime = self.runtime("27.1")
        udid = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
        device = self.device(udid)
        replies = [json.dumps({"runtimes": [runtime]}),
                   json.dumps({"devices": {runtime["identifier"]: [device]}}),
                   f"Available destinations for the scheme:\n{{ platform:iOS Simulator, id:{udid}, name:iPhone 17 }}", "Booted"]
        with tempfile.TemporaryDirectory(prefix="DaylightCI-") as directory:
            root = Path(directory)
            with patch("select_simulator.command", side_effect=replies) as runner, \
                    patch.dict(os.environ, {"GITHUB_OUTPUT": str(root / "output")}), \
                    patch.object(sys, "argv", ["select_simulator.py", "--logs", str(root / "logs")]):
                main()
            calls = [call.args[0] for call in runner.call_args_list]
            self.assertEqual(calls[-1], ["xcrun", "simctl", "bootstatus", udid, "-b"])
            self.assertFalse(any(call[:3] == ["xcrun", "simctl", "boot"] for call in calls))
            self.assertEqual((root / "output").read_text().strip(), f"udid={udid}")

    def test_failed_command_preserves_diagnostic_output(self):
        with tempfile.TemporaryDirectory(prefix="DaylightCI-") as directory:
            log = Path(directory) / "failure.log"
            failure = subprocess.CompletedProcess(["xcrun"], 1, stdout="Runtime unavailable")
            with patch("select_simulator.subprocess.run", return_value=failure):
                with self.assertRaisesRegex(SimulatorUnavailable, "Command failed"):
                    command(["xcrun"], log)
            self.assertEqual(log.read_text(), "Runtime unavailable")

    def test_timed_out_command_preserves_partial_output(self):
        with tempfile.TemporaryDirectory(prefix="DaylightCI-") as directory:
            log = Path(directory) / "timeout.log"
            failure = subprocess.TimeoutExpired(["xcrun"], 2, output=b"Boot in progress")
            with patch("select_simulator.subprocess.run", side_effect=failure):
                with self.assertRaisesRegex(SimulatorUnavailable, "timed out after 2s"):
                    command(["xcrun"], log, timeout=2)
            self.assertEqual(log.read_text(), "Boot in progress")


if __name__ == "__main__":
    unittest.main()
