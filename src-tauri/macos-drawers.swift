import AppKit

// Menu-bar drawers: one status item per metric (CPU, RAM, SSD, ...) with a popover under it.
// The web layer owns the data and sends already-formatted text plus bounded history and detail
// values; this file only draws them. Process quit confirmation stays in this drawer, and confirmed
// actions go to the shell. Activity Monitor opens through a fixed system command; the Storage
// analyser asks the shell to open its tool.

private func onMainSync<T>(_ operation: () -> T) -> T {
    Thread.isMainThread ? operation() : DispatchQueue.main.sync(execute: operation)
}

private let drawerContentWidth: CGFloat = 292

/// The colour for a tone the logic layer accepted, or nil when the drawer did not ask for one.
private func drawerColor(_ tone: String?) -> NSColor? {
    switch tone {
    case "blue": return .systemBlue
    case "orange": return .systemOrange
    case "red": return .systemRed
    case "grey": return .systemGray
    case "teal": return .systemTeal
    case "violet": return .systemIndigo
    default: return nil
    }
}

/// A drawn view that takes the next refresh's values in place, so the drawer updates without being rebuilt.
private protocol DrawerAdoptable: NSView {
    /// Copies the values of an equivalent freshly built view; false when it is not equivalent and must be replaced.
    func adopt(_ other: NSView) -> Bool
}

/// A ring gauge with its caption in the centre.
private final class DrawerRingView: NSView, DrawerAdoptable {
    private var percent: Double
    private var caption: String
    private var color: NSColor
    private var title: String?
    private let diameter: CGFloat
    private let titleHeight: CGFloat = 14

    /// `large` is the middle ring of a set of three, drawn bigger like the headline gauge.
    init(_ ring: MenuDrawerRing, large: Bool = false, size: CGFloat? = nil) {
        percent = ring.percent
        caption = ring.label
        title = ring.title
        color = drawerColor(ring.tone) ?? .systemBlue
        diameter = size ?? (large ? 80 : 64)
        let height = diameter + (ring.title == nil ? 0 : titleHeight)
        super.init(frame: NSRect(x: 0, y: 0, width: diameter, height: height))
        wantsLayer = true
        layerContentsRedrawPolicy = .onSetNeedsDisplay
        translatesAutoresizingMaskIntoConstraints = false
        widthAnchor.constraint(equalToConstant: diameter).isActive = true
        heightAnchor.constraint(equalToConstant: height).isActive = true
    }

    required init?(coder: NSCoder) { nil }

    func adopt(_ other: NSView) -> Bool {
        guard let next = other as? DrawerRingView, next.diameter == diameter, (next.title == nil) == (title == nil) else { return false }
        if next.percent != percent || next.caption != caption || next.title != title || next.color != color {
            percent = next.percent
            caption = next.caption
            title = next.title
            color = next.color
            needsDisplay = true
        }
        return true
    }

    override func draw(_ dirtyRect: NSRect) {
        let lift = title == nil ? 0 : titleHeight
        let ringBounds = NSRect(x: 0, y: lift, width: diameter, height: diameter)
        if let title {
            let small: [NSAttributedString.Key: Any] = [
                .font: NSFont.systemFont(ofSize: 9, weight: .medium),
                .foregroundColor: NSColor.secondaryLabelColor,
            ]
            let text = title.uppercased()
            let size = text.size(withAttributes: small)
            text.draw(at: NSPoint(x: bounds.midX - size.width / 2, y: 0), withAttributes: small)
        }
        let rect = ringBounds.insetBy(dx: 4, dy: 4)
        let center = NSPoint(x: rect.midX, y: rect.midY)
        let track = NSBezierPath(ovalIn: rect)
        track.lineWidth = 6
        NSColor.quaternaryLabelColor.setStroke()
        track.stroke()
        if percent > 0 {
            let arc = NSBezierPath()
            arc.appendArc(withCenter: center, radius: rect.width / 2, startAngle: 90,
                          endAngle: 90 - 360 * CGFloat(percent / 100), clockwise: true)
            arc.lineWidth = 6
            arc.lineCapStyle = .round
            color.setStroke()
            arc.stroke()
        }
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 13, weight: .bold),
            .foregroundColor: NSColor.labelColor,
        ]
        let size = caption.size(withAttributes: attributes)
        caption.draw(at: NSPoint(x: center.x - size.width / 2, y: center.y - size.height / 2), withAttributes: attributes)
    }
}

/// Usage history graph; network uses a full-width line while other drawers use recent activity bars.
private final class DrawerHistoryView: NSView, DrawerAdoptable {
    private var fractions: [Double]
    private let lineChart: Bool
    /// How far, in bar slots, the bars still have to slide left after a new sample arrived (1 → 0).
    private var slide: CGFloat = 0
    private var slideTimer: Timer?

    init(values: [Double], lineChart: Bool = false) {
        fractions = menuDrawerHistoryFractions(values)
        self.lineChart = lineChart
        super.init(frame: .zero)
        // Layer-backed, so a new frame replaces the old one whole instead of clearing and redrawing in view.
        wantsLayer = true
        layerContentsRedrawPolicy = .onSetNeedsDisplay
        translatesAutoresizingMaskIntoConstraints = false
        heightAnchor.constraint(equalToConstant: 62).isActive = true
        widthAnchor.constraint(equalToConstant: drawerContentWidth).isActive = true
    }

    required init?(coder: NSCoder) { nil }

    func adopt(_ other: NSView) -> Bool {
        guard let next = other as? DrawerHistoryView, next.lineChart == lineChart else { return false }
        guard next.fractions != fractions else { return true }
        // One new sample: the bars slide left by a slot and the new one enters on the right, nothing else moves.
        let grown = fractions.count >= menuDrawerMaxHistory ? Array(fractions.dropFirst()) : fractions
        let slides = !lineChart && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
            && next.fractions.count == grown.count + 1 && Array(next.fractions.dropLast()) == grown
        fractions = next.fractions
        if slides { startSlide() } else { needsDisplay = true }
        return true
    }

