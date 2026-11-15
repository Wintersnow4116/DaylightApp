import Foundation

/// Serialized file I/O kept off the UI actor. The caller supplies a durable file location.
public actor DaylightJournalFileStore: DaylightJournalStorage {
    private let fileURL: URL
    private let fileAccess: any DaylightJournalFileAccess
    private var validatedExistingState = false

    public init(
        fileURL: URL,
        fileAccess: any DaylightJournalFileAccess = FoundationDaylightJournalFileAccess()
    ) {
        self.fileURL = fileURL
        self.fileAccess = fileAccess
    }

    public func load() throws -> DaylightJournal {
        validatedExistingState = false
        let data: Data
        do {
            data = try fileAccess.read(from: fileURL)
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile {
            validatedExistingState = true
            return DaylightJournal()
        }
        // Permission, corruption and schema errors propagate; never silently reset data.
        let journal = try JSONDecoder().decode(DaylightJournal.self, from: data)
        validatedExistingState = true
        return journal
    }

    public func save(_ journal: DaylightJournal) throws {
        // A fresh store must not overwrite unreadable/corrupt existing data, even
        // when its caller forgot to load first. Failed saves require validation again.
        if !validatedExistingState { _ = try load() }
        let data = try JSONEncoder().encode(journal)
        do {
            try fileAccess.createDirectory(at: fileURL.deletingLastPathComponent())
            try fileAccess.writeAtomically(data, to: fileURL)
        } catch {
            validatedExistingState = false
            throw error
        }
    }
}
