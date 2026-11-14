import Foundation
import Testing
@testable import DaylightCore

private let journalStart = Date(timeIntervalSince1970: 1_800_000_000)

@Test func recordingRestoresElapsedTimeAndFinishesExactlyOnce() throws {
    var journal = DaylightJournal()
    try journal.start(at: journalStart)
    #expect(throws: DaylightRecordError.alreadyRecording) { try journal.start(at: journalStart) }
    let data = try JSONEncoder().encode(journal)
    var restored = try JSONDecoder().decode(DaylightJournal.self, from: data)
    let active = try #require(restored.activeSession)
    #expect(active.elapsed(at: journalStart.addingTimeInterval(3600)) == 3600)
    #expect(active.elapsed(at: journalStart.addingTimeInterval(-10)) == 0)
    #expect(throws: DaylightRecordError.invalidInterval) { try restored.finish(at: journalStart) }
    #expect(restored.activeSession == active)
    try restored.finish(at: journalStart.addingTimeInterval(3600))
    #expect(restored.sessions.count == 1)
    #expect(restored.sessions.first?.id == active.id)
    #expect(restored.activeSession == nil)
    #expect(throws: DaylightRecordError.notRecording) { try restored.finish(at: journalStart.addingTimeInterval(3601)) }
    #expect(restored.sessions.count == 1)
}

@Test func journalRejectsOverlapButAllowsAdjacentSessions() throws {
    var journal = DaylightJournal()
    let first = try DaylightSession(start: journalStart, end: journalStart.addingTimeInterval(60))
    try journal.add(first)
    #expect(throws: DaylightRecordError.duplicateID) { try journal.add(first) }
    let overlap = try DaylightSession(start: journalStart.addingTimeInterval(30), end: journalStart.addingTimeInterval(90))
    #expect(throws: DaylightRecordError.overlappingSessions) { try journal.add(overlap) }
    try journal.start(at: first.end)
    let active = try #require(journal.activeSession)
    let withActiveID = try DaylightSession(id: active.id, start: journalStart.addingTimeInterval(-60), end: journalStart)
    #expect(throws: DaylightRecordError.duplicateID) { try journal.add(withActiveID) }
    #expect(throws: DaylightRecordError.overlappingSessions) { try journal.add(overlap) }
    try journal.finish(at: first.end.addingTimeInterval(60))
    #expect(journal.sessions.count == 2)
}

@Test(arguments: [Int.min, -1, 0, 1441, Int.max])
func journalRejectsInvalidGoals(minutes: Int) {
    var journal = DaylightJournal()
    #expect(throws: DaylightRecordError.invalidGoal) { try journal.setGoalMinutes(minutes) }
    #expect(journal.goalMinutes == 30)
}

@Test func journalRoundTripAndCorruptSnapshotRejection() throws {
    var journal = DaylightJournal()
    try journal.add(DaylightSession(start: journalStart, end: journalStart.addingTimeInterval(600)))
    try journal.setGoalMinutes(45)
    try journal.start(at: journalStart.addingTimeInterval(1200))
    let data = try JSONEncoder().encode(journal)
    #expect(try JSONDecoder().decode(DaylightJournal.self, from: data) == journal)
    var object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    object["version"] = 2
    #expect(throws: DaylightRecordError.unsupportedFileVersion) {
        try JSONDecoder().decode(DaylightJournal.self, from: JSONSerialization.data(withJSONObject: object))
    }
    object["version"] = 1
    let records = try #require(object["sessions"] as? [[String: Any]])
    object["sessions"] = records + records
    #expect(throws: DaylightRecordError.duplicateID) {
        try JSONDecoder().decode(DaylightJournal.self, from: JSONSerialization.data(withJSONObject: object))
    }
}

@Test func fileStoreRestoresActiveRecordingAndCompletedRecords() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("DaylightTests-\(UUID())")
    defer { try? FileManager.default.removeItem(at: directory) }
    let url = directory.appendingPathComponent("nested/journal.json")
    let store = DaylightJournalFileStore(fileURL: url)
    let empty = try await store.load()
    #expect(empty == DaylightJournal())
    var journal = empty
    try journal.start(at: journalStart)
    try await store.save(journal)
    let reopened = DaylightJournalFileStore(fileURL: url)
    var restored = try await reopened.load()
    #expect(restored == journal)
    try restored.finish(at: journalStart.addingTimeInterval(1800))
    try restored.setGoalMinutes(60)
    try await reopened.save(restored)
    let completed = try await store.load()
    #expect(completed == restored)
    #expect(completed.sessions.first?.duration == 1800)
}

@Test func corruptFileIsReportedAndPreserved() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("DaylightTests-\(UUID())")
    defer { try? FileManager.default.removeItem(at: directory) }
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let url = directory.appendingPathComponent("journal.json")
    let original = Data("not a journal".utf8)
    try original.write(to: url)
    let store = DaylightJournalFileStore(fileURL: url)
    do {
        _ = try await store.load()
        Issue.record("Corrupt data must not silently become an empty journal")
    } catch {
        #expect(try Data(contentsOf: url) == original)
    }
}

@Test func failedWriteDoesNotReplaceExistingData() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("DaylightTests-\(UUID())")
    defer { try? FileManager.default.removeItem(at: directory) }
    let originalURL = directory.appendingPathComponent("journal.json")
    let store = DaylightJournalFileStore(fileURL: originalURL)
    try await store.save(DaylightJournal())
    let original = try Data(contentsOf: originalURL)
    // A regular file cannot also be the parent directory of another file.
    let blocked = DaylightJournalFileStore(fileURL: originalURL.appendingPathComponent("child.json"))
    do {
        try await blocked.save(DaylightJournal())
        Issue.record("Writing beneath a regular file must fail")
    } catch {
        #expect(try Data(contentsOf: originalURL) == original)
    }
}