    private func startSlide() {
        slideTimer?.invalidate()
        slide = 1
        let began = CACurrentMediaTime()
        let timer = Timer(timeInterval: 1.0 / 60.0, repeats: true) { [weak self] timer in
            guard let self else { timer.invalidate(); return }
            let progress = min(1, (CACurrentMediaTime() - began) / 0.5)
            self.slide = CGFloat(pow(1 - progress, 3))
            self.needsDisplay = true
            if progress >= 1 { timer.invalidate(); self.slideTimer = nil }
        }
        RunLoop.main.add(timer, forMode: .common)
        slideTimer = timer
    }

    override func draw(_ dirtyRect: NSRect) {
        if lineChart {
            guard !fractions.isEmpty else { return }
            let path = NSBezierPath()
            path.lineWidth = 1.75
            path.lineCapStyle = .round
            path.lineJoinStyle = .round
            for (index, fraction) in fractions.enumerated() {
                let x = fractions.count < 2 ? bounds.midX : bounds.minX + bounds.width * CGFloat(index) / CGFloat(fractions.count - 1)
                let y = bounds.minY + 2 + max(0, bounds.height - 4) * CGFloat(fraction)
                if index == 0 { path.move(to: NSPoint(x: x, y: y)) }
                else { path.line(to: NSPoint(x: x, y: y)) }
            }
            NSColor.systemBlue.setStroke()
            path.stroke()
            return
        }
        let background = NSBezierPath(roundedRect: bounds, xRadius: 8, yRadius: 8)
        NSColor.quaternaryLabelColor.withAlphaComponent(0.35).setFill()
        background.fill()
        let slot = bounds.width / CGFloat(menuDrawerMaxHistory)
        let start = fractions.count
        NSGraphicsContext.current?.saveGraphicsState()
        background.addClip()
        for (index, fraction) in fractions.enumerated() {
            let x = bounds.maxX - CGFloat(start - index) * slot + slide * slot
            let height = max(1, (bounds.height - 4) * CGFloat(fraction))
            NSColor.secondaryLabelColor.withAlphaComponent(0.85).setFill()
            NSRect(x: x + 0.5, y: bounds.minY + 2, width: max(1, slot - 1), height: height).fill()
        }
        NSGraphicsContext.current?.restoreGraphicsState()
    }
}

/// One bar per CPU core, side by side, each as tall as that core's load.
private final class DrawerCoresView: NSView, DrawerAdoptable {
    private var cores: [(fraction: CGFloat, color: NSColor)]

    init(_ items: [MenuDrawerCore]) {
        cores = items.map { (CGFloat($0.percent / 100), drawerColor($0.tone) ?? .systemTeal) }
        super.init(frame: .zero)
        wantsLayer = true
        layerContentsRedrawPolicy = .onSetNeedsDisplay
        translatesAutoresizingMaskIntoConstraints = false
        heightAnchor.constraint(equalToConstant: 44).isActive = true
        widthAnchor.constraint(equalToConstant: drawerContentWidth).isActive = true
    }

    required init?(coder: NSCoder) { nil }

    func adopt(_ other: NSView) -> Bool {
        guard let next = other as? DrawerCoresView else { return false }
        cores = next.cores
        needsDisplay = true
        return true
    }

    override func draw(_ dirtyRect: NSRect) {
        guard !cores.isEmpty else { return }
        let gap: CGFloat = 3
        let width = (bounds.width - gap * CGFloat(cores.count - 1)) / CGFloat(cores.count)
        for (index, core) in cores.enumerated() {
            let x = bounds.minX + CGFloat(index) * (width + gap)
            let track = NSBezierPath(roundedRect: NSRect(x: x, y: bounds.minY, width: width, height: bounds.height), xRadius: 2, yRadius: 2)
            NSColor.quaternaryLabelColor.setFill()
            track.fill()
            core.color.setFill()
            NSBezierPath(roundedRect: NSRect(x: x, y: bounds.minY, width: width, height: max(1, bounds.height * core.fraction)), xRadius: 2, yRadius: 2).fill()
        }
    }
}

/// A stacked bar: each segment is a share of the whole, drawn left to right and never past the end.
private final class DrawerSegmentBar: NSView, DrawerAdoptable {
    private var segments: [(fraction: CGFloat, color: NSColor)]

    init(_ items: [MenuDrawerSegment]) {
        segments = items.map { (CGFloat($0.percent / 100), drawerColor($0.tone) ?? .tertiaryLabelColor) }
        super.init(frame: .zero)
        wantsLayer = true
        layerContentsRedrawPolicy = .onSetNeedsDisplay
        translatesAutoresizingMaskIntoConstraints = false
        heightAnchor.constraint(equalToConstant: 10).isActive = true
    }

    required init?(coder: NSCoder) { nil }

    func adopt(_ other: NSView) -> Bool {
        guard let next = other as? DrawerSegmentBar else { return false }
        segments = next.segments
        needsDisplay = true
        return true
    }

    override func draw(_ dirtyRect: NSRect) {
        let track = NSBezierPath(roundedRect: bounds, xRadius: 5, yRadius: 5)
        NSColor.quaternaryLabelColor.setFill()
        track.fill()
        NSGraphicsContext.current?.saveGraphicsState()
        track.addClip()
        var x = bounds.minX
        for segment in segments {
            let width = min(bounds.maxX - x, bounds.width * max(0, segment.fraction))
            guard width > 0 else { continue }
            segment.color.setFill()
            NSRect(x: x, y: bounds.minY, width: width, height: bounds.height).fill()
            x += width
        }
        NSGraphicsContext.current?.restoreGraphicsState()
    }
}

private let drawerTabTransitionSeconds = 0.4

/// Stays as the popover's one content controller so a refresh swaps the drawer's content inside it:
/// the popover keeps its place and can animate its height instead of being rebuilt.
private final class DrawerHostController: NSViewController {
    private var content: NSView

