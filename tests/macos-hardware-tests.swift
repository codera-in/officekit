import Foundation

@main
struct MacOSHardwareTests {
    static func main() {
        // Which states count as running at a clock speed.
        require(hardwareIsActiveState("V3P11") && hardwareIsActiveState("P3"), "Voltage and performance states are active")
        require(!hardwareIsActiveState("IDLE") && !hardwareIsActiveState("down") && !hardwareIsActiveState("OFF") && !hardwareIsActiveState("NO_CLTM"), "Idle, down and off states are not")

        // Average clock speed: weighted by time in each running state.
        let names = ["IDLE", "V0P2", "V1P1", "V2P0"]
        let table = [600.0, 1200.0, 2400.0]
        require(hardwareAverageFrequency(stateNames: names, residencies: [50, 100, 100, 0], table: table) == 900, "Equal time at two speeds averages them")
        require(hardwareAverageFrequency(stateNames: names, residencies: [999, 0, 0, 100], table: table) == 2400, "Idle time does not drag the speed down")
        require(hardwareAverageFrequency(stateNames: names, residencies: [100, 0, 0, 0], table: table) == 600, "A cluster that never ran reports its lowest speed")
        require(hardwareAverageFrequency(stateNames: names, residencies: [1, 1], table: table) == nil, "Mismatched state and residency counts are refused")
        require(hardwareAverageFrequency(stateNames: names, residencies: [1, 1, 1, 1], table: [600, 1200]) == nil, "A table that does not line up with the states is refused")
        require(hardwareAverageFrequency(stateNames: ["IDLE"], residencies: [1], table: []) == nil, "No table, no speed")
        require(hardwareAverageFrequency(stateNames: names, residencies: [0, -5, 10, 10], table: table) == 1800, "Negative residency counts as zero")
        require(hardwareAverageFrequency(stateNames: ["V0"], residencies: [1], table: [50_000]) == nil, "An impossible speed is refused")

        // All cores: clusters weighted by core count.
        require(hardwareWeightedFrequency([(mhz: 1000, cores: 2), (mhz: 3000, cores: 6)]) == 2500, "Clusters are weighted by core count")
        require(hardwareWeightedFrequency([(mhz: 0, cores: 2), (mhz: 3000, cores: 0)]) == nil, "Nothing usable gives no speed")

        // Power.
        require(hardwarePowerWatts(energy: 2000, unit: "mJ", seconds: 1) == 2, "Millijoules over a second are milliwatts")
        require(abs((hardwarePowerWatts(energy: 200_079_400, unit: "nJ", seconds: 1) ?? 0) - 0.2) < 0.001, "Nanojoules convert to watts")
        require(hardwarePowerWatts(energy: 0, unit: "mJ", seconds: 1) == nil && hardwarePowerWatts(energy: 5, unit: "mJ", seconds: 0) == nil, "No energy or no time gives no reading")
        require(hardwarePowerWatts(energy: 5, unit: "bananas", seconds: 1) == nil, "Unknown units are refused")
        require(hardwarePowerWatts(energy: 9_000_000, unit: "mJ", seconds: 1) == nil, "Impossible power is refused")

        // SMC helpers.
        require(hardwareSMCKey("FNum") == 0x464E756D, "SMC keys are four characters packed big-endian")
        require(hardwareSMCKey("PST") == nil && hardwareSMCKey("PSTRX") == nil, "Other lengths are refused")
        let fifteenHundred: [UInt8] = [0x00, 0x80, 0xBB, 0x44]
        require(hardwareSMCFloat(fifteenHundred, within: 0...20_000) == 1500, "A little-endian float decodes")
        require(hardwareSMCFloat(fifteenHundred, within: 0...1000) == nil && hardwareSMCFloat([0, 0], within: 0...10) == nil, "Out of range or short data is refused")
        require(hardwareSMCFloat([0x00, 0x00, 0xC0, 0x7F], within: 0...10) == nil, "NaN is refused")

        // Frequency table blob: hertz and kilohertz entries, junk dropped.
        var blob = Data()
        for value: UInt32 in [600_000_000, 0, 3_228_000, 5] {
            var little = value.littleEndian
            blob.append(Data(bytes: &little, count: 4))
            blob.append(Data(count: 4))
        }
        require(hardwareFrequencyTable(blob) == [600, 0, 3228, 0], "Hertz and kilohertz entries become MHz and junk becomes zero")

        // The live reader returns bounded JSON or reports it does not fit.
        var buffer = [CChar](repeating: 0, count: 2048)
        let length = officeKitMacOSHardwareRead(&buffer, Int32(buffer.count))
        require(length > 1, "The hardware reader produces a result")
        let json = String(cString: buffer)
        guard let object = (try? JSONSerialization.jsonObject(with: Data(json.utf8))) as? [String: Any] else {
            fputs("FAIL: The hardware result is a JSON object: \(json)\n", stderr)
            exit(1)
        }
        require(["nominal", "fair", "serious", "critical"].contains(object["thermal_state"] as? String ?? ""), "The thermal state is one of the four names")
        if let frequency = object["cpu_frequency_mhz"] as? [String: Any] {
            for case let value as Double in frequency.values { require(value > 0 && value < 10_000, "Clock speeds are plausible") }
        }
        if let fans = object["fans"] as? [[String: Any]] {
            require(fans.count <= 4 && fans.allSatisfy { ($0["rpm"] as? Int ?? -1) >= 0 }, "Fan speeds are bounded")
        }
        require(officeKitMacOSHardwareRead(&buffer, 4) == -1, "A buffer that is too small is reported, not overrun")
        print("Hardware reading: \(json)")
    }
}

private func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else {
        fputs("FAIL: \(message)\n", stderr)
        exit(1)
    }
}
