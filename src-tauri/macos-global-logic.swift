import Foundation

// Pure logic for the global desktop layer. Foundation only, so the same file compiles into the
// app and into the Swift test binary without AppKit or Carbon.

/// Modifier bits shared with the Rust settings and the dictation shortcut editor:
/// 1 control, 2 option, 4 shift, 8 command.
let globalModifierControl: UInt8 = 0b0001
let globalModifierOption: UInt8 = 0b0010
let globalModifierShift: UInt8 = 0b0100
let globalModifierCommand: UInt8 = 0b1000

private let globalCarbonCommand: UInt32 = 1 << 8
private let globalCarbonShift: UInt32 = 1 << 9
private let globalCarbonOption: UInt32 = 1 << 11
private let globalCarbonControl: UInt32 = 1 << 12

private let globalFunctionKeyCodes: Set<UInt16> = [105, 107, 113, 106, 64, 79, 80, 90]

/// Carbon `RegisterEventHotKey` modifier flags for a modifier mask, or nil for an invalid mask.
func globalCarbonModifiers(forMask mask: UInt8) -> UInt32? {
    guard mask & ~0b1111 == 0 else { return nil }
    var flags: UInt32 = 0
    if mask & globalModifierControl != 0 { flags |= globalCarbonControl }
    if mask & globalModifierOption != 0 { flags |= globalCarbonOption }
    if mask & globalModifierShift != 0 { flags |= globalCarbonShift }
    if mask & globalModifierCommand != 0 { flags |= globalCarbonCommand }
    return flags
}

/// A global shortcut needs a modifier, except the F13 to F20 keys, and a real key code.
func globalShortcutIsRegistrable(keyCode: Int32, modifierMask: Int32) -> Bool {
    guard (0...127).contains(keyCode), (0...15).contains(modifierMask) else { return false }
    return modifierMask != 0 || globalFunctionKeyCodes.contains(UInt16(keyCode))
}

/// True when any two bindings use the same key and modifiers.
func globalShortcutsConflict(_ bindings: [(keyCode: Int32, modifierMask: Int32)]) -> Bool {
    var seen = Set<Int64>()
    for binding in bindings {
        let key = Int64(binding.keyCode) << 8 | Int64(binding.modifierMask)
        if !seen.insert(key).inserted { return true }
    }
    return false
}

// MARK: - Picker content

/// One picker row, decoded from the JSON Rust sends to the panel.
struct GlobalPickerItem: Equatable {
    let id: String
    let title: String
    let subtitle: String
    let badge: String
    let kind: String
    let pinned: Bool
    /// "app:<path to a .app bundle>" for an application icon, or a glyph name such as "tool".
    let icon: String
}

/// Only copied text and links can be pinned from the clipboard panel; images, launcher rows and transcripts cannot.
func globalPickerCanPin(kind: String) -> Bool {
    kind == "text" || kind == "link"
}

struct GlobalPickerChip: Equatable {
    let id: String
    let label: String
    /// Optional in-panel key that selects this chip, set by the user in Settings.
    let keyCode: Int?
    let modifierMask: Int?
}

/// Which quick-result rows the launcher may compute itself. Set in Settings; all on by default.
struct GlobalQuickSwitches: Equatable {
    var calculator = true
    var uuid = true
    var password = true
    var passwordLength = globalPasswordDefaultLength
    var passwordSymbols = "!@#$%&*?-_+="

    static let all = GlobalQuickSwitches()
}

struct GlobalPickerContent: Equatable {
    /// "launcher" for the large Spotlight-style panel; anything else is the standard panel.
    let style: String
    let title: String
    let placeholder: String
    let chips: [GlobalPickerChip]
    let items: [GlobalPickerItem]
    /// The chip a freshly opened panel selects; an id the panel does not have selects the first chip.
    var initialChip: String = ""
    var quickResults: GlobalQuickSwitches = .all
    /// Chips whose rows can only be pasted: pin and delete are off while one of them is selected.
    var readOnlyChips: [String] = []
}

let globalPickerMaxItems = 1_000
let globalPickerMaxChips = 12
let globalPickerMaxFieldLength = 4_096

private func clippedField(_ value: Any?) -> String {
    guard let text = value as? String else { return "" }
    let collapsed = text.split(whereSeparator: \.isNewline).joined(separator: " ")
    return String(collapsed.prefix(globalPickerMaxFieldLength))
}

/// Decodes panel content, rejecting malformed input and bounding item count and field length.
func globalPickerContent(fromJSON data: Data) -> GlobalPickerContent? {
    guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let rawItems = object["items"] as? [[String: Any]],
          rawItems.count <= globalPickerMaxItems else { return nil }
    var chips: [GlobalPickerChip] = []
    if let rawChips = object["chips"] as? [[String: Any]] {
        guard rawChips.count <= globalPickerMaxChips else { return nil }
        for raw in rawChips {
            guard let id = raw["id"] as? String, !id.isEmpty, id.count <= 128 else { return nil }
            var keyCode = raw["keyCode"] as? Int
            var modifierMask = raw["modifierMask"] as? Int
            if let key = keyCode, let mask = modifierMask, (0...127).contains(key), (1...15).contains(mask) {
                // A valid binding keeps both values.
            } else {
                keyCode = nil
                modifierMask = nil
            }
            chips.append(GlobalPickerChip(id: id, label: clippedField(raw["label"]), keyCode: keyCode, modifierMask: modifierMask))
        }
    }
    var items: [GlobalPickerItem] = []
    for raw in rawItems {
        guard let id = raw["id"] as? String, !id.isEmpty, id.count <= 128 else { return nil }
        items.append(GlobalPickerItem(
            id: id,
            title: clippedField(raw["title"]),
            subtitle: clippedField(raw["subtitle"]),
            badge: clippedField(raw["badge"]),
            kind: clippedField(raw["kind"]),
            pinned: (raw["pinned"] as? Bool) ?? false,
            icon: clippedField(raw["icon"])
        ))
    }
    var quick = GlobalQuickSwitches.all
    if let raw = object["quickResults"] as? [String: Any] {
        quick.calculator = (raw["calculator"] as? Bool) ?? true
        quick.uuid = (raw["uuid"] as? Bool) ?? true
        quick.password = (raw["password"] as? Bool) ?? true
        let length = raw["passwordLength"] as? Int ?? globalPasswordDefaultLength
        if (globalPasswordMinLength...globalPasswordMaxLength).contains(length) {
            quick.passwordLength = length
        }
        if let symbols = raw["passwordSymbols"] as? String,
           symbols.count <= 32, globalPasswordSymbolsAreValid(symbols) {
            quick.passwordSymbols = symbols
        }
    }
    return GlobalPickerContent(
        style: clippedField(object["style"]),
        title: clippedField(object["title"]),
        placeholder: clippedField(object["placeholder"]),
        chips: chips,
        items: items,
        initialChip: clippedField(object["initialChip"]),
        quickResults: quick,
        readOnlyChips: (object["readOnlyChips"] as? [String] ?? []).prefix(globalPickerMaxChips).map { clippedField($0) }
    )
}

