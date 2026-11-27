import CoreGraphics
import Foundation
import ImageIO
import Vision

private let maxImageBytes = 64 * 1024 * 1024
private let maxImagePixels = 40_000_000
private let maxObservations = 10_000
private let maxOutputBytes = 1024 * 1024
private let invalidInputExit: Int32 = 65
private let unavailableExit: Int32 = 69

private func fail(_ code: Int32) -> Never {
    exit(code)
}

private func readBoundedInput() -> Data {
    var input = Data()
    do {
        while let chunk = try FileHandle.standardInput.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            guard input.count + chunk.count <= maxImageBytes else { fail(invalidInputExit) }
            input.append(chunk)
        }
    } catch {
        fail(invalidInputExit)
    }
    guard !input.isEmpty else { fail(invalidInputExit) }
    return input
}

private func observations(from image: CGImage) -> [[String: Any]] {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    request.minimumTextHeight = 0.006
    request.recognitionLanguages = ["en-US"]

    do {
        try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    } catch {
        let diagnostic = "officekit-vision-ocr: Vision request failed (\((error as NSError).domain), \((error as NSError).code)): \(error.localizedDescription)\n"
        FileHandle.standardError.write(Data(diagnostic.utf8))
        fail(unavailableExit)
    }

    let results = request.results ?? []
    guard results.count <= maxObservations else { fail(invalidInputExit) }
    return results.flatMap { observation -> [[String: Any]] in
        guard let candidate = observation.topCandidates(1).first else { return [] }
        let text = candidate.string
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              text.utf8.count <= 4096 else { return [] }
        let expression = try! NSRegularExpression(pattern: #"\S+"#)
        let fullRange = NSRange(text.startIndex..<text.endIndex, in: text)
        let matches = expression.matches(in: text, range: fullRange)
        let boxes = matches.compactMap { match -> [String: Any]? in
            guard let range = Range(match.range, in: text),
                  let box = try? candidate.boundingBox(for: range) else { return nil }
            let token = String(text[range])
            return [
                "text": token,
                "x": Double(box.boundingBox.origin.x),
                "y": Double(box.boundingBox.origin.y),
                "width": Double(box.boundingBox.width),
                "height": Double(box.boundingBox.height),
                "confidence": Double(candidate.confidence),
            ]
        }
        return boxes
    }
}

let input = readBoundedInput()
guard let source = CGImageSourceCreateWithData(input as CFData, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
      image.width > 0,
      image.height > 0,
      image.width <= maxImagePixels / image.height else {
    fail(invalidInputExit)
}

let result = observations(from: image)
let output: Data
do {
    output = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
} catch {
    fail(unavailableExit)
}
guard output.count <= maxOutputBytes else { fail(invalidInputExit) }
FileHandle.standardOutput.write(output)
