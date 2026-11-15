import XCTest

final class DaylightUITests: XCTestCase {
    @MainActor private var app: XCUIApplication!
    private let timeout: TimeInterval = 15

    @MainActor
    private func launchApp() {
        continueAfterFailure = false
        // Explicit ID also fails safely if someone accidentally runs the tests in Debug.
        app = XCUIApplication(bundleIdentifier: "org.example.daylight.ios.uitesting")
        // New storage per test method; keep this environment for relaunch within a test.
        app.launchEnvironment["DAYLIGHT_UI_TEST_NAMESPACE"] = UUID().uuidString
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.buttons["today.startSession"].waitForExistence(timeout: timeout))
        XCTAssertTrue(element("screen.today").exists)
    }

    @MainActor
    private func captureDiagnostics() {
        if let app {
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.lifetime = .keepAlways
            add(screenshot)
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Accessibility hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
        }
    }

    @MainActor
    func testLaunchShowsToday() {
        launchApp()
        XCTAssertTrue(element("screen.today").exists)
        XCTAssertEqual(element("today.goal").value as? String, "30")
        XCTAssertFalse(app.buttons["today.endSession"].exists)
    }

    @MainActor
    func testHistoryLoads() {
        launchApp()
        openTab("tab.history", index: 1, screen: "screen.history")
        XCTAssertTrue(app.buttons["history.addSession"].waitForExistence(timeout: timeout))
        XCTAssertEqual(historyRows.count, 0)
    }

    @MainActor
    func testSettingsLoads() {
        launchApp()
        openTab("tab.settings", index: 2, screen: "screen.settings")
        let stepper = app.steppers["settings.goalStepper"]
        XCTAssertTrue(stepper.waitForExistence(timeout: timeout))
        XCTAssertEqual(stepper.value as? String, "30")
    }

    @MainActor
    func testStartSessionShowsActiveState() {
        launchApp()
        startSession()
        XCTAssertFalse(app.buttons["today.startSession"].exists)
        XCTAssertTrue(element("today.elapsedSeconds").exists)
    }

    @MainActor
    func testEndSessionShowsInactiveState() {
        launchApp()
        startSession()
        endSession()
        XCTAssertFalse(app.buttons["today.endSession"].exists)
        XCTAssertFalse(element("today.elapsedSeconds").exists)
    }

    @MainActor
    func testCompletedSessionAppearsInHistoryAndSurvivesRelaunch() {
        launchApp()
        startSession()
        endSession()
        openTab("tab.history", index: 1, screen: "screen.history")
        XCTAssertTrue(historyRows.firstMatch.waitForExistence(timeout: timeout))
        // Each local-day segment has its own stable row ID, including across midnight.
        let recordIdentifier = historyRows.firstMatch.identifier
        XCTAssertFalse(historyRows.firstMatch.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["today.startSession"].waitForExistence(timeout: timeout))
        openTab("tab.history", index: 1, screen: "screen.history")
        let savedRow = app.buttons.matching(identifier: recordIdentifier).firstMatch
        XCTAssertTrue(savedRow.waitForExistence(timeout: timeout))
        tapWhenReady(savedRow)
        XCTAssertTrue(element("screen.sessionDetail").waitForExistence(timeout: timeout))
        waitUntil("Saved activity has a positive visible duration", element: element("sessionDetail.duration"),
                  predicate: NSPredicate(format: "value.intValue >= 1"))
    }

    @MainActor
    func testDailyGoalPersistsAfterRelaunch() {
        launchApp()
        openTab("tab.settings", index: 2, screen: "screen.settings")
        let stepper = app.steppers["settings.goalStepper"]
        XCTAssertTrue(stepper.waitForExistence(timeout: timeout))
        let original = stepper.value as? String
        XCTAssertEqual(original, "30")
        // Use the system stepper's child control, not a localized Increment/Decrement label.
        tapWhenReady(stepper.buttons.element(boundBy: 0))
        waitUntil("One step changes the goal by one minute", element: stepper,
                  predicate: NSPredicate(format: "value IN %@", ["29", "31"]))
        let updated = stepper.value as? String
        XCTAssertNotNil(updated)
        tapWhenReady(app.buttons["settings.saveGoal"])
        XCTAssertTrue(element("settings.goalSaved").waitForExistence(timeout: timeout))
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["today.startSession"].waitForExistence(timeout: timeout))
        XCTAssertEqual(element("today.goal").value as? String, updated)
        openTab("tab.settings", index: 2, screen: "screen.settings")
        XCTAssertTrue(stepper.waitForExistence(timeout: timeout))
        XCTAssertEqual(stepper.value as? String, updated)
    }

    @MainActor
    func testActiveSessionRestoresAfterRelaunch() {
        launchApp()
        startSession()
        waitForElapsedSeconds(1)
        let elapsedBefore = elapsedSeconds
        let startLabel = element("today.sessionStart").label
        XCTAssertFalse(startLabel.isEmpty)
        let activeMarker = app.staticTexts.matching(
            NSPredicate(format: "identifier BEGINSWITH %@", "today.activeSession.")
        ).firstMatch
        XCTAssertTrue(activeMarker.waitForExistence(timeout: timeout))
        let activeIdentifier = activeMarker.identifier
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["today.endSession"].waitForExistence(timeout: timeout))
        XCTAssertTrue(app.staticTexts[activeIdentifier].waitForExistence(timeout: timeout))
        XCTAssertEqual(element("today.sessionStart").label, startLabel)
        XCTAssertFalse(app.buttons["today.startSession"].exists)
        waitForElapsedSeconds(elapsedBefore)
        endSession()
    }

    @MainActor private var historyRows: XCUIElementQuery {
        app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "history.session."))
    }

    @MainActor private var elapsedSeconds: Int {
        Int(element("today.elapsedSeconds").value as? String ?? "") ?? -1
    }

    @MainActor private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    @MainActor private func openTab(_ identifier: String, index: Int, screen: String) {
        let tabBar = app.tabBars.firstMatch
        XCTAssertTrue(tabBar.waitForExistence(timeout: timeout))
        let identified = tabBar.buttons.matching(identifier: identifier).firstMatch
        // SwiftUI on some OS versions does not forward tabItem identifiers to UIKit.
        // Fall back to the app's fixed tab order, never localized visible text.
        let tab = identified.exists ? identified : tabBar.buttons.element(boundBy: index)
        tapWhenReady(tab)
        waitUntil("Requested tab is selected", element: tab, predicate: NSPredicate(format: "selected == true"))
        XCTAssertTrue(element(screen).waitForExistence(timeout: timeout))
    }

    @MainActor private func startSession() {
        tapWhenReady(app.buttons["today.startSession"])
        XCTAssertTrue(app.buttons["today.endSession"].waitForExistence(timeout: timeout))
        waitUntil("Start has been saved", element: app.buttons["today.endSession"],
                  predicate: NSPredicate(format: "enabled == true"))
    }

    @MainActor private func endSession() {
        // Wait on real displayed time, not a fixed delay or a mocked persistence bypass.
        waitForElapsedSeconds(1)
        tapWhenReady(app.buttons["today.endSession"])
        XCTAssertTrue(app.buttons["today.startSession"].waitForExistence(timeout: timeout))
        waitUntil("End has been saved", element: app.buttons["today.startSession"],
                  predicate: NSPredicate(format: "enabled == true"))
    }

    @MainActor private func tapWhenReady(_ control: XCUIElement) {
        XCTAssertTrue(control.waitForExistence(timeout: timeout))
        // Keep small installed iPhones usable without assuming a particular screen size.
        for _ in 0..<3 {
            if control.isHittable { break }
            app.swipeUp()
        }
        waitUntil("Control is enabled and hittable: \(control.identifier)", element: control,
                  predicate: NSPredicate(format: "enabled == true AND hittable == true"))
        control.tap()
    }

    @MainActor private func waitForElapsedSeconds(_ minimum: Int) {
        waitUntil("Timer shows at least \(minimum) elapsed seconds", element: element("today.elapsedSeconds"),
                  predicate: NSPredicate(format: "value.intValue >= %d", minimum))
    }

    @MainActor private func waitUntil(_ description: String, element: XCUIElement, predicate: NSPredicate) {
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        let result = XCTWaiter.wait(for: [expectation], timeout: timeout)
        if result != .completed { captureDiagnostics() }
        XCTAssertEqual(result, .completed, description)
    }
}
