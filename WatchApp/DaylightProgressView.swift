import DaylightCore
import SwiftUI

struct DaylightProgressView: View {
    @State private var progress = DaylightProgress()

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                Label("今日户外", systemImage: "sun.max.fill")
                    .foregroundStyle(.orange)

                Text("\(progress.outdoorMinutes) / \(progress.goalMinutes) 分钟")
                    .font(.headline)
                    .monospacedDigit()

                ProgressView(value: progress.completionRatio, total: 1)
                    .tint(.orange)
                    .accessibilityLabel("每日目标")
                    .accessibilityValue("\(Int(progress.completionRatio * 100))%")

                Text("\(Int(progress.completionRatio * 100))%")
                    .font(.caption)

                Text(progress.remainingMinutes == 0
                     ? "目标已完成"
                     : "还需 \(progress.remainingMinutes) 分钟")
                    .font(.caption)

                Button("记录 5 分钟") {
                    progress.recordOutdoorMinutes(5)
                }
                .buttonStyle(.borderedProminent)

                Text("手动演示 · 仅本次会话")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal)
        }
    }
}
