import XCTest

final class DaylightUITests: XCTestCase {
    @MainActor private var app: XCUIApplication!
    private let timeout: TimeInterval = 15

    @MainActor
    private func launchApp() {
        continueAfterFailure = false
        // Explicit ID also fails safely if someone accidentally runs the tests in Debug.
        app = XCUIApplication(bundleIdentifier: "org.example.daylight.ios.uitesting")
        let application = app!
        // Do not make launch implicitly terminate a process left by another test.
        Self.stopApplication(application, timeout: timeout)
        let cleanupTimeout = timeout
        addTeardownBlock { @MainActor [application] () async throws in
            Self.stopApplication(application, timeout: cleanupTimeout)
        }
        // New storage per test method; keep this environment for relaunch within a test.
        app.launchEnvironment["DAYLIGHT_UI_TEST_NAMESPACE"] = UUID().uuidString
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        XCTContext.runActivity(named: "Launch fresh isolated journal") { _ in
            app.launch()
            XCTAssertTrue(app.wait(for: .runningForeground, timeout: timeout))
            waitForElement(app.buttons["today.startSession"])
        }
        XCTAssertTrue(element("screen.today").exists)
    }

    @MainActor
    private static func stopApplication(_ application: XCUIApplication, timeout: TimeInterval) {
        guard application.state != .notRunning else { return }
        XCTContext.runActivity(named: "Background and terminate test application") { _ in
            // Leave the foreground before requesting termination, including when
            // the previous screen is still completing an accessibility transition.
            if application.state == .runningForeground {
                XCUIDevice.shared.press(.home)
            }
            application.terminate()
            XCTAssertTrue(application.wait(for: .notRunning, timeout: timeout),
                          "The old application process must stop before another launch")
        }
    }

    @MainActor
    private func relaunchApp(expectedControl: String) {
        XCTContext.runActivity(named: "Relaunch the same persisted journal") { _ in
            Self.stopApplication(app, timeout: timeout)
            // Keep the same application, bundle ID and namespace. No data reset.
            app.launch()
            XCTAssertTrue(app.wait(for: .runningForeground, timeout: timeout))
            waitForElement(app.buttons[expectedControl])
        }
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
        waitForElement(app.buttons["history.addSession"])
        XCTAssertEqual(historyRows.count, 0)
    }

    @MainActor
    func testSettingsLoads() {
        launchApp()
        openTab("tab.settings", index: 2, screen: "screen.settings")
        let stepper = app.steppers["settings.goalStepper"]
        waitForElement(stepper)
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
        let originalRow = historyRows.firstMatch
        waitForElement(originalRow)
        // Each local-day segment has its own stable row ID, including across midnight.
        let recordIdentifier = originalRow.identifier
        XCTAssertFalse(originalRow.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        relaunchApp(expectedControl: "today.startSession")
        openTab("tab.history", index: 1, screen: "screen.history")
        let savedRow = app.buttons.matching(identifier: recordIdentifier).firstMatch
        tapWhenReady(savedRow)
        waitForElement(element("screen.sessionDetail"))
        waitUntil("Saved activity has a positive visible duration", element: element("sessionDetail.duration"),
                  predicate: NSPredicate(format: "value.intValue >= 1"))
    }

    @MainActor
    func testDailyGoalPersistsAfterRelaunch() {
        launchApp()
        openTab("tab.settings", index: 2, screen: "screen.settings")
        let stepper = app.steppers["settings.goalStepper"]
        waitForElement(stepper)
        let original = stepper.value as? String
        XCTAssertEqual(original, "30")
        // Use the system stepper's child control, not a localized Increment/Decrement label.
        tapWhenReady(stepper.buttons.element(boundBy: 0))
        waitUntil("One step changes the goal by one minute", element: stepper,
                  predicate: NSPredicate(format: "value IN %@", ["29", "31"]))
        let updated = stepper.value as? String
        XCTAssertNotNil(updated)
        tapWhenReady(app.buttons["settings.saveGoal"])
        waitForElement(element("settings.goalSaved"))
        relaunchApp(expectedControl: "today.startSession")
        XCTAssertEqual(element("today.goal").value as? String, updated)
        openTab("tab.settings", index: 2, screen: "screen.settings")
        waitForElement(stepper)
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
        waitForElement(activeMarker)
        let activeIdentifier = activeMarker.identifier
        relaunchApp(expectedControl: "today.endSession")
        waitForElement(app.staticTexts[activeIdentifier])
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
        // These identifiers belong to Text views, so avoid a whole-tree Any query.
        if ["today.goal", "today.elapsedSeconds", "today.sessionStart", "settings.goalSaved"].contains(identifier) {
            return app.staticTexts[identifier]
        }
        // Screen containers and the combined detail row vary in accessibility type.
        return app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    @MainActor private func openTab(_ identifier: String, index: Int, screen: String) {
        let tabBar = app.tabBars.firstMatch
        waitForElement(tabBar)
        let identified = tabBar.buttons.matching(identifier: identifier).firstMatch
        // SwiftUI on some OS versions does not forward tabItem identifiers to UIKit.
        // Fall back to the app's fixed tab order, never localized visible text.
        let tab = identified.exists ? identified : tabBar.buttons.element(boundBy: index)
        tapWhenReady(tab)
        waitUntil("Requested tab is selected", element: tab, predicate: NSPredicate(format: "selected == true"))
        waitForElement(element(screen))
    }

    @MainActor private func startSession() {
        tapWhenReady(app.buttons["today.startSession"])
        waitUntil("Start has been saved", element: app.buttons["today.endSession"],
                  predicate: NSPredicate(format: "exists == true AND enabled == true"))
    }

    @MainActor private func endSession() {
        // Wait on real displayed time, not a fixed delay or a mocked persistence bypass.
        waitForElapsedSeconds(1)
        tapWhenReady(app.buttons["today.endSession"])
        waitUntil("End has been saved", element: app.buttons["today.startSession"],
                  predicate: NSPredicate(format: "exists == true AND enabled == true"))
    }

    @MainActor private func tapWhenReady(_ control: XCUIElement) {
        let ready = NSPredicate(format: "exists == true AND enabled == true AND hittable == true")
        // Most controls are already ready. Avoid a mandatory expectation polling
        // cycle and repeated identifier/hittability lookups for every tap.
        if ready.evaluate(with: control) {
            control.tap()
            return
        }
        waitForElement(control)
        // Keep small installed iPhones usable without assuming a particular screen size.
        for _ in 0..<3 {
            if control.isHittable { break }
            app.swipeUp()
        }
        waitUntil("Control is enabled and hittable", element: control, predicate: ready)
        control.tap()
    }

    @MainActor private func waitForElement(_ control: XCUIElement) {
        if !control.exists {
            XCTAssertTrue(control.waitForExistence(timeout: timeout))
        }
    }

    @MainActor private func waitForElapsedSeconds(_ minimum: Int) {
        waitUntil("Timer shows at least \(minimum) elapsed seconds", element: element("today.elapsedSeconds"),
                  predicate: NSPredicate(format: "value.intValue >= %d", minimum))
    }

    @MainActor private func waitUntil(_ description: String, element: XCUIElement, predicate: NSPredicate) {
        if predicate.evaluate(with: element) { return }
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        let result = XCTWaiter.wait(for: [expectation], timeout: timeout)
        if result != .completed { captureDiagnostics() }
        XCTAssertEqual(result, .completed, description)
    }
}