    init(content: NSView) {
        self.content = content
        super.init(nibName: nil, bundle: nil)
        let host = NSView(frame: NSRect(origin: .zero, size: content.frame.size))
        host.wantsLayer = true
        host.layer?.masksToBounds = true
        place(content, in: host)
        view = host
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    private func place(_ child: NSView, in host: NSView) {
        child.autoresizingMask = [.width, .minYMargin]
        child.frame.origin = NSPoint(x: 0, y: host.bounds.height - child.frame.height)
        host.addSubview(child)
    }

    private var timer: Timer?
    private var leaving: NSView?
    private(set) var isAnimating = false

    /// A routine data refresh: the shown views take the new values in place and only what no longer matches
    /// (a different application row, say) is swapped, so nothing blinks. False when the layout itself changed.
    func update(with next: NSView, in popover: NSPopover?) -> Bool {
        guard !isAnimating, let shown = content as? NSStackView, let fresh = next as? NSStackView,
              Self.merge(shown, fresh) else { return false }
        let size = shown.fittingSize
        if abs(size.height - shown.frame.height) > 0.5 || abs(size.width - shown.frame.width) > 0.5 {
            fit(shown, to: size, in: popover)
        }
        return true
    }

    /// Resizes the host and the shown content together, content filling the host exactly. Resizing only the
    /// content and then letting the popover resize the host moves the top-pinned content by the growth twice,
    /// which clips the top of the drawer and leaves a blank band at the bottom.
    private func fit(_ shown: NSView, to size: NSSize, in popover: NSPopover?) {
        view.setFrameSize(size)
        shown.frame = NSRect(origin: .zero, size: size)
        popover?.contentSize = size
    }

    private static func merge(_ shown: NSStackView, _ fresh: NSStackView) -> Bool {
        let was = shown.arrangedSubviews
        let now = fresh.arrangedSubviews
        guard was.count == now.count else { return false }
        for (index, pair) in zip(was, now).enumerated() where !adopt(pair.0, pair.1) {
            shown.removeArrangedSubview(pair.0)
            pair.0.removeFromSuperview()
            shown.insertArrangedSubview(pair.1, at: index)
        }
        return true
    }

    private static func adopt(_ was: NSView, _ now: NSView) -> Bool {
        if let drawn = was as? DrawerAdoptable { return drawn.adopt(now) }
        if let was = was as? NSTextField, let now = now as? NSTextField {
            if was.stringValue != now.stringValue { was.stringValue = now.stringValue }
            if was.textColor != now.textColor { was.textColor = now.textColor }
            return true
        }
        if let was = was as? NSSegmentedControl, let now = now as? NSSegmentedControl,
           was.identifier == now.identifier, was.segmentCount == now.segmentCount {
            was.selectedSegment = now.selectedSegment
            return true
        }
        if let was = was as? NSButton, let now = now as? NSButton, type(of: was) == type(of: now),
           was.identifier == now.identifier, was.tag == now.tag, was.action == now.action, was.target === now.target {
            if was.title != now.title { was.title = now.title }
            was.isEnabled = now.isEnabled
            was.isHidden = now.isHidden
            return true
        }
        if let was = was as? NSStackView, let now = now as? NSStackView { return merge(was, now) }
        return false
    }

    /// The views under the tab bar; the whole drawer when it has none.
    private static func body(of drawer: NSView) -> [NSView] {
        guard let stack = drawer as? NSStackView,
              let tabs = stack.arrangedSubviews.firstIndex(where: { $0.identifier?.rawValue.hasPrefix("drawer-tabs-") == true })
        else { return [drawer] }
        return Array(stack.arrangedSubviews[(tabs + 1)...])
    }

    private func finishAnimation() {
        timer?.invalidate()
        timer = nil
        leaving?.removeFromSuperview()
        leaving = nil
        content.alphaValue = 1
        (content as? NSStackView)?.arrangedSubviews.forEach { $0.alphaValue = 1 }
        isAnimating = false
    }

    /// NSPopover resizes itself in a couple of frames and ignores a longer curve, so the height is stepped
    /// here on every frame: an ease-out that settles softly, with the old body fading out before the new one fades in.
    func show(_ next: NSView, in popover: NSPopover?, animated: Bool) {
        finishAnimation()
        let previous = content
        content = next
        let end = next.frame.size
        guard animated, let popover else {
            previous.removeFromSuperview()
            popover?.contentSize = end
            place(next, in: view)
            return
        }
        let start = popover.contentSize
        // Everything down to the tab bar is the same before and after, so it swaps at once and never fades;
        // only the part under the tabs crossfades.
        let oldBody = Self.body(of: previous)
        let newBody = Self.body(of: next)
        if let old = previous as? NSStackView {
            old.arrangedSubviews.filter { view in !oldBody.contains(where: { $0 === view }) }.forEach { $0.alphaValue = 0 }
        }
        newBody.forEach { $0.alphaValue = 0 }
        place(next, in: view)
        leaving = previous
        isAnimating = true
        let began = CACurrentMediaTime()
        let timer = Timer(timeInterval: 1.0 / 60.0, repeats: true) { [weak self, weak popover] _ in
            guard let self else { return }
            let progress = min(1, (CACurrentMediaTime() - began) / drawerTabTransitionSeconds)
            let eased = 1 - pow(1 - progress, 4)
            popover?.contentSize = NSSize(
                width: start.width + (end.width - start.width) * eased,
                height: start.height + (end.height - start.height) * eased
            )
            oldBody.forEach { $0.alphaValue = CGFloat(max(0, 1 - progress / 0.25)) }
            newBody.forEach { $0.alphaValue = CGFloat(min(1, max(0, (progress - 0.15) / 0.5))) }
            if progress >= 1 { self.finishAnimation() }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }
}

/// Receives keyboard focus while a process quit is in progress, when the dialog has no active action.
private final class DrawerFocusableStackView: NSStackView {
    override var acceptsFirstResponder: Bool { true }
}

/// A small coloured square used as the key for a line.
private final class DrawerDotView: NSView {
    private var color: NSColor

    init(_ color: NSColor) {
        self.color = color
        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        widthAnchor.constraint(equalToConstant: 10).isActive = true
        heightAnchor.constraint(equalToConstant: 10).isActive = true
    }

    required init?(coder: NSCoder) { nil }

    func setColor(_ next: NSColor) {
        color = next
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        color.setFill()
        NSBezierPath(roundedRect: bounds, xRadius: 3, yRadius: 3).fill()
    }
}

/// The network check result: a tinted, rounded banner across the full width, with the headline and the time it
/// was checked on one line and the explanation under it. Left-aligned like the rows around it.
private final class DrawerBannerView: NSStackView, DrawerAdoptable {
    private var tint: NSColor
    private var dot: DrawerDotView
    private let headline: NSTextField
    private let time: NSTextField
    private let detail: NSTextField

    init(tint: NSColor, headline headlineText: String, time timeText: String, detail detailText: String) {
        self.tint = tint
        dot = DrawerDotView(tint)
        headline = NSTextField(wrappingLabelWithString: headlineText)
        time = NSTextField(labelWithString: timeText)
        detail = NSTextField(wrappingLabelWithString: detailText)
        super.init(frame: .zero)
        orientation = .vertical
        alignment = .leading
        spacing = 3
        edgeInsets = NSEdgeInsets(top: 9, left: 11, bottom: 9, right: 11)
        headline.font = .systemFont(ofSize: 12, weight: .semibold)
        headline.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        headline.setContentHuggingPriority(.defaultLow, for: .horizontal)
        time.font = .systemFont(ofSize: 10)
        time.textColor = .tertiaryLabelColor
        time.alignment = .right
        time.setContentHuggingPriority(.required, for: .horizontal)
        detail.font = .systemFont(ofSize: 11)
        detail.textColor = .secondaryLabelColor
        detail.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let top = NSStackView(views: [dot, headline, time])
        top.orientation = .horizontal
        top.alignment = .firstBaseline
        top.spacing = 7
        top.distribution = .fill
        applyTint()
        addArrangedSubview(top)
        addArrangedSubview(detail)
        // Inside the insets the banner is as wide as the rows; the text wraps within it.
        widthAnchor.constraint(equalToConstant: drawerContentWidth).isActive = true
        top.widthAnchor.constraint(equalToConstant: drawerContentWidth - 22).isActive = true
        detail.widthAnchor.constraint(equalToConstant: drawerContentWidth - 22).isActive = true
        headline.preferredMaxLayoutWidth = drawerContentWidth - 22 - 17 - 56
        detail.preferredMaxLayoutWidth = drawerContentWidth - 22
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    private func applyTint() {
        headline.textColor = tint
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        let shape = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5), xRadius: 10, yRadius: 10)
        tint.withAlphaComponent(0.12).setFill()
        shape.fill()
        tint.withAlphaComponent(0.35).setStroke()
        shape.lineWidth = 1
        shape.stroke()
    }

    func adopt(_ other: NSView) -> Bool {
        guard let next = other as? DrawerBannerView else { return false }
        if headline.stringValue != next.headline.stringValue { headline.stringValue = next.headline.stringValue }
        if time.stringValue != next.time.stringValue { time.stringValue = next.time.stringValue }
        if detail.stringValue != next.detail.stringValue { detail.stringValue = next.detail.stringValue }
        if tint != next.tint {
            tint = next.tint
            dot.setColor(next.tint)
            applyTint()
        }
        return true
    }
}

private final class MenuDrawerController: NSObject, NSPopoverDelegate {
    static let shared = MenuDrawerController()

