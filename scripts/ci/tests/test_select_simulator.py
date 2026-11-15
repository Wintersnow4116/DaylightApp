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
        self.assertEqual(eligible_ids("No destinations"), set())

    def test_missing_devices_is_a_blocker(self):
        with self.assertRaisesRegex(SimulatorUnavailable, "No installed available iPhone"):
            select_device({"runtimes": [self.runtime("27.1")]}, {"devices": {}}, set(), "17.0")

    def test_boot_uses_one_idempotent_bootstatus_command(self):
        runtime = self.runtime("27.1")
        udid = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
        device = self.device(udid)
        replies = [json.dumps({"runtimes": [runtime]}),
                   json.dumps({"devices": {runtime["identifier"]: [device]}}),
                   f"Available destinations for the scheme:\n{{ id:{udid}, name:Phone }}", "Booted"]
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
