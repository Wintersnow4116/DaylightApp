import Foundation
import Testing
@testable import DaylightCore

private let reliabilityStart = Date(timeIntervalSince1970: 1_800_000_000)

/// Only the selected operation fails. All other operations use real disposable files.
/// This models an ordinary reported I/O error, not a crash or power loss.
private final class FailingJournalFileAccess: DaylightJournalFileAccess, @unchecked Sendable {
    enum Stage { case read, directory, replacement }
    private let lock = NSLock()
    private let foundation = FoundationDaylightJournalFileAccess()
    private var failure: (Stage, CocoaError.Code)?
    private var writeURL: URL?

    func fail(_ stage: Stage, with code: CocoaError.Code) {
        lock.lock()
        failure = (stage, code)
        lock.unlock()
    }

    func clearFailure() {
        lock.lock()
        failure = nil
        lock.unlock()
    }

    var lastWriteURL: URL? {
        lock.lock()
        defer { lock.unlock() }
        return writeURL
    }

    private func check(_ stage: Stage) throws {
        lock.lock()
        let current = failure
        lock.unlock()
        if let current, current.0 == stage { throw CocoaError(current.1) }
    }

    func read(from url: URL) throws -> Data {
        try check(.read)
        return try foundation.read(from: url)
    }

    func createDirectory(at url: URL) throws {
        try check(.directory)
        try foundation.createDirectory(at: url)
    }

    func writeAtomically(_ data: Data, to url: URL) throws {
        lock.lock()
        writeURL = url
        lock.unlock()
        try check(.replacement)
        try foundation.writeAtomically(data, to: url)
    }
}

private func reliabilityDirectory() -> URL {
    FileManager.default.temporaryDirectory.appendingPathComponent("DaylightReliability-\(UUID())")
}

private func journalWithHistoryAndActiveSession() throws -> DaylightJournal {
    var journal = DaylightJournal()
    try journal.add(DaylightSession(start: reliabilityStart, end: reliabilityStart.addingTimeInterval(900)))
    try journal.setGoalMinutes(45)
    try journal.start(at: reliabilityStart.addingTimeInterval(1800))
    return journal
}

