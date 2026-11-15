import Foundation
import Testing
@testable import DaylightCore

private let auditStart = Date(timeIntervalSince1970: 1_800_000_000)

@Test func changingGoalRecomputesRatioWithoutChangingRecordedTime() throws {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = try #require(TimeZone(secondsFromGMT: 0))
    let session = try DaylightSession(start: auditStart, end: auditStart.addingTimeInterval(900))
    let original = try DailyDaylightSummary(dayContaining: auditStart, sessions: [session], calendar: calendar)
    let higher = try DailyDaylightSummary(dayContaining: auditStart, sessions: [session], goalMinutes: 60, calendar: calendar)
    let lower = try DailyDaylightSummary(dayContaining: auditStart, sessions: [session], goalMinutes: 15, calendar: calendar)
    #expect(original.totalDuration == 900)
    #expect(higher.totalDuration == original.totalDuration)
    #expect(lower.totalDuration == original.totalDuration)
    #expect(original.completionRatio == 0.5)
    #expect(higher.completionRatio == 0.25)
    #expect(lower.completionRatio == 1)
    #expect(higher.remainingMinutes == 45)
    #expect(lower.remainingMinutes == 0)
}

@Test func rejectedStartAndStopLeaveJournalUnchanged() throws {
    var journal = DaylightJournal()
    try journal.start(at: auditStart)
    let activeSnapshot = journal
    #expect(throws: DaylightRecordError.alreadyRecording) { try journal.start(at: auditStart.addingTimeInterval(1)) }
    #expect(journal == activeSnapshot)
    #expect(throws: DaylightRecordError.invalidInterval) { try journal.finish(at: auditStart.addingTimeInterval(-1)) }
    #expect(journal == activeSnapshot)
    try journal.finish(at: auditStart.addingTimeInterval(60))
    let finishedSnapshot = journal
    #expect(throws: DaylightRecordError.notRecording) { try journal.finish(at: auditStart.addingTimeInterval(61)) }
    #expect(journal == finishedSnapshot)
}

@Test func manualRecordCannotOverlapOnlyActiveRecording() throws {
    var journal = DaylightJournal()
    try journal.start(at: auditStart)
    let original = journal
    let overlap = try DaylightSession(start: auditStart.addingTimeInterval(10), end: auditStart.addingTimeInterval(20))
    #expect(throws: DaylightRecordError.overlappingSessions) { try journal.add(overlap) }
    #expect(journal == original)
}

@Test func nonMissingReadFailureDoesNotBecomeEmptyJournal() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("DaylightAudit-\(UUID())")
    defer { try? FileManager.default.removeItem(at: directory) }
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let marker = directory.appendingPathComponent("preserved.txt")
    let original = Data("existing data".utf8)
    try original.write(to: marker)
    // Reading a directory as JSON produces a genuine non-missing file read error.
    let store = DaylightJournalFileStore(fileURL: directory)
    do {
        _ = try await store.load()
        Issue.record("A directory/read error must not become a new empty journal")
    } catch {
        #expect(try Data(contentsOf: marker) == original)
    }
}

@Test(arguments: ["goal", "activeID", "activeOverlap", "completedOverlap"])
func invalidSnapshotIsRejectedWithoutModifyingFile(kind: String) async throws {
    var journal = DaylightJournal()
    try journal.add(DaylightSession(start: auditStart, end: auditStart.addingTimeInterval(60)))
    try journal.start(at: auditStart.addingTimeInterval(120))
    let validData = try JSONEncoder().encode(journal)
    let expectedError: DaylightRecordError
    var object = try #require(JSONSerialization.jsonObject(with: validData) as? [String: Any])
    var records = try #require(object["sessions"] as? [[String: Any]])
    var active = try #require(object["activeSession"] as? [String: Any])
    switch kind {
    case "goal":
        expectedError = .invalidGoal
        object["goalMinutes"] = 0
    case "activeID":
        expectedError = .duplicateID
        active["id"] = records[0]["id"]
        object["activeSession"] = active
    case "activeOverlap":
        expectedError = .overlappingSessions
        active["start"] = records[0]["start"]
        object["activeSession"] = active
    default:
        expectedError = .overlappingSessions
        var overlapping = records[0]
        overlapping["id"] = UUID().uuidString
        records.append(overlapping)
        object["sessions"] = records
    }
    let invalidData = try JSONSerialization.data(withJSONObject: object)
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("DaylightAudit-\(UUID())")
    defer { try? FileManager.default.removeItem(at: directory) }
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let file = directory.appendingPathComponent("journal.json")
    try invalidData.write(to: file)
    let store = DaylightJournalFileStore(fileURL: file)
    do {
        _ = try await store.load()
        Issue.record("Invalid snapshot must fail to load")
    } catch {
        #expect((error as? DaylightRecordError) == expectedError)
        #expect(try Data(contentsOf: file) == invalidData)
    }
}
