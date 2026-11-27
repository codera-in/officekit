import AVFAudio
import AVFoundation
import AppKit
import ApplicationServices
import CoreGraphics
import CoreMedia
import CoreAudio
import Foundation
import OSLog
import ScreenCaptureKit

final class DictationCaptureLifecycleLock {
    private let lock = NSRecursiveLock()

    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try operation()
    }
}

struct DictationCaptureStartGate {
    private(set) var isStarting = false

    mutating func begin() -> Bool {
        guard !isStarting else { return false }
        isStarting = true
        return true
    }

    mutating func finish() {
        isStarting = false
    }
}

func dictationCaptureHasActiveOwner(coachActive: Bool, dictationActive: Bool) -> Bool {
    coachActive || dictationActive
}

/// Speech Coach joins a dictation that is already recording; it never opens the microphone itself.
func dictationCoachCanAttach(engineRunning: Bool, dictationActive: Bool, coachActive: Bool) -> Bool {
    engineRunning && dictationActive && !coachActive
}

/// When a dictation stops, coaching that only joined it leaves too; a Listen In session keeps running.
func dictationCoachOwnershipAfterDictationStops(coachActive: Bool, attachedByDictation: Bool) -> (
    coachActive: Bool, attachedByDictation: Bool, releasedAttachedCoach: Bool
) {
    attachedByDictation ? (false, false, true) : (coachActive, false, false)
}

/// A button that shows the pointing hand while the mouse is over it, so it reads as clickable.
/// Lives here (not in macos-drawers.swift) because the hotkey unit-test build compiles this file alone.
final class PointerButton: NSButton {
    override func resetCursorRects() {
        super.resetCursorRects()
        addCursorRect(bounds, cursor: .pointingHand)
    }
}

private let dictationSampleRate = 16_000.0
private let dictationMaxDurationSeconds = 300.0
private let dictationMaxSamples = Int(dictationSampleRate * dictationMaxDurationSeconds)
private let dictationMaxPasteBytes = 262_144
private let dictationMaxClipboardSnapshotBytes = 16 * 1024 * 1024
private let dictationDiagnosticLogger = Logger(subsystem: "app.officekit.desktop", category: "dictation-shortcut")

func dictationMicrophonePermissionCode(for permission: AVAuthorizationStatus) -> Int32 {
    switch permission {
    case .authorized:
        return 0
    case .notDetermined:
        return 1
    case .denied:
        return 2
    case .restricted:
        return 3
    @unknown default:
        return 3
    }
}

func dictationShouldRequestMicrophoneAccess(for permission: AVAuthorizationStatus) -> Bool {
    permission == .notDetermined
}

func dictationAudioInputDeviceIsUsable(status: OSStatus, device: AudioDeviceID) -> Bool {
    status == noErr && device != kAudioObjectUnknown
}

func dictationCoachWindowShouldDrain(
    sampleCount: Int,
    minimum: Int,
    maximum: Int,
    capacity: Int,
    coachActive: Bool,
    dictationActive: Bool
) -> Bool {
    coachActive && !dictationActive && sampleCount >= minimum && sampleCount <= maximum && sampleCount <= capacity
}

func dictationCoachShouldKeepDictationGeneration(active: Bool, dictationVisible: Bool, cancelled: Bool) -> Bool {
    active && dictationVisible && !cancelled
}

func dictationCoachZoneGeometry(
    pace: Int,
    targetMin: Int,
    targetMax: Int,
    trackWidth: Double
) -> (lowWidth: Double, targetWidth: Double, highWidth: Double, markerX: Double)? {
    guard (60...240).contains(targetMin), (60...240).contains(targetMax),
          targetMin < targetMax, trackWidth.isFinite, trackWidth > 0 else { return nil }
    let low = Double(targetMin - 60) / 180
    let target = Double(targetMax - targetMin) / 180
    return (
        trackWidth * low,
        trackWidth * target,
        trackWidth * (1 - low - target),
        trackWidth * Double(max(60, min(240, pace)) - 60) / 180
    )
}

let dictationCoachMinimumPaceSeconds = 10

func dictationCoachMeasuringText(speechSeconds: Double) -> String? {
    let measured = speechSeconds.isFinite ? max(0, speechSeconds) : 0
    guard measured < Double(dictationCoachMinimumPaceSeconds) else { return nil }
    return "Measuring your pace · \(Int(measured)) of \(dictationCoachMinimumPaceSeconds) s of speech"
}

func dictationCoachLevelBarHeights(rms: Float) -> [Int] {
    let level = rms.isFinite ? min(1, max(0, sqrt(rms) * 4.5)) : 0
    return [0.6, 0.85, 1, 0.75, 0.5].map { 2 + Int((12 * level * Float($0)).rounded()) }
}

func dictationOverlayChrome(coachEnabled: Bool, dictationVisible: Bool) -> (
    levelBars: Bool, closeButton: Bool, legacyMeter: Bool, legacyEscHint: Bool, legacyMicrophone: Bool, cancelInCorner: Bool
) {
    let coachOnly = coachEnabled && !dictationVisible
    let both = coachEnabled && dictationVisible
    // Dictating with coaching on: the pace bar and WPM take the bottom rows, so the meter and microphone go and Stop + Esc move to the top-right corner.
    return (coachOnly, coachOnly, !coachOnly && !both, !coachOnly, !coachOnly && !both, both)
}

/// Where the dictation Stop button and Esc hint sit. In the corner they stay clear of the coach rows below the title.
func dictationCancelLayout(inCorner: Bool) -> (cancel: CGRect, escHint: CGRect, titleWidth: CGFloat) {
    inCorner
        ? (CGRect(x: 326, y: 84, width: 26, height: 26), CGRect(x: 284, y: 88, width: 36, height: 18), 262)
        : (CGRect(x: 8, y: 6, width: 40, height: 40), CGRect(x: 56, y: 14, width: 40, height: 22), 328)
}

/// The five level bars sit next to the title; they step left while the close button is shown.
func dictationCoachLevelBarsOriginX(closeButtonVisible: Bool) -> CGFloat {
    closeButtonVisible ? 290 : 313
}

private func dictationHasDefaultAudioInput() -> Bool {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDefaultInputDevice,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    var device = AudioDeviceID(kAudioObjectUnknown)
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    let status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &device)
    return dictationAudioInputDeviceIsUsable(status: status, device: device)
}

private func currentDictationMicrophonePermissionCode() -> Int32 {
    dictationMicrophonePermissionCode(for: AVCaptureDevice.authorizationStatus(for: .audio))
}

private final class OfficeKitMicrophonePermissionProbe {
    static let shared = OfficeKitMicrophonePermissionProbe()

    func request() {
        let permission = AVCaptureDevice.authorizationStatus(for: .audio)
        guard dictationShouldRequestMicrophoneAccess(for: permission) else { return }

        // Request TCC directly. Requiring a default AVCaptureDevice first
        // silently skipped the permission prompt on Macs without one.
        let requestAccess = {
            AVCaptureDevice.requestAccess(for: .audio) { _ in }
        }
        if Thread.isMainThread {
            requestAccess()
        } else {
            DispatchQueue.main.async(execute: requestAccess)
        }
    }
}

struct DictationModifierKeyState {
    private(set) var isPressed = false

    mutating func update(eventKeyCode: UInt16, selectedKeyCode: UInt16, keyIsDown: Bool) {
        guard eventKeyCode == selectedKeyCode else { return }
        isPressed = keyIsDown
    }

    mutating func reset() {
        isPressed = false
    }
}

func dictationModifierKeyIsDown(keyCode: UInt16, flags: UInt) -> Bool {
    // Device-specific masks from IOKit/hidsystem/IOLLEvent.h preserve left/right identity.
    let mask: UInt
    switch keyCode {
    case 59: mask = 0x00000001
    case 56: mask = 0x00000002
    case 60: mask = 0x00000004
    case 55: mask = 0x00000008
    case 54: mask = 0x00000010
    case 58: mask = 0x00000020
    case 61: mask = 0x00000040
    case 62: mask = 0x00002000
    case 63: mask = NSEvent.ModifierFlags.function.rawValue
    default: return false
    }
    return flags & mask != 0
}

func dictationPasteTargetMatches(expectedPID: pid_t?, currentPID: pid_t?) -> Bool {
    expectedPID == nil || expectedPID == currentPID
}

private let dictationNonTextRoles: Set<String> = [
    "AXButton", "AXStaticText", "AXImage", "AXList", "AXTable", "AXOutline", "AXRow", "AXCell",
    "AXColumn", "AXToolbar", "AXMenuItem", "AXMenuBarItem", "AXRadioButton", "AXCheckBox",
    "AXPopUpButton", "AXSlider", "AXTabGroup", "AXBrowser", "AXDockItem",
]

/// macOS plays the alert beep when Cmd+V reaches a control that cannot take a paste.
/// Only a focused control with a known non-text role skips the keystroke; unknown or
/// unreadable focus (Electron, custom editors) still pastes.
func dictationFocusClearlyRejectsPaste() -> Bool {
    let system = AXUIElementCreateSystemWide()
    var focused: CFTypeRef?
    guard AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute as CFString, &focused) == .success,
          let focused, CFGetTypeID(focused) == AXUIElementGetTypeID() else { return false }
    let element = focused as! AXUIElement
    var settable: DarwinBoolean = false
    if AXUIElementIsAttributeSettable(element, kAXValueAttribute as CFString, &settable) == .success, settable.boolValue {
        return false
    }
    var role: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &role) == .success,
          let role = role as? String else { return false }
    return dictationNonTextRoles.contains(role)
}

