import SwiftUI

struct DaylightSettingsView: View {
    @ObservedObject var store: DaylightStore
    @State private var goal = 30
    @State private var savedGoal: Int?

    var body: some View {
        NavigationStack {
            Form {
                Section("每日目标") {
                    Stepper(value: $goal, in: 1...1440) { Text("\(goal) 分钟") }
                        .accessibilityIdentifier("settings.goalStepper")
                        .accessibilityLabel("每日目标（分钟）")
                        .accessibilityValue(String(goal))
                    Button("保存目标") {
                        let requestedGoal = goal
                        Task {
                            savedGoal = await store.setGoal(requestedGoal) ? requestedGoal : nil
                        }
                    }
                    .disabled(store.isBusy || goal == store.journal.goalMinutes)
                    .accessibilityIdentifier("settings.saveGoal")
                    if store.isBusy { ProgressView("正在保存") }
                    if savedGoal == goal && goal == store.journal.goalMinutes {
                        Text("目标已保存").foregroundStyle(.secondary)
                            .accessibilityIdentifier("settings.goalSaved")
                    }
                    Text("默认 30 分钟，可设置 1 至 1440 分钟。历史比例也按当前目标重新计算。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("数据与说明") {
                    Text("数据仅保存在此 iPhone 的 Application Support 文件中。暂不提供云同步或 Apple Watch 同步。")
                    Text("活动由你主动记录，不是传感器测量到的日光暴露，也不作为医疗建议。")
                    Text("按当前日历和时区统计；更换时区后历史记录会重新归入对应的自然日。")
                }
            }
            .navigationTitle("设置")
            .accessibilityIdentifier("screen.settings")
            .onAppear { goal = store.journal.goalMinutes; savedGoal = nil }
            .onChange(of: store.journal.goalMinutes) { _, minutes in goal = minutes }
            .onChange(of: goal) { _, minutes in
                if savedGoal != minutes { savedGoal = nil }
            }
            .disabled(store.isBusy)
        }
    }
}
