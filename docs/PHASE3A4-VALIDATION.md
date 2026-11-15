# Phase 3A.4 — Native iOS and watchOS validation plan

The current source-level readiness findings, CI gaps and exact macOS command
checklist are in [Phase 3A.4 readiness review](PHASE3A4-READINESS.md).

The execution phase is named [Phase 3A.5 — Final iOS & watchOS Validation](PHASE3A5-VALIDATION.md).
Use GitHub Actions macOS runners for Xcode builds and simulator tests of these two
applications. macOS is only their build/testing host: no macOS app, target, interface
or distribution configuration is authorized.

## 1. Product scope

Daylight supports exactly two native application platforms: **iOS and watchOS**.
SharedCore is the existing shared Swift package, exposing the DaylightCore product
for business logic and data models. It is not a third application platform.

Preserve iOS 17 and watchOS 10 minimum deployment targets, the separate SwiftUI app
targets, XcodeGen configuration, and current storage/model architecture. A concrete,
documented defect is required to justify an architectural or deployment change.

Explicitly excluded: Android applications, web applications, cross-platform frameworks,
additional desktop applications (including macOS or Windows apps), and unrelated
platform support, deployment pipelines or release deliverables. The active browser
prototype in `prototypes/daylight-web/` is an intentional design/interaction reference
for the native product, not a shipping web application. Its parallel implementation
and review continue independently of this native validation gate; preserve its files,
tracking and development setup under the [collaboration boundaries](COLLABORATION-BOUNDARIES.md).

Windows remains a development host capable of checking SharedCore. macOS is the host
required for Xcode and Apple Simulator validation. Neither host is an application target.
Host-side tooling checks support iOS/watchOS delivery and do not expand product scope.

## 2. Integration boundaries reviewed

| Component | Current boundary | Validation obligation |
| --- | --- | --- |
| SharedCore / DaylightCore | Foundation-based session/journal models, calendar-day summaries, progress, storage interfaces and file-store actor. No SwiftUI dependency or platform UI ownership. | Run the existing Swift Testing suite on the Xcode host; compile the shared product through both app targets. Preserve version-1 data validation and ordinary I/O failure protections. |
| iOSApp / DaylightIOS | SwiftUI Today, History and Settings; MainActor observable store; Application Support file resolution and persistence integration. Depends on the local DaylightCore product. | Build for iOS Simulator and exercise actual iPhone Simulator launch, UI interactions, persistence and lifecycle behavior. |
| WatchApp / DaylightWatch | Separate SwiftUI watch-only application. Uses DaylightProgress in local in-memory state. Depends on the same local DaylightCore product. | Build for watchOS Simulator, then install/launch on an available compatible watchOS simulator and check its existing progress interaction. |
| iOS ↔ watchOS | No current transport, paired installation, shared live store or synchronization. The iPhone journal is not the watch app's data source. | Validate each app independently. Do not treat successful builds, simulator pairing, or matching model types as proof of synchronization. |

The existing watch app is an in-memory progress demonstration. This plan does not
extend iPhone persistence claims to watchOS or introduce WatchConnectivity.

## 3. Apple-native technology evaluation

Use the existing SwiftUI interfaces, Foundation/Codable storage, Swift Concurrency,
and XCTest/Swift Testing for their established requirements. Evaluate another
Apple-native technology only when an actual product requirement and a gap in the
current implementation justify it. Record the requirement, supported OS availability,
permissions, lifecycle/data implications and validation plan before adoption.

This scope update authorizes no new synchronization, cloud storage, sensor, HealthKit,
WatchConnectivity or background-execution integration. No unverified watch ambient-light
API is assumed. There is no framework migration, new app target or deployment pipeline.

## 4. Xcode simulator validation matrix

| Application | Existing scheme / configuration | Required SDK and destination | Remaining evidence |
| --- | --- | --- | --- |
| iOS | DaylightIOS / Debug | iphonesimulator; `generic/platform=iOS Simulator` for compilation | Fresh successful app build incorporating Phase 3A.3 changes. |
| iOS UI testing | DaylightUITests / UITesting | iphonesimulator; `platform=iOS Simulator,id=<available iPhone UDID>` | All eight existing UI tests execute and pass on a booted compatible iPhone simulator; retain xcresult and failure diagnostics. |
| watchOS | DaylightWatch / Debug | watchsimulator; `generic/platform=watchOS Simulator` for compilation | Fresh successful independent watch app build linked to current SharedCore. |
| watchOS runtime | DaylightWatch / Debug | watchsimulator; `platform=watchOS Simulator,id=<available Watch UDID>` | Actual install/launch and existing progress-button smoke check, with simulator/runtime IDs and observed results recorded. No watch UI test target currently exists. |

