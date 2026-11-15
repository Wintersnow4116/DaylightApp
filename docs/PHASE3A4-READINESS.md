# Phase 3A.4 — Validation readiness review

Execution is governed by [Phase 3A.5 — Final iOS & watchOS Validation](PHASE3A5-VALIDATION.md).
Xcode builds and simulator tests run on GitHub Actions macOS runners exclusively
to validate the native iOS/watchOS applications. macOS is not a product target;
no macOS application, interface or distribution configuration is in scope.

## Verified items (source review)

- Supported applications remain native iOS and watchOS only. Windows/macOS are
  development/validation hosts, not application targets. The active browser prototype
  is a parallel native-product design reference, outside this native validation gate;
  its development and user review remain supported and must not be disrupted.
- `project.yml` defines Debug, Release and UITesting as global configurations. Its
  platform-wide minimums are iOS **17.0** and watchOS **10.0**. No target/configuration
  deployment override or xcconfig was found. Both apps inherit those minimums in
  all three configurations; the iOS UI-test target also inherits iOS 17.0.
- DaylightIOS and DaylightWatch each directly depend on product `DaylightCore` from
  local package path `SharedCore`. Source files in both apps import DaylightCore.
  Each app has its own source directory and scheme; neither app depends on or embeds
  the other. DaylightUITests depends on DaylightIOS only.
- UITesting changes only the iOS app bundle ID to `org.example.daylight.ios.uitesting`
  and enables test-only data routing. Normal iOS ID remains `org.example.daylight.ios`;
  watchOS remains `org.example.daylight.watch` in all configurations.
- The eight iOS UI tests cover launch, History, Settings, start, stop, completed-record
  history/relaunch, goal persistence and active-session restoration. They use unique
  storage namespaces, stable control identifiers, bounded waits and no fixed sleeps.
- CI retains SharedCore tests, separate unsigned iOS/watchOS Debug simulator builds,
  dynamic iPhone discovery/boot, the iOS UITesting suite, xcresult and failure diagnostics.
  UI failure uploads precede watchOS compilation.

These are source findings, not generated-Xcode-setting, linker or simulator results.

## Unverified items and missing tests

| Gap | Existing coverage versus required evidence |
| --- | --- |
| Effective configuration settings and linkage | Source dependencies/minimums are consistent. Generate the project, inspect actual settings for every configuration, and build each app independently with Xcode. |
| Release builds | CI builds Debug and the debug-type iOS UITesting configuration; neither app's Release build is currently checked. Watch UITesting is globally defined but not a CI build action. |
| Manual iPhone entry | History's add button is checked for existence only. Valid submission, cancel, invalid/end-in-future/overlapping intervals and saved-history results lack UI tests. |
| Persistence failure UI | Foundation fault-injection tests exist. Actual initial-read failure/retry and failed start/stop/goal save feedback, rollback and retry lack platform-layer tests. |
| Background/lifecycle and rapid actions | UI tests terminate/relaunch but do not exercise Home/background/foreground, rapid repeated taps or interrupted pending writes. |
| Settings regression and historical UI | Normal save/relaunch is covered; navigation during a pending save, acknowledgment retention, goal boundaries, and visible historical progress recalculation are not. |
| Midnight/timezone UI | SharedCore tests cover attribution and DST. The actual History screen, multi-day details and active timer regrouping lack deterministic UI coverage. |
| Device/accessibility matrix | No dedicated dark-mode, large-text, VoiceOver, small-screen or iPad UI matrix. iPad is included in the iOS target's device family `1,2`; the selector currently chooses iPhones only. |
| watchOS runtime | No watch UI-test target, stable interaction identifiers, install/launch check or automated button smoke test exists. Building is not proof of launch or interaction. |
| Failure artifacts | Configured for iOS/UI-stage failures, not observed in this review. Cancellation/timeouts can prevent upload. A later watchOS-only failure has console logs, but no dedicated screenshot/xcresult collection step. |

Tab identifiers have a fixed-order fallback; the stepper uses a system child button.
Their actual accessibility exposure still requires execution. The watch app is an
independent, in-memory progress demo, with no journal persistence or synchronization.
That is its present scope, not a missing cross-device feature to implement here.

