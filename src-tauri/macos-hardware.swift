import CoreFoundation
import Darwin
import Foundation
import IOKit

// Read-only Apple Silicon hardware readings for the System Stats panels: CPU clock speed, power draw, the
// thermal state and fan speeds. Nothing needs administrator rights. IOReport and the SMC are undocumented
// system interfaces, so every function is resolved at run time, every value is range-checked, and anything
// that cannot be read is simply left out of the result instead of being guessed.

// MARK: Pure logic (unit tested)

/// States named like IDLE, DOWN or OFF are not running at a clock speed.
func hardwareIsActiveState(_ name: String) -> Bool {
    let upper = name.uppercased()
    return !(upper == "IDLE" || upper == "DOWN" || upper == "OFF" || upper.hasPrefix("NO_"))
}

/// The clock speed in MHz averaged over the time spent in each running state, or nil when the table and the
/// states do not line up one to one (a wrong table would give wrong numbers). A cluster that never ran sits
/// at its lowest speed.
func hardwareAverageFrequency(stateNames: [String], residencies: [Int64], table: [Double]) -> Double? {
    guard stateNames.count == residencies.count else { return nil }
    let active = stateNames.indices.filter { hardwareIsActiveState(stateNames[$0]) }
    let speeds = table.filter { $0 > 0 }
    guard !active.isEmpty, active.count == table.count, !speeds.isEmpty else { return nil }
    var weighted = 0.0
    var total = 0.0
    for (position, index) in active.enumerated() {
        let time = Double(max(0, residencies[index]))
        weighted += time * table[position]
        total += time
    }
    guard total > 0 else { return speeds.min() }
    let result = weighted / total
    return result.isFinite && result > 0 && result < 10_000 ? result : nil
}

/// Combines cluster speeds, each weighted by its core count.
func hardwareWeightedFrequency(_ parts: [(mhz: Double, cores: Int)]) -> Double? {
    let usable = parts.filter { $0.mhz > 0 && $0.cores > 0 }
    let cores = usable.reduce(0) { $0 + $1.cores }
    guard cores > 0 else { return nil }
    return usable.reduce(0.0) { $0 + $1.mhz * Double($1.cores) } / Double(cores)
}

/// Watts from an energy counter delta over a time window. The unit label is the counter's own (mJ, uJ, nJ).
func hardwarePowerWatts(energy: Int64, unit: String, seconds: Double) -> Double? {
    guard energy > 0, seconds > 0 else { return nil }
    let divisor: Double
    switch unit.trimmingCharacters(in: .whitespaces) {
    case "mJ": divisor = 1e3
    case "uJ": divisor = 1e6
    case "nJ": divisor = 1e9
    default: return nil
    }
    let watts = Double(energy) / seconds / divisor
    return watts.isFinite && watts > 0 && watts < 500 ? watts : nil
}

func hardwareThermalName(_ state: ProcessInfo.ThermalState) -> String {
    switch state {
    case .nominal: return "nominal"
    case .fair: return "fair"
    case .serious: return "serious"
    case .critical: return "critical"
    @unknown default: return "nominal"
    }
}

/// A little-endian IEEE float from the SMC's four data bytes, or nil outside the range given.
func hardwareSMCFloat(_ bytes: [UInt8], within range: ClosedRange<Double>) -> Double? {
    guard bytes.count >= 4 else { return nil }
    let bits = UInt32(bytes[0]) | UInt32(bytes[1]) << 8 | UInt32(bytes[2]) << 16 | UInt32(bytes[3]) << 24
    let value = Double(Float(bitPattern: bits))
    return value.isFinite && range.contains(value) ? value : nil
}

/// A four-character SMC key as the number the SMC expects.
func hardwareSMCKey(_ text: String) -> UInt32? {
    let scalars = Array(text.utf8)
    guard scalars.count == 4 else { return nil }
    return scalars.reduce(UInt32(0)) { $0 << 8 | UInt32($1) }
}