/// Case-insensitive filter over title, subtitle and badge; an empty query keeps every item.
/// The chip "all" keeps everything, "pinned" keeps pinned rows, any other chip matches the kind.
/// With `ranked`, a typed query orders matches: title prefix, then title contains, then other fields;
/// ties keep the incoming order (which the caller uses for recency).
func globalPickerFilter(_ items: [GlobalPickerItem], query: String, chip: String = "all", ranked: Bool = false) -> [GlobalPickerItem] {
    let needle = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let matches = items.filter { item in
        let isWindowCommand = item.kind == "command" && item.id.hasPrefix("command-window-")
        let chipMatches: Bool
        switch chip {
        case "all": chipMatches = item.kind != "dictation"  // transcripts only show on their own tab
        case "pinned": chipMatches = item.pinned
        case "text": chipMatches = item.kind == "text" || item.kind == "link"  // a link is also text
        case "app": chipMatches = item.kind == "app" || (item.kind == "command" && !isWindowCommand)  // Finder commands sit with the apps
        case "tool": chipMatches = item.kind == "tool" || isWindowCommand  // window layouts sit with the tools
        default: chipMatches = item.kind == chip
        }
        guard chipMatches else { return false }
        guard !needle.isEmpty else { return true }
        return item.title.lowercased().contains(needle)
            || item.subtitle.lowercased().contains(needle)
            || item.badge.lowercased().contains(needle)
    }
    guard ranked, !needle.isEmpty else { return matches }
    func score(_ item: GlobalPickerItem) -> Int {
        let title = item.title.lowercased()
        if title.hasPrefix(needle) { return 0 }
        return title.contains(needle) ? 1 : 2
    }
    return matches.enumerated().sorted { left, right in
        let (a, b) = (score(left.element), score(right.element))
        return a != b ? a < b : left.offset < right.offset
    }.map(\.element)
}

/// Index of the chip bound to a key press, or nil when none is.
func globalPickerChipIndex(forKeyCode keyCode: Int, modifierMask: Int, chips: [GlobalPickerChip]) -> Int? {
    chips.firstIndex { $0.keyCode == keyCode && $0.modifierMask == modifierMask }
}

private let globalKeyNames: [Int: String] = [
    0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X", 8: "C", 9: "V", 11: "B", 12: "Q", 13: "W",
    14: "E", 15: "R", 16: "Y", 17: "T", 18: "1", 19: "2", 20: "3", 21: "4", 22: "6", 23: "5", 24: "=", 25: "9",
    26: "7", 27: "-", 28: "8", 29: "0", 30: "]", 31: "O", 32: "U", 33: "[", 34: "I", 35: "P", 36: "↩", 37: "L",
    38: "J", 39: "'", 40: "K", 41: ";", 42: "\\", 43: ",", 44: "/", 45: "N", 46: "M", 47: ".", 48: "⇥", 49: "Space",
    50: "`", 51: "⌫", 53: "⎋", 123: "←", 124: "→", 125: "↓", 126: "↑",
]

/// Display text for a shortcut, for example "⌃1". Modifier glyphs follow the system order.
func globalShortcutLabel(keyCode: Int, modifierMask: Int) -> String {
    var label = ""
    if modifierMask & Int(globalModifierControl) != 0 { label += "⌃" }
    if modifierMask & Int(globalModifierOption) != 0 { label += "⌥" }
    if modifierMask & Int(globalModifierShift) != 0 { label += "⇧" }
    if modifierMask & Int(globalModifierCommand) != 0 { label += "⌘" }
    return label + (globalKeyNames[keyCode] ?? "Key \(keyCode)")
}

let globalLauncherMaxRows = 8
let globalLauncherRowHeight = 48
private let globalLauncherChromeHeight = 144
private let globalLauncherMinHeight = 220
private let globalStandardPanelHeight = 464

/// Panel height: the standard panel is fixed; the launcher grows with its rows up to eight.
func globalPickerPanelHeight(style: String, rowCount: Int) -> Int {
    guard style == "launcher" else { return globalStandardPanelHeight }
    let rows = min(max(rowCount, 0), globalLauncherMaxRows)
    return max(globalLauncherMinHeight, globalLauncherChromeHeight + rows * globalLauncherRowHeight)
}

/// The .app bundle path inside an "app:<path>" icon reference, or nil when it is not a safe absolute path.
func globalPickerApplicationPath(fromIcon icon: String) -> String? {
    guard icon.hasPrefix("app:") else { return nil }
    let path = String(icon.dropFirst("app:".count))
    guard path.hasPrefix("/"), path.hasSuffix(".app"),
          !path.split(separator: "/").contains("..") else { return nil }
    return path
}

