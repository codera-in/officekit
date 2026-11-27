import CoreGraphics
import Foundation

// Aggregate idle time only. No event tap is installed and no key contents are read.
@_cdecl("officekit_user_activity_idle_seconds")
func officekitUserActivityIdleSeconds() -> Double {
    let idle = CGEventSource.secondsSinceLastEventType(
        .combinedSessionState,
        eventType: CGEventType(rawValue: UInt32.max)!
    )
    return idle.isFinite && idle >= 0 ? idle : Double.infinity
}