final class OfficeKitTranscriptPaster {
    static let shared = OfficeKitTranscriptPaster()

    func paste(_ text: String, expectedPID: pid_t? = nil) -> Int32 {
        guard AXIsProcessTrusted() else { return 1 }
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              text.utf8.count <= dictationMaxPasteBytes else { return 2 }

        let pasteboard = NSPasteboard.general
        guard let previousItems = snapshot(pasteboard),
              let source = CGEventSource(stateID: .hidSystemState),
              let keyDown = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: true),
              let keyUp = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: false) else {
            return 3
        }

        pasteboard.clearContents()
        guard pasteboard.writeObjects([text as NSString]) else {
            restore(previousItems, to: pasteboard)
            return 3
        }
        officekitGlobalMarkOwnPasteboardWrite()
        // Synthetic key events cannot confirm when the target reads the clipboard.
        // Retain the complete transcript instead of racing a 750 ms restoration.
        guard dictationPasteTargetMatches(expectedPID: expectedPID,
            currentPID: NSWorkspace.shared.frontmostApplication?.processIdentifier) else { return 4 }
        // The transcript stays on the clipboard; no keystroke means no system beep.
        guard !dictationFocusClearlyRejectsPaste() else { return 4 }
        keyDown.flags = .maskCommand
        keyUp.flags = .maskCommand
        keyDown.post(tap: .cghidEventTap)
        keyUp.post(tap: .cghidEventTap)

        return 0
    }

    func snapshot(_ pasteboard: NSPasteboard) -> [[(NSPasteboard.PasteboardType, Data)]]? {
        var totalBytes = 0
        var items: [[(NSPasteboard.PasteboardType, Data)]] = []
        for item in pasteboard.pasteboardItems ?? [] {
            var representations: [(NSPasteboard.PasteboardType, Data)] = []
            for type in item.types {
                guard let data = item.data(forType: type) else { return nil }
                let (updatedTotal, overflow) = totalBytes.addingReportingOverflow(data.count)
                guard !overflow, updatedTotal <= dictationMaxClipboardSnapshotBytes else {
                    return nil
                }
                totalBytes = updatedTotal
                representations.append((type, data))
            }
            items.append(representations)
        }
        return items
    }

    func restore(_ items: [[(NSPasteboard.PasteboardType, Data)]], to pasteboard: NSPasteboard) {
        pasteboard.clearContents()
        let restored = items.map { values -> NSPasteboardItem in
            let item = NSPasteboardItem()
            for (type, data) in values {
                item.setData(data, forType: type)
            }
            return item
        }
        if !restored.isEmpty {
            _ = pasteboard.writeObjects(restored)
        }
    }
}

private final class DictationOverlayPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

func screenshotShortcutMatches(keyCode: UInt16, flags: NSEvent.ModifierFlags, isRepeat: Bool, choice: Int32) -> Bool {
    guard choice == 1 || choice == 2, !isRepeat else { return false }
    let expected: NSEvent.ModifierFlags = choice == 1 ? [.command, .shift] : [.control, .shift]
    return keyCode == (choice == 1 ? 22 : 1) && flags.intersection([.command, .shift, .control, .option]) == expected
}

private final class OfficeKitScreenshotShortcut {
    static let shared = OfficeKitScreenshotShortcut()
    private var global: Any?
    private var local: Any?

    func configure(_ choice: Int32, callback: @escaping @convention(c) () -> Void) -> Int32 {
        let operation = { () -> Int32 in
            if let monitor = self.global { NSEvent.removeMonitor(monitor) }
            if let monitor = self.local { NSEvent.removeMonitor(monitor) }
            self.global = nil; self.local = nil
            if choice == 0 { return 0 }
            guard choice == 1 || choice == 2 else { return 2 }
            guard AXIsProcessTrusted() else { return 1 }
            let observe = { (event: NSEvent) -> Bool in
                guard screenshotShortcutMatches(keyCode: event.keyCode, flags: event.modifierFlags, isRepeat: event.isARepeat, choice: choice) else { return false }
                callback()
                return true
            }
            self.global = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { event in _ = observe(event) }
            self.local = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in observe(event) ? nil : event }
            return self.global != nil && self.local != nil ? 0 : 2
        }
        return Thread.isMainThread ? operation() : DispatchQueue.main.sync(execute: operation)
    }
}

@_cdecl("officekit_screenshot_shortcut_configure")
public func officekitScreenshotShortcutConfigure(_ choice: Int32, _ callback: @escaping @convention(c) () -> Void) -> Int32 {
    OfficeKitScreenshotShortcut.shared.configure(choice, callback: callback)
}

private final class OfficeKitDictationOverlay: NSObject {
    static let shared = OfficeKitDictationOverlay()
    private let lock = NSLock()
    private var generation: UInt64 = 0
    private var active = false
    private var cancelled = false
    private var dictationVisible = false
    private var targetPID: pid_t?
    private var panel: DictationOverlayPanel?
    private var label: NSTextField?
    private var coachLabel: NSTextField?
    private var coachPitchLabel: NSTextField?
    private var coachPaceLabel: NSTextField?
    private var coachZoneTrack: NSView?
    private var coachZoneLow: NSView?
    private var coachZoneTarget: NSView?
    private var coachZoneHigh: NSView?
    private var coachZoneMarker: NSView?
    private var coachPaceValue: NSTextField?
    private var meter: NSTextField?
    private var escHint: NSTextField?
    private var microphoneIcon: NSTextField?
    private var coachLevelBars: [NSView] = []
    private var coachHasPaceReading = false
    private var cancelButton: PointerButton?
    private var coachCloseButton: PointerButton?
    /// Set by the host: ends the Listen In session when the panel's close button is pressed.
    var coachCloseCallback: (@convention(c) () -> Void)?
    private var lastMeterUpdate = Date.distantPast
    private var lastLevelLog = Date.distantPast
    private var coachEnabled = false
    private var overlayVisible = true
    private var placementCode: Int32 = 0

    func configure(placement: Int32, visible: Bool) {
        lock.lock()
        placementCode = min(5, max(0, placement))
        overlayVisible = visible
        let showCoach = visible && coachEnabled && !dictationVisible
        let showDictation = visible && dictationVisible
        let value = generation
        lock.unlock()
        DispatchQueue.main.async {
            if !visible { self.panel?.orderOut(nil) }
            else if showCoach { self.showCoachPanel("Speech Coach · Listening", generation: self.current()) }
            else if showDictation {
                if self.panel == nil { self.show("Listening…", generation: value) }
                else { self.positionPanel(); self.panel?.orderFrontRegardless() }
            }
        }
    }

    func beginCoach() {
        lock.lock()
        let keepDictation = dictationCoachShouldKeepDictationGeneration(
            active: active,
            dictationVisible: dictationVisible,
            cancelled: cancelled
        )
        if !keepDictation {
            generation &+= 1
            active = false
            cancelled = false
            dictationVisible = false
            targetPID = nil
        }
        coachEnabled = true
        let value = generation
        lock.unlock()
        DispatchQueue.main.async { self.coachHasPaceReading = false }
        if !keepDictation {
            showCoachPanel("Speech Coach · Listening", generation: value)
        } else {
            DispatchQueue.main.async {
                guard self.isVisible(value) else { return }
                self.coachLabel?.isHidden = false
                self.coachPitchLabel?.isHidden = false
                self.coachPaceLabel?.isHidden = false
                self.coachZoneTrack?.isHidden = false
                self.coachPaceValue?.isHidden = false
                self.coachLabel?.stringValue = Self.coachIdleText
                self.applyChrome()
                self.positionPanel()
                self.panel?.orderFrontRegardless()
            }
        }
    }

    func endCoach() {
        lock.lock()
        coachEnabled = false
        let shouldHide = !dictationVisible
        if shouldHide { active = false }
        lock.unlock()
        DispatchQueue.main.async {
            self.coachHasPaceReading = false
            self.coachLabel?.isHidden = true
            self.coachPitchLabel?.isHidden = true
            self.coachPaceLabel?.isHidden = true
            self.coachZoneTrack?.isHidden = true
            self.coachPaceValue?.isHidden = true
            self.applyChrome()
            if shouldHide { self.panel?.orderOut(nil) }
        }
    }

    func level(_ rms: Float) {
        lock.lock()
        guard (dictationVisible || coachEnabled) && !cancelled && Date().timeIntervalSince(lastMeterUpdate) > 0.08 else { lock.unlock(); return }
        lastMeterUpdate = Date()
        let value = generation
        lock.unlock()
        // A level number only (never audio), once a second, so a silent meter can be traced.
        if Date().timeIntervalSince(lastLevelLog) > 1 {
            lastLevelLog = Date()
            dictationDiagnosticLogger.notice("Level meter input rms=\(rms, format: .fixed(precision: 4))")
        }
        let bars = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
        let height = min(7, max(0, Int(sqrt(max(0, rms)) * 16)))
        let barHeights = dictationCoachLevelBarHeights(rms: rms)
        DispatchQueue.main.async {
            guard self.isVisible(value) else { return }
            for (bar, barHeight) in zip(self.coachLevelBars, barHeights) {
                bar.frame = NSRect(x: bar.frame.minX, y: 92, width: 3, height: CGFloat(barHeight))
            }
            self.applyChrome()
            self.meter?.stringValue = [max(0, height - 3), max(0, height - 1), height, max(0, height - 2), height, max(0, height - 1), max(0, height - 3)].map { bars[$0] }.joined(separator: " ")
        }
    }

