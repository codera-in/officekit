"""Static release-contract tests for the bundled local API process."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TauriBackendSidecarTests(unittest.TestCase):
    def test_tauri_bundle_declares_the_backend_sidecar(self):
        config = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
        mac_config = json.loads((ROOT / "src-tauri/tauri.macos.conf.json").read_text(encoding="utf-8"))

        self.assertIn("binaries/officekit-backend", config["bundle"]["externalBin"])
        self.assertIn(
            "resources/officekit-backend/**/*",
            mac_config["bundle"]["resources"],
        )

    def test_python_sidecar_has_a_loopback_entrypoint(self):
        entry = ROOT / "backend_main.py"
        self.assertTrue(entry.is_file())
        source = entry.read_text(encoding="utf-8")

        self.assertIn('host="127.0.0.1"', source)
        self.assertIn("reload=False", source)
        self.assertIn('"OFFICEKIT_API_PORT", "8000"', source)
        self.assertIn("port=sidecar_api_port()", source)

    def test_tauri_starts_and_stops_the_backend_process(self):
        source = (ROOT / "src-tauri/src/lib.rs").read_text(encoding="utf-8")

        self.assertIn('.sidecar("officekit-backend")', source)
        self.assertIn('TcpStream::connect', source)
        self.assertIn(".try_recv()", source)
        self.assertIn("startup_event_is_failure", source)
        self.assertIn(".kill()", source)
        self.assertIn("RunEvent::Exit", source)
        self.assertIn('.env("OFFICEKIT_API_PORT", address.port().to_string())', source)
        self.assertIn('fn officekit_api_origin(address: State<\'_, BackendApiAddress>)', source)
        self.assertIn('fn select_backend_address_from(preferred: SocketAddr)', source)
        self.assertIn('.env("OFFICEKIT_APP_VERSION", env!("CARGO_PKG_VERSION"))', source)
        self.assertIn('"OFFICEKIT_RELEASE_MANIFEST_URL"', source)
        self.assertIn('"https://officekit.app/releases/latest.json"', source)

    def test_build_script_produces_the_target_triple_sidecar(self):
        source = (ROOT / "scripts/build-backend-sidecar.mjs").read_text(encoding="utf-8")

        self.assertIn("platform === 'darwin' ? '--onedir' : '--onefile'", source)
        self.assertIn("sidecar-launcher.rs", source)
        self.assertIn("--add-data", source)
        self.assertIn("'--print', 'host-tuple'", source)
        self.assertIn("officekit-backend-${targetTriple}", source)

    def test_native_paste_restore_requires_a_complete_bounded_clipboard_snapshot(self):
        source = (ROOT / "src-tauri/macos-dictation.swift").read_text(encoding="utf-8")
        snapshot = source.split("func snapshot(", 1)[1].split("func restore(", 1)[0]

        self.assertNotIn("compactMap", snapshot)
        self.assertIn("guard let data = item.data(forType: type) else { return nil }", snapshot)
        self.assertIn("addingReportingOverflow", snapshot)
        self.assertIn("dictationMaxClipboardSnapshotBytes", snapshot)

    def test_native_audio_stop_preserves_shared_coach_engine_and_waits_for_solo_stop(self):
        source = (ROOT / "src-tauri/macos-dictation.swift").read_text(encoding="utf-8")
        stop = source.split("private func stopLocked() -> Int32 {", 1)[1].split("private func stopAll()", 1)[0]

        shared_capture = stop.split("if dictationCaptureHasActiveOwner", 1)[1].split("let activeEngine", 1)[0]
        self.assertIn("let hasSamples = !samples.isEmpty", shared_capture)
        self.assertNotIn("activeEngine.stop()", shared_capture)
        self.assertLess(stop.index("let activeEngine"), stop.rindex("activeEngine.stop()"))

    def test_parakeet_model_download_repairs_required_vocabulary(self):
        package = (ROOT / "src-tauri/vendor/fluidaudio-rs/Package.swift").read_text(encoding="utf-8")
        resolution = json.loads(
            (ROOT / "src-tauri/vendor/fluidaudio-rs/Package.resolved").read_text(encoding="utf-8")
        )
        bridge = (ROOT / "src-tauri/vendor/fluidaudio-rs/swift/FluidAudioBridge.swift").read_text(
            encoding="utf-8"
        )

        self.assertIn('exact: "0.14.8"', package)
        fluid_audio = next(pin for pin in resolution["pins"] if pin["identity"] == "fluidaudio")
        self.assertEqual(fluid_audio["state"]["version"], "0.14.8")

        repair = bridge.split("private func downloadAndLoadParakeetModels(", 1)[1].split(
            "func initializeAsr(version:", 1
        )[0]
        implementation = (ROOT / "src-tauri/vendor/fluidaudio-rs/swift/ParakeetVocabularyRepair.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("AsrModels.download(", repair)
        self.assertIn("version: version,", repair)
        self.assertIn("case .v2: .parakeetV2", repair)
        self.assertIn("case .v3: .parakeetV3", repair)
        self.assertIn("ParakeetVocabularyRepair.ensurePresent", repair)
        self.assertIn("repository: repository", repair)
        self.assertIn("DownloadUtils.fetchHuggingFaceFile", repair)
        self.assertLess(repair.index("ensurePresent"), repair.index("AsrModels.load(from:"))
        self.assertIn('private static let vocabularyFileName = "parakeet_vocab.json"', implementation)
        self.assertIn("ModelRegistry.resolveModel", implementation)
        self.assertIn("repository: Repo = .parakeetV3", implementation)
        self.assertIn("vocabulary.keys.allSatisfy", implementation)
        self.assertIn("data.write(to: vocabularyURL, options: .atomic)", implementation)
        self.assertGreaterEqual(bridge.count("downloadAndLoadParakeetModels("), 3)

    def test_qwen3_model_avoids_mps_gpu_decoder_path(self):
        bridge = (ROOT / "src-tauri/vendor/fluidaudio-rs/swift/FluidAudioBridge.swift").read_text(
            encoding="utf-8"
        )
        setup = bridge.split("func initializeQwen3Asr(", 1)[1].split(
            "func qwen3TranscribeSamples", 1
        )[0]

        self.assertIn("Qwen3AsrModels.download(progressHandler: progressHandler)", setup)
        self.assertIn("Qwen3AsrManager()", setup)
        self.assertIn(
            "manager.loadModels(from: modelDir, computeUnits: .cpuAndNeuralEngine)",
            setup,
        )


if __name__ == "__main__":
    unittest.main()
