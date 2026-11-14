import Foundation
import Testing
@testable import DaylightCore

private func instant(_ value: String) throws -> Date {
    try #require(ISO8601DateFormatter().date(from: value))
}

private func calendar(_ zone: String = "UTC") throws -> Calendar {
    var result = Calendar(identifier: .gregorian)
    result.timeZone = try #require(TimeZone(identifier: zone))
    return result
}

@Test func sessionStoresValidatedIntervalAndManualSource() throws {
    let start = try instant("2026-11-14T12:00:00Z")
    let id = UUID()
    let session = try DaylightSession(id: id, start: start, end: start.addingTimeInterval(1800))
    #expect(session.id == id)
    #expect(session.start == start)
    #expect(session.duration == 1800)
    #expect(session.source == .manual)
}

@Test(arguments: [0.0, -1.0, -3600.0])
func zeroAndNegativeIntervalsAreRejected(seconds: Double) throws {
    let start = try instant("2026-11-14T12:00:00Z")
    #expect(throws: DaylightRecordError.invalidInterval) {
        try DaylightSession(start: start, end: start.addingTimeInterval(seconds))
    }
}

@Test(arguments: [Double.nan, Double.infinity, -Double.infinity])
func nonfiniteDatesAreRejected(value: Double) {
    let invalid = Date(timeIntervalSinceReferenceDate: value)
    #expect(throws: DaylightRecordError.invalidDate) {
        try DaylightSession(start: invalid, end: .now)
    }
    #expect(throws: DaylightRecordError.invalidDate) {
        try DaylightSession(start: .now, end: invalid)
    }
}

@Test func outOfCalendarRangeIsRejected() {
    #expect(throws: DaylightRecordError.invalidDate) {
        try DaylightSession(start: .distantPast.addingTimeInterval(-1), end: .now)
    }
}

@Test func multipleSessionsRoundOnlyAfterSumming() throws {
    let start = try instant("2026-11-14T12:00:00Z")
    let a = try DaylightSession(start: start, end: start.addingTimeInterval(30))
    let b = try DaylightSession(start: start.addingTimeInterval(60), end: start.addingTimeInterval(90))
    let summary = try DailyDaylightSummary(dayContaining: start, sessions: [a, b], calendar: calendar())
    #expect(summary.totalDuration == 60)
    #expect(summary.progress.outdoorMinutes == 1)
    #expect(summary.remainingMinutes == 29)
}

@Test func crossMidnightSplitsAndConservesSeconds() throws {
    let start = try instant("2026-11-14T23:50:00Z")
    let end = try instant("2026-11-15T00:20:00Z")
    let session = try DaylightSession(start: start, end: end)
    let first = try DailyDaylightSummary(dayContaining: start, sessions: [session], calendar: calendar())
    let second = try DailyDaylightSummary(dayContaining: end, sessions: [session], calendar: calendar())
    #expect(first.totalDuration == 600)
    #expect(second.totalDuration == 1200)
    #expect(first.totalDuration + second.totalDuration == session.duration)
    #expect(first.segments.first?.end == second.segments.first?.start)
}

@Test func exactMidnightEndDoesNotCreateNextDayRecord() throws {
    let start = try instant("2026-11-14T23:50:00Z")
    let end = try instant("2026-11-15T00:00:00Z")
    let session = try DaylightSession(start: start, end: end)
    let summary = try DailyDaylightSummary(dayContaining: end, sessions: [session], calendar: calendar())
    #expect(summary.totalDuration == 0)
    #expect(summary.segments.isEmpty)
}

@Test func sameAbsoluteSessionUsesSelectedTimeZone() throws {
    let start = try instant("2026-11-14T23:30:00Z")
    let end = try instant("2026-11-15T00:30:00Z")
    let session = try DaylightSession(start: start, end: end)
    let utc = try DailyDaylightSummary(dayContaining: start, sessions: [session], calendar: calendar())
    let shanghai = try DailyDaylightSummary(dayContaining: start, sessions: [session], calendar: calendar("Asia/Shanghai"))
    let losAngeles = try DailyDaylightSummary(dayContaining: start, sessions: [session], calendar: calendar("America/Los_Angeles"))
    #expect(utc.totalDuration == 1800)
    #expect(shanghai.totalDuration == 3600)
    #expect(losAngeles.totalDuration == 3600)
}