    func begin() -> UInt64 {
        let foregroundPID = Thread.isMainThread
            ? NSWorkspace.shared.frontmostApplication?.processIdentifier
            : DispatchQueue.main.sync { NSWorkspace.shared.frontmostApplication?.processIdentifier }
        lock.lock()
        generation &+= 1
        active = true
        cancelled = false
        dictationVisible = true
        targetPID = foregroundPID
        let value = generation
        lock.unlock()
        show("Listening…", generation: value)
        return value
    }

    func showTranscript(_ text: String, generation value: UInt64) {
        let compact = text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        let display = String(compact.prefix(108)) + (compact.count > 108 ? "…" : "")
        show(display, generation: value)
    }

    func coachCue(_ text: String, generation value: UInt64) {
        guard text.utf8.count <= 512 else { return }
        DispatchQueue.main.async {
            guard self.isVisible(value), self.coachEnabled else { return }
            self.coachLabel?.isHidden = false
            self.coachLabel?.stringValue = text
            DispatchQueue.main.asyncAfter(deadline: .now() + 15) {
                guard self.isVisible(value), self.coachEnabled,
                      self.coachLabel?.stringValue == text else { return }
                self.coachLabel?.stringValue = "Speak naturally · audio stays on this Mac"
            }
        }
    }

    func coachPitchStats(medianHz: UInt16, rangeHz: UInt16, generation value: UInt64) {
        DispatchQueue.main.async {
            guard self.isVisible(value), self.coachEnabled else { return }
            let text = "Pitch median \(medianHz) Hz · variation \(rangeHz) Hz"
            self.coachPitchLabel?.isHidden = false
            self.coachPitchLabel?.stringValue = text
            DispatchQueue.main.asyncAfter(deadline: .now() + 15) {
                guard self.isVisible(value), self.coachEnabled,
                      self.coachPitchLabel?.stringValue == text else { return }
                self.coachPitchLabel?.stringValue = "Pitch variation · descriptive only"
            }
        }
    }

    func coachPace(paceWpm: UInt16, targetMin: UInt16, targetMax: UInt16, generation value: UInt64) {
        DispatchQueue.main.async {
            guard self.isVisible(value), self.coachEnabled,
                  targetMin >= 60, targetMax <= 240, targetMin < targetMax else { return }
            guard let geometry = dictationCoachZoneGeometry(
                pace: Int(paceWpm),
                targetMin: Int(targetMin),
                targetMax: Int(targetMax),
                trackWidth: Double(self.coachZoneTrack?.bounds.width ?? 190)
            ) else { return }
            self.coachZoneLow?.frame = NSRect(x: 0, y: 0, width: geometry.lowWidth, height: 8)
            self.coachZoneTarget?.frame = NSRect(x: geometry.lowWidth, y: 0, width: geometry.targetWidth, height: 8)
            self.coachZoneHigh?.frame = NSRect(x: geometry.lowWidth + geometry.targetWidth, y: 0, width: geometry.highWidth, height: 8)
            self.coachZoneMarker?.frame = NSRect(x: geometry.markerX - 1, y: -4, width: 2, height: 16)
            self.coachZoneMarker?.isHidden = false
            self.coachPaceValue?.stringValue = "\(paceWpm) WPM"
            self.coachHasPaceReading = true
            self.applyChrome()
            DispatchQueue.main.asyncAfter(deadline: .now() + 15) {
                guard self.isVisible(value), self.coachEnabled,
                      self.coachPaceValue?.stringValue == "\(paceWpm) WPM" else { return }
                self.coachZoneMarker?.isHidden = true
                self.coachPaceValue?.stringValue = "— WPM"
                self.coachHasPaceReading = false
                self.applyChrome()
            }
        }
    }

    func current() -> UInt64 {
        lock.lock(); defer { lock.unlock() }
        return generation
    }

    func pasteTarget(_ value: UInt64) -> pid_t? {
        lock.lock(); defer { lock.unlock() }
        return value == generation ? targetPID : nil
    }