## Windows versus macOS checks

| Check | Host / current evidence |
| --- | --- |
| SharedCore build/test and CI Python fixtures | Can run on Windows using installed tools. Phase 3A.3 reported 44 Swift tests and nine Python fixtures passing; not rerun for this documentation-only review. The count includes the documented empty placeholder test. |
| Git whitespace/source/configuration review | Can run on Windows. Source review performed here; `git diff --check` passed. |
| Full YAML parsing | Can run wherever a suitable existing parser is available. No local parser was available in prior checks; CI configures Ruby YAML parsing. No parser installed or invoked here. |
| XcodeGen generation, effective settings, Apple SDK compilation/linking | Requires macOS/Xcode; not executed here. |
| iOS/watchOS simulator installation, launch, UI/lifecycle and artifacts | Requires macOS/Xcode; not executed here. |

## Exact iOS/watchOS validation commands for the macOS CI host

The commands below are **planned, not executed**. Use them in the GitHub Actions
macOS validation job, from the repository root in one Bash session with available
tools and designated test simulators. They validate iOS/watchOS, not a macOS product.
They create unique ignored build outputs and do not erase simulators, uninstall apps,
install software or touch the normal iPhone journal. Stop on any failed command.
Missing tools or eligible runtimes are **Blocked**, not Passed. Record actual Xcode,
SDK, simulator runtime and UDIDs; a newer runtime does not verify the minimum OS.

### 1. Preflight, parse and generate

```bash
set -euo pipefail
export DEVELOPER_DIR=/Applications/Xcode_27.1.app/Contents/Developer
test -d "$DEVELOPER_DIR"
command -v xcodegen
command -v python3
command -v ruby
mkdir -p build
validation_dir="$(mktemp -d "$PWD/build/phase3a4.XXXXXX")"
xcodebuild -version | tee "$validation_dir/xcode-version.log"
xcrun swift --version | tee "$validation_dir/swift-version.log"
xcodebuild -showsdks > "$validation_dir/sdks.log"
xcrun swift package --package-path SharedCore dump-package > "$validation_dir/package.json"
ruby -e 'require "yaml"; ARGV.each { |p| YAML.load_file(p); puts "YAML syntax OK: #{p}" }' project.yml .github/workflows/build.yml
python3 -B -m unittest discover -s scripts/ci/tests -v
xcrun swift build --package-path SharedCore
xcrun swift test --package-path SharedCore
xcodegen generate --spec project.yml
xcodebuild -list -project DaylightApp.xcodeproj | tee "$validation_dir/project-list.log"
```

Expected: the pinned Xcode exists, its compiler can read tools-version 6.4, both
simulator SDKs exist, YAML parses, nine fixtures and 44 Swift tests pass, and the
three existing schemes are listed. No installation fallback is authorized here.
The environment selection is local to this shell, not a global xcode-select change.

### 2. Verify effective settings for all six app/configuration combinations

```bash
for app_scheme in DaylightIOS DaylightWatch; do
  if [ "$app_scheme" = DaylightIOS ]; then
    simulator_sdk=iphonesimulator
    simulator_destination='generic/platform=iOS Simulator'
  else
    simulator_sdk=watchsimulator
    simulator_destination='generic/platform=watchOS Simulator'
  fi
  for build_configuration in Debug Release UITesting; do
    xcodebuild -project DaylightApp.xcodeproj -scheme "$app_scheme" \
      -configuration "$build_configuration" -sdk "$simulator_sdk" \
      -destination "$simulator_destination" \
      -showBuildSettings -json CODE_SIGNING_ALLOWED=NO \
      > "$validation_dir/$app_scheme-$build_configuration.json"
  done
done
python3 - "$validation_dir" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
for target, key, minimum in [
    ("DaylightIOS", "IPHONEOS_DEPLOYMENT_TARGET", "17.0"),
    ("DaylightWatch", "WATCHOS_DEPLOYMENT_TARGET", "10.0")
]:
    for config in ("Debug", "Release", "UITesting"):
        rows = json.loads((root / f"{target}-{config}.json").read_text())
        matches = [r["buildSettings"] for r in rows if r["target"] == target]
        assert len(matches) == 1, (target, config, "missing/ambiguous settings")
        settings = matches[0]
        assert float(settings[key]) == float(minimum), (target, config, settings[key])
        expected_id = ("org.example.daylight.watch" if target == "DaylightWatch" else
                       "org.example.daylight.ios.uitesting" if config == "UITesting" else
                       "org.example.daylight.ios")
        assert settings["PRODUCT_BUNDLE_IDENTIFIER"] == expected_id
        flags = settings.get("SWIFT_ACTIVE_COMPILATION_CONDITIONS", "")
        assert ("DAYLIGHT_UI_TESTING" in flags) == (target == "DaylightIOS" and config == "UITesting")
        print(f"Settings OK: {target} / {config}, minimum {minimum}, {expected_id}")
PY
```

