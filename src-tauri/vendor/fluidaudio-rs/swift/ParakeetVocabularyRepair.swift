import Foundation
import FluidAudio

enum ParakeetVocabularyRepair {
    private static let vocabularyFileName = "parakeet_vocab.json"

    static func ensurePresent(
        modelDirectory: URL,
        repository: Repo = .parakeetV3,
        fetch: (URL, String) async throws -> Data
    ) async throws {
        let repositoryDirectory = modelDirectory.deletingLastPathComponent()
            .appendingPathComponent(repository.folderName, isDirectory: true)
        let vocabularyURL = repositoryDirectory.appendingPathComponent(vocabularyFileName)

        if let attributes = try? FileManager.default.attributesOfItem(atPath: vocabularyURL.path) {
            guard attributes[.type] as? FileAttributeType == .typeRegular else {
                throw CocoaError(.fileReadCorruptFile, userInfo: [NSFilePathErrorKey: vocabularyURL.path])
            }
            if let data = try? Data(contentsOf: vocabularyURL), isValidVocabulary(data) {
                return
            }
        }

        let remoteURL = try ModelRegistry.resolveModel(repository.remotePath, vocabularyFileName)
        let data = try await fetch(remoteURL, vocabularyFileName)
        guard isValidVocabulary(data) else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [NSFilePathErrorKey: vocabularyURL.path])
        }

        try FileManager.default.createDirectory(
            at: repositoryDirectory,
            withIntermediateDirectories: true
        )
        try data.write(to: vocabularyURL, options: .atomic)
    }

    private static func isValidVocabulary(_ data: Data) -> Bool {
        guard let vocabulary = try? JSONSerialization.jsonObject(with: data) as? [String: String] else {
            return false
        }
        return !vocabulary.isEmpty && vocabulary.keys.allSatisfy({ Int($0) != nil })
    }
}
