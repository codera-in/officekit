import Foundation
import CoreMotion

// Core Motion keeps samples only in memory. No microphone, camera, or storage access.
@available(macOS 14.0, *)
private final class OfficeKitHeadphoneMotion: NSObject, CMHeadphoneMotionManagerDelegate {
    static let shared = OfficeKitHeadphoneMotion()
    private lazy var manager = CMHeadphoneMotionManager()
    private let lock = NSLock()
    private var enabled = false
    private var generation: UInt64 = 0
    private var connectionEpoch: UInt64 = 0
    private var status: Int32 = 0
    private var pitch = 0.0
    private var roll = 0.0
    private var speed = 0.0
    private var timestamp = 0.0

    private func clear(_ next: Int32) {
        lock.lock()
        status = next
        pitch = 0; roll = 0; speed = 0; timestamp = 0
        lock.unlock()
    }

    // Called on main; never synchronously dispatches to main from an FFI call.
    func action(_ action: Int32) {
        if action == 0 {
            enabled = false
            generation += 1
            manager.stopDeviceMotionUpdates()
            manager.stopConnectionStatusUpdates()
            clear(0)
            return
        }
        if action == 2 { return } // Rust owns calibration, not the native sensor.
        if enabled { return }
        guard Bundle.main.object(forInfoDictionaryKey: "NSMotionUsageDescription") != nil else {
            clear(7)
            return
        }
        let authorization = CMHeadphoneMotionManager.authorizationStatus()
        guard authorization != .denied && authorization != .restricted else {
            clear(2)
            return
        }
        enabled = true
        generation += 1
        manager.delegate = self
        manager.startConnectionStatusUpdates()
        startSamples()
    }

    private func startSamples() {
        guard enabled else { return }
        guard manager.isDeviceMotionAvailable else { clear(3); return }
        let authorization = CMHeadphoneMotionManager.authorizationStatus()
        let currentGeneration = generation
        clear(authorization == .notDetermined ? 1 : 6)
        // Starting updates is the platform permission request, only after explicit enable.
        manager.startDeviceMotionUpdates(to: .main) { [weak self] motion, error in
            guard let self, self.enabled, self.generation == currentGeneration else { return }
            let authorization = CMHeadphoneMotionManager.authorizationStatus()
            if authorization == .denied || authorization == .restricted {
                self.enabled = false
                self.clear(2)
                return
            }
            guard error == nil, let motion else {
                self.enabled = false
                self.clear(7)
                return
            }
            self.lock.lock()
            self.pitch = motion.attitude.pitch
            self.roll = motion.attitude.roll
            let rate = motion.rotationRate
            self.speed = sqrt(rate.x * rate.x + rate.y * rate.y + rate.z * rate.z)
            self.timestamp = motion.timestamp
            self.status = 4
            self.lock.unlock()
        }
    }

    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.generation += 1
            self.manager.stopDeviceMotionUpdates()
            self.lock.lock()
            self.connectionEpoch += 1
            self.lock.unlock()
            self.clear(self.enabled ? 6 : 0)
        }
    }

    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.enabled else { return }
            self.startSamples()
        }
    }

    func snapshot(_ pitchOut: UnsafeMutablePointer<Double>, _ rollOut: UnsafeMutablePointer<Double>,
                  _ speedOut: UnsafeMutablePointer<Double>, _ timestampOut: UnsafeMutablePointer<Double>,
                  _ nowOut: UnsafeMutablePointer<Double>, _ generationOut: UnsafeMutablePointer<UInt64>) -> Int32 {
        lock.lock()
        defer { lock.unlock() }
        pitchOut.pointee = pitch; rollOut.pointee = roll; speedOut.pointee = speed
        timestampOut.pointee = timestamp
        nowOut.pointee = ProcessInfo.processInfo.systemUptime
        generationOut.pointee = connectionEpoch
        return status
    }
}

@_cdecl("officekit_headphone_motion_action")
func officekitHeadphoneMotionAction(_ action: Int32) {
    guard #available(macOS 14.0, *) else { return }
    if Thread.isMainThread { OfficeKitHeadphoneMotion.shared.action(action) }
    else { DispatchQueue.main.async { OfficeKitHeadphoneMotion.shared.action(action) } }
}

@_cdecl("officekit_headphone_motion_snapshot")
func officekitHeadphoneMotionSnapshot(_ pitch: UnsafeMutablePointer<Double>, _ roll: UnsafeMutablePointer<Double>,
                                     _ speed: UnsafeMutablePointer<Double>, _ timestamp: UnsafeMutablePointer<Double>,
                                     _ now: UnsafeMutablePointer<Double>, _ generation: UnsafeMutablePointer<UInt64>) -> Int32 {
    guard #available(macOS 14.0, *) else { return 3 }
    return OfficeKitHeadphoneMotion.shared.snapshot(pitch, roll, speed, timestamp, now, generation)
}