    func valid(_ value: UInt64) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return value == generation && active && dictationVisible && !cancelled
    }

    private func isVisible(_ value: UInt64) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return value == generation && (dictationVisible || coachEnabled) && !cancelled
    }

    @objc func closeCoachPanel() {
        coachCloseCallback?()
    }

    @objc func cancel() {
        lock.lock()
        guard active else { lock.unlock(); return }
        let keepCoachVisible = coachEnabled
        cancelled = !keepCoachVisible
        active = false
        dictationVisible = false
        lock.unlock()
        DispatchQueue.main.async {
            if keepCoachVisible { self.showCoachPanel("Speech Coach · Listening", generation: self.current()) }
            else { self.panel?.orderOut(nil) }
        }
    }

    /// A dictation that could not start says why on the overlay itself, then goes away.
    func fail(_ text: String, generation value: UInt64) {
        show("⚠︎ " + text, generation: value)
        DispatchQueue.main.async {
            guard self.isVisible(value) else { return }
            self.cancelButton?.isHidden = true
            self.meter?.isHidden = true
            self.escHint?.isHidden = true
            self.microphoneIcon?.isHidden = true
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) { self.finish(value) }
    }

    func finish(_ value: UInt64) {
        lock.lock()
        guard generation == value else { lock.unlock(); return }
        active = false
        dictationVisible = false
        lock.unlock()
        DispatchQueue.main.async {
            self.lock.lock()
            let shouldHide = self.generation == value && !self.cancelled
            let showCoach = shouldHide && self.coachEnabled
            if showCoach { self.active = false }
            self.lock.unlock()
            if showCoach { self.showCoachPanel("Speech Coach · Listening", generation: value) }
            else if shouldHide { self.panel?.orderOut(nil) }
        }
    }

    func show(_ text: String, generation value: UInt64) {
        DispatchQueue.main.async {
            guard self.isVisible(value) else { return }
            if self.panel == nil {
                let panel = DictationOverlayPanel(
                    contentRect: NSRect(x: 0, y: 0, width: 360, height: 116),
                    styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
                panel.level = .floating
                // The coach HUD is for the speaker only: keep it out of screen shares and recordings.
                panel.sharingType = .none
                panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
                panel.isOpaque = false
                panel.backgroundColor = .clear
                panel.hasShadow = true
                panel.hidesOnDeactivate = false
                let content = NSView(frame: NSRect(x: 0, y: 0, width: 360, height: 116))
                content.wantsLayer = true
                content.layer?.backgroundColor = NSColor(calibratedRed: 0.09, green: 0.09, blue: 0.13, alpha: 0.97).cgColor
                content.layer?.cornerRadius = 16
                let label = NSTextField(labelWithString: "Listening…")
                label.frame = NSRect(x: 16, y: 66, width: 328, height: 42)
                label.textColor = .white
                label.font = .systemFont(ofSize: 14, weight: .medium)
                label.maximumNumberOfLines = 2
                label.cell?.wraps = true
                label.cell?.isScrollable = false
                content.addSubview(label)
                let coachLabel = NSTextField(labelWithString: "")
                coachLabel.frame = NSRect(x: 16, y: 46, width: 328, height: 16)
                coachLabel.textColor = NSColor(calibratedRed: 0.45, green: 0.85, blue: 0.9, alpha: 1)
                coachLabel.font = .systemFont(ofSize: 11, weight: .semibold)
                content.addSubview(coachLabel)
                self.coachLabel = coachLabel
                let coachPitchLabel = NSTextField(labelWithString: "Pitch variation · descriptive only")
                coachPitchLabel.frame = NSRect(x: 16, y: 30, width: 244, height: 14)
                coachPitchLabel.textColor = NSColor(calibratedRed: 0.72, green: 0.76, blue: 0.8, alpha: 1)
                coachPitchLabel.font = .systemFont(ofSize: 10, weight: .medium)
                content.addSubview(coachPitchLabel)
                self.coachPitchLabel = coachPitchLabel
                let coachPaceLabel = NSTextField(labelWithString: "Your pace")
                coachPaceLabel.frame = NSRect(x: 16, y: 13, width: 84, height: 16)
                coachPaceLabel.textColor = .white
                coachPaceLabel.font = .systemFont(ofSize: 10, weight: .medium)
                content.addSubview(coachPaceLabel)
                self.coachPaceLabel = coachPaceLabel
                let track = NSView(frame: NSRect(x: 104, y: 17, width: 190, height: 8))
                track.wantsLayer = true
                track.layer?.cornerRadius = 4
                track.layer?.masksToBounds = true
                content.addSubview(track)
                self.coachZoneTrack = track
                func zoneSegment(color: NSColor) -> NSView {
                    let segment = NSView()
                    segment.wantsLayer = true
                    segment.layer?.backgroundColor = color.cgColor
                    track.addSubview(segment)
                    return segment
                }
                self.coachZoneLow = zoneSegment(color: NSColor(calibratedRed: 0.96, green: 0.62, blue: 0.28, alpha: 1))
                self.coachZoneTarget = zoneSegment(color: NSColor(calibratedRed: 0.22, green: 0.76, blue: 0.56, alpha: 1))
                self.coachZoneHigh = zoneSegment(color: NSColor(calibratedRed: 0.96, green: 0.62, blue: 0.28, alpha: 1))
                self.coachZoneLow?.frame = NSRect(x: 0, y: 0, width: 190 * 50 / 180, height: 8)
                self.coachZoneTarget?.frame = NSRect(x: 190 * 50 / 180, y: 0, width: 190 * 50 / 180, height: 8)
                self.coachZoneHigh?.frame = NSRect(x: 190 * 100 / 180, y: 0, width: 190 * 80 / 180, height: 8)
                let marker = NSView(frame: NSRect(x: 0, y: -4, width: 2, height: 16))
                marker.wantsLayer = true
                marker.layer?.backgroundColor = NSColor.white.cgColor
                marker.layer?.cornerRadius = 1
                marker.layer?.shadowColor = NSColor.white.cgColor
                marker.layer?.shadowRadius = 4
                marker.layer?.shadowOpacity = 0.9
                marker.isHidden = true
                track.addSubview(marker)
                self.coachZoneMarker = marker
                let paceValue = NSTextField(labelWithString: "— WPM")
                paceValue.frame = NSRect(x: 298, y: 13, width: 52, height: 16)
                paceValue.alignment = .right
                paceValue.textColor = .white
                paceValue.font = .monospacedDigitSystemFont(ofSize: 9, weight: .semibold)
                content.addSubview(paceValue)
                self.coachPaceValue = paceValue
                let cancel = PointerButton(title: "■", target: self, action: #selector(self.cancel))
                cancel.frame = NSRect(x: 8, y: 6, width: 40, height: 40)
                cancel.bezelStyle = .circular
                cancel.contentTintColor = .systemPink
                cancel.setAccessibilityLabel("Cancel dictation")
                content.addSubview(cancel)
                self.cancelButton = cancel
                let meter = NSTextField(labelWithString: "▁ ▁ ▁ ▁ ▁ ▁ ▁")
                meter.frame = NSRect(x: 105, y: 16, width: 188, height: 20)
                meter.textColor = NSColor(calibratedRed: 0.72, green: 0.66, blue: 1, alpha: 1)
                content.addSubview(meter)
                self.meter = meter
                let hint = NSTextField(labelWithString: "Esc")
                hint.frame = NSRect(x: 56, y: 14, width: 40, height: 22)
                hint.textColor = .lightGray
                hint.font = .systemFont(ofSize: 12)
                content.addSubview(hint)
                self.escHint = hint
                let microphone = NSTextField(labelWithString: "🎙")
                microphone.frame = NSRect(x: 326, y: 14, width: 22, height: 22)
                content.addSubview(microphone)
                self.microphoneIcon = microphone
                self.coachLevelBars = (0..<5).map { index in
                    let bar = NSView(frame: NSRect(x: dictationCoachLevelBarsOriginX(closeButtonVisible: true) + CGFloat(index) * 6, y: 92, width: 3, height: 2))
                    bar.wantsLayer = true
                    bar.layer?.backgroundColor = NSColor(calibratedRed: 0.72, green: 0.66, blue: 1, alpha: 1).cgColor
                    bar.layer?.cornerRadius = 1
                    content.addSubview(bar)
                    return bar
                }
                let close = PointerButton(title: "✕", target: self, action: #selector(self.closeCoachPanel))
                close.frame = NSRect(x: 328, y: 85, width: 24, height: 24)
                close.bezelStyle = .circular
                close.contentTintColor = NSColor(calibratedWhite: 0.91, alpha: 1)
                close.setAccessibilityLabel("Stop Speech Coach")
                close.toolTip = "Stop Listen In"
                content.addSubview(close)
                self.coachCloseButton = close
                panel.contentView = content
                self.panel = panel
                self.label = label
            }
            self.label?.stringValue = text
            self.coachLabel?.isHidden = !self.coachEnabled
            self.coachPitchLabel?.isHidden = !self.coachEnabled
            self.coachPaceLabel?.isHidden = !self.coachEnabled
            self.coachZoneTrack?.isHidden = !self.coachEnabled
            self.coachPaceValue?.isHidden = !self.coachEnabled
            if self.coachEnabled { self.coachLabel?.stringValue = Self.coachIdleText }
            self.cancelButton?.isHidden = self.coachEnabled && !self.dictationVisible
            self.applyChrome()
            guard self.overlayVisible else { return }
            self.positionPanel()
            self.panel?.orderFrontRegardless()
        }
    }

    private func showCoachPanel(_ text: String, generation value: UInt64) {
        DispatchQueue.main.async {
            self.lock.lock()
            let shouldShow = self.coachEnabled && self.overlayVisible
            self.lock.unlock()
            guard shouldShow else { return }
            if self.panel == nil { self.show(text, generation: value); return }
            self.label?.stringValue = text
            self.coachLabel?.isHidden = false
            self.coachPitchLabel?.isHidden = false
            self.coachPaceLabel?.isHidden = false
            self.coachZoneTrack?.isHidden = false
            self.coachPaceValue?.isHidden = false
            self.coachLabel?.stringValue = Self.coachIdleText
            self.cancelButton?.isHidden = self.coachEnabled && !self.dictationVisible
            self.applyChrome()
            self.positionPanel()
            self.panel?.orderFrontRegardless()
        }
    }

    // Main thread only. Hides the dictation controls that would sit on top of the coach rows.
    private func applyChrome() {
        lock.lock()
        let chrome = dictationOverlayChrome(coachEnabled: coachEnabled, dictationVisible: dictationVisible)
        lock.unlock()
        meter?.isHidden = !chrome.legacyMeter
        escHint?.isHidden = !chrome.legacyEscHint
        microphoneIcon?.isHidden = !chrome.legacyMicrophone
        coachLevelBars.forEach { $0.isHidden = !chrome.levelBars }
        coachCloseButton?.isHidden = !chrome.closeButton
        let layout = dictationCancelLayout(inCorner: chrome.cancelInCorner)
        cancelButton?.frame = layout.cancel
        escHint?.frame = layout.escHint
        escHint?.font = .systemFont(ofSize: chrome.cancelInCorner ? 10 : 12)
        label?.frame.size.width = layout.titleWidth
        coachZoneTrack?.alphaValue = coachHasPaceReading ? 1 : 0.4
        guard chrome.levelBars, !coachHasPaceReading else { return }
        let current = coachLabel?.stringValue ?? ""
        // Only the idle line is replaced; a coaching cue keeps the line until it expires.
        guard current.isEmpty || current == Self.coachIdleText || current.hasPrefix("Measuring your pace") else { return }
        let seconds = OfficeKitAudioCapture.shared.coachSpeechSeconds()
        coachLabel?.stringValue = dictationCoachMeasuringText(speechSeconds: seconds) ?? Self.coachIdleText
    }

    private static let coachIdleText = "Speak naturally · audio stays on this Mac"

    private func positionPanel() {
        lock.lock()
        let position = placementCode
        lock.unlock()
        let screen = NSScreen.screens.first(where: { NSMouseInRect(NSEvent.mouseLocation, $0.frame, false) }) ?? NSScreen.main
        guard let frame = screen?.visibleFrame else { return }
        let x: CGFloat
        switch position {
        case 1, 4: x = frame.minX + 24
        case 2, 5: x = frame.maxX - 384
        default: x = frame.midX - 180
        }
        let y = position >= 3 ? frame.minY + 24 : frame.maxY - 140
        panel?.setFrameOrigin(NSPoint(x: x, y: y))
    }
}

@_cdecl("officekit_dictation_overlay_begin")
public func officekitDictationOverlayBegin() -> UInt64 { OfficeKitDictationOverlay.shared.begin() }
@_cdecl("officekit_dictation_overlay_generation")
public func officekitDictationOverlayGeneration() -> UInt64 { OfficeKitDictationOverlay.shared.current() }
@_cdecl("officekit_dictation_overlay_valid")
public func officekitDictationOverlayValid(_ generation: UInt64) -> Int32 { OfficeKitDictationOverlay.shared.valid(generation) ? 1 : 0 }
@_cdecl("officekit_dictation_overlay_processing")
public func officekitDictationOverlayProcessing(_ generation: UInt64) { OfficeKitDictationOverlay.shared.show("Transcribing…", generation: generation) }
@_cdecl("officekit_dictation_overlay_transcript")
public func officekitDictationOverlayTranscript(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64, _ generation: UInt64) {
    guard let bytes, length > 0, length <= 262_144,
          let text = String(bytes: UnsafeBufferPointer(start: bytes, count: Int(length)), encoding: .utf8) else { return }
    OfficeKitDictationOverlay.shared.showTranscript(text, generation: generation)
}
@_cdecl("officekit_dictation_overlay_fail")
public func officekitDictationOverlayFail(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64, _ generation: UInt64) {
    guard let bytes, length > 0, length <= 512,
          let text = String(bytes: UnsafeBufferPointer(start: bytes, count: Int(length)), encoding: .utf8) else {
        OfficeKitDictationOverlay.shared.finish(generation)
        return
    }
    OfficeKitDictationOverlay.shared.fail(text, generation: generation)
}
@_cdecl("officekit_dictation_overlay_finish")
public func officekitDictationOverlayFinish(_ generation: UInt64) { OfficeKitDictationOverlay.shared.finish(generation) }
@_cdecl("officekit_dictation_overlay_cancel")
public func officekitDictationOverlayCancel() { OfficeKitDictationOverlay.shared.cancel() }

private final class OfficeKitFunctionKeyMonitor {
    static let shared = OfficeKitFunctionKeyMonitor()

    private let lock = NSLock()
    private var globalMonitor: Any?
    private var localMonitor: Any?
    private var configuredKeyCode: UInt16?
    private var configuredCustomKey: (keyCode: UInt16, flags: NSEvent.ModifierFlags)?
    private var keyPressed = false
    private var modifierKeyState = DictationModifierKeyState()
    private var starting = false

    func accessibilityStatus() -> Int32 {
        AXIsProcessTrusted() ? 0 : 1
    }

    func requestAccessibility() -> Int32 {
        let promptKey = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        let options = [promptKey: true] as CFDictionary
        return AXIsProcessTrustedWithOptions(options) ? 0 : 1
    }

    func start(keyID: Int32, keyCode: Int32, modifierMask: Int32) -> Int32 {
        guard AXIsProcessTrusted() else { return 2 }
        let keyCodeForModifier = keyID == 9 ? nil : dictationNativeKeyCode(for: keyID)
        let customKey: (keyCode: UInt16, flags: NSEvent.ModifierFlags)?
        if keyID == 9 {
            guard (0...127).contains(keyCode), let flags = Self.modifierFlags(for: modifierMask) else {
                return 4
            }
            customKey = (UInt16(keyCode), flags)
        } else {
            guard keyCodeForModifier != nil else { return 4 }
            customKey = nil
        }
        lock.lock()
        if globalMonitor != nil || localMonitor != nil || starting {
            lock.unlock()
            return 1
        }
        starting = true
        configuredKeyCode = keyCodeForModifier
        configuredCustomKey = customKey
        keyPressed = false
        modifierKeyState.reset()
        lock.unlock()

        let monitors = onMain {
            let eventTypes: NSEvent.EventTypeMask = [.flagsChanged, .keyDown, .keyUp]
            let global = NSEvent.addGlobalMonitorForEvents(matching: eventTypes) { [weak self] event in
                self?.observe(event)
            }
            let local = NSEvent.addLocalMonitorForEvents(matching: eventTypes) { [weak self] event in
                self?.observe(event)
                return event
            }
            return (global, local)
        }

        guard monitors.0 != nil && monitors.1 != nil else {
            onMain {
                if let global = monitors.0 { NSEvent.removeMonitor(global) }
                if let local = monitors.1 { NSEvent.removeMonitor(local) }
            }
            lock.lock()
            starting = false
            configuredKeyCode = nil
            configuredCustomKey = nil
            keyPressed = false
            modifierKeyState.reset()
            lock.unlock()
            return 3
        }

        lock.lock()
        globalMonitor = monitors.0
        localMonitor = monitors.1
        starting = false
        lock.unlock()
        return 0
    }

    func stop() {
        lock.lock()
        let global = globalMonitor
        let local = localMonitor
        globalMonitor = nil
        localMonitor = nil
        keyPressed = false
        modifierKeyState.reset()
        configuredKeyCode = nil
        configuredCustomKey = nil
        lock.unlock()
        onMain {
            if let global { NSEvent.removeMonitor(global) }
            if let local { NSEvent.removeMonitor(local) }
        }
    }

    func isKeyPressed() -> Int32 {
        lock.lock()
        defer { lock.unlock() }
        return keyPressed ? 1 : 0
    }

    private func observe(_ event: NSEvent) {
        if event.type == .keyDown && event.keyCode == 53 {
            OfficeKitDictationOverlay.shared.cancel()
        }
        lock.lock()
        if let configuredKeyCode, event.type == .flagsChanged {
            // Modifier codes only: never log typed text or non-modifier keys.
            dictationDiagnosticLogger.notice("Modifier event code=\(event.keyCode, privacy: .public) selected=\(configuredKeyCode, privacy: .public)")
        }
        if let custom = configuredCustomKey {
            let activeFlags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            if event.type == .keyDown && event.keyCode == custom.keyCode {
                keyPressed = activeFlags.intersection(custom.flags) == custom.flags
            } else if event.type == .keyUp && event.keyCode == custom.keyCode {
                keyPressed = false
            } else if event.type == .flagsChanged && activeFlags.intersection(custom.flags) != custom.flags {
                keyPressed = false
            }
            lock.unlock()
            return
        }
        guard let configuredKeyCode, event.type == .flagsChanged, event.keyCode == configuredKeyCode else {
            lock.unlock()
            return
        }
        let physicalKeyIsDown = dictationModifierKeyIsDown(
            keyCode: configuredKeyCode,
            flags: event.modifierFlags.rawValue
        )
        dictationDiagnosticLogger.notice("Selected modifier down=\(physicalKeyIsDown, privacy: .public) flags=\(event.modifierFlags.rawValue, privacy: .public)")
        modifierKeyState.update(
            eventKeyCode: event.keyCode,
            selectedKeyCode: configuredKeyCode,
            keyIsDown: physicalKeyIsDown
        )
        keyPressed = modifierKeyState.isPressed
        lock.unlock()
    }

    private static func modifierFlags(for mask: Int32) -> NSEvent.ModifierFlags? {
        guard (0...15).contains(mask) else { return nil }
        var flags: NSEvent.ModifierFlags = []
        if mask & 0b0001 != 0 { flags.insert(.control) }
        if mask & 0b0010 != 0 { flags.insert(.option) }
        if mask & 0b0100 != 0 { flags.insert(.shift) }
        if mask & 0b1000 != 0 { flags.insert(.command) }
        return flags
    }

    private func onMain<T>(_ operation: () -> T) -> T {
        if Thread.isMainThread { return operation() }
        return DispatchQueue.main.sync(execute: operation)
    }
}

func dictationNativeKeyCode(for keyID: Int32) -> UInt16? {
    return switch keyID {
    case 0: 63
    case 1: 58
    case 2: 61
    case 3: 59
    case 4: 62
    case 5: 55
    case 6: 54
    case 7: 56
    case 8: 60
    default: nil
    }
}

@available(macOS 13.0, *)
private final class OfficeKitSystemAudioCapture: NSObject, SCStreamOutput {
    private var stream: SCStream?
    private let queue = DispatchQueue(label: "officekit.system-audio-capture", qos: .userInitiated)

    func start() {
        guard CGPreflightScreenCaptureAccess() else { return }
        Task {
            do {
                let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
                guard let display = content.displays.first else { return }
                let filter = SCContentFilter(display: display, excludingWindows: [])
                let config = SCStreamConfiguration()
                config.capturesAudio = true
                config.sampleRate = 16000
                config.channelCount = 1
                config.excludesCurrentProcessAudio = true
                let scStream = SCStream(filter: filter, configuration: config, delegate: nil)
                try scStream.addStreamOutput(self, type: .audio, sampleHandlerQueue: self.queue)
                try await scStream.startCapture()
                self.stream = scStream
            } catch {
                // If system audio capture fails (e.g. no permission), microphone capture continues
            }
        }
    }

    func stop() {
        guard let active = stream else { return }
        stream = nil
        Task {
            try? await active.stopCapture()
        }
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, let blockBuffer = sampleBuffer.dataBuffer else { return }
        var lengthAtOffsetOut = 0
        var totalLengthOut = 0
        var dataPointerOut: UnsafeMutablePointer<Int8>?
        guard CMBlockBufferGetDataPointer(blockBuffer, atOffset: 0, lengthAtOffsetOut: &lengthAtOffsetOut, totalLengthOut: &totalLengthOut, dataPointerOut: &dataPointerOut) == noErr,
              let dataPointer = dataPointerOut else { return }
        let floatCount = totalLengthOut / MemoryLayout<Float>.size
        guard floatCount > 0 else { return }
        let floats = dataPointer.withMemoryRebound(to: Float.self, capacity: floatCount) { ptr in
            Array(UnsafeBufferPointer(start: ptr, count: floatCount))
        }
        OfficeKitAudioCapture.shared.appendExternalSamples(floats)
    }
}

private final class OfficeKitAudioCapture {
    static let shared = OfficeKitAudioCapture()
    private let voiceActivityRmsThreshold: Float = 0.015

    private let lock = NSLock()
    private let lifecycleLock = DictationCaptureLifecycleLock()
    private var startGate = DictationCaptureStartGate()
    private var engine: AVAudioEngine?
    private var samples: [Float] = []
    private var overflowed = false
    private var conversionFailed = false
    private var isMeetingMode = false
    private var coachActive = false
    private var coachAttachedByDictation = false
    private var dictationActive = false
    private var coachVoiceSeconds: Double = 0
    private var coachWindowSamples: [Float] = []
    private var coachWindowVoiceSeconds: Double = 0
    private let coachWindowLimit = Int(dictationSampleRate * 15.0)
    private let coachWindowMinimum = Int(dictationSampleRate * 10.0)
    private var systemAudioCapture: Any?
    private var receivedBuffer = false
    private var lastVoiceActivityUptime: Double = 0
    private var configObserver: NSObjectProtocol?

    /// Installs the tap with a converter matching the engine's current input format.
    private func installTap(on input: AVAudioInputNode) -> Bool {
        let inputFormat = input.inputFormat(forBus: 0)
        guard inputFormat.sampleRate > 0,
              inputFormat.channelCount > 0,
              let outputFormat = AVAudioFormat(
                commonFormat: .pcmFormatFloat32,
                sampleRate: dictationSampleRate,
                channels: 1,
                interleaved: false
              ),
              let converter = AVAudioConverter(from: inputFormat, to: outputFormat) else {
            return false
        }
        return OfficeKitInstallAudioTap(input, inputFormat, { [weak self] buffer, _ in
            self?.consume(buffer, converter: converter, outputFormat: outputFormat)
        })
    }

    /// A Bluetooth headset or device switch stops the engine mid-start; rebuild instead of
    /// ending the session with no audio.
    private func handleConfigurationChange(_ candidate: AVAudioEngine) {
        lifecycleLock.withLock { handleConfigurationChangeLocked(candidate) }
    }

    private func handleConfigurationChangeLocked(_ candidate: AVAudioEngine) {
        lock.lock()
        let isActive = engine === candidate
        lock.unlock()
        guard isActive else { return }
        candidate.inputNode.removeTap(onBus: 0)
        guard installTap(on: candidate.inputNode) else { return }
        candidate.prepare()
        do { try candidate.start() } catch {
            dictationDiagnosticLogger.notice("Audio engine restart after route change failed")
        }
    }

    func start(meetingMode: Bool = false, captureSystemAudio: Bool = false) -> Int32 {
        lifecycleLock.withLock {
            startLocked(meetingMode: meetingMode, captureSystemAudio: captureSystemAudio)
        }
    }

    private func startLocked(meetingMode: Bool, captureSystemAudio: Bool) -> Int32 {
        dictationDiagnosticLogger.notice("Audio capture start requested")
        lock.lock()
        if engine != nil {
            if meetingMode == false && coachActive && !dictationActive {
                for index in samples.indices { samples[index] = 0.0 }
                samples.removeAll(keepingCapacity: true)
                overflowed = false
                conversionFailed = false
                receivedBuffer = false
                isMeetingMode = false
                dictationActive = true
                coachVoiceSeconds = 0
                for index in coachWindowSamples.indices { coachWindowSamples[index] = 0.0 }
                coachWindowSamples.removeAll(keepingCapacity: true)
                coachWindowVoiceSeconds = 0
                lock.unlock()
                return 0
            }
            lock.unlock()
            return 1
        }
        guard startGate.begin() else {
            lock.unlock()
            return 1
        }
        defer {
            lock.lock()
            startGate.finish()
            lock.unlock()
        }
        for index in samples.indices {
            samples[index] = 0.0
        }
        samples.removeAll(keepingCapacity: true)
        overflowed = false
        conversionFailed = false
        isMeetingMode = meetingMode
        receivedBuffer = false
        dictationActive = true
        lock.unlock()

        guard #available(macOS 14.0, *),
              currentDictationMicrophonePermissionCode() == 0 else { return 2 }
        guard dictationHasDefaultAudioInput() else { return 4 }

        let candidate = AVAudioEngine()
        let input = candidate.inputNode
        guard installTap(on: input) else { return 3 }
        lock.lock()
        engine = candidate
        lock.unlock()
        configObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: candidate, queue: .main
        ) { [weak self, weak candidate] _ in
            guard let candidate else { return }
            self?.handleConfigurationChange(candidate)
        }
        candidate.prepare()
        do {
            try candidate.start()
        } catch {
            input.removeTap(onBus: 0)
            if let observer = configObserver { NotificationCenter.default.removeObserver(observer) }
            configObserver = nil
            lock.lock()
            engine = nil
            lock.unlock()
            return 3
        }

        if #available(macOS 13.0, *), captureSystemAudio {
            let system = OfficeKitSystemAudioCapture()
            system.start()
            lock.lock()
            systemAudioCapture = system
            lock.unlock()
        }

        return 0
    }

    func stop() -> Int32 {
        lifecycleLock.withLock { stopLocked() }
    }

    private func stopLocked() -> Int32 {
        // Releasing the key right after the engine starts can beat the first buffer
        // (slow or Bluetooth inputs); give it a moment before calling it empty.
        if !Thread.isMainThread {
            for _ in 0..<25 {
                lock.lock()
                let ready = receivedBuffer || engine == nil
                lock.unlock()
                if ready { break }
                Thread.sleep(forTimeInterval: 0.02)
            }
        }
        lock.lock()
        guard dictationActive else { lock.unlock(); return 1 }
        dictationActive = false
        let ownership = dictationCoachOwnershipAfterDictationStops(
            coachActive: coachActive,
            attachedByDictation: coachAttachedByDictation
        )
        coachActive = ownership.coachActive
        coachAttachedByDictation = ownership.attachedByDictation
        if ownership.releasedAttachedCoach {
            for index in coachWindowSamples.indices { coachWindowSamples[index] = 0.0 }
            coachWindowSamples.removeAll(keepingCapacity: false)
            coachWindowVoiceSeconds = 0
        }
        if ownership.releasedAttachedCoach { OfficeKitDictationOverlay.shared.endCoach() }
        if dictationCaptureHasActiveOwner(coachActive: coachActive, dictationActive: false) {
            let didOverflow = overflowed
            let didFailConversion = conversionFailed
            let hasSamples = !samples.isEmpty
            lock.unlock()
            if didOverflow { return 4 }
            if didFailConversion { return 3 }
            return hasSamples ? 0 : 5
        }
        let activeEngine = engine
        engine = nil
        let activeSystem = systemAudioCapture
        systemAudioCapture = nil
        isMeetingMode = false
        lock.unlock()
        if let observer = configObserver { NotificationCenter.default.removeObserver(observer) }
        configObserver = nil

        if #available(macOS 13.0, *), let system = activeSystem as? OfficeKitSystemAudioCapture {
            system.stop()
        }

        if let activeEngine {
            activeEngine.inputNode.removeTap(onBus: 0)
            activeEngine.stop()
        }

        lock.lock()
        let didOverflow = overflowed
        let didFailConversion = conversionFailed
        let hasSamples = !samples.isEmpty
        lock.unlock()

        if didOverflow { return 4 }
        if didFailConversion { return 3 }
        guard activeEngine != nil else { return 1 }
        return hasSamples ? 0 : 5
    }

    private func stopAll() -> Int32 {
        lifecycleLock.withLock {
            lock.lock()
            coachActive = false
            coachAttachedByDictation = false
            for index in coachWindowSamples.indices { coachWindowSamples[index] = 0.0 }
            coachWindowSamples.removeAll(keepingCapacity: false)
            coachWindowVoiceSeconds = 0
            if engine != nil { dictationActive = true }
            lock.unlock()
            return stopLocked()
        }
    }

    func startCoach() -> Int32 {
        lifecycleLock.withLock { startCoachLocked() }
    }

    private func startCoachLocked() -> Int32 {
        lock.lock()
        if coachActive {
            lock.unlock()
            return 0
        }
        if engine != nil {
            coachActive = true
            coachVoiceSeconds = 0
            coachWindowVoiceSeconds = 0
            coachWindowSamples.removeAll(keepingCapacity: true)
            lock.unlock()
            return 0
        }
        lock.unlock()
        let code = start()
        guard code == 0 else { return code }
        lock.lock()
        coachActive = true
        coachVoiceSeconds = 0
        coachWindowVoiceSeconds = 0
        coachWindowSamples.removeAll(keepingCapacity: true)
        dictationActive = false
        for index in samples.indices { samples[index] = 0.0 }
        samples.removeAll(keepingCapacity: true)
        lock.unlock()
        return 0
    }

    /// Coaching for the length of a dictation that is already recording; ends when it ends.
    func startCoachForDictation() -> Int32 {
        lifecycleLock.withLock {
            lock.lock()
            defer { lock.unlock() }
            if coachActive { return 0 }
            guard dictationCoachCanAttach(engineRunning: engine != nil, dictationActive: dictationActive, coachActive: coachActive),
                  !isMeetingMode else { return 1 }
            coachActive = true
            coachAttachedByDictation = true
            coachVoiceSeconds = 0
            coachWindowVoiceSeconds = 0
            coachWindowSamples.removeAll(keepingCapacity: true)
            return 0
        }
    }

    /// Coaching for the length of a meeting recording that is already running. It listens to the
    /// microphone only: system audio reaches the recording through appendExternalSamples and never
    /// the coach window. Ends when the recording ends.
    func startCoachForMeeting() -> Int32 {
        lifecycleLock.withLock {
            lock.lock()
            defer { lock.unlock() }
            // 2: a coach session (Listen In) already owns the window, so this call did not join it.
            if coachActive { return 2 }
            guard dictationCoachCanAttach(engineRunning: engine != nil, dictationActive: dictationActive, coachActive: coachActive),
                  isMeetingMode else { return 1 }
            coachActive = true
            coachAttachedByDictation = true
            coachVoiceSeconds = 0
            coachWindowVoiceSeconds = 0
            coachWindowSamples.removeAll(keepingCapacity: true)
            return 0
        }
    }

    func stopCoach() -> Int32 {
        lifecycleLock.withLock { stopCoachLocked() }
    }

    private func stopCoachLocked() -> Int32 {
        lock.lock()
        guard coachActive else { lock.unlock(); return 1 }
        coachActive = false
        coachAttachedByDictation = false
        for index in coachWindowSamples.indices { coachWindowSamples[index] = 0.0 }
        coachWindowSamples.removeAll(keepingCapacity: false)
        coachWindowVoiceSeconds = 0
        if dictationCaptureHasActiveOwner(coachActive: false, dictationActive: dictationActive) {
            lock.unlock()
            return 0
        }
        let activeEngine = engine
        engine = nil
        let activeSystem = systemAudioCapture
        systemAudioCapture = nil
        isMeetingMode = false
        lock.unlock()
        if let observer = configObserver { NotificationCenter.default.removeObserver(observer) }
        configObserver = nil
        if #available(macOS 13.0, *), let system = activeSystem as? OfficeKitSystemAudioCapture { system.stop() }
        if let activeEngine {
            activeEngine.inputNode.removeTap(onBus: 0)
            activeEngine.stop()
        }
        lock.lock()
        for index in samples.indices { samples[index] = 0.0 }
        samples.removeAll(keepingCapacity: false)
        overflowed = false
        conversionFailed = false
        lock.unlock()
        return 0
    }

    func coachSpeechSeconds() -> Double {
        lock.lock()
        defer { lock.unlock() }
        return coachVoiceSeconds
    }

    func isCoachActive() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return coachActive
    }

    func drainCoachWindow(
        into destination: UnsafeMutablePointer<Float>?,
        capacity: UInt64,
        speechSeconds: UnsafeMutablePointer<Double>?
    ) -> UInt64 {
        lock.lock()
        defer { lock.unlock() }
        guard let destination, let capacity = Int(exactly: capacity),
              dictationCoachWindowShouldDrain(
                sampleCount: coachWindowSamples.count,
                minimum: coachWindowMinimum,
                maximum: coachWindowLimit,
                capacity: capacity,
                coachActive: coachActive,
                dictationActive: dictationActive
              )
        else { return 0 }
        let count = coachWindowSamples.count
        coachWindowSamples.withUnsafeBufferPointer { source in
            guard let base = source.baseAddress else { return }
            destination.update(from: base, count: count)
        }
        speechSeconds?.pointee = coachWindowVoiceSeconds
        for index in coachWindowSamples.indices { coachWindowSamples[index] = 0.0 }
        coachWindowSamples.removeAll(keepingCapacity: true)
        coachWindowVoiceSeconds = 0
        return UInt64(count)
    }

    func coachWindowSampleCount() -> UInt64 {
        lock.lock()
        defer { lock.unlock() }
        guard dictationCoachWindowShouldDrain(
            sampleCount: coachWindowSamples.count,
            minimum: coachWindowMinimum,
            maximum: coachWindowLimit,
            capacity: coachWindowLimit,
            coachActive: coachActive,
            dictationActive: dictationActive
        ) else { return 0 }
        return UInt64(coachWindowSamples.count)
    }

    func appendExternalSamples(_ external: [Float]) {
        lock.lock()
        defer { lock.unlock() }
        guard !overflowed, !conversionFailed else { return }
        let maxSamples = isMeetingMode ? Int(dictationSampleRate * 180.0) : dictationMaxSamples
        let room = max(0, maxSamples - samples.count)
        let take = min(room, external.count)
        if take > 0 {
            for sample in external[0..<take] {
                guard sample.isFinite else { continue }
                samples.append(max(-1.0, min(1.0, sample)))
            }
        }
    }

    func copySamples(into destination: UnsafeMutablePointer<Float>?, capacity: UInt64) -> UInt64 {
        guard let destination, capacity > 0 else { return 0 }
        lock.lock()
        defer { lock.unlock() }
        let count = min(samples.count, Int(min(capacity, UInt64(Int.max))))
        samples.withUnsafeBufferPointer { source in
            guard let base = source.baseAddress else { return }
            destination.update(from: base, count: count)
        }
        return UInt64(count)
    }

    func copySamples(from offset: UInt64, into destination: UnsafeMutablePointer<Float>?, capacity: UInt64) -> UInt64 {
        guard let destination, capacity > 0 else { return 0 }
        lock.lock()
        defer { lock.unlock() }
        let start = min(samples.count, Int(min(offset, UInt64(Int.max))))
        let count = min(samples.count - start, Int(min(capacity, UInt64(Int.max))))
        guard count > 0 else { return 0 }
        samples.withUnsafeBufferPointer { source in
            guard let base = source.baseAddress else { return }
            destination.update(from: base.advanced(by: start), count: count)
        }
        return UInt64(count)
    }

    func drainSamples(into destination: UnsafeMutablePointer<Float>?, capacity: UInt64) -> UInt64 {
        guard let destination, capacity > 0 else { return 0 }
        lock.lock()
        defer { lock.unlock() }
        let count = min(samples.count, Int(min(capacity, UInt64(Int.max))))
        guard count > 0 else { return 0 }
        samples.withUnsafeBufferPointer { source in
            guard let base = source.baseAddress else { return }
            destination.update(from: base, count: count)
        }
        samples.removeFirst(count)
        overflowed = false
        return UInt64(count)
    }

    func sampleCount() -> UInt64 {
        lock.lock()
        defer { lock.unlock() }
        return UInt64(samples.count)
    }

    func clear() {
        lock.lock()
        for index in samples.indices {
            samples[index] = 0.0
        }
        samples.removeAll(keepingCapacity: false)
        overflowed = false
        conversionFailed = false
        lock.unlock()
    }

    private func consume(
        _ inputBuffer: AVAudioPCMBuffer,
        converter: AVAudioConverter,
        outputFormat: AVAudioFormat
    ) {
        let ratio = outputFormat.sampleRate / inputBuffer.format.sampleRate
        let capacity = AVAudioFrameCount(ceil(Double(inputBuffer.frameLength) * ratio) + 32)
        guard capacity > 0,
              let outputBuffer = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: capacity) else {
            markConversionFailure()
            return
        }

        var suppliedInput = false
        var conversionError: NSError?
        let status = converter.convert(to: outputBuffer, error: &conversionError) { _, inputStatus in
            guard !suppliedInput else {
                inputStatus.pointee = .noDataNow
                return nil
            }
            suppliedInput = true
            inputStatus.pointee = .haveData
            return inputBuffer
        }
        guard conversionError == nil,
              status != .error,
              let channel = outputBuffer.floatChannelData?[0] else {
            markConversionFailure()
            return
        }

        let frameCount = Int(outputBuffer.frameLength)
        guard frameCount > 0 else { return }
        lock.lock()
        receivedBuffer = true
        lock.unlock()
        let energy = UnsafeBufferPointer(start: channel, count: frameCount).reduce(Float(0)) { $0 + $1 * $1 }
        let rms = energy.isFinite ? sqrt(energy / Float(frameCount)) : 0
        if energy.isFinite { OfficeKitDictationOverlay.shared.level(rms) }
        lock.lock()
        if rms >= voiceActivityRmsThreshold {
            lastVoiceActivityUptime = ProcessInfo.processInfo.systemUptime
            if coachActive { coachVoiceSeconds += Double(frameCount) / dictationSampleRate }
        }
        if coachActive && (!dictationActive || isMeetingMode) {
            if coachWindowSamples.count + frameCount > coachWindowLimit {
                for index in coachWindowSamples.indices { coachWindowSamples[index] = 0.0 }
                coachWindowSamples.removeAll(keepingCapacity: true)
                coachWindowVoiceSeconds = 0
            }
            if rms >= voiceActivityRmsThreshold {
                coachWindowVoiceSeconds += Double(frameCount) / dictationSampleRate
            }
            for sample in UnsafeBufferPointer(start: channel, count: frameCount) {
                coachWindowSamples.append(sample.isFinite ? max(-1.0, min(1.0, sample)) : 0.0)
            }
        }
        guard dictationActive else { lock.unlock(); return }
        let maxSamples = isMeetingMode ? Int(dictationSampleRate * 180.0) : dictationMaxSamples
        if samples.count + frameCount > maxSamples {
            overflowed = true
            lock.unlock()
            DispatchQueue.main.async { [weak self] in _ = self?.stop() }
            return
        }
        for sample in UnsafeBufferPointer(start: channel, count: frameCount) {
            guard sample.isFinite else {
                conversionFailed = true
                lock.unlock()
                DispatchQueue.main.async { [weak self] in _ = self?.stop() }
                return
            }
            samples.append(max(-1.0, min(1.0, sample)))
        }
        lock.unlock()
    }

    func voiceActivityAgeSeconds() -> Double {
        lock.lock()
        defer { lock.unlock() }
        guard lastVoiceActivityUptime > 0 else { return .infinity }
        return max(0, ProcessInfo.processInfo.systemUptime - lastVoiceActivityUptime)
    }

    private func markConversionFailure() {
        lock.lock()
        conversionFailed = true
        let activeEngine = engine
        lock.unlock()
        DispatchQueue.main.async { [weak self] in
            _ = self?.stopAll()
            activeEngine?.stop()
        }
    }
}

