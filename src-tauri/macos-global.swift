import AppKit
import ApplicationServices
import Carbon.HIToolbox
import Foundation
import OSLog
import ServiceManagement

private let globalDiagnosticLogger = Logger(subsystem: "app.officekit.desktop", category: "global-desktop")

private func onMainSync<T>(_ operation: () -> T) -> T {
    Thread.isMainThread ? operation() : DispatchQueue.main.sync(execute: operation)
}

/// Bytes from the system's secure random generator (used for generated passwords and UUIDs).
private func secureRandomBytes(_ count: Int) -> [UInt8] {
    var bytes = [UInt8](repeating: 0, count: count)
    let status = SecRandomCopyBytes(kSecRandomDefault, count, &bytes)
    // A failure is not expected; fall back to the system generator rather than return predictable bytes.
    if status != errSecSuccess { for index in bytes.indices { bytes[index] = UInt8.random(in: 0...255) } }
    return bytes
}

/// Runs `body` with a pointer and length for a string, or nil and 0 when it is absent.
private func withUTF8Bytes(_ text: String?, _ body: (UnsafePointer<UInt8>?, UInt64) -> Void) {
    guard let text else { return body(nil, 0) }
    let bytes = Array(text.utf8)
    bytes.withUnsafeBufferPointer { body($0.baseAddress, UInt64($0.count)) }
}

// MARK: - Global shortcuts (Carbon RegisterEventHotKey: swallows the key, needs no Accessibility)

private final class OfficeKitGlobalHotkeys {
    static let shared = OfficeKitGlobalHotkeys()

    let signature: OSType = 0x4F4B4754 // 'OKGT'
    private var handlerRef: EventHandlerRef?
    private var registered: [UInt32: EventHotKeyRef] = [:]
    var callback: (@convention(c) (Int32) -> Void)?

    private func installHandlerIfNeeded() -> Bool {
        if handlerRef != nil { return true }
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let status = InstallEventHandler(GetApplicationEventTarget(), { _, event, _ -> OSStatus in
            var identifier = EventHotKeyID()
            let result = GetEventParameter(
                event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                nil, MemoryLayout<EventHotKeyID>.size, nil, &identifier
            )
            // Other components (the screenshot shortcut plugin) share this event target; leave their keys to them.
            guard result == noErr, identifier.signature == OfficeKitGlobalHotkeys.shared.signature,
                  identifier.id <= UInt32(Int32.max) else { return OSStatus(eventNotHandledErr) }
            OfficeKitGlobalHotkeys.shared.callback?(Int32(identifier.id))
            return noErr
        }, 1, &spec, nil, &handlerRef)
        return status == noErr
    }

    /// 0 registered, 1 already registered, 3 refused by macOS (for example another app owns it), 4 invalid.
    func register(id: Int32, keyCode: Int32, modifierMask: Int32) -> Int32 {
        guard id >= 0, globalShortcutIsRegistrable(keyCode: keyCode, modifierMask: modifierMask),
              let modifiers = globalCarbonModifiers(forMask: UInt8(modifierMask)) else { return 4 }
        guard installHandlerIfNeeded() else { return 3 }
        let identifier = UInt32(id)
        if registered[identifier] != nil { return 1 }
        var reference: EventHotKeyRef?
        let hotKeyID = EventHotKeyID(signature: signature, id: identifier)
        let status = RegisterEventHotKey(UInt32(keyCode), modifiers, hotKeyID, GetApplicationEventTarget(), 0, &reference)
        guard status == noErr, let reference else {
            globalDiagnosticLogger.notice("Global shortcut registration refused status=\(status, privacy: .public)")
            return 3
        }
        registered[identifier] = reference
        return 0
    }

    func unregisterAll() {
        for reference in registered.values { UnregisterEventHotKey(reference) }
        registered.removeAll()
    }
}

@_cdecl("officekit_global_hotkey_set_callback")
public func officekitGlobalHotkeySetCallback(_ callback: @escaping @convention(c) (Int32) -> Void) {
    OfficeKitGlobalHotkeys.shared.callback = callback
}

@_cdecl("officekit_global_hotkey_register")
public func officekitGlobalHotkeyRegister(_ id: Int32, _ keyCode: Int32, _ modifierMask: Int32) -> Int32 {
    onMainSync { OfficeKitGlobalHotkeys.shared.register(id: id, keyCode: keyCode, modifierMask: modifierMask) }
}

@_cdecl("officekit_global_hotkey_unregister_all")
public func officekitGlobalHotkeyUnregisterAll() {
    onMainSync { OfficeKitGlobalHotkeys.shared.unregisterAll() }
}

// MARK: - Login item

/// 0 off, 1 on, 2 waiting for approval in System Settings, 3 unavailable.
@_cdecl("officekit_global_login_item_status")
public func officekitGlobalLoginItemStatus() -> Int32 {
    switch SMAppService.mainApp.status {
    case .enabled: return 1
    case .notRegistered: return 0
    case .requiresApproval: return 2
    default: return 3
    }
}

/// Returns the resulting status code, or 3 when macOS refused the change.
@_cdecl("officekit_global_login_item_set")
public func officekitGlobalLoginItemSet(_ enabled: Int32) -> Int32 {
    do {
        if enabled != 0 {
            try SMAppService.mainApp.register()
        } else {
            try SMAppService.mainApp.unregister()
        }
    } catch {
        globalDiagnosticLogger.notice("Login item change refused")
        return 3
    }
    return officekitGlobalLoginItemStatus()
}

// MARK: - Pasteboard watcher

private let globalMaxClipTextBytes = 5 * 1024 * 1024
private let globalMaxClipImageBytes = 4 * 1024 * 1024

private final class OfficeKitPasteboardWatcher {
    static let shared = OfficeKitPasteboardWatcher()

    /// kind (0 text, 1 PNG image), payload, frontmost bundle id, frontmost app name.
    var callback: (@convention(c) (Int32, UnsafePointer<UInt8>?, UInt64, UnsafePointer<UInt8>?, UInt64, UnsafePointer<UInt8>?, UInt64) -> Void)?

    private let pasteboard = NSPasteboard.general
    private var timer: Timer?
    private var lastChangeCount = NSPasteboard.general.changeCount
    private var ownChangeCount = -1
    private(set) var skipBundleIDs: Set<String> = []