private let globalToolCategoryTints: [String: String] = [
    "PDF & Documents": "red", "Images": "orange", "Finance & Documents": "green",
    "Calculators": "blue", "Unit Converters": "blue", "Developer & Data": "purple",
    "Audio & Dictation": "pink", "File Utilities": "yellow", "Storage & Cleanup": "yellow",
    "Network": "teal", "System": "gray", "Ergonomics": "green",
]

/// Catalog icon name (Font Awesome) to the closest SF Symbol. Unknown names fall back to the wrench.
private let globalToolSymbols: [String: String] = [
    "fa-arrow-trend-down": "chart.line.downtrend.xyaxis", "fa-arrow-up-wide-short": "arrow.up.arrow.down",
    "fa-arrows-left-right": "arrow.left.arrow.right", "fa-calculator": "plus.forwardslash.minus",
    "fa-calendar": "calendar", "fa-chart-line": "chart.xyaxis.line", "fa-chart-pie": "chart.pie.fill",
    "fa-circle-info": "info.circle.fill", "fa-clipboard-check": "checklist", "fa-clipboard-list": "list.clipboard.fill",
    "fa-clone": "square.on.square", "fa-code": "chevron.left.forwardslash.chevron.right",
    "fa-code-compare": "arrow.triangle.branch", "fa-coins": "dollarsign.circle.fill",
    "fa-compress": "arrow.down.right.and.arrow.up.left", "fa-crop-simple": "crop",
    "fa-ethernet": "network", "fa-expand": "arrow.up.left.and.arrow.down.right", "fa-eye": "eye.fill",
    "fa-file-circle-question": "questionmark.folder.fill", "fa-file-invoice-dollar": "doc.text.fill",
    "fa-file-lines": "doc.text.fill", "fa-file-shield": "lock.doc.fill", "fa-file-signature": "signature",
    "fa-file-zipper": "doc.zipper", "fa-fingerprint": "touchid", "fa-gauge-high": "gauge.with.dots.needle.67percent",
    "fa-glass-water": "drop.fill", "fa-hard-drive": "internaldrive.fill", "fa-headphones": "headphones",
    "fa-image": "photo.fill", "fa-images": "photo.on.rectangle", "fa-key": "key.fill",
    "fa-landmark": "building.columns.fill", "fa-link": "link", "fa-location-dot": "location.fill",
    "fa-lock-open": "lock.open.fill", "fa-magnifying-glass-location": "magnifyingglass",
    "fa-microphone-lines": "mic.fill", "fa-object-group": "square.on.square.dashed", "fa-palette": "paintpalette.fill",
    "fa-pen-to-square": "square.and.pencil", "fa-percent": "percent", "fa-person-walking": "figure.walk",
    "fa-photo-film": "photo.on.rectangle.angled", "fa-satellite-dish": "antenna.radiowaves.left.and.right",
    "fa-scale-balanced": "scalemass.fill", "fa-scissors": "scissors", "fa-shield-halved": "shield.lefthalf.filled",
    "fa-table": "tablecells.fill", "fa-trash-can": "trash.fill", "fa-user-secret": "person.fill.questionmark",
    "fa-user-tie": "person.crop.square.fill",
]

/// SF Symbol and colour family for a launcher tool row. `icon` is "tool" or
/// "tool|<catalog icon>|<category>"; anything unknown keeps the wrench in the category colour.
func globalToolGlyph(fromIcon icon: String) -> (symbol: String, tint: String) {
    let wrench = "wrench.and.screwdriver.fill"
    let parts = icon.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
    guard parts.count == 3, parts[0] == "tool" else { return (wrench, "indigo") }
    return (globalToolSymbols[parts[1]] ?? wrench, globalToolCategoryTints[parts[2]] ?? "indigo")
}

/// Next selected row for an arrow key, clamped to the list.
func globalPickerMoveSelection(current: Int, delta: Int, count: Int) -> Int {
    guard count > 0 else { return 0 }
    return min(count - 1, max(0, current + delta))
}

/// Row for a Command-1 to Command-9 shortcut, or nil when the key is not a digit 1 to 9 or the list is shorter.
func globalPickerQuickRow(forKey key: String?, count: Int) -> Int? {
    guard let key, key.count == 1, let digit = Int(key), (1...9).contains(digit), digit <= count else { return nil }
    return digit - 1
}

/// Next chip index when Tab cycles filters, wrapping around.
func globalPickerNextChip(current: Int, count: Int, backwards: Bool) -> Int {
    guard count > 0 else { return 0 }
    return (current + (backwards ? count - 1 : 1)) % count
}

// MARK: - Clipboard capture filter

let globalConcealedPasteboardTypes: Set<String> = [
    "org.nspasteboard.ConcealedType",
    "org.nspasteboard.AutoGeneratedType",
    "org.nspasteboard.TransientType",
    "com.agilebits.onepassword",
    "de.petermaurer.TransientPasteboardType",
    "Pasteboard generator type",
]

/// Bundle identifiers are case-insensitive, so the skip list matches the same way.
func globalBundleIDIsSkipped(_ bundleID: String, skipBundleIDs: Set<String>) -> Bool {
    skipBundleIDs.contains { $0.caseInsensitiveCompare(bundleID) == .orderedSame }
}

/// A pasteboard change is captured unless it is marked concealed or transient, or the frontmost
/// app is on the skip list.
func globalPasteboardShouldCapture(types: [String], frontmostBundleID: String?, skipBundleIDs: Set<String>) -> Bool {
    if types.contains(where: { globalConcealedPasteboardTypes.contains($0) }) { return false }
    if let frontmostBundleID, globalBundleIDIsSkipped(frontmostBundleID, skipBundleIDs: skipBundleIDs) { return false }
    return true
}

// MARK: - Snippet keyword matching

