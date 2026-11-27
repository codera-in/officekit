import Foundation

@main
struct MacOSGlobalLogicTests {
    static func main() {
        // Carbon modifier mapping
        require(globalCarbonModifiers(forMask: 0) == 0, "No modifiers map to no flags")
        require(globalCarbonModifiers(forMask: globalModifierCommand | globalModifierOption) == (1 << 8 | 1 << 11), "Command Option maps to Carbon flags")
        require(globalCarbonModifiers(forMask: globalModifierControl | globalModifierShift) == (1 << 12 | 1 << 9), "Control Shift maps to Carbon flags")
        require(globalCarbonModifiers(forMask: 0b10000) == nil, "Unknown modifier bits are rejected")

        // Registrable shortcuts
        require(globalShortcutIsRegistrable(keyCode: 9, modifierMask: 10), "Command Option V is registrable")
        require(!globalShortcutIsRegistrable(keyCode: 9, modifierMask: 0), "A bare letter is not a global shortcut")
        require(globalShortcutIsRegistrable(keyCode: 105, modifierMask: 0), "F13 alone is allowed")
        require(!globalShortcutIsRegistrable(keyCode: 200, modifierMask: 10), "Out of range key codes are rejected")
        require(!globalShortcutIsRegistrable(keyCode: 9, modifierMask: 16), "Out of range modifiers are rejected")
        require(!globalShortcutIsRegistrable(keyCode: -1, modifierMask: 10), "Negative key codes are rejected")

        // Conflicts
        require(!globalShortcutsConflict([(9, 10), (1, 10)]), "Different keys do not conflict")
        require(!globalShortcutsConflict([(9, 10), (9, 8)]), "Same key with different modifiers does not conflict")
        require(globalShortcutsConflict([(9, 10), (1, 10), (9, 10)]), "Duplicate bindings conflict")
        require(!globalShortcutsConflict([]), "No bindings never conflict")

        // Picker content decoding
        let good = Data("""
        {"title":"Clipboard","placeholder":"Search","items":[
          {"id":"a","title":"Invoice\\n2041","subtitle":"Mail","badge":"2m"},
          {"id":"b","title":"Link"}]}
        """.utf8)
        let content = globalPickerContent(fromJSON: good)
        require(content?.items.count == 2, "Valid content decodes both items")
        require(content?.items.first?.title == "Invoice 2041", "Newlines collapse into spaces")
        require(content?.items.last?.subtitle == "", "Missing fields default to empty")
        require(globalPickerContent(fromJSON: Data("not json".utf8)) == nil, "Malformed JSON is rejected")
        require(globalPickerContent(fromJSON: Data("{\"items\":[{\"title\":\"x\"}]}".utf8)) == nil, "Items without an id are rejected")
        require(globalPickerContent(fromJSON: Data("{\"items\":[{\"id\":\"\"}]}".utf8)) == nil, "Empty ids are rejected")
        let tooMany = "{\"items\":[" + Array(repeating: "{\"id\":\"x\"}", count: globalPickerMaxItems + 1).joined(separator: ",") + "]}"
        require(globalPickerContent(fromJSON: Data(tooMany.utf8)) == nil, "Too many items are rejected")
        let long = String(repeating: "a", count: globalPickerMaxFieldLength + 50)
        let longContent = globalPickerContent(fromJSON: Data("{\"items\":[{\"id\":\"x\",\"title\":\"\(long)\"}]}".utf8))
        require(longContent?.items.first?.title.count == globalPickerMaxFieldLength, "Long fields are clipped")

        // Filtering and selection
        let items = content?.items ?? []
        require(globalPickerFilter(items, query: "").count == 2, "Empty query keeps everything")
        require(globalPickerFilter(items, query: "  ").count == 2, "Blank query keeps everything")
        let transcript = GlobalPickerItem(id: "dictation-t", title: "Send the proposal", subtitle: "Dictation", badge: "3m", kind: "dictation", pinned: false, icon: "")
        let withTranscript = items + [transcript]
        require(globalPickerFilter(withTranscript, query: "", chip: "all").map(\.id) == ["a", "b"], "Transcripts stay off the All tab")
        require(globalPickerFilter(withTranscript, query: "", chip: "dictation").map(\.id) == ["dictation-t"], "The Dictation tab lists only transcripts")
        require(globalPickerFilter(withTranscript, query: "proposal", chip: "dictation").count == 1, "Dictation search matches the transcript text")
        let readOnlyJSON = Data("{\"items\":[],\"chips\":[{\"id\":\"dictation\",\"label\":\"Dictation\"}],\"readOnlyChips\":[\"dictation\"]}".utf8)
        require(globalPickerContent(fromJSON: readOnlyJSON)?.readOnlyChips == ["dictation"], "Read-only chips decode from the panel JSON")
        require(globalPickerFilter(items, query: "INVOICE").map(\.id) == ["a"], "Filter ignores case")
        // Mac apps and Mac tools match in any letter case, and an app wins a tie with an OfficeKit tool.
        let keychain = GlobalPickerItem(id: "app-keychain", title: "Keychain Access", subtitle: "/System/Library/CoreServices/Applications/Keychain Access.app", badge: "", kind: "app", pinned: false, icon: "")
        let finderTool = GlobalPickerItem(id: "command-open-trash", title: "Open Trash", subtitle: "Finder", badge: "bin", kind: "command", pinned: false, icon: "")
        let keyTool = GlobalPickerItem(id: "tool-keys", title: "Keychain helper", subtitle: "Security", badge: "", kind: "tool", pinned: false, icon: "")
        let macFirst = [keychain, finderTool, keyTool]
        for query in ["keychain", "KEYCHAIN", "KeyChain", "kEyCHAIN access"] {
            require(globalPickerFilter(macFirst, query: query, ranked: true).first?.id == "app-keychain", "App search ignores case: \(query)")
        }
        require(globalPickerFilter(macFirst, query: "OPEN TRASH", ranked: true).map(\.id) == ["command-open-trash"], "Mac tool search ignores case")
        require(globalPickerFilter(macFirst, query: "KEYC", ranked: true).map(\.id) == ["app-keychain", "tool-keys"], "An app listed first wins a ranking tie")
        require(globalPickerFilter(macFirst, query: "", chip: "app").map(\.id) == ["app-keychain", "command-open-trash"], "The Apps tab keeps Mac tools with the apps")
        require(globalPickerFilter(items, query: "mail").map(\.id) == ["a"], "Filter matches subtitles")
        require(globalPickerFilter(items, query: "2m").map(\.id) == ["a"], "Filter matches badges")
        require(globalPickerFilter(items, query: "zzz").isEmpty, "Unmatched query yields nothing")
        require(globalPickerMoveSelection(current: 0, delta: -1, count: 3) == 0, "Selection clamps at the top")
        require(globalPickerMoveSelection(current: 2, delta: 1, count: 3) == 2, "Selection clamps at the bottom")
        require(globalPickerMoveSelection(current: 1, delta: 1, count: 3) == 2, "Selection moves down")
        require(globalPickerMoveSelection(current: 1, delta: 1, count: 0) == 0, "Empty list selects nothing")
        require(globalPickerQuickRow(forKey: "1", count: 3) == 0, "Command-1 is the first row")
        require(globalPickerQuickRow(forKey: "3", count: 3) == 2, "Command-3 is the third row")
        require(globalPickerQuickRow(forKey: "4", count: 3) == nil, "A number past the list does nothing")
        require(globalPickerQuickRow(forKey: "9", count: 20) == 8, "Command-9 is the ninth row")
        require(globalPickerQuickRow(forKey: "0", count: 20) == nil, "Zero is not a row shortcut")
        require(globalPickerQuickRow(forKey: "10", count: 20) == nil, "Only single digits count")
        require(globalPickerQuickRow(forKey: "a", count: 20) == nil, "Letters are not row shortcuts")
        require(globalPickerQuickRow(forKey: nil, count: 20) == nil, "No key does nothing")

        // Chips, kinds and pinned flags
        let chipJSON = Data("""
        {"chips":[{"id":"all","label":"All"},{"id":"link","label":"Links"},{"id":"pinned","label":"Pinned"}],
         "items":[{"id":"1","title":"https://a.example","kind":"link"},
                  {"id":"2","title":"note","kind":"text","pinned":true},
                  {"id":"3","title":"other","kind":"text"}]}
        """.utf8)
        let chipContent = globalPickerContent(fromJSON: chipJSON)
        require(chipContent?.chips.map(\.label) == ["All", "Links", "Pinned"], "Chips decode with labels")
        require(chipContent?.items.map(\.pinned) == [false, true, false], "Pinned flags decode")
        let chipItems = chipContent?.items ?? []
        require(globalPickerFilter(chipItems, query: "", chip: "all").count == 3, "All chip keeps everything")
        require(globalPickerFilter(chipItems, query: "", chip: "link").map(\.id) == ["1"], "Kind chip filters by kind")
        require(globalPickerFilter(chipItems, query: "", chip: "pinned").map(\.id) == ["2"], "Pinned chip filters pinned rows")
        require(globalPickerFilter(chipItems, query: "oth", chip: "text").map(\.id) == ["3"], "Chip and query combine")
        require(globalPickerFilter(chipItems, query: "", chip: "text").map(\.id) == ["1", "2", "3"], "The Text chip includes links")
        require(globalPickerFilter(chipItems, query: "zzz", chip: "all").isEmpty, "Chip all with no match yields nothing")
        require(globalPickerContent(fromJSON: Data("{\"items\":[],\"chips\":[{\"label\":\"x\"}]}".utf8)) == nil, "Chips without an id are rejected")
        let manyChips = "{\"items\":[],\"chips\":[" + (0...globalPickerMaxChips).map { "{\"id\":\"c\($0)\"}" }.joined(separator: ",") + "]}"
        require(globalPickerContent(fromJSON: Data(manyChips.utf8)) == nil, "Too many chips are rejected")
        require(globalPickerContent(fromJSON: Data("{\"items\":[]}".utf8))?.chips.isEmpty == true, "Chips are optional")
        require(globalPickerNextChip(current: 0, count: 3, backwards: false) == 1, "Tab moves to the next chip")
        require(globalPickerNextChip(current: 2, count: 3, backwards: false) == 0, "Tab wraps to the first chip")
        require(globalPickerNextChip(current: 0, count: 3, backwards: true) == 2, "Shift Tab wraps to the last chip")
        require(globalPickerNextChip(current: 0, count: 0, backwards: false) == 0, "No chips selects the first")

        // Launcher: chip shortcuts, labels, ranking, sizing and icons
        let launcherJSON = Data("""
        {"style":"launcher","title":"Launcher",
         "chips":[{"id":"all","label":"All","keyCode":18,"modifierMask":1},
                  {"id":"app","label":"Apps","keyCode":19,"modifierMask":1},
                  {"id":"tool","label":"Tools"}],
         "items":[{"id":"a1","title":"Safari","subtitle":"/Applications/Safari.app","kind":"app","icon":"app:/Applications/Safari.app"},
                  {"id":"t1","title":"Safe file cleaner","subtitle":"Storage Reclaim","badge":"remove junk","kind":"tool","icon":"tool"},
                  {"id":"a2","title":"Notes Safari helper","subtitle":"/Applications/Notes.app","kind":"app"}]}
        """.utf8)
        let launcher = globalPickerContent(fromJSON: launcherJSON)
        require(launcher?.style == "launcher", "Launcher style decodes")
        require(globalPickerContent(fromJSON: good)?.style == "", "Style defaults to empty")
        require(launcher?.chips.map(\.keyCode) == [18, 19, nil], "Chip key codes decode and stay optional")
        require(launcher?.chips.map(\.modifierMask) == [1, 1, nil], "Chip modifier masks decode and stay optional")
        require(launcher?.items.map(\.icon) == ["app:/Applications/Safari.app", "tool", ""], "Icons decode and default to empty")
        let badChipKey = Data("{\"items\":[],\"chips\":[{\"id\":\"a\",\"keyCode\":999,\"modifierMask\":1}]}".utf8)
        require(globalPickerContent(fromJSON: badChipKey)?.chips.first?.keyCode == nil, "An out of range chip key is dropped")
        let chips = launcher?.chips ?? []
        require(globalPickerChipIndex(forKeyCode: 18, modifierMask: 1, chips: chips) == 0, "Control-1 selects the first chip")
        require(globalPickerChipIndex(forKeyCode: 19, modifierMask: 1, chips: chips) == 1, "Control-2 selects the second chip")
        require(globalPickerChipIndex(forKeyCode: 19, modifierMask: 2, chips: chips) == nil, "Another modifier does not select a chip")
        require(globalPickerChipIndex(forKeyCode: 20, modifierMask: 1, chips: chips) == nil, "An unbound key selects nothing")
        require(globalPickerChipIndex(forKeyCode: 18, modifierMask: 1, chips: []) == nil, "No chips select nothing")
        require(globalShortcutLabel(keyCode: 18, modifierMask: 1) == "⌃1", "Control-1 label")
        require(globalShortcutLabel(keyCode: 0, modifierMask: 15) == "⌃⌥⇧⌘A", "Modifier glyphs follow system order")
        require(globalShortcutLabel(keyCode: 49, modifierMask: 3) == "⌃⌥Space", "Space label")
        require(globalShortcutLabel(keyCode: 126, modifierMask: 2) == "⌥↑", "Arrow label")
        require(globalShortcutLabel(keyCode: 127, modifierMask: 1) == "⌃Key 127", "Unknown keys fall back to a number")
        let launcherItems = launcher?.items ?? []
        require(globalPickerFilter(launcherItems, query: "saf", ranked: true).map(\.id) == ["a1", "t1", "a2"], "Prefix matches rank before later matches, ties keep their order")
        require(globalPickerFilter(launcherItems, query: "saf").map(\.id) == ["a1", "t1", "a2"], "Unranked filtering keeps the original order")
        require(globalPickerFilter(launcherItems, query: "helper", ranked: true).map(\.id) == ["a2"], "Ranked filtering still filters")
        require(globalPickerFilter(launcherItems, query: "junk", ranked: true).map(\.id) == ["t1"], "Hidden badge text is searchable")
        let rankItems = [
            GlobalPickerItem(id: "x", title: "My Notes", subtitle: "", badge: "", kind: "app", pinned: false, icon: ""),
            GlobalPickerItem(id: "y", title: "Notes", subtitle: "", badge: "", kind: "app", pinned: false, icon: ""),
            GlobalPickerItem(id: "z", title: "Other", subtitle: "notes folder", badge: "", kind: "tool", pinned: false, icon: ""),
        ]
        require(globalPickerFilter(rankItems, query: "notes", ranked: true).map(\.id) == ["y", "x", "z"], "Title prefix, then title match, then other fields")
        require(globalPickerFilter(rankItems, query: "notes", chip: "tool", ranked: true).map(\.id) == ["z"], "Ranking respects the chip")
        require(globalPickerPanelHeight(style: "", rowCount: 0) == 464, "The standard panel keeps its fixed height")
        require(globalPickerPanelHeight(style: "", rowCount: 50) == 464, "The standard panel never grows")
        require(globalPickerPanelHeight(style: "launcher", rowCount: 0) == 220, "An empty launcher leaves room for the message")
        require(globalPickerPanelHeight(style: "launcher", rowCount: 1) == 220, "One launcher row uses the minimum height")
        require(globalPickerPanelHeight(style: "launcher", rowCount: 4) == 336, "The launcher grows with its rows")
        require(globalPickerPanelHeight(style: "launcher", rowCount: 8) == 528, "Eight rows reach the maximum height")
        require(globalPickerPanelHeight(style: "launcher", rowCount: 200) == 528, "The launcher stops growing at eight rows")
        require(globalPickerApplicationPath(fromIcon: "app:/Applications/Safari.app") == "/Applications/Safari.app", "App icons carry a path")
        require(globalPickerApplicationPath(fromIcon: "app:/Applications/Safari.app/../../etc/passwd") == nil, "Parent segments are rejected")
        require(globalPickerApplicationPath(fromIcon: "app:/Applications/Notes.txt") == nil, "Only .app bundles are accepted")

        // Tool icons come from the catalog; unknown input keeps the wrench
        let pdf = globalToolGlyph(fromIcon: "tool|fa-file-zipper|PDF & Documents")
        require(pdf.symbol == "doc.zipper" && pdf.tint == "red", "A catalog icon maps to its symbol and category colour")
        let unknownIcon = globalToolGlyph(fromIcon: "tool|fa-nope|Images")
        require(unknownIcon.symbol == "wrench.and.screwdriver.fill" && unknownIcon.tint == "orange", "An unknown icon keeps the wrench in the category colour")
        let unknownCategory = globalToolGlyph(fromIcon: "tool|fa-key|Something new")
        require(unknownCategory.symbol == "key.fill" && unknownCategory.tint == "indigo", "An unknown category falls back to indigo")
        require(globalToolGlyph(fromIcon: "tool").tint == "indigo", "The plain tool icon is the indigo wrench")
        require(globalToolGlyph(fromIcon: "tool|a|b|c").symbol == "wrench.and.screwdriver.fill", "Malformed icons keep the wrench")
        require(globalPickerApplicationPath(fromIcon: "app:relative/Safari.app") == nil, "Relative paths are rejected")
        require(globalPickerApplicationPath(fromIcon: "tool") == nil, "Glyph names are not paths")

        // Capture filter
        let skip: Set<String> = ["com.1password.1password"]
        require(globalPasteboardShouldCapture(types: ["public.utf8-plain-text"], frontmostBundleID: "com.apple.Notes", skipBundleIDs: skip), "Normal copies are captured")
        require(!globalPasteboardShouldCapture(types: ["public.utf8-plain-text", "org.nspasteboard.ConcealedType"], frontmostBundleID: nil, skipBundleIDs: skip), "Concealed copies are skipped")
        require(!globalPasteboardShouldCapture(types: ["org.nspasteboard.TransientType"], frontmostBundleID: nil, skipBundleIDs: skip), "Transient copies are skipped")
        require(!globalPasteboardShouldCapture(types: ["public.utf8-plain-text"], frontmostBundleID: "com.1password.1password", skipBundleIDs: skip), "Skip-listed apps are skipped")
        require(!globalPasteboardShouldCapture(types: ["public.utf8-plain-text"], frontmostBundleID: "COM.1PASSWORD.1PASSWORD", skipBundleIDs: skip), "Skip-listed apps match ignoring case")
        require(globalPasteboardShouldCapture(types: [], frontmostBundleID: nil, skipBundleIDs: skip), "An unknown frontmost app is captured")

        // Keyword buffer and matcher
        let start = Date(timeIntervalSince1970: 1_000)
        var buffer = GlobalKeywordBuffer()
        buffer.append(";", now: start)
        buffer.append("sig", now: start.addingTimeInterval(0.5))
        require(buffer.text == ";sig", "Typed characters accumulate")
        buffer.deleteLast()
        require(buffer.text == ";si", "Backspace removes the last character")
        buffer.reset()
        buffer.deleteLast()
        require(buffer.text.isEmpty, "Deleting from an empty buffer is harmless")
        buffer.append("ab", now: start)
        buffer.append("cd", now: start.addingTimeInterval(GlobalKeywordBuffer.pauseSeconds + 1))
        require(buffer.text == "cd", "A pause clears older characters")
        buffer.append(String(repeating: "x", count: 40), now: start.addingTimeInterval(GlobalKeywordBuffer.pauseSeconds + 1.2))
        require(buffer.text.count == GlobalKeywordBuffer.maxLength, "The buffer never exceeds 32 characters")
        let triggers: Set<String> = [";sig", ";meet", ";sign"]
        require(globalKeywordMatch(buffer: "hello ;sig", triggers: triggers) == ";sig", "A trigger at the end of the buffer matches")
        require(globalKeywordMatch(buffer: ";sig then", triggers: triggers) == nil, "A trigger followed by other text does not match")
        require(globalKeywordMatch(buffer: ";si", triggers: triggers) == nil, "A partial trigger does not match")
        require(globalKeywordMatch(buffer: "x;sign", triggers: triggers) == ";sign", "The longest matching trigger wins")
        require(globalKeywordMatch(buffer: "party", triggers: ["ty"]) == nil, "A word-like trigger does not fire inside a word")
        require(globalKeywordMatch(buffer: "so ty", triggers: ["ty"]) == "ty", "A word-like trigger fires at a word start")
        require(globalKeywordMatch(buffer: "ty", triggers: ["ty"]) == "ty", "A word-like trigger fires at the start of the buffer")
        require(globalKeywordMatch(buffer: "anything", triggers: []) == nil, "No triggers never match")
        require(globalKeywordMatch(buffer: "abc", triggers: [""]) == nil, "An empty trigger never matches")

        let drawerJSON = Data("""
        {"drawers":[
          {"id":"cpu","bar":"CPU 44%","heading":"CPU","big":"44%","sub":"10 cores","rows":[
            {"pid":812,"name":"Chrome","value":"18%","killable":true},
            {"pid":1,"name":"launchd","value":"1%","killable":true},
            {"pid":-4,"name":"bad","value":"1%"},
            {"pid":9,"name":"","value":"1%"}]},
          {"id":"cpu","bar":"dup","heading":"x","big":"x","sub":"x"},
          {"id":"bad id","bar":"x","heading":"x","big":"x","sub":"x"},
          {"id":"mem","bar":"","heading":"x","big":"x","sub":"x"},
          {"id":"disk","bar":"SSD 5%","heading":"Disk","big":"5%","sub":"471 GB free"}]}
        """.utf8)
        let drawers = menuDrawerModels(fromJSON: drawerJSON) ?? []
        require(drawers.map(\.id) == ["cpu", "disk"], "Duplicate, badly named and bar-less drawers are dropped")
        require(drawers[0].rows.count == 2, "Rows with a bad pid or empty name are dropped")
        require(drawers[0].rows[0].killable, "A user process row stays killable")
        require(!drawers[0].rows[1].killable, "pid 1 is never killable")
        require(drawers[1].rows.isEmpty, "A drawer without rows has none")
        require(menuDrawerModels(fromJSON: Data("nope".utf8)) == nil, "Invalid JSON is rejected")
        require(menuDrawerModels(fromJSON: Data("{\"drawers\":1}".utf8)) == nil, "A non-list is rejected")
        require(menuDrawerModels(fromJSON: Data(count: 70 * 1024)) == nil, "Oversized input is rejected")
        let manyRows = (0..<20).map { "{\"pid\":\($0 + 2),\"name\":\"p\($0)\",\"value\":\"1\"}" }.joined(separator: ",")
        let manyDrawers = (0..<11).map { "{\"id\":\"d\($0)\",\"bar\":\"b\",\"heading\":\"h\",\"big\":\"1\",\"sub\":\"s\",\"rows\":[\(manyRows)]}" }.joined(separator: ",")
        let bounded = menuDrawerModels(fromJSON: Data("{\"drawers\":[\(manyDrawers)]}".utf8)) ?? []
        require(bounded.count == 9 && bounded.allSatisfy { $0.rows.count == 8 }, "Drawers and rows are bounded")
        let control = menuDrawerModels(fromJSON: Data("{\"drawers\":[{\"id\":\"a\",\"bar\":\"x\\u0007\",\"heading\":\"h\",\"big\":\"1\",\"sub\":\"s\"}]}".utf8)) ?? []
        require(control.isEmpty, "Control characters are rejected")

        // Detailed drawers: rings, usage history, summary lines, details and the storage action
        let detailJSON = Data("""
        {"drawers":[
          {"id":"ram","bar":"RAM 87%","heading":"Memory","big":"86.9%","sub":"Pressure: Warning · Swap 5.3 GB",
           "rowsTitle":"Top processes",
           "rings":[{"label":"87%","percent":87,"tone":"red","title":"Pressure"},{"label":"5.3G","percent":140,"tone":"blue"},{"label":"x","percent":3,"tone":"green"},{"label":"y","percent":4}],
           "cores":[{"percent":80,"tone":"teal"},{"percent":150,"tone":"nope"},{"percent":"x"},{"percent":5}],
           "summary":[{"label":"Write","value":"2.6 MB/s","tone":"red"}],
           "historyTitle":"Usage history",
           "history":[10,"x",true,-5,250,42.5],
           "details":[{"label":"Used","value":"26.89 GB"},
                      {"bar":[{"percent":28,"tone":"blue"},{"percent":40,"tone":"purple"},{"percent":"no"}]},
                      {"heading":"Average load"},
                      {"label":"","value":"skipped"},
                      {"label":"App","value":"9.56 GB","tone":"blue"},
                      {"bar":[{"percent":"no"}]}],
           "rows":[{"pid":812,"name":"Chrome","value":"1 GB","killable":true}]},
          {"id":"disk","bar":"SSD 33%","heading":"Disk","big":"33%","sub":"Macintosh HD","rows":[],"storage":true},
          {"id":"net","bar":"x","heading":"Network","big":"1","sub":"s","storage":"yes"}]}
        """.utf8)
        let detailed = menuDrawerModels(fromJSON: detailJSON) ?? []
        require(detailed.count == 3, "Detailed drawers parse alongside the headline fields")
        let memory = detailed[0]
        require(memory.rowsTitle == "Top processes", "The process section can carry a title")
        require(memory.rings.count == menuDrawerMaxRings && menuDrawerMaxRings == 3, "Rings are bounded to three")
        require(memory.rings[0].title == "Pressure" && memory.rings[1].title == nil, "A ring can carry a small title")
        require(memory.cores == [MenuDrawerCore(percent: 80, tone: "teal"), MenuDrawerCore(percent: 100, tone: nil), MenuDrawerCore(percent: 5, tone: nil)], "Core bars clamp, drop unknown tones and skip bad values")
        require(detailed[2].cores.isEmpty, "A drawer without cores has none")
        require(memory.rings[0].tone == "red" && memory.rings[0].percent == 87, "Rings keep known tones and percentages")
        require(memory.rings[1].percent == 100 && memory.rings[1].label == "5.3G", "Ring percentages are clamped to 100")
        require(memory.summary == [MenuDrawerLine(label: "Write", value: "2.6 MB/s", tone: "red")], "Summary lines parse")
        require(detailed[2].rings.isEmpty, "A ring list that is missing is empty")
        require(memory.history == [10, 0, 100, 42.5], "History keeps only numeric values, clamped to 0 to 100")
        require(memory.details.count == 4, "Details drop items without a label and empty bars")
        require(memory.details[0] == .line(MenuDrawerLine(label: "Used", value: "26.89 GB", tone: nil)), "A plain line has no colour")
        require(memory.details[1] == .bar([MenuDrawerSegment(percent: 28, tone: "blue"), MenuDrawerSegment(percent: 40, tone: nil)]), "Stacked bars drop unknown tones and bad segments")
        require(memory.details[2] == .heading("Average load"), "Sub-headings parse")
        require(memory.details[3] == .line(MenuDrawerLine(label: "App", value: "9.56 GB", tone: "blue")), "Coloured lines keep a known tone")
        require(memory.storageAction == false && detailed[1].storageAction == true, "Only an explicit true boolean enables the storage action")
        require(detailed[2].storageAction == false, "A string is not an explicit true")
        require(detailed[1].summary.isEmpty, "Missing summary is empty on the disk drawer")
        require(detailed[1].history.isEmpty && detailed[1].details.isEmpty && detailed[1].rings.isEmpty, "Missing optional sections are empty")
        require(menuDrawerButtonCount(memory) == 3 && menuDrawerButtonCount(detailed[2]) == 2, "CPU and RAM disclosure controls stay within the button limit")
        let statsDrawer = MenuDrawerModel(id: "cpu", barText: "CPU", heading: "CPU", big: "10%", subtitle: "Load", rows: [])
        let ramDrawer = MenuDrawerModel(id: "ram", barText: "RAM", heading: "RAM", big: "8 GB", subtitle: "Used", rows: [])
        require(menuDrawerButtonCount(statsDrawer) == 3 && menuDrawerButtonCount(ramDrawer) == 3, "CPU and RAM disclosure controls fit the three-button limit")
        let quitJSON = Data("""
        {"drawers":[{"id":"cpu","bar":"CPU","heading":"CPU","big":"10%","sub":"Load","rows":[{"pid":812,"name":"Editor","value":"2%","killable":true}],"quitFeedback":{"pid":812,"state":"error","message":"Access denied"}}]}
        """.utf8)
        let quitDrawer = menuDrawerModels(fromJSON: quitJSON)?.first
        require(quitDrawer?.quitFeedback == MenuDrawerQuitFeedback(pid: 812, state: "error", message: "Access denied"), "Bounded quit feedback parses for the in-drawer confirmation")
        let invalidQuitFeedbacks: [(String, [String: Any])] = [
            ("lower pid", ["pid": 1, "state": "error", "message": "Access denied"]),
            ("upper pid", ["pid": 4_194_305, "state": "error", "message": "Access denied"]),
            ("unsupported state", ["pid": 812, "state": "success", "message": "Access denied"]),
            ("oversized message", ["pid": 812, "state": "error", "message": String(repeating: "x", count: menuDrawerMaxText + 1)]),
            ("control character", ["pid": 812, "state": "error", "message": "Access\u{0007}denied"]),
        ]
        for (label, feedback) in invalidQuitFeedbacks {
            let drawer: [String: Any] = ["id": "cpu", "bar": "CPU", "heading": "CPU", "big": "10%", "sub": "Load", "quitFeedback": feedback]
            let payload = try! JSONSerialization.data(withJSONObject: ["drawers": [drawer]])
            require(menuDrawerModels(fromJSON: payload)?.first?.quitFeedback == nil, "Invalid quit feedback rejects its \(label) independently")
        }
        let networkJSON = Data("""
        {"drawers":[{"id":"net","bar":"↓12K ↑4K","heading":"Network","big":"","sub":"Updated 10:00 AM","settings":"network","networkCheck":true,"networkCheckBusy":true,"networkCheckAuto":true,
          "networkHealth":{"headline":"Slow: ISP, not Wi-Fi","detail":"The gateway is quick, while internet responses are slow or missing.","tone":"orange","routerTone":"teal","internetTone":"red","connection":"Wi-Fi · en1","router":"Fast · 4 ms","internet":"186 ms","checked":"10:00 AM"}}]}
        """.utf8)
        let network = menuDrawerModels(fromJSON: networkJSON)?.first
        require(network?.networkCheckAction == true && network?.networkCheckBusy == true, "The network drawer preserves the explicit busy action")
        require(network?.networkCheckAuto == true, "The network drawer carries the run-on-open flag")
        require(network?.settingsPane == "network", "Network Settings remains available beside the check action")
        require(network?.networkHealth == MenuDrawerHealth(headline: "Slow: ISP, not Wi-Fi", detail: "The gateway is quick, while internet responses are slow or missing.", tone: "orange", routerTone: "teal", internetTone: "red", connection: "Wi-Fi · en1", router: "Fast · 4 ms", internet: "186 ms", checked: "10:00 AM"), "The Network health result parses with bounded display fields")
        require(network.map(menuDrawerButtonCount) == 3, "The network drawer stays within the three-action limit")
        let malformedHealthJSON = Data("""
        {"drawers":[{"id":"net","bar":"Network","heading":"Network","big":"","sub":"Updated","networkCheck":true,
          "networkHealth":{"headline":"Status","detail":"Details","tone":"orange","internetTone":"red","connection":"Wi-Fi","router":"4 ms","internet":"20 ms","checked":"10:00 AM"}}]}
        """.utf8)
        require(menuDrawerModels(fromJSON: malformedHealthJSON)?.first?.networkHealth == nil, "Incomplete health payloads are not rendered")
        let disk = MenuDrawerModel(id: "d", barText: "b", heading: "h", big: "1", subtitle: "s", rows: [], storageAction: true)
        require(menuDrawerButtonCount(disk) == 3 && menuDrawerButtonCount(disk) <= 3, "The disk drawer stays within three buttons")
        let batteryJSON = Data("{\"drawers\":[{\"id\":\"battery\",\"bar\":\"Battery 76%\",\"heading\":\"Battery\",\"big\":\"76%\",\"sub\":\"Discharging\",\"battery\":true}]}".utf8)
        let batteryDrawer = menuDrawerModels(fromJSON: batteryJSON)?.first
        require(batteryDrawer?.batteryAction == true, "The battery drawer enables its settings action only from a boolean flag")
        if let batteryDrawer {
            require(menuDrawerButtonCount(batteryDrawer) == 2, "The battery drawer keeps Activity Monitor and settings within the button limit")
        }
        let paneJSON = Data("{\"drawers\":[{\"id\":\"b\",\"bar\":\"BT 90%\",\"heading\":\"Bluetooth\",\"big\":\"\",\"sub\":\"s\",\"settings\":\"bluetooth\"},{\"id\":\"x\",\"bar\":\"x\",\"heading\":\"x\",\"big\":\"1\",\"sub\":\"s\",\"settings\":\"file:///etc/passwd\"},{\"id\":\"n\",\"bar\":\"n\",\"heading\":\"n\",\"big\":\"1\",\"sub\":\"s\"}]}".utf8)
        let panes = menuDrawerModels(fromJSON: paneJSON) ?? []
        require(panes.count == 3 && panes[0].settingsPane == "bluetooth", "A drawer can name a known System Settings pane")
        require(panes[1].settingsPane == nil && panes[2].settingsPane == nil, "An unknown pane name is ignored, so nothing the model sends is ever opened")
        require(batteryDrawer?.settingsPane == "battery", "The battery flag opens the battery pane")
        require(menuDrawerSettingsPanes["bluetooth"]?.url == "x-apple.systempreferences:com.apple.BluetoothSettings", "Bluetooth opens its fixed pane")
        require(menuDrawerClampPercent(-4) == 0 && menuDrawerClampPercent(104) == 100 && menuDrawerClampPercent(12.5) == 12.5, "Percentages clamp to 0 to 100")
        require(menuDrawerHistoryFractions([0, 50, 150]) == [0, 0.5, 1], "History fractions scale to the graph height")
        require(menuDrawerActivityMonitorCommand.executable == "/usr/bin/open", "Activity Monitor opens through the fixed system path")
        require(menuDrawerActivityMonitorCommand.arguments == ["-a", "Activity Monitor"], "Activity Monitor opens by name with no shell text")
        let manyHistory = (0..<300).map { "\($0)" }.joined(separator: ",")
        let trimmed = menuDrawerModels(fromJSON: Data("{\"drawers\":[{\"id\":\"c\",\"bar\":\"b\",\"heading\":\"h\",\"big\":\"1\",\"sub\":\"s\",\"history\":[\(manyHistory)]}]}".utf8)) ?? []
        require(trimmed.first?.history.count == menuDrawerMaxHistory, "Usage history is bounded")

        // Launcher quick results
        require(globalCalculate("24*7+12") == "180", "A sum is evaluated")
        require(globalCalculate("2+2*3") == "8", "Multiplication binds tighter than addition")
        require(globalCalculate("(2+2)*3") == "12", "Brackets group")
        require(globalCalculate("((1200*1.18)/12)") == "118", "Nested brackets and decimals work")
        require(globalCalculate("2^10") == "1024", "Powers work")
        require(globalCalculate("2^3^2") == "512", "Powers are right associative")
        require(globalCalculate("-3+5") == "2", "A leading minus works")
        require(globalCalculate("50%") == "0.5", "A postfix percent divides by 100")
        require(globalCalculate("15% of 800") == "120", "N% of M works")
        require(globalCalculate("1,200 + 300") == "1500", "Thousands commas and spaces are ignored")
        require(globalCalculate("6 × 7") == "42" && globalCalculate("6 x 7") == "42" && globalCalculate("84 ÷ 2") == "42", "Alternative operator symbols work")
        require(globalCalculate("0.1+0.2") == "0.3", "Results are rounded to 10 significant digits")
        require(globalCalculate("1/3") == "0.3333333333", "Fractions keep 10 digits")
        require(globalCalculate("42") == nil, "A bare number is not a calculation")
        require(globalCalculate("1/0") == nil, "Division by zero shows nothing")
        require(globalCalculate("2+") == nil && globalCalculate("(2+3") == nil && globalCalculate("2+3)") == nil, "Bad syntax shows nothing")
        require(globalCalculate("safari") == nil && globalCalculate("a+b") == nil, "Words are not calculations")
        require(globalCalculate(String(repeating: "(", count: 40) + "1" + String(repeating: ")", count: 40)) == nil, "Excessive nesting is rejected")
        require(globalCalculate(String(repeating: "1+", count: 100) + "1") == nil, "Overlong input is rejected")
        var counter: UInt8 = 0
        let sequential: (Int) -> [UInt8] = { count in (0..<count).map { _ in counter = counter &+ 37; return counter } }
        let uuid = globalGenerateUUID(random: sequential)
        require(uuid.count == 36 && uuid[uuid.index(uuid.startIndex, offsetBy: 14)] == "4", "A UUID has the v4 layout")
        require(["8", "9", "a", "b"].contains(String(uuid[uuid.index(uuid.startIndex, offsetBy: 19)])), "A UUID has the RFC variant bits")
        require(uuid.filter { $0 == "-" }.count == 4, "A UUID has four dashes")
        for length in [8, 20, 128] {
            let password = globalGeneratePassword(length: length, random: sequential) ?? ""
            require(password.count == length, "A password has the requested length")
            require(password.contains(where: \.isUppercase) && password.contains(where: \.isLowercase)
                    && password.contains(where: \.isNumber) && password.contains(where: { "!@#$%&*?-_+=".contains($0) }),
                    "A password has every character class")
            require(!password.contains(where: { "0O1lI".contains($0) }), "A password has no look-alike characters")
        }
        let symbolsOnlyDash = globalGeneratePassword(length: 32, symbols: "-", random: sequential) ?? ""
        require(symbolsOnlyDash.count == 32 && symbolsOnlyDash.contains("-")
                && symbolsOnlyDash.allSatisfy({ $0.isLetter || $0.isNumber || $0 == "-" }),
                "A custom symbol set is used exclusively")
        let noSymbols = globalGeneratePassword(length: 32, symbols: "", random: sequential) ?? ""
        require(noSymbols.count == 32 && noSymbols.allSatisfy({ $0.isLetter || $0.isNumber }),
                "An empty symbol set makes an alphanumeric password")
        require(globalGeneratePassword(length: 20, symbols: "--", random: sequential) == nil,
                "Duplicate symbols are rejected")
        require(globalGeneratePassword(length: 7, random: sequential) == nil && globalGeneratePassword(length: 129, random: sequential) == nil, "Password length is bounded")
        var biased = [UInt8](repeating: 255, count: 16) // values at or above the rejection limit are skipped
        biased[15] = 3
        require(globalRandomIndex(below: 10, random: { _ in biased }) == 3, "Rejection sampling skips biased values")
        let calc = globalQuickResults(query: "24*7+12", random: sequential)
        require(calc.count == 1 && calc[0].title == "180" && calc[0].kind == "quick" && calc[0].id == "quick:calc", "A sum gives one result row")
        require(globalQuickResults(query: "uuid", random: sequential).count == 2, "uuid gives dashed and plain rows")
        require(globalQuickResults(query: "GUID", random: sequential).count == 2, "guid works in any case")
        require(globalQuickResults(query: "password", random: sequential)[0].title.count == 20, "password defaults to 20 characters")
        let customDefaults = GlobalQuickSwitches(passwordLength: 36, passwordSymbols: "!_")
        let customPassword = globalQuickResults(query: "password", random: sequential, switches: customDefaults)[0].title
        require(customPassword.count == 36 && customPassword.contains(where: { "!_".contains($0) }), "Password settings control launcher defaults")
        require(globalQuickResults(query: "pw", random: sequential, switches: customDefaults)[0].title.count == 36, "The pw keyword uses configured length")
        require(globalQuickResults(query: "pw 12", random: sequential, switches: customDefaults)[0].title.count == 12, "An explicit pw length overrides settings")
        require(globalQuickResults(query: "pw 32", random: sequential)[0].title.count == 32, "pw takes a length")
        require(globalQuickResults(query: "pass 5", random: sequential).isEmpty, "A too-short password length gives nothing")
        require(globalQuickResults(query: "pas", random: sequential).count == 1 && globalQuickResults(query: "pass", random: sequential).count == 1, "A partly typed password keyword works from three letters")
        require(globalQuickResults(query: "passw 12", random: sequential)[0].title.count == 12, "A partly typed keyword takes a length")
        require(globalQuickResults(query: "pa", random: sequential).isEmpty && globalQuickResults(query: "passwords", random: sequential).isEmpty, "Two letters or a longer word do not trigger")
        require(globalQuickResults(query: "uui", random: sequential).count == 2, "A partly typed uuid keyword works from three letters")
        require(globalQuickResults(query: "ui", random: sequential).isEmpty, "Two letters do not trigger uuid")
        let emi = globalQuickResults(query: "emi 500000 8.5% 20y", random: sequential)
        require(emi.count == 2 && emi[0].title == "4,339.12" && emi[1].title == "1,041,386.34" && emi[0].subtitle.contains("541,386.34"), "emi gives the monthly payment")
        require(globalQuickResults(query: "EMI 1,200,000 0 10", random: sequential)[0].title == "10,000.00", "A zero-rate loan divides evenly")
        require(globalQuickResults(query: "loan 12000 12 12m", random: sequential)[0].title == "1,066.19", "Months can be given with m")
        require(globalQuickResults(query: "emi 1000 5", random: sequential).isEmpty && globalQuickResults(query: "emi x 5 5", random: sequential).isEmpty, "Missing or bad numbers give nothing")
        require(globalQuickResults(query: "emi 1000 5 0", random: sequential).isEmpty && globalQuickResults(query: "emi 1000 5 101", random: sequential).isEmpty && globalQuickResults(query: "emi 1000 1001 5", random: sequential).isEmpty, "Out-of-range loan values give nothing")
        require(globalQuickResults(query: "emi 1000 5 2.01", random: sequential).isEmpty, "A tenure that is not whole months gives nothing")
        require(globalQuickResults(query: "compound 10000 7% 10y", random: sequential)[0].title == "20,096.61", "Compound growth matches the calculator")
        require(globalQuickResults(query: "compound 0 6 1 100", random: sequential)[0].title == "1,233.56", "A monthly contribution is added at month end")
        require(globalQuickResults(query: "compound 1000 -100 1", random: sequential).isEmpty && globalQuickResults(query: "compound 1000 5 101", random: sequential).isEmpty, "Out-of-range growth values give nothing")
        require(globalFormatMoney(1234567.891) == "1,234,567.89" && globalFormatMoney(0.5) == "0.50" && globalFormatMoney(-1234.5) == "-1,234.50", "Money is grouped with two decimals")
        require(globalQuickResults(query: "safari", random: sequential).isEmpty && globalQuickResults(query: "", random: sequential).isEmpty, "Ordinary queries give no quick rows")

        // Quick-result switches: each one removes only its own rows.
        let noCalc = GlobalQuickSwitches(calculator: false, uuid: true, password: true)
        require(globalQuickResults(query: "24*7+12", random: sequential, switches: noCalc).isEmpty, "A switched-off calculator gives no sum")
        require(globalQuickResults(query: "emi 500000 8.5% 20y", random: sequential, switches: noCalc).isEmpty, "A switched-off calculator gives no loan rows")
        require(globalQuickResults(query: "uuid", random: sequential, switches: noCalc).count == 2, "Calculator off leaves UUID on")
        let noUUID = GlobalQuickSwitches(calculator: true, uuid: false, password: true)
        require(globalQuickResults(query: "uuid", random: sequential, switches: noUUID).isEmpty && globalQuickResults(query: "guid", random: sequential, switches: noUUID).isEmpty, "A switched-off UUID generator gives no UUID")
        require(globalQuickResults(query: "24*7+12", random: sequential, switches: noUUID).count == 1, "UUID off leaves the calculator on")
        let noPassword = GlobalQuickSwitches(calculator: true, uuid: true, password: false)
        require(globalQuickResults(query: "password", random: sequential, switches: noPassword).isEmpty && globalQuickResults(query: "pw 12", random: sequential, switches: noPassword).isEmpty, "A switched-off password generator gives no password")
        require(globalQuickResults(query: "pw 12", random: sequential, switches: .all).count == 1, "The default switches keep every quick row")

        // Decoding the panel JSON: a missing field keeps the defaults; the chip and switches come through.
        let json = Data(#"{"style":"launcher","title":"Clipboard history","chips":[{"id":"all","label":"All"},{"id":"text","label":"Text"}],"items":[],"initialChip":"text","quickResults":{"calculator":false,"uuid":true,"password":false,"passwordLength":36,"passwordSymbols":"!_"}}"#.utf8)
        let decoded = globalPickerContent(fromJSON: json)
        require(decoded?.initialChip == "text", "The panel opens on the chip it was given")
        require(decoded?.quickResults == GlobalQuickSwitches(calculator: false, uuid: true, password: false, passwordLength: 36, passwordSymbols: "!_"), "Quick password options are read from the panel JSON")
        let bare = globalPickerContent(fromJSON: Data(#"{"items":[]}"#.utf8))
        require(bare?.initialChip == "" && bare?.quickResults == .all, "Missing fields keep the defaults")
        require(GlobalQuickSwitches.all == GlobalQuickSwitches(), "All switches default to on")

        // Window layouts sit with the tools, Finder commands stay with the apps.
        let mixed = [
            GlobalPickerItem(id: "app-notes", title: "Notes", subtitle: "", badge: "", kind: "app", pinned: false, icon: "app:/x"),
            GlobalPickerItem(id: "command-open-trash", title: "Open Trash", subtitle: "", badge: "", kind: "command", pinned: false, icon: "command-open-trash"),
            GlobalPickerItem(id: "command-window-left-half", title: "Left half", subtitle: "", badge: "", kind: "command", pinned: false, icon: "command-window"),
            GlobalPickerItem(id: "tool-pdf", title: "PDF", subtitle: "", badge: "", kind: "tool", pinned: false, icon: "tool"),
        ]
        require(globalPickerFilter(mixed, query: "", chip: "app").map(\.id) == ["app-notes", "command-open-trash"], "Apps chip keeps Finder commands but not window layouts")
        require(globalPickerFilter(mixed, query: "", chip: "tool").map(\.id) == ["command-window-left-half", "tool-pdf"], "Tools chip lists window layouts")
        require(globalPickerFilter(mixed, query: "", chip: "all").count == 4, "All chip lists everything")

        print("macos-global-logic: all tests passed")
    }

    static func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        if !condition() {
            FileHandle.standardError.write(Data("FAILED: \(message)\n".utf8))
            exit(1)
        }
    }
}