    func start(skipBundleIDs: Set<String>) {
        self.skipBundleIDs = skipBundleIDs
        guard timer == nil else { return }
        lastChangeCount = pasteboard.changeCount
        let timer = Timer(timeInterval: 0.3, repeats: true) { [weak self] _ in self?.poll() }
        timer.tolerance = 0.1
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    /// Remembers the pasteboard state after OfficeKit's own write so it is not captured as a new clip.
    func markOwnWrite() {
        ownChangeCount = pasteboard.changeCount
    }

    private func poll() {
        let count = pasteboard.changeCount
        guard count != lastChangeCount else { return }
        lastChangeCount = count
        guard count != ownChangeCount else { return }
        let types = pasteboard.types?.map(\.rawValue) ?? []
        let front = NSWorkspace.shared.frontmostApplication
        guard globalPasteboardShouldCapture(types: types, frontmostBundleID: front?.bundleIdentifier, skipBundleIDs: skipBundleIDs) else { return }
        if let text = pasteboard.string(forType: .string), !text.isEmpty {
            guard text.utf8.count <= globalMaxClipTextBytes else { return }
            deliver(kind: 0, payload: Data(text.utf8), bundleID: front?.bundleIdentifier, name: front?.localizedName)
        } else if let png = pngData(), png.count <= globalMaxClipImageBytes {
            deliver(kind: 1, payload: png, bundleID: front?.bundleIdentifier, name: front?.localizedName)
        }
    }

    private func pngData() -> Data? {
        guard let image = NSImage(pasteboard: pasteboard), let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff) else { return nil }
        return bitmap.representation(using: .png, properties: [:])
    }

    private func deliver(kind: Int32, payload: Data, bundleID: String?, name: String?) {
        guard let callback else { return }
        payload.withUnsafeBytes { raw in
            let bytes = raw.bindMemory(to: UInt8.self).baseAddress
            withUTF8Bytes(bundleID) { bundleBytes, bundleLength in
                withUTF8Bytes(name) { nameBytes, nameLength in
                    callback(kind, bytes, UInt64(payload.count), bundleBytes, bundleLength, nameBytes, nameLength)
                }
            }
        }
    }
}

/// Called by the dictation paster after it writes the pasteboard, so its text is not recaptured.
func officekitGlobalMarkOwnPasteboardWrite() {
    OfficeKitPasteboardWatcher.shared.markOwnWrite()
}

@_cdecl("officekit_global_clipboard_set_callback")
public func officekitGlobalClipboardSetCallback(
    _ callback: @escaping @convention(c) (Int32, UnsafePointer<UInt8>?, UInt64, UnsafePointer<UInt8>?, UInt64, UnsafePointer<UInt8>?, UInt64) -> Void
) {
    OfficeKitPasteboardWatcher.shared.callback = callback
}

/// Starts background capture. `skip` is a JSON array of bundle identifiers to ignore. 4 on invalid JSON.
@_cdecl("officekit_global_clipboard_start")
public func officekitGlobalClipboardStart(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64) -> Int32 {
    var skip: [String] = []
    if let bytes, length > 0 {
        guard length <= 64 * 1024,
              let decoded = try? JSONSerialization.jsonObject(with: Data(bytes: bytes, count: Int(length))) as? [String] else { return 4 }
        skip = decoded
    }
    onMainSync { OfficeKitPasteboardWatcher.shared.start(skipBundleIDs: Set(skip)) }
    return 0
}

@_cdecl("officekit_global_clipboard_stop")
public func officekitGlobalClipboardStop() {
    onMainSync { OfficeKitPasteboardWatcher.shared.stop() }
}

// MARK: - Pasting into the previous app

private func postCommandV() -> Bool {
    guard let source = CGEventSource(stateID: .hidSystemState),
          let keyDown = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: true),
          let keyUp = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: false) else { return false }
    keyDown.flags = .maskCommand
    keyUp.flags = .maskCommand
    keyDown.post(tap: .cghidEventTap)
    keyUp.post(tap: .cghidEventTap)
    return true
}

/// Writes text (kind 0) or PNG data (kind 1) to the pasteboard and sends Cmd+V to the target app.
/// 0 requested, 1 Accessibility missing (content stays on the clipboard), 3 failure,
/// 4 target changed or focus cannot take a paste (content stays on the clipboard).
private func pasteIntoTarget(kind: Int32, payload: Data, targetPID: pid_t, restoreAfter: Bool) -> Int32 {
    let pasteboard = NSPasteboard.general
    let previous = restoreAfter ? OfficeKitTranscriptPaster.shared.snapshot(pasteboard) : nil
    if restoreAfter && previous == nil { return 3 }
    pasteboard.clearContents()
    // Marked transient so other clipboard managers do not record text OfficeKit only borrows the clipboard for.
    let transient = NSPasteboard.PasteboardType("org.nspasteboard.TransientType")
    let written: Bool
    if kind == 1 {
        pasteboard.declareTypes([.png, transient], owner: nil)
        written = pasteboard.setData(payload, forType: .png)
    } else if let text = String(data: payload, encoding: .utf8) {
        pasteboard.declareTypes([.string, transient], owner: nil)
        written = pasteboard.setString(text, forType: .string)
    } else {
        written = false
    }
    if written { pasteboard.setData(Data(), forType: transient) }
    guard written else {
        if let previous { OfficeKitTranscriptPaster.shared.restore(previous, to: pasteboard) }
        return 3
    }
    OfficeKitPasteboardWatcher.shared.markOwnWrite()
    let writtenCount = pasteboard.changeCount
    guard AXIsProcessTrusted() else { return 1 }
    guard dictationPasteTargetMatches(
        expectedPID: targetPID == 0 ? nil : targetPID,
        currentPID: NSWorkspace.shared.frontmostApplication?.processIdentifier
    ) else { return 4 }
    guard !dictationFocusClearlyRejectsPaste() else { return 4 }
    guard postCommandV() else { return 3 }
    if let previous {
        // Slow targets (Electron, VMs) read the pasteboard late; restoring too early would paste the old clipboard.
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
            guard pasteboard.changeCount == writtenCount else { return }
            OfficeKitTranscriptPaster.shared.restore(previous, to: pasteboard)
            OfficeKitPasteboardWatcher.shared.markOwnWrite()
        }
    }
    return 0
}