/// Rolling record of the last typed characters, kept in memory only. Never logged or stored.
struct GlobalKeywordBuffer {
    static let maxLength = 32
    static let pauseSeconds: TimeInterval = 3

    private(set) var text = ""
    private var lastInput = Date.distantPast

    mutating func append(_ characters: String, now: Date) {
        if now.timeIntervalSince(lastInput) > Self.pauseSeconds { text = "" }
        lastInput = now
        text += characters
        if text.count > Self.maxLength { text = String(text.suffix(Self.maxLength)) }
    }

    mutating func deleteLast() {
        if !text.isEmpty { text.removeLast() }
    }

    mutating func reset() {
        text = ""
    }
}

/// The longest trigger the buffer currently ends with, or nil. A trigger that starts with a
/// letter or digit only matches at the start of a word, so "ty" does not fire inside "party".
func globalKeywordMatch(buffer: String, triggers: Set<String>) -> String? {
    triggers.filter { trigger in
        guard !trigger.isEmpty, buffer.hasSuffix(trigger) else { return false }
        guard let first = trigger.first, first.isLetter || first.isNumber else { return true }
        let before = buffer.dropLast(trigger.count).last
        return before.map { !($0.isLetter || $0.isNumber) } ?? true
    }.max { $0.count < $1.count }
}

// MARK: Menu-bar drawers

let menuDrawerMaxItems = 9
let menuDrawerMaxRows = 8
let menuDrawerMaxText = 120
let menuDrawerMaxRings = 3
let menuDrawerMaxSummary = 4
let menuDrawerMaxHistory = 180
let menuDrawerMaxDetails = 40
let menuDrawerMaxCores = 64
let menuDrawerMaxSegments = 6
/// Colour names the drawer may use for rings, bars and dots. Anything else falls back to the default colour.
let menuDrawerTones: Set<String> = ["blue", "orange", "red", "grey", "teal", "violet"]
/// The Activity Monitor action runs this fixed command with no shell and no interpolated text.
let menuDrawerActivityMonitorCommand: (executable: String, arguments: [String]) = ("/usr/bin/open", ["-a", "Activity Monitor"])

/// One process row in a drawer.
struct MenuDrawerRow: Equatable {
    let pid: Int
    let name: String
    let value: String
    let killable: Bool
    var detail: String? = nil
}

/// A ring gauge: a percentage (0 to 100) with a caption in its centre and an optional small title beneath it.
struct MenuDrawerRing: Equatable {
    let label: String
    let percent: Double
    let tone: String?
    var title: String? = nil
}

/// One CPU core's load (0 to 100), drawn as a bar in the cores graph.
struct MenuDrawerCore: Equatable {
    let percent: Double
    let tone: String?
}

/// A segment of a stacked bar, as a percentage of the bar.
struct MenuDrawerSegment: Equatable {
    let percent: Double
    let tone: String?
}

/// A label and value line, with an optional coloured dot.
struct MenuDrawerLine: Equatable {
    let label: String
    let value: String
    let tone: String?
}

/// A user-triggered gateway/internet comparison shown only in the Network drawer.
struct MenuDrawerHealth: Equatable {
    let headline: String
    let detail: String
    let tone: String?
    let routerTone: String?
    let internetTone: String?
    let connection: String
    let router: String
    let internet: String
    let checked: String
}

/// Bounded result text for a process quit request in a menu-bar drawer.
struct MenuDrawerQuitFeedback: Equatable {
    let pid: Int
    let state: String
    let message: String
}

/// One entry of the DETAILS section: a line, a sub-heading, or a stacked bar.
enum MenuDrawerDetail: Equatable {
    case line(MenuDrawerLine)
    case heading(String)
    case bar([MenuDrawerSegment])
}

/// One menu-bar item and the drawer under it. Headline fields are required; the rest are optional sections.
/// Usage history values are percentages (0 to 100) and are kept in memory by the web layer only.
struct MenuDrawerModel: Equatable {
    let id: String
    let barText: String
    let heading: String
    let big: String
    let subtitle: String
    let rows: [MenuDrawerRow]
    var rowsTitle: String? = nil
    var rings: [MenuDrawerRing] = []
    var summary: [MenuDrawerLine] = []
    var historyTitle: String? = nil
    var history: [Double] = []
    var details: [MenuDrawerDetail] = []
    var cores: [MenuDrawerCore] = []
    var storageAction = false
    var batteryAction = false
    var networkCheckAction = false
    var networkCheckBusy = false
    /// True when opening this drawer should start the router and internet check (the last result is old or missing).
    var networkCheckAuto = false
    var networkHealth: MenuDrawerHealth? = nil
    var quitFeedback: MenuDrawerQuitFeedback? = nil
    /// A key of `menuDrawerSettingsPanes`; the footer button opens that System Settings pane instead of Activity Monitor.
    var settingsPane: String? = nil
}

/// The only System Settings panes a drawer can open: fixed names and addresses, nothing taken from the model.
let menuDrawerSettingsPanes: [String: (title: String, url: String)] = [
    "battery": ("Open Battery settings", "x-apple.systempreferences:com.apple.Battery-Settings.extension"),
    "bluetooth": ("Open Bluetooth settings", "x-apple.systempreferences:com.apple.BluetoothSettings"),
    "network": ("Open Network settings", "x-apple.systempreferences:com.apple.Network-Settings.extension"),
]

/// Clamps a usage figure to the 0 to 100 range the gauges and bars can draw.
func menuDrawerClampPercent(_ value: Double) -> Double {
    min(100, max(0, value))
}

/// Number of button-like actions: Activity Monitor in the header, one footer action, optional Storage
/// and optional Network check footer actions. The Cloudflare shortcut is a text link; Quit chips are per-row.
func menuDrawerButtonCount(_ model: MenuDrawerModel) -> Int {
    2 + ((model.id == "cpu" || model.id == "ram") ? 1 : 0) + (model.storageAction ? 1 : 0) + (model.networkCheckAction ? 1 : 0)
}

