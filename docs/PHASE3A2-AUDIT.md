# Phase 3A.2 — Pre-release audit

Audit date: 2026-11-15. Environment: Windows 11, Swift 6.4.2, PowerShell.
No commit, push, remote CI dispatch, software installation or deletion of existing
application/user data was performed. Tests clean up only their own generated fixtures.
Existing Phase 3A.1 working changes and parallel `prototypes/` design files were preserved.

## 1. Issues identified and fixes

| Finding | Severity | Change | Verification boundary |
| --- | --- | --- | --- |
| F1. Two day-segment rows of a cross-midnight session shared a global accessibility identifier. | Medium | Add the calendar-day timestamp to each row ID, keeping the session prefix. | Static review Passed; actual accessibility hierarchy Requires macOS/Xcode. |
| F2. Navigation asserted element existence without confirming the requested tab was selected. Completed-record checks verified identity but not the displayed duration. | Medium | Assert selected tab state and positive detail duration. Restoration now compares the displayed start text as well as session ID and elapsed time. A goal step must yield 29 or 31 from 30. | All eight tests retained; execution Requires macOS/Xcode. |
| F3. Settings could show an old goal after returning during a pending save: onAppear read the previous journal while the save later committed the new goal. | Medium | Synchronize the displayed draft when the committed journal goal changes. No layout or target-setting policy change. | Interleaving verified by source review; runtime regression Requires macOS/Xcode. |
| F4. A separate `simctl boot` used the state from an earlier inventory snapshot, potentially failing if another process booted the same device meanwhile. | Medium | Use the existing `bootstatus -b` boot-and-wait operation directly. | Fixture asserts one bootstatus operation; real boot Requires macOS/Xcode. |
| F5. UI failure artifacts were collected only after watchOS compilation, leaving them vulnerable to a slow watchOS build exhausting the job. | Medium | Collect/upload iOS/UI-stage diagnostics immediately after UI testing, before the preserved watchOS build. | Workflow order reviewed; real upload Requires macOS/Xcode/CI. Cancellation can still prevent upload. |
| F6. Missing regression coverage for goal changes on the same records, failed non-missing reads, invalid active snapshots, and unchanged state after rejected transitions. | Medium | Add five Swift Testing tests, including four parameterized invalid snapshots. Add three CI-script fixtures for boot-command flow, subprocess failure, and timeout logs. | Passed: 36 Swift tests and 9 Python tests. |

No verified SharedCore production behavior defect was found. Its source, Package.swift,
existing tests, WatchApp source and deployment minimums were not changed.

## 2. Review of all eight UI tests

The following are coverage conclusions from source review, not simulator test results.
All eight runtime statuses are **Requires macOS/Xcode**.

| Test | Intended user-visible behavior and assertions | Runtime status |
| --- | --- | --- |
| testLaunchShowsToday | Today appears; default goal is 30; start exists and end does not. | Requires macOS/Xcode |
| testHistoryLoads | History tab is selected; screen/add control appear; fresh namespace has no completed rows. | Requires macOS/Xcode |
| testSettingsLoads | Settings tab is selected; goal stepper appears with value 30. | Requires macOS/Xcode |
| testStartSessionShowsActiveState | Start leads to enabled end control and visible elapsed time; start disappears. | Requires macOS/Xcode |
| testEndSessionShowsInactiveState | After positive real elapsed time, end saves and start returns; timer/end disappear. | Requires macOS/Xcode |
| testCompletedSessionAppearsInHistoryAndSurvivesRelaunch | A nonempty visible row persists with its stable segment ID after terminate/launch, and its detail displays positive recorded duration. | Requires macOS/Xcode |
| testDailyGoalPersistsAfterRelaunch | One real step changes 30 to 29 or 31; save acknowledgment appears; the same goal is loaded in Today and Settings after relaunch. | Requires macOS/Xcode |
| testActiveSessionRestoresAfterRelaunch | The same active ID, displayed start time and elapsed time survive termination/relaunch; the restored session can finish. | Requires macOS/Xcode |

Identifiers supplement actual controls, displayed text and accessibility values; tests
do not read journal JSON or call model mutation methods. Stable UUIDs are an additional
restoration check, not the only assertion. History row identifiers now distinguish days.