@_cdecl("officekit_dictation_microphone_permission_status")
public func officekitDictationMicrophonePermissionStatus() -> Int32 {
    guard #available(macOS 14.0, *) else { return 3 }
    return currentDictationMicrophonePermissionCode()
}

@_cdecl("officekit_dictation_has_audio_input")
public func officekitDictationHasAudioInput() -> Int32 {
    dictationHasDefaultAudioInput() ? 1 : 0
}

@_cdecl("officekit_dictation_request_microphone_permission")
public func officekitDictationRequestMicrophonePermission() -> Int32 {
    guard #available(macOS 14.0, *) else { return 3 }
    let permissionCode = currentDictationMicrophonePermissionCode()
    guard permissionCode == 1 else { return permissionCode }
    OfficeKitMicrophonePermissionProbe.shared.request()
    return 1
}

@_cdecl("officekit_dictation_start_capture")
public func officekitDictationStartCapture() -> Int32 {
    OfficeKitAudioCapture.shared.start()
}

@_cdecl("officekit_dictation_coach_start")
public func officekitDictationCoachStart() -> Int32 {
    guard #available(macOS 14.0, *), currentDictationMicrophonePermissionCode() == 0,
          dictationHasDefaultAudioInput() else { return 2 }
    let result = OfficeKitAudioCapture.shared.startCoach()
    if result == 0 { OfficeKitDictationOverlay.shared.beginCoach() }
    return result
}

