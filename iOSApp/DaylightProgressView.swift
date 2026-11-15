import DaylightCore
import SwiftUI

struct DaylightProgressView: View {
    @ObservedObject var store: DaylightStore
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            if store.isLoaded {
                TabView {
                    TodayView(store: store)
                        .tabItem {
                            Label("今日", systemImage: "sun.max")
                                .accessibilityIdentifier("tab.today")
                        }
                    DaylightHistoryView(store: store)
                        .tabItem {
                            Label("历史", systemImage: "calendar")
                                .accessibilityIdentifier("tab.history")
                        }
                    DaylightSettingsView(store: store)
                        .tabItem {
                            Label("设置", systemImage: "gearshape")
                                .accessibilityIdentifier("tab.settings")
                        }
                }
            } else {
                VStack(spacing: 20) {
                    Text("日光习惯").font(.title)
                    if store.isBusy {
                        ProgressView("正在恢复记录")
                    } else {
                        Text("尚未载入记录。读取失败时不会覆盖原文件。")
                        Button("重新读取") { Task { await store.load() } }
                    }
                }
                .padding()
            }
        }
        .task { await store.load() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { store.refreshClock() }
        }
        .alert("操作未完成", isPresented: Binding(
            get: { store.errorMessage != nil },
            set: { if !$0 { store.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) { store.errorMessage = nil }
        } message: {
            Text(store.errorMessage ?? "")
        }
    }
}

private struct TodayView: View {
    @ObservedObject var store: DaylightStore

    var body: some View {
        NavigationStack {
            TimelineView(.periodic(from: store.referenceDate, by: 1)) { _ in
                today(at: Date())
            }
            .navigationTitle("今日户外活动")
            .accessibilityIdentifier("screen.today")
        }
    }

    private func today(at now: Date) -> some View {
        let calendar = Calendar.current
        var sessions = store.journal.sessions
        if let active = store.journal.activeSession,
           let provisional = try? active.finished(at: now) {
            sessions.append(provisional)
        }
        let summary = try? DailyDaylightSummary(
            dayContaining: now, sessions: sessions,
            goalMinutes: store.journal.goalMinutes, calendar: calendar
        )
        return ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if let summary {
                    Text(DaylightFormatting.duration(summary.totalDuration))
                        .font(.title.bold()).monospacedDigit()
                        .accessibilityLabel("今日累计 \(DaylightFormatting.duration(summary.totalDuration))")
                    Text("每日目标：\(summary.progress.goalMinutes) 分钟")
                        .accessibilityIdentifier("today.goal")
                        .accessibilityValue(String(summary.progress.goalMinutes))
                    ProgressView(value: summary.completionRatio, total: 1)
                        .tint(.orange)
                        .accessibilityLabel("今日目标进度")
                        .accessibilityValue("百分之 \(Int(summary.completionRatio * 100))")
                    Text(summary.remainingMinutes == 0
                         ? "今日目标已完成"
                         : "还需 \(summary.remainingMinutes) 分钟（按完整分钟计算）")
                    if store.journal.activeSession != nil {
                        Text("今日累计包含正在记录的时间；结束后保存为完整记录。")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                } else {
                    Text("当前日历无法计算今日汇总，请检查系统日期设置。")
                }
                if let active = store.journal.activeSession {
                    Text("本次计时").font(.headline)
                        .accessibilityIdentifier("today.activeSession.\(active.id.uuidString)")
                    Text(DaylightFormatting.duration(active.elapsed(at: now)))
                        .font(.title2).monospacedDigit()
                        .accessibilityIdentifier("today.elapsedSeconds")
                        .accessibilityLabel("本次计时（秒）")
                        .accessibilityValue(String(Int(active.elapsed(at: now))))
                    Text("开始于 \(active.start.formatted(date: .abbreviated, time: .standard))")
                        .font(.footnote)
                        .accessibilityIdentifier("today.sessionStart")
                    if now < active.start {
                        Text("系统时间早于开始时间。请校正时间后结束记录；已保存的开始时间保持不变。")
                            .foregroundStyle(.red)
                    }
                    Button("结束并保存", role: .destructive) {
                        Task { await store.finish() }
                    }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("today.endSession")
                    .disabled(store.isBusy)
                } else {
                    Button { Task { await store.start() } } label: {
                        Label("开始户外活动", systemImage: "play.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("today.startSession")
                    .disabled(store.isBusy)
                }
                if store.isBusy { ProgressView("正在保存") }
                Text("记录的是你主动声明的户外活动时间，不是传感器测量的真实日光暴露。")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
        }
    }
}
