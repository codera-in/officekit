import AppKit
import ApplicationServices
import Foundation
import OSLog

private let windowDiagnosticLogger = Logger(subsystem: "app.officekit.desktop", category: "window-manager")

/// Records a short, content-free state transition (for example "drag started") in the unified log.
@_cdecl("officekit_wm_diag")
public func officekitWindowDiagnostic(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64) {
    guard let bytes, length > 0, length <= 120 else { return }
    let text = String(decoding: UnsafeBufferPointer(start: bytes, count: Int(length)), as: UTF8.self)
    windowDiagnosticLogger.notice("\(text, privacy: .public)")
}

// Native half of the global window manager. Layout math lives in Rust (`window_manager.rs`); this
// file only reads and sets the focused window's frame through Accessibility, reports the visible
// screen areas, watches left-button drags and draws the click-through snap preview.
// All coordinates are Accessibility coordinates: origin at the top left of the primary display.

private func windowOnMainSync<T>(_ operation: () -> T) -> T {
    Thread.isMainThread ? operation() : DispatchQueue.main.sync(execute: operation)
}

private func primaryScreenHeight() -> CGFloat {
    NSScreen.screens.first?.frame.height ?? 0
}

/// A Cocoa rectangle (origin bottom left) as an Accessibility rectangle (origin top left).
private func accessibilityRect(fromCocoa rect: CGRect) -> CGRect {
    CGRect(x: rect.minX, y: primaryScreenHeight() - rect.maxY, width: rect.width, height: rect.height)
}

private func cocoaRect(fromAccessibility rect: CGRect) -> CGRect {
    CGRect(x: rect.minX, y: primaryScreenHeight() - rect.maxY, width: rect.width, height: rect.height)
}

private func axValue<T>(_ element: AXUIElement, _ attribute: String, as type: T.Type) -> T? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else { return nil }
    return value as? T
}

private func axPoint(_ element: AXUIElement) -> CGPoint? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &value) == .success,
          let value, CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero
    return AXValueGetValue(value as! AXValue, .cgPoint, &point) ? point : nil
}

private func axSize(_ element: AXUIElement) -> CGSize? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &value) == .success,
          let value, CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
    var size = CGSize.zero
    return AXValueGetValue(value as! AXValue, .cgSize, &size) ? size : nil
}

private func setAXPosition(_ element: AXUIElement, _ point: CGPoint) -> Bool {
    var point = point
    guard let value = AXValueCreate(.cgPoint, &point) else { return false }
    return AXUIElementSetAttributeValue(element, kAXPositionAttribute as CFString, value) == .success
}

private func setAXSize(_ element: AXUIElement, _ size: CGSize) -> Bool {
    var size = size
    guard let value = AXValueCreate(.cgSize, &size) else { return false }
    return AXUIElementSetAttributeValue(element, kAXSizeAttribute as CFString, value) == .success
}

private func focusedWindow(ofPID pid: pid_t) -> AXUIElement? {
    let application = AXUIElementCreateApplication(pid)
    // A hung app must not freeze OfficeKit's main thread for the default multi-second timeout.
    AXUIElementSetMessagingTimeout(application, 0.25)
    for attribute in [kAXFocusedWindowAttribute, kAXMainWindowAttribute] {
        var value: CFTypeRef?
        if AXUIElementCopyAttributeValue(application, attribute as CFString, &value) == .success,
           let value, CFGetTypeID(value) == AXUIElementGetTypeID() {
            return (value as! AXUIElement)
        }
    }
    return nil
}

/// Visible area (no menu bar or Dock) of every screen, in Accessibility coordinates.
private func visibleScreenAreas() -> [[String: Int]] {
    NSScreen.screens.map { screen in
        let rect = accessibilityRect(fromCocoa: screen.visibleFrame)
        return ["x": Int(rect.minX.rounded()), "y": Int(rect.minY.rounded()),
                "w": Int(rect.width.rounded()), "h": Int(rect.height.rounded())]
    }
}

/// Full frame of every screen, in the same order as `visibleScreenAreas`.
private func fullScreenFrames() -> [[String: Int]] {
    NSScreen.screens.map { screen in
        let rect = accessibilityRect(fromCocoa: screen.frame)
        return ["x": Int(rect.minX.rounded()), "y": Int(rect.minY.rounded()),
                "w": Int(rect.width.rounded()), "h": Int(rect.height.rounded())]
    }
}

private func copyOut(_ data: Data, _ output: UnsafeMutablePointer<UInt8>?, _ capacity: UInt64) -> Int64 {
    guard let output, UInt64(data.count) <= capacity else { return -3 }
    data.copyBytes(to: output, count: data.count)
    return Int64(data.count)
}

/// The focused window of the frontmost app as JSON, or a negative code:
/// -1 Accessibility not granted, -2 no usable window, -3 buffer too small.
@_cdecl("officekit_wm_focused")
public func officekitWindowFocused(_ output: UnsafeMutablePointer<UInt8>?, _ capacity: UInt64) -> Int64 {
    guard AXIsProcessTrusted() else { return -1 }
    return windowOnMainSync {
        guard let application = NSWorkspace.shared.frontmostApplication,
              let window = focusedWindow(ofPID: application.processIdentifier),
              let origin = axPoint(window), let size = axSize(window) else { return -2 }
        if axValue(window, kAXMinimizedAttribute, as: Bool.self) == true { return -2 }
        var settable = DarwinBoolean(false)
        AXUIElementIsAttributeSettable(window, kAXSizeAttribute as CFString, &settable)
        let fullscreen = axValue(window, "AXFullScreen", as: Bool.self) ?? false
        let payload: [String: Any] = [
            "pid": Int(application.processIdentifier),
            "bundleId": application.bundleIdentifier ?? "",
            "x": Int(origin.x.rounded()), "y": Int(origin.y.rounded()),
            "w": Int(size.width.rounded()), "h": Int(size.height.rounded()),
            "resizable": settable.boolValue,
            "fullscreen": fullscreen,
            "screens": visibleScreenAreas(),
            "frames": fullScreenFrames(),
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return -2 }
        return copyOut(data, output, capacity)
    }
}