/// The frequency table in MHz from a power-manager voltage-states blob: 8-byte entries, the first four bytes a
/// frequency in hertz (or kilohertz on newer chips). Entries that are not a plausible speed are dropped to 0.
func hardwareFrequencyTable(_ data: Data) -> [Double] {
    var table: [Double] = []
    var offset = 0
    while offset + 8 <= data.count, table.count < 64 {
        let raw = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: offset, as: UInt32.self) }
        let mhz = raw >= 100_000_000 ? Double(raw) / 1e6 : raw >= 100_000 ? Double(raw) / 1e3 : 0
        table.append(mhz > 0 && mhz < 10_000 ? mhz : 0)
        offset += 8
    }
    return table
}

// MARK: Readings

public struct OfficeKitHardwareReading {
    var thermal = "nominal"
    var efficiencyMHz: Double?
    var performanceMHz: Double?
    var allMHz: Double?
    var gpuWatts: Double?
    var cpuWatts: Double?
    var systemWatts: Double?
    var fans: [(name: String, rpm: Int)] = []
}

private typealias IOReportCopyInGroup = @convention(c) (CFString?, CFString?, UInt64, UInt64, UInt64) -> Unmanaged<CFMutableDictionary>?
private typealias IOReportMerge = @convention(c) (CFMutableDictionary, CFDictionary, UnsafeRawPointer?) -> Void
private typealias IOReportCreateSub = @convention(c) (UnsafeRawPointer?, CFMutableDictionary, UnsafeMutablePointer<Unmanaged<CFMutableDictionary>?>, UInt64, UnsafeRawPointer?) -> UnsafeRawPointer?
private typealias IOReportCreateSamples = @convention(c) (UnsafeRawPointer, CFMutableDictionary, UnsafeRawPointer?) -> Unmanaged<CFDictionary>?
private typealias IOReportCreateDelta = @convention(c) (CFDictionary, CFDictionary, UnsafeRawPointer?) -> Unmanaged<CFDictionary>?
private typealias IOReportString = @convention(c) (CFDictionary) -> Unmanaged<CFString>?
private typealias IOReportSimple = @convention(c) (CFDictionary, Int32) -> Int64
private typealias IOReportStateCount = @convention(c) (CFDictionary) -> Int32
private typealias IOReportStateName = @convention(c) (CFDictionary, Int32) -> Unmanaged<CFString>?
private typealias IOReportStateResidency = @convention(c) (CFDictionary, Int32) -> Int64

private final class OfficeKitIOReport {
    private let copyInGroup: IOReportCopyInGroup
    private let merge: IOReportMerge
    private let createSub: IOReportCreateSub
    private let createSamples: IOReportCreateSamples
    private let createDelta: IOReportCreateDelta
    private let channelGroup: IOReportString
    private let channelName: IOReportString
    private let channelUnit: IOReportString
    private let simple: IOReportSimple
    private let stateCount: IOReportStateCount
    private let stateName: IOReportStateName
    private let stateResidency: IOReportStateResidency
    private let subscription: UnsafeRawPointer
    private let channels: CFMutableDictionary
    private var previous: (sample: CFDictionary, at: Date)?