Expected: six Settings OK lines and no lower/accidental per-configuration deployment
override. Keep the JSON evidence. This checks resolved settings, not runtime behavior.

### 3. Build both apps independently, including Release

```bash
for build_configuration in Debug Release; do
  xcodebuild -project DaylightApp.xcodeproj -scheme DaylightIOS \
    -configuration "$build_configuration" -sdk iphonesimulator \
    -destination 'generic/platform=iOS Simulator' \
    -derivedDataPath "$validation_dir/iOS-$build_configuration" \
    CODE_SIGNING_ALLOWED=NO build 2>&1 | tee "$validation_dir/iOS-$build_configuration.log"
  xcodebuild -project DaylightApp.xcodeproj -scheme DaylightWatch \
    -configuration "$build_configuration" -sdk watchsimulator \
    -destination 'generic/platform=watchOS Simulator' \
    -derivedDataPath "$validation_dir/watchOS-$build_configuration" \
    CODE_SIGNING_ALLOWED=NO build 2>&1 | tee "$validation_dir/watchOS-$build_configuration.log"
done
```

Expected: four successful builds, each linking the local DaylightCore product.
The watch build must not require an iPhone app build/embedding. Inspect each log;
SharedCore is a Swift package product, so do not require a separate dynamic framework
file as linkage evidence. The iOS UITesting configuration is built by the next test step.

### 4. Select an actual iPhone and run the eight UI tests

```bash
GITHUB_OUTPUT="$validation_dir/ios-selection.outputs" \
  python3 scripts/ci/select_simulator.py --minimum-ios 17.0 --logs "$validation_dir/ios-diagnostics"
ios_simulator_id="$(sed -n 's/^udid=//p' "$validation_dir/ios-selection.outputs")"
test -n "$ios_simulator_id"
xcodebuild -project DaylightApp.xcodeproj -scheme DaylightUITests \
  -configuration UITesting -sdk iphonesimulator \
  -destination "platform=iOS Simulator,id=$ios_simulator_id" -destination-timeout 120 \
  -derivedDataPath "$validation_dir/UITests" \
  -resultBundlePath "$validation_dir/DaylightUITests.xcresult" \
  -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
  -test-timeouts-enabled YES -default-test-execution-time-allowance 120 \
  -maximum-test-execution-time-allowance 180 -only-testing:DaylightUITests \
  CODE_SIGNING_ALLOWED=NO test 2>&1 | tee "$validation_dir/ui-tests.log"
```

Expected: an available Xcode-eligible iOS 17+ iPhone is booted, the isolated test app
runs, all eight tests pass and the xcresult exists. Confirm the executed test count;
a successful build or zero tests is insufficient. The selector's destination query
also uses its existing ignored `build/UITests` directory. No production data reset occurs.

### 5. Select, install and launch an actual watchOS app