/// Bar heights for the usage history as fractions of the graph height, oldest first.
func menuDrawerHistoryFractions(_ values: [Double]) -> [Double] {
    values.map { menuDrawerClampPercent($0) / 100 }
}

private func menuDrawerText(_ value: Any?, allowEmpty: Bool = true) -> String? {
    guard let value = value as? String, value.count <= menuDrawerMaxText,
          !value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }),
          allowEmpty || !value.isEmpty else { return nil }
    return value
}

/// A finite JSON number that is not a boolean, or nil.
private func menuDrawerNumber(_ value: Any?) -> Double? {
    guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
    let double = number.doubleValue
    return double.isFinite ? double : nil
}

private func menuDrawerTone(_ value: Any?) -> String? {
    guard let tone = value as? String, menuDrawerTones.contains(tone) else { return nil }
    return tone
}

private func menuDrawerSegments(_ value: Any?) -> [MenuDrawerSegment] {
    (value as? [[String: Any]] ?? []).prefix(menuDrawerMaxSegments).compactMap { item in
        guard let percent = menuDrawerNumber(item["percent"]) else { return nil }
        return MenuDrawerSegment(percent: menuDrawerClampPercent(percent), tone: menuDrawerTone(item["tone"]))
    }
}

private func menuDrawerLine(_ item: [String: Any]) -> MenuDrawerLine? {
    guard let label = menuDrawerText(item["label"], allowEmpty: false), let value = menuDrawerText(item["value"]) else { return nil }
    return MenuDrawerLine(label: label, value: value, tone: menuDrawerTone(item["tone"]))
}

private func menuDrawerDetails(_ value: Any?) -> [MenuDrawerDetail] {
    var details: [MenuDrawerDetail] = []
    for item in (value as? [[String: Any]] ?? []).prefix(menuDrawerMaxDetails) {
        if let heading = menuDrawerText(item["heading"], allowEmpty: false) {
            details.append(.heading(heading))
        } else if let segments = item["bar"] {
            let parsed = menuDrawerSegments(segments)
            if !parsed.isEmpty { details.append(.bar(parsed)) }
        } else if let line = menuDrawerLine(item) {
            details.append(.line(line))
        }
    }
    return details
}

private func menuDrawerHealth(_ value: Any?) -> MenuDrawerHealth? {
    guard let item = value as? [String: Any],
          let headline = menuDrawerText(item["headline"], allowEmpty: false),
          let detail = menuDrawerText(item["detail"], allowEmpty: false),
          let routerTone = menuDrawerText(item["routerTone"], allowEmpty: false),
          let internetTone = menuDrawerText(item["internetTone"], allowEmpty: false),
          let connection = menuDrawerText(item["connection"], allowEmpty: false),
          let router = menuDrawerText(item["router"], allowEmpty: false),
          let internet = menuDrawerText(item["internet"], allowEmpty: false),
          let checked = menuDrawerText(item["checked"]) else { return nil }
    return MenuDrawerHealth(headline: headline, detail: detail, tone: menuDrawerTone(item["tone"]),
                            routerTone: menuDrawerTone(routerTone), internetTone: menuDrawerTone(internetTone),
                            connection: connection, router: router, internet: internet, checked: checked)
}

private func menuDrawerQuitFeedback(_ value: Any?) -> MenuDrawerQuitFeedback? {
    guard let item = value as? [String: Any],
          let pid = item["pid"] as? Int, pid >= 2, pid <= 4_194_304,
          let state = item["state"] as? String, ["working", "error"].contains(state),
          let message = menuDrawerText(item["message"], allowEmpty: false) else { return nil }
    return MenuDrawerQuitFeedback(pid: pid, state: state, message: message)
}

/// Keeps only well-formed drawers: at most 7, ids of letters and digits, bounded text, at most 8 rows, no
/// control characters, and a killable row only for a pid of 2 or more. Malformed items are dropped.
func menuDrawerModels(fromJSON data: Data) -> [MenuDrawerModel]? {
    guard data.count <= 64 * 1024,
          let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let drawers = object["drawers"] as? [[String: Any]] else { return nil }
    var seen = Set<String>()
    var models: [MenuDrawerModel] = []
    for drawer in drawers.prefix(menuDrawerMaxItems) {
        guard let id = menuDrawerText(drawer["id"], allowEmpty: false), id.count <= 16,
              id.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber) }), seen.insert(id).inserted,
              let barText = menuDrawerText(drawer["bar"], allowEmpty: false), let heading = menuDrawerText(drawer["heading"]),
              let big = menuDrawerText(drawer["big"]), let subtitle = menuDrawerText(drawer["sub"]) else { continue }
        var rows: [MenuDrawerRow] = []
        for row in (drawer["rows"] as? [[String: Any]] ?? []).prefix(menuDrawerMaxRows) {
            guard let name = menuDrawerText(row["name"], allowEmpty: false), let value = menuDrawerText(row["value"]),
                  let pid = row["pid"] as? Int, pid >= 0, pid <= 4_194_304 else { continue }
            rows.append(MenuDrawerRow(pid: pid, name: name, value: value, killable: (row["killable"] as? Bool ?? false) && pid >= 2,
                                      detail: menuDrawerText(row["detail"], allowEmpty: false)))
        }
        let rings: [MenuDrawerRing] = (drawer["rings"] as? [[String: Any]] ?? []).prefix(menuDrawerMaxRings).compactMap { ring in
            guard let label = menuDrawerText(ring["label"]), let percent = menuDrawerNumber(ring["percent"]) else { return nil }
            return MenuDrawerRing(label: label, percent: menuDrawerClampPercent(percent), tone: menuDrawerTone(ring["tone"]),
                                  title: menuDrawerText(ring["title"], allowEmpty: false))
        }
        let cores: [MenuDrawerCore] = (drawer["cores"] as? [[String: Any]] ?? []).prefix(menuDrawerMaxCores).compactMap { core in
            menuDrawerNumber(core["percent"]).map { MenuDrawerCore(percent: menuDrawerClampPercent($0), tone: menuDrawerTone(core["tone"])) }
        }
        let summary: [MenuDrawerLine] = (drawer["summary"] as? [[String: Any]] ?? []).prefix(menuDrawerMaxSummary).compactMap(menuDrawerLine)
        let history: [Double] = (drawer["history"] as? [Any] ?? []).prefix(menuDrawerMaxHistory).compactMap { menuDrawerNumber($0).map(menuDrawerClampPercent) }
        models.append(MenuDrawerModel(
            id: id, barText: barText, heading: heading, big: big, subtitle: subtitle, rows: rows,
            rowsTitle: menuDrawerText(drawer["rowsTitle"], allowEmpty: false),
            rings: rings, summary: summary,
            historyTitle: menuDrawerText(drawer["historyTitle"], allowEmpty: false),
            history: history, details: menuDrawerDetails(drawer["details"]), cores: cores,
            storageAction: drawer["storage"] as? Bool ?? false,
            batteryAction: drawer["battery"] as? Bool ?? false,
            networkCheckAction: drawer["networkCheck"] as? Bool ?? false,
            networkCheckBusy: drawer["networkCheckBusy"] as? Bool ?? false,
            networkCheckAuto: drawer["networkCheckAuto"] as? Bool ?? false,
            networkHealth: menuDrawerHealth(drawer["networkHealth"]),
            quitFeedback: menuDrawerQuitFeedback(drawer["quitFeedback"]),
            settingsPane: (drawer["settings"] as? String).flatMap { menuDrawerSettingsPanes[$0] != nil ? $0 : nil }
                ?? ((drawer["battery"] as? Bool ?? false) ? "battery" : nil)
        ))
    }
    return models
}

