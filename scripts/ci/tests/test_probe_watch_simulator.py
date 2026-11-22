"""Synthetic subprocess responses only; these are not captured Xcode evidence."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_watch_simulator import EvidenceError, Probe, destinations, inventory


A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
B = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
RUNTIME = "com.apple.CoreSimulator.SimRuntime.watchOS-27-2"
APP_DESTINATIONS = "DaylightWatch-destinations"
TEST_DESTINATIONS = "DaylightWatchUITests-destinations"
TEST_PREFLIGHT = "DaylightWatchUITests-destinations-preflight"
APP_REPEAT = "DaylightWatch-destinations-repeat"
PLACEHOLDER = "dvtdevice-DVTiOSDeviceSimulatorPlaceholder-watchsimulator:placeholder"


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
        "TARGET_NAME": name,
        "PRODUCT_TYPE": "com.apple.product-type.application" if name == "DaylightWatch" else "com.apple.product-type.bundle.ui-testing",
        **({"TEST_TARGET_NAME": "DaylightWatch"} if name == "DaylightWatchUITests" else {}),
        "PLATFORM_NAME": "watchsimulator",
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
                TEST_PREFLIGHT: output("DaylightWatchUITests"),
                APP_REPEAT: output("DaylightWatch"),
                "settings-" + A: [settings()[0]],
                "watch-test-target-settings": [settings()[1]]}

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
        commands[tuple(base + ["-target", "DaylightWatchUITests", "-configuration", "Debug",
                              "-sdk", "watchsimulator", "-showBuildSettings", "-json",
                              "CODE_SIGNING_ALLOWED=NO"])] = "watch-test-target-settings"
        for operation in ("list", "bootstatus", "install", "launch", "spawn", "io", "terminate", "get_app_container"):
            name = "simctl-help-" + operation
            commands[("xcrun", "simctl", "help", operation)] = name
            responses.setdefault(name, f"Usage: simctl {operation} <synthetic arguments>\n")
        for scheme in ("DaylightWatch", "DaylightWatchUITests"):
            commands[tuple(base + ["-scheme", scheme, "-configuration", "Debug",
                                  "-showdestinations", "CODE_SIGNING_ALLOWED=NO"])] = scheme + "-destinations"
        for name in responses:
            if not name.startswith("settings-"):
                continue
            identifier = name.removeprefix("settings-")
            commands[tuple(base + ["-scheme", "DaylightWatchUITests", "-configuration", "Debug",
                "-sdk", "watchsimulator", "-destination", "platform=watchOS Simulator,id=" + identifier,
                "-showBuildSettings", "-json", "CODE_SIGNING_ALLOWED=NO"])] = name

        app_queries = 0
        test_queries = 0

        def runner(args, **kwargs):
            nonlocal app_queries, test_queries
            calls.append(args)
            self.assertIn(tuple(args), commands, "Unexpected command invocation")
            self.assertEqual(kwargs, {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                                      "timeout": 180, "check": False})
            name = commands[tuple(args)]
            if name == APP_DESTINATIONS:
                app_queries += 1
                self.assertLessEqual(app_queries, 2)
                if app_queries == 2:
                    name = APP_REPEAT
            elif name == TEST_DESTINATIONS:
                test_queries += 1
                self.assertLessEqual(test_queries, 2)
                if test_queries == 1:
                    name = TEST_PREFLIGHT
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

    def test_repeat_cannot_change_ten_device_authoritative_decision(self):
        identifiers = [f"AAAAAAAA-AAAA-AAAA-AAAA-{index:012d}" for index in range(10)]
        app_full = 'Destinations compatible with the "DaylightWatch" scheme:\r\n' + "".join(
            f' {{ platform:watchOS Simulator, id:{identifier}, name:Synthetic Watch }}\r\n'
            for identifier in identifiers)
        test_full = app_full.replace('"DaylightWatch"', '"DaylightWatchUITests"', 1)
        app_empty = output("DaylightWatch", PLACEHOLDER)
        test_empty = output("DaylightWatchUITests", PLACEHOLDER)
        responses = {"devices": {"devices": {RUNTIME: [device(identifier) for identifier in identifiers]}}}
        responses.update({"settings-" + identifier: [settings()[0]] for identifier in identifiers})
        for preflight_count, test_count, app_count, repeat_count in (
            (0, 10, 10, 10), (10, 10, 10, 10), (10, 0, 10, 10),
            (10, 10, 0, 10), (0, 0, 10, 10), (10, 10, 0, 0), (10, 10, 10, 0),
        ):
            with self.subTest(preflight=preflight_count, ui_tests=test_count, app=app_count, repeat=repeat_count):
                preflight = test_full if preflight_count else test_empty
                ui_tests = test_full if test_count else test_empty
                app = app_full if app_count else app_empty
                repeat = app_full if repeat_count else app_empty
                code, report, files, calls = self.run_probe({
                    **responses, TEST_PREFLIGHT: preflight, TEST_DESTINATIONS: ui_tests,
                    APP_DESTINATIONS: app, APP_REPEAT: repeat})
                expected = identifiers if test_count and app_count else []
                self.assertEqual(code, 0 if expected else 1)
                self.assertEqual(report["common_eligible_watch_udids"], expected)
                self.assertEqual(report["destinations"]["DaylightWatch"]["compatible_watch_udids"],
                                 identifiers if app_count else [])
                self.assertEqual(report["destinations"]["DaylightWatchUITests"]["compatible_watch_udids"],
                                 identifiers if test_count else [])
                self.assertEqual(report["destination_preflight"]["destinations"]["compatible_watch_udids"],
                                 identifiers if preflight_count else [])
                self.assertEqual(report["destination_preflight"]["issues"], [])
                self.assertEqual(report["destination_repeat"]["destinations"]["compatible_watch_udids"],
                                 identifiers if repeat_count else [])
                self.assertEqual(report["destination_repeat"]["issues"], [])
                self.assertEqual(files[TEST_DESTINATIONS + ".stdout.log"], ui_tests.encode())
                self.assertEqual(files[APP_DESTINATIONS + ".stdout.log"], app.encode())
                self.assertEqual(files[APP_REPEAT + ".stdout.log"], repeat.encode())
                self.assertEqual(sum("-showBuildSettings" in call for call in calls), 11 if expected else 0)
                if expected:
                    self.assertTrue(report["test_target_configuration"]["verified"])
                    for identifier in expected:
                        self.assertTrue(report["configuration"][identifier]["verified"])

    def test_repeat_runs_after_unparseable_first_query_without_replacing_it(self):
        code, report, files, _ = self.run_probe({APP_DESTINATIONS: "unknown header"})
        self.assertEqual(code, 1)
        self.assertNotIn("DaylightWatch", report["destinations"])
        self.assertEqual(report["common_eligible_watch_udids"], [])
        self.assertTrue(any(issue["category"] == "malformed_output" for issue in report["issues"]))
        self.assertEqual(report["destination_repeat"]["destinations"]["compatible_watch_udids"], [A])
        self.assertEqual(files[APP_DESTINATIONS + ".stdout.log"], b"unknown header")

    def test_preflight_errors_do_not_block_authoritative_queries(self):
        for exit_code, category in ((0, "malformed_output"), (65, "command_failed")):
            with self.subTest(exit_code=exit_code):
                response = subprocess.CompletedProcess([], exit_code, b"unknown header\r\n", b"detail\xff\r\n")
                code, report, files, _ = self.run_probe({TEST_PREFLIGHT: response})
                self.assertEqual(code, 0)
                self.assertEqual(report["issues"], [])
                self.assertEqual(report["common_eligible_watch_udids"], [A])
                self.assertTrue(report["test_target_configuration"]["verified"])
                preflight = report["destination_preflight"]
                self.assertEqual([issue["category"] for issue in preflight["issues"]], [category])
                self.assertNotIn("destinations", preflight)
                command = report["commands"][TEST_PREFLIGHT]
                self.assertEqual(command["returncode"], exit_code)
                self.assertEqual(files[command["stdout"]], response.stdout)
                self.assertEqual(files[command["stderr"]], response.stderr)

    def test_repeat_command_failures_are_diagnostic_and_preserve_partial_output(self):
        for response, status, returncode, stdout, stderr in (
            (subprocess.CompletedProcess([], 65, b"partial\r\n", b"failure\xff\r\n"),
             "command_failed", 65, b"partial\r\n", b"failure\xff\r\n"),
            (subprocess.TimeoutExpired([], 180, output=b"partial\r\n", stderr=b"timeout\r\n"),
             "timeout", None, b"partial\r\n", b"timeout\r\n"),
            (FileNotFoundError("Synthetic missing executable"), "missing_tool", None, b"", b""),
        ):
            with self.subTest(status=status):
                code, report, files, _ = self.run_probe({APP_REPEAT: response})
                self.assertEqual(code, 0)
                self.assertEqual(report["status"], "established")
                self.assertEqual(report["common_eligible_watch_udids"], [A])
                self.assertEqual(report["issues"], [])
                self.assertEqual(report["destination_repeat"]["issues"],
                                 [{"category": status, "message": APP_REPEAT}])
                self.assertNotIn("destinations", report["destination_repeat"])
                record = report["commands"][APP_REPEAT]
                self.assertEqual(record["status"], status)
                self.assertEqual(record.get("returncode"), returncode)
                self.assertEqual(files[record["stdout"]], stdout)
                self.assertEqual(files[record["stderr"]], stderr)

    def test_malformed_repeat_is_reported_separately_from_authoritative_errors(self):
        placeholder = output("DaylightWatch", PLACEHOLDER)
        for first, expected_code in ((output("DaylightWatch"), 0), (placeholder, 1)):
            with self.subTest(expected_code=expected_code):
                baseline_code, baseline, _, _ = self.run_probe({APP_DESTINATIONS: first})
                self.assertEqual(baseline_code, expected_code)
                code, report, files, _ = self.run_probe({APP_DESTINATIONS: first, APP_REPEAT: "bad header"})
                self.assertEqual(code, expected_code)
                self.assertEqual(report["issues"], baseline["issues"])
                self.assertEqual(report["common_eligible_watch_udids"], baseline["common_eligible_watch_udids"])
                self.assertNotIn("destinations", report["destination_repeat"])
                self.assertEqual(report["destination_repeat"]["issues"][0]["category"], "malformed_output")
                self.assertEqual(files[APP_REPEAT + ".stdout.log"], b"bad header")

    def test_preflight_and_destination_queries_preserve_order_timing_and_bytes(self):
        keys = (TEST_PREFLIGHT, TEST_DESTINATIONS, APP_DESTINATIONS, APP_REPEAT)
        responses = {
            name: subprocess.CompletedProcess([], 0, self.responses()[name].encode(),
                                               f"{index}: raw stderr\r\n".encode() + b"\xff")
            for index, name in enumerate(keys)
        }
        with patch("probe_watch_simulator.monotonic", side_effect=[0, 0.5, 10, 11.25, 40, 42.5, 100, 103.75]):
            code, report, files, calls = self.run_probe(responses)
        self.assertEqual(code, 0)
        first_index = next(index for index, call in enumerate(calls) if "-showdestinations" in call)
        preflight, ui_tests, app, repeat = calls[first_index:first_index + 4]
        queries = [preflight, ui_tests, app, repeat]
        self.assertEqual([call[call.index("-scheme") + 1] for call in queries],
                         ["DaylightWatchUITests", "DaylightWatchUITests", "DaylightWatch", "DaylightWatch"])
        self.assertEqual(preflight, ui_tests)
        self.assertEqual(app, repeat)
        self.assertEqual([call for call in calls if "-showdestinations" in call], queries)
        self.assertEqual(report["destination_query_order"], [
            {"command": TEST_PREFLIGHT, "authoritative": False},
            {"command": TEST_DESTINATIONS, "authoritative": True},
            {"command": APP_DESTINATIONS, "authoritative": True},
            {"command": APP_REPEAT, "authoritative": False},
        ])
        self.assertIn("-showBuildSettings", calls[first_index + 4])
        self.assertEqual(report["destination_preflight"]["command"], TEST_PREFLIGHT)
        self.assertEqual(report["destination_repeat"]["command"], APP_REPEAT)
        for name, arguments, elapsed in zip(keys, queries, (0.5, 1.25, 2.5, 3.75)):
            record = report["commands"][name]
            self.assertEqual(record["arguments"], arguments)
            self.assertEqual(datetime.fromisoformat(record["started_at_utc"]).tzinfo, timezone.utc)
            self.assertEqual(record["elapsed_seconds"], elapsed)
            self.assertEqual(record["returncode"], 0)
            self.assertEqual(record["stdout"], name + ".stdout.log")
            self.assertEqual(record["stderr"], name + ".stderr.log")
            self.assertEqual(files[record["stdout"]], responses[name].stdout)
            self.assertEqual(files[record["stderr"]], responses[name].stderr)

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
                self.assertEqual(report["destination_query_order"][0],
                                 {"command": TEST_PREFLIGHT, "authoritative": False})
                self.assertEqual(report["destination_preflight"]["destinations"]["compatible_watch_udids"], [A])

    def test_all_common_devices_are_inspected_without_selection(self):
        additions = {"devices": {"devices": {RUNTIME: [device(), device(B)]}},
                     "settings-" + B: [settings()[0]]}
        for scheme in ("DaylightWatch", "DaylightWatchUITests"):
            additions[scheme + "-destinations"] = (
                f'Destinations compatible with the "{scheme}" scheme:\r\n'
                f' {{ platform:watchOS Simulator, id:{A}, name:First synthetic Watch }}\r\n'
                f' {{ platform:watchOS Simulator, id:{B}, name:Second synthetic Watch }}\r\n')
        code, report, _, calls = self.run_probe(additions)
        self.assertEqual(code, 0)
        self.assertEqual(report["common_eligible_watch_udids"], [A, B])
        self.assertEqual(set(report["configuration"]), {A, B})
        self.assertEqual(sum("-showBuildSettings" in call for call in calls), 3)

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
        for key in (TEST_DESTINATIONS, APP_DESTINATIONS):
            with self.subTest(failed_query=key):
                failure = subprocess.CompletedProcess([], 65, b"partial output\r\n", b"failure\r\n")
                code, report, files, calls = self.run_probe({key: failure})
                self.assertEqual(code, 1)
                self.assertEqual(report["commands"][key]["status"], "command_failed")
                self.assertIn({"category": "command_failed", "message": key}, report["issues"])
                self.assertEqual(files[key + ".stderr.log"], failure.stderr)
                self.assertEqual(report["destination_repeat"]["destinations"]["compatible_watch_udids"], [A])
                self.assertEqual(report["common_eligible_watch_udids"], [])
                self.assertFalse(any("-showBuildSettings" in call for call in calls))

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
            self.assertEqual(self.run_probe({"watch-test-target-settings": [invalid[1]]})[0], 1)

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

    def test_observed_xcode_placeholder_is_preserved_alongside_real_devices(self):
        # Exact placeholder row/section syntax observed in run 44691975970;
        # the remaining device/error rows are synthetic, not captured evidence.
        row = ('\t\t{ platform:watchOS Simulator, '
               'id:dvtdevice-DVTiOSDeviceSimulatorPlaceholder-watchsimulator:placeholder, '
               'name:Any watchOS Simulator Device }')
        overrides = {}
        for scheme in ("DaylightWatch", "DaylightWatchUITests"):
            text = output(scheme).replace("\r\n", "\r\n" + row + "\r\n", 1)
            evidence = destinations(text, scheme)
            self.assertEqual(evidence["compatible_watch_udids"], [A])
            self.assertEqual(evidence["compatible"][0]["raw"], row)
            self.assertNotIn("udid", evidence["compatible"][0])
            self.assertEqual(evidence["incompatible"][0]["udid"], B)
            overrides[scheme + "-destinations"] = text
        code, report, files, _ = self.run_probe(overrides)
        self.assertEqual(code, 0)
        self.assertEqual(report["common_eligible_watch_udids"], [A])
        self.assertEqual(files["DaylightWatch-destinations.stdout.log"],
                         overrides["DaylightWatch-destinations"].encode())
        for invalid in ("dvtdevice-UnknownPlaceholder-watchsimulator:placeholder", "not-a-uuid"):
            with self.assertRaises(EvidenceError):
                destinations(output("DaylightWatch", invalid), "DaylightWatch")

    def test_observed_placeholder_does_not_bypass_error_or_exclusion_rules(self):
        placeholder = "dvtdevice-DVTiOSDeviceSimulatorPlaceholder-watchsimulator:placeholder"
        self.assertEqual(self.run_probe({"DaylightWatch-destinations": output("DaylightWatch", placeholder)})[0], 1)
        for text in (output("DaylightWatch").replace("name:Synthetic Watch", "error:unavailable"),
                     output("DaylightWatch").replace("id:" + B, "id:" + A.lower())):
            text = text.replace("\r\n", f'\r\n {{ platform:watchOS Simulator, id:{placeholder}, name:Any watchOS Simulator Device }}\r\n', 1)
            self.assertEqual(self.run_probe({"DaylightWatch-destinations": text})[0], 1)

    def test_successful_stderr_only_help_is_valid_and_preserves_both_streams(self):
        overrides = {}
        for operation in ("list", "bootstatus", "install", "launch", "spawn", "io", "terminate", "get_app_container"):
            raw = f"Synthetic description\r\nUsage: simctl {operation} <arguments>\r\n".encode()
            overrides["simctl-help-" + operation] = subprocess.CompletedProcess([], 0, b"", raw)
        code, report, files, _ = self.run_probe(overrides)
        self.assertEqual(code, 0)
        for name, response in overrides.items():
            self.assertEqual(report["commands"][name]["status"], "passed")
            self.assertEqual(files[name + ".stdout.log"], b"")
            self.assertEqual(files[name + ".stderr.log"], response.stderr)

    def test_empty_malformed_or_failed_help_cannot_establish_capabilities(self):
        for response in (subprocess.CompletedProcess([], 0, b"", b""),
                         subprocess.CompletedProcess([], 0, b"", b" \r\n"),
                         subprocess.CompletedProcess([], 0, b"unrecognized output", b"warning only"),
                         subprocess.CompletedProcess([], 0, b"", b"Usage: simctl install <device>"),
                         subprocess.CompletedProcess([], 0, b"", b"\xff"),
                         subprocess.CompletedProcess([], 1, b"", b"Usage: simctl launch <device>")):
            code, report, files, _ = self.run_probe({"simctl-help-launch": response})
            self.assertEqual(code, 1)
            self.assertEqual(report["status"], "not_established")
            self.assertEqual(files["simctl-help-launch.stdout.log"], response.stdout)
            self.assertEqual(files["simctl-help-launch.stderr.log"], response.stderr)
            self.assertTrue(any(i["category"] == ("command_failed" if response.returncode else "malformed_output")
                                for i in report["issues"]))

    def test_json_commands_never_parse_stderr_as_stdout(self):
        for name in ("runtimes", "devices", "schemes", "settings-" + A, "watch-test-target-settings"):
            raw = json.dumps(self.responses()[name]).encode()
            code, report, files, _ = self.run_probe({name: subprocess.CompletedProcess([], 0, b"", raw)})
            self.assertEqual(code, 1)
            self.assertEqual(report["status"], "not_established")
            self.assertEqual(files[name + ".stdout.log"], b"")
            self.assertEqual(files[name + ".stderr.log"], raw)

    def test_application_only_scheme_response_and_independent_test_target_succeed(self):
        code, report, files, calls = self.run_probe()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(files["settings-" + A + ".stdout.log"]), [settings()[0]])
        self.assertEqual(json.loads(files["watch-test-target-settings.stdout.log"]), [settings()[1]])
        self.assertTrue(report["test_target_configuration"]["verified"])
        self.assertTrue(report["configuration"][A]["verified"])
        target_calls = [c for c in calls if "-target" in c]
        self.assertEqual(len(target_calls), 1)
        self.assertEqual(target_calls[0][target_calls[0].index("-target") + 1], "DaylightWatchUITests")
        self.assertNotIn("-scheme", target_calls[0])
        self.assertNotIn("-destination", target_calls[0])

    def test_captured_application_sdk_path_format_is_accepted(self):
        # Path format observed in run 44695148451; this response is synthetic.
        app = settings()[0]
        app["buildSettings"]["SDKROOT"] = (
            "/Applications/Xcode_27.1.app/Contents/Developer/Platforms/WatchSimulator.platform/"
            "Developer/SDKs/WatchSimulator27.0.sdk")
        self.assertNotIn("TEST_TARGET_NAME", app["buildSettings"])
        code, report, _, _ = self.run_probe({"settings-" + A: [app]})
        self.assertEqual(code, 0)
        self.assertTrue(report["configuration"][A]["verified"])

    def test_missing_malformed_duplicate_or_unexpected_target_responses_fail(self):
        for name, normal in (("settings-" + A, settings()[0]),
                             ("watch-test-target-settings", settings()[1])):
            for value in ([], {}, "not JSON", [normal, normal],
                          [dict(normal, target="UnexpectedTarget")],
                          [dict(normal, buildSettings={})], [settings()[0], settings()[1]]):
                with self.subTest(command=name, response=value):
                    code, report, files, _ = self.run_probe({name: value})
                    self.assertEqual(code, 1)
                    self.assertEqual(report["status"], "not_established")
                    self.assertFalse(report["configuration"][A]["verified"])
                    self.assertIn(name + ".stdout.log", files)

    def test_each_target_requires_consistent_identity_sdk_platform_and_deployment(self):
        for name, normal in (("settings-" + A, settings()[0]),
                             ("watch-test-target-settings", settings()[1])):
            for key, value in (("TARGET_NAME", "WrongTarget"), ("PLATFORM_NAME", "watchos"),
                               ("SDKROOT", "iphoneos27.0"), ("SDKROOT", "notwatchsimulator27.0"),
                               ("WATCHOS_DEPLOYMENT_TARGET", "9.0"),
                               ("WATCHOS_DEPLOYMENT_TARGET", "11.0")):
                with self.subTest(command=name, setting=key, value=value):
                    altered = dict(normal, buildSettings=dict(normal["buildSettings"], **{key: value}))
                    self.assertEqual(self.run_probe({name: [altered]})[0], 1)

    def test_ui_test_product_type_and_host_must_be_explicitly_established(self):
        for key in ("TEST_TARGET_NAME", "PRODUCT_TYPE"):
            for missing in (False, True):
                altered = settings()[1]
                if missing:
                    del altered["buildSettings"][key]
                else:
                    altered["buildSettings"][key] = "incorrect"
                code, report, _, _ = self.run_probe({"watch-test-target-settings": [altered]})
                self.assertEqual(code, 1)
                self.assertFalse(report["test_target_configuration"]["verified"])
                self.assertTrue(any(key in i["message"] for i in report["issues"]))
                if missing:
                    self.assertTrue(any("was not exposed" in i["message"] for i in report["issues"]))

    def test_target_specific_command_failure_preserves_raw_evidence_and_exit_code(self):
        code, report, files, _ = self.run_probe({"watch-test-target-settings":
            subprocess.CompletedProcess([], 65, b"partial stdout\r\n", b"target failed\r\n")})
        self.assertEqual(code, 1)
        self.assertEqual(report["commands"]["watch-test-target-settings"]["returncode"], 65)
        self.assertEqual(report["commands"]["watch-test-target-settings"]["status"], "command_failed")
        self.assertEqual(files["watch-test-target-settings.stdout.log"], b"partial stdout\r\n")
        self.assertEqual(files["watch-test-target-settings.stderr.log"], b"target failed\r\n")
        self.assertFalse(report["configuration"][A]["verified"])


if __name__ == "__main__":
    unittest.main()