The app's system tab/stepper hierarchy still needs runtime inspection. Tabs prefer IDs
and otherwise use the fixed Today/History/Settings order; the stepper uses its first
system child button without matching English labels. None of the tests use fixed sleeps.
Element/predicate waits are bounded at 15 seconds and scrolling at three gestures.
Real elapsed time reaching one second is a condition wait, not a time injection.

Each test gets a fresh UUID namespace. The same namespace is deliberately retained on
relaunch within that test. A dedicated test app bundle ID isolates app storage from
Debug/Release, and missing test namespaces fail before opening a journal. Production
builds do not compile test routing. No reset, validation bypass or fake persistence exists.
Test namespaces are disposable with the CI runner; old namespaces are not automatically
removed from a developer's local test-app container. Tests do not exercise app upgrading
from previous schemas, multiple-window interactions, or persistence-error alerts end to end.

## 3. Persistence and concurrency review

| Area | Review result | Evidence / limits |
| --- | --- | --- |
| Durable file location | Passed (static) | iOS resolves Application Support, not Caches/temporaryDirectory. Tests alone use unique temporary directories. |
| Atomic writes | Passed (static/API review) | Codable encoding precedes `.atomic` write. File-store actor serializes its I/O. No source changes were required. |
| Read/corruption failures | Passed (shared tests + static UI review) | Only file-not-found becomes a new journal. Bad JSON, invalid schema/state and non-missing read errors propagate. UI stays unloaded and blocks writes on load failure. |
| Failed writes | Passed for existing fixture; static rollback review Passed | The fixture proves a parent-directory creation failure is reported while original bytes remain unchanged. It does **not** simulate disk-full, denied replacement of a valid target, or power loss. |
| UI commit order | Passed (static) | Candidate snapshot is saved before replacing in-memory journal. Failure keeps the prior committed state and displays an error. Ending failure retains active timing; retry uses a later end time. Actual iOS error presentation is Not tested. |
| Repeated start/stop | Passed (shared tests + static) | MainActor/isBusy guards prevent concurrent UI transitions; journal rejects duplicates without changing state. Repeated core transitions throw rather than return success; UI treats repeated actions as no-ops. |
| Midnight/time zones/DST | Passed (shared tests) | Intersections use calendar day intervals and half-open bounds. UTC/Shanghai/Los Angeles and 23/25-hour DST days are covered. No fixed 86400-second day. |
| Goal changes | Passed (shared tests) | The same recorded seconds yield ratios 0.5/0.25/1 for goals 30/60/15. Goal changes do not alter sessions. Historical ratios intentionally use the current goal. |
| Precision/overflow | Passed (shared tests) | Sum seconds before flooring once to minutes; saturating conversions cover numeric upper bounds. Progress remains 0...1. |
| State isolation | Passed (static) | App owns a StateObject; views observe it; DaylightStore is MainActor; file I/O is in its own actor. No persistent retain cycle found. |
| Lifecycle | Requires macOS/Xcode | Wall-clock calculation, saved active state and foreground refresh are present. Actual background/foreground, kill/relaunch, alerts and file-protection behavior have not been exercised in this audit. |

