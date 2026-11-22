"""Collect optional iOS simulator diagnostics with per-command deadlines."""

import argparse
import json
import os
from pathlib import Path
import signal
import stat
import struct
import subprocess
import tempfile
from time import monotonic
import zlib


REAP_TIMEOUT = 2
POSIX = os.name == "posix"
MAX_INVENTORY_BYTES = 16 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def reject_json_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def validate_inventory(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Simulator inventory is not a regular file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_INVENTORY_BYTES + 1)
    if not raw:
        raise ValueError("Simulator inventory is empty")
    if len(raw) > MAX_INVENTORY_BYTES:
        raise ValueError("Simulator inventory exceeds the evidence size limit")
    inventory = json.loads(raw, parse_constant=reject_json_constant)
    devices = inventory.get("devices") if isinstance(inventory, dict) else None
    if not isinstance(devices, dict) or any(
            not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries)
            for entries in devices.values()):
        raise ValueError("Simulator inventory requires a devices object mapping runtimes to device lists")


def validate_screenshot(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Screenshot is not a regular file")
    with path.open("rb") as stream:
        header = stream.read(33)
    if len(header) != 33 or header[:8] != PNG_SIGNATURE:
        raise ValueError("Screenshot has no complete PNG header")
    length, kind, width, height, depth, color, compression, filtering, interlace, crc = struct.unpack(
        ">I4sIIBBBBBI", header[8:])
    depths_by_color = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
    if (length != 13 or kind != b"IHDR" or not (0 < width < 2**31 and 0 < height < 2**31)
            or depth not in depths_by_color.get(color, ()) or compression != 0 or filtering != 0
            or interlace not in (0, 1) or zlib.crc32(header[12:29]) != crc):
        raise ValueError("Screenshot has an invalid PNG IHDR chunk")


def validate_evidence(record, path, validator):
    if record["process_status"] != "passed":
        return
    try:
        validator(path)
    except (OSError, ValueError, RecursionError) as error:
        record.update(status="incomplete", output_complete=False, evidence_status="invalid",
                      evidence_error=str(error))
    else:
        record["evidence_status"] = "valid"


def stop_timed_out_process(process):
    errors = []
    try:
        if POSIX:
            # Kill the session's process group, including children of xcrun.
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    except OSError as error:
        errors.append(f"Could not terminate subprocess: {error}")

    try:
        return process.wait(timeout=REAP_TIMEOUT), errors
    except subprocess.TimeoutExpired:
        errors.append(f"Subprocess did not exit within {REAP_TIMEOUT}s after termination")
        return None, errors


def run_diagnostic(output, name, arguments, timeout, stdout_name):
    stderr_name = f"{name}.stderr.log"
    record = {"name": name, "arguments": arguments, "timeout_seconds": timeout,
              "stdout": stdout_name, "stderr": stderr_name, "exit_code": None,
              "timed_out": False, "output_complete": False, "execution_error": None,
              "evidence_status": "not_checked", "evidence_error": None}
    start = monotonic()
    try:
        with (output / stdout_name).open("wb") as stdout, (output / stderr_name).open("wb") as stderr:
            # The child writes directly into the artifact files. It cannot block on a
            # pipe, and terminating it does not discard bytes already written.
            process = subprocess.Popen(arguments, stdout=stdout, stderr=stderr, start_new_session=POSIX)
            try:
                record["exit_code"] = process.wait(timeout=timeout)
                record["output_complete"] = record["exit_code"] == 0
            except subprocess.TimeoutExpired:
                record["timed_out"] = True
                record["exit_code"], errors = stop_timed_out_process(process)
                record["execution_error"] = "; ".join([f"Exceeded {timeout}s time limit", *errors])
    except OSError as error:
        record["execution_error"] = str(error)
    record["elapsed_seconds"] = monotonic() - start
    record["process_status"] = ("timed_out" if record["timed_out"] else
                                "passed" if record["output_complete"] else "failed")
    record["status"] = record["process_status"]
    return record


def collect(output, simulator):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "selected_simulator": simulator or None, "commands": []}
    outcome = output / "diagnostic-outcome.json"

    def save():
        outcome.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    commands = [
        ("xcode-version", ["xcodebuild", "-version"], 10, "xcode-version.log"),
        ("simulator-inventory", ["xcrun", "simctl", "list", "--json"], 20, "simulator-final-state.json"),
    ]
    if simulator:
        screenshot = output / "simulator-final.png"
        if os.path.lexists(screenshot):
            # Preserve the old image and give simctl a new path for this invocation.
            screenshot = Path(tempfile.mkdtemp(prefix="screenshot-", dir=output)) / screenshot.name
        commands.extend([
            ("simulator-screenshot", ["xcrun", "simctl", "io", simulator, "screenshot",
                                     str(screenshot)], 40, "simulator-screenshot.stdout.log"),
            ("simulator-app", ["xcrun", "simctl", "spawn", simulator, "log", "show", "--last", "10m",
                              "--style", "compact", "--predicate",
                              'process == "DaylightIOS" OR process CONTAINS "DaylightUITests"'],
             60, "simulator-app.log"),
        ])
    save()
    for command in commands:
        record = run_diagnostic(output, *command)
        if record["name"] == "simulator-inventory":
            validate_evidence(record, output / record["stdout"], validate_inventory)
        elif record["name"] == "simulator-screenshot":
            record["screenshot"] = screenshot.relative_to(output).as_posix()
            validate_evidence(record, screenshot, validate_screenshot)
        report["commands"].append(record)
        if record["status"] != "passed":
            print(f"::warning::{record['name']} {record['status']}. See {outcome} and the command logs.")
        save()

    if not simulator:
        for name in ("simulator-screenshot", "simulator-app"):
            report["commands"].append({"name": name, "status": "skipped", "reason": "No simulator UUID"})
        print("::notice::No simulator UUID available for screenshot or app logs")

    report["status"] = ("complete" if all(record["status"] == "passed" for record in report["commands"])
                        else "incomplete")
    save()
    return int(any(record["status"] in ("timed_out", "failed", "incomplete") for record in report["commands"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--simulator", default="")
    args = parser.parse_args()
    raise SystemExit(collect(args.output, args.simulator))
