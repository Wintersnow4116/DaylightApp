"""Synthetic subprocess responses only; these are not captured Xcode evidence."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_watch_simulator import EvidenceError, Probe, destinations, inventory


A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
B = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
RUNTIME = "com.apple.CoreSimulator.SimRuntime.watchOS-27-2"


def runtime(available=True):
    return {"identifier": RUNTIME, "version": "27.2", "isAvailable": available,
            "availabilityError": "Unavailable synthetic runtime" if not available else ""}


def device(identifier=A, available=True):
    return {"name": "Synthetic Watch", "udid": identifier, "isAvailable": available,
            "state": "Shutdown", "deviceTypeIdentifier": "com.apple.CoreSimulator.SimDeviceType.Apple-Watch-Synthetic",
            "availabilityError": "Unavailable synthetic device" if not available else ""}


def output(scheme, identifier=A, legacy=False):
    good = "Available destinations for" if legacy else "Destinations compatible with"
    bad = "Ineligible destinations for" if legacy else "Destinations incompatible with"
    return (f'{good} the "{scheme}" scheme:\r\n'
            f' {{ platform:watchOS Simulator, id:{identifier}, name:Synthetic Watch }}\r\n'
            f'{bad} the "{scheme}" scheme:\r\n'
            f' {{ platform:watchOS Simulator, id:{B}, name:Unavailable, error:runtime missing }}\r\n')


def settings():
    return [{"target": name, "buildSettings": {
        "TEST_TARGET_NAME": "DaylightWatch", "PLATFORM_NAME": "watchsimulator",
        "SDKROOT": "watchsimulator27.0", "WATCHOS_DEPLOYMENT_TARGET": "10.0"}}
        for name in ("DaylightWatch", "DaylightWatchUITests")]


class WatchProbeTests(unittest.TestCase):
    def responses(self):
        return {"xcode": "Xcode 27.1\nBuild version 27A9275\n",
                "swift": "Apple Swift version 6.4\n", "sdks": "-sdk watchsimulator27.0\n",
                "xcodegen": "Version: 2.44.1\n",
                "runtimes": {"runtimes": [runtime()]},
                "devices": {"devices": {RUNTIME: [device()]}},
                "schemes": {"project": {"schemes": ["DaylightWatch", "DaylightWatchUITests"]}},
                "DaylightWatch-destinations": output("DaylightWatch"),
                "DaylightWatchUITests-destinations": output("DaylightWatchUITests"),
                "settings-" + A: settings()}

    def run_probe(self, overrides=None):
        responses = self.responses()
        responses.update(overrides or {})
        calls = []
        base = ["xcodebuild", "-project", "DaylightApp.xcodeproj"]
        commands = {("xcodebuild", "-version"): "xcode",
                    ("xcrun", "swift", "--version"): "swift",
                    ("xcodebuild", "-showsdks"): "sdks",
                    ("xcodegen", "--version"): "xcodegen",
                    ("xcrun", "simctl", "list", "runtimes", "--json"): "runtimes",
                    ("xcrun", "simctl", "list", "devices", "--json"): "devices",
                    tuple(base + ["-list", "-json"]): "schemes"}
        for operation in ("list", "bootstatus", "install", "launch", "spawn", "io", "terminate", "get_app_container"):
            name = "simctl-help-" + operation
            commands[("xcrun", "simctl", "help", operation)] = name
            responses.setdefault(name, "Synthetic command help\n")
        for scheme in ("DaylightWatch", "DaylightWatchUITests"):
            commands[tuple(base + ["-scheme", scheme, "-configuration", "Debug",
                                  "-showdestinations", "CODE_SIGNING_ALLOWED=NO"])] = scheme + "-destinations"
        for identifier in (A, B):
            commands[tuple(base + ["-scheme", "DaylightWatchUITests", "-configuration", "Debug",
                "-sdk", "watchsimulator", "-destination", "platform=watchOS Simulator,id=" + identifier,
                "-showBuildSettings", "-json", "CODE_SIGNING_ALLOWED=NO"])] = "settings-" + identifier

        def runner(args, **kwargs):
            calls.append(args)
            self.assertIn(tuple(args), commands, "Unexpected command invocation")
            self.assertEqual(kwargs, {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                                      "timeout": 180, "check": False})
            name = commands[tuple(args)]
            self.assertIn(name, responses, "Missing explicit mocked response")
            response = responses[name]
            if isinstance(response, Exception):
                raise response
            if isinstance(response, subprocess.CompletedProcess):
                return response
            raw = json.dumps(response) if isinstance(response, (dict, list)) else response
            return subprocess.CompletedProcess(args, 0, raw.encode(), b"synthetic stderr\r\n")

        with tempfile.TemporaryDirectory() as temporary:
            probe = Probe(Path(temporary) / "evidence", "DaylightApp.xcodeproj", runner)
            code = probe.run()
            files = {p.name: p.read_bytes() for p in probe.output.iterdir()}
            return code, json.loads(files["report.json"]), files, calls

    def test_success_preserves_bytes_and_does_not_operate_devices(self):
        code, report, files, calls = self.run_probe()
        self.assertEqual(code, 0)
        self.assertEqual(report["runtime_execution"], "not_executed")
        self.assertEqual(report["common_eligible_watch_udids"], [A])
        self.assertTrue(report["configuration"][A]["verified"])
        self.assertEqual(files["DaylightWatch-destinations.stdout.log"], output("DaylightWatch").encode())
        self.assertEqual(files["DaylightWatch-destinations.stderr.log"], b"synthetic stderr\r\n")
        for args in calls:
            if args[:2] == ["xcrun", "simctl"]:
                self.assertIn(args[2], ("help", "list"))
            self.assertNotIn("test", args)
            self.assertNotIn("build", args)
            self.assertNotIn("generate", args)

    def test_multiple_devices_and_unavailable_reasons_retained(self):
        data = inventory({"runtimes": [runtime()]},
                         {"devices": {RUNTIME: [device(), device(B, False)]}})
        self.assertEqual(data["available_watch_udids"], [A])
        self.assertEqual(len(data["devices"]), 2)
        self.assertEqual(data["devices"][1]["device"]["availabilityError"], "Unavailable synthetic device")
        self.assertFalse(inventory({"runtimes": [runtime(False)]},
                                  {"devices": {RUNTIME: [device()]}})["available_watch_udids"])

    def test_missing_or_unavailable_runtime_fails(self):
        for runtimes in ([], [runtime(False)]):
            with self.subTest(runtimes=runtimes):
                code, report, _, _ = self.run_probe({"runtimes": {"runtimes": runtimes}})
                self.assertEqual(code, 1)
                self.assertEqual(report["common_eligible_watch_udids"], [])

    def test_all_common_devices_are_inspected_without_selection(self):
        additions = {"devices": {"devices": {RUNTIME: [device(), device(B)]}},
                     "settings-" + B: settings()}
        for scheme in ("DaylightWatch", "DaylightWatchUITests"):
            additions[scheme + "-destinations"] = (
                f'Destinations compatible with the "{scheme}" scheme:\r\n'
                f' {{ platform:watchOS Simulator, id:{A}, name:First synthetic Watch }}\r\n'
                f' {{ platform:watchOS Simulator, id:{B}, name:Second synthetic Watch }}\r\n')
        code, report, _, calls = self.run_probe(additions)
        self.assertEqual(code, 0)
        self.assertEqual(report["common_eligible_watch_udids"], [A, B])
        self.assertEqual(set(report["configuration"]), {A, B})
        self.assertEqual(sum("-showBuildSettings" in call for call in calls), 2)

    def test_missing_scheme_fails_even_when_destination_query_succeeds(self):
        code, report, _, _ = self.run_probe({"schemes": {"project": {"schemes": ["DaylightWatch"]}}})
        self.assertEqual(code, 1)
        self.assertTrue(any("Missing scheme" in issue["message"] for issue in report["issues"]))

    def test_both_header_formats_and_incompatible_exclusion(self):
        for legacy in (False, True):
            evidence = destinations(output("DaylightWatch", legacy=legacy), "DaylightWatch")
            self.assertEqual(evidence["compatible_watch_udids"], [A])
            self.assertIn("runtime missing", evidence["incompatible"][0]["raw"])
            excluded = output("DaylightWatch").replace("id:" + B, "id:" + A.lower())
            self.assertEqual(destinations(excluded, "DaylightWatch")["compatible_watch_udids"], [])

    def test_different_scheme_eligibility_does_not_establish_common_device(self):
        other = output("DaylightWatchUITests", B).replace("id:" + B + ", name:Unavailable", "id:" + A + ", name:Unavailable")
        code, report, _, calls = self.run_probe({"DaylightWatchUITests-destinations": other})
        self.assertEqual(code, 1)
        self.assertEqual(report["common_eligible_watch_udids"], [])
        self.assertFalse(any("-showBuildSettings" in call for call in calls))

    def test_malformed_and_missing_outputs_fail(self):
        for name, value in (("runtimes", "not json"), ("devices", {}),
                            ("schemes", []), ("xcode", ""),
                            ("DaylightWatch-destinations", "unknown header"),
                            ("settings-" + A, []),
                            ("settings-" + A, [{"target": "DaylightWatch", "buildSettings": []}]),
                            ("settings-" + A, settings() + settings())):
            with self.subTest(name=name):
                self.assertEqual(self.run_probe({name: value})[0], 1)

    def test_missing_tools_and_nonzero_exit_are_distinct(self):
        for name in ("xcodegen", "simctl-help-launch"):
            code, report, _, _ = self.run_probe({name: FileNotFoundError("Synthetic missing tool")})
            self.assertEqual(code, 1)
            self.assertEqual(report["commands"][name]["status"], "missing_tool")
        code, report, files, _ = self.run_probe({"DaylightWatch-destinations":
            subprocess.CompletedProcess([], 65, b"partial output\r\n", b"failure\r\n")})
        self.assertEqual(code, 1)
        self.assertEqual(report["commands"]["DaylightWatch-destinations"]["status"], "command_failed")
        self.assertEqual(files["DaylightWatch-destinations.stderr.log"], b"failure\r\n")

    def test_timeout_preserves_partial_evidence(self):
        code, report, files, _ = self.run_probe({"devices": subprocess.TimeoutExpired(
            ["xcrun"], 180, output=b"partial\r\n", stderr=b"timed out\r\n")})
        self.assertEqual(code, 1)
        self.assertEqual(report["commands"]["devices"]["status"], "timeout")
        self.assertEqual(files["devices.stdout.log"], b"partial\r\n")

    def test_structural_ids_scheme_mismatch_and_duplicate_sections_fail_closed(self):
        source = output("DaylightWatch")
        embedded = source.replace("name:Synthetic Watch", "name:Reference id:" + B)
        self.assertEqual(destinations(embedded, "DaylightWatch")["compatible_watch_udids"], [A])
        for invalid in (source.replace("id:" + A, "id:" + A + ", id:" + B),
                        source + source, source.replace('incompatible with the "DaylightWatch"',
                                                        'incompatible with the "OtherTests"')):
            with self.assertRaises(EvidenceError):
                destinations(invalid, "DaylightWatch")

    def test_settings_must_establish_watch_platform_target_and_deployment(self):
        for key, value in (("PLATFORM_NAME", "iphonesimulator"),
                           ("TEST_TARGET_NAME", "OtherApp"), ("WATCHOS_DEPLOYMENT_TARGET", "9.0")):
            invalid = settings()
            invalid[1]["buildSettings"][key] = value
            self.assertEqual(self.run_probe({"settings-" + A: invalid})[0], 1)

    def test_existing_evidence_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileExistsError):
                Probe(temporary, "DaylightApp.xcodeproj").run()

    def test_error_bearing_compatible_destinations_never_establish_capability(self):
        for tail in ("error:runtime unavailable", "name:Watch, error:runtime unavailable", "error:"):
            for legacy in (False, True):
                with self.subTest(tail=tail, legacy=legacy):
                    overrides = {scheme + "-destinations": output(scheme, legacy=legacy).replace(
                        "name:Synthetic Watch", tail) for scheme in ("DaylightWatch", "DaylightWatchUITests")}
                    code, report, files, _ = self.run_probe(overrides)
                    self.assertEqual(code, 1)
                    self.assertEqual(report["status"], "not_established")
                    self.assertEqual(report["common_eligible_watch_udids"], [])
                    self.assertEqual(files["DaylightWatch-destinations.stdout.log"],
                                     overrides["DaylightWatch-destinations"].encode())
                    self.assertTrue(report["destinations"]["DaylightWatch"]["compatible"][0]["unavailable"])

    def test_conflicting_runtime_duplicates_fail_in_both_orders(self):
        for records in ([runtime(), runtime(False)], [runtime(False), runtime()]):
            code, report, files, _ = self.run_probe({"runtimes": {"runtimes": records}})
            self.assertEqual(code, 1)
            self.assertEqual(report["status"], "not_established")
            self.assertTrue(any("Conflicting duplicate runtime" in i["message"] for i in report["issues"]))
            self.assertEqual(json.loads(files["runtimes.stdout.log"])["runtimes"], records)

    def test_conflicting_device_duplicates_fail_in_both_orders(self):
        for changed in (device(available=False), dict(device(), state="Booted")):
            for records in ([device(), changed], [changed, device()]):
                code, report, files, _ = self.run_probe({"devices": {"devices": {RUNTIME: records}}})
                self.assertEqual(code, 1)
                self.assertTrue(any("Conflicting duplicate device" in i["message"] for i in report["issues"]))
                self.assertEqual(json.loads(files["devices.stdout.log"])["devices"][RUNTIME], records)

    def test_consistent_duplicate_inventory_is_collapsed(self):
        code, report, _, _ = self.run_probe({"runtimes": {"runtimes": [runtime(), runtime()]},
            "devices": {"devices": {RUNTIME: [device(), device(A.lower())]}}})
        self.assertEqual(code, 0)
        self.assertEqual(len(report["inventory"]["runtimes"]), 1)
        self.assertEqual(len(report["inventory"]["devices"]), 1)
        self.assertEqual(report["common_eligible_watch_udids"], [A])

    def test_duplicate_device_runtime_associations_conflict_in_either_order(self):
        other = "com.apple.CoreSimulator.SimRuntime.iOS-27-1"
        groups = [(RUNTIME, [device()]), (other, [device()])]
        for ordered in (groups, list(reversed(groups))):
            code, report, _, _ = self.run_probe({"devices": {"devices": dict(ordered)}})
            self.assertEqual(code, 1)
            self.assertTrue(any("Conflicting duplicate device" in i["message"] for i in report["issues"]))

    def test_malformed_runtime_versions_always_produce_failure_report(self):
        for value in (27, None, "", "27..2", "27.beta", " 27.2", [], {}, True):
            with self.subTest(version=value):
                record = dict(runtime(), version=value)
                code, report, files, _ = self.run_probe({"runtimes": {"runtimes": [record]}})
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "not_established")
                self.assertTrue(any(i["category"] == "malformed_output" for i in report["issues"]))
                self.assertEqual(json.loads(files["runtimes.stdout.log"])["runtimes"], [record])
        record = runtime()
        del record["version"]
        self.assertEqual(self.run_probe({"runtimes": {"runtimes": [record]}})[0], 1)

    def test_below_minimum_runtime_and_non_watch_devices_are_ineligible(self):
        for overrides in ({"runtimes": {"runtimes": [dict(runtime(), version="9.4")]}},
                          {"devices": {"devices": {RUNTIME: [dict(device(),
                              deviceTypeIdentifier="com.apple.CoreSimulator.SimDeviceType.iPhone-Synthetic")]}}}):
            code, report, _, _ = self.run_probe(overrides)
            self.assertEqual(code, 1)
            self.assertEqual(report["common_eligible_watch_udids"], [])

    def test_stderr_only_output_is_preserved_but_does_not_establish_eligibility(self):
        raw = output("DaylightWatch").encode()
        code, report, files, _ = self.run_probe({"DaylightWatch-destinations":
            subprocess.CompletedProcess([], 0, b"", raw)})
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "not_established")
        self.assertEqual(files["DaylightWatch-destinations.stderr.log"], raw)
        self.assertEqual(files["DaylightWatch-destinations.stdout.log"], b"")

    def test_placeholder_malformed_and_missing_destinations_cannot_pass(self):
        for identifier in ("dvtdevice-DVTWatchDeviceSimulatorPlaceholder-watchsimulator:placeholder", "bad-id"):
            code, report, _, _ = self.run_probe({"DaylightWatch-destinations": output("DaylightWatch", identifier)})
            self.assertEqual(code, 1)
            self.assertEqual(report["common_eligible_watch_udids"], [])
        self.assertEqual(self.run_probe({"DaylightWatch-destinations":
            'Destinations compatible with the "DaylightWatch" scheme:\n'})[0], 1)


if __name__ == "__main__":
    unittest.main()