Keep `CODE_SIGNING_ALLOWED=NO` for simulator builds/tests. Resolve installed available
runtimes/devices using `xcrun simctl`, and check Xcode-eligible destinations for each
scheme. Do not assume a particular iPhone/Watch model or OS runtime exists. Select
an iOS 17+ or watchOS 10+ runtime respectively; a newer installed runtime does not
prove behavior on the minimum OS version. Record exactly which versions ran.

Boot the selected compatible device as necessary and wait for readiness. If no
eligible runtime/device is installed, report that platform check as **Blocked**;
do not silently substitute a host platform or claim successful runtime execution.
Use already available tools/runtimes for this validation plan. No installation or
remote execution is authorized by this documentation update.

The current workflow already compiles both simulator targets, selects/boots an
iPhone, and configures the iOS UI suite. It does **not** currently automate watchOS
install/launch or interaction testing. Those remain planned platform checks; this
documentation does not add or claim execution of a watch runtime test step.

## 5. Remaining iOS validation

1. Parse project/workflow YAML, generate the existing Xcode project and confirm test
   target-to-app association and local DaylightCore linking.
2. Run the current SharedCore suite with the Xcode toolchain, including injected I/O
   error, corruption, missing-directory, repeated-I/O and large-history regressions.
3. Build the normal iOS app and the separate UITesting configuration. Confirm the
   test bundle ID and UUID data namespace cannot touch production records.
4. Execute all eight UI tests: Today launch, History, Settings, start, stop, completed
   history/relaunch, persisted goal change, and restored active session.
5. Verify the Phase 3A.3 Settings acknowledgment fix, including leaving/returning
   while a save is pending; verify committed values and history ratios are consistent.
6. Exercise foreground/background and actual terminate/relaunch recovery, repeated
   taps, midnight/timezone attribution, and accessibility identifiers on the simulator.
7. Verify persistence-error feedback and rollback with controlled storage injection.
   Do not describe injected errors as real disk-full or power-loss verification.
8. Check current layouts with dark mode, large Dynamic Type and VoiceOver. Confirm
   real xcresult, screenshot and diagnostic collection if runtime/UI checks fail.

## 6. Remaining watchOS validation

1. Confirm the independent watch target still links DaylightCore and does not compile
   iOS UI/store code or depend on the iPhone app target.
2. Build the watch app against watchsimulator with its watchOS 10 minimum unchanged.
3. Discover an available Xcode-compatible watchOS simulator and record its UDID/runtime.
4. Install and launch the watch app; verify the existing default 30-minute progress,
   increase-by-five-minutes interaction, remaining duration and capped completion.
5. Check existing small-screen, large-text, dark-mode and basic accessibility behavior.
6. Confirm expectations remain independent: the watch's in-memory demo can reset on
   relaunch; iPhone journal restoration and cross-device synchronization are not
   claimed for it. Pairing a simulator is not synchronization acceptance evidence.

## 7. Evidence and readiness

| Validation evidence | Status at this scope update |
| --- | --- |
| Repository configuration and integration-boundary review | Reviewed statically for this document. |
| SharedCore Windows build and 44 Swift tests; nine CI fixtures | Previously passed in Phase 3A.3; not rerun for this documentation-only change. Includes the documented inherited empty test. |
| Fresh Xcode builds for both current app targets | Requires macOS/Xcode; not run by this scope update. Earlier phase success is historical evidence only. |
| All eight iOS UI tests / real simulator lifecycle | Configured but not executed by this scope update. |
| watchOS simulator install/launch/interaction | Planned, not executed; not currently automated by the workflow. |
| Full YAML parse, actual failure-artifact upload and platform-specific error UI | Still require execution/evidence as described above. |

Phase 3A remains ready for final **iOS/watchOS platform validation**, not cleared
for release. Acceptance requires distinct build and runtime evidence for both
supported apps, explicit disposition of unavailable runtimes and recorded remaining
limitations. No Android, web or desktop acceptance gate is part of this plan.

This update modifies documentation only. It changes no application code, SharedCore
behavior, deployment target, app architecture or workflow. No software installation,
commit, push or remote workflow dispatch was performed.
