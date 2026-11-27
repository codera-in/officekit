import AVFoundation
import AVFAudio
import CoreImage
import CoreMedia
import Foundation
import ImageIO
import QuartzCore
import UniformTypeIdentifiers
import Vision

func exportGIF(asset: AVURLAsset, sourceVideo: AVAssetTrack, outputURL: URL, fps: Int, maxWidth: Int, maxDuration: Int) async throws {
    guard (1...60).contains(fps), (16...1920).contains(maxWidth), (1...60).contains(maxDuration) else {
        fail("GIF settings are outside the supported range")
    }
    let reader = try AVAssetReader(asset: asset)
    let output = AVAssetReaderTrackOutput(track: sourceVideo, outputSettings: [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
    ])
    guard reader.canAdd(output) else { fail("Could not read the video frames") }
    reader.add(output)
    guard reader.startReading(),
          let destination = CGImageDestinationCreateWithURL(outputURL as CFURL, UTType.gif.identifier as CFString, 0, nil) else {
        fail("Could not start GIF encoding")
    }
    CGImageDestinationSetProperties(destination, [
        kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 0],
    ] as CFDictionary)
    let context = CIContext(options: [.useSoftwareRenderer: true])
    let sourceLimit = Double(maxDuration)
    let frameInterval = 1.0 / Double(fps)
    var nextFrameTime = 0.0
    var frameCount = 0
    while let sample = output.copyNextSampleBuffer() {
        let time = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample))
        if time >= sourceLimit { break }
        guard time + 0.0001 >= nextFrameTime else { continue }
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sample) else { continue }
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        let extent = image.extent
        guard extent.width > 0, extent.height > 0 else { continue }
        let scale = min(1.0, Double(maxWidth) / extent.width)
        let resized = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        let bounds = CGRect(origin: .zero, size: CGSize(width: extent.width * scale, height: extent.height * scale))
        guard let frame = context.createCGImage(resized, from: bounds) else { continue }
        CGImageDestinationAddImage(destination, frame, [
            kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFDelayTime: frameInterval],
        ] as CFDictionary)
        frameCount += 1
        nextFrameTime = time + frameInterval
    }
    reader.cancelReading()
    guard frameCount > 0, CGImageDestinationFinalize(destination) else {
        fail("No GIF frames could be encoded")
    }
}

func writePreviewJPEG(_ image: CGImage, to url: URL) throws {
    guard let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.jpeg.identifier as CFString, 1, nil) else {
        fail("Could not create the preview image")
    }
    CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 0.82] as CFDictionary)
    guard CGImageDestinationFinalize(destination) else { fail("Could not write the preview image") }
}

func fail(_ message: String) -> Never {
    fputs("Media transform failed: \(message)\n", stderr)
    exit(1)
}

struct LoudnessBiquad {
    let b0: Double
    let b1: Double
    let b2: Double
    let a1: Double
    let a2: Double
    var x1 = 0.0
    var x2 = 0.0
    var y1 = 0.0
    var y2 = 0.0

    mutating func process(_ input: Double) -> Double {
        let output = b0 * input + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2 = x1
        x1 = input
        y2 = y1
        y1 = output
        return output
    }
}

struct LoudnessMeasurement {
    let lufs: Double
    let samplePeakDBFS: Double
}

struct BS1770MonoStereoMeter {
    private let blockLength = 19_200
    private let blockHop = 4_800
    private var filters: [[LoudnessBiquad]]
    private var squareRing: [[Double]]
    private var squareSums: [Double]
    private var sampleCount = 0
    private var blockPowers: [[Double]] = []
    private(set) var samplePeak = 0.0

    init(channelCount: Int) throws {
        guard channelCount == 1 || channelCount == 2 else {
            throw NSError(domain: "OfficeKitMedia", code: 1, userInfo: [NSLocalizedDescriptionKey: "LUFS normalization currently supports mono or stereo audio."])
        }
        let shelf = LoudnessBiquad(
            b0: 1.53512485958697, b1: -2.69169618940638, b2: 1.19839281085285,
            a1: -1.69065929318241, a2: 0.73248077421585
        )
        let highPass = LoudnessBiquad(
            b0: 1.0, b1: -2.0, b2: 1.0,
            a1: -1.99004745483398, a2: 0.99007225036621
        )
        filters = Array(repeating: [shelf, highPass], count: channelCount)
        squareRing = Array(repeating: Array(repeating: 0, count: blockLength), count: channelCount)
        squareSums = Array(repeating: 0, count: channelCount)
    }

    mutating func consume(_ buffer: AVAudioPCMBuffer) throws {
        guard let channels = buffer.floatChannelData else {
            throw NSError(domain: "OfficeKitMedia", code: 2, userInfo: [NSLocalizedDescriptionKey: "The audio decoder returned an unsupported sample format."])
        }
        let channelCount = Int(buffer.format.channelCount)
        guard channelCount == filters.count else {
            throw NSError(domain: "OfficeKitMedia", code: 3, userInfo: [NSLocalizedDescriptionKey: "The audio channel layout changed during decode."])
        }
        for frame in 0..<Int(buffer.frameLength) {
            let ringIndex = sampleCount % blockLength
            for channel in 0..<channelCount {
                let sample = Double(channels[channel][frame])
                guard sample.isFinite else {
                    throw NSError(domain: "OfficeKitMedia", code: 4, userInfo: [NSLocalizedDescriptionKey: "The audio contains invalid samples."])
                }
                samplePeak = max(samplePeak, abs(sample))
                var weighted = filters[channel][0].process(sample)
                weighted = filters[channel][1].process(weighted)
                let power = weighted * weighted
                if sampleCount >= blockLength {
                    squareSums[channel] -= squareRing[channel][ringIndex]
                }
                squareRing[channel][ringIndex] = power
                squareSums[channel] += power
            }
            sampleCount += 1
            if sampleCount >= blockLength && (sampleCount - blockLength) % blockHop == 0 {
                blockPowers.append(squareSums.map { max(0, $0 / Double(blockLength)) })
            }
        }
    }

