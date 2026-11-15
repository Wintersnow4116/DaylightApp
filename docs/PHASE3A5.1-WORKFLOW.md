# Phase 3A.5.1 — iOS and watchOS Validation Workflow

## Scope and implementation

Daylight remains native iOS and watchOS only. macOS is the GitHub Actions build/test
host, not an application target. No application code, visual design, deployment
minimum, package business logic, UI test or WatchApp file changed in this phase.
All pre-existing working changes and prototypes were preserved.

The existing `.github/workflows/build.yml` already had `workflow_dispatch`. It is
retained alongside push/pull_request triggers. The workflow is now named
**Validate Daylight iOS and watchOS**, still using one standard `xcode-27` runner
and `/Applications/Xcode_27.1.app/Contents/Developer`. No larger runner or unrelated
platform job was added. The job limit is 60 minutes.

## Exact automated steps and expected results

| Order | Workflow step | Expected result / evidence |
| --- | --- | --- |
| 1 | Check out source | Requested revision checked out; credentials are not persisted. |
| 2 | Prepare validation evidence | Create ignored result, log and settings directories. |
| 3 | Inspect Xcode and Swift toolchain | Record Xcode/Swift/SDK versions; parse the existing tools-6.4 package into `build/validation/package.json`. Incompatible/missing tools fail explicitly. |
| 4 | Test SharedCore | Existing suite compiles/runs on the host; currently 44 Swift Testing tests, including the documented inherited empty placeholder. Preserve the test log. |
| 5 | Validate configuration syntax and CI script fixtures | Ruby parses project/workflow YAML and exports the project spec as JSON; Python executes the existing simulator fixtures and new integration/workflow guards (currently 20 tests). |
| 6 | Install XcodeGen | Retain the pre-existing macOS Homebrew install-if-missing behavior; record the generator version. No Windows software installation occurs. |
| 7 | Generate Xcode project | Generate from the existing project.yml and record the scheme list. |
| 8 | Verify independent SharedCore integration and resolved settings | Verify local package/product wiring and six Xcode-resolved app/configuration combinations: Debug, Release and UITesting for both apps. Record JSON, stderr and validator output. |
| 9 | Build iOS Simulator Debug | DaylightIOS, Debug, iphonesimulator, generic iOS Simulator; unsigned build succeeds. |
| 10 | Build iOS Simulator Release | DaylightIOS, Release, iphonesimulator, generic iOS Simulator; unsigned build succeeds. |
| 11 | Build watchOS Simulator Debug | DaylightWatch, Debug, watchsimulator, generic watchOS Simulator; unsigned independent build succeeds. |
| 12 | Build watchOS Simulator Release | DaylightWatch, Release, watchsimulator, generic watchOS Simulator; unsigned independent build succeeds. |
| 13 | Discover and boot an available iPhone simulator | Select an installed available iOS 17+ iPhone eligible for Xcode's UI-test scheme and wait for boot. No fixed model/runtime download. Missing compatible devices/runtimes produce an explicit failed discovery step, not a successful skip. |
| 14 | Run iOS Simulator UI tests | Execute the unchanged DaylightUITests suite using UITesting on the selected UDID; expect all eight existing tests to pass, with an xcresult bundle. |
| 15 | Collect simulator diagnostics | Best-effort final inventory, tool version, screenshot and recent app logs on success or failure, unless cancelled. |
| 16 | Preserve validation results and diagnostics | Always attempt to upload logs, configuration evidence, xcresult and XCTest diagnostic files. Retain seven days. |
| 17 | Summarize automated checks and manual watchOS requirements | Always attempt a job-summary table containing actual step outcomes, upload outcome and explicit unexecuted watch runtime acceptance items. |

The four build steps are individually gated on successful project generation and
non-cancellation, not on the preceding app build. A failed Debug build does not
silently prevent the remaining Release/watchOS checks. The integration check also
remains a failing job gate if it fails; subsequent successful builds cannot erase
that failure. There is no `continue-on-error` masking of required validation.

All shell build/test pipelines use `set -euo pipefail`, so `tee` cannot hide a failed
xcodebuild or Swift test. Each app build has a 10-minute step limit, settings checks
10 minutes, simulator discovery 10 minutes, UI tests 20 minutes and diagnostics
3 minutes. Xcode's per-test allowances remain 120 seconds default / 180 seconds maximum.

## SharedCore integration validation

`scripts/ci/validate_integration.py` consumes the YAML-exported project spec, actual
`swift package dump-package` output and Xcode settings JSON. It checks:

- Exactly the existing two native application targets; no macOS/other app target.
- SharedCore is the local package path and exports the DaylightCore library target.
- Each app independently declares the DaylightCore product dependency and its own
  build scheme; neither app depends on the other.
- Debug/UITesting stay debug-type, and Release stays release-type.
- All six resolved settings preserve iOS 17.0 or watchOS 10.0 as appropriate.
- Normal versus UITesting app IDs and the test-only storage flag remain correctly
  separated; simulator signing is disabled.
- The existing iOS UI-test target, app association and UITesting test action remain wired.

