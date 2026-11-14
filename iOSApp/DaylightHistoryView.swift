import DaylightCore
import SwiftUI

struct DaylightHistoryView: View {
    @ObservedObject var store: DaylightStore
    @State private var showingManualEntry = false

    var body: some View {
        NavigationStack {
            TimelineView(.periodic(from: store.referenceDate, by: 60)) { _ in
                history(at: Date())
            }
            .navigationTitle("最近 7 天")
            .toolbar {
                Button { showingManualEntry = true } label: {
                    Label("补记活动", systemImage: "plus")
                }
                .disabled(store.isBusy)
            }
            .sheet(isPresented: $showingManualEntry) {
                ManualSessionView(store: store)
            }
        }
    }

    private func history(at now: Date) -> some View {
        let calendar = Calendar.current
        return List {
            Section {
                Text("仅显示已保存的活动。跨日记录按当前日历和时区拆分；目标比例使用当前设置。")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            ForEach(0..<7, id: \.self) { offset in
                if let date = calendar.date(byAdding: .day, value: -offset, to: now),
                   let summary = try? DailyDaylightSummary(
                    dayContaining: date, sessions: store.journal.sessions,
                    goalMinutes: store.journal.goalMinutes, calendar: calendar
                   ) {
                    Section {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(DaylightFormatting.duration(summary.totalDuration)).font(.headline)
                            Text("目标完成 \(Int(summary.completionRatio * 100))%")
                                .font(.subheadline)
                        }
                        if summary.segments.isEmpty {
                            Text("暂无已保存记录").foregroundStyle(.secondary)
                        }
                        ForEach(summary.segments) { segment in
                            NavigationLink {
                                SessionDetailView(segment: segment)
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("\(segment.start.formatted(date: .omitted, time: .shortened)) – \(segment.end.formatted(date: .omitted, time: .shortened))")
                                    Text(DaylightFormatting.duration(segment.duration))
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    } header: {
                        Text(summary.day, format: .dateTime.month().day().weekday())
                    }
                }
            }
        }
    }
}

private struct SessionDetailView: View {
    let segment: DaylightDaySegment

    var body: some View {
        Form {
            Section("完整记录") {
                detail("开始", segment.session.start.formatted(date: .complete, time: .standard))
                detail("结束", segment.session.end.formatted(date: .complete, time: .standard))
                detail("记录时长", DaylightFormatting.duration(segment.session.duration))
                detail("来源", "用户手动记录")
                detail("记录 ID", segment.session.id.uuidString)
            }
            Section("当天分段") {
                detail("分段开始", segment.start.formatted(date: .abbreviated, time: .standard))
                detail("分段结束", segment.end.formatted(date: .abbreviated, time: .standard))
                detail("计入当天", DaylightFormatting.duration(segment.duration))
                Text("按当前时区 \(TimeZone.current.identifier) 显示。")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("活动详情")
    }

    private func detail(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(value).textSelection(.enabled)
        }
        .accessibilityElement(children: .combine)
    }
}

private struct ManualSessionView: View {
    @ObservedObject var store: DaylightStore
    @Environment(\.dismiss) private var dismiss
    @State private var start = Date().addingTimeInterval(-600)
    @State private var end = Date()

    var body: some View {
        NavigationStack {
            Form {
                Section("手动补记") {
                    DatePicker("开始", selection: $start, in: ...Date(), displayedComponents: [.date, .hourAndMinute])
                    DatePicker("结束", selection: $end, in: ...Date(), displayedComponents: [.date, .hourAndMinute])
                    Text("结束必须晚于开始，且不能与已有活动重叠。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    Button("保存记录") {
                        Task {
                            if await store.addManual(start: start, end: end) { dismiss() }
                        }
                    }
                    .disabled(store.isBusy || end <= start)
                    if store.isBusy { ProgressView("正在保存") }
                    if let error = store.errorMessage { Text(error).foregroundStyle(.red) }
                }
            }
            .navigationTitle("补记户外活动")
            .toolbar {
                Button("取消", role: .cancel) { dismiss() }.disabled(store.isBusy)
            }
            .interactiveDismissDisabled(store.isBusy)
        }
    }
}
