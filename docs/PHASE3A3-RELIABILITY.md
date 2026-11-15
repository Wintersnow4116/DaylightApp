# Phase 3A.3 — Persistence reliability and release readiness

Date: 2026-11-15. Local environment: Windows 11, PowerShell, installed Swift 6.4.2.

## 1. Initial review and verification of previous conclusions

Before editing, the Phase 3A.2 audit, complete tracked working diff, staged diff
(empty), untracked-file inventory, storage implementation, existing storage/audit
tests, all eight UI tests, Today/History/Settings code, XcodeGen spec, workflow and
CI scripts were inspected. The working tree already contained Phase 3A.1/3A.2
changes and a parallel browser design prototype. Those changes were preserved; prototype
contents are outside this persistence review and were not modified.

| Previous audit finding | Verification from current implementation | Conclusion |
| --- | --- | --- |
| F1: unique history segment identifiers | IDs include session UUID and the absolute start of the represented calendar day. | Present. Stable for the same day/session; changing time zone intentionally changes grouping. Actual accessibility exposure still requires Xcode. |
| F2: stronger UI assertions | Tests assert selected tabs, positive saved duration, one-minute goal changes, restored ID/start text and elapsed time. | Present. All eight remain configured; none were executed on Windows. |
| F3: Settings synchronization | The committed-goal observer updates the draft. However, its resulting draft-change observer unconditionally cleared the Boolean save acknowledgment. | The value-sync fix was present but introduced an acknowledgment race. Corrected in this phase. |
| F4: simulator boot race | Selector uses one `bootstatus -b` operation, not a separate boot based on stale inventory. | Present; the command-flow fixture passed locally. Real simulator behavior remains unexecuted. |
| F5: failure artifact ordering | UI diagnostics/upload precede watchOS compilation. | Present; ordering and build commands checked statically. Actual upload remains unexecuted. |
| F6: additional regressions | All five audit tests and nine Python fixture tests are present. | Existing tests preserved and included in this phase's executed suites. |

The prior write-failure test did not fail replacement at the valid journal's
destination: it tried a child path beneath an existing regular file. That test is
retained as a directory/path failure check, not proof of replacement rollback.
Another safety gap was that a new low-level file store could save without first
validating an unreadable or corrupt existing journal; the UI prevented that path,
but the storage API itself did not.

No additional verified regression was found in the audit's boot/artifact changes.
This is a source/fixture conclusion, not proof of Apple Simulator execution.

## 2. Changes implemented

### Storage boundaries and ordinary write failures

- Added `DaylightJournalStorage`, a Sendable async load/save interface. The existing
  file-store actor implements it, and the MainActor iOS store accepts an optional
  injected implementation. Normal app construction still resolves Application
  Support and creates the same production file store.
- Added `DaylightJournalFileAccess`, a small synchronous, Sendable file-operation
  boundary for deterministic read/directory/replacement error injection.
- Its production implementation still uses Foundation `Data(contentsOf:)`, recursive
  directory creation, and `Data.write(options: .atomic)`. There is no new database,
  file schema, staging format, background service, backup file, or third-party dependency.
- A fresh file store validates the existing journal before its first save. A missing
  file is valid initial state; malformed, incomplete, unsupported, or unreadable data
  prevents a blind replacement. A failed read or write invalidates that validation,
  so retry must validate again. Successful loads remain read-only.
- Successful save/load behavior, version-1 Codable data, session IDs, goal policy,
  precision and calendar attribution remain unchanged. The deliberately stricter
  behavior is rejection of a first save over existing data that cannot be validated.

The default backend owns auxiliary-file creation and replacement through Foundation.
The file-access contract requires an ordinary failed replacement to leave the old
destination intact. Tests inject errors **before delegating to Foundation's atomic
write**, then inspect real bytes at that same destination. This proves the store's
control flow and preservation under that error contract. It does not experimentally
prove every operating-system/filesystem failure mode or power-loss behavior.

### iOS integration and the Settings regression

The committed journal is still published only after `save` succeeds. MainActor and
`isBusy` guards remain intact; failed saves retain the last committed journal and
existing meaningful error messages. A failed stop leaves the previously saved
active session in place; retry deliberately uses its new requested end time.

