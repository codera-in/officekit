import AVFoundation
import CoreMedia
import CoreVideo
import Foundation

let outputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let width = 160
let height = 120
let frameCount = 600
let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mov)
let title = AVMutableMetadataItem()
title.identifier = .commonIdentifierTitle
title.value = "OfficeKit private metadata smoke" as NSString
title.dataType = kCMMetadataBaseDataType_UTF8 as String
writer.metadata = [title]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width,
    AVVideoHeightKey: height,
])
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
    kCVPixelBufferWidthKey as String: width,
    kCVPixelBufferHeightKey as String: height,
    kCVPixelBufferCGImageCompatibilityKey as String: true,
    kCVPixelBufferCGBitmapContextCompatibilityKey as String: true,
])
guard writer.canAdd(input) else { fatalError("Video writer rejected the test stream") }
writer.add(input)
guard writer.startWriting() else { fatalError(writer.error?.localizedDescription ?? "Video writer failed to start") }
writer.startSession(atSourceTime: .zero)

for frame in 0..<frameCount {
    while !input.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.002) }
    guard let pool = adaptor.pixelBufferPool else { fatalError("Video pixel buffer pool is unavailable") }
    var maybeBuffer: CVPixelBuffer?
    guard CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, pool, &maybeBuffer) == kCVReturnSuccess,
          let buffer = maybeBuffer,
          CVPixelBufferLockBaseAddress(buffer, []) == kCVReturnSuccess,
          let base = CVPixelBufferGetBaseAddress(buffer) else {
        fatalError("Video frame allocation failed")
    }
    let rowBytes = CVPixelBufferGetBytesPerRow(buffer)
    let pixels = base.assumingMemoryBound(to: UInt8.self)
    for y in 0..<height {
        for x in 0..<width {
            let offset = y * rowBytes + x * 4
            pixels[offset] = 255
            pixels[offset + 1] = UInt8((x + frame) % 256)
            pixels[offset + 2] = UInt8((y * 2 + frame) % 256)
            pixels[offset + 3] = 180
        }
    }
    CVPixelBufferUnlockBaseAddress(buffer, [])
    guard adaptor.append(buffer, withPresentationTime: CMTime(value: Int64(frame), timescale: 30)) else {
        fatalError(writer.error?.localizedDescription ?? "Video frame append failed")
    }
}

input.markAsFinished()
let finished = DispatchSemaphore(value: 0)
writer.finishWriting { finished.signal() }
guard finished.wait(timeout: .now() + 30) == .success, writer.status == .completed else {
    fatalError(writer.error?.localizedDescription ?? "Video test stream did not finish")
}
