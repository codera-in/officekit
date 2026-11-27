import CoreML
import Foundation
import FluidAudio

/// FluidAudio's AsrModels.load may delete and re-download a corrupt cache. This
/// path uses only CoreML file loading, so failed first use preserves local files.
enum CachedParakeetModels {
    static func vocabulary(directory: URL) throws -> [Int: String] {
        let data = try Data(contentsOf: directory.appendingPathComponent(ModelNames.ASR.vocabularyFile))
        guard let values = try JSONSerialization.jsonObject(with: data) as? [String: String],
              !values.isEmpty else { throw CocoaError(.fileReadCorruptFile) }
        var result: [Int: String] = [:]
        for (key, value) in values {
            guard let id = Int(key), id >= 0, result[id] == nil else {
                throw CocoaError(.fileReadCorruptFile)
            }
            result[id] = value
        }
        return result
    }

    static func load(directory: URL, version: AsrModelVersion) throws -> AsrModels {
        let vocabulary = try vocabulary(directory: directory)
        let configuration = MLModelConfiguration()
        configuration.computeUnits = .cpuAndNeuralEngine
        configuration.allowLowPrecisionAccumulationOnGPU = true
        let preprocessorConfiguration = MLModelConfiguration()
        preprocessorConfiguration.computeUnits = .cpuOnly
        let encoderName = version == .v3 ? ParakeetEncoderPrecision.int8.encoderFileName : ModelNames.ASR.encoderFile
        let jointName = version == .v3 ? ModelNames.ASR.jointV3File : ModelNames.ASR.jointFile
        return try AsrModels(
            encoder: MLModel(contentsOf: directory.appendingPathComponent(encoderName), configuration: configuration),
            preprocessor: MLModel(contentsOf: directory.appendingPathComponent(ModelNames.ASR.preprocessorFile), configuration: preprocessorConfiguration),
            decoder: MLModel(contentsOf: directory.appendingPathComponent(ModelNames.ASR.decoderFile), configuration: configuration),
            joint: MLModel(contentsOf: directory.appendingPathComponent(jointName), configuration: configuration),
            configuration: configuration,
            vocabulary: vocabulary,
            version: version
        )
    }
}
