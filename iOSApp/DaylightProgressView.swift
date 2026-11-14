import DaylightCore
import SwiftUI

struct DaylightProgressView: View {
    @State private var progress = DaylightProgress()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    Label("今日户外时长", systemImage: "sun.max.fill")
                        .font(.title2)
                        .foregroundStyle(.orange)

                    Text("\(progress.outdoorMinutes) / \(progress.goalMinutes) 分钟")
                        .font(.largeTitle.bold())
                        .monospacedDigit()

                    ProgressView(value: progress.completionRatio, total: 1) {
                        Text("每日目标")
                    } currentValueLabel: {
                        Text("\(Int(progress.completionRatio * 100))%")
                    }
                    .tint(.orange)

                    Text(progress.remainingMinutes == 0
                         ? "今日目标已完成"
                         : "还需 \(progress.remainingMinutes) 分钟")
                        .font(.headline)

                    Button {
                        progress.recordOutdoorMinutes(5)
                    } label: {
                        Label("记录 5 分钟户外活动", systemImage: "plus")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)

                    Text("本阶段为手动记录演示，仅保留本次会话的数据。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                .padding()
            }
            .navigationTitle("日光习惯")
        }
    }
}