@_cdecl("officekit_global_paste")
public func officekitGlobalPaste(_ kind: Int32, _ bytes: UnsafePointer<UInt8>?, _ length: UInt64, _ targetPID: Int32) -> Int32 {
    guard (kind == 0 || kind == 1), let bytes, length > 0,
          length <= UInt64(kind == 1 ? globalMaxClipImageBytes : globalMaxClipTextBytes) else { return 4 }
    let payload = Data(bytes: bytes, count: Int(length))
    return onMainSync { pasteIntoTarget(kind: kind, payload: payload, targetPID: pid_t(targetPID), restoreAfter: false) }
}

/// Copies the current pasteboard text into `output`. Returns the byte count, 0 when there is no text,
/// or -1 when it does not fit.
@_cdecl("officekit_global_clipboard_text")
public func officekitGlobalClipboardText(_ output: UnsafeMutablePointer<UInt8>?, _ capacity: UInt64) -> Int64 {
    guard let output, capacity > 0 else { return -1 }
    let text = onMainSync { NSPasteboard.general.string(forType: .string) } ?? ""
    let bytes = Array(text.utf8)
    guard UInt64(bytes.count) <= capacity else { return -1 }
    bytes.withUnsafeBufferPointer { buffer in
        if let base = buffer.baseAddress { output.update(from: base, count: bytes.count) }
    }
    return Int64(bytes.count)
}

/// Asks for one value per variable name. `names` is a JSON array; the answer is a JSON object written
/// to `output`. Returns its byte count, -1 when cancelled, -2 on invalid input, -3 when it does not fit.
@_cdecl("officekit_global_prompt")
public func officekitGlobalPrompt(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64, _ targetPID: Int32,
                                  _ output: UnsafeMutablePointer<UInt8>?, _ capacity: UInt64) -> Int64 {
    guard let bytes, length > 0, length <= 64 * 1024, let output, capacity > 0,
          let names = (try? JSONSerialization.jsonObject(with: Data(bytes: bytes, count: Int(length)))) as? [String],
          !names.isEmpty, names.count <= 8, names.allSatisfy({ !$0.isEmpty && $0.count <= 64 }) else { return -2 }
    return onMainSync { () -> Int64 in
        let alert = NSAlert()
        alert.messageText = "Fill in snippet values"
        alert.addButton(withTitle: "Insert")
        alert.addButton(withTitle: "Cancel")
        let rowHeight: CGFloat = 32
        let labelWidth: CGFloat = 96
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 320, height: CGFloat(names.count) * rowHeight))
        var fields: [NSTextField] = []
        for (index, name) in names.enumerated() {
            let y = CGFloat(names.count - 1 - index) * rowHeight
            let label = NSTextField(labelWithString: name)
            label.lineBreakMode = .byTruncatingTail
            label.frame = NSRect(x: 0, y: y + 4, width: labelWidth - 8, height: 20)
            let field = NSTextField(frame: NSRect(x: labelWidth, y: y + 2, width: 320 - labelWidth, height: 24))
            container.addSubview(label)
            container.addSubview(field)
            fields.append(field)
        }
        alert.accessoryView = container
        alert.window.initialFirstResponder = fields.first
        NSApp.activate(ignoringOtherApps: true)
        let response = alert.runModal()
        if targetPID > 0 { NSRunningApplication(processIdentifier: pid_t(targetPID))?.activate() }
        guard response == .alertFirstButtonReturn else { return -1 }
        var values: [String: String] = [:]
        for (name, field) in zip(names, fields) { values[name] = field.stringValue }
        guard let data = try? JSONSerialization.data(withJSONObject: values) else { return -2 }
        guard UInt64(data.count) <= capacity else { return -3 }
        data.withUnsafeBytes { raw in
            if let base = raw.bindMemory(to: UInt8.self).baseAddress { output.update(from: base, count: data.count) }
        }
        Thread.sleep(forTimeInterval: 0.2)
        return Int64(data.count)
    }
}

// MARK: - Snippet keyword expansion

private final class OfficeKitKeywordMonitor {
    static let shared = OfficeKitKeywordMonitor()

    var callback: (@convention(c) (UnsafePointer<UInt8>?, UInt64) -> Void)?
    private var monitor: Any?
    private var triggers: Set<String> = []
    private var buffer = GlobalKeywordBuffer()
    private var suppressUntil = Date.distantPast

    var bufferText: String { buffer.text }

    func configure(triggers: Set<String>, enabled: Bool) {
        self.triggers = triggers
        buffer.reset()
        if enabled && !triggers.isEmpty {
            guard monitor == nil else { return }
            monitor = NSEvent.addGlobalMonitorForEvents(matching: [.keyDown, .leftMouseDown]) { [weak self] event in
                self?.handle(event)
            }
        } else if let monitor {
            NSEvent.removeMonitor(monitor)
            self.monitor = nil
        }
    }

    /// Ignores the keystrokes OfficeKit itself sends while expanding.
    func suppress(for seconds: TimeInterval) {
        suppressUntil = Date().addingTimeInterval(seconds)
        buffer.reset()
    }

    func reset() { buffer.reset() }

    private func handle(_ event: NSEvent) {
        guard Date() >= suppressUntil else { return }
        // Keystrokes in skipped apps (password managers, terminals the user listed) are never buffered.
        let front = NSWorkspace.shared.frontmostApplication?.bundleIdentifier
        if event.type == .leftMouseDown || IsSecureEventInputEnabled()
            || front.map({ globalBundleIDIsSkipped($0, skipBundleIDs: OfficeKitPasteboardWatcher.shared.skipBundleIDs) }) == true {
            buffer.reset()
            return
        }
        let modifiers = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        if !modifiers.isDisjoint(with: [.command, .control, .option]) {
            buffer.reset()
            return
        }
        switch event.keyCode {
        case 51:
            buffer.deleteLast()
            return
        case 36, 48, 53, 76, 117, 123, 124, 125, 126:
            buffer.reset()
            return
        default:
            break
        }
        guard let characters = event.characters, !characters.isEmpty,
              characters.unicodeScalars.allSatisfy({ !CharacterSet.controlCharacters.contains($0) }) else {
            buffer.reset()
            return
        }
        buffer.append(characters, now: Date())
        if let match = globalKeywordMatch(buffer: buffer.text, triggers: triggers), let callback {
            withUTF8Bytes(match) { bytes, length in callback(bytes, length) }
        }
    }
}

