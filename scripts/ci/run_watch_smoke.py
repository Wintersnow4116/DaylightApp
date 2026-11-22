"""Run one Watch UI smoke test using configuration evidence from this runner."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from probe_watch_simulator import EvidenceError, SCHEMES, uuid


TEST_METHOD = "testInitialLaunchShowsDefaultProgress"
TEST_IDENTIFIER = f"{SCHEMES[1]}/{SCHEMES[1]}/{TEST_METHOD}"


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
        raise EvidenceError(f"Invalid version: {value!r}")
    return tuple(int(part) for part in (value.split(".") + ["0"])[:3])


def select_destination(report):
    if report["status"] != "established" or report["test_target_configuration"]["verified"] is not True:
        raise EvidenceError("Watch configuration gate is not established")
    sdk_versions = {version(value) for value in re.findall(
        r"-sdk watchsimulator(\d+(?:\.\d+)+)\s*$", report["toolchain"]["sdks"], re.MULTILINE)}
    runtimes = {runtime["identifier"]: runtime for runtime in report["inventory"]["runtimes"]}
    devices = {entry["device"]["udid"]: entry for entry in report["inventory"]["devices"]}
    candidates = []
    for value in report["verified_watch_udids"]:
        identifier = uuid(value)
        evidence = report["configuration"][identifier]
        settings = evidence["application_settings"]
        entry = devices[identifier]
        runtime = runtimes[entry["runtime_identifier"]]
        if (identifier not in report["common_eligible_watch_udids"]
                or identifier not in report["inventory"]["available_watch_udids"]
                or evidence["verified"] is not True or "destination_issue" in evidence
                or uuid(settings["TARGET_DEVICE_IDENTIFIER"]) != identifier
                or settings["TARGET_DEVICE_PLATFORM_NAME"] != "watchsimulator"
                or entry["device"]["isAvailable"] is not True or runtime["isAvailable"] is not True):
            raise EvidenceError(f"Inconsistent Watch destination evidence for {identifier}")
        runtime_version = version(runtime["version"])
        candidates.append((runtime_version in sdk_versions, runtime_version, identifier, {
            "udid": identifier, "name": entry["device"]["name"], "runtime": runtime["identifier"],
            "runtime_version": runtime["version"], "sdk_runtime_match": runtime_version in sdk_versions,
            "sdk": settings["SDKROOT"],
        }))
    if not candidates:
        raise EvidenceError("No verified Watch simulator destination")
    # Prefer a matching SDK runtime, then the newest runtime, then the lowest UUID.
    return min(candidates, key=lambda item: (not item[0], tuple(-n for n in item[1]), item[2]))[3]


def test_cases(nodes):
    if not isinstance(nodes, list):
        raise EvidenceError("Expected a list of test nodes")
    for node in nodes:
        if not isinstance(node, dict):
            raise EvidenceError("Expected a test node object")
        if node.get("nodeType") == "Test Case":
            yield node
        yield from test_cases(node.get("children", []))


class Smoke:
    def __init__(self, output):
        self.output = output
        self.outcome = {"stage": "setup", "status": "running", "commands": {}}

    def save(self):
        (self.output / "outcome.json").write_text(json.dumps(self.outcome, indent=2) + "\n", encoding="utf-8")

    def run_command(self, name, args, timeout):
        record = {"arguments": args, "timeout_seconds": timeout}
        self.outcome["commands"][name] = record
        self.save()
        stdout = stderr = b""
        try:
            result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
            stdout, stderr = result.stdout, result.stderr
            record["returncode"] = result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            record.update(returncode=124, execution_error=str(error))
        except OSError as error:
            record.update(returncode=1, execution_error=str(error))
        (self.output / f"{name}.stdout.log").write_bytes(stdout)
        (self.output / f"{name}.stderr.log").write_bytes(stderr)
        self.save()
        return record["returncode"], stdout, stderr

    def require(self, stage, args, timeout):
        self.outcome["stage"] = stage
        code, _, _ = self.run_command(stage, args, timeout)
        if code:
            raise subprocess.CalledProcessError(code, args)

    def execute(self):
        project = "DaylightApp.xcodeproj"
        self.require("xcode_version", ["xcodebuild", "-version"], 30)
        self.require("inventory_before", ["xcrun", "simctl", "list", "--json"], 30)
        self.require("project_generation", ["xcodegen", "generate", "--spec", "project.yml"], 120)
        self.require("configuration_gate", [sys.executable, "-B", "scripts/ci/probe_watch_simulator.py",
                     "--project", project, "--output", str(self.output / "capability")], 1080)
        self.outcome["stage"] = "destination_selection"
        report = json.loads((self.output / "capability/report.json").read_bytes())
        self.outcome["selected_destination"] = selected = select_destination(report)
        udid = selected["udid"]
        self.save()

        base = ["xcodebuild", "-project", project, "-scheme", SCHEMES[1], "-configuration", "Debug",
                "-sdk", "watchsimulator", "-destination", f"platform=watchOS Simulator,id={udid}",
                "-destination-timeout", "60", "-derivedDataPath", str(self.output / "DerivedData")]
        self.require("build_for_testing", base + ["CODE_SIGNING_ALLOWED=NO", "build-for-testing"], 600)
        self.require("simulator_startup", ["xcrun", "simctl", "bootstatus", udid, "-b"], 180)
        bundle = self.output / "WatchSmoke.xcresult"
        self.outcome["stage"] = "test_execution"
        code, stdout, stderr = self.run_command("test_execution", base + [
            "-parallel-testing-enabled", "NO", "-maximum-concurrent-test-simulator-destinations", "1",
            "-test-timeouts-enabled", "YES", "-default-test-execution-time-allowance", "120",
            "-maximum-test-execution-time-allowance", "120", "-resultBundlePath", str(bundle),
            f"-only-testing:{TEST_IDENTIFIER}", "CODE_SIGNING_ALLOWED=NO", "test-without-building"], 300)
        result = []
        reader_code = None
        if bundle.is_dir():
            reader_code, raw, _ = self.run_command("test_results", [
                "xcrun", "xcresulttool", "get", "test-results", "tests", "--path", str(bundle)], 30)
            if reader_code:
                self.outcome["result_error"] = f"xcresulttool exited with status {reader_code}"
            else:
                try:
                    result = list(test_cases(json.loads(raw)["testNodes"]))
                except (ValueError, KeyError, TypeError, RecursionError):
                    self.outcome["result_error"] = "Could not read test cases from the result bundle"
        else:
            self.outcome["result_error"] = "WatchSmoke.xcresult was not produced"
        expected = [node for node in result if node.get("nodeIdentifier")
                    in (f"{SCHEMES[1]}/{TEST_METHOD}", f"{SCHEMES[1]}/{TEST_METHOD}()")]
        if len(result) == len(expected) == 1:
            self.outcome["test_result"] = expected[0].get("result")
        stage = "test_result_verification"
        logs = stdout + b"\n" + stderr
        if re.search(rb"failed to (?:boot|start) (?:the )?simulator", logs, re.IGNORECASE):
            stage = "simulator_startup"
        elif re.search(rb"(?:failed|unable) to launch (?:the )?test runner|test runner failed to launch",
                       logs, re.IGNORECASE):
            stage = "test_runner_launch"
        elif (code or self.outcome.get("test_result") == "Failed") and re.search(
                rb"XCT(?:Assert\w*|Fail) failed", logs):
            stage = "xctest_assertion"
        elif self.outcome.get("test_result") == "Failed":
            stage = "xctest_failure"
        elif code:
            stage = "test_execution" if bundle.is_dir() else "test_runner_launch_or_pretest"
        self.outcome["stage"] = stage
        if code:
            raise subprocess.CalledProcessError(code, ["xcodebuild", "test-without-building"])
        if reader_code:
            raise subprocess.CalledProcessError(reader_code, ["xcresulttool", "get", "test-results", "tests"])
        if stage in ("simulator_startup", "test_runner_launch"):
            raise EvidenceError("Xcode reported a startup or runner launch failure")
        if self.outcome.get("test_result") != "Passed":
            raise EvidenceError("The result bundle did not verify that exactly the requested test passed")

    def run(self):
        self.output.mkdir(parents=True, exist_ok=False)
        try:
            self.execute()
            self.outcome.update(stage="complete", status="passed", exit_code=0)
        except (EvidenceError, OSError, KeyError, TypeError, ValueError, subprocess.CalledProcessError) as error:
            self.outcome.update(status="failed", error=str(error), exit_code=getattr(error, "returncode", 1))
        finally:
            self.run_command("inventory_after", ["xcrun", "simctl", "list", "--json"], 30)
            self.save()
        print(f"Watch smoke {self.outcome['status']} at {self.outcome['stage']}")
        return self.outcome["exit_code"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(Smoke(parser.parse_args().output).run())