/// Moves and resizes the focused window of `pid`.
/// 0 done, 1 Accessibility not granted, 2 no window, 3 the app refused.
@_cdecl("officekit_wm_set_frame")
public func officekitWindowSetFrame(_ pid: Int32, _ x: Double, _ y: Double, _ width: Double, _ height: Double) -> Int32 {
    guard AXIsProcessTrusted() else { return 1 }
    guard width >= 1, height >= 1, width < 100_000, height < 100_000, abs(x) < 1_000_000, abs(y) < 1_000_000 else { return 3 }
    // An AX call against OfficeKit's own window is served in-process by AppKit, which insists on the
    // main thread (NSWindow frame changes off it trap). Other apps' windows keep the caller's thread.
    if pid == ProcessInfo.processInfo.processIdentifier, !Thread.isMainThread {
        return windowOnMainSync { officekitWindowSetFrame(pid, x, y, width, height) }
    }
    guard let window = focusedWindow(ofPID: pid) else { return 2 }
    let target = CGRect(x: x, y: y, width: width, height: height)
    // Size, position, size: a window moved across displays is clamped to the old one's bounds
    // unless it is resized again after it lands.
    let resizedFirst = setAXSize(window, target.size)
    let moved = setAXPosition(window, target.origin)
    let resizedAgain = setAXSize(window, target.size)
    return (moved && (resizedFirst || resizedAgain)) ? 0 : 3
}

// MARK: - Drag to edge

private final class OfficeKitDragMonitor {
    static let shared = OfficeKitDragMonitor()
    var callback: (@convention(c) (Int32, Double, Double) -> Void)?
    private var monitors: [Any] = []

    private func report(_ kind: Int32) {
        let location = NSEvent.mouseLocation
        callback?(kind, Double(location.x), Double(primaryScreenHeight() - location.y))
    }

    func configure(enabled: Bool) {
        for monitor in monitors { NSEvent.removeMonitor(monitor) }
        monitors.removeAll()
        guard enabled else { return }
        let mask: NSEvent.EventTypeMask = [.leftMouseDown, .leftMouseDragged, .leftMouseUp]
        let handler: (NSEvent) -> Void = { [weak self] event in
            switch event.type {
            case .leftMouseDown: self?.report(0)
            case .leftMouseDragged: self?.report(1)
            case .leftMouseUp: self?.report(2)
            default: break
            }
        }
        if let global = NSEvent.addGlobalMonitorForEvents(matching: mask, handler: handler) { monitors.append(global) }
        if let local = NSEvent.addLocalMonitorForEvents(matching: mask, handler: { event in handler(event); return event }) {
            monitors.append(local)
        }
    }
}

@_cdecl("officekit_wm_drag_set_callback")
public func officekitWindowDragSetCallback(_ callback: @escaping @convention(c) (Int32, Double, Double) -> Void) {
    OfficeKitDragMonitor.shared.callback = callback
}

@_cdecl("officekit_wm_drag_configure")
public func officekitWindowDragConfigure(_ enabled: Int32) -> Int32 {
    windowOnMainSync { OfficeKitDragMonitor.shared.configure(enabled: enabled != 0) }
    return 0
}

private final class OfficeKitSnapPreview {
    static let shared = OfficeKitSnapPreview()
    private var window: NSWindow?

    private func makeWindow() -> NSWindow {
        let preview = NSWindow(contentRect: .zero, styleMask: .borderless, backing: .buffered, defer: false)
        preview.isOpaque = false
        preview.backgroundColor = .clear
        preview.hasShadow = false
        preview.ignoresMouseEvents = true
        preview.level = .statusBar
        preview.isReleasedWhenClosed = false
        preview.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle, .fullScreenAuxiliary]
        let view = NSView(frame: .zero)
        view.wantsLayer = true
        view.layer?.cornerRadius = 10
        view.layer?.backgroundColor = NSColor.controlAccentColor.withAlphaComponent(0.22).cgColor
        view.layer?.borderColor = NSColor.controlAccentColor.withAlphaComponent(0.8).cgColor
        view.layer?.borderWidth = 2
        preview.contentView = view
        return preview
    }

    func show(_ rect: CGRect) {
        let preview = window ?? makeWindow()
        window = preview
        preview.setFrame(cocoaRect(fromAccessibility: rect), display: true)
        preview.orderFrontRegardless()
    }

    func hide() {
        window?.orderOut(nil)
    }
}

/// Shows (visible != 0) or hides the translucent snap preview over `rect`.
@_cdecl("officekit_wm_preview")
public func officekitWindowPreview(_ visible: Int32, _ x: Double, _ y: Double, _ width: Double, _ height: Double) {
    windowOnMainSync {
        if visible != 0, width >= 1, height >= 1 {
            OfficeKitSnapPreview.shared.show(CGRect(x: x, y: y, width: width, height: height))
        } else {
            OfficeKitSnapPreview.shared.hide()
        }
    }
}
