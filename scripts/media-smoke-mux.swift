import AVFoundation
import Foundation

guard CommandLine.arguments.count == 4 else { exit(2) }
let videoAsset = AVURLAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
let audioAsset = AVURLAsset(url: URL(fileURLWithPath: CommandLine.arguments[2]))
let outputURL = URL(fileURLWithPath: CommandLine.arguments[3])
let composition = AVMutableComposition()
guard let videoSource = videoAsset.tracks(withMediaType: .video).first,
      let audioSource = audioAsset.tracks(withMediaType: .audio).first,
      let videoTrack = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid),
      let audioTrack = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid) else {
    fatalError("Could not create audio/video fixture tracks")
}
try videoTrack.insertTimeRange(videoSource.timeRange, of: videoSource, at: .zero)
try audioTrack.insertTimeRange(CMTimeRange(start: .zero, duration: videoSource.timeRange.duration), of: audioSource, at: .zero)
guard let exporter = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetPassthrough),
      exporter.supportedFileTypes.contains(.mov) else { fatalError("Could not create audio/video fixture") }
exporter.outputURL = outputURL
exporter.outputFileType = .mov
exporter.metadata = videoAsset.metadata
let finished = DispatchSemaphore(value: 0)
exporter.exportAsynchronously { finished.signal() }
guard finished.wait(timeout: .now() + 60) == .success, exporter.status == .completed else {
    fatalError(exporter.error?.localizedDescription ?? "Audio/video fixture export failed")
}
