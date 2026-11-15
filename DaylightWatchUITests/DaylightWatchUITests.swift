import XCTest

final class DaylightWatchUITests: XCTestCase {
    @MainActor private var app: XCUIApplication!
    private let timeout: TimeInterval = 15

    @MainActor
    func testInitialLaunchShowsDefaultProgress() {
        launchFreshApp()
        assertProgress(minutes: 0, percentage: 0, remaining: 30)
        reveal(recordButton, scrollingUp: true, requiresHittable: true)
        XCTAssertTrue(recordButton.isEnabled)
        XCTAssertEqual(recordButton.label, "Record 5 outdoor minutes")
    }

    @MainActor
    func testSingleInteractionAddsFiveMinutes() {
        launchFreshApp()
        recordFiveMinutes()
        assertProgress(minutes: 5, percentage: 16, remaining: 25)
    }

    @MainActor
    func testRepeatedInteractionsReachAndExceedGoal() {
        launchFreshApp()
        let expected = [
            (minutes: 5, percentage: 16, remaining: 25),
            (minutes: 10, percentage: 33, remaining: 20),
            (minutes: 15, percentage: 50, remaining: 15),
            (minutes: 20, percentage: 66, remaining: 10),
            (minutes: 25, percentage: 83, remaining: 5),
            (minutes: 30, percentage: 100, remaining: 0),
            (minutes: 35, percentage: 100, remaining: 0),
        ]
        for state in expected {
            XCTContext.runActivity(named: "Record and verify \(state.minutes) minutes") { _ in
                recordFiveMinutes()
                assertProgress(minutes: state.minutes, percentage: state.percentage, remaining: state.remaining)
            }
        }
    }

    @MainActor
    func testColdRelaunchResetsInMemoryProgress() {
        launchFreshApp()
        recordFiveMinutes()
        assertProgress(minutes: 5, percentage: 16, remaining: 25)
        XCTContext.runActivity(named: "Confirm process termination and cold-launch reset") { _ in
            Self.stopApplication(app, timeout: timeout)
            XCTAssertEqual(app.state, .notRunning)
            app.launch()
            XCTAssertTrue(app.wait(for: .runningForeground, timeout: timeout))
            assertProgress(minutes: 0, percentage: 0, remaining: 30)
        }
    }

    @MainActor
    func testControlsExposeAccessibilityMetadata() {
        launchFreshApp()
        assertProgress(minutes: 0, percentage: 0, remaining: 30)
        XCTAssertEqual(accumulatedMinutes.label, "Recorded outdoor minutes, daily goal 30 minutes")
        XCTAssertEqual(completionPercentage.label, "Goal completion")
        XCTAssertEqual(remainingMinutes.label, "Remaining outdoor minutes")
        // ProgressView accessibility types may vary between watchOS runtimes.
        let indicator = app.descendants(matching: .any).matching(identifier: "watch.goalProgress").firstMatch
        reveal(indicator, scrollingUp: false)
        XCTAssertEqual(indicator.label, "Daily goal")
        waitForValue(indicator, "0%")
        reveal(recordButton, scrollingUp: true, requiresHittable: true)
        XCTAssertEqual(recordButton.label, "Record 5 outdoor minutes")
        recordFiveMinutes()
        assertProgress(minutes: 5, percentage: 16, remaining: 25)
        reveal(indicator, scrollingUp: false)
        waitForValue(indicator, "16%")
        // Metadata assertions are not a substitute for physical-device VoiceOver testing.
    }

    @MainActor private var recordButton: XCUIElement { app.buttons["watch.recordFiveMinutes"] }
    @MainActor private var accumulatedMinutes: XCUIElement { app.staticTexts["watch.accumulatedMinutes"] }
    @MainActor private var completionPercentage: XCUIElement { app.staticTexts["watch.completionPercentage"] }
    @MainActor private var remainingMinutes: XCUIElement { app.staticTexts["watch.remainingMinutes"] }

    @MainActor
    private func launchFreshApp() {
        continueAfterFailure = false
        app = XCUIApplication(bundleIdentifier: "org.example.daylight.watch")
        let application = app!
        Self.stopApplication(application, timeout: timeout)
        let cleanupTimeout = timeout
        addTeardownBlock { @MainActor [application] () async throws in
            Self.stopApplication(application, timeout: cleanupTimeout)
        }
        // Watch state is intentionally in-memory. A new process isolates each test;
        // no launch flag, file reset, alternate model or persistence bypass is needed.
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: timeout))
        waitForValue(accumulatedMinutes, "0")
    }

    @MainActor
    private static func stopApplication(_ application: XCUIApplication, timeout: TimeInterval) {
        guard application.state != .notRunning else { return }
        application.terminate()
        XCTAssertTrue(application.wait(for: .notRunning, timeout: timeout),
                      "The Watch process must stop before a cold launch")
    }

    @MainActor
    private func recordFiveMinutes() {
        reveal(recordButton, scrollingUp: true, requiresHittable: true)
        waitUntil("Record button is enabled", element: recordButton,
                  predicate: NSPredicate(format: "exists == true AND enabled == true AND hittable == true"))
        // Exactly one actual tap per requested increment. Never retry a tap.
        recordButton.tap()
    }

    @MainActor
    private func assertProgress(minutes: Int, percentage: Int, remaining: Int) {
        reveal(accumulatedMinutes, scrollingUp: false)
        waitForValue(accumulatedMinutes, String(minutes))
        waitForValue(completionPercentage, "\(percentage)%")
        waitForValue(remainingMinutes, String(remaining))
    }

    @MainActor
    private func reveal(_ element: XCUIElement, scrollingUp: Bool, requiresHittable: Bool = false) {
        // Scrolling reveals real controls on small watches; it does not retry tests
        // or repeat state-changing interactions after a failure. Read-only metadata
        // does not require a hit target; the actual button always does.
        let ready = NSPredicate(format: requiresHittable
                                ? "exists == true AND hittable == true" : "exists == true")
        for _ in 0..<3 {
            if ready.evaluate(with: element) { return }
            if scrollingUp { app.swipeUp() } else { app.swipeDown() }
        }
        waitUntil("Element is accessible after bounded scrolling", element: element, predicate: ready)
    }

    @MainActor
    private func waitForValue(_ element: XCUIElement, _ value: String) {
        waitUntil("Accessibility value equals \(value)", element: element,
                  predicate: NSPredicate(format: "exists == true AND value == %@", value))
    }

    @MainActor
    private func waitUntil(_ description: String, element: XCUIElement, predicate: NSPredicate) {
        if predicate.evaluate(with: element) { return }
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        let result = XCTWaiter.wait(for: [expectation], timeout: timeout)
        if result != .completed {
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.lifetime = .keepAlways
            add(screenshot)
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Watch accessibility hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
        }
        XCTAssertEqual(result, .completed, description)
    }
}
