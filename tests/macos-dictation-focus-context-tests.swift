import Foundation

@main
struct MacOSDictationContextTests {
    static func main() {
        // Secure fields and non-text roles never allow field text.
        require(dictationContextFieldTextAllowed(role: "AXTextField", subrole: nil), "Plain text fields allow field text")
        require(dictationContextFieldTextAllowed(role: "AXTextArea", subrole: nil), "Text areas allow field text")
        require(!dictationContextFieldTextAllowed(role: "AXTextField", subrole: "AXSecureTextField"), "Password fields must never be read")
        require(!dictationContextFieldTextAllowed(role: "AXButton", subrole: nil), "Non-text roles must not be read")
        require(!dictationContextFieldTextAllowed(role: nil, subrole: nil), "Missing role must not be read")

        // The window is bounded around the cursor and never splits a character.
        let long = String(repeating: "a", count: 5_000)
        require(dictationContextWindow(value: long, cursorUTF16: 2_500).count == 1_000, "Window is 700 before plus 300 after the cursor")
        require(dictationContextWindow(value: long, cursorUTF16: nil).count == 700, "Missing cursor uses the end of the text")
        require(dictationContextWindow(value: "hello", cursorUTF16: 99) == "hello", "Cursor past the end is clamped")
        require(dictationContextWindow(value: "", cursorUTF16: 0).isEmpty, "Empty value gives empty window")
        let emoji = String(repeating: "\u{1F600}", count: 600)
        let window = dictationContextWindow(value: emoji, cursorUTF16: 600)
        require(window.unicodeScalars.allSatisfy { $0 == "\u{1F600}" }, "A surrogate pair is never split")

        // Payload: opt-in gating, secure fields, bounds and cleaning.
        let optedOut = dictationContextPayload(appName: "Slack", bundleID: "com.tinyspeck.slackmacgap", role: "AXTextArea", subrole: nil, value: "secret draft", cursorUTF16: 3, includeFieldText: false)
        require(optedOut?["app_name"] == "Slack" && optedOut?["field_role"] == "AXTextArea", "App and role are reported without field text")
        require(optedOut?["field_text"] == nil, "Field text is absent unless the user opted in")
        let optedIn = dictationContextPayload(appName: "Slack", bundleID: nil, role: "AXTextArea", subrole: nil, value: "hello Sedhu", cursorUTF16: 11, includeFieldText: true)
        require(optedIn?["field_text"] == "hello Sedhu", "Opted-in text fields report the surrounding text")
        let secure = dictationContextPayload(appName: "Safari", bundleID: nil, role: "AXTextField", subrole: "AXSecureTextField", value: "hunter2", cursorUTF16: 7, includeFieldText: true)
        require(secure?["field_text"] == nil && secure?["field_role"] == "AXTextField", "Secure fields never leak text even when opted in")
        require(dictationContextPayload(appName: nil, bundleID: nil, role: nil, subrole: nil, value: "x", cursorUTF16: 0, includeFieldText: true) == nil, "No identifying facts means no context")
        let cleaned = dictationContextPayload(appName: "Mail\n\u{0}App", bundleID: nil, role: nil, subrole: nil, value: nil, cursorUTF16: nil, includeFieldText: false)
        require(cleaned?["app_name"] == "Mail App", "Control characters are removed from labels")
        let longName = dictationContextPayload(appName: String(repeating: "N", count: 500), bundleID: nil, role: nil, subrole: nil, value: nil, cursorUTF16: nil, includeFieldText: false)
        require(longName?["app_name"]?.count == 128, "Labels are bounded")

        // The exported function must fail closed without a buffer.
        require(officekitDictationFocusContext(0, nil, 64) == 0, "A missing buffer returns no context")
        var tiny = [UInt8](repeating: 0, count: 1)
        let written = tiny.withUnsafeMutableBufferPointer { officekitDictationFocusContext(0, $0.baseAddress, 1) }
        require(written == 0 || written == -1, "A too-small buffer never overruns")
        print("macOS dictation focus context: 19 checks passed")
    }

    private static func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else { fatalError(message) }
    }
}
