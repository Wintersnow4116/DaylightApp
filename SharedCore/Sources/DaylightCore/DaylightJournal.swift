import Foundation

/// A versioned, validated snapshot. An active recording has a stable ID across launches.
public struct DaylightJournal: Codable, Equatable, Sendable {
    public private(set) var sessions: [DaylightSession]
    public private(set) var activeSession: ActiveDaylightSession?
    public private(set) var goalMinutes: Int
    public let version: Int

    public init() {
        sessions = []
        activeSession = nil
        goalMinutes = 30
        version = 1
    }

    public mutating func setGoalMinutes(_ minutes: Int) throws {
        guard (1...1440).contains(minutes) else { throw DaylightRecordError.invalidGoal }
        goalMinutes = minutes
    }

    public mutating func start(at date: Date) throws {
        guard activeSession == nil else { throw DaylightRecordError.alreadyRecording }
        let active = try ActiveDaylightSession(start: date)
        guard !sessions.contains(where: { $0.end > date }) else {
            throw DaylightRecordError.overlappingSessions
        }
        activeSession = active
    }

    public mutating func finish(at date: Date) throws {
        guard let active = activeSession else { throw DaylightRecordError.notRecording }
        let session = try active.finished(at: date)
        // Validation and creation happen before any mutation.
        try checkAddition(session)
        sessions.append(session)
        activeSession = nil
    }

    public mutating func add(_ session: DaylightSession) throws {
        try checkAddition(session)
        guard activeSession?.id != session.id else { throw DaylightRecordError.duplicateID }
        if let active = activeSession, session.end > active.start {
            throw DaylightRecordError.overlappingSessions
        }
        sessions.append(session)
    }

    private func checkAddition(_ session: DaylightSession) throws {
        guard !sessions.contains(where: { $0.id == session.id }) else {
            throw DaylightRecordError.duplicateID
        }
        guard !sessions.contains(where: { $0.start < session.end && session.start < $0.end }) else {
            throw DaylightRecordError.overlappingSessions
        }
    }

    private enum CodingKeys: String, CodingKey { case version, sessions, activeSession, goalMinutes }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let version = try values.decode(Int.self, forKey: .version)
        guard version == 1 else { throw DaylightRecordError.unsupportedFileVersion }
        let sessions = try values.decode([DaylightSession].self, forKey: .sessions)
        let active = try values.decodeIfPresent(ActiveDaylightSession.self, forKey: .activeSession)
        let goal = try values.decode(Int.self, forKey: .goalMinutes)
        guard (1...1440).contains(goal) else { throw DaylightRecordError.invalidGoal }
        var ids = Set<UUID>()
        for session in sessions {
            guard ids.insert(session.id).inserted else { throw DaylightRecordError.duplicateID }
        }
        let sorted = sessions.sorted { $0.start < $1.start }
        for index in sorted.indices.dropFirst() {
            guard sorted[index - 1].end <= sorted[index].start else {
                throw DaylightRecordError.overlappingSessions
            }
        }
        if let active {
            guard !ids.contains(active.id) else { throw DaylightRecordError.duplicateID }
            guard !sessions.contains(where: { $0.end > active.start }) else {
                throw DaylightRecordError.overlappingSessions
            }
        }
        self.version = version
        self.sessions = sessions
        activeSession = active
        goalMinutes = goal
    }
}