@_cdecl("officekit_dictation_coach_start_for_dictation")
public func officekitDictationCoachStartForDictation() -> Int32 {
    let result = OfficeKitAudioCapture.shared.startCoachForDictation()
    if result == 0 { OfficeKitDictationOverlay.shared.beginCoach() }
    return result
}

@_cdecl("officekit_dictation_coach_start_for_meeting")
public func officekitDictationCoachStartForMeeting() -> Int32 {
    let result = OfficeKitAudioCapture.shared.startCoachForMeeting()
    if result == 0 { OfficeKitDictationOverlay.shared.beginCoach() }
    return result
}

@_cdecl("officekit_dictation_coach_set_close_callback")
public func officekitDictationCoachSetCloseCallback(_ callback: @escaping @convention(c) () -> Void) {
    OfficeKitDictationOverlay.shared.coachCloseCallback = callback
}

@_cdecl("officekit_dictation_coach_stop")
public func officekitDictationCoachStop() -> Int32 {
    let result = OfficeKitAudioCapture.shared.stopCoach()
    if result == 0 || result == 1 { OfficeKitDictationOverlay.shared.endCoach() }
    return result
}

@_cdecl("officekit_dictation_coach_speech_seconds")
public func officekitDictationCoachSpeechSeconds() -> Double {
    OfficeKitAudioCapture.shared.coachSpeechSeconds()
}