    init?() {
        guard let library = dlopen("/usr/lib/libIOReport.dylib", RTLD_LAZY) else { return nil }
        func load<T>(_ name: String, _ type: T.Type) -> T? {
            guard let symbol = dlsym(library, name) else { return nil }
            return unsafeBitCast(symbol, to: type)
        }
        guard let copyInGroup = load("IOReportCopyChannelsInGroup", IOReportCopyInGroup.self),
              let merge = load("IOReportMergeChannels", IOReportMerge.self),
              let createSub = load("IOReportCreateSubscription", IOReportCreateSub.self),
              let createSamples = load("IOReportCreateSamples", IOReportCreateSamples.self),
              let createDelta = load("IOReportCreateSamplesDelta", IOReportCreateDelta.self),
              let channelGroup = load("IOReportChannelGetGroup", IOReportString.self),
              let channelName = load("IOReportChannelGetChannelName", IOReportString.self),
              let channelUnit = load("IOReportChannelGetUnitLabel", IOReportString.self),
              let simple = load("IOReportSimpleGetIntegerValue", IOReportSimple.self),
              let stateCount = load("IOReportStateGetCount", IOReportStateCount.self),
              let stateName = load("IOReportStateGetNameForIndex", IOReportStateName.self),
              let stateResidency = load("IOReportStateGetResidency", IOReportStateResidency.self),
              let energy = copyInGroup("Energy Model" as CFString, nil, 0, 0, 0)?.takeRetainedValue() else { return nil }
        for group in ["CPU Stats", "GPU Stats"] {
            if let more = copyInGroup(group as CFString, nil, 0, 0, 0)?.takeRetainedValue() { merge(energy, more, nil) }
        }
        var system: Unmanaged<CFMutableDictionary>?
        guard let subscription = createSub(nil, energy, &system, 0, nil) else { return nil }
        self.copyInGroup = copyInGroup; self.merge = merge; self.createSub = createSub
        self.createSamples = createSamples; self.createDelta = createDelta
        self.channelGroup = channelGroup; self.channelName = channelName; self.channelUnit = channelUnit
        self.simple = simple; self.stateCount = stateCount; self.stateName = stateName; self.stateResidency = stateResidency
        self.subscription = subscription
        self.channels = energy
    }

    private func sample() -> CFDictionary? { createSamples(subscription, channels, nil)?.takeRetainedValue() }

    /// The change between two samples and the seconds it covers. A stale or missing first sample is replaced by a
    /// short fresh window, so the first reading after a long gap is not an average over minutes.
    func window() -> (delta: CFDictionary, seconds: Double)? {
        var start = previous
        if start == nil || Date().timeIntervalSince(start!.at) > 5 {
            guard let first = sample() else { return nil }
            start = (first, Date())
            Thread.sleep(forTimeInterval: 0.15)
        }
        guard let first = start, let now = sample() else { return nil }
        let at = Date()
        previous = (now, at)
        let seconds = at.timeIntervalSince(first.at)
        guard seconds > 0.05, let delta = createDelta(first.sample, now, nil)?.takeRetainedValue() else { return nil }
        return (delta, seconds)
    }

    func channelItems(_ delta: CFDictionary) -> [CFDictionary] {
        ((delta as NSDictionary)["IOReportChannels"] as? [NSDictionary] ?? []).prefix(2048).map { $0 as CFDictionary }
    }

    func name(_ item: CFDictionary) -> String { channelName(item)?.takeUnretainedValue() as String? ?? "" }
    func group(_ item: CFDictionary) -> String { channelGroup(item)?.takeUnretainedValue() as String? ?? "" }
    func unit(_ item: CFDictionary) -> String { channelUnit(item)?.takeUnretainedValue() as String? ?? "" }
    func integer(_ item: CFDictionary) -> Int64 { simple(item, 0) }

    func states(_ item: CFDictionary) -> (names: [String], residencies: [Int64]) {
        let count = min(Int(stateCount(item)), 64)
        var names: [String] = []
        var residencies: [Int64] = []
        for index in 0..<max(0, count) {
            names.append(stateName(item, Int32(index))?.takeUnretainedValue() as String? ?? "")
            residencies.append(stateResidency(item, Int32(index)))
        }
        return (names, residencies)
    }
}

private func officeKitLoadFrequencyTables() -> (efficiency: [Double], performance: [Double]) {
    var efficiency: [Double] = []
    var performance: [Double] = []
    var iterator: io_iterator_t = 0
    guard IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("AppleARMIODevice"), &iterator) == KERN_SUCCESS else { return ([], []) }
    defer { IOObjectRelease(iterator) }
    while case let entry = IOIteratorNext(iterator), entry != 0 {
        defer { IOObjectRelease(entry) }
        var nameBuffer = [CChar](repeating: 0, count: 128)
        guard IORegistryEntryGetName(entry, &nameBuffer) == KERN_SUCCESS, String(cString: nameBuffer) == "pmgr" else { continue }
        var properties: Unmanaged<CFMutableDictionary>?
        guard IORegistryEntryCreateCFProperties(entry, &properties, kCFAllocatorDefault, 0) == KERN_SUCCESS,
              let dictionary = properties?.takeRetainedValue() as NSDictionary? else { continue }
        func table(_ keys: [String]) -> [Double] {
            for key in keys {
                if let data = dictionary[key] as? Data {
                    let parsed = hardwareFrequencyTable(data)
                    if parsed.contains(where: { $0 > 0 }) { return parsed }
                }
            }
            return []
        }
        efficiency = table(["voltage-states1-sram", "voltage-states9-sram"])
        performance = table(["voltage-states5-sram"])
    }
    return (efficiency, performance)
}