    var quitCallback: (@convention(c) (Int32) -> Void)?
    var quitCancelCallback: (@convention(c) (Int32) -> Void)?
    var storageCallback: (@convention(c) () -> Void)?
    var networkCheckCallback: (@convention(c) () -> Void)?
    private var order: [String] = []
    private var models: [String: MenuDrawerModel] = [:]
    private var items: [String: NSStatusItem] = [:]
    private var popover: NSPopover?
    private var openID: String?
    private var activityProcess: Process?
    /// CPU and RAM drawers currently on their History and details tab; the rest show Applications.
    private var statsHistoryTab = Set<String>()
    private var pendingQuitPid: Int32?
    private var quitInProgress = false
    private var quitError: String?
    private var lastQuitAnnouncement: String?

    func update(_ newModels: [MenuDrawerModel]) {
        order = newModels.map(\.id)
        models = Dictionary(uniqueKeysWithValues: newModels.map { ($0.id, $0) })
        if let pendingQuitPid {
            let rowModel = newModels.first { $0.rows.contains(where: { $0.pid == Int(pendingQuitPid) }) }
            if rowModel == nil {
                clearPendingQuit()
            } else if let feedback = rowModel?.quitFeedback, feedback.pid == Int(pendingQuitPid) {
                quitInProgress = feedback.state == "working"
                quitError = feedback.state == "error" ? feedback.message : nil
            }
        }
        for stale in items.keys where models[stale] == nil {
            NSStatusBar.system.removeStatusItem(items[stale]!)
            items[stale] = nil
            if openID == stale { closePopover() }
        }
        // Items are created in reverse so the first drawer ends up leftmost.
        for id in order.reversed() where items[id] == nil {
            let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
            item.button?.target = self
            item.button?.action = #selector(toggle(_:))
            item.button?.identifier = NSUserInterfaceItemIdentifier(id)
            items[id] = item
        }
        for (id, model) in models {
            items[id]?.button?.title = model.barText
        }
        if openID != nil, popover?.isShown == true {
            refreshOpenPopover()
        }
    }

    func remove() {
        closePopover()
        for item in items.values { NSStatusBar.system.removeStatusItem(item) }
        items = [:]
        models = [:]
        order = []
    }

    @objc private func toggle(_ sender: NSStatusBarButton) {
        guard let id = sender.identifier?.rawValue, let model = models[id] else { return }
        if openID == id, popover?.isShown == true {
            closePopover()
            return
        }
        closePopover()
        let popover = NSPopover()
        popover.behavior = .transient
        popover.delegate = self
        popover.contentViewController = DrawerHostController(content: makeViewController(model).view)
        popover.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
        self.popover = popover
        openID = id
        // Opening the Network drawer starts the check itself when the last result is old; the web layer decides that.
        if model.networkCheckAction, model.networkCheckAuto, !model.networkCheckBusy {
            networkCheckCallback?()
        }
    }

    private func closePopover() {
        popover?.performClose(nil)
        popover = nil
        openID = nil
        resetDrawerState()
    }