Settings now captures the goal at the Save action and tracks the successfully saved
goal value, rather than a Boolean acknowledgment. Synchronizing the draft to that
same committed value no longer clears the acknowledgment. Editing a different draft
invalidates it, and returning to Settings still reads the committed goal. No layout,
navigation, existing accessibility identifiers, or localized product copy was changed.

Today/History review confirmed that active timing is derived from the stored start
and current Date, completed history uses saved sessions, and natural-day clipping
handles midnight without clearing records. Existing tests cover timezone/DST cases.
The new storage injection does not bypass those validation or persistence rules.

### Files changed in this phase

| File | Change |
| --- | --- |
| SharedCore/Sources/DaylightCore/DaylightJournalStorage.swift | New storage/file-access protocols and Foundation backend. |
| SharedCore/Sources/DaylightCore/DaylightJournalFileStore.swift | Injected file operations and validation-before-first-save/retry guard. |
| SharedCore/Tests/DaylightCoreTests/PersistenceReliabilityTests.swift | Eight focused reliability test functions, several parameterized. |
| iOSApp/DaylightStore.swift | Optional storage injection; existing default location/commit sequence retained. |
| iOSApp/DaylightSettingsView.swift | Saved-goal acknowledgment fix. |
| docs/PHASE3A3-RELIABILITY.md | This report. |

WatchApp, deployment targets, Package.swift, business-model rules, UI tests, workflow
and CI scripts were not changed in this phase. Existing user changes in those files
were left in place. All new code/comments/test descriptions and this report are English;
existing localized UI strings and historical documents were preserved.

## 3. Regression tests added

| Test | Evidence |
| --- | --- |
| failedReplacementPreservesExistingJournalAndActiveSession | Injects out-of-space, permission, or directory failure at the same valid journal path. Checks exact original bytes, goal/history/active ID after a fresh store load, and a successful retry with exactly one completed replacement for the active ID. |
| deniedReadDoesNotBecomeEmptyStateOrPermitOverwrite | After a successful read, injects denied reads. Verifies the exact error, blocked save, no write attempt, unchanged bytes and successful reload after the fault is cleared. |
| corruptOrIncompleteJournalRequiresExplicitRepair | Empty, truncated and missing-field JSON fail decoding. Both the same and a fresh writer refuse a blind save. Damaged bytes remain untouched. Explicit restoration of known-good test bytes permits reload/save without losing sessions. |
| missingFileOrDirectoryCreatesDataOnlyOnSave | Missing file with an existing or absent parent loads default state without writing; save creates nested directories and round-trips normally. |
| repeatedSaveAndLoadPreserveHistoryAndGoal | Twenty real save/load cycles, checking the entire journal through both the same actor and fresh instances. |
| persistedGoalChangeRecalculatesHistoryWithoutChangingSessions | Persisted 30-to-60-minute goal change recalculates a 15-minute history from 0.5 to 0.25 without changing IDs, intervals, or recorded seconds. |
| largeHistoryRoundTripAndSummaryMeasurements | Validates and persists 20,000 non-overlapping sessions, restores the full journal, checks seven daily summaries against the expected record count, and reports elapsed I/O/summary time. |
| failedFirstSaveCanRetryAfterMissingDirectoryCreation | Injected disk-write error leaves no published journal; reopening returns genuine initial state. Clearing the fault permits retry and restoration of the requested goal. |

All file fixtures use unique, test-created temporary directories and clean up only
those directories. No app/user record location is accessed by the tests. Error codes
are injected, not induced by filling a disk or changing OS permissions.

The inherited empty `example()` test is retained to preserve existing work and is
explicitly excluded from claims of behavioral coverage. It is included in the runner's
44-test count; the total does not mean 44 independently meaningful behaviors.

## 4. Actual local validation results