    func measurement() throws -> LoudnessMeasurement {
        guard !blockPowers.isEmpty, samplePeak > 0 else {
            throw NSError(domain: "OfficeKitMedia", code: 5, userInfo: [NSLocalizedDescriptionKey: "The audio is silent or shorter than the 400 ms loudness window."])
        }
        func blockLoudness(_ powers: [Double]) -> Double {
            let energy = powers.reduce(0, +)
            return energy > 0 ? -0.691 + 10 * log10(energy) : -.infinity
        }
        let absoluteBlocks = blockPowers.filter { blockLoudness($0) > -70 }
        guard !absoluteBlocks.isEmpty else {
            throw NSError(domain: "OfficeKitMedia", code: 6, userInfo: [NSLocalizedDescriptionKey: "The audio is below the loudness meter threshold."])
        }
        let absoluteEnergy = absoluteBlocks.flatMap { $0 }.reduce(0, +) / Double(absoluteBlocks.count)
        guard absoluteEnergy > 0 else {
            throw NSError(domain: "OfficeKitMedia", code: 7, userInfo: [NSLocalizedDescriptionKey: "The audio loudness could not be measured."])
        }
        let relativeThreshold = -0.691 + 10 * log10(absoluteEnergy) - 10
        let gatedBlocks = absoluteBlocks.filter { blockLoudness($0) > relativeThreshold }
        guard !gatedBlocks.isEmpty else {
            throw NSError(domain: "OfficeKitMedia", code: 8, userInfo: [NSLocalizedDescriptionKey: "The audio loudness could not be measured."])
        }
        let gatedEnergy = gatedBlocks.flatMap { $0 }.reduce(0, +) / Double(gatedBlocks.count)
        return LoudnessMeasurement(
            lufs: -0.691 + 10 * log10(gatedEnergy),
            samplePeakDBFS: 20 * log10(samplePeak)
        )
    }
}

func measureProgramLoudness(_ url: URL) throws -> LoudnessMeasurement {
    let audioFile = try AVAudioFile(forReading: url)
    let sourceFormat = audioFile.processingFormat
    let channelCount = Int(sourceFormat.channelCount)
    var meter = try BS1770MonoStereoMeter(channelCount: channelCount)
    guard let targetFormat = AVAudioFormat(
        commonFormat: .pcmFormatFloat32, sampleRate: 48_000,
        channels: AVAudioChannelCount(channelCount), interleaved: false
    ), let converter = AVAudioConverter(from: sourceFormat, to: targetFormat),
       let input = AVAudioPCMBuffer(pcmFormat: sourceFormat, frameCapacity: 8_192),
       let output = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: 16_384) else {
        throw NSError(domain: "OfficeKitMedia", code: 9, userInfo: [NSLocalizedDescriptionKey: "The audio could not be converted to the loudness meter format."])
    }
    var endOfInput = false
    while true {
        var conversionError: NSError?
        var inputError: Error?
        let status = converter.convert(to: output, error: &conversionError) { _, inputStatus in
            if endOfInput {
                inputStatus.pointee = .endOfStream
                return nil
            }
            do {
                try audioFile.read(into: input)
            } catch let error as NSError {
                if error.domain == NSOSStatusErrorDomain && error.code == Int(kAudioFileEndOfFileError) {
                    endOfInput = true
                    inputStatus.pointee = .endOfStream
                    return nil
                }
                inputError = error
                inputStatus.pointee = .endOfStream
                endOfInput = true
                return nil
            }
            if input.frameLength == 0 {
                endOfInput = true
                inputStatus.pointee = .endOfStream
                return nil
            }
            inputStatus.pointee = .haveData
            return input
        }
        if let inputError { throw inputError }
        if let conversionError { throw conversionError }
        if output.frameLength > 0 { try meter.consume(output) }
        if status == .endOfStream { break }
        if status == .error {
            throw NSError(domain: "OfficeKitMedia", code: 10, userInfo: [NSLocalizedDescriptionKey: "The audio could not be converted for loudness measurement."])
        }
    }
    return try meter.measurement()
}