@_cdecl("officekit_global_keywords_set_callback")
public func officekitGlobalKeywordsSetCallback(_ callback: @escaping @convention(c) (UnsafePointer<UInt8>?, UInt64) -> Void) {
    OfficeKitKeywordMonitor.shared.callback = callback
}

/// `triggers` is a JSON array of keywords. 1 when Accessibility is missing, 4 on invalid JSON.
@_cdecl("officekit_global_keywords_configure")
public func officekitGlobalKeywordsConfigure(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64, _ enabled: Int32) -> Int32 {
    var triggers: [String] = []
    if let bytes, length > 0 {
        guard length <= 256 * 1024,
              let decoded = try? JSONSerialization.jsonObject(with: Data(bytes: bytes, count: Int(length))) as? [String] else { return 4 }
        triggers = decoded.filter { !$0.isEmpty && $0.count <= 32 }
    }
    if enabled != 0 && !triggers.isEmpty && !AXIsProcessTrusted() { return 1 }
    onMainSync { OfficeKitKeywordMonitor.shared.configure(triggers: Set(triggers), enabled: enabled != 0) }
    return 0
}

/// Replaces the typed keyword with `text`: deletes it with Backspace, pastes, then restores the clipboard.
/// 0 requested, 1 Accessibility missing, 3 failure, 4 the typed text changed or input is secure.
@_cdecl("officekit_global_expand")
public func officekitGlobalExpand(_ triggerBytes: UnsafePointer<UInt8>?, _ triggerLength: UInt64, _ textBytes: UnsafePointer<UInt8>?, _ textLength: UInt64) -> Int32 {
    guard let triggerBytes, triggerLength > 0, triggerLength <= 256,
          let trigger = String(bytes: UnsafeBufferPointer(start: triggerBytes, count: Int(triggerLength)), encoding: .utf8),
          let textBytes, textLength > 0, textLength <= UInt64(globalMaxClipTextBytes) else { return 4 }
    let payload = Data(bytes: textBytes, count: Int(textLength))
    return onMainSync {
        guard AXIsProcessTrusted() else { return Int32(1) }
        let monitor = OfficeKitKeywordMonitor.shared
        guard !IsSecureEventInputEnabled(), monitor.bufferText.hasSuffix(trigger) else { return Int32(4) }
        // Everything the paste needs is checked before the typed keyword is deleted.
        guard OfficeKitTranscriptPaster.shared.snapshot(NSPasteboard.general) != nil,
              !dictationFocusClearlyRejectsPaste() else { return Int32(4) }
        guard let source = CGEventSource(stateID: .hidSystemState) else { return Int32(3) }
        monitor.suppress(for: 1.0)
        for _ in 0..<trigger.count {
            guard let down = CGEvent(keyboardEventSource: source, virtualKey: 51, keyDown: true),
                  let up = CGEvent(keyboardEventSource: source, virtualKey: 51, keyDown: false) else { return Int32(3) }
            down.post(tap: .cghidEventTap)
            up.post(tap: .cghidEventTap)
        }
        return pasteIntoTarget(kind: 0, payload: payload, targetPID: 0, restoreAfter: true)
    }
}

// MARK: - Picker panel (non-activating, key-capable, floating over full-screen apps)

/// Search cell with breathing room: the text starts clear of the magnifier and is centred vertically
/// in the tall field (the stock square cell packs both against the edges).
private final class PickerSearchFieldCell: NSSearchFieldCell {
    override func searchButtonRect(forBounds rect: NSRect) -> NSRect {
        var button = super.searchButtonRect(forBounds: rect)
        button.origin.x += 6
        return button
    }

    override func searchTextRect(forBounds rect: NSRect) -> NSRect {
        var text = super.searchTextRect(forBounds: rect)
        text.origin.x += 12
        text.size.width -= 12
        if let font {
            let line = ceil(font.ascender - font.descender + font.leading)
            if text.height > line {
                text.origin.y += (text.height - line) / 2
                text.size.height = line
            }
        }
        return text
    }

    override func cancelButtonRect(forBounds rect: NSRect) -> NSRect {
        var button = super.cancelButtonRect(forBounds: rect)
        button.origin.x -= 6
        return button
    }
}

private final class PickerSearchField: NSSearchField {
    override class var cellClass: AnyClass? {
        get { PickerSearchFieldCell.self }
        set {}
    }
}

private final class GlobalPickerPanel: NSPanel {
    var onCommandKey: ((String) -> Bool)?
    /// Called with the key code and the control/option/shift/command mask of every key press.
    var onChipKey: ((Int, Int) -> Bool)?

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    override func sendEvent(_ event: NSEvent) {
        if event.type == .keyDown {
            let flags = event.modifierFlags
            var mask = 0
            if flags.contains(.control) { mask |= Int(globalModifierControl) }
            if flags.contains(.option) { mask |= Int(globalModifierOption) }
            if flags.contains(.shift) { mask |= Int(globalModifierShift) }
            if flags.contains(.command) { mask |= Int(globalModifierCommand) }
            if mask != 0, onChipKey?(Int(event.keyCode), mask) == true { return }
        }
        super.sendEvent(event)
    }

    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        let modifiers = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        if modifiers == .command {
            if event.keyCode == 51, onCommandKey?("delete") == true { return true }
            if event.charactersIgnoringModifiers?.lowercased() == "p", onCommandKey?("pin") == true { return true }
            if let key = event.charactersIgnoringModifiers, onCommandKey?("quick:\(key)") == true { return true }
        }
        return super.performKeyEquivalent(with: event)
    }
}

private final class GlobalPickerController: NSObject, NSSearchFieldDelegate, NSTableViewDataSource, NSTableViewDelegate, NSWindowDelegate {
    static let shared = GlobalPickerController()

    /// Selected item id and action: 0 paste, 1 paste plain, 2 pin or unpin, 3 delete.
    var callback: (@convention(c) (UnsafePointer<UInt8>?, UInt64, Int32) -> Void)?
    private(set) var targetPID: pid_t = 0

