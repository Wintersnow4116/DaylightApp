"""Inspect an already-generated Watch project without changing simulator state.

Commands may populate Xcode's ordinary caches. This probe never generates a
project, builds, runs tests, boots devices, pairs devices or installs software.
Raw stdout/stderr bytes are saved before parsing; JSON is configuration evidence,
never evidence that an application or test actually executed.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from time import monotonic
from uuid import UUID


SCHEMES = ("DaylightWatch", "DaylightWatchUITests")
WATCH_PLACEHOLDERS = {
    "dvtdevice-DVTWatchDeviceSimulatorPlaceholder-watchsimulator:placeholder",
    # Observed in Xcode 27.1, despite the iOS class name.
    "dvtdevice-DVTiOSDeviceSimulatorPlaceholder-watchsimulator:placeholder",
}


class EvidenceError(ValueError):
    pass


def uuid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise EvidenceError("Invalid simulator UDID")
    return str(UUID(value)).upper()


def destinations(text, scheme):
    """Conservatively interpret known headers, keeping every raw row and reason."""
    pairs = {"Available destinations for": "Ineligible destinations for",
             "Destinations compatible with": "Destinations incompatible with"}
    pattern = re.compile(
        r'^\s*(Available destinations for|Ineligible destinations for|'
        r'Destinations compatible with|Destinations incompatible with) '
        r'(?:the "([^"\r\n]+)" scheme|the scheme):[ \t]*\r?$', re.MULTILINE)
    headers = list(pattern.finditer(text))
    if (not headers or len(headers) > 2 or headers[0][1] not in pairs
            or any(h[2] not in (None, scheme) for h in headers)
            or (len(headers) == 2 and
                (headers[1][1] != pairs[headers[0][1]] or headers[1][2] != headers[0][2]))):
        raise EvidenceError("Missing, ambiguous or mismatched destination sections")
    result = {"compatible": [], "incompatible": []}
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        for line in text[header.end():end].splitlines():
            if not line.strip():
                continue
            row = re.fullmatch(r"\s*\{(.*)\}\s*", line)
            if not row:
                raise EvidenceError("Malformed destination section")
            # Free-text name/error consume the tail, so embedded 'id:' is never
            # interpreted as a structural attribute. Unknown formats fail closed.
            fields = {}
            tail = row[1].strip()
            while tail:
                match = re.match(r"(platform|arch|variant|id|OS|name|error):\s*", tail)
                if not match or match[1] in fields:
                    raise EvidenceError("Unknown or duplicated destination attribute")
                key = match[1]
                tail = tail[match.end():]
                if key in ("name", "error"):
                    fields[key] = tail
                    break
                # Architecture lists can contain commas within brackets.
                value = re.match(r"(?:\[[^\[\]]*\]|[^,\[\]])*(?:,|$)", tail)
                if not value or not value[0]:
                    raise EvidenceError("Malformed destination attributes")
                fields[key] = value[0].rstrip(",").strip()
                tail = tail[value.end():].strip()
            if not fields.get("platform") or not fields.get("id"):
                raise EvidenceError("Missing destination platform or id")
            item = {"raw": line, "attributes": fields}
            # Names/errors are unescaped free text. Treat an error-like tail
            # conservatively as unavailable; never reinterpret embedded IDs.
            item["unavailable"] = ("error" in fields or bool(
                re.search(r"(?:^|,)\s*error:", fields.get("name", ""))))
            if fields["platform"] == "watchOS Simulator":
                if fields["id"] not in WATCH_PLACEHOLDERS:
                    item["udid"] = uuid(fields["id"])
            result["compatible" if index == 0 else "incompatible"].append(item)
    excluded = {r["udid"] for r in result["incompatible"] if "udid" in r}
    excluded.update(r["udid"] for r in result["compatible"]
                    if "udid" in r and r["unavailable"])
    result["compatible_watch_udids"] = sorted(
        {r["udid"] for r in result["compatible"] if "udid" in r} - excluded)
    return result


def inventory(runtimes, devices):
    """Collapse identical identities; reject any conflicting duplicate record.

    Equality includes all reported fields and device runtime association. UUID
    case alone is equivalent. Original inventory bytes remain in command logs.
    """
    if not isinstance(runtimes, dict) or not isinstance(devices, dict):
        raise EvidenceError("Malformed simulator inventory")
    if not isinstance(runtimes.get("runtimes"), list) or not isinstance(devices.get("devices"), dict):
        raise EvidenceError("Malformed simulator inventory")
    watch = []
    associations = {}
    seen_runtimes = {}
    for runtime in runtimes["runtimes"]:
        if not isinstance(runtime, dict) or not isinstance(runtime.get("identifier"), str):
            raise EvidenceError("Malformed runtime entry")
        identifier = runtime["identifier"]
        if identifier in seen_runtimes:
            if seen_runtimes[identifier] != runtime:
                raise EvidenceError("Conflicting duplicate runtime: " + identifier)
            continue
        seen_runtimes[identifier] = runtime
        if runtime["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.watchOS-"):
            version = runtime.get("version")
            if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", version):
                raise EvidenceError("Missing or malformed Watch runtime version")
            watch.append(runtime)
            associations[runtime["identifier"]] = runtime
    entries = []
    available = set()
    seen_devices = {}
    for runtime_id, group in devices["devices"].items():
        if not isinstance(runtime_id, str) or not isinstance(group, list):
            raise EvidenceError("Malformed device group")
        for device in group:
            if not isinstance(device, dict):
                raise EvidenceError("Malformed Watch device")
            identifier = uuid(device.get("udid", ""))
            canonical = dict(device, udid=identifier)
            identity = {"runtime_identifier": runtime_id, "device": canonical}
            if identifier in seen_devices:
                if seen_devices[identifier] != identity:
                    raise EvidenceError("Conflicting duplicate device: " + identifier)
                continue
            seen_devices[identifier] = identity
            if not runtime_id.startswith("com.apple.CoreSimulator.SimRuntime.watchOS-"):
                continue
            if not all(isinstance(device.get(k), str) for k in ("name", "state", "deviceTypeIdentifier")):
                raise EvidenceError("Missing Watch device attributes")
            entries.append(identity)
            runtime = associations.get(runtime_id, {})
            if (runtime.get("isAvailable") is True and device.get("isAvailable") is True
                    and int(runtime["version"].split(".")[0]) >= 10
                    and device["deviceTypeIdentifier"].startswith(
                        "com.apple.CoreSimulator.SimDeviceType.Apple-Watch-")):
                available.add(identifier)
    return {"runtimes": sorted(watch, key=lambda r: r["identifier"]),
            "devices": sorted(entries, key=lambda d: (d["runtime_identifier"], d["device"]["udid"])),
            "available_watch_udids": sorted(available)}


def resolved_settings(response, target):
    """Validate one explicit target response, never infer settings from another."""
    if (not isinstance(response, list) or len(response) != 1
            or not isinstance(response[0], dict) or response[0].get("target") != target
            or not isinstance(response[0].get("buildSettings"), dict)):
        raise EvidenceError("Missing, duplicated or unexpected settings target: " + target)
    settings = response[0]["buildSettings"]
    expected = {"TARGET_NAME": target, "PLATFORM_NAME": "watchsimulator",
                "WATCHOS_DEPLOYMENT_TARGET": "10.0"}
    if target == SCHEMES[1]:
        expected.update(TEST_TARGET_NAME=SCHEMES[0],
                        PRODUCT_TYPE="com.apple.product-type.bundle.ui-testing")
    for key, value in expected.items():
        if key not in settings:
            raise EvidenceError(f"{target}: required setting {key} was not exposed")
        if settings[key] != value:
            raise EvidenceError(f"{target}: contradictory setting {key}")
    sdk = settings.get("SDKROOT")
    if not isinstance(sdk, str) or not re.search(
            r"(?:^|/)watchsimulator(?:[0-9]+(?:\.[0-9]+)*)?(?:\.sdk)?$", sdk, re.IGNORECASE):
        raise EvidenceError(target + ": missing or invalid Watch Simulator SDKROOT")
    if target == SCHEMES[0] and settings.get("PRODUCT_TYPE", "com.apple.product-type.application") != "com.apple.product-type.application":
        raise EvidenceError(target + ": unexpected application product type")
    return settings


class Probe:
    def __init__(self, output, project, runner=subprocess.run):
        self.output = Path(output)
        self.project = Path(project)
        self.runner = runner
        self.report = {"schema_version": 1, "runtime_execution": "not_executed",
                       "commands": {}, "issues": [], "configuration": {}}

    def issue(self, category, message, *, diagnostic=False):
        report = self.report["destination_repeat"] if diagnostic else self.report
        report["issues"].append({"category": category, "message": message})

    def command(self, name, args, structured=False, *, timed=False, diagnostic=False):
        stdout, stderr = b"", b""
        record = {"arguments": args, "stdout": name + ".stdout.log", "stderr": name + ".stderr.log"}
        if timed:
            record["started_at_utc"] = datetime.now(timezone.utc).isoformat()
            started = monotonic()
        try:
            result = self.runner(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 timeout=180, check=False)
            stdout, stderr = result.stdout, result.stderr
            record["returncode"] = result.returncode
            record["status"] = "passed" if result.returncode == 0 else "command_failed"
        except FileNotFoundError as error:
            record.update(status="missing_tool", error=str(error))
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            record.update(status="timeout")
        except OSError as error:
            record.update(status="command_failed", error=str(error))
        finally:
            if timed:
                record["elapsed_seconds"] = monotonic() - started
        # Preserve bytes, including original line endings, before interpretation.
        self.report["commands"][name] = record
        (self.output / record["stdout"]).write_bytes(stdout)
        (self.output / record["stderr"]).write_bytes(stderr)
        if record["status"] != "passed":
            self.issue(record["status"], name, diagnostic=diagnostic)
            return None
        try:
            # Only simctl help may supply its evidence on stderr. Validate the
            # usage line for the requested operation; JSON/destinations retain
            # strict stdout handling. The original streams above are untouched.
            if not structured and len(args) == 4 and args[:3] == ["xcrun", "simctl", "help"]:
                usage = r"(?m)^Usage:\s+simctl\s+" + re.escape(args[3]) + r"(?:\s|$)"
                for stream in (stdout, stderr):
                    help_text = stream.decode("utf-8-sig")
                    if re.search(usage, help_text):
                        return help_text
                raise EvidenceError("Missing or malformed simctl help usage for " + args[3])
            text = stdout.decode("utf-8-sig")
            if not text.strip():
                raise EvidenceError("Empty command output")
            return json.loads(text) if structured else text
        except (ValueError, UnicodeError) as error:
            self.issue("malformed_output", f"{name}: {error}", diagnostic=diagnostic)
            return None

    def query_destinations(self, name, args, scheme, *, diagnostic=False):
        raw = self.command(name, args, timed=True, diagnostic=diagnostic)
        if raw is not None:
            try:
                return destinations(raw, scheme)
            except EvidenceError as error:
                self.issue("malformed_output", f"{scheme}: {error}", diagnostic=diagnostic)
        return None

    def run(self):
        self.output.mkdir(parents=True, exist_ok=False)
        try:
            self.inspect()
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as error:
            self.issue("malformed_output", f"{type(error).__name__}: {error}")
        except OSError as error:
            self.issue("diagnostic_failure", str(error))
        finally:
            self.report["status"] = "established" if not self.report["issues"] else "not_established"
            (self.output / "report.json").write_text(
                json.dumps(self.report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if not self.report["issues"] else 1

    def inspect(self):
        for name, args, expected in (
            ("xcode", ["xcodebuild", "-version"], r"Xcode 27\.1\s+Build version \S+"),
            ("swift", ["xcrun", "swift", "--version"], r"Swift version \d+\.\d+"),
            ("sdks", ["xcodebuild", "-showsdks"], r"-sdk watchsimulator\S+"),
            ("xcodegen", ["xcodegen", "--version"], r"\d+\.\d+\.\d+"),
        ):
            evidence = self.command(name, args)
            if evidence is not None:
                self.report.setdefault("toolchain", {})[name] = evidence
                if not re.search(expected, evidence):
                    self.issue("missing_configuration", "Unexpected toolchain output: " + name)
        for operation in ("list", "bootstatus", "install", "launch", "spawn", "io", "terminate", "get_app_container"):
            self.command("simctl-help-" + operation, ["xcrun", "simctl", "help", operation])
        runtimes = self.command("runtimes", ["xcrun", "simctl", "list", "runtimes", "--json"], True)
        devices = self.command("devices", ["xcrun", "simctl", "list", "devices", "--json"], True)
        eligible_inventory = set()
        try:
            if not isinstance(runtimes, dict) or not isinstance(devices, dict):
                raise EvidenceError("Simulator inventory not established")
            self.report["inventory"] = inventory(runtimes, devices)
            eligible_inventory = set(self.report["inventory"]["available_watch_udids"])
            if not eligible_inventory:
                self.issue("missing_infrastructure", "No available Watch device on an installed watchOS 10+ runtime")
        except (EvidenceError, TypeError, KeyError) as error:
            self.issue("malformed_output", str(error))
        base = ["xcodebuild", "-project", str(self.project)]
        listing = self.command("schemes", base + ["-list", "-json"], True)
        try:
            schemes = listing["project"]["schemes"]
            if not isinstance(schemes, list) or not all(isinstance(s, str) for s in schemes):
                raise EvidenceError("Malformed scheme inventory")
            self.report["schemes"] = sorted(schemes)
            for scheme in SCHEMES:
                if scheme not in schemes:
                    self.issue("missing_configuration", "Missing scheme: " + scheme)
        except (TypeError, KeyError, EvidenceError) as error:
            self.issue("malformed_output", "Scheme inventory: " + str(error))
        compatible = []
        self.report["destinations"] = {}
        destination_commands = {
            scheme: base + ["-scheme", scheme, "-configuration", "Debug",
                            "-showdestinations", "CODE_SIGNING_ALLOWED=NO"]
            for scheme in SCHEMES
        }
        for scheme, args in destination_commands.items():
            evidence = self.query_destinations(scheme + "-destinations", args, scheme)
            ids = set()
            if evidence is not None:
                self.report["destinations"][scheme] = evidence
                ids = set(evidence["compatible_watch_udids"])
            if not ids:
                self.issue("missing_infrastructure", scheme + " has no established compatible Watch destination")
            compatible.append(ids)

        # Repeat the app query for comparison only. The first pair remains authoritative.
        app_scheme = SCHEMES[0]
        repeat_name = app_scheme + "-destinations-repeat"
        repeat = {"command": repeat_name, "issues": []}
        self.report["destination_repeat"] = repeat
        try:
            evidence = self.query_destinations(repeat_name, destination_commands[app_scheme],
                                               app_scheme, diagnostic=True)
            if evidence is not None:
                repeat["destinations"] = evidence
        except OSError as error:
            self.issue("diagnostic_failure", f"{repeat_name}: {error}", diagnostic=True)

        common = sorted(eligible_inventory.intersection(*compatible))
        self.report["common_eligible_watch_udids"] = common
        if not common:
            self.issue("missing_infrastructure", "No Watch UDID is available and compatible with both schemes")
        test_settings = None
        if common:
            # Scheme build-action settings can omit the UI-test target. Query
            # that target explicitly with its simulator SDK, without combining
            # -target with -scheme or claiming device-specific test resolution.
            response = self.command("watch-test-target-settings", base + [
                "-target", SCHEMES[1], "-configuration", "Debug", "-sdk", "watchsimulator",
                "-showBuildSettings", "-json", "CODE_SIGNING_ALLOWED=NO"], True)
            self.report["test_target_configuration"] = {
                "command": "watch-test-target-settings", "scope": "target-level simulator SDK settings",
                "verified": False}
            try:
                test_settings = resolved_settings(response, SCHEMES[1])
                self.report["test_target_configuration"].update(settings=test_settings, verified=True)
            except EvidenceError as error:
                self.issue("missing_configuration", str(error))
        # Inspect every common destination; never choose or boot a device.
        for identifier in common:
            settings = self.command("settings-" + identifier, base + ["-scheme", SCHEMES[1],
                "-configuration", "Debug", "-sdk", "watchsimulator", "-destination",
                "platform=watchOS Simulator,id=" + identifier, "-showBuildSettings", "-json",
                "CODE_SIGNING_ALLOWED=NO"], True)
            evidence = {"application_command": "settings-" + identifier,
                        "test_target_command": "watch-test-target-settings", "verified": False}
            self.report["configuration"][identifier] = evidence
            try:
                evidence["application_settings"] = resolved_settings(settings, SCHEMES[0])
                evidence["verified"] = test_settings is not None
            except EvidenceError as error:
                self.issue("missing_configuration", identifier + ": " + str(error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="DaylightApp.xcodeproj")
    parser.add_argument("--output", default="build/watch-probe", help="New evidence directory; existing evidence is never overwritten")
    args = parser.parse_args()
    try:
        return Probe(args.output, args.project).run()
    except OSError as error:
        parser.exit(1, f"Probe evidence could not be written: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