private let officeKitHardwareLock = NSLock()
private let officeKitIOReport = OfficeKitIOReport()
private let officeKitFrequencyTables = officeKitLoadFrequencyTables()

// MARK: SMC (fan speed and system power)

private final class OfficeKitSMC {
    private var connection: io_connect_t = 0
    private static let structSize = 80

    init?() {
        let service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("AppleSMC"))
        guard service != 0 else { return nil }
        defer { IOObjectRelease(service) }
        guard IOServiceOpen(service, mach_task_self_, 0, &connection) == KERN_SUCCESS else { return nil }
    }

    deinit { if connection != 0 { IOServiceClose(connection) } }

    private func call(_ input: [UInt8]) -> [UInt8]? {
        var output = [UInt8](repeating: 0, count: Self.structSize)
        var outputSize = Self.structSize
        let status = input.withUnsafeBytes { source in
            output.withUnsafeMutableBytes { target in
                IOConnectCallStructMethod(connection, 2, source.baseAddress, Self.structSize, target.baseAddress, &outputSize)
            }
        }
        return status == KERN_SUCCESS && output[40] == 0 ? output : nil
    }

    /// The raw bytes and four-character type of one key, or nil when the Mac does not have it.
    func read(_ key: String) -> (bytes: [UInt8], type: String)? {
        guard let code = hardwareSMCKey(key) else { return nil }
        var request = [UInt8](repeating: 0, count: Self.structSize)
        // The request and reply are a C struct of host-order integers, so on Apple Silicon the key goes in
        // little-endian and a four-character type comes back reversed.
        for shift in 0..<4 { request[shift] = UInt8((code >> UInt32(8 * shift)) & 0xff) }
        request[42] = 9
        guard let info = call(request) else { return nil }
        let size = Int(UInt32(info[28]) | UInt32(info[29]) << 8 | UInt32(info[30]) << 16 | UInt32(info[31]) << 24)
        guard size > 0, size <= 32 else { return nil }
        request[28] = UInt8(size & 0xff); request[29] = 0; request[30] = 0; request[31] = 0
        request[42] = 5
        guard let value = call(request) else { return nil }
        let type = String(bytes: Array(info[32..<36].reversed()), encoding: .ascii) ?? ""
        return (Array(value[48..<(48 + size)]), type)
    }

    func float(_ key: String, within range: ClosedRange<Double>) -> Double? {
        guard let reading = read(key), reading.type == "flt " else { return nil }
        return hardwareSMCFloat(reading.bytes, within: range)
    }

    func count(_ key: String) -> Int? {
        guard let reading = read(key), reading.type == "ui8 ", let first = reading.bytes.first else { return nil }
        return Int(first)
    }
}

private let officeKitSMC = OfficeKitSMC()

