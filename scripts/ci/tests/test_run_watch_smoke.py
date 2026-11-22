"""Test smoke-lane contracts with synthetic runner responses."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_watch_smoke import EvidenceError, Smoke, TEST_IDENTIFIER, TEST_METHOD, select_destination


A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
B = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"


def capability():
    runtimes = [
        {"identifier": f"watchOS-{number}", "version": number, "isAvailable": True}
        for number in ("27.0", "27.2")
    ]
    return {
        "status": "established", "test_target_configuration": {"verified": True},
        "toolchain": {"sdks": "Simulator - watchOS 27.0  -sdk watchsimulator27.0\n"},
        "common_eligible_watch_udids": [A, B], "verified_watch_udids": [B, A],
        "inventory": {"runtimes": runtimes, "available_watch_udids": [A, B], "devices": [
            {"runtime_identifier": runtime["identifier"],
             "device": {"udid": identifier, "name": "Apple Watch", "isAvailable": True}}
            for identifier, runtime in zip((A, B), runtimes)]},
        "configuration": {identifier: {"verified": True, "application_settings": {
            "TARGET_DEVICE_IDENTIFIER": identifier, "TARGET_DEVICE_PLATFORM_NAME": "watchsimulator",
            "SDKROOT": "watchsimulator27.0"}} for identifier in (A, B)},
    }


class WatchSmokeTests(unittest.TestCase):
    def test_prefers_matching_sdk_runtime_and_only_verified_devices(self):
        report = capability()
        self.assertEqual(select_destination(report)["udid"], A)
        report["verified_watch_udids"] = [B]
        report["configuration"][A]["destination_issue"] = "destination_mismatch"
        self.assertEqual(select_destination(report)["udid"], B)

    def test_unestablished_empty_and_contradictory_reports_fail_closed(self):
        for mutation in (
            lambda report: report.update(status="not_established"),
            lambda report: report.update(verified_watch_udids=[]),
            lambda report: report["configuration"][A].update(destination_issue="destination_unavailable"),
            lambda report: report["inventory"].update(available_watch_udids=[B]),
        ):
            report = capability()
            mutation(report)
            with self.assertRaises(EvidenceError):
                select_destination(report)

    def run_smoke(self, *, fail_on=None, result="Passed", test_code=0, test_output=b"", report=None,
                  reader_code=0, reader_output=None):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence"

            def runner(args, *, capture_output, timeout, check):
                calls.append(args)
                if "probe_watch_simulator.py" in " ".join(args) and fail_on != "configuration_gate":
                    folder = output / "capability"
                    folder.mkdir()
                    (folder / "report.json").write_text(json.dumps(report if report is not None else capability()))
                stages = {"build-for-testing": "build_for_testing", "bootstatus": "simulator_startup",
                          "scripts/ci/probe_watch_simulator.py": "configuration_gate"}
                if any(token in args and phase == fail_on for token, phase in stages.items()):
                    return subprocess.CompletedProcess(args, 64, b"partial stdout\r\n", b"failure\xff")
                if "test-without-building" in args:
                    if result is not None:
                        (output / "WatchSmoke.xcresult").mkdir()
                    return subprocess.CompletedProcess(args, test_code, test_output, b"test stderr\xff")
                if "xcresulttool" in args:
                    nodes = {"testNodes": [{"nodeType": "Test Suite", "children": [
                        {"nodeType": "Test Case", "nodeIdentifier": f"DaylightWatchUITests/{TEST_METHOD}()",
                         "result": result}]}]}
                    stdout = json.dumps(nodes).encode() if reader_output is None else reader_output
                    stderr = b"xcresulttool: result read failed\r\n" if reader_code else b""
                    return subprocess.CompletedProcess(args, reader_code, stdout, stderr)
                return subprocess.CompletedProcess(args, 0, b"{}", b"")

            with patch("run_watch_smoke.subprocess.run", side_effect=runner):
                code = Smoke(output).run()
            files = {path.name: path.read_bytes() for path in output.glob("*.log")}
            return code, json.loads((output / "outcome.json").read_text()), files, calls

    def test_launches_exactly_one_serial_test_on_verified_device_and_preserves_evidence(self):
        code, outcome, files, calls = self.run_smoke(test_output=b"test stdout\r\n")
        self.assertEqual(code, 0)
        self.assertEqual(outcome["status"], "passed")
        self.assertEqual(outcome["test_result"], "Passed")
        self.assertEqual(outcome["commands"]["test_execution"]["returncode"], 0)
        self.assertEqual(outcome["commands"]["test_results"]["returncode"], 0)
        self.assertEqual(outcome["selected_destination"]["udid"], A)
        tests = [call for call in calls if "test-without-building" in call]
        self.assertEqual(len(tests), 1)
        self.assertIn(f"-only-testing:{TEST_IDENTIFIER}", tests[0])
        self.assertIn(f"platform=watchOS Simulator,id={A}", tests[0])
        self.assertEqual(tests[0][tests[0].index("-parallel-testing-enabled") + 1], "NO")
        self.assertEqual([call for call in calls if "bootstatus" in call],
                         [["xcrun", "simctl", "bootstatus", A, "-b"]])
        self.assertEqual(files["test_execution.stdout.log"], b"test stdout\r\n")
        self.assertEqual(files["test_execution.stderr.log"], b"test stderr\xff")
        self.assertEqual(calls[-1], ["xcrun", "simctl", "list", "--json"])

    def test_failed_prerequisites_prevent_test_execution_and_preserve_exit_code(self):
        for stage in ("configuration_gate", "build_for_testing", "simulator_startup"):
            with self.subTest(stage=stage):
                code, outcome, files, calls = self.run_smoke(fail_on=stage)
                self.assertEqual(code, 64)
                self.assertEqual(outcome["stage"], stage)
                self.assertEqual(files[f"{stage}.stderr.log"], b"failure\xff")
                self.assertFalse(any("test-without-building" in call for call in calls))
                self.assertIn("inventory_after.stdout.log", files)

    def test_empty_verified_list_stops_before_build_or_boot(self):
        report = capability()
        report["verified_watch_udids"] = []
        code, outcome, _, calls = self.run_smoke(report=report)
        self.assertEqual(code, 1)
        self.assertEqual(outcome["stage"], "destination_selection")
        self.assertIn("No verified Watch simulator", outcome["error"])
        self.assertFalse(any("build-for-testing" in call or "bootstatus" in call for call in calls))

    def test_runner_launch_assertion_and_skipped_results_are_distinct(self):
        for result, code, logs, stage in (
            (None, 65, b"Failed to launch the test runner", "test_runner_launch"),
            ("Failed", 65, b"XCTAssertEqual failed", "xctest_assertion"),
            ("Skipped", 0, b"", "test_result_verification"),
            (None, 0, b"", "test_result_verification"),
        ):
            with self.subTest(stage=stage, result=result):
                returned, outcome, _, _ = self.run_smoke(result=result, test_code=code, test_output=logs)
                self.assertEqual(returned, code or 1)
                self.assertEqual(outcome["stage"], stage)
                self.assertEqual(outcome["status"], "failed")

    def test_failed_result_reader_cannot_use_passing_json_as_evidence(self):
        code, outcome, files, _ = self.run_smoke(reader_code=1)
        self.assertEqual(code, 1)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["stage"], "test_result_verification")
        self.assertNotIn("test_result", outcome)
        self.assertEqual(outcome["commands"]["test_execution"]["returncode"], 0)
        self.assertEqual(outcome["commands"]["test_results"]["returncode"], 1)
        self.assertIn("xcresulttool exited with status 1", outcome["result_error"])
        nodes = json.loads(files["test_results.stdout.log"])["testNodes"]
        self.assertEqual(nodes[0]["children"][0]["result"], "Passed")
        self.assertEqual(files["test_results.stderr.log"], b"xcresulttool: result read failed\r\n")

    def test_execution_exit_code_remains_primary_even_if_reader_passes_or_fails(self):
        for reader_code in (0, 1):
            with self.subTest(reader_code=reader_code):
                code, outcome, _, _ = self.run_smoke(test_code=65, reader_code=reader_code)
                self.assertEqual(code, 65)
                self.assertEqual(outcome["status"], "failed")
                self.assertEqual(outcome["stage"], "test_execution")
                self.assertEqual(outcome["commands"]["test_execution"]["returncode"], 65)
                self.assertEqual(outcome["commands"]["test_results"]["returncode"], reader_code)
                if reader_code:
                    self.assertIn("xcresulttool exited with status 1", outcome["result_error"])
                    self.assertNotIn("test_result", outcome)
                else:
                    self.assertEqual(outcome["test_result"], "Passed")

    def test_unreadable_empty_unexpected_and_duplicate_results_fail_closed(self):
        case = {"nodeType": "Test Case", "nodeIdentifier": f"DaylightWatchUITests/{TEST_METHOD}()",
                "result": "Passed"}
        for stdout in (b"{malformed", b'{"testNodes": null}', b'{"testNodes": []}',
                       json.dumps({"testNodes": [{**case, "nodeIdentifier": "OtherTests/testUnexpected()"}]}).encode(),
                       json.dumps({"testNodes": [case, case]}).encode()):
            with self.subTest(stdout=stdout):
                code, outcome, files, _ = self.run_smoke(reader_output=stdout)
                self.assertEqual(code, 1)
                self.assertEqual(outcome["status"], "failed")
                self.assertEqual(outcome["stage"], "test_result_verification")
                self.assertNotIn("test_result", outcome)
                self.assertEqual(outcome["commands"]["test_results"]["returncode"], 0)
                self.assertEqual(files["test_results.stdout.log"], stdout)

    def test_runner_launch_failure_is_preserved_when_result_reader_also_fails(self):
        code, outcome, _, _ = self.run_smoke(
            test_code=65, reader_code=1, test_output=b"Failed to launch the test runner")
        self.assertEqual(code, 65)
        self.assertEqual(outcome["stage"], "test_runner_launch")
        self.assertIn("xcresulttool exited with status 1", outcome["result_error"])
