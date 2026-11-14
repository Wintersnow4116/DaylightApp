/// One day's accumulated outdoor time, measured in whole minutes.
public struct DaylightProgress: Equatable, Sendable {
    public private(set) var outdoorMinutes: Int
    public let goalMinutes: Int

    /// Negative durations and goals are normalized to zero.
    public init(outdoorMinutes: Int = 0, goalMinutes: Int = 30) {
        self.outdoorMinutes = max(0, outdoorMinutes)
        self.goalMinutes = max(0, goalMinutes)
    }

    /// A zero goal has no measurable progress and returns zero.
    public var completionRatio: Double {
        guard goalMinutes > 0 else { return 0 }
        return min(1, Double(outdoorMinutes) / Double(goalMinutes))
    }

    public var remainingMinutes: Int {
        guard outdoorMinutes < goalMinutes else { return 0 }
        return goalMinutes - outdoorMinutes
    }

    /// Adds an outdoor session. Negative minutes are ignored;
    /// totals exceeding the integer range saturate at `Int.max`.
    public mutating func recordOutdoorMinutes(_ minutes: Int) {
        guard minutes > 0 else { return }
        let result = outdoorMinutes.addingReportingOverflow(minutes)
        outdoorMinutes = result.overflow ? Int.max : result.partialValue
    }
}