@_cdecl("officekit_dictation_coach_is_active")
public func officeKitDictationCoachIsActive() -> Int32 {
    OfficeKitAudioCapture.shared.isCoachActive() ? 1 : 0
}

@_cdecl("officekit_dictation_coach_drain_window")
public func officekitDictationCoachDrainWindow(
    _ destination: UnsafeMutablePointer<Float>?,
    _ capacity: UInt64,
    _ speechSeconds: UnsafeMutablePointer<Double>?
) -> UInt64 {
    OfficeKitAudioCapture.shared.drainCoachWindow(
        into: destination,
        capacity: capacity,
        speechSeconds: speechSeconds
    )
}

@_cdecl("officekit_dictation_coach_window_sample_count")
public func officekitDictationCoachWindowSampleCount() -> UInt64 {
    OfficeKitAudioCapture.shared.coachWindowSampleCount()
}

@_cdecl("officekit_dictation_coach_cue")
public func officekitDictationCoachCue(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64, _ generation: UInt64) {
    guard let bytes, length > 0, length <= 512,
          let text = String(bytes: UnsafeBufferPointer(start: bytes, count: Int(length)), encoding: .utf8) else { return }
    OfficeKitDictationOverlay.shared.coachCue(text, generation: generation)
}

@_cdecl("officekit_dictation_coach_pitch_stats")
public func officekitDictationCoachPitchStats(_ medianHz: UInt16, _ rangeHz: UInt16, _ generation: UInt64) {
    OfficeKitDictationOverlay.shared.coachPitchStats(
        medianHz: medianHz,
        rangeHz: rangeHz,
        generation: generation
    )
}

