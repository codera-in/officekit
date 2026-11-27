import AppKit
import ApplicationServices
import Foundation

// Focus context for dictation: which app and kind of field the user is typing in,
// and (only when the user opted in) a short window of the text around the cursor.
// Nothing here logs, stores or returns more than the bounded values below, and
// secure fields are never read.

private let dictationContextCharactersBeforeCursor = 700
private let dictationContextCharactersAfterCursor = 300
private let dictationContextMaxLabelCharacters = 128
private let dictationContextMessagingTimeout: Float = 0.25

private let dictationContextTextRoles: Set<String> = ["AXTextField", "AXTextArea", "AXComboBox"]
private let dictationContextSecureSubrole = "AXSecureTextField"

func dictationContextFieldTextAllowed(role: String?, subrole: String?) -> Bool {
    guard let role, dictationContextTextRoles.contains(role) else { return false }
    return subrole != dictationContextSecureSubrole
}

func dictationContextBounded(_ value: String, limit: Int) -> String {
    let cleaned = value.unicodeScalars
        .map { CharacterSet.controlCharacters.contains($0) ? " " : String($0) }
        .joined()
        .split(whereSeparator: { $0.isWhitespace })
        .joined(separator: " ")
    return String(cleaned.prefix(limit))
}

/// Returns the slice of `value` around the cursor (UTF-16 offset, as Accessibility
/// reports it), widened to whole characters so a surrogate pair is never split.
func dictationContextWindow(value: String, cursorUTF16: Int?) -> String {
    let text = value as NSString
    let length = text.length
    guard length > 0 else { return "" }
    let cursor = min(max(cursorUTF16 ?? length, 0), length)
    var start = max(0, cursor - dictationContextCharactersBeforeCursor)
    var end = min(length, cursor + dictationContextCharactersAfterCursor)
    if start > 0, start < length {
        start = text.rangeOfComposedCharacterSequence(at: start).location
    }
    if end > start, end < length {
        end = NSMaxRange(text.rangeOfComposedCharacterSequence(at: end - 1))
    }
    guard end > start else { return "" }
    return text.substring(with: NSRange(location: start, length: end - start))
}

/// Builds the payload handed to Rust. Field text is included only when the caller
/// opted in and the role is a non-secure text field.
func dictationContextPayload(
    appName: String?,
    bundleID: String?,
    role: String?,
    subrole: String?,
    value: String?,
    cursorUTF16: Int?,
    includeFieldText: Bool
) -> [String: String]? {
    var payload: [String: String] = [:]
    if let appName, !appName.isEmpty {
        payload["app_name"] = dictationContextBounded(appName, limit: dictationContextMaxLabelCharacters)
    }
    if let bundleID, !bundleID.isEmpty {
        payload["bundle_id"] = dictationContextBounded(bundleID, limit: dictationContextMaxLabelCharacters)
    }
    if let role, !role.isEmpty {
        payload["field_role"] = dictationContextBounded(role, limit: dictationContextMaxLabelCharacters)
    }
    if includeFieldText,
       dictationContextFieldTextAllowed(role: role, subrole: subrole),
       let value, !value.isEmpty {
        let window = dictationContextWindow(value: value, cursorUTF16: cursorUTF16)
        if !window.isEmpty { payload["field_text"] = window }
    }
    return payload.isEmpty ? nil : payload
}

private func dictationContextStringAttribute(_ element: AXUIElement, _ name: String) -> String? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
    return value as? String
}

private func dictationContextCursor(_ element: AXUIElement) -> Int? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, kAXSelectedTextRangeAttribute as CFString, &value) == .success,
          let value, CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
    var range = CFRange()
    guard AXValueGetValue(value as! AXValue, .cfRange, &range) else { return nil }
    return range.location >= 0 ? range.location : nil
}

private func dictationContextFrontmostApplication() -> NSRunningApplication? {
    Thread.isMainThread
        ? NSWorkspace.shared.frontmostApplication
        : DispatchQueue.main.sync { NSWorkspace.shared.frontmostApplication }
}

func dictationReadFocusContext(includeFieldText: Bool) -> [String: String]? {
    guard AXIsProcessTrusted() else { return nil }
    let application = dictationContextFrontmostApplication()
    let system = AXUIElementCreateSystemWide()
    AXUIElementSetMessagingTimeout(system, dictationContextMessagingTimeout)
    var focused: CFTypeRef?
    var role: String?
    var subrole: String?
    var value: String?
    var cursor: Int?
    if AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute as CFString, &focused) == .success,
       let focused, CFGetTypeID(focused) == AXUIElementGetTypeID() {
        let element = focused as! AXUIElement
        AXUIElementSetMessagingTimeout(element, dictationContextMessagingTimeout)
        role = dictationContextStringAttribute(element, kAXRoleAttribute as String)
        subrole = dictationContextStringAttribute(element, kAXSubroleAttribute as String)
        // The value is read only for an opted-in, non-secure text field.
        if includeFieldText, dictationContextFieldTextAllowed(role: role, subrole: subrole) {
            value = dictationContextStringAttribute(element, kAXValueAttribute as String)
            cursor = dictationContextCursor(element)
        }
    }
    return dictationContextPayload(
        appName: application?.localizedName,
        bundleID: application?.bundleIdentifier,
        role: role,
        subrole: subrole,
        value: value,
        cursorUTF16: cursor,
        includeFieldText: includeFieldText
    )
}

/// Writes the context as UTF-8 JSON into `output`. Returns the byte count, 0 when
/// there is no context (no Accessibility trust, no frontmost app) and -1 when the
/// buffer is too small. Context is best effort: any failure means "no context".
@_cdecl("officekit_dictation_focus_context")
public func officekitDictationFocusContext(
    _ includeFieldText: Int32,
    _ output: UnsafeMutablePointer<UInt8>?,
    _ capacity: UInt64
) -> Int64 {
    guard let output, capacity > 0,
          let payload = dictationReadFocusContext(includeFieldText: includeFieldText != 0),
          let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) else { return 0 }
    guard UInt64(data.count) <= capacity else { return -1 }
    data.copyBytes(to: output, count: data.count)
    return Int64(data.count)
}
