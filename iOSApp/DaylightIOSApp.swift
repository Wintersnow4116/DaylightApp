import SwiftUI

@main
struct DaylightIOSApp: App {
    @StateObject private var store = DaylightStore()

    var body: some Scene {
        WindowGroup {
            DaylightProgressView(store: store)
        }
    }
}
