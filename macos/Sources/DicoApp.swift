import SwiftUI
import AppKit
import Carbon.HIToolbox

// MARK: - The floating panel

/// A non-activating NSPanel that can still become key — you have to type in it.
final class FloatingPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) {   // Esc
        (NSApp.delegate as? AppDelegate)?.escape()
    }
}

// MARK: - Application delegate

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let model = DicoModel()
    private var panel: FloatingPanel!
    private var statusItem: NSStatusItem!
    private var hotKeyRef: EventHotKeyRef?
    private var localMonitor: Any?
    private var globalMonitor: Any?

    private let services = DicoServices()

    func applicationDidFinishLaunching(_ notification: Notification) {
        DicoClient.seedDataIfNeeded()               // first run: unpack the bundled data
        NSApp.mainMenu = AppDelegate.editingMenu()   // ⌘C ⌘V ⌘A ⌘Z reach the text field
        buildStatusItem()
        buildPanel()
        registerHotKey(nil)
        installKeyMonitors()
        services.onText = { [weak self] text in self?.lookUp(selected: text) }
        NSApp.servicesProvider = services
        NSUpdateDynamicServices()
        NotificationCenter.default.addObserver(
            forName: .dicoOpenSettings, object: nil, queue: .main) { _ in
                MainActor.assumeIsolated { (NSApp.delegate as? AppDelegate)?.openSettings() }
            }
    }

    /// A menu-bar-only app has no main menu, so ⌘V has nowhere to go and the
    /// field never receives it. An invisible Edit menu with the standard
    /// selectors is all it takes.
    static func editingMenu() -> NSMenu {
        let main = NSMenu()
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Edit")
        let items: [(String, Selector, String)] = [
            ("Undo", Selector(("undo:")), "z"), ("Redo", Selector(("redo:")), "Z"),
            ("Cut", #selector(NSText.cut(_:)), "x"), ("Copy", #selector(NSText.copy(_:)), "c"),
            ("Paste", #selector(NSText.paste(_:)), "v"),
            ("Select All", #selector(NSText.selectAll(_:)), "a"),
        ]
        for (title, sel, key) in items {
            edit.addItem(NSMenuItem(title: title, action: sel, keyEquivalent: key))
        }
        editItem.submenu = edit
        main.addItem(editItem)
        return main
    }

    /// Text handed over by ⌥D-with-a-selection or the Services menu:
    /// show the panel with it and run it in the right mode.
    func lookUp(selected text: String) {
        if !panel.isVisible { showPanel() }
        model.run(text, mode: Selection.mode(for: text))
    }

    // MARK: Menu bar

    private func buildStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = AppDelegate.menuBarMark()
        statusItem.button?.toolTip = "Dico"
        rebuildMenu()
    }

    /// The app's own mark, « é », drawn as a TEMPLATE image: the menu bar
    /// recolours it itself, so it follows light/dark and the highlight state —
    /// which an emoji never did.
    static func menuBarMark() -> NSImage {
        let side: CGFloat = 18
        let image = NSImage(size: NSSize(width: side, height: side))
        image.lockFocus()
        let font = NSFont.systemFont(ofSize: 15, weight: .semibold)
        let mark = NSAttributedString(string: "é", attributes: [
            .font: font, .foregroundColor: NSColor.black,
        ])
        let s = mark.size()
        mark.draw(at: NSPoint(x: (side - s.width) / 2, y: (side - s.height) / 2))
        image.unlockFocus()
        image.isTemplate = true          // black + alpha; AppKit tints it
        return image
    }

    /// Rebuilt when the hotkey changes, so the menu shows the real one.
    private func rebuildMenu() {
        let menu = NSMenu()
        let hk = HotkeyChoice.from(ConfigStore.readRaw(at: ConfigPath.current)["popup_hotkey"] as? String)
        let open = NSMenuItem(title: "Open  (\(hk.display))", action: #selector(togglePanel),
                              keyEquivalent: "")
        open.target = self
        menu.addItem(open)
        let settings = NSMenuItem(title: "Settings…", action: #selector(openSettings),
                                  keyEquivalent: ",")
        settings.keyEquivalentModifierMask = [.command]
        settings.target = self
        menu.addItem(settings)
        let keys = NSMenuItem(title: "Shortcuts", action: #selector(showShortcuts), keyEquivalent: "/")
        keys.keyEquivalentModifierMask = [.command]
        keys.target = self
        menu.addItem(keys)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        statusItem.menu = menu
    }

    @objc private func quit() { NSApp.terminate(nil) }

    @objc func openSettings() {
        SettingsWindowController.shared.onHotkeyChange = { [weak self] choice in
            self?.registerHotKey(choice)
            self?.rebuildMenu()
            self?.model.refreshHotkeyLabel()
        }
        SettingsWindowController.shared.show()
    }

    @objc func showShortcuts() {
        if !panel.isVisible { showPanel() }
        model.showShortcuts = true
    }

    // MARK: Window

    private func buildPanel() {
        // Content + a margin all around, so the native shadow has room.
        let rect = NSRect(x: 0, y: 0,
                          width: PanelSize.width + 2 * PanelSize.margin,
                          height: PanelSize.height + 2 * PanelSize.margin)
        panel = FloatingPanel(contentRect: rect,
                              styleMask: [.nonactivatingPanel, .borderless],
                              backing: .buffered, defer: false)
        panel.level = .floating
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true                  // native shadow, follows the rounded corners (non-opaque window)
        panel.hidesOnDeactivate = false
        panel.isMovableByWindowBackground = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
        panel.isReleasedWhenClosed = false

        let host = NSHostingView(rootView: PanelView(model: model))
        host.frame = rect
        panel.contentView = host
    }

    private func center() {
        guard let screen = NSScreen.main else { return }
        let f = screen.visibleFrame
        let s = panel.frame.size
        panel.setFrameOrigin(NSPoint(x: f.midX - s.width / 2,
                                     y: f.midY - s.height / 2 + f.height * 0.12))
    }

    @objc func togglePanel() {
        panel.isVisible ? hidePanel() : showPanel()
    }

    /// The global hotkey. With the panel hidden and text selected in the
    /// front app, the selection is looked up straight away.
    @objc func hotkeyPressed() {
        if panel.isVisible { hidePanel(); return }
        let raw = ConfigStore.readRaw(at: ConfigPath.current)
        if Selection.enabled(in: raw), let text = Selection.grab() {
            lookUp(selected: text)
        } else {
            showPanel()
        }
    }

    func showPanel() {
        center()
        model.shown = false
        NSApp.activate(ignoringOtherApps: true)
        panel.makeKeyAndOrderFront(nil)
        DispatchQueue.main.async { [weak self] in self?.panel.invalidateShadow() }
        model.shown = true                       // triggers the springy animation
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.02) {
            NotificationCenter.default.post(name: .dicoFocusField, object: nil)
        }
        startClickAwayMonitor()
    }

    func hidePanel() {
        model.shown = false
        stopClickAwayMonitor()
        // Let the collapse animation play before removing the window.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.16) { [weak self] in
            self?.panel.orderOut(nil)
        }
    }

    // MARK: Global ⌥D hotkey (Carbon — no Accessibility permission needed)

    private var hotKeyHandlerInstalled = false

    /// (Re-)registers the global hotkey. `nil` means "whatever the config says".
    func registerHotKey(_ choice: HotkeyChoice? = nil) {
        if !hotKeyHandlerInstalled {
            var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                          eventKind: UInt32(kEventHotKeyPressed))
            InstallEventHandler(GetApplicationEventTarget(), { _, _, _ -> OSStatus in
                DispatchQueue.main.async {
                    (NSApp.delegate as? AppDelegate)?.hotkeyPressed()
                }
                return noErr
            }, 1, &eventType, nil, nil)
            hotKeyHandlerInstalled = true
        }
        if let old = hotKeyRef { UnregisterEventHotKey(old); hotKeyRef = nil }

        let hk = choice ?? HotkeyChoice.from(
            ConfigStore.readRaw(at: ConfigPath.current)["popup_hotkey"] as? String)
        let id = EventHotKeyID(signature: OSType(0x4449_434F), id: 1)   // 'DICO'
        RegisterEventHotKey(hk.keyCode, hk.carbonModifiers,
                            id, GetApplicationEventTarget(), 0, &hotKeyRef)
        model.refreshHotkeyLabel()
    }

    // MARK: Local keyboard (Esc, ⌘K, ⌘1…⌘9) and click-away

    /// The number keys, by key code — `charactersIgnoringModifiers` turns
    /// ⌘⇧1 into "!" on most layouts, so the digit has to come from the code.
    private static let digitCodes: [UInt16: Int] = [
        UInt16(kVK_ANSI_1): 1, UInt16(kVK_ANSI_2): 2, UInt16(kVK_ANSI_3): 3,
        UInt16(kVK_ANSI_4): 4, UInt16(kVK_ANSI_5): 5, UInt16(kVK_ANSI_6): 6,
        UInt16(kVK_ANSI_7): 7, UInt16(kVK_ANSI_8): 8, UInt16(kVK_ANSI_9): 9,
    ]

    private func installKeyMonitors() {
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self else { return event }
            // ⌘, works wherever the app is — even from the Settings window.
            if event.modifierFlags.contains(.command),
               (event.charactersIgnoringModifiers ?? "") == "," {
                self.openSettings()
                return nil
            }
            guard self.panel.isVisible, self.panel.isKeyWindow else { return event }
            return self.handlePanelKey(event)
        }
    }

    /// Every shortcut the panel itself listens to. Returns nil once handled.
    private func handlePanelKey(_ event: NSEvent) -> NSEvent? {
        if event.keyCode == 53 {                                   // Esc
            if model.showShortcuts { model.showShortcuts = false; return nil }
            escape()
            return nil
        }
        guard event.modifierFlags.contains(.command) else { return event }
        let chars = (event.charactersIgnoringModifiers ?? "").lowercased()
        let shift = event.modifierFlags.contains(.shift)

        if chars == "/" { model.showShortcuts.toggle(); return nil }
        if chars == "w" { hidePanel(); return nil }

        // ⌘⇧1…⌘⇧5 switch mode; ⌘1…⌘9 save a sense.
        if let n = AppDelegate.digitCodes[event.keyCode] {
            if shift {
                if n <= Mode.allCases.count { model.setMode(Mode.allCases[n - 1]) }
            } else {
                model.saveSense(number: n)
            }
            return nil
        }

        if shift {
            if chars == "c" { return model.copyCorrected() ? nil : event }
            return event
        }

        switch chars {
        case "k": model.clear(); return nil
        case "d": return model.toggleSectionShortcut(.definitions) ? nil : event
        case "r": return model.toggleSectionShortcut(.russe) ? nil : event
        case "e": return model.toggleSectionShortcut(.exemples) ? nil : event
        case "j": return model.toggleSectionShortcut(.conjugaison) ? nil : event
        case "l": return model.askAboutCurrentCard() ? nil : event
        case "p":
            guard !model.cardTerm.isEmpty else { return event }
            model.speak(model.cardTerm)
            return nil
        default: return event
        }
    }

    /// Esc: the first press wipes the field and the results, the second hides.
    func escape() {
        if model.showShortcuts { model.showShortcuts = false; return }
        if model.escape() {
            NotificationCenter.default.post(name: .dicoFocusField, object: nil)
        } else {
            hidePanel()
        }
    }

    private func startClickAwayMonitor() {
        guard globalMonitor == nil else { return }
        globalMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
                self?.hidePanel()
            }
    }

    private func stopClickAwayMonitor() {
        if let m = globalMonitor { NSEvent.removeMonitor(m); globalMonitor = nil }
    }
}

