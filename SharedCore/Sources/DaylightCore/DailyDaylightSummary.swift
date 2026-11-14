import Foundation

/// The intersection of one session with one local calendar day: [start, end).
public struct DaylightDaySegment: Identifiable, Equatable, Sendable {
    public var id: UUID { session.id }
    public let session: DaylightSession
    public let start: Date
    public let end: Date
    public var duration: TimeInterval { end.timeIntervalSince(start) }
}

public struct DailyDaylightSummary: Sendable {
    public let day: Date
    public let segments: [DaylightDaySegment]
    public let totalDuration: TimeInterval
    public let progress: DaylightProgress

    public var completionRatio: Double { progress.completionRatio }
    public var remainingMinutes: Int { progress.remainingMinutes }

    /// Reinterprets absolute timestamps using the supplied calendar and its time zone.
    /// Only intersections with the requested day are visited, even for very long sessions.
    /// Repeated IDs are counted once. Distinct overlapping sessions are summed as recorded.
    public init(
        dayContaining date: Date,
        sessions: [DaylightSession],
        goalMinutes: Int = 30,
        calendar: Calendar = .current
    ) throws {
        try DaylightSession.validate(date)
        guard let interval = calendar.dateInterval(of: .day, for: date) else {
            throw DaylightRecordError.invalidDate
        }
        day = interval.start
        var seen = Set<UUID>()
        var pieces: [DaylightDaySegment] = []
        var seconds: TimeInterval = 0
        for session in sessions where seen.insert(session.id).inserted {
            let start = max(session.start, interval.start)
            let end = min(session.end, interval.end)
            guard end > start else { continue }
            let piece = DaylightDaySegment(session: session, start: start, end: end)
            pieces.append(piece)
            seconds = Self.addDurations(seconds, piece.duration)
        }
        segments = pieces.sorted { $0.start < $1.start }
        totalDuration = seconds
        // Round once after summing: two 30-second sessions contribute one minute.
        progress = DaylightProgress(outdoorMinutes: Self.wholeMinutes(seconds), goalMinutes: goalMinutes)
    }

    static func addDurations(_ left: TimeInterval, _ right: TimeInterval) -> TimeInterval {
        let sum = left + right
        return sum.isFinite ? sum : .greatestFiniteMagnitude
    }

    static func wholeMinutes(_ seconds: TimeInterval) -> Int {
        guard seconds > 0 else { return 0 }
        let minutes = (seconds / 60).rounded(.down)
        guard minutes < Double(Int.max) else { return Int.max }
        return Int(minutes)
    }
}
