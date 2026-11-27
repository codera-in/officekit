import Foundation

private var readings: [(String, Double)] = []

private let collect: OfficeKitSensorCallback = { _, name, value in
    guard let name, let sensorName = String(validatingUTF8: name) else { return }
    readings.append((sensorName, value))
}

@main
struct MacOSSensorTests {
    static func main() {
        let result = officeKitMacOSSensorRead(collect, nil)
        require(result >= -1, "Sensor reader returns a documented count or unsupported status")
        require(result != -1 || readings.isEmpty, "Unsupported IOKit symbols return no sensor readings")
        require(readings.count <= 16, "Sensor results stay bounded")
        require(readings.allSatisfy { !$0.0.isEmpty && $0.0.utf8.count <= 60 && $0.1.isFinite && $0.1 > 0 && $0.1 <= 150 }, "Sensor results have bounded names and temperatures")
        if readings.isEmpty {
            print("No HID temperature readings available on this Mac; provider remains optional.")
        } else {
            print("Read \(readings.count) HID temperature sensors.")
        }
    }
}

private func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else {
        fputs("FAIL: \(message)\n", stderr)
        exit(1)
    }
}