func exportNormalizedAudio(asset: AVURLAsset, sourceURL: URL, outputURL: URL, targetLUFS: Double) async throws -> [String: Any] {
    guard !FileManager.default.fileExists(atPath: outputURL.path), sourceURL.standardizedFileURL != outputURL.standardizedFileURL else {
        throw NSError(domain: "OfficeKitMedia", code: 15, userInfo: [NSLocalizedDescriptionKey: "Choose a new output for normalized audio."])
    }
    var verified = false
    defer {
        if !verified { try? FileManager.default.removeItem(at: outputURL) }
    }
    guard (-24 ... -5).contains(targetLUFS) else {
        throw NSError(domain: "OfficeKitMedia", code: 11, userInfo: [NSLocalizedDescriptionKey: "The loudness target is outside the supported range."])
    }
    let tracks = try await asset.loadTracks(withMediaType: .audio)
    guard let track = tracks.first else {
        throw NSError(domain: "OfficeKitMedia", code: 12, userInfo: [NSLocalizedDescriptionKey: "No audio track was found."])
    }
    let duration = try await asset.load(.duration)
    guard duration.isNumeric, duration.seconds >= 0.4, duration.seconds <= 120 else {
        throw NSError(domain: "OfficeKitMedia", code: 13, userInfo: [NSLocalizedDescriptionKey: "Audio duration must be between 0.4 and 120 seconds for loudness normalization."])
    }
    let input = try measureProgramLoudness(sourceURL)
    let requestedGain = targetLUFS - input.lufs
    let peakCeilingDBFS = -2.0
    let correctionMarginDB = 0.25
    let maximumAttempts = 3
    let safeGain = peakCeilingDBFS - input.samplePeakDBFS
    var appliedGain = min(requestedGain, safeGain)
    var peakLimited = requestedGain > safeGain + 0.05
    let metadata = try await asset.load(.metadata)
    for attempt in 0..<maximumAttempts {
        if attempt > 0 { try FileManager.default.removeItem(at: outputURL) }
        let parameters = AVMutableAudioMixInputParameters(track: track)
        parameters.setVolume(Float(pow(10, appliedGain / 20)), at: .zero)
        let mix = AVMutableAudioMix()
        mix.inputParameters = [parameters]
        guard let session = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetAppleM4A),
              session.supportedFileTypes.contains(.m4a) else {
            throw NSError(domain: "OfficeKitMedia", code: 14, userInfo: [NSLocalizedDescriptionKey: "The system audio encoder cannot create a normalized M4A copy."])
        }
        session.outputURL = outputURL
        session.outputFileType = .m4a
        session.audioMix = mix
        session.metadata = metadata
        session.shouldOptimizeForNetworkUse = true
        waitForExport(session)
        let output = try measureProgramLoudness(outputURL)
        if output.samplePeakDBFS > peakCeilingDBFS {
            appliedGain -= output.samplePeakDBFS - peakCeilingDBFS + correctionMarginDB
            peakLimited = true
            continue
        }
        verified = true
        return [
            "input_lufs": input.lufs,
            "output_lufs": output.lufs,
            "applied_gain_db": appliedGain,
            "sample_peak_dbfs": output.samplePeakDBFS,
            "peak_limited": peakLimited,
        ]
    }
    throw NSError(domain: "OfficeKitMedia", code: 16, userInfo: [NSLocalizedDescriptionKey: "The encoded audio could not meet the sample-peak ceiling."])
}

func writeMetrics(_ attributes: [String: Any], to path: String) throws {
    let data = try JSONSerialization.data(withJSONObject: attributes, options: [.sortedKeys])
    try data.write(to: URL(fileURLWithPath: path), options: .atomic)
}

func waitForExport(_ session: AVAssetExportSession) {
    let completed = DispatchSemaphore(value: 0)
    session.exportAsynchronously { completed.signal() }
    guard completed.wait(timeout: .now() + 110) == .success else {
        session.cancelExport()
        fail("The media transform exceeded its time limit")
    }
    guard session.status == .completed else {
        if let error = session.error as NSError? {
            fail("\(error.localizedDescription) (\(error.domain) \(error.code))")
        }
        fail("The media encoder did not finish")
    }
}

func exportResizedArtwork(asset: AVURLAsset, outputURL: URL, maxEdge: Int) async throws {
    guard (64...4096).contains(maxEdge) else { fail("Artwork size is outside the supported range") }
    let sourceMetadata = try await asset.load(.metadata)
    let artworkItems = AVMetadataItem.metadataItems(from: sourceMetadata, filteredByIdentifier: .commonIdentifierArtwork)
    guard let artwork = artworkItems.first else { fail("This audio file has no supported embedded artwork") }
    guard let bytes = try await artwork.load(.dataValue),
          let imageSource = CGImageSourceCreateWithData(bytes as CFData, nil),
          CGImageSourceGetCount(imageSource) == 1,
          let image = CGImageSourceCreateThumbnailAtIndex(imageSource, 0, [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: maxEdge,
          ] as CFDictionary),
          let sourceType = CGImageSourceGetType(imageSource),
          let imageData = CFDataCreateMutable(nil, 0),
          let imageDestination = CGImageDestinationCreateWithData(imageData, sourceType, 1, nil) else {
        fail("This audio file has no supported embedded artwork")
    }
    CGImageDestinationAddImage(imageDestination, image, nil)
    guard CGImageDestinationFinalize(imageDestination) else { fail("Could not resize embedded artwork") }

    let replacement = AVMutableMetadataItem()
    replacement.identifier = .commonIdentifierArtwork
    replacement.dataType = artwork.dataType
    replacement.value = imageData as Data as NSData
    let metadata = sourceMetadata.filter { $0.commonKey != .commonKeyArtwork } + [replacement]
    guard let session = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetAppleM4A),
          session.supportedFileTypes.contains(.m4a) else {
        fail("The system encoder cannot preserve resized artwork in M4A")
    }
    session.outputURL = outputURL
    session.outputFileType = .m4a
    session.metadata = metadata
    session.shouldOptimizeForNetworkUse = true
    waitForExport(session)
}

