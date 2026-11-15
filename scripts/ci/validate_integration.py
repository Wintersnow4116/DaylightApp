"""Validate native app/SharedCore wiring and Xcode-resolved simulator settings."""

import argparse
import json
from pathlib import Path
import sys


APPS = {
    "DaylightIOS": ("iOS", "IPHONEOS_DEPLOYMENT_TARGET", "17.0", "org.example.daylight.ios"),
    "DaylightWatch": ("watchOS", "WATCHOS_DEPLOYMENT_TARGET", "10.0", "org.example.daylight.watch"),
}
CONFIGURATIONS = ("Debug", "Release", "UITesting")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def deployment_version(value):
    parts = str(value).split(".")
    require(1 <= len(parts) <= 3 and all(part.isdigit() for part in parts),
            f"Invalid deployment version: {value}")
    return tuple(int(part) for part in parts) + (0,) * (3 - len(parts))


def validate_spec(spec, manifest):
    require(set(CONFIGURATIONS).issubset(spec.get("configs", {})), "Missing existing build configuration")
    require(spec["configs"]["Debug"] == "debug" and spec["configs"]["UITesting"] == "debug"
            and spec["configs"]["Release"] == "release", "Release/Debug configuration types must remain correct")
    require(spec.get("packages", {}).get("DaylightCore", {}).get("path") == "SharedCore",
            "DaylightCore must use the local SharedCore package")
    products = manifest.get("products", [])
    require(any(p.get("name") == "DaylightCore" and p.get("targets") == ["DaylightCore"]
                for p in products), "SharedCore must export the DaylightCore target as product DaylightCore")
    require(any(t.get("name") == "DaylightCore" and t.get("type") == "regular"
                for t in manifest.get("targets", [])), "Missing regular DaylightCore package target")
    targets = spec.get("targets", {})
    application_targets = {name for name, target in targets.items()
                           if target.get("type", "").startswith("application")}
    require(application_targets == set(APPS), "Only the existing native iOS/watchOS applications are supported")
    for name, (platform, _, minimum, _) in APPS.items():
        target = targets[name]
        require(target.get("platform") == platform, f"{name}: wrong platform")
        require(str(spec.get("options", {}).get("deploymentTarget", {}).get(platform)) == minimum,
                f"{name}: minimum must remain {minimum}")
        dependencies = target.get("dependencies", [])
        require(any(d.get("package") == "DaylightCore" and d.get("product") == "DaylightCore"
                    for d in dependencies), f"{name}: missing direct DaylightCore product dependency")
        require(not any(d.get("target") in APPS for d in dependencies),
                f"{name}: applications must not depend on each other")
        scheme = spec.get("schemes", {}).get(name, {})
        require(name in scheme.get("build", {}).get("targets", {}), f"{name}: missing independent build scheme")
    ui = targets.get("DaylightUITests", {})
    require(ui.get("type") == "bundle.ui-testing" and ui.get("platform") == "iOS",
            "DaylightUITests must remain an iOS UI-testing target")
    require(ui.get("settings", {}).get("base", {}).get("TEST_TARGET_NAME") == "DaylightIOS",
            "UI tests must reference DaylightIOS")
    require(any(d.get("target") == "DaylightIOS" for d in ui.get("dependencies", [])),
            "UI tests must depend on DaylightIOS")
    test_action = spec.get("schemes", {}).get("DaylightUITests", {}).get("test", {})
    require(test_action.get("config") == "UITesting", "UI tests must use the isolated UITesting configuration")
    require(any((t if isinstance(t, str) else t.get("name")) == "DaylightUITests"
                for t in test_action.get("targets", [])), "UI scheme must execute DaylightUITests")


def validate_settings(rows, target, configuration):
    matches = [row.get("buildSettings", {}) for row in rows if row.get("target") == target]
    require(len(matches) == 1, f"{target}/{configuration}: missing or ambiguous resolved settings")
    settings = matches[0]
    _, key, minimum, bundle_id = APPS[target]
    actual_minimum = str(settings.get(key, ""))
    require(deployment_version(actual_minimum) == deployment_version(minimum),
            f"{target}/{configuration}: {key} is {actual_minimum}, expected {minimum}")
    isolated = target == "DaylightIOS" and configuration == "UITesting"
    require(settings.get("CONFIGURATION") == configuration, f"{target}: wrong resolved configuration")
    require(settings.get("PRODUCT_BUNDLE_IDENTIFIER") == (bundle_id + ".uitesting" if isolated else bundle_id),
            f"{target}/{configuration}: wrong application bundle identifier")
    flags = settings.get("SWIFT_ACTIVE_COMPILATION_CONDITIONS", "")
    tokens = flags.split() if isinstance(flags, str) else flags
    require(("DAYLIGHT_UI_TESTING" in tokens) == isolated,
            f"{target}/{configuration}: incorrect test-only storage routing flag")
    require(settings.get("CODE_SIGNING_ALLOWED") == "NO", f"{target}/{configuration}: signing must be disabled")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="Project spec exported from YAML as JSON")
    parser.add_argument("--manifest", type=Path, required=True, help="swift package dump-package JSON")
    parser.add_argument("--settings-directory", type=Path, required=True)
    args = parser.parse_args()
    validate_spec(json.loads(args.spec.read_text(encoding="utf-8")),
                  json.loads(args.manifest.read_text(encoding="utf-8")))
    print("Integration spec OK: both native app targets directly link local DaylightCore")
    for target in APPS:
        for configuration in CONFIGURATIONS:
            path = args.settings_directory / f"{target}-{configuration}.json"
            validate_settings(json.loads(path.read_text(encoding="utf-8")), target, configuration)
            print(f"Resolved settings OK: {target}/{configuration}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