    func popoverDidClose(_ notification: Notification) {
        // Closing one drawer to open another reports the old close late; it must not clear the new drawer.
        if let closed = notification.object as? NSPopover, let current = popover, closed !== current { return }
        popover = nil
        openID = nil
        resetDrawerState()
    }

    private func resetDrawerState() {
        statsHistoryTab.removeAll()
        clearPendingQuit()
    }

    private func clearPendingQuit() {
        pendingQuitPid = nil
        quitInProgress = false
        quitError = nil
        lastQuitAnnouncement = nil
    }

    private func drawerView(with identifier: String, in view: NSView) -> NSView? {
        if view.identifier?.rawValue == identifier { return view }
        for child in view.subviews {
            if let match = drawerView(with: identifier, in: child) { return match }
        }
        return nil
    }

    private func refreshOpenPopover(focusIdentifier: String? = nil, animated: Bool = false) {
        guard let openID, let model = models[openID], popover?.isShown == true else { return }
        // A press in progress would be lost if the buttons under the pointer were rebuilt; the next update applies it.
        if !animated, focusIdentifier == nil, NSEvent.pressedMouseButtons != 0 { return }
        guard let host = popover?.contentViewController as? DrawerHostController else { return }
        // A routine data refresh waits for a running tab transition instead of cutting it short.
        if !animated, focusIdentifier == nil, host.isAnimating { return }
        let oldWindow = host.view.window
        let oldFocus = (oldWindow?.firstResponder as? NSView)?.identifier?.rawValue
        let content = makeViewController(model).view
        // A routine data refresh updates the shown views in place; only a changed layout, a tab switch or a
        // quit prompt swaps the content.
        if !animated, focusIdentifier == nil, pendingQuitPid == nil, host.update(with: content, in: popover) {
            return
        }
        // Switching tabs eases the drawer to its new height while the old content fades out and the new fades in;
        // with Reduce Motion on, or for any other refresh, the drawer changes at once.
        let ease = animated && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        host.show(content, in: popover, animated: ease)
        let targetIdentifier = focusIdentifier ?? oldFocus
        if let targetIdentifier {
            DispatchQueue.main.async { [weak self, weak content] in
                guard let self, let content, let window = content.window,
                      let target = self.drawerView(with: targetIdentifier, in: content),
                      (target as? NSControl)?.isEnabled ?? true else { return }
                window.makeFirstResponder(target)
            }
        }
        if pendingQuitPid != nil {
            let announcement = quitError ?? (quitInProgress ? "Closing the selected application." : "Quit confirmation. Unsaved work may be lost.")
            if lastQuitAnnouncement != announcement {
                lastQuitAnnouncement = announcement
                DispatchQueue.main.async { [weak content] in
                    guard let content else { return }
                    NSAccessibility.post(element: content, notification: .announcementRequested,
                                         userInfo: [.announcement: announcement, .priority: NSAccessibilityPriorityLevel.medium.rawValue])
                }
            }
        }
    }

    private func sectionLabel(_ text: String) -> NSTextField {
        let label = NSTextField(labelWithString: text.uppercased())
        label.font = .systemFont(ofSize: 10, weight: .semibold)
        label.textColor = .secondaryLabelColor
        return label
    }

    private func centred(_ views: [NSView], spread: Bool = false) -> NSStackView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = spread ? 0 : 16
        if spread {
            row.distribution = .equalSpacing
            row.widthAnchor.constraint(equalToConstant: drawerContentWidth).isActive = true
        } else {
            let leading = NSView()
            let trailing = NSView()
            for spacer in [leading, trailing] { spacer.setContentHuggingPriority(.defaultLow, for: .horizontal) }
            row.addArrangedSubview(leading)
            views.forEach { row.addArrangedSubview($0) }
            row.addArrangedSubview(trailing)
        }
        if spread { views.forEach { row.addArrangedSubview($0) } }
        return row
    }

    private func networkHealthView(_ health: MenuDrawerHealth?) -> NSView {
        let card = NSStackView()
        card.orientation = .vertical
        card.alignment = .leading
        card.spacing = 4
        card.widthAnchor.constraint(equalToConstant: drawerContentWidth).isActive = true

        // The result is one tinted banner on the same left and right edges as the rows below it.
        card.addArrangedSubview(DrawerBannerView(
            tint: drawerColor(health?.tone) ?? .secondaryLabelColor,
            headline: health?.headline ?? "Run a check to compare your router and internet",
            time: health?.checked ?? "",
            detail: health?.detail ?? "No diagnostic probes run until you ask."
        ))
        if let health {
            card.addArrangedSubview(lineView(MenuDrawerLine(label: "Connection", value: health.connection, tone: nil)))
            card.addArrangedSubview(lineView(MenuDrawerLine(label: "Router", value: health.router, tone: health.routerTone)))
            card.addArrangedSubview(lineView(MenuDrawerLine(label: "Internet", value: health.internet, tone: health.internetTone)))
        }
        return card
    }

