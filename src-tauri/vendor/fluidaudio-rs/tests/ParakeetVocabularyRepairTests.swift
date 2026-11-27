import Foundation
import XCTest
import FluidAudio
@testable import FluidAudioBridge

final class ParakeetVocabularyRepairTests: XCTestCase {
    private struct Fixture {
        let root: URL
        let modelDirectory: URL
        let vocabularyURL: URL
    }

    private func makeFixture(repository: Repo = .parakeetV3) -> Fixture {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let modelDirectory = root.appendingPathComponent("models/\(repository.folderName)", isDirectory: true)
        let repositoryDirectory = modelDirectory.deletingLastPathComponent()
            .appendingPathComponent(repository.folderName, isDirectory: true)
        return Fixture(
            root: root,
            modelDirectory: modelDirectory,
            vocabularyURL: repositoryDirectory.appendingPathComponent("parakeet_vocab.json")
        )
    }

    func testExistingVocabularyIsPreservedWithoutNetworkFetch() async throws {
        let fixture = makeFixture()
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        let expected = Data(#"{"0":"blank","1":"a"}"#.utf8)
        try FileManager.default.createDirectory(
            at: fixture.vocabularyURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try expected.write(to: fixture.vocabularyURL)
        var fetchCount = 0

        try await ParakeetVocabularyRepair.ensurePresent(modelDirectory: fixture.modelDirectory) { _, _ in
            fetchCount += 1
            throw CocoaError(.fileReadUnknown)
        }

        XCTAssertEqual(fetchCount, 0)
        XCTAssertEqual(try Data(contentsOf: fixture.vocabularyURL), expected)
    }

    func testMissingVocabularyFetchesExpectedHuggingFaceFileAndWritesAtomically() async throws {
        let fixture = makeFixture()
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        let expected = Data(#"{"0":"blank","1":"a"}"#.utf8)
        var fetchedURL: URL?
        var fetchedDescription: String?

        try await ParakeetVocabularyRepair.ensurePresent(modelDirectory: fixture.modelDirectory) { url, description in
            fetchedURL = url
            fetchedDescription = description
            return expected
        }

        XCTAssertEqual(
            fetchedURL?.absoluteString,
            "https://huggingface.co/FluidInference/parakeet-tdt-0.6b-v3-coreml/resolve/main/parakeet_vocab.json"
        )
        XCTAssertEqual(fetchedDescription, "parakeet_vocab.json")
        XCTAssertEqual(try Data(contentsOf: fixture.vocabularyURL), expected)
    }

    func testMissingV2VocabularyFetchesTheEnglishModelRepository() async throws {
        let fixture = makeFixture(repository: .parakeetV2)
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        let expected = Data(#"{"0":"blank","1":"a"}"#.utf8)
        var fetchedURL: URL?

        try await ParakeetVocabularyRepair.ensurePresent(
            modelDirectory: fixture.modelDirectory,
            repository: .parakeetV2
        ) { url, _ in
            fetchedURL = url
            return expected
        }

        XCTAssertEqual(
            fetchedURL?.absoluteString,
            "https://huggingface.co/FluidInference/parakeet-tdt-0.6b-v2-coreml/resolve/main/parakeet_vocab.json"
        )
        XCTAssertEqual(try Data(contentsOf: fixture.vocabularyURL), expected)
    }

    func testMalformedVocabularyIsNotInstalled() async throws {
        for invalid in ["not-json", "{}", "[]", #"{"0":1}"#, #"{"word":"a"}"#] {
            let fixture = makeFixture()
            defer { try? FileManager.default.removeItem(at: fixture.root) }
            var fetchCount = 0
            do {
                try await ParakeetVocabularyRepair.ensurePresent(modelDirectory: fixture.modelDirectory) { _, _ in
                    fetchCount += 1
                    return Data(invalid.utf8)
                }
                XCTFail("Malformed vocabulary must fail")
            } catch {
                XCTAssertEqual((error as? CocoaError)?.code, .fileReadCorruptFile)
            }
            XCTAssertEqual(fetchCount, 1)
            XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.vocabularyURL.path))
        }
    }

    func testCorruptCachedVocabularyIsRepaired() async throws {
        let fixture = makeFixture()
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        try FileManager.default.createDirectory(
            at: fixture.vocabularyURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data("incomplete download".utf8).write(to: fixture.vocabularyURL)
        let expected = Data(#"{"0":"blank","1":"a"}"#.utf8)
        var fetchCount = 0

        try await ParakeetVocabularyRepair.ensurePresent(modelDirectory: fixture.modelDirectory) { _, _ in
            fetchCount += 1
            return expected
        }

        XCTAssertEqual(fetchCount, 1)
        XCTAssertEqual(try Data(contentsOf: fixture.vocabularyURL), expected)
    }

    func testFailedRepairPreservesCachedBytesForRetry() async throws {
        let fixture = makeFixture()
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        try FileManager.default.createDirectory(
            at: fixture.vocabularyURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let original = Data("unfinished".utf8)
        try original.write(to: fixture.vocabularyURL)
        var fetchCount = 0
        do {
            try await ParakeetVocabularyRepair.ensurePresent(modelDirectory: fixture.modelDirectory) { _, _ in
                fetchCount += 1
                throw URLError(.notConnectedToInternet)
            }
            XCTFail("Failed repair must surface its error")
        } catch {
            XCTAssertEqual((error as? URLError)?.code, .notConnectedToInternet)
        }
        XCTAssertEqual(fetchCount, 1)
        XCTAssertEqual(try Data(contentsOf: fixture.vocabularyURL), original)
    }

    func testSymlinkedOrDirectoryVocabularyIsRejectedWithoutFetching() async throws {
        for useSymlink in [true, false] {
            let fixture = makeFixture()
            defer { try? FileManager.default.removeItem(at: fixture.root) }
            try FileManager.default.createDirectory(
                at: fixture.vocabularyURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let original = Data(#"{"0":"blank"}"#.utf8)
            let target = fixture.root.appendingPathComponent("original.json")
            try original.write(to: target)
            if useSymlink {
                try FileManager.default.createSymbolicLink(at: fixture.vocabularyURL, withDestinationURL: target)
            } else {
                try FileManager.default.createDirectory(at: fixture.vocabularyURL, withIntermediateDirectories: false)
            }
            var fetchCount = 0
            do {
                try await ParakeetVocabularyRepair.ensurePresent(modelDirectory: fixture.modelDirectory) { _, _ in
                    fetchCount += 1
                    return original
                }
                XCTFail("Wrong-type vocabulary must fail")
            } catch {
                XCTAssertEqual((error as? CocoaError)?.code, .fileReadCorruptFile)
            }
            XCTAssertEqual(fetchCount, 0)
            XCTAssertEqual(try Data(contentsOf: target), original)
        }
    }
}
