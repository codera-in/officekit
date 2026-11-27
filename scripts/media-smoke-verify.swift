import AVFoundation
import AudioToolbox
import CoreGraphics
import Foundation
import ImageIO

let args = CommandLine.arguments
guard args.count >= 3 else {
    fputs("Usage: swift media-smoke-verify.swift <image|audio|video|video-muted|audio-artwork> <path> [maximum-artwork-edge] | video-speed <source> <output> <factor-percent>\n", stderr)
    exit(2)
}

func firstFramePixels(_ url: URL) -> (Int, Int, [UInt8])? {
    let asset = AVURLAsset(url: url)
    guard let track = asset.tracks(withMediaType: .video).first,
          let reader = try? AVAssetReader(asset: asset) else { return nil }
    let output = AVAssetReaderTrackOutput(track: track, outputSettings: [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
    ])
    guard reader.canAdd(output) else { return nil }
    reader.add(output)
    guard reader.startReading(), let sample = output.copyNextSampleBuffer(),
          let pixel = CMSampleBufferGetImageBuffer(sample) else { return nil }
    let width = CVPixelBufferGetWidth(pixel)
    let height = CVPixelBufferGetHeight(pixel)
    let bytesPerRow = CVPixelBufferGetBytesPerRow(pixel)
    guard CVPixelBufferLockBaseAddress(pixel, .readOnly) == kCVReturnSuccess,
          let address = CVPixelBufferGetBaseAddress(pixel) else { return nil }
    defer {
        CVPixelBufferUnlockBaseAddress(pixel, .readOnly)
        reader.cancelReading()
    }
    let bytes = UnsafeBufferPointer(start: address.assumingMemoryBound(to: UInt8.self), count: bytesPerRow * height)
    return (width, height, Array(bytes))
}

let kind = args[1]
let url = URL(fileURLWithPath: args[2])