| Check | Status | Result |
| --- | --- | --- |
| Swift 6.4.2 `swift build`, SharedCore | Passed | Exit 0; production storage protocols/actor/backend compiled on Windows. |
| Swift 6.4.2 `swift test`, SharedCore | Passed | Exit 0; 44 Swift Testing tests, including all existing 36 and eight new test functions. |
| Python CI script tests | Passed | Exit 0; all nine fixtures passed. This invoked no real simctl/xcodebuild command. |
| `git diff --check` | Passed | No whitespace errors; normal LF/CRLF notices only. |
| Static workflow/spec consistency | Passed | iOS 17/watchOS 10 preserved, correct UI test target/scheme/configuration, signing disabled for all three simulator commands, SharedCore tests retained, UI failure artifacts uploaded before watchOS compilation. |
| Full YAML grammar parsing | Not executed locally | Existing local parser availability is unchanged; no software was installed. CI's Ruby syntax check remains configured. Source-level review is not a YAML parser. |
| XcodeGen generation / iOS/watchOS builds | Requires macOS/Xcode | Configured in CI; not executed in this phase. |
| Eight XCTest UI tests | Requires macOS/Xcode | Configured in CI; not executed on Windows. |
| UI model rollback/Settings lifecycle on iOS | Requires macOS/Xcode | Reviewed statically; storage fault paths are tested, but the Combine/SwiftUI layer was not compiled or executed locally. |
| Real simulator discovery, boot, screenshots and artifact upload | Requires macOS/Xcode | Fixtures/source reviewed; actual platform operations not executed. |

One Windows run measured approximately **401 ms** for the 20,000-session save/load
and **43 ms** for seven daily summaries. Fixture creation is outside those timings.
There is no wall-clock test threshold: these are one-host observations under concurrent
test execution, not a mobile performance guarantee or a statistically rigorous benchmark.

No executed check failed. No claim of successful Xcode compilation or Simulator
execution follows from the Windows results.

## 5. Remaining limitations and unverified behaviors

- No power-loss, process-kill-during-replacement, real disk-full, real permission/ACL,
  iOS locked-file or hardware-filesystem fault experiment was performed. Ordinary
  injected error handling is not evidence for all filesystem durability guarantees.
- Corruption recovery is fail-closed plus retry after an explicit repair/restore of
  valid bytes. There is no automatic reconstruction, backup/export/recovery UI, or
  promise that lost/corrupt bytes can be recovered without an independent good copy.
- The actor serializes one store's operations, not arbitrary external writers. Once
  validated, it assumes the app's existing single-writer architecture; this is not a
  cross-process lock, versioned compare-and-swap, or external-file-change monitor.
- Tests reopen storage instances to verify persisted relaunch state. That is not an
  actual iOS process termination/relaunch; the eight configured UI tests cover the
  platform lifecycle only when they run on macOS.
- Today still recomputes from in-memory history, and each save rewrites the snapshot.
  The measured 20,000-record fixture does not profile SwiftUI rendering, memory usage,
  battery impact or multi-year interactive performance.
- Historical ratios intentionally use the current goal and current calendar/timezone.
  Progress still uses complete minutes; wall-clock changes can affect elapsed time.
- Existing test tab/stepper accessibility fallbacks, slow-runner waits and the preview
  runner/Xcode path remain platform-validation risks. No deployment minimum was lowered.

## 6. macOS/Xcode verification requirements

The next user-authorized platform run should execute the existing workflow, including
YAML parsing, XcodeGen generation, SharedCore tests, both Simulator builds, dynamic
iPhone selection/boot and all eight UI tests. In particular, confirm:

1. The new Sendable storage protocol integrates with the MainActor iOS store in both
   normal Debug and isolated UITesting configurations.
2. A goal save acknowledgment remains visible after successful save and synchronization,
   including leaving/returning to Settings while the write is pending.
3. Failed start/stop/goal saves leave displayed committed state intact and show the
   correct feedback; failed initial reads keep writes disabled and allow retry.
   The injected storage constructor enables controlled future platform tests of this path.
4. Active ID/start/elapsed time and completed history survive real app termination/
   relaunch; repeated taps cannot publish duplicate sessions.
5. Cross-midnight day rows retain unique accessibility IDs and correct totals; current
   timezone changes regroup the same stored absolute intervals consistently.
6. Failure evidence is actually available in xcresult/screenshots/diagnostic artifacts.

No macOS run, remote workflow dispatch, commit or push was performed by this phase.

## 7. Recommendation

**Ready for final platform validation, not cleared for release.** The local Foundation
storage implementation compiles, all regression tests pass, and ordinary read/write
failure handling is now directly testable at the real destination path. The Settings
regression has a focused source fix with its platform acknowledgment test already
configured. Final release readiness depends on the unexecuted macOS/Xcode checks and
explicit acceptance of the documented recovery and durability limits.

No software was installed, no global environment was modified, no WatchApp file or
deployment target changed, and all pre-existing user changes were preserved.