private func officeKitReading() -> OfficeKitHardwareReading {
    var reading = OfficeKitHardwareReading()
    reading.thermal = hardwareThermalName(ProcessInfo.processInfo.thermalState)
    if let report = officeKitIOReport, let window = report.window() {
        var efficiency: Double?
        var performance: [Double] = []
        for item in report.channelItems(window.delta) {
            let name = report.name(item)
            let group = report.group(item)
            if group == "CPU Stats" {
                let states = report.states(item)
                if name == "ECPU" {
                    efficiency = hardwareAverageFrequency(stateNames: states.names, residencies: states.residencies, table: officeKitFrequencyTables.efficiency)
                } else if name.hasPrefix("PCPU"), Int(name.dropFirst(4)) != nil || name == "PCPU" {
                    if let mhz = hardwareAverageFrequency(stateNames: states.names, residencies: states.residencies, table: officeKitFrequencyTables.performance) { performance.append(mhz) }
                }
            } else if group == "Energy Model" {
                let watts = hardwarePowerWatts(energy: report.integer(item), unit: report.unit(item), seconds: window.seconds)
                if name == "GPU Energy" { reading.gpuWatts = watts } else if name == "CPU Energy" { reading.cpuWatts = watts }
            }
        }
        reading.efficiencyMHz = efficiency
        if !performance.isEmpty { reading.performanceMHz = performance.reduce(0, +) / Double(performance.count) }
        var cores: [(mhz: Double, cores: Int)] = []
        var levels: (performance: Int32, efficiency: Int32) = (0, 0)
        var size = MemoryLayout<Int32>.size
        sysctlbyname("hw.perflevel0.logicalcpu", &levels.performance, &size, nil, 0)
        size = MemoryLayout<Int32>.size
        sysctlbyname("hw.perflevel1.logicalcpu", &levels.efficiency, &size, nil, 0)
        if let mhz = reading.efficiencyMHz { cores.append((mhz, Int(levels.efficiency))) }
        if let mhz = reading.performanceMHz { cores.append((mhz, Int(levels.performance))) }
        reading.allMHz = hardwareWeightedFrequency(cores)
    }
    if let smc = officeKitSMC {
        reading.systemWatts = smc.float("PSTR", within: 0.1...500)
        if let fans = smc.count("FNum"), fans > 0 {
            for index in 0..<min(fans, 4) {
                if let rpm = smc.float("F\(index)Ac", within: 0...20_000) {
                    reading.fans.append((fans == 2 ? (index == 0 ? "Left fan" : "Right fan") : "Fan \(index + 1)", Int(rpm.rounded())))
                }
            }
        }
    }
    return reading
}

private func officeKitJSON(_ reading: OfficeKitHardwareReading) -> String {
    func number(_ value: Double?, digits: Int) -> Any {
        guard let value else { return NSNull() }
        let scale = pow(10.0, Double(digits))
        return (value * scale).rounded() / scale
    }
    var object: [String: Any] = ["thermal_state": reading.thermal]
    if reading.efficiencyMHz != nil || reading.performanceMHz != nil || reading.allMHz != nil {
        object["cpu_frequency_mhz"] = ["efficiency": number(reading.efficiencyMHz, digits: 0),
                                       "performance": number(reading.performanceMHz, digits: 0),
                                       "all": number(reading.allMHz, digits: 0)]
    }
    if reading.gpuWatts != nil || reading.cpuWatts != nil || reading.systemWatts != nil {
        object["power_w"] = ["cpu": number(reading.cpuWatts, digits: 1), "gpu": number(reading.gpuWatts, digits: 1), "system": number(reading.systemWatts, digits: 1)]
    }
    if !reading.fans.isEmpty { object["fans"] = reading.fans.map { ["name": $0.name, "rpm": $0.rpm] } }
    let data = (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])) ?? Data("{}".utf8)
    return String(data: data, encoding: .utf8) ?? "{}"
}

/// Writes one JSON object of bounded readings into `buffer` and returns its length, or -1 when it does not fit.
@_cdecl("officekit_macos_hardware_read")
public func officeKitMacOSHardwareRead(_ buffer: UnsafeMutablePointer<CChar>?, _ capacity: Int32) -> Int32 {
    guard let buffer, capacity > 1 else { return -1 }
    officeKitHardwareLock.lock()
    defer { officeKitHardwareLock.unlock() }
    let bytes = Array(officeKitJSON(officeKitReading()).utf8)
    guard bytes.count < Int(capacity) else { return -1 }
    for (index, byte) in bytes.enumerated() { buffer[index] = CChar(bitPattern: byte) }
    buffer[bytes.count] = 0
    return Int32(bytes.count)
}