@_cdecl("officekit_dictation_coach_pace")
public func officekitDictationCoachPace(_ paceWpm: UInt16, _ targetMin: UInt16, _ targetMax: UInt16, _ generation: UInt64) {
    OfficeKitDictationOverlay.shared.coachPace(
        paceWpm: paceWpm,
        targetMin: targetMin,
        targetMax: targetMax,
        generation: generation
    )
}

@_cdecl("officekit_dictation_coach_overlay_configure")
public func officekitDictationCoachOverlayConfigure(_ placement: Int32, _ visible: Int32) {
    OfficeKitDictationOverlay.shared.configure(placement: placement, visible: visible != 0)
}

@_cdecl("officekit_dictation_stop_capture")
public func officekitDictationStopCapture() -> Int32 {
    OfficeKitAudioCapture.shared.stop()
}

@_cdecl("officekit_dictation_sample_count")
public func officekitDictationSampleCount() -> UInt64 {
    OfficeKitAudioCapture.shared.sampleCount()
}

/// Writes the bundle ids of the apps that are capturing microphone input right now, one per line.
/// It reads CoreAudio's process list only: no audio is opened and nothing is recorded.
/// Returns the byte count written, or 0 when none is capturing or the system cannot say (before macOS 14.4).
@_cdecl("officekit_call_input_bundles")
public func officekitCallInputBundles(_ buffer: UnsafeMutablePointer<CChar>?, _ capacity: Int32) -> Int32 {
    guard let buffer, capacity > 1 else { return 0 }
    guard #available(macOS 14.4, *) else { return 0 }
    let system = AudioObjectID(kAudioObjectSystemObject)
    var listAddress = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyProcessObjectList,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(system, &listAddress, 0, nil, &size) == noErr, size > 0 else { return 0 }
    var processes = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(system, &listAddress, 0, nil, &size, &processes) == noErr else { return 0 }
    var bundles: [String] = []
    for process in processes {
        var runningAddress = AudioObjectPropertyAddress(
            mSelector: kAudioProcessPropertyIsRunningInput,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var running: UInt32 = 0
        var runningSize = UInt32(MemoryLayout<UInt32>.size)
        guard AudioObjectGetPropertyData(process, &runningAddress, 0, nil, &runningSize, &running) == noErr, running != 0 else { continue }
        var bundleAddress = AudioObjectPropertyAddress(
            mSelector: kAudioProcessPropertyBundleID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var bundle: Unmanaged<CFString>?
        var bundleSize = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        if AudioObjectGetPropertyData(process, &bundleAddress, 0, nil, &bundleSize, &bundle) == noErr,
           let name = bundle?.takeRetainedValue() {
            bundles.append(name as String)
        }
    }
    let bytes = Array(bundles.joined(separator: "\n").utf8.prefix(Int(capacity) - 1))
    for (index, byte) in bytes.enumerated() { buffer[index] = CChar(bitPattern: byte) }
    buffer[bytes.count] = 0
    return Int32(bytes.count)
}

@_cdecl("officekit_dictation_voice_activity_age_seconds")
public func officekitDictationVoiceActivityAgeSeconds() -> Double {
    OfficeKitAudioCapture.shared.voiceActivityAgeSeconds()
}

@_cdecl("officekit_dictation_copy_samples")
public func officekitDictationCopySamples(
    _ destination: UnsafeMutablePointer<Float>?,
    _ capacity: UInt64
) -> UInt64 {
    OfficeKitAudioCapture.shared.copySamples(into: destination, capacity: capacity)
}

@_cdecl("officekit_dictation_copy_samples_range")
public func officekitDictationCopySamplesRange(
    _ destination: UnsafeMutablePointer<Float>?,
    _ offset: UInt64,
    _ capacity: UInt64
) -> UInt64 {
    OfficeKitAudioCapture.shared.copySamples(from: offset, into: destination, capacity: capacity)
}

@_cdecl("officekit_dictation_start_meeting_capture")
public func officekitDictationStartMeetingCapture(_ captureSystemAudio: Int32) -> Int32 {
    OfficeKitAudioCapture.shared.start(meetingMode: true, captureSystemAudio: captureSystemAudio != 0)
}

@_cdecl("officekit_dictation_drain_samples")
public func officekitDictationDrainSamples(
    _ destination: UnsafeMutablePointer<Float>?,
    _ capacity: UInt64
) -> UInt64 {
    OfficeKitAudioCapture.shared.drainSamples(into: destination, capacity: capacity)
}

@_cdecl("officekit_dictation_screen_recording_permission_status")
public func officekitDictationScreenRecordingPermissionStatus() -> Int32 {
    CGPreflightScreenCaptureAccess() ? 0 : 1
}

@_cdecl("officekit_dictation_request_screen_recording_permission")
public func officekitDictationRequestScreenRecordingPermission() -> Int32 {
    CGRequestScreenCaptureAccess() ? 0 : 1
}

@_cdecl("officekit_dictation_clear_samples")
public func officekitDictationClearSamples() {
    OfficeKitAudioCapture.shared.clear()
}

@_cdecl("officekit_dictation_accessibility_status")
public func officekitDictationAccessibilityStatus() -> Int32 {
    OfficeKitFunctionKeyMonitor.shared.accessibilityStatus()
}

@_cdecl("officekit_dictation_request_accessibility_permission")
public func officekitDictationRequestAccessibilityPermission() -> Int32 {
    OfficeKitFunctionKeyMonitor.shared.requestAccessibility()
}

@_cdecl("officekit_dictation_start_hotkey_monitor")
public func officekitDictationStartHotkeyMonitor(
    _ keyID: Int32,
    _ keyCode: Int32,
    _ modifierMask: Int32
) -> Int32 {
    OfficeKitFunctionKeyMonitor.shared.start(keyID: keyID, keyCode: keyCode, modifierMask: modifierMask)
}

@_cdecl("officekit_dictation_stop_hotkey_monitor")
public func officekitDictationStopHotkeyMonitor() {
    OfficeKitFunctionKeyMonitor.shared.stop()
}

@_cdecl("officekit_dictation_hotkey_key_pressed")
public func officekitDictationHotkeyKeyPressed() -> Int32 {
    OfficeKitFunctionKeyMonitor.shared.isKeyPressed()
}

@_cdecl("officekit_dictation_paste_text")
public func officekitDictationPasteText(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64) -> Int32 {
    guard let bytes, length > 0, length <= UInt64(dictationMaxPasteBytes) else { return 2 }
    let textBytes = UnsafeBufferPointer(start: bytes, count: Int(length))
    guard let text = String(bytes: textBytes, encoding: .utf8) else { return 2 }
    let operation = { OfficeKitTranscriptPaster.shared.paste(text) }
    return Thread.isMainThread ? operation() : DispatchQueue.main.sync(execute: operation)
}

@_cdecl("officekit_dictation_paste_session")
public func officekitDictationPasteSession(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64, _ generation: UInt64) -> Int32 {
    guard let bytes, length > 0, length <= UInt64(dictationMaxPasteBytes),
          let text = String(bytes: UnsafeBufferPointer(start: bytes, count: Int(length)), encoding: .utf8) else { return 2 }
    let operation = {
        guard generation == 0 || OfficeKitDictationOverlay.shared.valid(generation) else { return Int32(3) }
        let target = generation == 0 ? nil : OfficeKitDictationOverlay.shared.pasteTarget(generation)
        guard generation == 0 || target != nil else { return Int32(3) }
        let result = OfficeKitTranscriptPaster.shared.paste(text, expectedPID: target)
        if generation != 0 { OfficeKitDictationOverlay.shared.finish(generation) }
        return result
    }
    return Thread.isMainThread ? operation() : DispatchQueue.main.sync(execute: operation)
}