```bash
xcrun simctl list runtimes --json > "$validation_dir/runtimes.json"
xcrun simctl list devices --json > "$validation_dir/devices.json"
xcodebuild -project DaylightApp.xcodeproj -scheme DaylightWatch -configuration Debug \
  -sdk watchsimulator -showdestinations CODE_SIGNING_ALLOWED=NO \
  > "$validation_dir/watch-destinations.log"
watch_simulator_id="$(python3 - "$validation_dir" <<'PY'
import json, pathlib, sys
from scripts.ci.select_simulator import eligible_ids, version_tuple
root = pathlib.Path(sys.argv[1])
eligible = eligible_ids((root / "watch-destinations.log").read_text())
runtimes = {r["identifier"]: r for r in json.loads((root / "runtimes.json").read_text())["runtimes"]
            if r.get("isAvailable") and r["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.watchOS-")
            and version_tuple(r["version"]) >= version_tuple("10.0")}
candidates = [(version_tuple(runtimes[rid]["version"]), d.get("state") == "Booted", d["udid"], runtimes[rid], d)
              for rid, devices in json.loads((root / "devices.json").read_text())["devices"].items() if rid in runtimes
              for d in devices if d.get("isAvailable") and d["udid"] in eligible]
if not candidates:
    raise SystemExit("BLOCKED: no installed Xcode-eligible available watchOS 10+ simulator")
chosen = max(candidates, key=lambda c: c[:3])
(root / "selected-watch.json").write_text(json.dumps({"runtime": chosen[3], "device": chosen[4]}, indent=2))
print(chosen[2])
PY
)"
test -n "$watch_simulator_id"
xcrun simctl bootstatus "$watch_simulator_id" -b
watch_app_path="$validation_dir/watchOS-Debug/Build/Products/Debug-watchsimulator/DaylightWatch.app"
test -d "$watch_app_path"
xcrun simctl install "$watch_simulator_id" "$watch_app_path"
xcrun simctl launch "$watch_simulator_id" org.example.daylight.watch
xcrun simctl io "$watch_simulator_id" screenshot "$validation_dir/watch-initial.png"
```

Expected: a compatible installed watchOS runtime/device is recorded, install exits 0,
launch reports a process ID and a screenshot can be captured. Inspect the screenshot;
the command can succeed before the app's UI is ready. A launch PID/screenshot is not
interaction evidence. No phone pairing or synchronization is assumed.

With an already available interactive Mac Simulator session, bring up that device:

```bash
open -a Simulator --args -CurrentDeviceUDID "$watch_simulator_id"
```

Manually verify initial 0/30 minutes, 0% and 30 remaining; five taps of the existing
+5-minute button yield 25/30, 83% and 5 remaining; six total taps yield 30/30 and 100%;
seven total taps yield 35/30 with completion capped at 100% and no remaining time.
Capture the resulting screen, then verify the documented in-memory reset:

```bash
xcrun simctl io "$watch_simulator_id" screenshot "$validation_dir/watch-after-interaction.png"
xcrun simctl terminate "$watch_simulator_id" org.example.daylight.watch
xcrun simctl launch "$watch_simulator_id" org.example.daylight.watch
```

Expected after UI readiness: 0/30 again. On the current headless CI runner, the manual
interaction/visual checks remain **Not tested** unless a narrow watch UI test is
separately authorized and added. This review adds no test target or infrastructure.

### 6. Record the remaining acceptance evidence

Record each missing iOS flow above as Passed/Failed/Not tested/Blocked, not inferred
from the eight-test result. Retain version/settings/build logs, both selected device
records, xcresult and screenshots. Verify the existing CI upload action actually
delivers iOS failure artifacts when a failure occurs; local files alone do not prove
upload. Watch-only failure evidence currently needs manual collection. Never fill a
disk, erase a simulator, delete records or claim a power-loss test for this checklist.

## Release readiness assessment

**Ready to start final iOS/watchOS platform validation; not release-ready.** The source
configuration and independent integration boundaries are consistent. The blockers to
release clearance are unexecuted current Xcode builds/UI tests, uncovered critical iOS
flows and absent watch interaction evidence. A missing runtime is a recorded blocker,
not a reason to add another platform or silently pass the gate.

This review changes documentation only. No application behavior, target, workflow,
dependency or user data was changed. No software was installed; no commit, push or
remote workflow was triggered. Historical Windows test passes are not new results.
