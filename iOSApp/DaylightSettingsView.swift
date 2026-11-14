import SwiftUI

struct DaylightSettingsView: View {
    @ObservedObject var store: DaylightStore
    @State private var goal = 30
    @State private var saved = false

    var body: some View {
        NavigationStack {
            Form {
                Section("每日目标") {
                    Stepper(value: $goal, in: 1...1440) { Text("\(goal) 分钟") }
                    Button("保存目标") {
                        Task { saved = await store.setGoal(goal) }
                    }
                    .disabled(store.isBusy || goal == store.journal.goalMinutes)
                    if store.isBusy { ProgressView("正在保存") }
                    if saved { Text("目标已保存").foregroundStyle(.secondary) }
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
            .onAppear { goal = store.journal.goalMinutes; saved = false }
            .onChange(of: goal) { _, _ in saved = false }
            .disabled(store.isBusy)
        }
    }
}
