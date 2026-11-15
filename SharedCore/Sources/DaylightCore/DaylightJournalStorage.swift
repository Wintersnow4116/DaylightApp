import Foundation

/// The app uses the same validated journal interface for production and test storage.
public protocol DaylightJournalStorage: Sendable {
    func load() async throws -> DaylightJournal
    func save(_ journal: DaylightJournal) async throws
}

/// A small fault-injection boundary, not a replacement persistence implementation.
/// Implementations must preserve the destination if atomic replacement fails.
public protocol DaylightJournalFileAccess: Sendable {
    func read(from url: URL) throws -> Data
    func createDirectory(at url: URL) throws
    func writeAtomically(_ data: Data, to url: URL) throws
}

public struct FoundationDaylightJournalFileAccess: DaylightJournalFileAccess {
    public init() {}

    public func read(from url: URL) throws -> Data {
        try Data(contentsOf: url)
    }

    public func createDirectory(at url: URL) throws {
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    }

    public func writeAtomically(_ data: Data, to url: URL) throws {
        // Foundation owns the auxiliary-file creation and replacement operation.
        try data.write(to: url, options: .atomic)
    }
}
