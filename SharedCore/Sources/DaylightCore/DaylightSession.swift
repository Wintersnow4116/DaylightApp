import Foundation

public enum DaylightRecordError: Error, Equatable, Sendable {
    case invalidDate
    case invalidInterval
    case invalidGoal
    case alreadyRecording
    case notRecording
    case duplicateID
    case overlappingSessions
    case unsupportedFileVersion
}

/// User-declared outdoor activity, not measured light exposure.
public struct DaylightSession: Identifiable, Codable, Equatable, Sendable {
    public enum Source: String, Codable, Sendable {
        case manual
    }

    public let id: UUID
    public let start: Date
    public let end: Date
    public let source: Source

    /// Seconds derived from the authoritative interval, never a separately editable value.
    public var duration: TimeInterval { end.timeIntervalSince(start) }

    public init(id: UUID = UUID(), start: Date, end: Date, source: Source = .manual) throws {
        try Self.validate(start)
        try Self.validate(end)
        guard end > start else { throw DaylightRecordError.invalidInterval }
        self.id = id
        self.start = start
        self.end = end
        self.source = source
    }

    static func validate(_ date: Date) throws {
        guard date.timeIntervalSinceReferenceDate.isFinite,
              date >= .distantPast, date <= .distantFuture else {
            throw DaylightRecordError.invalidDate
        }
    }

    private enum CodingKeys: String, CodingKey { case id, start, end, source }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            id: values.decode(UUID.self, forKey: .id),
            start: values.decode(Date.self, forKey: .start),
            end: values.decode(Date.self, forKey: .end),
            source: values.decode(Source.self, forKey: .source)
        )
    }
}

public struct ActiveDaylightSession: Codable, Equatable, Sendable {
    public let id: UUID
    public let start: Date

    public init(id: UUID = UUID(), start: Date) throws {
        try DaylightSession.validate(start)
        self.id = id
        self.start = start
    }

    /// Wall-clock based; a clock moving behind the start never produces negative time.
    public func elapsed(at date: Date) -> TimeInterval {
        let seconds = date.timeIntervalSince(start)
        return seconds.isFinite ? max(0, seconds) : 0
    }

    public func finished(at date: Date) throws -> DaylightSession {
        try DaylightSession(id: id, start: start, end: date)
    }

    private enum CodingKeys: String, CodingKey { case id, start }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(id: values.decode(UUID.self, forKey: .id), start: values.decode(Date.self, forKey: .start))
    }
}
