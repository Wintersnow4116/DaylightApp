import Foundation

/// Serialized file I/O kept off the UI actor. The caller supplies a durable file location.
public actor DaylightJournalFileStore {
    private let fileURL: URL

    public init(fileURL: URL) {
        self.fileURL = fileURL
    }

    public func load() throws -> DaylightJournal {
        let data: Data
        do {
            data = try Data(contentsOf: fileURL)
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile {
            return DaylightJournal()
        }
        // Permission, corruption and schema errors propagate; never silently reset data.
        return try JSONDecoder().decode(DaylightJournal.self, from: data)
    }

    public func save(_ journal: DaylightJournal) throws {
        let data = try JSONEncoder().encode(journal)
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        // Write an auxiliary file and replace the destination only after the write completes.
        try data.write(to: fileURL, options: .atomic)
    }
}