@Test(arguments: [
    ("2026-03-08T08:00:00Z", "2026-03-09T07:00:00Z", 23.0),
    ("2026-11-01T07:00:00Z", "2026-11-02T08:00:00Z", 25.0)
])
func daylightSavingDaysAreNotAssumedToBe24Hours(example: (String, String, Double)) throws {
    let start = try instant(example.0)
    let end = try instant(example.1)
    let session = try DaylightSession(start: start, end: end)
    let summary = try DailyDaylightSummary(
        dayContaining: start.addingTimeInterval(3600), sessions: [session],
        calendar: calendar("America/Los_Angeles")
    )
    #expect(summary.totalDuration == example.2 * 3600)
}

@Test(arguments: [1800.0, 3600.0])
func sessionGoalCompletionIsCapped(seconds: Double) throws {
    let start = try instant("2026-11-14T12:00:00Z")
    let session = try DaylightSession(start: start, end: start.addingTimeInterval(seconds))
    let summary = try DailyDaylightSummary(dayContaining: start, sessions: [session], calendar: calendar())
    #expect(summary.completionRatio == 1)
    #expect(summary.remainingMinutes == 0)
}

@Test(arguments: [0, -30])
func summaryNormalizesNonpositiveGoals(goal: Int) throws {
    let start = try instant("2026-11-14T12:00:00Z")
    let session = try DaylightSession(start: start, end: start.addingTimeInterval(60))
    let summary = try DailyDaylightSummary(dayContaining: start, sessions: [session], goalMinutes: goal, calendar: calendar())
    #expect(summary.completionRatio == 0)
    #expect(summary.remainingMinutes == 0)
}

@Test func duplicateSessionIDsAreNotDoubleCounted() throws {
    let start = try instant("2026-11-14T12:00:00Z")
    let session = try DaylightSession(start: start, end: start.addingTimeInterval(60))
    let summary = try DailyDaylightSummary(dayContaining: start, sessions: [session, session], calendar: calendar())
    #expect(summary.totalDuration == 60)
    #expect(summary.segments.count == 1)
}

@Test func manyRecordsAndNumericSaturation() throws {
    let start = try instant("2026-11-14T00:00:00Z")
    let sessions = try (0..<10_000).map { index in
        let begin = start.addingTimeInterval(Double(index * 2))
        return try DaylightSession(start: begin, end: begin.addingTimeInterval(1))
    }
    let summary = try DailyDaylightSummary(dayContaining: start, sessions: sessions, goalMinutes: Int.max, calendar: calendar())
    #expect(summary.totalDuration == 10_000)
    #expect(summary.progress.outdoorMinutes == 166)
    #expect(summary.remainingMinutes == Int.max - 166)
    #expect((0...1).contains(summary.completionRatio))
    #expect(DailyDaylightSummary.wholeMinutes(Double.greatestFiniteMagnitude) == Int.max)
    #expect(DailyDaylightSummary.wholeMinutes(Double(Int.max) * 60) == Int.max)
    #expect(DailyDaylightSummary.addDurations(.greatestFiniteMagnitude, .greatestFiniteMagnitude) == .greatestFiniteMagnitude)
}

@Test func sessionCodableRoundTripAndDecoderValidation() throws {
    let start = try instant("2026-11-14T12:00:00Z")
    let session = try DaylightSession(start: start, end: start.addingTimeInterval(90.5))
    let data = try JSONEncoder().encode(session)
    #expect(try JSONDecoder().decode(DaylightSession.self, from: data) == session)
    var object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    object["end"] = object["start"]
    let invalid = try JSONSerialization.data(withJSONObject: object)
    #expect(throws: DaylightRecordError.invalidInterval) {
        try JSONDecoder().decode(DaylightSession.self, from: invalid)
    }
}

@Test func nonGregorianCalendarCanSummarize() throws {
    let start = try instant("2026-11-14T12:00:00Z")
    var buddhist = Calendar(identifier: .buddhist)
    buddhist.timeZone = try #require(TimeZone(secondsFromGMT: 0))
    let session = try DaylightSession(start: start, end: start.addingTimeInterval(60))
    let summary = try DailyDaylightSummary(dayContaining: start, sessions: [session], calendar: buddhist)
    #expect(summary.totalDuration == 60)
}