    private var panel: GlobalPickerPanel?
    private let search = PickerSearchField()
    private let table = NSTableView()
    private let titleLabel = NSTextField(labelWithString: "")
    private let footer = NSTextField(labelWithString: "")
    private let chipControl = NSSegmentedControl()
    private let appIcon = NSImageView()
    private let brand = NSTextField(labelWithString: "OfficeKit  ·")
    private let scroll = NSScrollView()
    private let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("item"))
    private var content = GlobalPickerContent(style: "", title: "", placeholder: "", chips: [], items: [])
    private var visible: [GlobalPickerItem] = []
    private var iconCache: [String: NSImage] = [:]

    private var isLauncher: Bool { content.style == "launcher" }
    private var panelWidth: CGFloat { isLauncher ? 720 : 520 }

    private var selectedChip: String {
        let index = chipControl.selectedSegment
        return content.chips.indices.contains(index) ? content.chips[index].id : "all"
    }

    func show(_ newContent: GlobalPickerContent) {
        targetPID = NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0
        buildPanelIfNeeded()
        apply(newContent, keepState: false)
        let screen = NSScreen.screens.first(where: { NSMouseInRect(NSEvent.mouseLocation, $0.frame, false) }) ?? NSScreen.main
        if let frame = screen?.visibleFrame, let panel {
            // The top edge sits where the standard panel's top edge sits, so a growing launcher grows downward.
            // Every panel (launcher, clipboard, snippets) hangs from 70% of the screen height, measured from the bottom.
            let top = frame.minY + frame.height * 0.70
            panel.setFrameOrigin(NSPoint(x: frame.midX - panel.frame.width / 2, y: top - panel.frame.height))
        }
        panel?.makeKeyAndOrderFront(nil)
        panel?.makeFirstResponder(search)
    }

    /// Replaces the rows while keeping the search text, chip and selected position.
    func update(_ newContent: GlobalPickerContent) {
        guard panel?.isVisible == true else { return }
        apply(newContent, keepState: true)
    }

    func hide() {
        panel?.orderOut(nil)
    }

    private func apply(_ newContent: GlobalPickerContent, keepState: Bool) {
        let previousRow = table.selectedRow
        let previousChip = chipControl.selectedSegment
        content = newContent
        titleLabel.stringValue = newContent.title
        search.placeholderString = newContent.placeholder
        if !keepState { search.stringValue = "" }
        chipControl.segmentCount = newContent.chips.count
        for (index, chip) in newContent.chips.enumerated() {
            var label = chip.label
            if let keyCode = chip.keyCode, let mask = chip.modifierMask {
                label += "  " + globalShortcutLabel(keyCode: keyCode, modifierMask: mask)
            }
            chipControl.setLabel(label, forSegment: index)
            chipControl.setWidth(0, forSegment: index)
        }
        table.rowHeight = isLauncher ? CGFloat(globalLauncherRowHeight) : 34
        // Every panel shares the launcher's large, square search field.
        search.font = .systemFont(ofSize: 24)
        (search.cell as? NSSearchFieldCell)?.bezelStyle = .squareBezel
        footer.stringValue = isLauncher
            ? "↵ open or paste   ⌘1–9 pick row   ⇥ filter   esc close"
            : "↵ paste   ⌘1–9 paste row   ⇥ filter   ⌘P pin   ⌘⌫ delete   esc close"
        chipControl.isHidden = newContent.chips.isEmpty
        // A fresh panel opens on the chip the user chose in Settings ("Panel opens on"), when it has one.
        let startChip = newContent.chips.firstIndex { $0.id == newContent.initialChip } ?? 0
        chipControl.selectedSegment = newContent.chips.isEmpty ? -1 : (keepState && previousChip >= 0 && previousChip < newContent.chips.count ? previousChip : startChip)
        applyFilter()
        if keepState, !visible.isEmpty {
            let row = min(max(previousRow, 0), visible.count - 1)
            table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false)
        }
    }

    private func buildPanelIfNeeded() {
        guard panel == nil else { return }
        let size = NSSize(width: 520, height: 440)
        let panel = GlobalPickerPanel(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.delegate = self
        panel.onCommandKey = { [weak self] key in self?.handleCommandKey(key) ?? false }
        panel.onChipKey = { [weak self] keyCode, mask in self?.handleChipKey(keyCode: keyCode, modifierMask: mask) ?? false }

        let effect = NSVisualEffectView(frame: NSRect(origin: .zero, size: size))
        effect.material = .hudWindow
        effect.blendingMode = .behindWindow
        effect.state = .active
        effect.wantsLayer = true
        effect.layer?.cornerRadius = 16
        effect.layer?.masksToBounds = true

        appIcon.image = NSApp.applicationIconImage
        appIcon.imageScaling = .scaleProportionallyUpOrDown
        effect.addSubview(appIcon)
        brand.font = .systemFont(ofSize: 11, weight: .semibold)
        brand.textColor = .labelColor
        effect.addSubview(brand)
        titleLabel.font = .systemFont(ofSize: 11, weight: .semibold)
        titleLabel.textColor = .secondaryLabelColor
        effect.addSubview(titleLabel)

        search.delegate = self
        search.font = .systemFont(ofSize: 15)
        effect.addSubview(search)

        chipControl.segmentStyle = .rounded
        chipControl.controlSize = .small
        chipControl.trackingMode = .selectOne
        chipControl.target = self
        chipControl.action = #selector(chipChanged)
        effect.addSubview(chipControl)

        table.addTableColumn(column)
        table.headerView = nil
        table.rowHeight = 34
        table.backgroundColor = .clear
        table.dataSource = self
        table.delegate = self
        table.target = self
        table.doubleAction = #selector(activateSelection)
        scroll.documentView = table
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        effect.addSubview(scroll)

        footer.font = .systemFont(ofSize: 11)
        footer.textColor = .secondaryLabelColor
        effect.addSubview(footer)

        panel.contentView = effect
        self.panel = panel
        layoutPanel()
    }

    /// Sizes the panel for the current style and row count (keeping its top edge) and places every view.
    private func layoutPanel() {
        guard let panel else { return }
        let height = CGFloat(globalPickerPanelHeight(style: content.style, rowCount: visible.count))
        let size = NSSize(width: panelWidth, height: height)
        if panel.frame.size != size {
            var frame = panel.frame
            frame.origin.y = frame.maxY - size.height
            frame.size = size
            panel.setFrame(frame, display: true)
        }
        panel.contentView?.frame = NSRect(origin: .zero, size: size)
        appIcon.frame = NSRect(x: 18, y: size.height - 24, width: 16, height: 16)
        brand.frame = NSRect(x: 40, y: size.height - 25, width: 76, height: 18)
        titleLabel.frame = NSRect(x: 116, y: size.height - 25, width: size.width - 134, height: 18)
        let searchHeight: CGFloat = 50
        let searchTop = size.height - 28
        search.frame = NSRect(x: 14, y: searchTop - searchHeight - 4, width: size.width - 28, height: searchHeight)
        let chipsY = search.frame.minY - 6 - 24
        chipControl.frame = NSRect(x: 14, y: chipsY, width: size.width - 28, height: 24)
        let scrollBottom: CGFloat = isLauncher ? 26 : 30
        scroll.frame = NSRect(x: 8, y: scrollBottom, width: size.width - 16, height: chipsY - (isLauncher ? 6 : 8) - scrollBottom)
        column.width = size.width - 28
        footer.frame = NSRect(x: 18, y: isLauncher ? 5 : 8, width: size.width - 36, height: 16)
    }

    private func applyFilter() {
        visible = globalPickerFilter(content.items, query: search.stringValue, chip: selectedChip, ranked: isLauncher)
        updateChrome()
        if isLauncher && selectedChip == "all" {
            visible = globalQuickResults(query: search.stringValue, random: secureRandomBytes, switches: content.quickResults) + visible
        }
        // Reload before resizing: resizing lays the table out, and a table still holding the old row count
        // would ask for rows the shorter list no longer has.
        table.reloadData()
        layoutPanel()
        if !visible.isEmpty { table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false) }
    }

    private var readOnlySelected: Bool { content.readOnlyChips.contains(selectedChip) }
    /// Images cannot be pinned, so Command-P does nothing on an image row.
    private var selectedRowCanPin: Bool {
        visible.indices.contains(table.selectedRow) && globalPickerCanPin(kind: visible[table.selectedRow].kind)
    }

    /// The search hint and key hints follow the selected tab: a read-only tab (Dictation) has no pin or delete.
    private func updateChrome() {
        guard !isLauncher else { return }
        search.placeholderString = selectedChip == "dictation" ? "Search dictation" : content.placeholder
        footer.stringValue = readOnlySelected
            ? "↵ paste   ⌘1–9 paste row   ⇥ filter   esc close"
            : "↵ paste   ⌘1–9 paste row   ⇥ filter   ⌘P pin   ⌘⌫ delete   esc close"
    }

    /// Chip bound to this key press: switch the filter and report it handled.
    private func handleChipKey(keyCode: Int, modifierMask: Int) -> Bool {
        guard let index = globalPickerChipIndex(forKeyCode: keyCode, modifierMask: modifierMask, chips: content.chips) else { return false }
        chipControl.selectedSegment = index
        applyFilter()
        return true
    }

    @objc private func chipChanged() {
        applyFilter()
    }

    @objc private func activateSelection() {
        deliver(action: 0, hide: true)
    }

    private func handleCommandKey(_ key: String) -> Bool {
        switch key {
        case "pin": if !readOnlySelected && selectedRowCanPin { deliver(action: 2, hide: false) }
        case "delete": if !readOnlySelected { deliver(action: 3, hide: false) }
        default:
            guard key.hasPrefix("quick:"),
                  let row = globalPickerQuickRow(forKey: String(key.dropFirst("quick:".count)), count: visible.count) else { return false }
            table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false)
            deliver(action: 0, hide: true)
        }
        return true
    }

    /// A sum, UUID or password row is handled here and never leaves this process: Enter pastes it into the app
    /// the panel opened over (the previous clipboard comes back afterwards), Shift+Enter only copies it.
    private func deliverQuickResult(_ item: GlobalPickerItem, copyOnly: Bool) {
        let value = item.title
        let target = targetPID
        hide()
        if copyOnly {
            let pasteboard = NSPasteboard.general
            pasteboard.clearContents()
            // Marked transient so clipboard managers (including ours) do not keep a generated secret.
            let transient = NSPasteboard.PasteboardType("org.nspasteboard.TransientType")
            pasteboard.declareTypes([.string, transient], owner: nil)
            pasteboard.setString(value, forType: .string)
            pasteboard.setData(Data(), forType: transient)
            OfficeKitPasteboardWatcher.shared.markOwnWrite()
        } else {
            DispatchQueue.main.async { _ = pasteIntoTarget(kind: 0, payload: Data(value.utf8), targetPID: target, restoreAfter: true) }
        }
    }

    private func deliver(action: Int32, hide shouldHide: Bool) {
        let row = table.selectedRow
        guard visible.indices.contains(row) else { return }
        if visible[row].kind == "quick" {
            deliverQuickResult(visible[row], copyOnly: action == 1)
            return
        }
        let identifier = Array(visible[row].id.utf8)
        if shouldHide { hide() }
        identifier.withUnsafeBufferPointer { buffer in
            callback?(buffer.baseAddress, UInt64(buffer.count), action)
        }
    }

    // MARK: Search field

    func controlTextDidChange(_ notification: Notification) {
        applyFilter()
    }

    func control(_ control: NSControl, textView: NSTextView, doCommandBy selector: Selector) -> Bool {
        switch selector {
        case #selector(NSResponder.moveUp(_:)), #selector(NSResponder.moveDown(_:)):
            let delta = selector == #selector(NSResponder.moveUp(_:)) ? -1 : 1
            let next = globalPickerMoveSelection(current: table.selectedRow, delta: delta, count: visible.count)
            if visible.indices.contains(next) {
                table.selectRowIndexes(IndexSet(integer: next), byExtendingSelection: false)
                table.scrollRowToVisible(next)
            }
            return true
        case #selector(NSResponder.insertNewline(_:)):
            let plain = NSApp.currentEvent?.modifierFlags.contains(.shift) == true
            deliver(action: plain ? 1 : 0, hide: true)
            return true
        case #selector(NSResponder.insertTab(_:)), #selector(NSResponder.insertBacktab(_:)):
            guard !content.chips.isEmpty else { return true }
            let backwards = selector == #selector(NSResponder.insertBacktab(_:))
            chipControl.selectedSegment = globalPickerNextChip(current: max(chipControl.selectedSegment, 0), count: content.chips.count, backwards: backwards)
            applyFilter()
            return true
        case #selector(NSResponder.moveLeft(_:)), #selector(NSResponder.moveRight(_:)):
            // With nothing typed there is no caret to move, so the arrows step through the filter chips.
            guard search.stringValue.isEmpty, !content.chips.isEmpty else { return false }
            let backwards = selector == #selector(NSResponder.moveLeft(_:))
            chipControl.selectedSegment = globalPickerNextChip(current: max(chipControl.selectedSegment, 0), count: content.chips.count, backwards: backwards)
            applyFilter()
            return true
        case #selector(NSResponder.cancelOperation(_:)):
            hide()
            return true
        default:
            return false
        }
    }

    // MARK: Table

    func numberOfRows(in tableView: NSTableView) -> Int { visible.count }

    /// Rounded colored square with a symbol, used for OfficeKit tools and snippets.
    private func glyphIcon(_ name: String) -> NSImage {
        if let cached = iconCache["glyph:\(name)"] { return cached }
        let (symbol, color): (String, NSColor)
        switch name {
        case "snippet": (symbol, color) = ("text.quote", .systemTeal)
        case "quick-calc": (symbol, color) = ("equal", .systemGreen)
        case "quick-uuid": (symbol, color) = ("number", .systemGreen)
        case "quick-password": (symbol, color) = ("key.fill", .systemGreen)
        case "command-open-trash": (symbol, color) = ("trash", .systemGray)
        case "command-empty-trash": (symbol, color) = ("trash.fill", .systemRed)
        default: (symbol, color) = ("wrench.and.screwdriver.fill", .systemIndigo)
        }
        let image = squareIcon(symbol: symbol, color: color)
        iconCache["glyph:\(name)"] = image
        return image
    }

    /// OfficeKit tool row icon: the tool's own symbol on a softened square in its category colour.
    private func toolIcon(_ icon: String) -> NSImage {
        if let cached = iconCache["tool:\(icon)"] { return cached }
        let glyph = globalToolGlyph(fromIcon: icon)
        let base: NSColor
        switch glyph.tint {
        case "red": base = .systemRed
        case "orange": base = .systemOrange
        case "green": base = .systemGreen
        case "blue": base = .systemBlue
        case "purple": base = .systemPurple
        case "pink": base = .systemPink
        case "yellow": base = .systemYellow
        case "teal": base = .systemTeal
        case "gray": base = .systemGray
        default: base = .systemIndigo
        }
        // Less intense than the raw system colours: lower saturation, slightly darker.
        var hue: CGFloat = 0, saturation: CGFloat = 0, brightness: CGFloat = 0, alpha: CGFloat = 0
        (base.usingColorSpace(.deviceRGB) ?? base).getHue(&hue, saturation: &saturation, brightness: &brightness, alpha: &alpha)
        let soft = NSColor(hue: hue, saturation: saturation * 0.62, brightness: brightness * 0.86, alpha: 1)
        var symbol = glyph.symbol
        if NSImage(systemSymbolName: symbol, accessibilityDescription: nil) == nil { symbol = "wrench.and.screwdriver.fill" }
        let image = squareIcon(symbol: symbol, color: soft)
        iconCache["tool:\(icon)"] = image
        return image
    }

    private func squareIcon(symbol: String, color: NSColor) -> NSImage {
        NSImage(size: NSSize(width: 30, height: 30), flipped: false) { rect in
            color.setFill()
            NSBezierPath(roundedRect: rect, xRadius: 7, yRadius: 7).fill()
            if let glyph = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)?
                .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 14, weight: .semibold)) {
                let tinted = glyph.copy() as! NSImage
                tinted.lockFocus()
                NSColor.white.set()
                NSRect(origin: .zero, size: tinted.size).fill(using: .sourceAtop)
                tinted.unlockFocus()
                tinted.draw(in: NSRect(x: (rect.width - tinted.size.width) / 2, y: (rect.height - tinted.size.height) / 2,
                                       width: tinted.size.width, height: tinted.size.height))
            }
            return true
        }
    }

    private func icon(for item: GlobalPickerItem) -> NSImage {
        if let path = globalPickerApplicationPath(fromIcon: item.icon) {
            if let cached = iconCache[path] { return cached }
            let image = NSWorkspace.shared.icon(forFile: path)
            image.size = NSSize(width: 30, height: 30)
            iconCache[path] = image
            return image
        }
        if item.kind == "tool" { return toolIcon(item.icon) }
        return glyphIcon(item.kind == "quick" || item.kind == "command" || item.icon == "snippet" ? item.icon : "tool")
    }

    private static let kindLabels = ["app": "Application", "command": "Command", "tool": "OfficeKit tool", "snippet": "Snippet"]

    /// Launcher row: icon, name over a small second line, kind label and the Command-number badge.
    private func launcherCell(for item: GlobalPickerItem, row: Int) -> NSView {
        let cell = NSView()
        let iconView = NSImageView()
        iconView.image = icon(for: item)
        iconView.imageScaling = .scaleProportionallyUpOrDown
        let name = NSTextField(labelWithString: item.title)
        name.font = .systemFont(ofSize: 15)
        name.lineBreakMode = .byTruncatingTail
        let detail = NSTextField(labelWithString: item.subtitle)
        detail.font = .systemFont(ofSize: 11)
        detail.textColor = .secondaryLabelColor
        detail.lineBreakMode = .byTruncatingMiddle
        let texts = NSStackView(views: [name, detail])
        texts.orientation = .vertical
        texts.alignment = .leading
        texts.spacing = 1
        let kind = NSTextField(labelWithString: item.kind == "quick" ? item.badge : (Self.kindLabels[item.kind] ?? ""))
        kind.font = .systemFont(ofSize: 12)
        kind.textColor = .secondaryLabelColor
        kind.alignment = .right
        let badge = NSTextField(labelWithString: row < 9 ? "⌘\(row + 1)" : "")
        badge.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
        badge.textColor = .secondaryLabelColor
        badge.alignment = .right
        for view in [iconView, texts, kind, badge] { view.translatesAutoresizingMaskIntoConstraints = false; cell.addSubview(view) }
        texts.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        kind.setContentCompressionResistancePriority(.required, for: .horizontal)
        NSLayoutConstraint.activate([
            iconView.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 8),
            iconView.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
            iconView.widthAnchor.constraint(equalToConstant: 30),
            iconView.heightAnchor.constraint(equalToConstant: 30),
            texts.leadingAnchor.constraint(equalTo: iconView.trailingAnchor, constant: 12),
            texts.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
            texts.trailingAnchor.constraint(lessThanOrEqualTo: kind.leadingAnchor, constant: -10),
            badge.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -8),
            badge.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
            badge.widthAnchor.constraint(equalToConstant: 30),
            kind.trailingAnchor.constraint(equalTo: badge.leadingAnchor, constant: -10),
            kind.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
        ])
        return cell
    }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        guard visible.indices.contains(row) else { return nil }
        let item = visible[row]
        if isLauncher { return launcherCell(for: item, row: row) }
        var parts = [item.title]
        if !item.subtitle.isEmpty { parts.append(item.subtitle) }
        if !item.badge.isEmpty { parts.append(item.badge) }
        let label = NSTextField(labelWithString: parts.joined(separator: "   "))
        label.lineBreakMode = .byTruncatingTail
        label.font = .systemFont(ofSize: 13)
        let canPin = !readOnlySelected && globalPickerCanPin(kind: item.kind)
        guard row < 9 || canPin else { return label }
        let cell = NSView()
        var views: [NSView] = [label]
        var constraints: [NSLayoutConstraint] = [label.centerYAnchor.constraint(equalTo: cell.centerYAnchor)]
        // Pin toggle at the left edge of text and link rows: faint, bright on the selected row, amber and filled when pinned.
        if canPin {
            let pin = NSButton()
            pin.isBordered = false
            pin.bezelStyle = .regularSquare
            pin.imagePosition = .imageOnly
            pin.setButtonType(.momentaryChange)
            pin.image = NSImage(systemSymbolName: item.pinned ? "pin.fill" : "pin", accessibilityDescription: item.pinned ? "Unpin" : "Pin")
            pin.contentTintColor = item.pinned ? .systemOrange : .labelColor
            pin.alphaValue = item.pinned || row == table.selectedRow ? 1 : 0.35
            pin.toolTip = item.pinned ? "Unpin" : "Pin"
            pin.tag = row
            pin.target = self
            pin.action = #selector(pinRowClicked(_:))
            views.append(pin)
            constraints += [
                pin.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 2),
                pin.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
                pin.widthAnchor.constraint(equalToConstant: 22),
                pin.heightAnchor.constraint(equalToConstant: 22),
                label.leadingAnchor.constraint(equalTo: pin.trailingAnchor, constant: 6),
            ]
        } else {
            constraints.append(label.leadingAnchor.constraint(equalTo: cell.leadingAnchor))
        }
        // The first nine rows paste with Command-1 to Command-9, shown at the right edge.
        if row < 9 {
            let badge = NSTextField(labelWithString: "⌘\(row + 1)")
            badge.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
            badge.textColor = .secondaryLabelColor
            badge.alignment = .right
            views.append(badge)
            constraints += [
                badge.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -6),
                badge.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
                badge.widthAnchor.constraint(equalToConstant: 30),
                label.trailingAnchor.constraint(equalTo: badge.leadingAnchor, constant: -8),
            ]
        } else {
            constraints.append(label.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -6))
        }
        for view in views { view.translatesAutoresizingMaskIntoConstraints = false; cell.addSubview(view) }
        label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        NSLayoutConstraint.activate(constraints)
        return cell
    }

    /// Keep the pin brightness in step with the selection: bright on the selected row, faint elsewhere unless pinned.
    func tableViewSelectionDidChange(_ notification: Notification) {
        for row in 0..<visible.count {
            guard let cell = table.view(atColumn: 0, row: row, makeIfNecessary: false),
                  let pin = cell.subviews.compactMap({ $0 as? NSButton }).first else { continue }
            pin.alphaValue = visible[row].pinned || row == table.selectedRow ? 1 : 0.35
        }
    }

    /// Row pin button: select that row, then toggle its pin without closing the panel.
    @objc private func pinRowClicked(_ sender: NSButton) {
        guard visible.indices.contains(sender.tag), globalPickerCanPin(kind: visible[sender.tag].kind) else { return }
        table.selectRowIndexes(IndexSet(integer: sender.tag), byExtendingSelection: false)
        deliver(action: 2, hide: false)
    }

    func windowDidResignKey(_ notification: Notification) {
        hide()
    }
}

