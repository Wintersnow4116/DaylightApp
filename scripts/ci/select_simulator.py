"""Select and boot an installed, Xcode-eligible iPhone; never download or erase one."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import UUID


class SimulatorUnavailable(RuntimeError):
    pass


def version_tuple(value):
    parts = tuple(int(part) for part in str(value).split("."))
    return (parts + (0, 0, 0))[:3]


def canonical_id(value):
    try:
        return str(UUID(value)).upper()
    except (ValueError, TypeError, AttributeError):
        # Xcode also reports opaque physical-device and placeholder identifiers.
        return value


def destination_attributes(line):
    row = re.fullmatch(r"\s*\{(.*)\}\s*", line)
    if not row:
        raise SimulatorUnavailable("Malformed Xcode destination row; inspect destinations.log.")
    remaining = row.group(1).strip()
    attributes = {}
    while remaining:
        field = re.match(r"(platform|arch|variant|id|OS|name|error):\s*", remaining)
        if not field or field.group(1) in attributes:
            raise SimulatorUnavailable("Unknown or duplicate destination attribute; inspect destinations.log.")
        key = field.group(1)
        remaining = remaining[field.end():]
        # Xcode does not escape free-text names/errors. Never reinterpret their
        # contents as attributes, even if they contain commas, braces or 'id:'.
        if key in {"name", "error"}:
            attributes[key] = remaining
            break
        depth = 0
        boundary = len(remaining)
        for index, character in enumerate(remaining):
            if character == "[":
                depth += 1
            elif character == "]":
                depth -= 1
            elif character == "," and depth == 0:
                boundary = index
                break
            if depth < 0:
                break
        if depth != 0:
            raise SimulatorUnavailable("Malformed destination attribute brackets; inspect destinations.log.")
        attributes[key] = remaining[:boundary].strip()
        remaining = remaining[boundary + 1:].strip()
    if not attributes.get("platform") or not attributes.get("id"):
        raise SimulatorUnavailable("Missing destination platform/id; inspect destinations.log.")
    return attributes


def eligible_ids(destinations):
    pairs = {
        "Available destinations for": "Ineligible destinations for",
        "Destinations compatible with": "Destinations incompatible with",
    }
    header = re.compile(
        r"^[ \t]*(Available destinations for|Ineligible destinations for|"
        r"Destinations compatible with|Destinations incompatible with)"
        r'[ \t]+(?:the "([^"\r\n]+)" scheme|the scheme):[ \t]*\r?$', re.MULTILINE)
    sections = list(header.finditer(destinations))
    if (not sections or sections[0].group(1) not in pairs
            or len(sections) > 2
            or (len(sections) == 2
                and (sections[1].group(1) != pairs[sections[0].group(1)]
                     or sections[1].group(2) != sections[0].group(2)))):
        raise SimulatorUnavailable(
            "Unknown or ambiguous Xcode destination sections; inspect destinations.log.")

    end = sections[1].start() if len(sections) == 2 else len(destinations)
    available = destinations[sections[0].end():end]
    # A new/unrecognized header must not make later rows look compatible.
    if any(line.strip() and not re.fullmatch(r"\s*\{.*\}\s*", line)
           for line in available.splitlines()):
        raise SimulatorUnavailable(
            "Malformed Xcode compatible destination section; inspect destinations.log.")

    def section_ids(section, compatible_only):
        ids = set()
        for line in section.splitlines():
            if not line.strip():
                continue
            attributes = destination_attributes(line)
            raw_id = attributes["id"]
            if attributes["platform"] == "iOS Simulator":
                if raw_id == "dvtdevice-DVTiOSDeviceSimulatorPlaceholder-iphonesimulator:placeholder":
                    continue
                if not re.fullmatch(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", raw_id):
                    raise SimulatorUnavailable("Malformed simulator UUID; inspect destinations.log.")
                ids.add(canonical_id(raw_id))
            elif not compatible_only:
                ids.add(canonical_id(raw_id))
        return ids

    eligible = section_ids(available, compatible_only=True)
    # Exclusion wins even if a contradictory row repeats a compatible UDID.
    incompatible = destinations[sections[1].end():] if len(sections) == 2 else ""
    return eligible - section_ids(incompatible, compatible_only=False)


def select_device(runtimes, devices, eligible, minimum):
    eligible = {canonical_id(identifier) for identifier in eligible}
    compatible = {
        runtime["identifier"]: runtime
        for runtime in runtimes["runtimes"]
        if runtime.get("isAvailable") is True
        and runtime["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
        and version_tuple(runtime["version"]) >= version_tuple(minimum)
    }
    if not compatible:
        raise SimulatorUnavailable(
            f"No installed available iOS Simulator runtime satisfies iOS {minimum}+. "
            "No runtime was downloaded; inspect simulator-runtimes.json."
        )
    candidates = []
    for runtime_id, entries in devices["devices"].items():
        if runtime_id not in compatible:
            continue
        for device in entries:
            if (device.get("isAvailable") is True
                    and device.get("deviceTypeIdentifier", "").startswith(
                        "com.apple.CoreSimulator.SimDeviceType.iPhone-")
                    and canonical_id(device.get("udid")) in eligible):
                candidates.append((compatible[runtime_id], device))
    if not candidates:
        raise SimulatorUnavailable(
            "No installed available iPhone is eligible for the DaylightUITests scheme "
            f"on an iOS {minimum}+ runtime. Inspect simulator-devices.json and destinations.log."
        )
    # Deterministic choice: newest eligible OS, then an already booted device, then UDID.
    return sorted(candidates, key=lambda item: (
        version_tuple(item[0]["version"]), item[1].get("state") == "Booted", canonical_id(item[1]["udid"])
    ), reverse=True)[0]


def command(arguments, log, timeout=120):
    try:
        result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        output = error.stdout or b""
        log.write_text(output.decode(errors="replace") if isinstance(output, bytes) else output,
                       encoding="utf-8")
        raise SimulatorUnavailable(f"Command timed out after {timeout}s: {' '.join(arguments)}") from error
    log.write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        raise SimulatorUnavailable(f"Command failed ({result.returncode}): {' '.join(arguments)}; see {log}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum-ios", default="17.0")
    parser.add_argument("--logs", type=Path, default=Path("build/ui-diagnostics"))
    args = parser.parse_args()
    args.logs.mkdir(parents=True, exist_ok=True)
    runtimes = json.loads(command(["xcrun", "simctl", "list", "runtimes", "--json"],
                                  args.logs / "simulator-runtimes.json"))
    devices = json.loads(command(["xcrun", "simctl", "list", "devices", "--json"],
                                 args.logs / "simulator-devices.json"))
    destinations = command([
        "xcodebuild", "-showdestinations", "-project", "DaylightApp.xcodeproj",
        "-scheme", "DaylightUITests", "-configuration", "UITesting",
        "-derivedDataPath", "build/UITests", "CODE_SIGNING_ALLOWED=NO"
    ], args.logs / "destinations.log", timeout=180)
    runtime, device = select_device(runtimes, devices, eligible_ids(destinations), args.minimum_ios)
    udid = device["udid"]
    print(f"Selected {device['name']} ({udid}), installed iOS {runtime['version']}", flush=True)
    (args.logs / "selected-simulator.json").write_text(
        json.dumps({"runtime": runtime, "device": device}, indent=2), encoding="utf-8")
    # Export before boot, so failure diagnostics can still identify the chosen device.
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"udid={udid}\n")
    # -b boots if needed. Avoid a separate boot based on stale inventory: another
    # process may have booted the selected device since discovery.
    command(["xcrun", "simctl", "bootstatus", udid, "-b"],
            args.logs / "simulator-bootstatus.log", timeout=240)


if __name__ == "__main__":
    try:
        main()
    except (SimulatorUnavailable, ValueError, OSError, KeyError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
