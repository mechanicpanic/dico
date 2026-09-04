import SwiftUI
import AppKit
import Carbon.HIToolbox

// MARK: - The floating panel

/// A non-activating NSPanel that can still become key — you have to type in it.
final class FloatingPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) {   // Esc
        (NSApp.delegate as? AppDelegate)?.hidePanel()
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
        // 520×420 of content + 12 pt of margin all around for the shadow.
        let rect = NSRect(x: 0, y: 0, width: 544, height: 444)
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
            if event.keyCode == 53 { self.hidePanel(); return nil }        // Esc
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
func runSelfTest() {
    _ = NSApplication.shared   // AppKit must exist to lay out an off-screen view

    /// Force the layout of the matching view, off screen: this is what really
    /// exercises the rendering (FlowLayout, Grid, markdown…).
    func render(_ outcome: Outcome) -> String {
        let model = DicoModel()
        model.outcome = outcome
        let host = NSHostingView(rootView: PanelView(model: model))
        host.frame = NSRect(x: 0, y: 0, width: 544, height: 444)
        host.layoutSubtreeIfNeeded()
        return "view \(Int(host.fittingSize.width))×\(Int(host.fittingSize.height))"
    }

    func line(_ label: String, _ body: () throws -> String) {
        do {
            let s = try body().replacingOccurrences(of: "\n", with: " ")
            print("✓ \(label): \(s.prefix(160))")
        } catch {
            let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            print("✗ \(label): \(msg)")
        }
    }

    line("word cook") {
        let l = try DicoClient.lookup("cook")
        let senses = (l.senses ?? []).prefix(3).map { $0.display }.joined(separator: ", ")
        return "direction=\(l.direction ?? "?") transl=\(l.translation ?? "?") | \(senses) | \(render(.mot(l)))"
    }
    line("conj aller") {
        let c = try DicoClient.conjugate("aller")
        let p = (c.tenses?["présent"] ?? []).joined(separator: ", ")
        return "\(c.infinitive ?? "?") — \(c.orderedTenses.count) tenses — présent: \(p) | \(render(.conjugaison(c)))"
    }
    line("gram elle est parti") {
        let g = try DicoClient.grammar("elle est parti")
        let n = (g.errors?.count ?? 0) + (g.spelling?.count ?? 0)
        return "\(n) mistake(s) → \u{201c}\(g.corrected ?? "?")\u{201d} | \(render(.grammaire(g, "elle est parti")))"
    }
    line("x-ray je vais au marché") {
        let t = try DicoClient.xray("je vais au marché demain")
        return "\(t.count) words — \(t.map { $0.lemma ?? "?" }.joined(separator: "/")) | \(render(.rayonsX(t)))"
    }
    line("tutor tu ou vous") {
        let a = try DicoClient.ask("tu ou vous ?", context: "cook")
        return "[\(a.model ?? "?")] \(render(.reponse(a))) — \(a.answer ?? "")"
    }
}

// MARK: - Entry point

@main
struct DicoMain {
    @MainActor static func main() {
        if CommandLine.arguments.contains("--selftest") {
            runSelfTest()
            exit(0)
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
