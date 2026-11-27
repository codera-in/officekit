import CoreFoundation
import Darwin
import Foundation

private typealias OfficeKitHIDCreate = @convention(c) (CFAllocator?) -> UnsafeMutableRawPointer?
private typealias OfficeKitHIDCopyServices = @convention(c) (UnsafeMutableRawPointer) -> Unmanaged<CFArray>?
private typealias OfficeKitHIDConforms = @convention(c) (UnsafeMutableRawPointer, UInt32, UInt32) -> Int32
private typealias OfficeKitHIDCopyProperty = @convention(c) (UnsafeMutableRawPointer, CFString) -> Unmanaged<CFTypeRef>?
private typealias OfficeKitHIDCopyEvent = @convention(c) (UnsafeMutableRawPointer, Int64, UInt64, UInt32) -> Unmanaged<CFTypeRef>?
private typealias OfficeKitHIDEventValue = @convention(c) (UnsafeMutableRawPointer, Int64) -> Double
public typealias OfficeKitSensorCallback = @convention(c) (UnsafeMutableRawPointer?, UnsafePointer<CChar>?, Double) -> Void

private enum OfficeKitTemperatureReader {
    static let lock = NSLock()
    static let ioKit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_LAZY)
    static let create = function("IOHIDEventSystemClientCreate", as: OfficeKitHIDCreate.self)
    static let copyServices = function("IOHIDEventSystemClientCopyServices", as: OfficeKitHIDCopyServices.self)
    static let conforms = function("IOHIDServiceClientConformsTo", as: OfficeKitHIDConforms.self)
    static let copyProperty = function("IOHIDServiceClientCopyProperty", as: OfficeKitHIDCopyProperty.self)
    static let copyEvent = function("IOHIDServiceClientCopyEvent", as: OfficeKitHIDCopyEvent.self)
    static let eventValue = function("IOHIDEventGetFloatValue", as: OfficeKitHIDEventValue.self)
    static let client = create?(kCFAllocatorDefault)

    private static func function<T>(_ name: String, as type: T.Type) -> T? {
        guard let ioKit, let symbol = dlsym(ioKit, name) else { return nil }
        return unsafeBitCast(symbol, to: type)
    }

    static func read(_ callback: OfficeKitSensorCallback, context: UnsafeMutableRawPointer?) -> Int32 {
        lock.lock()
        defer { lock.unlock() }
        guard let client, let copyServices, let conforms, let copyProperty, let copyEvent, let eventValue,
              let services = copyServices(client)?.takeRetainedValue() else { return -1 }

        var emitted: Int32 = 0
        let count = min(CFArrayGetCount(services), 512)
        for index in 0..<count where emitted < 16 {
            guard let service = CFArrayGetValueAtIndex(services, index) else { continue }
            let servicePointer = UnsafeMutableRawPointer(mutating: service)
            guard conforms(servicePointer, 0xff00, 0x0005) != 0,
                  let rawProduct = copyProperty(servicePointer, "Product" as CFString)?.takeRetainedValue() else { continue }

            let product = rawProduct as? String
            let name = product?.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let name, !name.isEmpty, name.utf8.count <= 60,
                  !name.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains),
                  let rawEvent = copyEvent(servicePointer, 15, 0, 0) else { continue }
            defer { rawEvent.release() }
            let value = eventValue(rawEvent.toOpaque(), Int64(15 << 16))
            guard value.isFinite, value > 0, value <= 150 else { continue }
            name.withCString { callback(context, $0, value) }
            emitted += 1
        }
        return emitted
    }
}

/// Streams bounded Apple Silicon HID temperature values to the local metrics bridge.
/// The private event functions are resolved dynamically so older macOS releases without
/// these symbols safely return no readings instead of failing app startup.
@_cdecl("officekit_macos_sensor_read")
public func officeKitMacOSSensorRead(_ callback: OfficeKitSensorCallback, _ context: UnsafeMutableRawPointer?) -> Int32 {
    OfficeKitTemperatureReader.read(callback, context: context)
}