@_cdecl("officekit_global_panel_set_callback")
public func officekitGlobalPanelSetCallback(_ callback: @escaping @convention(c) (UnsafePointer<UInt8>?, UInt64, Int32) -> Void) {
    GlobalPickerController.shared.callback = callback
}

/// 0 shown, 4 invalid content.
@_cdecl("officekit_global_panel_show")
public func officekitGlobalPanelShow(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64) -> Int32 {
    guard let bytes, length > 0, length <= 4 * 1024 * 1024,
          let content = globalPickerContent(fromJSON: Data(bytes: bytes, count: Int(length))) else { return 4 }
    onMainSync { GlobalPickerController.shared.show(content) }
    return 0
}

/// Refreshes the visible panel's rows without resetting the search or selection. 4 invalid content.
@_cdecl("officekit_global_panel_update")
public func officekitGlobalPanelUpdate(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64) -> Int32 {
    guard let bytes, length > 0, length <= 4 * 1024 * 1024,
          let content = globalPickerContent(fromJSON: Data(bytes: bytes, count: Int(length))) else { return 4 }
    onMainSync { GlobalPickerController.shared.update(content) }
    return 0
}

@_cdecl("officekit_global_panel_hide")
public func officekitGlobalPanelHide() {
    onMainSync { GlobalPickerController.shared.hide() }
}

/// Process id of the app that was frontmost when the panel opened, or 0.
@_cdecl("officekit_global_panel_target_pid")
public func officekitGlobalPanelTargetPid() -> Int32 {
    onMainSync { Int32(GlobalPickerController.shared.targetPID) }
}
