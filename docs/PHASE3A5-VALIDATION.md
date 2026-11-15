# Phase 3A.5 — Final iOS & watchOS Validation

The current automated workflow and evidence paths are documented in
[Phase 3A.5.1 — iOS and watchOS Validation Workflow](PHASE3A5.1-WORKFLOW.md).

## Purpose and scope

Execute final validation of Daylight's two supported native applications: **iOS and
watchOS**. SharedCore remains their shared business-logic and data-model package.
Preserve the existing architecture and minimum deployment targets of iOS 17 and
watchOS 10.

**macOS is exclusively a build and testing environment.** Use GitHub Actions macOS
runners to run Xcode, generate the existing project, build the iOS/watchOS simulator
targets and execute simulator tests. A macOS runner, host-side package test or
Simulator tool does not imply a macOS product.

Do not create a macOS application, target, interface, desktop distribution, signing
or packaging configuration. Do not introduce Android, web, cross-platform or other
desktop products or pipelines. The active `prototypes/daylight-web/` design reference
remains maintained by the parallel UI task. It is outside this native simulator gate,
not excluded from ongoing design work. Preserve it under the
[collaboration boundaries](COLLABORATION-BOUNDARIES.md).

## Execution plan on GitHub Actions macOS runners

Use the existing standard runner and Xcode configuration; no larger runner or new
infrastructure is introduced by this correction. The commands and expected results
in the [Phase 3A.4 readiness review](PHASE3A4-READINESS.md) form the technical checklist.
Run the applicable build/test commands in the existing macOS CI job after a separately
authorized validation run. Do not depend on an interactive Mac being available.

| Check | Application or shared layer under validation | Required evidence |
| --- | --- | --- |
| Project generation and resolved build settings | Existing iOS/watchOS targets | Correct independent SharedCore dependencies; iOS 17/watchOS 10 minimums across configurations. |
| SharedCore Swift tests | Shared business logic used by both apps | Actual suite results from the CI host. These are host-side tests, not a macOS application build. |
| DaylightIOS Debug/Release builds | iOS Simulator / iphonesimulator | Both configurations are now scheduled by Phase 3A.5.1; actual independent successful builds with signing disabled still require a CI run. |
| DaylightUITests / UITesting | An installed, available, Xcode-eligible iPhone simulator | All eight current UI tests execute, with isolated data and xcresult evidence. Missing critical flows identified in Phase 3A.4 must receive an explicit validation disposition. |
| DaylightWatch Debug/Release builds | watchOS Simulator / watchsimulator | Successful independent watch builds linked to SharedCore, with signing disabled. |
| Watch install, launch and interaction | An installed, available, Xcode-eligible watchOS simulator | Actual install/launch and existing progress-control assertions; a build or process ID alone is insufficient. |

Discover installed runtimes/devices dynamically. If a compatible simulator is absent,
report that platform check as **Blocked**, not Passed. Record actual Xcode/SDK/runtime
versions and UDIDs; testing a newer runtime does not establish minimum-OS behavior.
Retain xcresult, screenshots and diagnostic logs for observed failures.

## Known execution gaps

Phase 3A.5.1 configures both apps' Debug and Release simulator builds, resolved SharedCore
integration checks, iPhone discovery and the existing iOS UI tests. It preserves results
on success and failure. These are configured checks, not newly observed platform results.
The workflow still does not automate watchOS install/launch/interaction checks.

The interactive watch smoke-check instructions retained in Phase 3A.4 are supplemental
guidance only. They are not a substitute for the required macOS-runner simulator
validation and must not be reported as executed on a headless runner. Watch interaction
needs a narrowly scoped, separately authorized simulator-test implementation before
this acceptance gate can be satisfied in the current Windows-plus-CI setup.

Do not assume paired installation, shared live data or synchronization between the
apps. The watch app remains an independent in-memory progress demonstration.

## Status and completion criteria

This correction performs no builds, simulator execution or remote workflow dispatch.
Historical local test passes remain historical; Phase 3A.5 has no newly executed
validation result. Its official name is **Final iOS & watchOS Validation**.

Completion requires actual iOS and watchOS build/runtime evidence from the macOS
validation environment and documented resolution or acceptance of the remaining
Phase 3A.4 coverage gaps. Until then, Daylight is ready to pursue platform validation,
not cleared for release. No macOS product deliverable is part of completion.
