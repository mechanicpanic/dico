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

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildStatusItem()
        buildPanel()
        registerHotKey()
        installKeyMonitors()
    }

    // MARK: Menu bar

    private func buildStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "📖"
        let menu = NSMenu()
        let open = NSMenuItem(title: "Open", action: #selector(togglePanel), keyEquivalent: "d")
        open.keyEquivalentModifierMask = [.option]
        open.target = self
        menu.addItem(open)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        statusItem.menu = menu
    }

    @objc private func quit() { NSApp.terminate(nil) }

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

    private func registerHotKey() {
        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                      eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, _ -> OSStatus in
            DispatchQueue.main.async {
                (NSApp.delegate as? AppDelegate)?.togglePanel()
            }
            return noErr
        }, 1, &eventType, nil, nil)

        let id = EventHotKeyID(signature: OSType(0x4449_434F), id: 1)   // 'DICO'
        RegisterEventHotKey(UInt32(kVK_ANSI_D), UInt32(optionKey),
                            id, GetApplicationEventTarget(), 0, &hotKeyRef)
    }

    // MARK: Local keyboard (Esc, ⌘K, ⌘1…⌘9) and click-away

    private func installKeyMonitors() {
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self, self.panel.isVisible else { return event }
            if event.keyCode == 53 { self.escape(); return nil }           // Esc
            if event.modifierFlags.contains(.command) {
                let chars = event.charactersIgnoringModifiers ?? ""
                if chars == "k" { self.model.clear(); return nil }
                if chars == "w" { self.hidePanel(); return nil }
                if let n = Int(chars), (1...9).contains(n) {
                    self.model.saveSense(number: n)
                    return nil
                }
            }
            return event
        }
    }

    /// Esc: the first press wipes the field and the results, the second hides.
    func escape() {
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
            WordView(lookup: lookup, model: model).frame(width: PanelSize.width - 32))
        host.layoutSubtreeIfNeeded()
        return "card \(Int(host.fittingSize.width))×\(Int(host.fittingSize.height))"
    }

    func line(_ label: String, _ body: () throws -> String) {
        do {
            let s = try body().replacingOccurrences(of: "\n", with: " ")
            print("✓ \(label): \(s.prefix(170))")
        } catch {
            failures += 1
            let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            print("✗ \(label): \(msg)")
        }
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
            ExamplesBody(pack: p, own: own).frame(width: PanelSize.width - 60))
        host.layoutSubtreeIfNeeded()
        let merged = ExamplesBody(pack: p, own: own)
        return "\(en.count) en / \(ru.count) ru — \(en.first?.fr ?? "") / \(ru.first?.ru ?? "") | body \(Int(host.fittingSize.width))×\(Int(host.fittingSize.height)) | \(merged.debugSummary)"
    }
    line("examples: empty pack") {
        let p = try DicoClient.examples("zzqqzzxyw")
        guard p.isEmpty else { throw Failed(why: "expected an empty pack") }
        let host = NSHostingView(rootView:
            ExamplesBody(pack: p).frame(width: PanelSize.width - 60))
        host.layoutSubtreeIfNeeded()
        return "empty → \"No examples found\" (body \(Int(host.fittingSize.width))×\(Int(host.fittingSize.height)))"
    }
    line("tutor tu ou vous") {
        let a = try DicoClient.ask("tu ou vous ?", context: "cuisiner")
        return "[\(a.model ?? "?")] \(render(.reponse(a))) — \(a.answer ?? "")"
    }

    // The Word card laid out WITH an expanded Definitions section.
    line("word card + Definitions open") {
        let l = try DicoClient.lookup("cook")
        let d = try DicoClient.definition("cuisiner")
        let model = DicoModel(recentKey: testKey)
        let plain = renderCard(model, l)
        model.preload(card: l, query: "cook", section: .definitions, content: .definition(d))
        let opened = renderCard(model, l)
        guard model.cardTerm == "cuire" || model.cardIsVerb else {
            throw Failed(why: "the card did not adopt a French verb term (got \u{ab} \(model.cardTerm) \u{bb})")
        }
        return "term=\(model.cardTerm) verb=\(model.cardIsVerb) sections=\(model.open.count) | closed \(plain) → open \(opened) | \(render(model))"
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

    print(failures == 0 ? "✓ all good" : "✗ \(failures) failure(s)")
    return failures == 0 ? 0 : 1
}

// MARK: - Entry point

@main
struct DicoMain {
    @MainActor static func main() {
        if CommandLine.arguments.contains("--selftest") {
            exit(runSelfTest())
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