@Test(arguments: ["outOfSpace", "permission", "directory"])
func failedReplacementPreservesExistingJournalAndActiveSession(failure: String) async throws {
    let directory = reliabilityDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let url = directory.appendingPathComponent("journal.json")
    let original = try journalWithHistoryAndActiveSession()
    try await DaylightJournalFileStore(fileURL: url).save(original)
    let originalBytes = try Data(contentsOf: url)
    let access = FailingJournalFileAccess()
    let storage: any DaylightJournalStorage = DaylightJournalFileStore(fileURL: url, fileAccess: access)
    var candidate = try await storage.load()
    try candidate.finish(at: reliabilityStart.addingTimeInterval(1920))
    try candidate.setGoalMinutes(60)
    let expectedCode: CocoaError.Code = failure == "outOfSpace" ? .fileWriteOutOfSpace : .fileWriteNoPermission
    access.fail(failure == "directory" ? .directory : .replacement, with: expectedCode)
    do {
        try await storage.save(candidate)
        Issue.record("The injected write failure must propagate")
    } catch {
        #expect((error as? CocoaError)?.code == expectedCode)
    }
    // Same destination as the valid journal, not a separate deliberately invalid path.
    if failure != "directory" { #expect(access.lastWriteURL == url) }
    #expect(try Data(contentsOf: url) == originalBytes)
    let relaunched = try await DaylightJournalFileStore(fileURL: url).load()
    #expect(relaunched == original)
    #expect(relaunched.activeSession?.id == original.activeSession?.id)
    access.clearFailure()
    try await storage.save(candidate)
    let recovered = try await DaylightJournalFileStore(fileURL: url).load()
    #expect(recovered == candidate)
    #expect(recovered.sessions.count == 2)
    #expect(recovered.sessions.last?.id == original.activeSession?.id)
    #expect(recovered.activeSession == nil)
}

@Test func deniedReadDoesNotBecomeEmptyStateOrPermitOverwrite() async throws {
    let directory = reliabilityDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let url = directory.appendingPathComponent("journal.json")
    let original = try journalWithHistoryAndActiveSession()
    try await DaylightJournalFileStore(fileURL: url).save(original)
    let bytes = try Data(contentsOf: url)
    let access = FailingJournalFileAccess()
    let storage = DaylightJournalFileStore(fileURL: url, fileAccess: access)
    let initiallyLoaded = try await storage.load()
    #expect(initiallyLoaded == original)
    // A later failed read must revoke the permission to save based on an earlier read.
    access.fail(.read, with: .fileReadNoPermission)
    do {
        _ = try await storage.load()
        Issue.record("Permission denial must not become an empty journal")
    } catch {
        #expect((error as? CocoaError)?.code == .fileReadNoPermission)
    }
    do {
        try await storage.save(DaylightJournal())
        Issue.record("A save must not bypass a failed initial read")
    } catch {
        #expect((error as? CocoaError)?.code == .fileReadNoPermission)
    }
    #expect(access.lastWriteURL == nil)
    #expect(try Data(contentsOf: url) == bytes)
    access.clearFailure()
    let recovered = try await storage.load()
    #expect(recovered == original)
}

@Test(arguments: ["empty", "truncated", "missingField"])
func corruptOrIncompleteJournalRequiresExplicitRepair(kind: String) async throws {
    let directory = reliabilityDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let url = directory.appendingPathComponent("journal.json")
    let original = try journalWithHistoryAndActiveSession()
    try await DaylightJournalFileStore(fileURL: url).save(original)
    let knownGoodBytes = try Data(contentsOf: url)
    let damaged: Data
    switch kind {
    case "empty": damaged = Data()
    case "truncated": damaged = Data(knownGoodBytes.prefix(knownGoodBytes.count / 2))
    default:
        var object = try #require(JSONSerialization.jsonObject(with: knownGoodBytes) as? [String: Any])
        object.removeValue(forKey: "goalMinutes")
        damaged = try JSONSerialization.data(withJSONObject: object)
    }
    try damaged.write(to: url)
    let storage = DaylightJournalFileStore(fileURL: url)
    do {
        _ = try await storage.load()
        Issue.record("Incomplete data must fail decoding")
    } catch { #expect(error is DecodingError) }
    for writer in [storage, DaylightJournalFileStore(fileURL: url)] {
        do {
            try await writer.save(DaylightJournal())
            Issue.record("Neither retry nor a fresh writer may silently replace corrupt data")
        } catch { #expect(error is DecodingError) }
    }
    #expect(try Data(contentsOf: url) == damaged)
    // Explicit test-owned repair, not an application backup or auto-reset feature.
    try knownGoodBytes.write(to: url, options: .atomic)
    var recovered = try await storage.load()
    #expect(recovered == original)
    try recovered.setGoalMinutes(60)
    try await storage.save(recovered)
    let persisted = try await DaylightJournalFileStore(fileURL: url).load()
    #expect(persisted == recovered)
    #expect(persisted.sessions == original.sessions)
}

@Test(arguments: [false, true])
func missingFileOrDirectoryCreatesDataOnlyOnSave(directoryExists: Bool) async throws {
    let directory = reliabilityDirectory().appendingPathComponent("nested/support")
    let cleanupRoot = directory.deletingLastPathComponent().deletingLastPathComponent()
    defer { try? FileManager.default.removeItem(at: cleanupRoot) }
    if directoryExists {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }
    let url = directory.appendingPathComponent("journal.json")
    let store = DaylightJournalFileStore(fileURL: url)
    let loaded = try await store.load()
    #expect(loaded == DaylightJournal())
    #expect(FileManager.default.fileExists(atPath: directory.path) == directoryExists)
    #expect(!FileManager.default.fileExists(atPath: url.path))
    try await store.save(loaded)
    let reopened = try await DaylightJournalFileStore(fileURL: url).load()
    #expect(reopened == loaded)
}

@Test func repeatedSaveAndLoadPreserveHistoryAndGoal() async throws {
    let directory = reliabilityDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let url = directory.appendingPathComponent("journal.json")
    let store = DaylightJournalFileStore(fileURL: url)
    var expected = DaylightJournal()
    for index in 0..<20 {
        let start = reliabilityStart.addingTimeInterval(Double(index * 120))
        try expected.add(DaylightSession(start: start, end: start.addingTimeInterval(60)))
        try expected.setGoalMinutes(30 + (index % 3) * 15)
        try await store.save(expected)
        let sameInstance = try await store.load()
        let newInstance = try await DaylightJournalFileStore(fileURL: url).load()
        #expect(sameInstance == expected)
        #expect(newInstance == expected)
        #expect(newInstance.sessions.count == index + 1)
    }
}

@Test func persistedGoalChangeRecalculatesHistoryWithoutChangingSessions() async throws {
    let directory = reliabilityDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let url = directory.appendingPathComponent("journal.json")
    var journal = DaylightJournal()
    try journal.add(DaylightSession(start: reliabilityStart, end: reliabilityStart.addingTimeInterval(900)))
    let storage = DaylightJournalFileStore(fileURL: url)
    try await storage.save(journal)
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = try #require(TimeZone(secondsFromGMT: 0))
    let before = try DailyDaylightSummary(dayContaining: reliabilityStart, sessions: journal.sessions, calendar: calendar)
    try journal.setGoalMinutes(60)
    try await storage.save(journal)
    let reopened = try await DaylightJournalFileStore(fileURL: url).load()
    let after = try DailyDaylightSummary(dayContaining: reliabilityStart, sessions: reopened.sessions,
                                        goalMinutes: reopened.goalMinutes, calendar: calendar)
    #expect(before.completionRatio == 0.5)
    #expect(after.completionRatio == 0.25)
    #expect(after.totalDuration == before.totalDuration)
    #expect(reopened.sessions == journal.sessions)
}

private struct LargeJournalFixture: Encodable {
    let version = 1
    let sessions: [DaylightSession]
    let goalMinutes = 30
}

@Test func largeHistoryRoundTripAndSummaryMeasurements() async throws {
    let directory = reliabilityDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let sessions = try (0..<20_000).map { index in
        let start = reliabilityStart.addingTimeInterval(Double(index * 120))
        return try DaylightSession(start: start, end: start.addingTimeInterval(60))
    }
    // Use the real decoder to validate a large fixture without quadratic test setup.
    let fixture = try JSONEncoder().encode(LargeJournalFixture(sessions: sessions))
    let journal = try JSONDecoder().decode(DaylightJournal.self, from: fixture)
    let store = DaylightJournalFileStore(fileURL: directory.appendingPathComponent("journal.json"))
    let clock = ContinuousClock()
    let ioStart = clock.now
    try await store.save(journal)
    let restored = try await store.load()
    let ioTime = clock.now - ioStart
    #expect(restored == journal)
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = try #require(TimeZone(secondsFromGMT: 0))
    let last = try #require(sessions.last)
    let lastDay = calendar.startOfDay(for: last.start)
    let firstDay = try #require(calendar.date(byAdding: .day, value: -6, to: lastDay))
    let summaryStart = clock.now
    var total: TimeInterval = 0
    for offset in 0..<7 {
        let day = try #require(calendar.date(byAdding: .day, value: offset, to: firstDay))
        let summary = try DailyDaylightSummary(dayContaining: day, sessions: restored.sessions, calendar: calendar)
        total += summary.totalDuration
        #expect((0...1).contains(summary.completionRatio))
    }
    let summaryTime = clock.now - summaryStart
    let expectedCount = sessions.filter { $0.start >= firstDay }.count
    #expect(total == Double(expectedCount) * 60)
    print("Reliability sample: 20,000-session save/load = \(ioTime); seven daily summaries = \(summaryTime)")
    // No wall-clock pass/fail threshold: CI load is variable; correctness is asserted above.
}

@Test func failedFirstSaveCanRetryAfterMissingDirectoryCreation() async throws {
    let directory = reliabilityDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let url = directory.appendingPathComponent("support/nested/journal.json")
    let access = FailingJournalFileAccess()
    access.fail(.replacement, with: .fileWriteOutOfSpace)
    let store = DaylightJournalFileStore(fileURL: url, fileAccess: access)
    var candidate = DaylightJournal()
    try candidate.setGoalMinutes(75)
    do {
        try await store.save(candidate)
        Issue.record("The first write must report the injected disk-write error")
    } catch { #expect((error as? CocoaError)?.code == .fileWriteOutOfSpace) }
    #expect(!FileManager.default.fileExists(atPath: url.path))
    let previous = try await DaylightJournalFileStore(fileURL: url).load()
    #expect(previous == DaylightJournal())
    access.clearFailure()
    try await store.save(candidate)
    let restored = try await DaylightJournalFileStore(fileURL: url).load()
    #expect(restored == candidate)
}
