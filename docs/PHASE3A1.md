# Phase 3A.1 — Simulator runtime and UI testing

## Scope

The existing `DaylightIOS` app target remains iOS 17+, normally installed as
`org.example.daylight.ios`. Today, History and Settings retain their existing layout
and behavior. SharedCore and WatchApp are unchanged.

`project.yml` now declares an iOS XCTest UI test target and shared scheme named
`DaylightUITests`, dependent on `DaylightIOS` with `TEST_TARGET_NAME: DaylightIOS`.
The existing Debug and Release configurations remain; the new debug-type
`UITesting` configuration is used only for runtime testing.

## Test data safety

Only `UITesting` compiles `DAYLIGHT_UI_TESTING` into the iOS app, and installs that
app under the separate ID `org.example.daylight.ios.uitesting`. The tests explicitly
launch this ID, so accidentally selecting Debug does not launch the production app.

Each test supplies a fresh UUID in `DAYLIGHT_UI_TEST_NAMESPACE`. Its journal is
stored in that test app's Application Support directory:

```
DaylightAppUITests/<UUID>/journal-v1.json
```

The same namespace is retained across terminate/launch inside a test. Nothing is
reset on launch. Missing or invalid namespaces fail before opening any journal;
there is no fallback to the normal app's records. UUID validation prevents paths
from being supplied through the namespace. Debug/Release ignore this mechanism.

The real DaylightJournal validation, serialized file I/O and atomic persistence
are used. No time, storage or validation bypass is introduced. Tests do not delete
existing records or erase simulators. Test files live only in the disposable test
app's container; GitHub-hosted runners discard that container with the job.
Repeated local Mac runs may leave old test namespaces in the test app's container.

## Eight independent UI tests

Every test launches with its own fresh namespace; random execution order is enabled.

1. Launch and verify Today, default goal 30 and inactive state.
2. Navigate to History and verify it loads with no completed records.
3. Navigate to Settings and verify its goal control.
4. Start and verify the saved active state and elapsed-time display.
5. End a positive-duration session and verify the saved inactive state.
6. Verify the completed record appears in History, retains the same record ID after
   relaunch, and opens its detail screen.
7. Change and save the goal through the system stepper; relaunch and verify it in
   both Today and Settings.
8. Relaunch during a session and verify the same active session ID and elapsed
   time are preserved, then finish the session.

Queries use accessibility identifiers and explicit accessibility values. The
system stepper's first child button changes the goal without matching a localized
Increment/Decrement label; the test accepts either direction from 30. Tab navigation
prefers identifiers and falls back to the existing fixed tab order when SwiftUI
does not forward tabItem identifiers to UIKit. No visible English text is matched.

Element/predicate waits are bounded at 15 seconds; interaction helpers allow up to
three scroll gestures for small iPhone screens. Ending waits for the actual timer
to show at least one second, without fixed sleeps. Tests are MainActor-isolated
methods and avoid actor-isolation changes to XCTest lifecycle overrides.

## CI changes

The existing standard `xcode-27` runner and Xcode 27.1 `DEVELOPER_DIR` are preserved.
No larger runner, simulator runtime download, signing service or device is needed.

- Preserve `swift test`, XcodeGen installation/generation, and both existing Debug
  iOS Simulator and watchOS Simulator build commands.
- Use maintained official `actions/checkout@v7` and `actions/upload-artifact@v7`;
  checkout does not persist credentials.
- Parse both YAML files with the runner's built-in Ruby YAML parser, then run the
  Python standard-library simulator-selection fixture tests. XcodeGen separately
  validates the project spec when generating the actual project.
- Run `xcrun simctl list runtimes --json` and `list devices --json` to inventory
  installed runtimes and devices. Intersect available iOS 17+ iPhones with the
  eligible UDIDs from `xcodebuild -showdestinations` for DaylightUITests.
- Select the newest eligible installed OS, preferring an already booted device at
  that version. No device model or runtime version is hard-coded.
- Boot the chosen device if needed and wait with `simctl bootstatus -b`, with
  bounded subprocess timeouts. Failure is an explicit failed step, not a skip.
- Run `xcodebuild test -scheme DaylightUITests -configuration UITesting` on its
  actual UDID, with `CODE_SIGNING_ALLOWED=NO` and simulator parallelism disabled.
- Keep UI DerivedData separate at `build/UITests` and results at
  `build/TestResults/DaylightUITests.xcresult`. Pipe output through `tee` with
  `pipefail`, preserving failures.
- Job timeout: 50 minutes. Discovery/boot: 10 minutes. UI test step: 20 minutes.
  Xcode test allowances: default 120 seconds, maximum 180 seconds per test.
- On iOS/UI-stage failure, collect simulator inventory, selected device, boot/destination logs,
  Xcode version, app logs and a simulator screenshot when possible. Upload those,
  the xcresult and DerivedData test logs as a seven-day artifact. XCTest also
  captures failure screenshots, and predicate failures attach the accessibility tree.
- Phase 3A.2 moves this collection/upload before the watchOS build to protect the
  UI failure evidence from a slow later build; watchOS-only failure is still reported
  by its build step's normal Actions log.
- The watchOS build still runs after iOS/UI failures if generation succeeded and
  the job has not been cancelled. Cancelled jobs or exhausted job timeouts may
  prevent final diagnostic collection.

If no compatible runtime or Xcode-eligible available iPhone exists, selection
fails with a clear error. The inventory and destination logs explain the blocker;
no successful UI-test result is reported without running the tests.

## Validation performed on Windows

- SharedCore `swift build`: passed (exit 0).
- SharedCore `swift test`: all 31 Swift Testing tests passed (exit 0).
- Simulator selector: all six Python fixture tests passed. These test selection
  logic against synthetic inventory, not a real Simulator.
- Configuration and UI source reviewed statically; `git diff --check` passed.
- No local YAML parser is available (PyYAML probe returned `None`). No parser was
  installed. YAML parsing and actual XcodeGen validation are configured in CI but
  have not run for this change.

No Xcode, simulator, UI test runner or new macOS build was run on Windows. No push
or remote workflow was triggered. The next macOS run must validate UI-test Swift
compilation, generated target/scheme wiring, accessibility hierarchy, stepper/tab
behavior and simulator execution. Fifteen-second UI waits may need tuning if the
runner is unusually slow; system accessibility structure can vary by iOS version.

For an existing compatible Mac, reproduce after generating the project:

```bash
xcodegen generate --spec project.yml
export GITHUB_OUTPUT="$(mktemp)"
python3 scripts/ci/select_simulator.py --minimum-ios 17.0
SIMULATOR_ID="$(sed -n 's/^udid=//p' "$GITHUB_OUTPUT")"
mkdir -p build/TestResults
xcodebuild -project DaylightApp.xcodeproj -scheme DaylightUITests \
  -configuration UITesting -sdk iphonesimulator \
  -destination "platform=iOS Simulator,id=$SIMULATOR_ID" \
  -derivedDataPath build/UITests \
  -resultBundlePath "build/TestResults/DaylightUITests-$(date +%s).xcresult" \
  -parallel-testing-enabled NO CODE_SIGNING_ALLOWED=NO test
```

Official configuration references:

- [XcodeGen project spec](https://github.com/yonaskolb/XcodeGen/blob/master/Docs/ProjectSpec.md)
- [Checkout action](https://github.com/actions/checkout)
- [Upload artifact action](https://github.com/actions/upload-artifact)