if kind == "audio-artwork" {
    let asset = AVURLAsset(url: url)
    let audioTrackCount = asset.tracks(withMediaType: .audio).count
    let metadata = asset.commonMetadata
    let artworkItems = AVMetadataItem.metadataItems(from: metadata, filteredByIdentifier: .commonIdentifierArtwork)
    let titleItems = AVMetadataItem.metadataItems(from: metadata, filteredByIdentifier: .commonIdentifierTitle)
    let artwork = artworkItems.first?.dataValue
    let imageSource = artwork.flatMap { CGImageSourceCreateWithData($0 as CFData, nil) }
    let image = imageSource.flatMap { CGImageSourceCreateImageAtIndex($0, 0, nil) }
    let dimensions = image.map { "\($0.width)x\($0.height)" } ?? "missing"
    let titles = titleItems.map { String(describing: $0.value as Any) }.joined(separator: ",")
    guard args.count == 4, let maxEdge = Int(args[3]), maxEdge >= 64,
          audioTrackCount > 0, let image, max(image.width, image.height) <= maxEdge,
          titleItems.contains(where: { ($0.value as? String) == "OfficeKit artwork smoke" }) else {
        fputs("Audio artwork check failed: audioTracks=\(audioTrackCount), artworkItems=\(artworkItems.count), artworkSize=\(dimensions), titles=\(titles).\n", stderr)
        exit(1)
    }
} else if kind == "image" || kind == "gif" {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          CGImageSourceGetCount(source) > 0,
          CGImageSourceCreateImageAtIndex(source, 0, nil) != nil else {
        fputs("Image or GIF output could not be decoded.\n", stderr)
        exit(1)
    }
} else {
    if kind == "video-hevc" {
        let asset = AVURLAsset(url: url)
        guard let track = asset.tracks(withMediaType: .video).first,
              let descriptions = track.formatDescriptions as? [CMFormatDescription],
              descriptions.contains(where: { CMFormatDescriptionGetMediaSubType($0) == kCMVideoCodecType_HEVC }),
              let reader = try? AVAssetReader(asset: asset) else {
            fputs("Video output is not HEVC or could not be read.\n", stderr)
            exit(1)
        }
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
        guard reader.canAdd(output) else { exit(1) }
        reader.add(output)
        guard reader.startReading(), output.copyNextSampleBuffer() != nil else {
            fputs("HEVC output did not decode a sample.\n", stderr)
            exit(1)
        }
        reader.cancelReading()
    } else if kind == "video-speed" {
        guard args.count == 5, let factor = Double(args[4]), factor >= 25, factor <= 400 else { exit(2) }
        let source = AVURLAsset(url: URL(fileURLWithPath: args[2]))
        let output = AVURLAsset(url: URL(fileURLWithPath: args[3]))
        let sourceDuration = source.duration.seconds
        let outputDuration = output.duration.seconds
        let expected = sourceDuration * 100 / factor
        guard sourceDuration > 0, outputDuration > 0,
              abs(outputDuration - expected) <= max(0.5, expected * 0.08),
              !output.tracks(withMediaType: .video).isEmpty else {
            fputs("Video speed output duration or track did not match the requested factor.\n", stderr)
            exit(1)
        }
    } else if kind == "video-watermark" {
        guard args.count == 4 else { exit(2) }
        let source = AVURLAsset(url: URL(fileURLWithPath: args[2]))
        let output = AVURLAsset(url: URL(fileURLWithPath: args[3]))
        guard !source.tracks(withMediaType: .audio).isEmpty,
              !output.tracks(withMediaType: .audio).isEmpty,
              let sourcePixels = firstFramePixels(source.url),
              let outputPixels = firstFramePixels(output.url),
              sourcePixels.0 == outputPixels.0, sourcePixels.1 == outputPixels.1 else {
            fputs("Watermarked video did not preserve decodable video and audio tracks.\n", stderr)
            exit(1)
        }
        let width = sourcePixels.0
        let height = sourcePixels.1
        let stride = width * 4
        func regionDifference(_ left: Int, _ top: Int, _ right: Int, _ bottom: Int) -> Double {
            var total = 0.0
            var count = 0
            for y in top..<bottom {
                for x in left..<right {
                    let offset = y * stride + x * 4
                    for channel in 0..<3 {
                        total += Double(abs(Int(sourcePixels.2[offset + channel]) - Int(outputPixels.2[offset + channel])))
                        count += 1
                    }
                }
            }
            return count > 0 ? total / Double(count) : 0
        }
        let watermarkDifference = regionDifference(0, 0, width / 4, height / 4)
        let controlDifference = regionDifference(width * 3 / 4, height * 3 / 4, width, height)
        guard watermarkDifference > 10, watermarkDifference > controlDifference * 1.4 else {
            fputs("Watermark did not produce a visible change in its expected video region.\n", stderr)
            exit(1)
        }
    } else if kind == "video-crop" {
        guard args.count == 5, let expectedWidth = Int(args[3]), let expectedHeight = Int(args[4]) else { exit(2) }
        let asset = AVURLAsset(url: url)
        guard let track = asset.tracks(withMediaType: .video).first,
              let reader = try? AVAssetReader(asset: asset) else { exit(1) }
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
        guard reader.canAdd(output) else { exit(1) }
        reader.add(output)
        guard reader.startReading(), let sample = output.copyNextSampleBuffer(),
              let pixels = CMSampleBufferGetImageBuffer(sample),
              CVPixelBufferGetWidth(pixels) == expectedWidth,
              CVPixelBufferGetHeight(pixels) == expectedHeight else {
            fputs("Video crop output dimensions did not match the requested rectangle.\n", stderr)
            exit(1)
        }
        reader.cancelReading()
    } else if kind == "video-resize" {
        guard args.count == 5, let maximumWidth = Int(args[3]), let maximumHeight = Int(args[4]) else { exit(2) }
        let asset = AVURLAsset(url: url)
        guard let track = asset.tracks(withMediaType: .video).first,
              !asset.tracks(withMediaType: .audio).isEmpty,
              let reader = try? AVAssetReader(asset: asset) else { exit(1) }
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
        guard reader.canAdd(output) else { exit(1) }
        reader.add(output)
        guard reader.startReading(), let sample = output.copyNextSampleBuffer(),
              let pixels = CMSampleBufferGetImageBuffer(sample),
              CVPixelBufferGetWidth(pixels) <= maximumWidth,
              CVPixelBufferGetHeight(pixels) <= maximumHeight else {
            fputs("Video resize output exceeded its requested bounds or lost source audio.\n", stderr)
            exit(1)
        }
        reader.cancelReading()
    } else if kind == "video-fps" {
        guard args.count == 5, let maximumFps = Float(args[4]), maximumFps >= 1, maximumFps <= 120 else { exit(2) }
        let source = AVURLAsset(url: URL(fileURLWithPath: args[2]))
        let output = AVURLAsset(url: URL(fileURLWithPath: args[3]))
        guard let sourceTrack = source.tracks(withMediaType: .video).first,
              let outputTrack = output.tracks(withMediaType: .video).first,
              !output.tracks(withMediaType: .audio).isEmpty,
              source.duration.seconds > 0, output.duration.seconds > 0,
              let sourceReader = try? AVAssetReader(asset: source),
              let outputReader = try? AVAssetReader(asset: output) else {
            fputs("Frame-rate fixture could not be decoded or lost its audio track.\n", stderr)
            exit(1)
        }
        let sourceFrames = AVAssetReaderTrackOutput(track: sourceTrack, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
        let outputFrames = AVAssetReaderTrackOutput(track: outputTrack, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
        guard sourceReader.canAdd(sourceFrames), outputReader.canAdd(outputFrames) else { exit(1) }
        sourceReader.add(sourceFrames)
        outputReader.add(outputFrames)
        guard sourceReader.startReading(), outputReader.startReading() else { exit(1) }
        var sourceFrameCount = 0
        while sourceFrames.copyNextSampleBuffer() != nil { sourceFrameCount += 1 }
        var outputFrameCount = 0
        while outputFrames.copyNextSampleBuffer() != nil { outputFrameCount += 1 }
        let sourceFps = Double(sourceFrameCount) / source.duration.seconds
        let outputFps = Double(outputFrameCount) / output.duration.seconds
        print("Measured video frame rates: source=\(sourceFps), output=\(outputFps), maximum=\(maximumFps)")
        guard sourceFps > Double(maximumFps), outputFps <= Double(maximumFps) + 0.1 else {
            fputs("Decoded frame rates were not capped: source=\(sourceFps), output=\(outputFps), maximum=\(maximumFps).\n", stderr)
            exit(1)
        }
    } else if kind == "video-strip-metadata" {
        guard args.count == 4 else { exit(2) }
        let source = AVURLAsset(url: URL(fileURLWithPath: args[2]))
        let output = AVURLAsset(url: URL(fileURLWithPath: args[3]))
        let marker = "OfficeKit private metadata smoke"
        let sourceHasMarker = source.commonMetadata.contains {
            $0.commonKey == .commonKeyTitle && ($0.value as? String) == marker
        }
        let outputHasMarker = output.commonMetadata.contains {
            $0.commonKey == .commonKeyTitle && ($0.value as? String) == marker
        }
        guard sourceHasMarker, !outputHasMarker,
              !output.tracks(withMediaType: .video).isEmpty,
              !output.tracks(withMediaType: .audio).isEmpty else {
            fputs("Video metadata removal failed to preserve media tracks and remove the marker.\n", stderr)
            exit(1)
        }
    } else {
    let mediaType: AVMediaType = kind == "audio" || kind == "audio-channels" ? .audio : .video
    let asset = AVURLAsset(url: url)
    if kind == "video-muted" && !asset.tracks(withMediaType: .audio).isEmpty {
        fputs("Muted video still contains an audio track.\n", stderr)
        exit(1)
    }
    guard let track = asset.tracks(withMediaType: mediaType).first else {
        fputs("Media output has no decodable track.\n", stderr)
        exit(1)
    }
    if kind != "video-muted" {
    guard
          let reader = try? AVAssetReader(asset: asset) else {
        fputs("Media output has no decodable track.\n", stderr)
        exit(1)
    }
    let settings: [String: Any] = kind == "video"
        ? [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        : [AVFormatIDKey: kAudioFormatLinearPCM,
           AVLinearPCMBitDepthKey: 16,
           AVLinearPCMIsBigEndianKey: false,
           AVLinearPCMIsFloatKey: false,
           AVLinearPCMIsNonInterleaved: false]
    let output = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
    guard reader.canAdd(output) else {
        fputs("Media output could not be read.\n", stderr)
        exit(1)
    }
    reader.add(output)
    guard reader.startReading(), let decodedSample = output.copyNextSampleBuffer() else {
        fputs("Media output did not decode a sample.\n", stderr)
        exit(1)
    }
    if kind == "audio-channels" {
        guard args.count == 4, let expectedChannels = Int(args[3]),
              let description = CMSampleBufferGetFormatDescription(decodedSample),
              let stream = CMAudioFormatDescriptionGetStreamBasicDescription(description)?.pointee,
              Int(stream.mChannelsPerFrame) == expectedChannels else {
            fputs("Decoded audio channel count did not match the expected value.\n", stderr)
            exit(1)
        }
    }
    reader.cancelReading()
    }
    _ = track
    }
}

print("Decoded \(kind) output successfully.")
