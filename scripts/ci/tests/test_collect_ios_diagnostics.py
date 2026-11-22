"""Exercise diagnostic deadlines and evidence with mocked subprocesses."""

import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect_ios_diagnostics import collect, run_diagnostic


UDID = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"


def png_header(width=11, height=17):
    ihdr = b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + ihdr + struct.pack(">I", zlib.crc32(ihdr))


class IOSDiagnosticsTests(unittest.TestCase):
    def run_collection(self, *, simulator=UDID, failures=None, inventory=b'{"devices": {}}',
                       screenshot=png_header(), stale_screenshot=None):
        failures = failures or {}
        processes = {}

        def launch(args, *, stdout, stderr, start_new_session):
            name = args[2] if args[0] == "xcrun" else "version"
            code = failures.get(name, 0)
            stdout.write(inventory if name == "list" else f"{name} stdout\r\n".encode())
            stderr.write(b"stderr\xff\r\n")
            if name == "io" and code == 0 and screenshot is not None:
                Path(args[-1]).write_bytes(screenshot)
            process = Mock()
            process.wait.return_value = code
            processes[name] = process
            return process

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            if stale_screenshot is not None:
                (output / "simulator-final.png").write_bytes(stale_screenshot)
            with patch("collect_ios_diagnostics.subprocess.Popen", side_effect=launch):
                code = collect(output, simulator)
            files = {path.relative_to(output).as_posix(): path.read_bytes()
                     for path in output.rglob("*") if path.is_file()}
            report = json.loads(files["diagnostic-outcome.json"])
            return code, report, files, processes

    def test_success_preserves_legacy_output_paths_and_independent_deadlines(self):
        code, report, files, processes = self.run_collection()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["selected_simulator"], UDID)
        self.assertEqual(files["xcode-version.log"], b"version stdout\r\n")
        self.assertEqual(files["simulator-final-state.json"], b'{"devices": {}}')
        self.assertEqual(files["simulator-final.png"], png_header())
        self.assertEqual(files["simulator-app.log"], b"spawn stdout\r\n")
        self.assertEqual(files["simulator-app.stderr.log"], b"stderr\xff\r\n")
        for record, (name, timeout) in zip(
                report["commands"], [("version", 10), ("list", 20), ("io", 40), ("spawn", 60)], strict=True):
            processes[name].wait.assert_called_once_with(timeout=timeout)
            self.assertEqual(record["status"], "passed")
            self.assertEqual(record["exit_code"], 0)
            self.assertFalse(record["timed_out"])
            self.assertTrue(record["output_complete"])
            self.assertGreaterEqual(record["elapsed_seconds"], 0)
        self.assertEqual(report["commands"][1]["evidence_status"], "valid")
        self.assertEqual(report["commands"][2]["evidence_status"], "valid")

    def test_zero_exits_with_empty_inventory_and_no_screenshot_fail_closed(self):
        code, report, files, _ = self.run_collection(inventory=b"", screenshot=None)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "incomplete")
        for record in report["commands"][1:3]:
            self.assert_invalid_evidence(record)
            self.assertEqual(files[record["stderr"]], b"stderr\xff\r\n")
        self.assertEqual(files["simulator-final-state.json"], b"")
        self.assertEqual(files["simulator-screenshot.stdout.log"], b"io stdout\r\n")
        self.assertNotIn("simulator-final.png", files)

    def assert_invalid_evidence(self, record):
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["process_status"], "passed")
        self.assertFalse(record["timed_out"])
        self.assertIsNone(record["execution_error"])
        self.assertEqual(record["status"], "incomplete")
        self.assertFalse(record["output_complete"])
        self.assertEqual(record["evidence_status"], "invalid")
        self.assertTrue(record["evidence_error"])

    def test_invalid_inventory_preserves_original_stdout_and_stderr(self):
        for raw in (b"{broken", b"[]", b"{}", b'{"devices": []}', b'{"devices": {"runtime": [1]}}',
                    b'{"devices": {}, "other": NaN}', b"\xff"):
            with self.subTest(raw=raw):
                code, report, files, _ = self.run_collection(inventory=raw)
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "incomplete")
                record = report["commands"][1]
                self.assert_invalid_evidence(record)
                self.assertEqual(files[record["stdout"]], raw)
                self.assertEqual(files[record["stderr"]], b"stderr\xff\r\n")
                self.assertEqual(report["commands"][2]["evidence_status"], "valid")

    def test_invalid_screenshot_bytes_are_preserved(self):
        for image in (b"", b"not a PNG", png_header()[:29], png_header(width=0),
                      png_header()[:-1] + bytes([png_header()[-1] ^ 1])):
            with self.subTest(image=image):
                code, report, files, _ = self.run_collection(screenshot=image)
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "incomplete")
                record = report["commands"][2]
                self.assert_invalid_evidence(record)
                self.assertEqual(files[record["screenshot"]], image)

    def test_stale_screenshot_cannot_satisfy_the_current_invocation(self):
        stale = png_header(width=31)
        for image in (None, png_header()):
            with self.subTest(new_screenshot=bool(image)):
                code, report, files, _ = self.run_collection(screenshot=image, stale_screenshot=stale)
                record = report["commands"][2]
                self.assertNotEqual(record["screenshot"], "simulator-final.png")
                self.assertEqual(files["simulator-final.png"], stale)
                if image is None:
                    self.assertEqual(code, 1)
                    self.assert_invalid_evidence(record)
                    self.assertNotIn(record["screenshot"], files)
                else:
                    self.assertEqual(code, 0)
                    self.assertEqual(record["evidence_status"], "valid")
                    self.assertEqual(files[record["screenshot"]], image)

    def test_missing_uuid_collects_inventory_and_marks_device_commands_skipped(self):
        code, report, files, processes = self.run_collection(simulator="")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "incomplete")
        self.assertIsNone(report["selected_simulator"])
        self.assertEqual(set(processes), {"version", "list"})
        self.assertNotIn("simulator-final.png", files)
        self.assertNotIn("simulator-app.log", files)
        self.assertEqual([item["status"] for item in report["commands"]],
                         ["passed", "passed", "skipped", "skipped"])
        self.assertEqual(report["commands"][-1]["reason"], "No simulator UUID")

    def test_optional_failures_are_reported_and_other_evidence_is_collected(self):
        for command, report_name in (("list", "simulator-inventory"),
                                     ("io", "simulator-screenshot"), ("spawn", "simulator-app")):
            with self.subTest(command=command):
                code, report, files, processes = self.run_collection(failures={command: 23})
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "incomplete")
                self.assertEqual(set(processes), {"version", "list", "io", "spawn"})
                records = {record["name"]: record for record in report["commands"]}
                failed = records[report_name]
                self.assertEqual(failed["status"], "failed")
                self.assertEqual(failed["exit_code"], 23)
                self.assertFalse(failed["output_complete"])
                self.assertFalse(failed["timed_out"])
                self.assertEqual(files[failed["stderr"]], b"stderr\xff\r\n")
                self.assertEqual("simulator-final.png" in files, command != "io")

    def test_timeout_kills_process_group_and_never_waits_without_a_deadline(self):
        for reaped in (True, False):
            with self.subTest(reaped=reaped), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                args = ["xcrun", "simctl", "spawn", UDID, "log", "show"]
                process = Mock(pid=321)
                process.wait.side_effect = [
                    subprocess.TimeoutExpired(args, 60),
                    -9 if reaped else subprocess.TimeoutExpired(args, 2),
                ]

                def launch(arguments, *, stdout, stderr, start_new_session):
                    self.assertEqual(arguments, args)
                    self.assertTrue(start_new_session)
                    stdout.write(b"partial stdout\r\n")
                    stderr.write(b"partial stderr\xff\r\n")
                    return process

                with (patch("collect_ios_diagnostics.POSIX", True),
                      patch("collect_ios_diagnostics.signal.SIGKILL", 9, create=True),
                      patch("collect_ios_diagnostics.os.killpg", create=True) as kill,
                      patch("collect_ios_diagnostics.subprocess.Popen", side_effect=launch)):
                    record = run_diagnostic(output, "simulator-app", args, 60, "simulator-app.log")

                kill.assert_called_once_with(321, 9)
                process.kill.assert_not_called()
                self.assertEqual(process.wait.call_args_list, [call(timeout=60), call(timeout=2)])
                self.assertEqual(record["status"], "timed_out")
                self.assertEqual(record["process_status"], "timed_out")
                self.assertEqual(record["evidence_status"], "not_checked")
                self.assertTrue(record["timed_out"])
                self.assertFalse(record["output_complete"])
                self.assertEqual(record["exit_code"], -9 if reaped else None)
                self.assertIn("Exceeded 60s time limit", record["execution_error"])
                if not reaped:
                    self.assertIn("did not exit within 2s", record["execution_error"])
                self.assertEqual((output / record["stdout"]).read_bytes(), b"partial stdout\r\n")
                self.assertEqual((output / record["stderr"]).read_bytes(), b"partial stderr\xff\r\n")

    def test_command_start_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("collect_ios_diagnostics.subprocess.Popen", side_effect=FileNotFoundError("xcrun")):
                record = run_diagnostic(Path(directory), "simulator-app", ["xcrun"], 60, "simulator-app.log")
            self.assertEqual(record["status"], "failed")
            self.assertIsNone(record["exit_code"])
            self.assertEqual(record["execution_error"], "xcrun")
