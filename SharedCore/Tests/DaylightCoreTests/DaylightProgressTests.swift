import Testing
@testable import DaylightCore

@Test func defaultDailyProgress() {
    let progress = DaylightProgress()
    #expect(progress.outdoorMinutes == 0)
    #expect(progress.goalMinutes == 30)
    #expect(progress.completionRatio == 0)
    #expect(progress.remainingMinutes == 30)
}

@Test func outdoorSessionsAccumulate() {
    var progress = DaylightProgress()
    progress.recordOutdoorMinutes(5)
    progress.recordOutdoorMinutes(10)
    #expect(progress.outdoorMinutes == 15)
    #expect(progress.completionRatio == 0.5)
    #expect(progress.remainingMinutes == 15)
}

@Test func customGoal() {
    let progress = DaylightProgress(outdoorMinutes: 15, goalMinutes: 60)
    #expect(progress.completionRatio == 0.25)
    #expect(progress.remainingMinutes == 45)
}

@Test(arguments: [30, 45, Int.max])
func completedGoal(minutes: Int) {
    let progress = DaylightProgress(outdoorMinutes: minutes)
    #expect(progress.completionRatio == 1)
    #expect(progress.remainingMinutes == 0)
}

@Test(arguments: [0, 15, Int.max])
func zeroGoal(minutes: Int) {
    let progress = DaylightProgress(outdoorMinutes: minutes, goalMinutes: 0)
    #expect(progress.completionRatio == 0)
    #expect(progress.remainingMinutes == 0)
}

@Test func negativeInputsAreNormalized() {
    let progress = DaylightProgress(outdoorMinutes: Int.min, goalMinutes: Int.min)
    #expect(progress.outdoorMinutes == 0)
    #expect(progress.goalMinutes == 0)
    #expect(progress.completionRatio == 0)
    #expect(progress.remainingMinutes == 0)
    #expect(DaylightProgress(outdoorMinutes: -5).remainingMinutes == 30)
}

@Test func nonpositiveSessionsAreIgnored() {
    var progress = DaylightProgress(outdoorMinutes: 10)
    progress.recordOutdoorMinutes(Int.min)
    progress.recordOutdoorMinutes(0)
    #expect(progress.outdoorMinutes == 10)
}

@Test func accumulationSaturatesWithoutOverflow() {
    var progress = DaylightProgress(outdoorMinutes: Int.max - 1, goalMinutes: Int.max)
    #expect(progress.remainingMinutes == 1)
    progress.recordOutdoorMinutes(10)
    progress.recordOutdoorMinutes(1)
    #expect(progress.outdoorMinutes == Int.max)
    #expect(progress.completionRatio == 1)
    #expect(progress.remainingMinutes == 0)
}