// MARK: - Self-test (`--selftest`): no UI, it exercises the CLI→Swift chain

@MainActor
func runSelfTest() -> Int32 {
    _ = NSApplication.shared   // AppKit must exist to lay out an off-screen view

    let testKey = "dico.recent.selftest"
    var failures = 0
    var skipped = 0

    /// Force the layout of the whole panel, off screen: this is what really
    /// exercises the rendering (FlowLayout, Grid, markdown…).
    func render(_ outcome: Outcome) -> String {
        let model = DicoModel(recentKey: testKey)
        model.outcome = outcome
        return render(model)
    }

    func render(_ model: DicoModel) -> String {
        let host = NSHostingView(rootView: PanelView(model: model))
        host.frame = NSRect(x: 0, y: 0,
                            width: PanelSize.width + 2 * PanelSize.margin,
                            height: PanelSize.height + 2 * PanelSize.margin)
        host.layoutSubtreeIfNeeded()
        return "panel \(Int(host.fittingSize.width))×\(Int(host.fittingSize.height))"
    }

    /// Lays the Word card out on its own, so the measured height is meaningful.
    func renderCard(_ model: DicoModel, _ lookup: Lookup) -> String {
        let host = NSHostingView(rootView:
            WordView(lookup: lookup, model: model).frame(width: PanelSize.content))
        host.layoutSubtreeIfNeeded()
        return "card \(Int(host.fittingSize.width))×\(Int(host.fittingSize.height))"
    }

    func line(_ label: String, _ body: () throws -> String) {
        do {
            let s = try body().replacingOccurrences(of: "\n", with: " ")
            print("✓ \(label): \(s.prefix(170))")
        } catch {
            let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            // Multitran needs proprietary dictionaries and the tutor needs a
            // model: on a machine that has neither — which is every machine
            // dico has just been installed on — that is not a failure.
            if isOptional(msg) {
                skipped += 1
                print("⊘ \(label): \(msg.prefix(120)) — optional, skipped")
            } else {
                failures += 1
                print("✗ \(label): \(msg)")
            }
        }
    }

    /// True when the message only says an optional extra is absent.
    func isOptional(_ msg: String) -> Bool {
        let m = msg.lowercased()
        return m.contains("multitran not installed")
            || m.contains("empty response")
            || m.contains("no model loaded")
            || m.contains("endpoint unreachable")
            || m.contains("no tutor")
            || m.contains("the tutor answered nothing")
    }

    struct Failed: LocalizedError {
        let why: String
        var errorDescription: String? { why }
    }

    line("word cook") {
        let l = try DicoClient.lookup("cook")
        let senses = (l.senses ?? []).prefix(3).map { $0.display }.joined(separator: ", ")
        return "direction=\(l.direction ?? "?") transl=\(l.translation ?? "?") | \(senses) | \(render(.mot(l)))"
    }
    line("word maison (fr)") {
        let l = try DicoClient.lookup("maison")
        return "head=\(l.head ?? "?") pos=\(l.lexique?.pos ?? "?") band=\(l.lexique?.band ?? "?") | \(render(.mot(l)))"
    }
    line("conj aller") {
        let c = try DicoClient.conjugate("aller")
        let p = (c.tenses?["présent"] ?? []).joined(separator: ", ")
        return "\(c.infinitive ?? "?") — \(c.orderedTenses.count) tenses — présent: \(p) | \(render(.conjugaison(c)))"
    }
    line("gram elle est parti") {
        let g = try DicoClient.grammar("elle est parti")
        let n = (g.errors?.count ?? 0) + (g.spelling?.count ?? 0)
        return "\(n) mistake(s) → \u{ab} \(g.corrected ?? "?") \u{bb} | \(render(.grammaire(g, "elle est parti")))"
    }
    line("x-ray je vais au marché") {
        let t = try DicoClient.xray("je vais au marché demain")
        return "\(t.count) words — \(t.map { $0.lemma ?? "?" }.joined(separator: "/")) | \(render(.rayonsX(t)))"
    }
    line("definition -f cuisiner") {
        let d = try DicoClient.definition("cuisiner")
        return "\(d.word ?? "?") [\(d.ipa ?? "")] \(d.pos ?? "") — \((d.defs ?? []).count) def(s): \((d.defs ?? []).first ?? "")"
    }
    line("multitran -m cuisiner") {
        let m = try DicoClient.multitran("cuisiner")
        return "\(m.direction ?? "?") — \((m.lines ?? []).count) line(s): \((m.lines ?? []).prefix(2).joined(separator: " | "))"
    }
    line("examples --examples cuisiner") {
        let p = try DicoClient.examples("cuisiner")
        let en = p.en ?? [], ru = p.ru ?? []
        guard !en.isEmpty, !ru.isEmpty else { throw Failed(why: "expected both lists, got \(en.count) en / \(ru.count) ru") }
        // The card's own example must not be repeated once Tatoeba has it.
        let own = [["Dois-tu cuisiner ?", "Do you have to cook?"], ["Une phrase inédite.", "A brand-new sentence."]]
        let host = NSHostingView(rootView:
            ExamplesBody(pack: p, own: own).frame(width: PanelSize.paneBody))
        host.layoutSubtreeIfNeeded()
        let merged = ExamplesBody(pack: p, own: own)
        return "\(en.count) en / \(ru.count) ru — \(en.first?.fr ?? "") / \(ru.first?.ru ?? "") | body \(Int(host.fittingSize.width))×\(Int(host.fittingSize.height)) | \(merged.debugSummary)"
    }
    line("examples: empty pack") {
        let p = try DicoClient.examples("zzqqzzxyw")
        guard p.isEmpty else { throw Failed(why: "expected an empty pack") }
        let host = NSHostingView(rootView:
            ExamplesBody(pack: p).frame(width: PanelSize.paneBody))
        host.layoutSubtreeIfNeeded()
        return "empty → \"No examples found\" (body \(Int(host.fittingSize.width))×\(Int(host.fittingSize.height)))"
    }
    line("tutor tu ou vous") {
        let a = try DicoClient.ask("tu ou vous ?", context: "cuisiner")
        return "[\(a.model ?? "?")] \(render(.reponse(a))) — \(a.answer ?? "")"
    }

    // The Word card laid out WITH an expanded Definitions section.
    // « cook » needs the network; when it is down (or rate-limited) we fall
    // back to a French verb card so the check still means something.
    line("word card + Definitions open") {
        var l = try DicoClient.lookup("cook")
        var note = ""
        if let e = l.error, !e.isEmpty {
            note = " [\u{ab} cook \u{bb} unavailable: \(e.prefix(40)) — fell back to a French card]"
            l = try DicoClient.lookup("cuisiner")
        }
        let d = try DicoClient.definition("cuisiner")
        let model = DicoModel(recentKey: testKey)
        let plain = renderCard(model, l)
        model.preload(card: l, query: l.query ?? "cook", section: .definitions, content: .definition(d))
        let opened = renderCard(model, l)
        guard model.cardTerm == "cuire" || model.cardIsVerb else {
            throw Failed(why: "the card did not adopt a French verb term (got \u{ab} \(model.cardTerm) \u{bb})")
        }
        return "term=\(model.cardTerm) verb=\(model.cardIsVerb) sections=\(model.open.count) | closed \(plain) → open \(opened) | \(render(model))\(note)"
    }

    // The three other section bodies, laid out off screen too.
    line("word card + Russian / Examples / Conjugate open") {
        let l = try DicoClient.lookup("cuisiner")
        var sizes: [String] = []
        for (s, c) in [(Section.russe, SectionContent.multitran(try DicoClient.multitran("cuisiner"))),
                       (Section.exemples, SectionContent.examples(try DicoClient.examples("cuisiner"))),
                       (Section.conjugaison, SectionContent.conjugation(try DicoClient.conjugate("cuisiner")))] {
            let model = DicoModel(recentKey: testKey)
            model.preload(card: l, query: "cuisiner", section: s, content: c)
            guard model.cardIsVerb else { throw Failed(why: "cuisiner should be a verb") }
            sizes.append("\(s.label) \(renderCard(model, l))")
        }
        return sizes.joined(separator: " | ")
    }

    // Clearing the field must wipe the results.
    line("clear on erase") {
        let model = DicoModel(recentKey: testKey)
        model.query = "cook"
        model.outcome = .rayonsX([XrayToken(text: "je")])
        model.query = ""
        model.inputChanged()
        guard case .vide = model.outcome else { throw Failed(why: "the results survived an empty field") }
        model.query = "chat"
        model.outcome = .rayonsX([XrayToken(text: "je")])
        guard model.escape() else { throw Failed(why: "Esc did not clear") }
        guard model.query.isEmpty, model.escape() == false else {
            throw Failed(why: "the second Esc should fall through to hiding the panel")
        }
        return "empty field → .vide, Esc clears then falls through"
    }

    // The recent list survives a new model (UserDefaults).
    line("recent list persistence") {
        UserDefaults.standard.removeObject(forKey: testKey)
        let a = DicoModel(recentKey: testKey)
        for w in ["cook", "maison", "cuisiner", "cook"] { a.remember(w) }
        for i in 1...9 { a.remember("mot\(i)") }
        UserDefaults.standard.synchronize()
        let b = DicoModel(recentKey: testKey)
        guard b.recent.count == DicoModel.recentLimit else {
            throw Failed(why: "expected \(DicoModel.recentLimit) entries, got \(b.recent.count)")
        }
        guard b.recent.first == "mot9" else { throw Failed(why: "wrong order: \(b.recent)") }
        guard Set(b.recent).count == b.recent.count else { throw Failed(why: "duplicates: \(b.recent)") }
        let shown = render(b)
        let listed = b.recent.joined(separator: ", ")
        b.forgetRecent()
        UserDefaults.standard.removeObject(forKey: testKey)
        let c = DicoModel(recentKey: testKey)
        guard c.recent.isEmpty else { throw Failed(why: "the list was not forgotten") }
        return "\(listed) | \(shown)"
    }

    // ------------------------------------------------------------------ //
    // 1. The conjugation grid: a real grid, and it must fit without scrolling.
    // ------------------------------------------------------------------ //
    line("conj grid -c dire fits the panel") {
        let c = try DicoClient.conjugate("dire")
        var report: [String] = []
        for compact in [false, true] {
            let view = ConjugationView(conj: c, compact: compact)
            let budget = compact ? ConjugationView.compactBudget : ConjugationView.fullBudget
            let host = NSHostingView(rootView: view)
            host.layoutSubtreeIfNeeded()
            let measured = host.fittingSize.width
            guard view.gridWidth <= budget + 0.5 else {
                throw Failed(why: "grid \(view.gridWidth) pt > budget \(budget) pt (compact=\(compact))")
            }
            guard measured <= budget + 0.5 else {
                throw Failed(why: "laid-out width \(measured) > budget \(budget) (compact=\(compact))")
            }
            report.append("\(compact ? "compact" : "full") grid \(Int(view.gridWidth))/\(Int(budget)) pt, col \(Int(view.colWidth))")
        }
        // Full tense names in the header, seven of them, présent first.
        let names = c.orderedTenses.map { $0.0 }
        guard names.first == "présent", names.count == 7 else {
            throw Failed(why: "expected 7 tenses starting at présent, got \(names)")
        }
        // Compound forms: the auxiliary is split off so it can be dimmed.
        guard let pc = c.tenses?["passé composé"], let first = pc.first else {
            throw Failed(why: "no passé composé")
        }
        let (aux, rest) = ConjugationView.split(first)
        guard aux == "ai", rest == "dit" else {
            throw Failed(why: "\u{ab} \(first) \u{bb} split as (\(aux ?? "nil"), \(rest)), expected (ai, dit)")
        }
        // The impératif really has three holes — they render as « — ».
        let imp = c.tenses?["impératif"] ?? []
        let blanks = (0..<6).filter { ConjugationView.form("impératif", imp, row: $0) == nil }
        guard blanks == [0, 2, 5] else { throw Failed(why: "impératif blanks at \(blanks)") }
        return report.joined(separator: " | ") + " | tenses: \(names.joined(separator: " · ")) | ai+dit split ✓ | blanks je/il/ils"
    }

    // ------------------------------------------------------------------ //
    // 2. Multitran: the WHOLE entry, groups + senses + items + notes.
    // ------------------------------------------------------------------ //
    func checkMultitran(_ word: String) throws -> String {
        let m = try DicoClient.multitran(word)
        let groups = m.usableGroups
        guard !groups.isEmpty else { throw Failed(why: "no groups for \u{ab} \(word) \u{bb}") }
        let body = MultitranBody(entry: m)
        let flat = body.plainText

        var items = 0, notes = 0, senses = 0
        for g in groups {
            let pos = (g.pos ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if !pos.isEmpty {
                guard flat.contains(pos) else { throw Failed(why: "POS \u{ab} \(pos) \u{bb} missing") }
            }
            for sense in g.senses ?? [] {
                senses += 1
                let domain = (sense.domain ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                if !domain.isEmpty {
                    guard flat.contains(domain) else { throw Failed(why: "domain \u{ab} \(domain) \u{bb} missing") }
                }
                for it in sense.items ?? [] {
                    let tr = (it.tr ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                    guard tr.isEmpty || flat.contains(tr) else {
                        throw Failed(why: "translation \u{ab} \(tr) \u{bb} missing")
                    }
                    if !tr.isEmpty { items += 1 }
                    let note = (it.note ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                    if !note.isEmpty {
                        // The WHOLE note, not a prefix of it.
                        guard flat.contains(note) else {
                            throw Failed(why: "note of \u{ab} \(tr) \u{bb} truncated")
                        }
                        notes += 1
                    }
                }
            }
        }
        // And it lays out — no fixed height, so the card just gets taller.
        let host = NSHostingView(rootView: body.frame(width: PanelSize.paneBody))
        host.layoutSubtreeIfNeeded()
        let size = host.fittingSize
        return "\(m.direction ?? "?") — \(groups.count) group(s), \(senses) sense(s), \(items) item(s), \(notes) note(s) all present | body \(Int(size.width))×\(Int(size.height))"
    }

    line("multitran -m dire: the whole entry") {
        let m = try DicoClient.multitran("dire")
        let flat = MultitranBody(entry: m).plainText
        // The long note on « называть » is a full sentence — it must be whole.
        let long = "Parallèlement à la gamme que nous dirons standard, certains fabricants produisent en très petite série des cercueils plus luxueux."
        let hasLong = flat.contains(long)
        let summary = try checkMultitran("dire")
        guard hasLong else {
            throw Failed(why: "the note of \u{ab} называть \u{bb} is not there in full")
        }
        return summary + " | « называть » note: \(long.count) chars, verbatim ✓"
    }

    line("multitran -m кошка: ru→fr, empty and short POS") {
        let s = try checkMultitran("кошка")
        let m = try DicoClient.multitran("кошка")
        let poss = m.usableGroups.map { ($0.pos ?? "").isEmpty ? "(empty)" : ($0.pos ?? "") }
        return s + " | pos: \(poss.joined(separator: ", "))"
    }

    line("multitran: lines are only a fallback") {
        // groups present → the flat lines must NOT be what gets rendered.
        let m = try DicoClient.multitran("dire")
        guard !m.usableGroups.isEmpty else { throw Failed(why: "expected groups") }
        let empty = Multitran(direction: "frru", lines: ["гл.", "1) общ. dire"], groups: [], error: nil)
        let flat = MultitranBody(entry: empty).plainText
        guard flat.contains("1) общ. dire") else { throw Failed(why: "the fallback did not render the lines") }
        let host = NSHostingView(rootView: MultitranBody(entry: empty).frame(width: 400))
        host.layoutSubtreeIfNeeded()
        return "groups → structured; no groups → \(empty.lines?.count ?? 0) raw line(s) (\(Int(host.fittingSize.height)) pt)"
    }

    // ------------------------------------------------------------------ //
    // 3. The card header uses the QUERY's language, not 🇫🇷.
    // ------------------------------------------------------------------ //
    line("card flag follows the query's language") {
        let cases: [(String, String?, String)] = [
            ("сказать", nil, "🇷🇺"),          // Cyrillic, no src_lang
            ("сказать", "ru", "🇷🇺"),
            ("cook", nil, "🇬🇧"),
            ("cook", "en", "🇬🇧"),
            ("кошка", "", "🇷🇺"),
        ]
        for (q, lang, want) in cases {
            let got = WordView.flag(forQuery: q, srcLang: lang)
            guard got == want else {
                throw Failed(why: "\(q) [\(lang ?? "nil")] → \(got), expected \(want)")
            }
        }
        return cases.map { "\($0.0)→\($0.2)" }.joined(separator: " ") + " (🇫🇷 stays on the result)"
    }

    // ------------------------------------------------------------------ //
    // 4. Settings: a real round trip through a temp config file.
    // ------------------------------------------------------------------ //
    line("settings round-trip + chmod 600") {
        let dir = NSTemporaryDirectory() + "dico-selftest-\(UUID().uuidString)"
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(atPath: dir) }
        let path = dir + "/config.json"

        // Something the app knows nothing about must survive the round trip.
        let seed: [String: Any] = ["autosave": true, "un_known_key": "keep me", "llm": "local"]
        guard ConfigStore.writeRaw(seed, to: path) else { throw Failed(why: "seed write failed") }

        let store = ConfigStore(path: path)
        guard store.autosave, store.tutor == .local else {
            throw Failed(why: "read back wrong: autosave=\(store.autosave) tutor=\(store.tutor)")
        }
        store.tutor = .byok
        store.llmURL = "https://api.mistral.ai/v1"
        store.llmModel = "mistral-small-latest"
        store.llmKey = "sk-test-123"
        store.autosave = false
        store.examples = false
        store.xraySpacy = false
        store.vocabPath = "/tmp/vocab.md"
        store.storePath = "/tmp/store.json"
        store.hotkey = .ctrlOptD
        guard store.save() else { throw Failed(why: "save failed") }

        let back = ConfigStore(path: path)
        let expected: [(String, String, String)] = [
            ("llm", back.tutor.rawValue, "byok"),
            ("llm_url", back.llmURL, "https://api.mistral.ai/v1"),
            ("llm_model", back.llmModel, "mistral-small-latest"),
            ("llm_key", back.llmKey, "sk-test-123"),
            ("vocab_path", back.vocabPath, "/tmp/vocab.md"),
            ("store_path", back.storePath, "/tmp/store.json"),
            ("popup_hotkey", back.hotkey.id, "ctrl+opt+d"),
        ]
        for (k, got, want) in expected where got != want {
            throw Failed(why: "\(k) = \u{ab} \(got) \u{bb}, expected \u{ab} \(want) \u{bb}")
        }
        guard !back.autosave, !back.examples, !back.xraySpacy else {
            throw Failed(why: "the booleans did not survive")
        }
        let raw = ConfigStore.readRaw(at: path)
        guard raw["un_known_key"] as? String == "keep me" else {
            throw Failed(why: "an unknown key was dropped")
        }
        guard raw["anthropic_key"] == nil else {
            throw Failed(why: "switching backend must clear the other one's keys")
        }
        guard let perms = ConfigStore.permissions(of: path), perms == 0o600 else {
            throw Failed(why: "permissions are \(String(ConfigStore.permissions(of: path) ?? -1, radix: 8)), expected 600")
        }
        // Switching to Anthropic must clear the byok keys in turn.
        back.tutor = .anthropic
        back.anthropicKey = "sk-ant-xyz"
        _ = back.save()
        let raw2 = ConfigStore.readRaw(at: path)
        guard raw2["llm_url"] == nil, raw2["llm_key"] == nil,
              raw2["anthropic_key"] as? String == "sk-ant-xyz" else {
            throw Failed(why: "the anthropic switch did not clean up: \(raw2.keys.sorted())")
        }
        return "\(expected.count) keys + 3 booleans round-tripped, unknown key kept, chmod \(String(perms, radix: 8)), backend switch clears the other keys"
    }

    line("settings pane lays out") {
        var sizes: [String] = []
        let dir = NSTemporaryDirectory() + "dico-selftest-ui-\(UUID().uuidString)"
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(atPath: dir) }
        _ = ConfigStore.writeRaw(["llm": "byok", "llm_url": "https://api.openai.com/v1"],
                                 to: dir + "/config.json")
        let store = ConfigStore(path: dir + "/config.json")
        let tabs: [(String, AnyView)] = [
            ("Tutor", AnyView(TutorTab(store: store))),
            ("Vocabulary", AnyView(VocabularyTab(store: store))),
            ("General", AnyView(GeneralTab(store: store))),
            ("Offline data", AnyView(OfflineDataTab())),
            ("Shortcuts", AnyView(ShortcutsTab())),
        ]
        for (name, v) in tabs {
            let host = NSHostingView(rootView: v.frame(width: 608, height: 480))
            host.layoutSubtreeIfNeeded()
            sizes.append("\(name) \(Int(host.fittingSize.width))×\(Int(host.fittingSize.height))")
        }
        return sizes.joined(separator: " | ")
    }

    // ------------------------------------------------------------------ //
    // 5. The hotkey presets map onto Carbon.
    // ------------------------------------------------------------------ //
    line("hotkey → Carbon mapping") {
        let want: [(String, String, UInt32, UInt32)] = [
            ("opt+d", "⌥D", UInt32(kVK_ANSI_D), UInt32(optionKey)),
            ("opt+space", "⌥Space", UInt32(kVK_Space), UInt32(optionKey)),
            ("ctrl+opt+d", "⌃⌥D", UInt32(kVK_ANSI_D), UInt32(controlKey | optionKey)),
            ("cmd+shift+d", "⌘⇧D", UInt32(kVK_ANSI_D), UInt32(cmdKey | shiftKey)),
        ]
        for (id, display, code, mods) in want {
            let h = HotkeyChoice.from(id)
            guard h.id == id, h.display == display, h.keyCode == code, h.carbonModifiers == mods else {
                throw Failed(why: "\(id) → \(h.display) code=\(h.keyCode) mods=\(h.carbonModifiers)")
            }
        }
        guard HotkeyChoice.from("nonsense").id == "opt+d",
              HotkeyChoice.from(nil).id == "opt+d" else {
            throw Failed(why: "an unknown hotkey must fall back to ⌥D")
        }
        return want.map { "\($0.1)=\($0.2)/\($0.3)" }.joined(separator: " · ") + " · unknown→⌥D"
    }

    // ------------------------------------------------------------------ //
    // 6. Shortcuts: the catalogue drives the sheet and the Settings list.
    // ------------------------------------------------------------------ //
    line("shortcuts catalogue + ⌘/ sheet") {
        let all = Shortcuts.all()
        let musts = ["⌘,", "⌘K", "Esc", "⌘1…⌘9", "⌘⇧1", "⌘⇧5", "⌘D", "⌘R", "⌘E",
                     "⌘J", "⌘L", "⌘/", "⌘⇧C", "⌘V · ⌘C · ⌘A", Shortcuts.globalHotkey + " + selection"]
        for k in musts where !all.contains(where: { $0.keys == k }) {
            throw Failed(why: "\(k) is not in the catalogue")
        }
        guard all.contains(where: { $0.keys == Shortcuts.globalHotkey }) else {
            throw Failed(why: "the global hotkey is not listed")
        }
        let host = NSHostingView(rootView: ShortcutsSheet(close: {}))
        host.layoutSubtreeIfNeeded()
        let model = DicoModel(recentKey: testKey)
        model.showShortcuts = true
        return "\(all.count) shortcuts in \(Shortcuts.grouped().count) groups | sheet \(Int(host.fittingSize.width))×\(Int(host.fittingSize.height)) | over the panel: \(render(model))"
    }

    // ------------------------------------------------------------------ //
    // 6b. Paste + selection: the Edit menu, the service, the text shaping.
    // ------------------------------------------------------------------ //
    line("edit menu routes ⌘V/⌘C/⌘A") {
        let menu = AppDelegate.editingMenu()
        guard let edit = menu.items.first?.submenu else { throw Failed(why: "no Edit submenu") }
        let want: [(String, String)] = [("paste:", "v"), ("copy:", "c"), ("cut:", "x"),
                                        ("selectAll:", "a"), ("undo:", "z")]
        for (sel, key) in want {
            guard edit.items.contains(where: {
                $0.action.map { NSStringFromSelector($0) } == sel && $0.keyEquivalent == key
            }) else { throw Failed(why: "\(sel) (⌘\(key.uppercased())) missing from the Edit menu") }
        }
        return "\(edit.items.count) items: " + want.map { "⌘\($0.1.uppercased())→\($0.0)" }.joined(separator: " ")
    }

    line("selection → text shaping + mode") {
        let cases: [(String?, String?)] = [
            ("  bonjour\n", "bonjour"), ("« maison », ", "maison"), ("j'ai   dit\nseconde ligne", "j'ai dit"),
            ("https://example.com/x", nil), ("", nil), (nil, nil), (String(repeating: "a", count: 250), nil),
        ]
        for (input, want) in cases where Selection.normalize(input) != want {
            throw Failed(why: "normalize(\(input ?? "nil")) = \(Selection.normalize(input) ?? "nil"), wanted \(want ?? "nil")")
        }
        let modes: [(String, Mode)] = [
            ("chat", .mot), ("un coup de main", .mot),
            ("elle est parti hier et je mange", .grammaire), ("je ne sais pas où il est", .grammaire),
            ("the cat is on the table", .mot), ("кошка сидит на столе тихо", .mot),
        ]
        for (t, m) in modes where Selection.mode(for: t) != m {
            throw Failed(why: "mode(\(t)) = \(Selection.mode(for: t)), wanted \(m)")
        }
        guard DicoServices().responds(to: Selector(("lookUp:userData:error:"))) else {
            throw Failed(why: "the services provider lacks lookUp:userData:error:")
        }
        var plist = "not in a bundle"
        if let services = Bundle.main.infoDictionary?["NSServices"] as? [[String: Any]],
           let first = services.first {
            guard first["NSMessage"] as? String == "lookUp", first["NSPortName"] as? String == "Dico" else {
                throw Failed(why: "NSServices entry does not point at lookUp / Dico")
            }
            plist = "Info.plist advertises « \((first["NSMenuItem"] as? [String: String])?["default"] ?? "?") »"
        }
        return "\(cases.count) shapes · \(modes.count) mode picks · service selector ✓ · \(plist) · AX trusted: \(Selection.trusted)"
    }

    line("config: popup_selection round-trips") {
        let dir = NSTemporaryDirectory() + "dico-selftest-sel-\(UUID().uuidString)"
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(atPath: dir) }
        let path = dir + "/config.json"
        _ = ConfigStore.writeRaw(["popup_selection": false, "autosave": true], to: path)
        let store = ConfigStore(path: path)
        guard store.selection == false else { throw Failed(why: "false not read back") }
        store.selection = true
        guard store.save(), Selection.enabled(in: ConfigStore.readRaw(at: path)) else {
            throw Failed(why: "true not written") }
        guard Selection.enabled(in: [:]) else { throw Failed(why: "must default to on") }
        return "off → on → file, default on"
    }

    // ------------------------------------------------------------------ //
    // 6c. The Wiktionnaire's extra layers: audio, synonyms, homophones, Russian.
    // ------------------------------------------------------------------ //
    line("wiktionary: synonyms + homophones + russian") {
        let d = try DicoClient.definition("chat")
        let syn = (d.syn ?? []).compactMap(\.word)
        let homo = (d.homo ?? []).compactMap(\.word)
        let ru = d.ru ?? []
        guard !syn.isEmpty else { throw Failed(why: "no synonyms for « chat »") }
        guard !homo.isEmpty else { throw Failed(why: "no homophones for « chat »") }
        guard let first = ru.first, (first.word ?? "").unicodeScalars
                .contains(where: { (0x0400...0x04FF).contains($0.value) }) else {
            throw Failed(why: "no Cyrillic translation for « chat »")
        }
        let host = NSHostingView(rootView:
            DefinitionBody(def: d).frame(width: PanelSize.paneBody))
        host.layoutSubtreeIfNeeded()
        let ruHost = NSHostingView(rootView:
            WiktionaryRuBody(terms: ru).frame(width: PanelSize.paneBody))
        ruHost.layoutSubtreeIfNeeded()
        let tr = first.tr.map { " [\($0)]" } ?? ""
        return "syn \(syn.prefix(3).joined(separator: "·")) | homo \(homo.prefix(3).joined(separator: "·")) | ru \(first.word ?? "")\(tr) | body \(Int(host.fittingSize.height))pt, ru \(Int(ruHost.fittingSize.height))pt"
    }

    line("CEFR level + offline IPA on the card") {
        var seen: [String] = []
        for (word, want) in [("maison", "A1"), ("neanmoins", "B1")] {
            let l = try DicoClient.lookup(word)
            guard let lvl = l.lexique?.cefr, lvl == want else {
                throw Failed(why: "\(word) → \(l.lexique?.cefr ?? "nil"), wanted \(want)")
            }
            guard let ipa = l.lexique?.ipa, !ipa.isEmpty,
                  ipa.rangeOfCharacter(from: CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZ")) == nil else {
                throw Failed(why: "\(word): « \(l.lexique?.ipa ?? "") » is not IPA")
            }
            seen.append("\(word) \(lvl) /\(ipa)/")
            let host = NSHostingView(rootView: WordView(lookup: l, model: DicoModel(recentKey: testKey))
                .frame(width: PanelSize.content))
            host.layoutSubtreeIfNeeded()
        }
        let pill = NSHostingView(rootView: CEFRPill(level: "B2"))
        pill.layoutSubtreeIfNeeded()
        return seen.joined(separator: " | ") + " | pill \(Int(pill.fittingSize.width))×\(Int(pill.fittingSize.height))"
    }

    line("first run offers something to press") {
        let model = DicoModel(recentKey: "dico.recent.selftest.firstrun")
        model.forgetRecent()
        guard model.recent.isEmpty else { throw Failed(why: "recents were not cleared") }
        let host = NSHostingView(rootView: EmptyStateView(model: model)
            .frame(width: PanelSize.content))
        host.layoutSubtreeIfNeeded()
        guard host.fittingSize.height > 120 else {
            throw Failed(why: "the first-run state is \(Int(host.fittingSize.height))pt — the examples are missing")
        }
        // Every example must be something the app can actually run.
        for ex in EmptyStateView.examples where ex.query.isEmpty {
            throw Failed(why: "empty example")
        }
        return "\(EmptyStateView.examples.count) examples: "
            + EmptyStateView.examples.map(\.query).joined(separator: " · ")
            + " | \(Int(host.fittingSize.height))pt"
    }

    line("menu bar mark is a template image") {
        let img = AppDelegate.menuBarMark()
        guard img.isTemplate else { throw Failed(why: "not a template: it will not follow dark mode") }
        guard img.size.width > 8, img.size.height > 8 else {
            throw Failed(why: "degenerate size \(img.size)")
        }
        // It must actually have ink in it — an empty template is invisible.
        guard let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) else {
            throw Failed(why: "no bitmap")
        }
        var inked = 0
        for x in 0..<rep.pixelsWide {
            for y in 0..<rep.pixelsHigh where (rep.colorAt(x: x, y: y)?.alphaComponent ?? 0) > 0.2 {
                inked += 1
            }
        }
        guard inked > 20 else { throw Failed(why: "only \(inked) inked pixels") }
        return "\(Int(img.size.width))×\(Int(img.size.height)) template, \(inked) inked px"
    }

    line("badges reach a translation card too") {
        let l = try DicoClient.lookup("cook")
        guard let lvl = l.lexique?.cefr, !lvl.isEmpty else {
            throw Failed(why: "no CEFR level on the French result of « cook »")
        }
        guard let ipa = l.lexique?.ipa, !ipa.isEmpty else {
            throw Failed(why: "no IPA on the French result of « cook »")
        }
        let graded = (l.senses ?? []).filter { !($0.cefr ?? "").isEmpty }
        guard !graded.isEmpty else { throw Failed(why: "no sense carries a level") }
        let host = NSHostingView(rootView: WordView(lookup: l, model: DicoModel(recentKey: testKey))
            .frame(width: PanelSize.content))
        host.layoutSubtreeIfNeeded()
        return "\(l.translation ?? "") \(lvl) /\(ipa)/ | \(graded.count)/\((l.senses ?? []).count) senses graded | card \(Int(host.fittingSize.height))pt"
    }

    line("audio: a playable recording") {
        let a = try DicoClient.audio("vert")
        if let e = a.error, !e.isEmpty { throw Failed(why: e) }
        guard let path = a.path, !path.isEmpty else { throw Failed(why: "no path returned") }
        let size = ((try? FileManager.default.attributesOfItem(atPath: path))?[.size] as? Int) ?? 0
        guard size > 1000 else { throw Failed(why: "the file is \(size) bytes") }
        // Built, never played: a self-test must stay silent.
        guard NSSound(contentsOfFile: path, byReference: true) != nil else {
            throw Failed(why: "AppKit cannot play \(path)")
        }
        return "\((path as NSString).lastPathComponent) — \(size / 1024) KB, NSSound ✓ (not played)"
    }

    // ------------------------------------------------------------------ //
    // 7. The Settings ▸ Test button's actual call.
    // ------------------------------------------------------------------ //
    line("settings Test button: --json -a") {
        let a = try DicoClient.ask("Reply with the single word ok", context: nil)
        let text = (a.answer ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw Failed(why: "the tutor answered nothing") }
        return "[\(a.model ?? "?")] \(text.prefix(60))"
    }

    let tail = skipped > 0 ? " (\(skipped) optional skipped)" : ""
    print(failures == 0 ? "✓ all good\(tail)" : "✗ \(failures) failure(s)\(tail)")
    return failures == 0 ? 0 : 1
}

