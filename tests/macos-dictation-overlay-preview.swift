import AppKit
import Foundation

// Manual native visual check: no microphone capture, clipboard access or audio fixture.
@main
struct DictationOverlayPreview {
    static func main() {
        let application = NSApplication.shared
        application.setActivationPolicy(.accessory)
        let focusedPID = NSWorkspace.shared.frontmostApplication?.processIdentifier
        let generation = officekitDictationOverlayBegin()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
            guard let panel = application.windows.first(where: { $0.frame.width == 320 }) else { fatalError("Overlay did not appear") }
            precondition(!panel.canBecomeKey && !panel.canBecomeMain, "Overlay must never take keyboard focus")
            precondition(panel.isVisible, "Overlay must be visible")
            precondition(NSWorkspace.shared.frontmostApplication?.processIdentifier == focusedPID, "Focused app changed")
            print("Overlay visible; target focus preserved")
            print("Overlay window: \(panel.windowNumber), frame: \(panel.frame)")
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 12) {
            officekitDictationOverlayProcessing(generation)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 24) {
            officekitDictationOverlayCancel()
            precondition(officekitDictationOverlayValid(generation) == 0)
            print("Overlay cancellation invalidated session")
            application.stop(nil)
            let event = NSEvent.otherEvent(with: .applicationDefined, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil, subtype: 0, data1: 0, data2: 0)!
            application.postEvent(event, atStart: false)
        }
        application.run()
    }
}