@main
struct OfficeKitMediaTransform {
    static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 3 && args.count <= 9 else {
            fail("Invalid media transform arguments")
        }
        let operation = args[1]
        let sourceURL = URL(fileURLWithPath: args[2])
        let outputURL = URL(fileURLWithPath: args.count >= 4 ? args[3] : "/dev/null")
        let asset = AVURLAsset(url: sourceURL)
        do {
            if operation == "video-info" {
                let videoTracks = try await asset.loadTracks(withMediaType: .video)
                guard args.count == 3, let sourceVideo = videoTracks.first else {
                    fail("Video information request is invalid")
                }
                let duration = try await asset.load(.duration)
                let naturalSize = try await sourceVideo.load(.naturalSize)
                let transform = try await sourceVideo.load(.preferredTransform)
                let displayRect = CGRect(origin: .zero, size: naturalSize).applying(transform).standardized
                let width = Int(displayRect.width.rounded(.down))
                let height = Int(displayRect.height.rounded(.down))
                guard duration.isNumeric, duration.seconds > 0, duration.seconds <= 120,
                      width > 0, height > 0, width <= 10_000, height <= 10_000,
                      width * height <= 100_000_000 else {
                    fail("Video dimensions or duration are outside the supported range")
                }
                let payload = try JSONSerialization.data(withJSONObject: ["width": width, "height": height])
                FileHandle.standardOutput.write(payload)
                return
            }
            if operation == "smart-crop-bounds" {
                guard args.count == 4, (args[3] == "image" || args[3] == "video") else {
                    fail("Smart crop request is invalid")
                }
                let request = VNGenerateAttentionBasedSaliencyImageRequest()
                let requestHandler: VNImageRequestHandler
                let width: Int
                let height: Int
                if args[3] == "image" {
                    guard let imageSource = CGImageSourceCreateWithURL(sourceURL as CFURL, nil),
                          let properties = CGImageSourceCopyPropertiesAtIndex(imageSource, 0, nil) as? [CFString: Any],
                          let rawWidth = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
                          let rawHeight = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue else {
                        fail("Image dimensions could not be read for smart crop")
                    }
                    let rawOrientation = (properties[kCGImagePropertyOrientation] as? NSNumber)?.uint32Value ?? 1
                    let orientation = CGImagePropertyOrientation(rawValue: rawOrientation) ?? .up
                    let swapsDimensions = (5...8).contains(rawOrientation)
                    width = swapsDimensions ? rawHeight : rawWidth
                    height = swapsDimensions ? rawWidth : rawHeight
                    requestHandler = VNImageRequestHandler(url: sourceURL, orientation: orientation, options: [:])
                } else {
                    let videoTracks = try await asset.loadTracks(withMediaType: .video)
                    guard let sourceVideo = videoTracks.first else { fail("Video has no frame for smart crop") }
                    let naturalSize = try await sourceVideo.load(.naturalSize)
                    let transform = try await sourceVideo.load(.preferredTransform)
                    let displayRect = CGRect(origin: .zero, size: naturalSize).applying(transform).standardized
                    guard displayRect.width.isFinite, displayRect.height.isFinite,
                          displayRect.width >= 1, displayRect.height >= 1,
                          displayRect.width <= 40_000, displayRect.height <= 40_000,
                          displayRect.width * displayRect.height <= 100_000_000 else {
                        fail("Smart crop dimensions exceed the supported range")
                    }
                    width = Int(displayRect.width.rounded(.down))
                    height = Int(displayRect.height.rounded(.down))
                    let generator = AVAssetImageGenerator(asset: asset)
                    generator.appliesPreferredTrackTransform = true
                    generator.maximumSize = CGSize(width: 2048, height: 2048)
                    let frame = try generator.copyCGImage(at: .zero, actualTime: nil)
                    requestHandler = VNImageRequestHandler(cgImage: frame, options: [:])
                }
                guard width > 0, height > 0, width <= 40_000, height <= 40_000,
                      width * height <= 100_000_000 else {
                    fail("Smart crop dimensions exceed the supported range")
                }
                try requestHandler.perform([request])
                let salientBox = request.results?.first?.salientObjects?.first?.boundingBox
                let detected = salientBox != nil
                let box = salientBox ?? CGRect(x: 0.5, y: 0.5, width: 0, height: 0)
                let payload = try JSONSerialization.data(withJSONObject: [
                    "width": width, "height": height,
                    "x": Double(box.minX), "y": Double(box.minY),
                    "boxWidth": Double(box.width), "boxHeight": Double(box.height),
                    "detected": detected,
                ])
                FileHandle.standardOutput.write(payload)
                return
            }
            if operation == "preview-video" {
                // preview-video <source> <output.jpg> <max edge> <position percent>
                guard args.count == 6, let maxEdge = Int(args[4]), (32...2048).contains(maxEdge),
                      let percent = Int(args[5]), (0...100).contains(percent) else {
                    fail("Video preview request is invalid")
                }
                let videoTracks = try await asset.loadTracks(withMediaType: .video)
                guard let sourceVideo = videoTracks.first else { fail("The file has no video track") }
                let duration = try await asset.load(.duration)
                let naturalSize = try await sourceVideo.load(.naturalSize)
                let transform = try await sourceVideo.load(.preferredTransform)
                let displayRect = CGRect(origin: .zero, size: naturalSize).applying(transform).standardized
                let width = Int(displayRect.width.rounded(.down))
                let height = Int(displayRect.height.rounded(.down))
                guard duration.isNumeric, duration.seconds > 0, duration.seconds <= 86_400,
                      width > 0, height > 0, width <= 40_000, height <= 40_000 else {
                    fail("Video dimensions or duration are outside the supported range")
                }
                let generator = AVAssetImageGenerator(asset: asset)
                generator.appliesPreferredTrackTransform = true
                generator.maximumSize = CGSize(width: maxEdge, height: maxEdge)
                let target = min(duration.seconds * Double(percent) / 100, max(0, duration.seconds - 0.1))
                let frame = try generator.copyCGImage(at: CMTime(seconds: target, preferredTimescale: 600), actualTime: nil)
                try writePreviewJPEG(frame, to: outputURL)
                let payload = try JSONSerialization.data(withJSONObject: [
                    "width": width, "height": height, "duration": duration.seconds,
                    "peaks": [Int](), "hasArtwork": true,
                ])
                FileHandle.standardOutput.write(payload)
                return
            }
            if operation == "preview-audio" {
                // preview-audio <source> <output.jpg> <max edge> <waveform buckets>
                guard args.count == 6, let maxEdge = Int(args[4]), (32...2048).contains(maxEdge),
                      let buckets = Int(args[5]), (8...256).contains(buckets) else {
                    fail("Audio preview request is invalid")
                }
                let audioTracks = try await asset.loadTracks(withMediaType: .audio)
                guard let sourceAudio = audioTracks.first else { fail("The file has no audio track") }
                let duration = try await asset.load(.duration)
                guard duration.isNumeric, duration.seconds > 0, duration.seconds <= 86_400 else {
                    fail("Audio duration is outside the supported range")
                }
                var hasArtwork = false
                let common = try await asset.load(.commonMetadata)
                if let item = AVMetadataItem.metadataItems(from: common, filteredByIdentifier: .commonIdentifierArtwork).first,
                   let data = try? await item.load(.dataValue), data.count <= 16_000_000,
                   let imageSource = CGImageSourceCreateWithData(data as CFData, nil),
                   let cover = CGImageSourceCreateThumbnailAtIndex(imageSource, 0, [
                       kCGImageSourceCreateThumbnailFromImageAlways: true,
                       kCGImageSourceCreateThumbnailWithTransform: true,
                       kCGImageSourceThumbnailMaxPixelSize: maxEdge,
                   ] as CFDictionary) {
                    try writePreviewJPEG(cover, to: outputURL)
                    hasArtwork = true
                }
                let sampleRate = 8000
                let reader = try AVAssetReader(asset: asset)
                let output = AVAssetReaderTrackOutput(track: sourceAudio, outputSettings: [
                    AVFormatIDKey: kAudioFormatLinearPCM,
                    AVLinearPCMBitDepthKey: 32,
                    AVLinearPCMIsFloatKey: true,
                    AVLinearPCMIsBigEndianKey: false,
                    AVLinearPCMIsNonInterleaved: false,
                    AVNumberOfChannelsKey: 1,
                    AVSampleRateKey: sampleRate,
                ])
                var peaks = [Float](repeating: 0, count: buckets)
                if reader.canAdd(output) {
                    reader.add(output)
                    if reader.startReading() {
                        let expected = max(1, Int(duration.seconds * Double(sampleRate)))
                        var index = 0
                        while let sample = output.copyNextSampleBuffer() {
                            guard let block = CMSampleBufferGetDataBuffer(sample) else { continue }
                            let length = CMBlockBufferGetDataLength(block)
                            var bytes = [UInt8](repeating: 0, count: length)
                            guard CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: length, destination: &bytes) == kCMBlockBufferNoErr else { continue }
                            bytes.withUnsafeBytes { raw in
                                for value in raw.bindMemory(to: Float.self) {
                                    let bucket = min(buckets - 1, index * buckets / expected)
                                    peaks[bucket] = max(peaks[bucket], abs(value))
                                    index += 1
                                }
                            }
                            if index > expected * 2 { break }
                        }
                        reader.cancelReading()
                    }
                }
                let loudest = max(peaks.max() ?? 0, 0.0001)
                let scaled = peaks.map { min(100, max(2, Int(($0 / loudest * 100).rounded()))) }
                let payload = try JSONSerialization.data(withJSONObject: [
                    "width": 0, "height": 0, "duration": duration.seconds,
                    "peaks": scaled, "hasArtwork": hasArtwork,
                ])
                FileHandle.standardOutput.write(payload)
                return
            }
            if operation == "audio-info" {
                let audioTracks = try await asset.loadTracks(withMediaType: .audio)
                guard args.count == 3, !audioTracks.isEmpty else {
                    fail("Audio information request is invalid")
                }
                let duration = try await asset.load(.duration)
                guard duration.isNumeric, duration.seconds > 0, duration.seconds <= 120 else {
                    fail("Audio duration is outside the supported range")
                }
                let payload = try JSONSerialization.data(withJSONObject: ["duration": duration.seconds])
                FileHandle.standardOutput.write(payload)
                return
            }
            if operation == "audio-speed" {
                guard args.count == 5, let number = Int(args[4]), (25...400).contains(number) else {
                    fail("Speed must be between 25 and 400 percent")
                }
                let audioTracks = try await asset.loadTracks(withMediaType: .audio)
                guard !audioTracks.isEmpty else { fail("No audio track was found") }
                let duration = try await asset.load(.duration)
                guard duration.isNumeric, duration.seconds > 0, duration.seconds <= 120 else {
                    fail("The source duration is outside the supported range")
                }
                let composition = AVMutableComposition()
                for sourceAudio in audioTracks {
                    guard let audio = composition.addMutableTrack(
                        withMediaType: .audio,
                        preferredTrackID: kCMPersistentTrackID_Invalid
                    ) else { fail("Could not create an output audio track") }
                    let audioRange = try await sourceAudio.load(.timeRange)
                    try audio.insertTimeRange(audioRange, of: sourceAudio, at: .zero)
                    audio.scaleTimeRange(
                        CMTimeRange(start: .zero, duration: audioRange.duration),
                        toDuration: CMTimeMultiplyByFloat64(audioRange.duration, multiplier: 100.0 / Double(number))
                    )
                }
                guard let session = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetAppleM4A),
                      session.supportedFileTypes.contains(.m4a) else {
                    fail("The system cannot export sped audio as M4A")
                }
                session.outputURL = outputURL
                session.outputFileType = .m4a
                session.shouldOptimizeForNetworkUse = true
                waitForExport(session)
                return
            }
            if operation == "audio-artwork" {
                guard let number = Int(args[4]) else { fail("Invalid artwork settings") }
                guard args.count == 5 else { fail("Invalid artwork settings") }
                try await exportResizedArtwork(asset: asset, outputURL: outputURL, maxEdge: number)
                return
            }
            if operation == "audio-normalize" {
                guard args.count == 6, let targetLUFS = Double(args[4]) else { fail("Invalid loudness settings") }
                let attributes = try await exportNormalizedAudio(
                    asset: asset, sourceURL: sourceURL, outputURL: outputURL, targetLUFS: targetLUFS
                )
                try writeMetrics(attributes, to: args[5])
                return
            }
            if operation == "video-strip-metadata" {
                guard args.count == 4 else { fail("Invalid metadata removal request") }
                let videoTracks = try await asset.loadTracks(withMediaType: .video)
                let audioTracks = try await asset.loadTracks(withMediaType: .audio)
                guard !videoTracks.isEmpty else { fail("No video track was found") }
                let composition = AVMutableComposition()
                for sourceTrack in videoTracks + audioTracks {
                    guard let destinationTrack = composition.addMutableTrack(
                        withMediaType: sourceTrack.mediaType,
                        preferredTrackID: kCMPersistentTrackID_Invalid
                    ) else { fail("Could not create an output media track") }
                    let timeRange = try await sourceTrack.load(.timeRange)
                    try destinationTrack.insertTimeRange(timeRange, of: sourceTrack, at: .zero)
                    if sourceTrack.mediaType == .video {
                        destinationTrack.preferredTransform = try await sourceTrack.load(.preferredTransform)
                    }
                }
                guard let session = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetPassthrough),
                      session.supportedFileTypes.contains(.mov) else {
                    fail("The system cannot copy video while removing metadata")
                }
                session.outputURL = outputURL
                session.outputFileType = .mov
                session.metadata = []
                session.shouldOptimizeForNetworkUse = true
                waitForExport(session)
                return
            }
            let number = operation == "video-watermark-overlay" ? 0 : Int(args[4])
            guard let number else { fail("Invalid transform option") }
            let sourceVideoTracks = try await asset.loadTracks(withMediaType: .video)
            guard let sourceVideo = sourceVideoTracks.first else { fail("No video track was found") }
            let duration = try await asset.load(.duration)
            guard duration.isNumeric, duration.seconds > 0, duration.seconds <= 120 else {
                fail("The source duration is outside the supported range")
            }

            let composition = AVMutableComposition()
            if operation == "video-to-gif" {
                guard args.count == 7, let maxWidth = Int(args[5]), let maxDuration = Int(args[6]) else {
                    fail("Invalid GIF settings")
                }
                try await exportGIF(asset: asset, sourceVideo: sourceVideo, outputURL: outputURL,
                                    fps: number, maxWidth: maxWidth, maxDuration: maxDuration)
                return
            }
            guard let video = composition.addMutableTrack(
                withMediaType: .video,
                preferredTrackID: kCMPersistentTrackID_Invalid
            ) else { fail("Could not create an output video track") }
            let videoRange = try await sourceVideo.load(.timeRange)
            try video.insertTimeRange(videoRange, of: sourceVideo, at: .zero)
            let preferredTransform = try await sourceVideo.load(.preferredTransform)
            video.preferredTransform = preferredTransform

            var selfAssignVideoComposition: AVVideoComposition?
            let preset: String
            if operation == "video-mute" {
                preset = AVAssetExportPresetPassthrough
            } else if operation == "video-speed" {
                guard (25...400).contains(number) else { fail("Speed must be between 25 and 400 percent") }
                let sourceAudioTracks = try await asset.loadTracks(withMediaType: .audio)
                for sourceAudio in sourceAudioTracks {
                    guard let audio = composition.addMutableTrack(
                        withMediaType: .audio,
                        preferredTrackID: kCMPersistentTrackID_Invalid
                    ) else { fail("Could not create an output audio track") }
                    let audioRange = try await sourceAudio.load(.timeRange)
                    try audio.insertTimeRange(audioRange, of: sourceAudio, at: .zero)
                    audio.scaleTimeRange(
                        CMTimeRange(start: .zero, duration: audioRange.duration),
                        toDuration: CMTimeMultiplyByFloat64(audioRange.duration, multiplier: 100.0 / Double(number))
                    )
                }
                video.scaleTimeRange(
                    CMTimeRange(start: .zero, duration: videoRange.duration),
                    toDuration: CMTimeMultiplyByFloat64(videoRange.duration, multiplier: 100.0 / Double(number))
                )
                preset = AVAssetExportPresetHighestQuality
            } else if operation == "video-watermark-overlay" {
                guard args.count == 9,
                      let marginPercent = Int(args[6]), (0...20).contains(marginPercent),
                      let sizePercent = Int(args[7]), (5...60).contains(sizePercent),
                      let opacityPercent = Int(args[8]), (10...100).contains(opacityPercent),
                      ["bottom-right", "bottom-left", "top-right", "top-left", "center"].contains(args[5]) else {
                    fail("Invalid video watermark settings")
                }
                let sourceAudioTracks = try await asset.loadTracks(withMediaType: .audio)
                for sourceAudio in sourceAudioTracks {
                    guard let audio = composition.addMutableTrack(
                        withMediaType: .audio,
                        preferredTrackID: kCMPersistentTrackID_Invalid
                    ) else { fail("Could not create an output audio track") }
                    let audioRange = try await sourceAudio.load(.timeRange)
                    try audio.insertTimeRange(audioRange, of: sourceAudio, at: .zero)
                }
                let watermarkURL = URL(fileURLWithPath: args[4])
                guard let watermarkAttributes = try? FileManager.default.attributesOfItem(atPath: watermarkURL.path),
                      let watermarkSize = watermarkAttributes[.size] as? NSNumber,
                      watermarkSize.intValue > 0, watermarkSize.intValue <= 5 * 1024 * 1024,
                      let imageSource = CGImageSourceCreateWithURL(watermarkURL as CFURL, nil),
                      CGImageSourceGetCount(imageSource) == 1,
                      let logo = CGImageSourceCreateImageAtIndex(imageSource, 0, nil),
                      logo.width > 0, logo.height > 0, logo.width <= 40_000_000 / logo.height else {
                    fail("Watermark must be one supported image below the size limit")
                }
                let naturalSize = try await sourceVideo.load(.naturalSize)
                let displayRect = CGRect(origin: .zero, size: naturalSize).applying(preferredTransform).standardized
                guard displayRect.width > 0, displayRect.height > 0,
                      displayRect.width <= 10_000, displayRect.height <= 10_000 else {
                    fail("Invalid source dimensions")
                }
                let renderWidth = Int(displayRect.width.rounded(.up))
                let renderHeight = Int(displayRect.height.rounded(.up))
                let renderSize = CGSize(width: renderWidth, height: renderHeight)
                video.preferredTransform = .identity
                let instruction = AVMutableVideoCompositionInstruction()
                instruction.timeRange = CMTimeRange(start: .zero, duration: videoRange.duration)
                let videoLayerInstruction = AVMutableVideoCompositionLayerInstruction(assetTrack: video)
                let normalize = CGAffineTransform(translationX: -displayRect.minX, y: -displayRect.minY)
                videoLayerInstruction.setTransform(preferredTransform.concatenating(normalize), at: .zero)
                instruction.layerInstructions = [videoLayerInstruction]
                let videoComposition = AVMutableVideoComposition()
                videoComposition.renderSize = renderSize
                let sourceFrameDuration = try await sourceVideo.load(.minFrameDuration)
                videoComposition.frameDuration = sourceFrameDuration.isNumeric && sourceFrameDuration > .zero
                    ? sourceFrameDuration : CMTime(value: 1, timescale: 30)
                videoComposition.instructions = [instruction]

                let compositionLayer = CALayer()
                compositionLayer.frame = CGRect(origin: .zero, size: renderSize)
                compositionLayer.isGeometryFlipped = true
                let videoLayer = CALayer()
                videoLayer.frame = compositionLayer.frame
                let watermarkLayer = CALayer()
                let insetX = displayRect.width * CGFloat(marginPercent) / 100
                let insetY = displayRect.height * CGFloat(marginPercent) / 100
                let markAspect = CGFloat(logo.height) / CGFloat(logo.width)
                let desiredMarkWidth = displayRect.width * CGFloat(sizePercent) / 100
                let markWidth = max(1, min(desiredMarkWidth, (displayRect.height - 2 * insetY) / markAspect))
                let markHeight = markWidth * markAspect
                let origin: CGPoint
                switch args[5] {
                case "bottom-right": origin = CGPoint(x: displayRect.width - insetX - markWidth, y: displayRect.height - insetY - markHeight)
                case "bottom-left": origin = CGPoint(x: insetX, y: displayRect.height - insetY - markHeight)
                case "top-right": origin = CGPoint(x: displayRect.width - insetX - markWidth, y: insetY)
                case "top-left": origin = CGPoint(x: insetX, y: insetY)
                default: origin = CGPoint(x: (displayRect.width - markWidth) / 2, y: (displayRect.height - markHeight) / 2)
                }
                watermarkLayer.frame = CGRect(origin: origin, size: CGSize(width: markWidth, height: markHeight))
                watermarkLayer.contents = logo
                watermarkLayer.contentsGravity = .resizeAspect
                watermarkLayer.opacity = Float(opacityPercent) / 100
                compositionLayer.addSublayer(videoLayer)
                compositionLayer.addSublayer(watermarkLayer)
                videoComposition.animationTool = AVVideoCompositionCoreAnimationTool(
                    postProcessingAsVideoLayer: videoLayer, in: compositionLayer
                )
                selfAssignVideoComposition = videoComposition
                preset = AVAssetExportPresetHighestQuality
            } else if operation == "video-crop" {
                guard args.count == 8,
                      let x = Int(args[4]), let y = Int(args[5]),
                      let width = Int(args[6]), let height = Int(args[7]),
                      x >= 0, y >= 0, width > 0, height > 0 else { fail("Invalid crop rectangle") }
                let naturalSize = try await sourceVideo.load(.naturalSize)
                let displayRect = CGRect(origin: .zero, size: naturalSize).applying(preferredTransform).standardized
                let cropRect = CGRect(x: x, y: y, width: width, height: height)
                guard displayRect.contains(cropRect), width <= 10_000, height <= 10_000 else {
                    fail("Crop rectangle is outside the video frame")
                }
                let audioTracks = try await asset.loadTracks(withMediaType: .audio)
                for sourceAudio in audioTracks {
                    guard let audio = composition.addMutableTrack(
                        withMediaType: .audio,
                        preferredTrackID: kCMPersistentTrackID_Invalid
                    ) else { fail("Could not create an output audio track") }
                    let audioRange = try await sourceAudio.load(.timeRange)
                    try audio.insertTimeRange(audioRange, of: sourceAudio, at: .zero)
                }
                video.preferredTransform = .identity
                let instruction = AVMutableVideoCompositionInstruction()
                instruction.timeRange = CMTimeRange(start: .zero, duration: videoRange.duration)
                let layer = AVMutableVideoCompositionLayerInstruction(assetTrack: video)
                let normalize = CGAffineTransform(translationX: -displayRect.minX - CGFloat(x), y: -displayRect.minY - CGFloat(y))
                layer.setTransform(preferredTransform.concatenating(normalize), at: .zero)
                instruction.layerInstructions = [layer]
                let videoComposition = AVMutableVideoComposition()
                videoComposition.renderSize = CGSize(width: width, height: height)
                let sourceFrameDuration = try await sourceVideo.load(.minFrameDuration)
                videoComposition.frameDuration = sourceFrameDuration.isNumeric && sourceFrameDuration > .zero
                    ? sourceFrameDuration : CMTime(value: 1, timescale: 30)
                videoComposition.instructions = [instruction]
                selfAssignVideoComposition = videoComposition
                preset = AVAssetExportPresetHighestQuality
            } else if operation == "video-resize" {
                guard (args.count == 6 || args.count == 7),
                      let maxWidth = Int(args[4]), let maxHeight = Int(args[5]),
                      maxWidth > 0, maxHeight > 0, maxWidth <= 10_000, maxHeight <= 10_000 else {
                    fail("Invalid video dimensions")
                }
                let maxFps = args.count == 7 ? Int(args[6]) : nil
                if let maxFps, !(1...120).contains(maxFps) {
                    fail("Invalid maximum frame rate")
                }
                let naturalSize = try await sourceVideo.load(.naturalSize)
                let displayRect = CGRect(origin: .zero, size: naturalSize).applying(preferredTransform).standardized
                guard displayRect.width > 0, displayRect.height > 0 else { fail("Invalid source dimensions") }
                let scale = min(1, min(CGFloat(maxWidth) / displayRect.width, CGFloat(maxHeight) / displayRect.height))
                let renderWidth = max(1, Int((displayRect.width * scale).rounded(.down)))
                let renderHeight = max(1, Int((displayRect.height * scale).rounded(.down)))
                let audioTracks = try await asset.loadTracks(withMediaType: .audio)
                for sourceAudio in audioTracks {
                    guard let audio = composition.addMutableTrack(
                        withMediaType: .audio,
                        preferredTrackID: kCMPersistentTrackID_Invalid
                    ) else { fail("Could not create an output audio track") }
                    let audioRange = try await sourceAudio.load(.timeRange)
                    try audio.insertTimeRange(audioRange, of: sourceAudio, at: .zero)
                }
                video.preferredTransform = .identity
                let instruction = AVMutableVideoCompositionInstruction()
                instruction.timeRange = CMTimeRange(start: .zero, duration: videoRange.duration)
                let layer = AVMutableVideoCompositionLayerInstruction(assetTrack: video)
                let normalize = CGAffineTransform(translationX: -displayRect.minX, y: -displayRect.minY)
                layer.setTransform(preferredTransform.concatenating(normalize).scaledBy(x: scale, y: scale), at: .zero)
                instruction.layerInstructions = [layer]
                let videoComposition = AVMutableVideoComposition()
                videoComposition.renderSize = CGSize(width: renderWidth, height: renderHeight)
                let sourceFrameDuration = try await sourceVideo.load(.minFrameDuration)
                let fallbackFrameDuration = CMTime(value: 1, timescale: 30)
                let validSourceFrameDuration = sourceFrameDuration.isNumeric && sourceFrameDuration > .zero
                    ? sourceFrameDuration : fallbackFrameDuration
                if let maxFps {
                    let capFrameDuration = CMTime(value: 1, timescale: Int32(maxFps))
                    videoComposition.frameDuration = validSourceFrameDuration > capFrameDuration
                        ? validSourceFrameDuration : capFrameDuration
                } else {
                    videoComposition.frameDuration = validSourceFrameDuration
                }
                videoComposition.instructions = [instruction]
                selfAssignVideoComposition = videoComposition
                preset = AVAssetExportPresetHighestQuality
            } else {
                fail("Unsupported media transform")
            }

            guard let session = AVAssetExportSession(asset: composition, presetName: preset),
                  session.supportedFileTypes.contains(.mov) else {
                fail("The system encoder cannot create a MOV file")
            }
            session.outputURL = outputURL
            session.outputFileType = .mov
            session.videoComposition = selfAssignVideoComposition
            session.shouldOptimizeForNetworkUse = true
            waitForExport(session)
        } catch {
            fail(error.localizedDescription)
        }
    }
}