// MARK: - Screenshots (`--shots DIR`): every screen, both appearances, off screen

/// Renders the panel in each of its states — and the Settings tabs — to PNG
/// files, without ever touching the screen. For design review.
@MainActor
func renderShots(into dir: String) -> Int32 {
    _ = NSApplication.shared
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    let testKey = "dico.recent.shots"
    var count = 0

    func png<V: View>(_ name: String, _ view: V, size: NSSize, dark: Bool) {
        let host = NSHostingView(rootView: view)
        host.frame = NSRect(origin: .zero, size: size)
        host.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        host.layoutSubtreeIfNeeded()
        guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
        host.cacheDisplay(in: host.bounds, to: rep)
        guard let data = rep.representation(using: .png, properties: [:]) else { return }
        let path = "\(dir)/\(name)-\(dark ? "dark" : "light").png"
        try? data.write(to: URL(fileURLWithPath: path))
        count += 1
        print("→ \(path)")
    }

    func panel(_ name: String, _ model: DicoModel) {
        model.shown = true
        let size = NSSize(width: PanelSize.width + 2 * PanelSize.margin,
                          height: PanelSize.height + 2 * PanelSize.margin)
        for dark in [true, false] {
            png(name, PanelView(model: model).background(dark ? Color.black : Color(white: 0.93)),
                size: size, dark: dark)
        }
    }

    func model(_ query: String = "", mode: Mode = .mot, recent: [String] = []) -> DicoModel {
        UserDefaults.standard.set(recent, forKey: testKey)
        let m = DicoModel(recentKey: testKey)
        m.query = query
        m.mode = mode
        return m
    }

    panel("00-empty", model(recent: ["dire", "кошка", "chat", "cuire", "aller"]))
    panel("00-firstrun", model())

    func card(_ name: String, _ q: String, section: Section?, content: ((String) throws -> SectionContent)?) {
        do {
            let l = try DicoClient.lookup(q)
            let m = model(q)
            m.preload(card: l, query: q)
            if let section, let content {
                let term = m.cardTerm
                m.preload(card: l, query: q, section: section, content: try content(term))
            }
            panel(name, m)
        } catch {
            print("⊘ \(name): \((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)")
        }
    }
    card("10-card-definitions", "cook", section: .definitions) { .definition(try DicoClient.definition($0)) }
    card("11-card-examples", "chat", section: .exemples) { .examples(try DicoClient.examples($0)) }
    card("12-card-russian", "chat", section: .russe) { .multitran(try DicoClient.multitran($0)) }
    card("13-card-conj", "cuisiner", section: .conjugaison) { .conjugation(try DicoClient.conjugate($0)) }
    card("14-card-ru-query", "кошка", section: .definitions) { .definition(try DicoClient.definition($0)) }

    if let c = try? DicoClient.conjugate("dire") {
        let m = model("dire", mode: .conjuguer); m.outcome = .conjugaison(c); panel("20-conjugate", m)
    }
    if let g = try? DicoClient.grammar("elle est parti hier avec ces amis") {
        let m = model("elle est parti hier avec ces amis", mode: .grammaire)
        m.outcome = .grammaire(g, "elle est parti hier avec ces amis"); panel("30-grammar", m)
    }
    if let t = try? DicoClient.xray("le chat noir dort sur la table") {
        let m = model("le chat noir dort sur la table", mode: .rayonsX); m.outcome = .rayonsX(t); panel("40-xray", m)
    }
    do {
        let m = model("quand employer le subjonctif ?", mode: .demander)
        m.askAbout("dire"); m.query = "quand employer le subjonctif ?"
        m.outcome = .reponse(Answer(answer: "Le subjonctif exprime ce qui n'est pas présenté comme un fait : le doute, le souhait, l'obligation.\n- Après **il faut que**, **bien que**, **pour que** : *il faut que tu dises la vérité*.\n- Après les verbes de volonté et d'émotion : **vouloir que**, **craindre que**.\n- Jamais après **après que**, malgré l'usage courant.", error: nil, model: "mistral-small-latest · local"))
        panel("50-ask", m)
    }
    do {
        let m = model("maison"); m.outcome = .erreur(.notInstalled); panel("60-not-installed", m)
        let m2 = model("maison"); m2.outcome = .erreur(.plain("The tutor answered nothing — is LM Studio running?")); panel("61-error", m2)
    }
    do {
        let m = model("dire"); m.showShortcuts = true; panel("70-shortcuts", m)
    }
    do {
        let m = model("chat"); m.toast = "✓ \u{ab} un chat \u{bb} added"; panel("80-toast", m)
    }

    // Settings, every tab.
    let dir2 = NSTemporaryDirectory() + "dico-shots-\(UUID().uuidString)"
    try? FileManager.default.createDirectory(atPath: dir2, withIntermediateDirectories: true)
    _ = ConfigStore.writeRaw(["llm": "local", "llm_model": "gemma-3-12b"], to: dir2 + "/config.json")
    let store = ConfigStore(path: dir2 + "/config.json")
    for (id, name) in SettingsView.tabs {
        for dark in [true, false] {
            png("90-settings-\(name.lowercased().replacingOccurrences(of: " ", with: "-"))",
                SettingsView(store: store, initialTab: id), size: NSSize(width: 640, height: 540), dark: dark)
        }
    }
    try? FileManager.default.removeItem(atPath: dir2)
    UserDefaults.standard.removeObject(forKey: testKey)
    print("✓ \(count) shots in \(dir)")
    return 0
}

// MARK: - Entry point

@main
struct DicoMain {
    @MainActor static func main() {
        if CommandLine.arguments.contains("--selftest") {
            exit(runSelfTest())
        }
        if let i = CommandLine.arguments.firstIndex(of: "--shots"), i + 1 < CommandLine.arguments.count {
            exit(renderShots(into: CommandLine.arguments[i + 1]))
        }
        let app = NSApplication.shared
        let delegate = AppDelegate()
        DicoMain.retainedDelegate = delegate
        app.delegate = delegate
        app.setActivationPolicy(.accessory)   // LSUIElement: no Dock icon
        app.run()
    }
    @MainActor static var retainedDelegate: AppDelegate?
}