    private func lineView(_ line: MenuDrawerLine) -> NSStackView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8
        if let color = drawerColor(line.tone) {
            row.addArrangedSubview(DrawerDotView(color))
        }
        let name = NSTextField(labelWithString: line.label)
        name.font = .systemFont(ofSize: 12)
        name.lineBreakMode = .byTruncatingTail
        name.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        name.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let value = NSTextField(labelWithString: line.value)
        value.font = .monospacedDigitSystemFont(ofSize: 12, weight: .semibold)
        value.textColor = drawerColor(line.tone) ?? .secondaryLabelColor
        value.alignment = .right
        value.setContentHuggingPriority(.required, for: .horizontal)
        row.distribution = .fill
        row.addArrangedSubview(name)
        row.addArrangedSubview(value)
        // A fixed row width keeps the label on the left edge and the value on the right edge.
        row.widthAnchor.constraint(equalToConstant: drawerContentWidth).isActive = true
        return row
    }

    private func detailView(_ detail: MenuDrawerDetail) -> NSView {
        switch detail {
        case .line(let line):
            return lineView(line)
        case .heading(let text):
            return sectionLabel(text)
        case .bar(let segments):
            return DrawerSegmentBar(segments)
        }
    }

    private func appendUsageHistoryAndDetails(_ model: MenuDrawerModel, to stack: NSStackView) {
        if let history = model.historyTitle ?? (model.history.isEmpty ? nil : "Usage history") {
            stack.addArrangedSubview(sectionLabel(history))
            stack.addArrangedSubview(DrawerHistoryView(values: model.history, lineChart: model.id == "net"))
        }
        if !model.cores.isEmpty {
            stack.addArrangedSubview(sectionLabel("Cores"))
            stack.addArrangedSubview(DrawerCoresView(model.cores))
        }
        if !model.details.isEmpty {
            stack.addArrangedSubview(sectionLabel("Details"))
            model.details.forEach { stack.addArrangedSubview(detailView($0)) }
        }
    }

    /// Two tabs under the gauges: the top applications, or the usage history and details.
    private func statsTabs(for model: MenuDrawerModel) -> NSSegmentedControl {
        let tabs = NSSegmentedControl(
            labels: ["Applications", "History and details"], trackingMode: .selectOne,
            target: self, action: #selector(selectStatsTab(_:))
        )
        tabs.identifier = NSUserInterfaceItemIdentifier("drawer-tabs-\(model.id)")
        tabs.selectedSegment = statsHistoryTab.contains(model.id) ? 1 : 0
        tabs.controlSize = .small
        tabs.segmentDistribution = .fillEqually
        tabs.refusesFirstResponder = false
        tabs.focusRingType = .default
        tabs.setAccessibilityLabel("\(model.heading) view")
        return tabs
    }

    private func makeViewController(_ model: MenuDrawerModel) -> NSViewController {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .width
        stack.spacing = 6
        stack.edgeInsets = NSEdgeInsets(top: 14, left: 14, bottom: 14, right: 14)
        let activeQuitRow = pendingQuitPid.flatMap { pid in model.rows.first(where: { $0.pid == Int(pid) }) }

        let heading = NSTextField(labelWithString: model.heading)
        heading.font = .systemFont(ofSize: 13, weight: .semibold)
        heading.setContentHuggingPriority(.defaultLow, for: .horizontal)
        var headerViews: [NSView] = [heading]
        if activeQuitRow == nil {
            let link = PointerButton(title: "Activity Monitor ↗", target: self, action: #selector(openActivityMonitor(_:)))
            link.identifier = NSUserInterfaceItemIdentifier("drawer-activity-monitor")
            link.bezelStyle = .inline
            link.font = .systemFont(ofSize: 11)
            link.refusesFirstResponder = true
            link.focusRingType = .none
            headerViews.append(link)
        }
        let header = NSStackView(views: headerViews)
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 8
        stack.addArrangedSubview(header)

        let big = NSTextField(labelWithString: model.big)
        big.font = .systemFont(ofSize: 28, weight: .bold)
        let sub = NSTextField(labelWithString: model.subtitle)
        sub.font = .systemFont(ofSize: 12)
        sub.textColor = .secondaryLabelColor
        // A drawer led by gauges leaves the big number out; the rings carry it.
        if !model.big.isEmpty { stack.addArrangedSubview(big) }
        stack.addArrangedSubview(sub)

        if !model.rings.isEmpty {
            let threeUp = model.rings.count == 3
            let network = model.id == "net"
            stack.addArrangedSubview(centred(model.rings.enumerated().map { DrawerRingView($1, large: threeUp && $0 == 1, size: network ? 68 : nil) }, spread: network))
        }
        model.summary.forEach { stack.addArrangedSubview(lineView($0)) }
        let collapsibleStats = model.id == "cpu" || model.id == "ram"
        var showHistoryTab = false
        if collapsibleStats {
            if !model.history.isEmpty || !model.cores.isEmpty || !model.details.isEmpty {
                stack.addArrangedSubview(statsTabs(for: model))
                showHistoryTab = statsHistoryTab.contains(model.id)
                if showHistoryTab {
                    appendUsageHistoryAndDetails(model, to: stack)
                }
            }
        } else {
            appendUsageHistoryAndDetails(model, to: stack)
        }
        // The Cloudflare link is a plain text link under the footer buttons, not a boxed button.
        var speedTestLink: NSButton?
        if model.id == "net" {
            stack.addArrangedSubview(networkHealthView(model.networkHealth))
            let speedTest = PointerButton(title: "Cloudflare Speed Test ↗", target: self, action: #selector(openCloudflareSpeedTest(_:)))
            speedTest.isBordered = false
            speedTest.font = .systemFont(ofSize: 11)
            // Centred under the two buttons, across the full row width.
            speedTest.alignment = .center
            speedTest.widthAnchor.constraint(equalToConstant: drawerContentWidth).isActive = true
            speedTest.contentTintColor = .linkColor
            speedTest.setAccessibilityLabel("Open Cloudflare Speed Test in your browser")
            speedTest.refusesFirstResponder = false
            speedTest.focusRingType = .default
            speedTestLink = speedTest
        }
        if !showHistoryTab, !model.rows.isEmpty, let title = model.rowsTitle {
            stack.addArrangedSubview(sectionLabel(title))
        }

        for row in (showHistoryTab ? [] : model.rows) {
            let line = NSStackView()
            line.orientation = .horizontal
            line.spacing = 8
            let name = NSTextField(labelWithString: row.name)
            name.font = .systemFont(ofSize: 12)
            name.lineBreakMode = .byTruncatingTail
            name.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
            name.setContentHuggingPriority(.defaultLow, for: .horizontal)
            let nameContent: NSView
            if let detail = row.detail {
                let caption = NSTextField(labelWithString: detail)
                caption.font = .systemFont(ofSize: 10)
                caption.textColor = .secondaryLabelColor
                caption.lineBreakMode = .byTruncatingTail
                caption.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
                caption.setContentHuggingPriority(.defaultLow, for: .horizontal)
                let textStack = NSStackView(views: [name, caption])
                textStack.orientation = .vertical
                textStack.alignment = .leading
                textStack.spacing = 2
                nameContent = textStack
            } else {
                nameContent = name
            }
            let value = NSTextField(labelWithString: row.value)
            value.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
            value.textColor = .secondaryLabelColor
            value.alignment = .right
            value.widthAnchor.constraint(equalToConstant: 64).isActive = true
            line.distribution = .fill
            line.widthAnchor.constraint(equalToConstant: drawerContentWidth).isActive = true
            line.addArrangedSubview(nameContent)
            line.addArrangedSubview(value)
            // Every row reserves the same Quit column so values line up whether or not a row can be quit.
            let isPendingQuit = pendingQuitPid == Int32(row.pid)
            let quit = PointerButton(title: "Quit", target: self, action: #selector(quitRow(_:)))
            quit.bezelStyle = .inline
            quit.tag = row.pid
            quit.identifier = NSUserInterfaceItemIdentifier("drawer-quit-\(row.pid)")
            quit.isHidden = !row.killable
            quit.isEnabled = !isPendingQuit
            quit.refusesFirstResponder = false
            quit.focusRingType = .default
            quit.widthAnchor.constraint(equalToConstant: 44).isActive = true
            line.addArrangedSubview(quit)
            stack.addArrangedSubview(line)
        }

        if let activeQuitRow {
            stack.addArrangedSubview(processQuitPrompt(for: activeQuitRow))
        }

        // Footer: full-width buttons stacked, so a second button never runs past the card edge.
        var footerButtons: [NSView] = []
        let pane = model.settingsPane
        // Activity Monitor already has its link in the header, so a drawer with neither a settings pane nor a
        // network check has no primary button here.
        if model.networkCheckAction || pane != nil {
            let primary = PointerButton(
                title: model.networkCheckAction ? (model.networkCheckBusy ? "Checking…" : model.networkHealth == nil ? "Run network check" : "Run again") : pane.flatMap { menuDrawerSettingsPanes[$0]?.title } ?? "Open settings",
                target: self,
                action: model.networkCheckAction ? #selector(runNetworkCheck(_:)) : #selector(openSettingsPane(_:))
            )
            primary.isEnabled = !model.networkCheckBusy && activeQuitRow == nil
            primary.identifier = NSUserInterfaceItemIdentifier("drawer-primary-\(model.id)")
            primary.identifier = pane.map { NSUserInterfaceItemIdentifier($0) }
            primary.bezelStyle = .rounded
            primary.bezelColor = .controlAccentColor
            primary.refusesFirstResponder = !model.networkCheckAction
            primary.focusRingType = model.networkCheckAction ? .default : .none
            footerButtons.append(primary)
            if activeQuitRow == nil, model.networkCheckAction, let pane, let settingsTitle = menuDrawerSettingsPanes[pane]?.title {
                // "Open Network settings" is shortened so the two buttons fit side by side at equal width.
                let settings = PointerButton(title: settingsTitle.replacingOccurrences(of: "Open ", with: ""), target: self, action: #selector(openSettingsPane(_:)))
                settings.identifier = NSUserInterfaceItemIdentifier(pane)
                settings.setAccessibilityLabel(settingsTitle)
                settings.bezelStyle = .rounded
                settings.refusesFirstResponder = false
                settings.focusRingType = .default
                // Pinned edge to edge with explicit constraints: a nested fill-equally stack kept its own narrower
                // width and sat against the right edge instead of lining up with the rows.
                let pair = NSView()
                pair.translatesAutoresizingMaskIntoConstraints = false
                for button in [primary, settings] {
                    button.translatesAutoresizingMaskIntoConstraints = false
                    pair.addSubview(button)
                    button.topAnchor.constraint(equalTo: pair.topAnchor).isActive = true
                    button.bottomAnchor.constraint(equalTo: pair.bottomAnchor).isActive = true
                }
                primary.leadingAnchor.constraint(equalTo: pair.leadingAnchor).isActive = true
                settings.trailingAnchor.constraint(equalTo: pair.trailingAnchor).isActive = true
                settings.leadingAnchor.constraint(equalTo: primary.trailingAnchor, constant: 8).isActive = true
                primary.widthAnchor.constraint(equalTo: settings.widthAnchor).isActive = true
                pair.widthAnchor.constraint(equalToConstant: drawerContentWidth).isActive = true
                footerButtons = [pair]
            }
        }
        if activeQuitRow == nil, model.storageAction {
            let storage = PointerButton(title: "Open Storage analyser", target: self, action: #selector(openStorage(_:)))
            storage.bezelStyle = .rounded
            storage.refusesFirstResponder = true
            footerButtons.append(storage)
        }
        if let speedTestLink, activeQuitRow == nil { footerButtons.append(speedTestLink) }
        if activeQuitRow == nil, !footerButtons.isEmpty {
            let footer = NSStackView(views: footerButtons)
            footer.orientation = .vertical
            footer.alignment = .width
            footer.spacing = 6
            // As wide as the rows above, so the buttons and the link line up with them instead of hugging the right edge.
            footer.widthAnchor.constraint(equalToConstant: drawerContentWidth).isActive = true
            stack.addArrangedSubview(footer)
        }

        let controller = NSViewController()
        controller.view = stack
        stack.widthAnchor.constraint(equalToConstant: drawerContentWidth + 28).isActive = true
        stack.setFrameSize(stack.fittingSize)
        return controller
    }

    @objc private func quitRow(_ sender: NSButton) {
        let pid = Int32(sender.tag)
        guard pid >= 2 else { return }
        pendingQuitPid = pid
        quitInProgress = false
        quitError = nil
        refreshOpenPopover(focusIdentifier: "drawer-quit-cancel")
    }

    private func processQuitPrompt(for row: MenuDrawerRow) -> NSView {
        let card = DrawerFocusableStackView()
        card.orientation = .vertical
        card.alignment = .width
        card.spacing = 7
        card.edgeInsets = NSEdgeInsets(top: 10, left: 10, bottom: 10, right: 10)
        card.wantsLayer = true
        card.layer?.cornerRadius = 8
        card.layer?.borderWidth = 1
        card.layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.55).cgColor
        card.layer?.backgroundColor = NSColor.windowBackgroundColor.withAlphaComponent(0.3).cgColor
        card.widthAnchor.constraint(equalToConstant: drawerContentWidth).isActive = true
        card.identifier = NSUserInterfaceItemIdentifier("drawer-quit-status")
        card.focusRingType = .default

        let title = NSTextField(labelWithString: "Quit \(row.name)?")
        title.font = .systemFont(ofSize: 12, weight: .semibold)
        card.addArrangedSubview(title)
        let message = NSTextField(wrappingLabelWithString: quitError ?? (quitInProgress
            ? "Closing this application. The menu stays open."
            : "Unsaved work may be lost. OfficeKit stays in the background."))
        message.identifier = NSUserInterfaceItemIdentifier("drawer-quit-status")
        message.font = .systemFont(ofSize: 11)
        message.textColor = quitError == nil ? .secondaryLabelColor : .systemRed
        card.addArrangedSubview(message)
        card.setAccessibilityElement(true)
        card.setAccessibilityRole(.group)
        card.setAccessibilityLabel("Quit confirmation for \(row.name)")

        if !quitInProgress {
            let actions = NSStackView()
            actions.orientation = .horizontal
            actions.alignment = .centerY
            actions.distribution = .fillEqually
            actions.spacing = 8
            let cancel = PointerButton(title: "Cancel", target: self, action: #selector(cancelQuit(_:)))
            cancel.tag = row.pid
            cancel.identifier = NSUserInterfaceItemIdentifier("drawer-quit-cancel")
            cancel.bezelStyle = .rounded
            cancel.refusesFirstResponder = false
            cancel.focusRingType = .default
            let confirm = PointerButton(title: quitError == nil ? "Quit \(row.name)" : "Try again", target: self, action: #selector(confirmQuit(_:)))
            confirm.tag = row.pid
            confirm.bezelStyle = .rounded
            confirm.bezelColor = .controlAccentColor
            confirm.refusesFirstResponder = false
            confirm.focusRingType = .default
            confirm.setAccessibilityLabel(quitError == nil ? "Confirm quit \(row.name)" : "Retry quitting \(row.name)")
            actions.addArrangedSubview(cancel)
            actions.addArrangedSubview(confirm)
            card.addArrangedSubview(actions)
        } else {
            let working = NSTextField(labelWithString: "Closing…")
            working.font = .systemFont(ofSize: 11, weight: .medium)
            working.textColor = .secondaryLabelColor
            card.addArrangedSubview(working)
        }
        return card
    }

    @objc private func cancelQuit(_ sender: NSButton) {
        let pid = pendingQuitPid
        clearPendingQuit()
        refreshOpenPopover(focusIdentifier: pid.map { "drawer-quit-\($0)" })
        if let pid { quitCancelCallback?(pid) }
    }

    @objc private func confirmQuit(_ sender: NSButton) {
        guard let pid = pendingQuitPid, pid == Int32(sender.tag), !quitInProgress else { return }
        quitInProgress = true
        quitError = nil
        refreshOpenPopover(focusIdentifier: "drawer-quit-status")
        quitCallback?(pid)
    }

    @objc private func selectStatsTab(_ sender: NSSegmentedControl) {
        guard let id = sender.identifier?.rawValue.replacingOccurrences(of: "drawer-tabs-", with: ""),
              models[id] != nil else { return }
        if sender.selectedSegment == 1 { statsHistoryTab.insert(id) }
        else { statsHistoryTab.remove(id) }
        refreshOpenPopover(animated: true)
    }

    /// Opens Activity Monitor with the fixed system command: no shell, no interpolated text, nothing logged.
    @objc private func openActivityMonitor(_ sender: NSButton) {
        closePopover()
        let command = menuDrawerActivityMonitorCommand
        let process = Process()
        process.executableURL = URL(fileURLWithPath: command.executable)
        process.arguments = command.arguments
        activityProcess = process
        try? process.run()
    }

    /// Opens one of the fixed System Settings panes named by the button's identifier; unknown names do nothing.
    @objc private func openSettingsPane(_ sender: NSButton) {
        closePopover()
        guard let key = sender.identifier?.rawValue, let address = menuDrawerSettingsPanes[key]?.url,
              let url = URL(string: address) else { return }
        NSWorkspace.shared.open(url)
    }

    @objc private func openStorage(_ sender: NSButton) {
        closePopover()
        storageCallback?()
    }

    @objc private func runNetworkCheck(_ sender: NSButton) {
        networkCheckCallback?()
    }

    /// Opens the fixed Cloudflare speed test URL; no URL is accepted from the WebView payload.
    @objc private func openCloudflareSpeedTest(_ sender: NSButton) {
        NSWorkspace.shared.open(URL(string: "https://speed.cloudflare.com/")!)
    }
}

@_cdecl("officekit_drawers_set_callback")
public func officekitDrawersSetCallback(_ callback: @escaping @convention(c) (Int32) -> Void) {
    MenuDrawerController.shared.quitCallback = callback
}

@_cdecl("officekit_drawers_set_quit_cancel_callback")
public func officekitDrawersSetQuitCancelCallback(_ callback: @escaping @convention(c) (Int32) -> Void) {
    MenuDrawerController.shared.quitCancelCallback = callback
}

@_cdecl("officekit_drawers_set_storage_callback")
public func officekitDrawersSetStorageCallback(_ callback: @escaping @convention(c) () -> Void) {
    MenuDrawerController.shared.storageCallback = callback
}

@_cdecl("officekit_drawers_set_network_check_callback")
public func officekitDrawersSetNetworkCheckCallback(_ callback: @escaping @convention(c) () -> Void) {
    MenuDrawerController.shared.networkCheckCallback = callback
}

/// Replaces the drawers. Returns 4 for invalid content.
@_cdecl("officekit_drawers_update")
public func officekitDrawersUpdate(_ bytes: UnsafePointer<UInt8>?, _ length: UInt64) -> Int32 {
    guard let bytes, length > 0, length <= 64 * 1024,
          let models = menuDrawerModels(fromJSON: Data(bytes: bytes, count: Int(length))) else { return 4 }
    onMainSync { MenuDrawerController.shared.update(models) }
    return 0
}

@_cdecl("officekit_drawers_remove")
public func officekitDrawersRemove() {
    onMainSync { MenuDrawerController.shared.remove() }
}
