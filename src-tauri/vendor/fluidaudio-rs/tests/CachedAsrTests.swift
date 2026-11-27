import Foundation
import XCTest
import FluidAudio
@testable import FluidAudioBridge

final class CachedAsrTests: XCTestCase {
    func testCachedEntryPointsRejectNullPointersAndUnsupportedVersions() {
        XCTAssertEqual(fluidaudio_initialize_asr_version_cached(nil, 3, nil), -1)
        XCTAssertEqual(fluidaudio_initialize_qwen3_asr_cached(nil, nil), -1)
        let bridge = fluidaudio_bridge_create()
        defer { fluidaudio_bridge_destroy(bridge) }
        XCTAssertEqual(fluidaudio_initialize_asr_version_cached(bridge, 99, nil), -1)
        XCTAssertEqual(fluidaudio_initialize_asr_version_cached(bridge, 3, nil), -1)
        XCTAssertEqual(fluidaudio_initialize_qwen3_asr_cached(bridge, nil), -1)
        "".withCString { path in
            XCTAssertEqual(fluidaudio_initialize_asr_version_cached(bridge, 3, path), -1)
            XCTAssertEqual(fluidaudio_initialize_qwen3_asr_cached(bridge, path), -1)
        }
        [CChar(bitPattern: 0xff), 0].withUnsafeBufferPointer { path in
            XCTAssertEqual(fluidaudio_initialize_asr_version_cached(bridge, 3, path.baseAddress), -1)
            XCTAssertEqual(fluidaudio_initialize_qwen3_asr_cached(bridge, path.baseAddress), -1)
        }
    }

    func testCachedEntryPointsRejectMissingAndEmptyModelDirectories() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let bridge = fluidaudio_bridge_create()
        defer { fluidaudio_bridge_destroy(bridge) }
        for create in [false, true] {
            if create { try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true) }
            root.path.withCString { path in
                XCTAssertEqual(fluidaudio_initialize_asr_version_cached(bridge, 2, path), -1)
                XCTAssertEqual(fluidaudio_initialize_asr_version_cached(bridge, 3, path), -1)
                XCTAssertEqual(fluidaudio_initialize_qwen3_asr_cached(bridge, path), -1)
                XCTAssertEqual(fluidaudio_initialize_asr_version_cached(bridge, 99, path), -1)
            }
        }
        XCTAssertEqual(fluidaudio_is_asr_available(bridge), 0)
        let file = root.appendingPathComponent("ordinary-file")
        try Data().write(to: file)
        file.path.withCString { path in
            XCTAssertEqual(fluidaudio_initialize_asr_version_cached(bridge, 3, path), -1)
            XCTAssertEqual(fluidaudio_initialize_qwen3_asr_cached(bridge, path), -1)
        }
    }

    func testCachedVocabularyRejectsCorruptTokensAndNeverRepairsFiles() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let vocabulary = root.appendingPathComponent(ModelNames.ASR.vocabularyFile)
        let bridge = fluidaudio_bridge_create()
        defer { fluidaudio_bridge_destroy(bridge) }
        for value in ["{", "{}", "[]", "{\"x\":\"a\"}", "{\"-1\":\"a\"}", "{\"1\":\"a\",\"01\":\"b\"}"] {
            let data = Data(value.utf8)
            try data.write(to: vocabulary)
            XCTAssertThrowsError(try CachedParakeetModels.vocabulary(directory: root))
            root.path.withCString { path in
                XCTAssertEqual(fluidaudio_initialize_asr_version_cached(bridge, 3, path), -1)
            }
            XCTAssertEqual(try Data(contentsOf: vocabulary), data)
            XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [ModelNames.ASR.vocabularyFile])
        }
        try Data(#"{"0":"blank","1":"a"}"#.utf8).write(to: vocabulary)
        XCTAssertEqual(try CachedParakeetModels.vocabulary(directory: root), [0: "blank", 1: "a"])
        root.path.withCString { path in
            XCTAssertEqual(fluidaudio_initialize_asr_version_cached(bridge, 3, path), -1)
        }
        XCTAssertTrue(FileManager.default.fileExists(atPath: vocabulary.path))
    }

    func testCachedParakeetLoadsInstalledModelsWhenRuntimeFixtureIsRequested() throws {
        guard let path = ProcessInfo.processInfo.environment["OFFICEKIT_CACHED_PARAKEET_TEST_PATH"] else {
            throw XCTSkip("Set OFFICEKIT_CACHED_PARAKEET_TEST_PATH to exercise actual cached model loading")
        }
        let bridge = fluidaudio_bridge_create()
        defer { fluidaudio_bridge_destroy(bridge) }
        path.withCString { path in
            XCTAssertEqual(fluidaudio_initialize_asr_version_cached(bridge, 3, path), 0)
        }
        XCTAssertEqual(fluidaudio_is_asr_available(bridge), 1)
    }
}
