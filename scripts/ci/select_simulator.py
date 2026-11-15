"""Select and boot an installed, Xcode-eligible iPhone; never download or erase one."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


class SimulatorUnavailable(RuntimeError):
    pass


def version_tuple(value):
    parts = tuple(int(part) for part in str(value).split("."))
    return (parts + (0, 0, 0))[:3]


def eligible_ids(destinations):
    # Ineligible entries can contain valid UDIDs too; exclude that entire section.
    available = destinations.split("Available destinations for", 1)
    if len(available) != 2:
        return set()
    section = available[1].split("Ineligible destinations", 1)[0]
    return set(re.findall(r"\bid:\s*([0-9A-Fa-f-]{36})(?=[,\s}])", section))


def select_device(runtimes, devices, eligible, minimum):
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
                    and device.get("udid") in eligible):
                candidates.append((compatible[runtime_id], device))
    if not candidates:
        raise SimulatorUnavailable(
            "No installed available iPhone is eligible for the DaylightUITests scheme "
            f"on an iOS {minimum}+ runtime. Inspect simulator-devices.json and destinations.log."
        )
    # Deterministic choice: newest eligible OS, then an already booted device, then UDID.
    return sorted(candidates, key=lambda item: (
        version_tuple(item[0]["version"]), item[1].get("state") == "Booted", item[1]["udid"]
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