// MARK: Launcher quick results (sums, UUIDs, passwords)

let globalQuickMaxQueryLength = 120
let globalPasswordMinLength = 8
let globalPasswordMaxLength = 128
let globalPasswordDefaultLength = 20

/// Evaluates a small arithmetic expression: + - * / ^ % and brackets, `x` or `×` for times, `÷` for divide,
/// "15% of 800", spaces and thousands commas ignored. Nil for anything else, a bare number, or a
/// non-finite result (divide by zero), so the launcher shows no row for it.
func globalCalculate(_ input: String) -> String? {
    var text = input.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
    guard !text.isEmpty, text.count <= globalQuickMaxQueryLength else { return nil }
    if let match = text.range(of: #"^([0-9.,]+)\s*%\s*of\s*([0-9.,]+)$"#, options: .regularExpression) {
        let parts = text[match].replacingOccurrences(of: ",", with: "").components(separatedBy: CharacterSet(charactersIn: "% ")).filter { !$0.isEmpty && $0 != "of" }
        guard parts.count == 2, let rate = Double(parts[0]), let base = Double(parts[1]) else { return nil }
        return globalFormatNumber(rate / 100 * base)
    }
    text = text.replacingOccurrences(of: "×", with: "*").replacingOccurrences(of: "÷", with: "/")
        .replacingOccurrences(of: ",", with: "").replacingOccurrences(of: " ", with: "")
    text = text.replacingOccurrences(of: #"(?<=[0-9)])x(?=[0-9(])"#, with: "*", options: .regularExpression)
    guard text.allSatisfy({ "0123456789.+-*/^%()".contains($0) }),
          text.contains(where: { "+-*/^%()".contains($0) }),
          text.contains(where: \.isNumber) else { return nil }
    var parser = GlobalExpressionParser(Array(text))
    guard let value = parser.parse(), value.isFinite else { return nil }
    return globalFormatNumber(value)
}

/// Up to 10 significant digits, without a trailing ".0".
func globalFormatNumber(_ value: Double) -> String {
    guard value.isFinite else { return "" }
    if value == value.rounded(), abs(value) < 1e15 { return String(format: "%.0f", value) }
    return String(format: "%.10g", value)
}

/// Money with thousands commas and two decimals, e.g. 1,234,567.89.
func globalFormatMoney(_ value: Double) -> String {
    guard value.isFinite else { return "" }
    let cents = (abs(value) * 100).rounded() / 100
    let whole = String(format: "%.0f", cents.rounded(.down))
    var grouped = ""
    for (index, digit) in whole.reversed().enumerated() {
        if index > 0, index % 3 == 0 { grouped.append(",") }
        grouped.append(digit)
    }
    let fraction = String(format: "%.2f", cents - cents.rounded(.down)).dropFirst()
    return (value < 0 ? "-" : "") + String(grouped.reversed()) + fraction
}

/// Parses "500,000", "8.5%", "20y" or "240m" (months) into a number; years is the unit unless "m" is given.
private func globalFinanceNumber(_ token: String, years: Bool = false) -> Double? {
    var text = token.lowercased().replacingOccurrences(of: ",", with: "")
    var scale = 1.0
    if years {
        if text.hasSuffix("years") { text.removeLast(5) } else if text.hasSuffix("yrs") { text.removeLast(3) }
        else if text.hasSuffix("y") { text.removeLast() }
        else if text.hasSuffix("m") { text.removeLast(); scale = 1.0 / 12.0 }
    } else if text.hasSuffix("%") { text.removeLast() }
    guard !text.isEmpty, text.allSatisfy({ "0123456789.".contains($0) }), let value = Double(text), value.isFinite else { return nil }
    return value * scale
}

/// "emi 500000 8.5% 20y" -> the fixed monthly payment, using the same bounds and formula as the Loan EMI
/// calculator: principal up to 1e12, rate 0-1000%, whole months between one month and 100 years.
func globalLoanEMI(principal: Double, annualRate: Double, years: Double) -> (payment: Double, total: Double, interest: Double)? {
    guard (0...1e12).contains(principal), (0...1000).contains(annualRate), years >= 1.0 / 12.0, years <= 100 else { return nil }
    let exactMonths = years * 12
    let months = exactMonths.rounded()
    guard abs(exactMonths - months) < 1e-9, months >= 1 else { return nil }
    let monthlyRate = annualRate / 1200
    let payment: Double
    if monthlyRate == 0 { payment = principal / months } else {
        let growth = pow(1 + monthlyRate, months)
        payment = principal * monthlyRate * growth / (growth - 1)
    }
    guard payment.isFinite else { return nil }
    // Walk the schedule in whole cents like the calculator: the last payment clears the balance.
    let regular = (payment * 100).rounded()
    var balance = (principal * 100).rounded()
    var interestTotal = 0.0
    var paidTotal = 0.0
    for month in 1...Int(months) {
        guard balance > 0 else { break }
        let interest = (balance * monthlyRate).rounded()
        var principalPaid = month == Int(months) ? balance : regular - interest
        if principalPaid <= 0 { return nil }
        principalPaid = min(principalPaid, balance)
        balance -= principalPaid
        interestTotal += interest
        paidTotal += principalPaid + interest
    }
    return (regular / 100, paidTotal / 100, interestTotal / 100)
}

/// "compound 10000 7% 10y [500]" -> the balance after whole months of monthly compounding with an optional
/// end-of-month contribution, as in the Compound interest calculator.
func globalCompoundGrowth(principal: Double, annualRate: Double, years: Double, monthly: Double) -> (balance: Double, contributed: Double)? {
    guard (0...1e12).contains(principal), annualRate > -100, annualRate <= 1000, (0...100).contains(years), (0...1e12).contains(monthly) else { return nil }
    let exactMonths = years * 12
    let months = exactMonths.rounded()
    guard abs(exactMonths - months) < 1e-9 else { return nil }
    let factor = 1 + annualRate / 1200
    var balance = principal
    for _ in 0..<Int(months) { balance = balance * factor + monthly }
    guard balance.isFinite else { return nil }
    return (balance, principal + monthly * months)
}

/// Launcher rows for "emi …" and "compound …" queries; empty for anything else or invalid numbers.
func globalFinanceResults(_ text: String) -> [GlobalPickerItem] {
    let words = text.lowercased().split(whereSeparator: { $0 == " " || $0 == "\t" }).map(String.init)
    guard let command = words.first, words.count >= 4, words.count <= 5 else { return [] }
    func row(_ id: String, _ title: String, _ subtitle: String) -> GlobalPickerItem {
        GlobalPickerItem(id: "quick:\(id)", title: title, subtitle: subtitle + " · Enter pastes, ⇧Enter copies", badge: "Calculation", kind: "quick", pinned: false, icon: "quick-calc")
    }
    guard let principal = globalFinanceNumber(words[1]), let rate = globalFinanceNumber(words[2]),
          let years = globalFinanceNumber(words[3], years: true) else { return [] }
    switch command {
    case "emi", "loan":
        guard words.count == 4, let result = globalLoanEMI(principal: principal, annualRate: rate, years: years) else { return [] }
        return [
            row("emi", globalFormatMoney(result.payment), "Monthly EMI · total \(globalFormatMoney(result.total)), interest \(globalFormatMoney(result.interest))"),
            row("emi-total", globalFormatMoney(result.total), "Total repaid"),
        ]
    case "compound", "invest":
        let monthly = words.count == 5 ? globalFinanceNumber(words[4]) : 0
        guard let monthly, let result = globalCompoundGrowth(principal: principal, annualRate: rate, years: years, monthly: monthly) else { return [] }
        return [row("compound", globalFormatMoney(result.balance), "Balance · put in \(globalFormatMoney(result.contributed)), earned \(globalFormatMoney(result.balance - result.contributed))")]
    default:
        return []
    }
}

private struct GlobalExpressionParser {
    private let characters: [Character]
    private var position = 0
    private var depth = 0

    init(_ characters: [Character]) { self.characters = characters }

    mutating func parse() -> Double? {
        guard let value = expression(), position == characters.count else { return nil }
        return value
    }

    private func peek() -> Character? { position < characters.count ? characters[position] : nil }

    private mutating func expression() -> Double? {
        guard var left = term() else { return nil }
        while let op = peek(), op == "+" || op == "-" {
            position += 1
            guard let right = term() else { return nil }
            left = op == "+" ? left + right : left - right
        }
        return left
    }

    private mutating func term() -> Double? {
        guard var left = unary() else { return nil }
        while let op = peek(), op == "*" || op == "/" {
            position += 1
            guard let right = unary() else { return nil }
            left = op == "*" ? left * right : left / right
        }
        return left
    }

    private mutating func unary() -> Double? {
        if peek() == "-" {
            position += 1
            return unary().map { -$0 }
        }
        return power()
    }

    private mutating func power() -> Double? {
        guard let base = postfix() else { return nil }
        if peek() == "^" {
            position += 1
            guard let exponent = unary() else { return nil }
            return pow(base, exponent)
        }
        return base
    }

    private mutating func postfix() -> Double? {
        guard var value = primary() else { return nil }
        while peek() == "%" {
            position += 1
            value /= 100
        }
        return value
    }

    private mutating func primary() -> Double? {
        if peek() == "(" {
            depth += 1
            guard depth <= 32 else { return nil }
            position += 1
            guard let value = expression(), peek() == ")" else { return nil }
            position += 1
            depth -= 1
            return value
        }
        let start = position
        while let c = peek(), c.isNumber || c == "." { position += 1 }
        guard position > start else { return nil }
        return Double(String(characters[start..<position]))
    }
}

private let globalPasswordLetters = Array("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
private let globalPasswordUppercase = Array("ABCDEFGHJKLMNPQRSTUVWXYZ")
private let globalPasswordLowercase = Array("abcdefghijkmnopqrstuvwxyz")
private let globalPasswordDigits = Array("23456789")
private let globalPasswordSymbols = "!@#$%&*?-_+="

private func globalPasswordSymbolsAreValid(_ symbols: String) -> Bool {
    var seen = Set<Character>()
    return symbols.unicodeScalars.allSatisfy { scalar in
        let value = scalar.value
        let punctuation = (33...47).contains(value) || (58...64).contains(value)
            || (91...96).contains(value) || (123...126).contains(value)
        return punctuation && seen.insert(Character(scalar)).inserted
    }
}

/// Uniform random integer in 0..<bound from `random`, using rejection sampling so no value is favoured.
func globalRandomIndex(below bound: Int, random: (Int) -> [UInt8]) -> Int {
    precondition(bound > 0 && bound <= 256)
    let limit = 256 - 256 % bound
    while true {
        for byte in random(16) where Int(byte) < limit { return Int(byte) % bound }
    }
}

/// A password of `length` characters with at least one upper, lower, digit and symbol, no look-alikes
/// (0 O 1 l I), shuffled with the same secure source. Nil outside 8...128.
func globalGeneratePassword(length: Int, symbols: String = globalPasswordSymbols, random: (Int) -> [UInt8]) -> String? {
    guard (globalPasswordMinLength...globalPasswordMaxLength).contains(length) else { return nil }
    guard symbols.count <= 32, globalPasswordSymbolsAreValid(symbols) else { return nil }
    var pools = [globalPasswordUppercase, globalPasswordLowercase, globalPasswordDigits]
    let symbolPool = Array(symbols)
    if !symbolPool.isEmpty { pools.append(symbolPool) }
    let all = globalPasswordLetters + globalPasswordDigits + symbolPool
    func pick(_ pool: [Character]) -> Character { pool[globalRandomIndex(below: pool.count, random: random)] }
    var characters = pools.map(pick)
    while characters.count < length { characters.append(pick(all)) }
    for index in stride(from: characters.count - 1, to: 0, by: -1) {
        characters.swapAt(index, globalRandomIndex(below: index + 1, random: random))
    }
    return String(characters)
}

/// A UUID string (v4 layout) from 16 random bytes.
func globalGenerateUUID(random: (Int) -> [UInt8]) -> String {
    var bytes = Array(random(16).prefix(16))
    while bytes.count < 16 { bytes.append(0) }
    bytes[6] = (bytes[6] & 0x0F) | 0x40
    bytes[8] = (bytes[8] & 0x3F) | 0x80
    let hex = bytes.map { String(format: "%02x", $0) }.joined()
    let parts = [0..<8, 8..<12, 12..<16, 16..<20, 20..<32].map { range -> String in
        let start = hex.index(hex.startIndex, offsetBy: range.lowerBound)
        let end = hex.index(hex.startIndex, offsetBy: range.upperBound)
        return String(hex[start..<end])
    }
    return parts.joined(separator: "-")
}

/// Result rows the launcher shows above the normal matches for a typed query. Each row's `title` is the
/// value to paste or copy; its id starts with "quick:".
func globalQuickResults(query: String, random: (Int) -> [UInt8], switches: GlobalQuickSwitches = .all) -> [GlobalPickerItem] {
    let text = query.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !text.isEmpty, text.count <= globalQuickMaxQueryLength else { return [] }
    func row(_ id: String, _ title: String, _ subtitle: String, _ badge: String, _ icon: String) -> GlobalPickerItem {
        GlobalPickerItem(id: "quick:\(id)", title: title, subtitle: subtitle, badge: badge, kind: "quick", pinned: false, icon: icon)
    }
    let lower = text.lowercased()
    // The keyword may be typed in part (from three letters), so "pas" and "pass" both reach the password row.
    func isKeyword(_ typed: String, _ full: String) -> Bool { typed.count >= 3 && full.hasPrefix(typed) }
    if lower == "guid" || isKeyword(lower, "uuid") {
        // A switched-off UUID row is not generated at all; the text then falls through to nothing.
        guard switches.uuid else { return [] }
        let uuid = globalGenerateUUID(random: random)
        return [
            row("uuid", uuid, "New UUID (v4) · Enter pastes, ⇧Enter copies", "Generated", "quick-uuid"),
            row("uuid-plain", uuid.replacingOccurrences(of: "-", with: ""), "UUID without dashes", "Generated", "quick-uuid"),
        ]
    }
    if let match = lower.range(of: #"^[a-z]{2,8}(\s+[0-9]{1,3})?$"#, options: .regularExpression) {
        let words = lower[match].split(separator: " ")
        let keyword = String(words[0])
        guard keyword == "pw" || isKeyword(keyword, "password") else { return globalQuickCalculation(text, row, switches) }
        guard switches.password else { return [] }
        let length = words.count > 1 ? Int(words[1]) ?? 0 : switches.passwordLength
        guard let password = globalGeneratePassword(length: length, symbols: switches.passwordSymbols, random: random) else { return [] }
        return [row("password", password, "Strong password · \(length) characters · Enter pastes, ⇧Enter copies", "Generated", "quick-password")]
    }
    return globalQuickCalculation(text, row, switches)
}

private func globalQuickCalculation(_ text: String, _ row: (String, String, String, String, String) -> GlobalPickerItem, _ switches: GlobalQuickSwitches) -> [GlobalPickerItem] {
    guard switches.calculator else { return [] }
    let finance = globalFinanceResults(text)
    if !finance.isEmpty { return finance }
    guard let result = globalCalculate(text) else { return [] }
    return [row("calc", result, "\(text) · Enter pastes, ⇧Enter copies", "Calculation", "quick-calc")]
}