The four actual app builds additionally compile/link the shared product for their
respective simulator SDKs. Source/settings checks alone are not reported as successful
linking. A separate DaylightCore.framework file is not required: SwiftPM can link
the automatic library statically.

## Build commands and output paths

Each app build executes the equivalent of:

```bash
xcodebuild -project DaylightApp.xcodeproj -scheme <scheme> \
  -configuration <configuration> -sdk <sdk> -destination '<destination>' \
  -derivedDataPath <derived-data> CODE_SIGNING_ALLOWED=NO build
```

| Scheme / configuration | SDK / destination | DerivedData | Build log |
| --- | --- | --- | --- |
| DaylightIOS / Debug | iphonesimulator / generic/platform=iOS Simulator | build/iOS | build/validation/iOS-Debug.log |
| DaylightIOS / Release | iphonesimulator / generic/platform=iOS Simulator | build/iOS-Release | build/validation/iOS-Release.log |
| DaylightWatch / Debug | watchsimulator / generic/platform=watchOS Simulator | build/watchOS | build/validation/watchOS-Debug.log |
| DaylightWatch / Release | watchsimulator / generic/platform=watchOS Simulator | build/watchOS-Release | build/validation/watchOS-Release.log |

The unchanged iOS UI-test invocation uses `-scheme DaylightUITests -configuration UITesting`,
the selected `platform=iOS Simulator,id=<UDID>`, disabled signing and parallelism,
`build/UITests` DerivedData and `build/TestResults/DaylightUITests.xcresult`.

## Evidence retention

The official `actions/upload-artifact@v7` action now runs with `always()`, retaining
success evidence as well as failures under:

```
daylight-validation-<run_id>-<run_attempt>
  build/validation/                 # tool versions, manifest/spec, settings, test/build logs
  build/TestResults/DaylightUITests.xcresult
  build/UITests/Logs/Test/
  build/ui-diagnostics/             # selected device, destinations, boot/final-state logs, screenshot
```

No built app binaries or full DerivedData tree are uploaded. XCTest attachments remain
inside the result bundle. The final screenshot is named `simulator-final.png`; its
existence is not proof that an interaction passed. Early failures may produce only
partial evidence and no xcresult. Missing files emit a warning; that does not turn
a failed build/test into success. Cancellation, runner loss or an exhausted job timeout
can prevent final upload/summary even with `always()`.

## Manual trigger

After the user reviews and publishes the workflow and scripts:

1. Ensure the workflow exists on the repository's default branch so GitHub exposes
   manual dispatch, and the selected revision includes the new scripts.
2. Open **Actions → Validate Daylight iOS and watchOS → Run workflow**.
3. Choose the branch/revision to validate, then select **Run workflow**.
4. Inspect every step's actual outcome and the `daylight-validation-...` artifact.

No inputs are required. `workflow_dispatch` was already present and is intentionally
retained, not described as newly added. No commit, push or dispatch was performed here.

## Manual watchOS acceptance and remaining gaps

The workflow automates **watchOS Debug/Release compilation only**. It does not install,
launch or tap the watch app. Those remain distinct runtime checks:

- Select an available Xcode-compatible watchOS 10+ simulator; install and launch the
  built watch app, recording runtime/UDID and any failure diagnostics.
- Verify the initial 0/30 minutes, the existing five-minute button, remaining time,
  target completion and a completion ratio capped at 100% after exceeding the goal.
- Verify the documented in-memory reset after process termination/relaunch.
- Check small-screen/large-text layout, dark appearance and basic accessibility.

Use the exact watch runtime commands in [the Phase 3A.4 checklist](PHASE3A4-READINESS.md).
There is no interactive Mac available in the current setup. A headless runner's build
or process ID does not satisfy button/visual acceptance; a future narrowly scoped watch
UI-test implementation or separately available interactive validation is needed.
No synchronization or paired-installation claim is made.

The additional iOS manual-entry, error-UI, pending-save navigation, background/foreground,
rapid-tap, midnight/timezone and accessibility gaps from Phase 3A.4 also remain. This
phase changes CI coverage, not product behavior or the set of eight UI tests.

## Actual local validation and readiness

| Check | Actual local result |
| --- | --- |
| Windows `swift build`, SharedCore | Passed, exit 0. |
| Windows `swift test`, SharedCore | Passed, exit 0; 44 Swift Testing tests. |
| Actual package manifest inspection | Passed: DaylightCore exports target DaylightCore with regular package-target type. |
| Python CI tests | Passed: 20 tests, preserving the previous nine fixtures. |
| Workflow run-block Bash syntax | Passed using installed Git Bash with `-n`; no workflow command executed. |
| `git diff --check` | Passed. |
| Full YAML parsing, XcodeGen, six actual Xcode settings and four simulator builds | Not executed locally; require the macOS CI host. Local fixture/source guards are not a YAML parser. |
| Existing eight iOS UI tests / real discovery and upload | Configured, not executed on Windows. |
| watchOS install/launch/interaction | Not automated; not executed. |

No Windows software was installed. Application/WatchApp/SharedCore behavior, deployment
targets, existing tests and unrelated changes remain intact. No commit, push or remote
workflow dispatch occurred. This is ready for a user-authorized CI validation run,
not a claim of successful platform validation or release readiness.
