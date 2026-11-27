import Foundation

@main
struct SpeechCoachClarityTests {
    static func main() throws {
        guard officekitDictationPolishStatus() == 0 else {
            print("SKIP: Apple Intelligence is unavailable; sentence coaching needs the local model.")
            return
        }
        let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let cases = try JSONSerialization.jsonObject(with: data) as! [[String: String]]
        for (index, example) in cases.enumerated() {
            let source = example["source"]!
            let start = Date()
            let response = review(source)
            let lines = response.components(separatedBy: "\n")
            precondition(lines.count == 4 && lines[0] == "PATTERN: sentence_clarity")
            precondition(lines[1] == "QUOTE: \(source)", "Quote must preserve the original sentence")
            precondition(lines[2].hasPrefix("SUGGESTION: ") && lines[2] != "SUGGESTION: \(source)")
            if index == 2 {
                precondition(!lines[2].contains("win contest"), "The missing article or broken contest phrase must be repaired")
                precondition(!lines[2].contains("in which and"), "The incomplete relative clause must be repaired")
            }
            if index == 3 {
                precondition(!lines[2].contains("kind of"), "Repeated empty qualifiers should be removed")
            }
            precondition(lines[3].hasPrefix("HINT: ") && lines[3].utf8.count <= 126)
            print("Example \(index + 1) (\(Int(Date().timeIntervalSince(start) * 1000)) ms):\n\(response)")
        }
        for clear in ["We should meet tomorrow.", "Could we add comments and prizes?"] {
            precondition(review(clear) == "NONE", "Already clear English should not need a rewrite: \(clear)")
        }
        print("PASS: all \(cases.count) real brainstorm sentences receive on-device clarity coaching.")
    }

    static func review(_ source: String) -> String {
        let input = Array(source.utf8)
        var output = [UInt8](repeating: 0, count: 8_192)
        let count = input.withUnsafeBufferPointer { bytes in
            output.withUnsafeMutableBufferPointer { buffer in
                officekitDictationLanguageSuggestion(bytes.baseAddress, UInt64(bytes.count), 3,
                    buffer.baseAddress, UInt64(buffer.count), 15_000)
            }
        }
        precondition(count > 0 && count <= output.count, "No sentence coaching result for: \(source)")
        return String(decoding: output.prefix(Int(count)), as: UTF8.self)
    }
}