Atomic writes follow [Foundation's documented auxiliary-file replacement contract](https://developer.apple.com/documentation/foundation/nsdata/writingoptions/atomic).
That API review is not a local crash/power-loss experiment. The file-store actor is not
a cross-process file lock; the current app uses one shared store. No external writer,
manual file deletion or hardware-failure recovery guarantee is claimed.

Minimum deployment targets remain iOS 17/watchOS 10. Source review found no newly introduced
higher-version UI API. Actual SwiftUI/XCTest availability and type checking still require
Xcode; Windows only builds Foundation-based SharedCore. Manual wall-clock changes still
affect elapsed time, as documented in Phase 3A.

## 4. CI/CD review

Source-level consistency checks Passed for all eight guards: deployment versions,
UI test target-to-app association, UITesting configuration, isolated app bundle ID,
signing disabled on all three simulator commands, distinct UI DerivedData/result
paths, preservation of eight UI tests, and inclusion of results/logs in artifacts.

- Existing standard `xcode-27` runner and `/Applications/Xcode_27.1.app` selection remain.
- Debug app builds and UITesting app bundle ID/configuration are separated. UI test
  target is `bundle.ui-testing`, `TEST_TARGET_NAME` is DaylightIOS, and its scheme
  includes the correct app/test targets. Tests and command-line parallelism are disabled.
- SharedCore tests, iOS Simulator build and watchOS Simulator build commands remain.
  All simulator commands use `CODE_SIGNING_ALLOWED=NO`.
- Discovery filters installed available iOS 17+ runtimes, available iPhone device types,
  and Xcode-eligible destinations. No model, exact runtime version, download or erase is assumed.
- No eligible runtime/device is an explicit nonzero failure, never a successful skip.
  Subprocess failure/timeout output is retained; mocked fixture tests cover those paths.
- UI xcodebuild uses pipefail, bounded test/step/job allowances, separate DerivedData
  and an xcresult bundle. iOS/UI-stage failures collect screenshots, inventory, boot,
  destination and test logs before watchOS compilation. XCTest screenshots and predicate
  failure hierarchy attachments are configured. Real upload remains unexecuted here.
- Dependencies added by Phase 3A.1 are official GitHub actions and Python/Ruby standard
  libraries. Existing Homebrew XcodeGen installation remains; no extra software was installed.

Remaining reproducibility risks: runner is a preview label; installed Xcode paths can
change; Homebrew XcodeGen and major action tags are mutable. The preflight/generation
steps expose failures, but installed tool/runtime availability cannot be inferred from
an earlier successful build. Cancellation or an exhausted job timeout can prevent
artifact collection/upload. iOS 17/watchOS 10 runtime behavior is not covered merely
by compiling against those minimum deployment settings on a newer SDK.

## 5. Actual validation results

| Validation | Status | Actual result |
| --- | --- | --- |
| Windows Swift 6.4.2 `swift build` in SharedCore | Passed | Exit 0. |
| Windows Swift 6.4.2 `swift test` in SharedCore | Passed | Exit 0; 36 Swift Testing tests passed, including all original 31. |
| Python CI/simulator fixtures | Passed | Exit 0; 9 standard-library unittest tests passed. No xcrun was invoked on Windows. |
| `git diff --check` | Passed | No whitespace errors; Git reports normal LF/CRLF notices. |
| Static YAML configuration consistency | Passed | Eight source-level guards plus manual review of structure/commands; not a full YAML parser. |
| Failure artifact ordering guard | Passed | Upload step precedes the preserved watchOS build. |
| Full YAML grammar/parser validation | Not tested | No local YAML parser was available; no parser/software was installed. Runner's Ruby YAML parse is configured but was not executed locally. |
| XcodeGen generation / generated scheme validation | Requires macOS/Xcode | Not run in this audit. |
| iOS/watchOS Xcode builds and all eight UI tests | Requires macOS/Xcode | Not run in this audit; earlier phase CI success does not validate these changes. |
| Real simulator discovery/boot and artifact upload | Requires macOS/Xcode | Only selection/command flow and failure logging were fixture-tested locally. |
| iOS persistence-error UI, locked-device behavior, disk-full/power-loss tests | Not tested | No device/simulator fault injection performed. |

No executed validation remains Failed. An unexecuted check is not recorded as Passed.

## 6. Remaining gates and commit/push recommendation

The local changes are ready for focused human review and a user-authorized validation
commit/push to obtain CI results. They are **not cleared for release or Phase 3B**.
Before that approval, the next macOS run must pass actual YAML parsing, XcodeGen
generation, both builds, simulator boot and all eight UI tests. Failure artifacts must
be inspected if a test fails. Tab/stepper accessibility exposure, the Settings save
interleaving, foreground restoration and iOS persistence-error behavior need runtime
verification. No such run was triggered by this audit.

Large-history performance is unprofiled: Today recomputes over in-memory sessions each
second and the journal rewrites the full snapshot on save. Runtime memory profiling and
app performance benchmarks were not performed. Backup/migration/export features remain out
of scope. These observations did not justify refactoring or changing business behavior.

The inherited `example()` test is still an empty package-template placeholder. It is
included in the 36-test runner count but provides no behavioral coverage; it was not
deleted or presented as evidence for any specific audit guarantee.

Audit edits: DaylightUITests.swift; iOS History/Today/Settings accessibility and goal
synchronization; simulator selector and its fixtures; CI artifact ordering; new
PreReleaseAuditTests.swift; this report; Phase 3A.1 documentation clarification and
README link. SharedCore production sources, WatchApp, package settings and deployment
targets remain unchanged. Existing untracked prototypes were not audited or altered.
