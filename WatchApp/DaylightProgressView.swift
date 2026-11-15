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
                    .accessibilityIdentifier("watch.accumulatedMinutes")
                    .accessibilityLabel("Recorded outdoor minutes, daily goal \(progress.goalMinutes) minutes")
                    .accessibilityValue(String(progress.outdoorMinutes))

                ProgressView(value: progress.completionRatio, total: 1)
                    .tint(.orange)
                    .accessibilityIdentifier("watch.goalProgress")
                    .accessibilityLabel("Daily goal")
                    .accessibilityValue("\(Int(progress.completionRatio * 100))%")

                Text("\(Int(progress.completionRatio * 100))%")
                    .font(.caption)
                    .accessibilityIdentifier("watch.completionPercentage")
                    .accessibilityLabel("Goal completion")
                    .accessibilityValue("\(Int(progress.completionRatio * 100))%")

                Text(progress.remainingMinutes == 0
                     ? "目标已完成"
                     : "还需 \(progress.remainingMinutes) 分钟")
                    .font(.caption)
                    .accessibilityIdentifier("watch.remainingMinutes")
                    .accessibilityLabel("Remaining outdoor minutes")
                    .accessibilityValue(String(progress.remainingMinutes))

                Button("记录 5 分钟") {
                    progress.recordOutdoorMinutes(5)
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("watch.recordFiveMinutes")
                .accessibilityLabel("Record 5 outdoor minutes")

                Text("手动演示 · 仅本次会话")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal)
        }
    }
}
