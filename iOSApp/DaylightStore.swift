import Combine
import DaylightCore
import Foundation

@MainActor
final class DaylightStore: ObservableObject {
    @Published private(set) var journal = DaylightJournal()
    @Published private(set) var isLoaded = false
    @Published private(set) var isBusy = false
    @Published private(set) var referenceDate = Date()
    @Published var errorMessage: String?
    private var fileStore: (any DaylightJournalStorage)?

    init(storage: (any DaylightJournalStorage)? = nil) {
        fileStore = storage
    }

    func load() async {
        guard !isBusy, !isLoaded else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            let storage: any DaylightJournalStorage
            if let fileStore {
                storage = fileStore
            } else {
                let support = try FileManager.default.url(
                    for: .applicationSupportDirectory, in: .userDomainMask,
                    appropriateFor: nil, create: true
                )
                storage = DaylightJournalFileStore(fileURL: try journalURL(in: support))
            }
            journal = try await storage.load()
            fileStore = storage
            isLoaded = true
            errorMessage = nil
            refreshClock()
        } catch {
            errorMessage = "无法读取已保存的数据，已暂停写入以保护原文件。请重试。\n\(error.localizedDescription)"
        }
    }

    func refreshClock() { referenceDate = Date() }

    private func journalURL(in support: URL) throws -> URL {
        #if DAYLIGHT_UI_TESTING
        // Only compiled into the separate UITesting app configuration. Never reset data
        // on launch: a test's namespace must survive terminate/launch persistence checks.
        guard let raw = ProcessInfo.processInfo.environment["DAYLIGHT_UI_TEST_NAMESPACE"],
              let namespace = UUID(uuidString: raw) else {
            throw UIStorageConfigurationError.missingNamespace
        }
        return support.appendingPathComponent("DaylightAppUITests", isDirectory: true)
            .appendingPathComponent(namespace.uuidString, isDirectory: true)
            .appendingPathComponent("journal-v1.json")
        #else
        return support.appendingPathComponent("DaylightApp", isDirectory: true)
            .appendingPathComponent("journal-v1.json")
        #endif
    }

    func start() async {
        guard isLoaded, !isBusy, journal.activeSession == nil else { return }
        do {
            var next = journal
            try next.start(at: Date())
            _ = await commit(next, failure: "开始时间未保存，计时尚未开始，请重试。")
        } catch { report(error) }
    }

    func finish() async {
        guard isLoaded, !isBusy, journal.activeSession != nil else { return }
        do {
            var next = journal
            try next.finish(at: Date())
            _ = await commit(next, failure: "结束记录未保存，计时仍在继续，请重试结束。")
        } catch { report(error) }
    }

    func addManual(start: Date, end: Date) async -> Bool {
        guard isLoaded, !isBusy else { return false }
        guard end <= Date() else {
            errorMessage = "记录结束时间不能在未来。"
            return false
        }
        do {
            var next = journal
            try next.add(DaylightSession(start: start, end: end))
            return await commit(next, failure: "这条记录未保存，请保留表单并重试。")
        } catch { report(error); return false }
    }

    func setGoal(_ minutes: Int) async -> Bool {
        guard isLoaded, !isBusy else { return false }
        do {
            var next = journal
            try next.setGoalMinutes(minutes)
            return await commit(next, failure: "目标未保存，原目标仍有效，请重试。")
        } catch { report(error); return false }
    }

    private func commit(_ next: DaylightJournal, failure: String) async -> Bool {
        guard let fileStore, !isBusy else { return false }
        isBusy = true
        defer { isBusy = false }
        do {
            try await fileStore.save(next)
            journal = next
            errorMessage = nil
            refreshClock()
            return true
        } catch {
            errorMessage = "\(failure)\n\(error.localizedDescription)"
            return false
        }
    }

    private func report(_ error: any Error) {
        switch error as? DaylightRecordError {
        case .invalidInterval:
            errorMessage = "结束时间必须晚于开始时间。若系统时钟被调早，请校正后重试；原计时已保留。"
        case .overlappingSessions:
            errorMessage = "时间与已有记录或进行中的计时重叠，请检查时间；原数据已保留。"
        case .invalidGoal:
            errorMessage = "每日目标必须为 1 至 1440 分钟。"
        default:
            errorMessage = "操作未保存，请检查输入并重试。\n\(error.localizedDescription)"
        }
    }
}

#if DAYLIGHT_UI_TESTING
private enum UIStorageConfigurationError: LocalizedError {
    case missingNamespace

    var errorDescription: String? {
        "UITesting configuration requires a UUID DAYLIGHT_UI_TEST_NAMESPACE; no journal was opened."
    }
}
#endif

enum DaylightFormatting {
    static func duration(_ seconds: TimeInterval) -> String {
        let safe = seconds.isFinite ? max(0, min(seconds, Double(Int.max / 2))) : 0
        let total = Int(safe)
        return "\(total / 3600) 小时 \((total % 3600) / 60) 分 \(total % 60) 秒"
    }
}
