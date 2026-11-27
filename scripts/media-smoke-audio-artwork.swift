import AVFoundation
import Foundation

guard CommandLine.arguments.count == 4 else { exit(2) }
let audioURL = URL(fileURLWithPath: CommandLine.arguments[1])
let artworkURL = URL(fileURLWithPath: CommandLine.arguments[2])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[3])
let asset = AVURLAsset(url: audioURL)
let artwork = try Data(contentsOf: artworkURL)
let artworkItem = AVMutableMetadataItem()
artworkItem.identifier = .commonIdentifierArtwork
artworkItem.dataType = "com.apple.metadata.datatype.JPEG"
artworkItem.value = artwork as NSData
let titleItem = AVMutableMetadataItem()
titleItem.identifier = .commonIdentifierTitle
titleItem.value = "OfficeKit artwork smoke" as NSString
guard let exporter = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetAppleM4A),
      exporter.supportedFileTypes.contains(.m4a) else { fatalError("Could not create M4A artwork fixture") }
exporter.outputURL = outputURL
exporter.outputFileType = .m4a
exporter.metadata = [titleItem, artworkItem]
let finished = DispatchSemaphore(value: 0)
exporter.exportAsynchronously { finished.signal() }
guard finished.wait(timeout: .now() + 60) == .success, exporter.status == .completed else {
    fatalError(exporter.error?.localizedDescription ?? "Audio artwork fixture export failed")
}
