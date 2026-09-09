import SwiftUI
import AppKit
import ServiceManagement

// MARK: - ⚙︎ Settings — the same file the CLI reads
//
// Everything here writes `~/.dico_config.json`, so the panel and the command
// line never disagree. A normal (activating) window, not the floating panel.

@MainActor
final class SettingsWindowController: NSObject, NSWindowDelegate {
    static let shared = SettingsWindowController()
    private var window: NSWindow?

    /// Called when the user picks another global hotkey.
    var onHotkeyChange: ((HotkeyChoice) -> Void)?

    func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 640, height: 540),
                             styleMask: [.titled, .closable, .miniaturizable],
                             backing: .buffered, defer: false)
            w.title = "Dico Settings"
            w.isReleasedWhenClosed = false
            w.center()
            w.delegate = self
            w.contentView = NSHostingView(rootView: SettingsView(
                onHotkeyChange: { [weak self] h in self?.onHotkeyChange?(h) }))
            window = w
        }
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }
}

// MARK: - The window's content

struct SettingsTab: Hashable { let id: String }

struct SettingsView: View {
    var onHotkeyChange: (HotkeyChoice) -> Void = { _ in }
    @StateObject private var store: ConfigStore
    @State private var tab: String

    init(onHotkeyChange: @escaping (HotkeyChoice) -> Void = { _ in },
         store: ConfigStore? = nil, initialTab: String = "tutor") {
        self.onHotkeyChange = onHotkeyChange
        _store = StateObject(wrappedValue: store ?? ConfigStore())
        _tab = State(initialValue: initialTab)
    }

    static let tabs: [(String, String)] = [
        ("tutor", "Tutor"), ("vocab", "Vocabulary"), ("general", "General"),
        ("data", "Offline data"), ("keys", "Shortcuts"),
    ]

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 20) {
                ForEach(SettingsView.tabs, id: \.0) { id, name in
                    let on = tab == id
                    Button { tab = id } label: {
                        Text(name).font(sans(12.5, on ? .semibold : .regular))
                            .foregroundStyle(on ? Palette.bleuInk : Palette.ink(0.45))
                            .padding(.top, 12).padding(.bottom, 10)
                            .overlay(alignment: .bottom) {
                                Rectangle().fill(on ? Palette.bleuInk : .clear).frame(height: 2)
                            }
                    }
                    .buttonStyle(.plain)
                    .focusable(false)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 22)
            Hairline()
            Group {
                switch tab {
                case "vocab": VocabularyTab(store: store)
                case "general": GeneralTab(store: store, onHotkeyChange: onHotkeyChange)
                case "data": OfflineDataTab()
                case "keys": ShortcutsTab()
                default: TutorTab(store: store)
                }
            }
            .padding(.vertical, 20).padding(.horizontal, 22)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(width: 640, height: 540)
        .background(Palette.panel)
        .tint(Palette.vert)
    }
}

// MARK: - Shared bits of visual language

/// A section: a mono eyebrow riding on a hairline, the content, a dimmed caption.
struct SettingsCard<Content: View>: View {
    let title: String
    var caption: String? = nil
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Eyebrow(title)
            content
            if let caption {
                Text(caption).font(sans(11)).foregroundStyle(Palette.ink(0.35))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A small tinted button: accent fill at 0.16, accent ink text.
struct PillButton: View {
    let label: String
    var tint: Color = Palette.bleu
    var help: String = ""
    var busy: Bool = false
    let action: () -> Void

    var body: some View {
        TintButton(label: label, tint: tint, ink: tint == Palette.vert ? Palette.vertInk : Palette.bleuInk,
                   help: help, busy: busy, action: action)
    }
}

/// A switch on the left, the title and a dimmed caption on the right.
struct SwitchRow: View {
    let title: String
    var caption: String? = nil
    @Binding var isOn: Bool

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Toggle("", isOn: $isOn).toggleStyle(.switch).labelsHidden().controlSize(.small)
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(sans(12.5, .medium)).foregroundStyle(Palette.ink)
                if let caption {
                    Text(caption).font(sans(11)).foregroundStyle(Palette.ink(0.35))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

/// The mono text well the paths and keys live in.
struct WellField: ViewModifier {
    func body(content: Content) -> some View {
        content
            .textFieldStyle(.plain).font(mono(11)).foregroundStyle(Palette.ink(0.75))
            .padding(.horizontal, 10).padding(.vertical, 7)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 7, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 7, style: .continuous)
                .strokeBorder(Palette.hairline, lineWidth: 1))
    }
}

// MARK: - Tutor

struct TutorTab: View {
    @ObservedObject var store: ConfigStore
    @State private var detected: [String] = []
    @State private var found: [(name: String, url: String, model: String)] = []
    @State private var probing = false
    @State private var testResult: String? = nil
    @State private var testing = false
    @State private var preset: String = "custom"

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SettingsCard(title: "Tutor",
                             caption: "Powers Ask mode 💬 and « ? » in the CLI. Stored as « llm » in ~/.dico_config.json.") {
                    ChipRow(items: TutorKind.allCases.map { ($0, $0.label) }, selection: $store.tutor)
                    .onChange(of: store.tutor) { _, new in
                        if new == .byok, store.llmURL.isEmpty {
                            apply(ProviderPreset.all[0])
                        }
                        store.save()
                    }
                    Text(store.tutor.blurb).font(sans(11.5)).foregroundStyle(Palette.ink(0.45))
                        .fixedSize(horizontal: false, vertical: true)
                }

                switch store.tutor {
                case .local:  localCard
                case .byok:   byokCard
                case .anthropic: anthropicCard
                case .none:   EmptyView()
                }

                SettingsCard(title: "Test",
                             caption: "Runs « dico --json -a \"Reply with the single word ok\" » and shows the model that answered.") {
                    HStack(spacing: 10) {
                        PillButton(label: testing ? "Asking…" : "Test the tutor",
                                   help: "Ask the tutor one word", busy: testing) { runTest() }
                        if let r = testResult {
                            Text(r).font(sans(11.5))
                                .foregroundStyle(r.hasPrefix("✓") ? Palette.vertInk : Palette.rougeInk)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: 0)
                    }
                }
                Spacer(minLength: 0)
            }
        }
        .onAppear {
            preset = ProviderPreset.matching(url: store.llmURL).id
            probe()
        }
    }

    private var localCard: some View {
        SettingsCard(title: "Local model",
                     caption: "The CLI auto-detects LM Studio on :1234 and Ollama on :11434 — nothing to configure.") {
            HStack(spacing: 8) {
                if probing {
                    ProgressView().controlSize(.small).scaleEffect(0.6)
                    Text("looking for a local server…").font(sans(11.5)).foregroundStyle(Palette.ink(0.45))
                } else if detected.isEmpty {
                    Text("No local server answered.").font(sans(11.5)).foregroundStyle(Palette.rougeInk)
                } else {
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(detected, id: \.self) { d in
                            Text("✓ " + d).font(sans(11.5)).foregroundStyle(Palette.vertInk)
                        }
                        Text("Click a model to pin it — otherwise dico takes whichever answers first.")
                            .font(sans(11)).foregroundStyle(Palette.ink(0.35))
                        ForEach(found, id: \.model) { f in
                            Button {
                                store.llmURL = f.url
                                store.llmModel = f.model
                                store.save()
                            } label: {
                                let pinned = store.llmModel == f.model
                                HStack(spacing: 9) {
                                    Text(pinned ? "◉" : "○").font(sans(11))
                                        .foregroundStyle(pinned ? Palette.vertInk : Palette.ink(0.35))
                                    Text(f.model).font(mono(12)).foregroundStyle(Palette.ink(pinned ? 1 : 0.7))
                                    Text(f.name).font(sans(10.5)).foregroundStyle(Palette.ink(0.35))
                                    Spacer(minLength: 0)
                                    if pinned { Text("pinned").font(sans(10.5)).foregroundStyle(Palette.ink(0.35)) }
                                }
                                .padding(.horizontal, 9).padding(.vertical, 6)
                                .background(RoundedRectangle(cornerRadius: 7, style: .continuous)
                                    .fill(pinned ? Palette.bleu.opacity(0.12) : .clear))
                                .padding(.horizontal, -9)
                            }
                            .buttonStyle(.plain)
                            .help("Pin \(f.model) at \(f.url)")
                        }
                    }
                }
                Spacer(minLength: 0)
                LinkButton(label: "Detect again", help: "GET /v1/models on :1234 and :11434") { probe() }
            }
        }
    }

    private var byokCard: some View {
        SettingsCard(title: "Bring your own key",
                     caption: "Any OpenAI-compatible endpoint. The base URL ends in /v1. The key is stored in ~/.dico_config.json (chmod 600).") {
            HStack(spacing: 6) {
                Text("Provider").font(sans(12, .medium)).frame(width: 66, alignment: .leading)
                Picker("", selection: $preset) {
                    ForEach(ProviderPreset.all) { p in Text(p.name).tag(p.id) }
                }
                .labelsHidden().frame(width: 160)
                .onChange(of: preset) { _, id in
                    if let p = ProviderPreset.all.first(where: { $0.id == id }), id != "custom" {
                        apply(p)
                    }
                }
                Spacer(minLength: 0)
            }
            field("Base URL", text: $store.llmURL, placeholder: "https://api.openai.com/v1")
            field("Model", text: $store.llmModel, placeholder: "gpt-4o-mini")
            secureField("API key", text: $store.llmKey)
        }
    }

    private var anthropicCard: some View {
        SettingsCard(title: "Anthropic",
                     caption: "The CLI picks the Claude model itself. Stored as « anthropic_key ».") {
            secureField("API key", text: $store.anthropicKey)
        }
    }

    private func field(_ label: String, text: Binding<String>, placeholder: String) -> some View {
        HStack(spacing: 6) {
            Text(label).font(sans(12, .medium)).frame(width: 66, alignment: .leading)
            TextField(placeholder, text: text)
                .modifier(WellField())
                .onChange(of: text.wrappedValue) { _, _ in store.scheduleSave() }
        }
    }

    private func secureField(_ label: String, text: Binding<String>) -> some View {
        HStack(spacing: 6) {
            Text(label).font(sans(12, .medium)).frame(width: 66, alignment: .leading)
            SecureField("sk-…", text: text)
                .modifier(WellField())
                .onChange(of: text.wrappedValue) { _, _ in store.scheduleSave() }
        }
    }

    private func apply(_ p: ProviderPreset) {
        preset = p.id
        if !p.url.isEmpty { store.llmURL = p.url }
        if !p.model.isEmpty { store.llmModel = p.model }
        store.save()
    }

    /// GET /v1/models on the two servers the CLI knows about.
    private func probe() {
        probing = true
        detected = []
        Task.detached(priority: .utility) {
            var lines: [String] = []
            var models: [(name: String, url: String, model: String)] = []
            for (name, url) in DicoClient.localServers {
                if let ids = DicoClient.models(at: url), !ids.isEmpty {
                    lines.append("\(name) at \(url) — \(ids.prefix(3).joined(separator: ", "))")
                    for id in ids.prefix(6) { models.append((name, url, id)) }
                }
            }
            let result = lines, picks = models
            await MainActor.run { detected = result; found = picks; probing = false }
        }
    }

    private func runTest() {
        testing = true
        testResult = nil
        Task.detached(priority: .userInitiated) {
            let msg: String
            do {
                let a = try DicoClient.ask("Reply with the single word ok", context: nil)
                let model = a.model ?? "?"
                msg = "✓ \(model) — \((a.answer ?? "").prefix(60))"
            } catch {
                msg = "✗ \((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)"
            }
            let out = msg
            await MainActor.run { testResult = out; testing = false }
        }
    }
}

// MARK: - Vocabulary

struct VocabularyTab: View {
    @ObservedObject var store: ConfigStore
    @State private var paths: DicoClient.Paths? = nil
    @State private var backingUp = false
    @State private var backupResult: String? = nil

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SettingsCard(title: "Auto-save",
                             caption: "With it on, every lookup becomes a flashcard — no need to click a sense.") {
                    SwitchRow(title: "Save every lookup automatically", isOn: $store.autosave)
                    .onChange(of: store.autosave) { _, _ in store.save() }
                }

                SettingsCard(title: "Cards",
                             caption: store.reviewSource == .dico
                                ? "Every saved word is a card, scheduled by dico itself (spaced repetition) — no other app needed. « push to Anki » exports them."
                                : "Reviews this Anki deck through the AnkiConnect add-on (2055492159); Anki must be open.") {
                    HStack(spacing: 6) {
                        Text("Review with").font(sans(12, .medium)).frame(width: 78, alignment: .leading)
                        ChipRow(items: ReviewSource.allCases.map { ($0, $0.label) }, selection: $store.reviewSource)
                            .onChange(of: store.reviewSource) { _, _ in store.save() }
                    }
                    HStack(spacing: 6) {
                        Text("Anki deck").font(sans(12, .medium)).frame(width: 78, alignment: .leading)
                        TextField(AnkiClient.defaultDeck, text: $store.ankiDeck)
                            .modifier(WellField())
                            .onChange(of: store.ankiDeck) { _, _ in store.scheduleSave() }
                    }
                }

                SettingsCard(title: "Backup",
                             caption: (paths?.cards_repo ?? "").isEmpty
                                ? "Put the store in a git repository with a remote and dico pulls, commits and pushes it — « dico --backup »."
                                : "The cards live in a git repository; other machines and scripts can write to it. dico pulls at launch and pushes after saves.") {
                    if let repo = paths?.cards_repo, !repo.isEmpty {
                        HStack(spacing: 10) {
                            Text(repo.replacingOccurrences(of: NSHomeDirectory(), with: "~"))
                                .font(mono(11)).foregroundStyle(Palette.ink(0.75)).lineLimit(1).truncationMode(.middle)
                            Spacer(minLength: 0)
                            PillButton(label: backingUp ? "Backing up…" : "Back up now", busy: backingUp) { backupNow() }
                        }
                        SwitchRow(title: "Back up to git after every save", isOn: $store.cardsAutosync)
                            .onChange(of: store.cardsAutosync) { _, _ in store.save() }
                        if let r = backupResult {
                            Text(r).font(sans(11.5)).foregroundStyle(r.hasPrefix("✓") ? Palette.vertInk : Palette.rougeInk)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }

                SettingsCard(title: "Vocabulary location", caption: envCaption) {
                    pathRow("Markdown", text: $store.vocabPath,
                            placeholder: ConfigStore.defaultVocabPath,
                            help: "The readable view — point it at an Obsidian vault file if you like",
                            types: ["md", "markdown", "txt"])
                    pathRow("JSON store", text: $store.storePath,
                            placeholder: ConfigStore.defaultStorePath,
                            help: "The source of truth the markdown is regenerated from",
                            types: ["json"])
                }
                Spacer(minLength: 0)
            }
        }
        .onAppear { Task.detached { let p = try? DicoClient.paths(); await MainActor.run { paths = p } } }
    }

    private func backupNow() {
        backingUp = true
        Task.detached(priority: .userInitiated) {
            let msg: String
            do {
                let b = try DicoClient.backup()
                msg = (b.error ?? "").isEmpty ? "✓ \((b.steps ?? []).joined(separator: ", ").ifEmpty("nothing to do")) → \(b.remote ?? b.repo ?? "")"
                                              : "✗ \(b.error ?? "")"
            } catch {
                msg = "✗ \((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)"
            }
            let out = msg
            await MainActor.run { backupResult = out; backingUp = false }
        }
    }

    private var envCaption: String {
        let env = ConfigStore.envOverrides
        let base = "Empty means the default under ~/.dico/."
        return env.isEmpty ? base
            : base + " ⚠︎ These environment variables are set and win over the config: "
                   + env.joined(separator: ", ") + "."
    }

    private func pathRow(_ label: String, text: Binding<String>, placeholder: String,
                         help: String, types: [String]) -> some View {
        HStack(spacing: 6) {
            Text(label).font(sans(12, .medium)).frame(width: 78, alignment: .leading)
            TextField(placeholder, text: text)
                .modifier(WellField())
                .onChange(of: text.wrappedValue) { _, _ in store.scheduleSave() }
                .help(help)
            LinkButton(label: "Choose…", help: help) {
                pick(into: text, types: types)
            }
            if !text.wrappedValue.isEmpty {
                LinkButton(label: "Default", tint: Palette.ink(0.4), help: "Back to ~/.dico/") {
                    text.wrappedValue = ""
                    store.save()
                }
            }
        }
    }

    private func pick(into text: Binding<String>, types: [String]) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true
        panel.message = "Pick the file dico should write to."
        if panel.runModal() == .OK, let url = panel.url {
            text.wrappedValue = url.path
            store.save()
        }
    }
}

// MARK: - General

struct GeneralTab: View {
    @ObservedObject var store: ConfigStore
    var onHotkeyChange: (HotkeyChoice) -> Void = { _ in }
    @State private var loginItem = false
    @State private var loginError: String? = nil
    @State private var axTrusted = Selection.trusted

    private var selectionCaption: String {
        if !store.selection { return "Off: the hotkey only opens the panel." }
        return axTrusted
            ? "Reading the selection uses the Accessibility permission — granted. Right-click ▸ Services ▸ Look up in Dico works everywhere, with no permission."
            : "Needs the Accessibility permission (System Settings ▸ Privacy & Security ▸ Accessibility ▸ Dico). Until then the hotkey only opens the panel; right-click ▸ Services ▸ Look up in Dico works without it."
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SettingsCard(title: "Word card") {
                    SwitchRow(title: "Show an example sentence", isOn: $store.examples)
                    .onChange(of: store.examples) { _, _ in store.save() }
                }

                SettingsCard(title: "X-ray roles",
                             caption: "off = instant · on = about 3 s, and it needs `uv` on the PATH.") {
                    SwitchRow(title: "Grammatical roles via spaCy", isOn: $store.xraySpacy)
                    .onChange(of: store.xraySpacy) { _, _ in store.save() }
                }

                SettingsCard(title: "Appearance",
                             caption: "The panel and this window. « System » follows macOS.") {
                    ChipRow(items: Appearance.choices, selection: $store.appearance)
                        .onChange(of: store.appearance) { _, a in
                            store.save()
                            Appearance.apply(a)
                        }
                }

                SettingsCard(title: "Global hotkey",
                             caption: "Opens and closes the panel from any app. Registered with Carbon — no Accessibility permission is asked for.") {
                    ChipRow(items: HotkeyChoice.all.map { ($0.id, $0.display) },
                            selection: Binding(get: { store.hotkey.id }, set: { id in
                                guard let h = HotkeyChoice.all.first(where: { $0.id == id }) else { return }
                                store.hotkey = h
                                store.save()
                                onHotkeyChange(h)
                            }), monoKeys: true)
                }

                SettingsCard(title: "Look up the selection",
                             caption: selectionCaption) {
                    SwitchRow(title: "\(store.hotkey.display) with text selected looks it up", isOn: $store.selection)
                    .onChange(of: store.selection) { _, on in
                        store.save()
                        if on && !Selection.trusted { Selection.requestAccess() }
                        axTrusted = Selection.trusted
                    }
                    if store.selection && !axTrusted {
                        HStack(spacing: 9) {
                            Text("Accessibility not granted yet — the hotkey only opens the panel.")
                                .font(sans(11.5)).foregroundStyle(Palette.jauneInk)
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                            TintButton(label: "Grant access…", tint: Palette.jaune, ink: Palette.jauneInk,
                                       help: "Opens System Settings ▸ Privacy & Security ▸ Accessibility") {
                                Selection.requestAccess()
                            }
                            LinkButton(label: "Check again", tint: Palette.ink(0.4)) { axTrusted = Selection.trusted }
                        }
                        .padding(.horizontal, 11).padding(.vertical, 9)
                        .background(Palette.jaune.opacity(0.08), in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous)
                            .strokeBorder(Palette.jaune.opacity(0.2), lineWidth: 1))
                    }
                }

                SettingsCard(title: "Launch at login",
                             caption: loginError ?? "macOS keeps Dico in the menu bar from the next login on.") {
                    SwitchRow(title: "Start Dico when I log in", isOn: $loginItem)
                    .onChange(of: loginItem) { _, want in setLogin(want) }
                }
                Spacer(minLength: 0)
            }
        }
        .onAppear {
            loginItem = SMAppService.mainApp.status == .enabled
            axTrusted = Selection.trusted
        }
        // The grant happens in System Settings: notice it without a click.
        .onReceive(Timer.publish(every: 1.5, on: .main, in: .common).autoconnect()) { _ in
            if store.selection && !axTrusted { axTrusted = Selection.trusted }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            axTrusted = Selection.trusted
        }
    }

    private func setLogin(_ want: Bool) {
        do {
            if want { try SMAppService.mainApp.register() }
            else { try SMAppService.mainApp.unregister() }
            loginError = nil
        } catch {
            loginError = "macOS refused: \(error.localizedDescription) — an app run from build/ often cannot register; copy it to /Applications first (./install.sh)."
            loginItem = SMAppService.mainApp.status == .enabled
        }
    }
}

// MARK: - Offline data

struct OfflineDataTab: View {
    @State private var log: [String] = []
    @State private var running = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SettingsCard(title: "Offline data",
                         caption: "Downloads and builds the conjugations, the Lexique and Grammalecte — « dico --setup --no-llm ». It can take a few minutes.") {
                HStack(spacing: 10) {
                    PillButton(label: running ? "Building…" : "Build / refresh",
                               help: "Run dico --setup --no-llm", busy: running) { build() }
                    PillButton(label: "Take the tour", tint: Palette.vert,
                               help: "Opens Terminal and runs dico --tour") { tour() }
                    Spacer(minLength: 0)
                    Text("a few minutes, once").font(sans(11)).foregroundStyle(Palette.ink(0.35))
                }
            }
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 2) {
                        if log.isEmpty {
                            Text("Nothing yet — the output of « dico --setup » will show up here.")
                                .font(mono(10.5)).foregroundStyle(Palette.ink(0.35))
                        }
                        ForEach(Array(log.enumerated()), id: \.offset) { i, line in
                            Text(line)
                                .font(mono(10.5)).lineSpacing(4)
                                .foregroundStyle(Palette.ink(line.hasPrefix("$") ? 0.75 : 0.5))
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .id(i)
                        }
                    }
                    .padding(.horizontal, 13).padding(.vertical, 12)
                }
                .frame(maxWidth: .infinity)
                .background(Palette.well, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .strokeBorder(Palette.ink(0.06), lineWidth: 1))
                .onChange(of: log.count) { _, n in
                    withAnimation { proxy.scrollTo(n - 1, anchor: .bottom) }
                }
            }
            Spacer(minLength: 0)
        }
    }

    private func build() {
        guard !running else { return }
        running = true
        log = ["$ dico --setup --no-llm"]
        DicoClient.stream(["--setup", "--no-llm"],
                          onLine: { line in log.append(line) },
                          onExit: { status in
                              log.append(status == 0 ? "✓ done" : "✗ exited with \(status)")
                              running = false
                          })
    }

    /// Opens Terminal on a tiny script — the tour is interactive, so it belongs
    /// in a real terminal, not in this window.
    private func tour() {
        let path = NSTemporaryDirectory() + "dico-tour.command"
        let script = "#!/bin/sh\nexec dico --tour\n"
        try? script.write(toFile: path, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: NSNumber(value: Int16(0o755))],
                                               ofItemAtPath: path)
        NSWorkspace.shared.open([URL(fileURLWithPath: path)],
                                withApplicationAt: URL(fileURLWithPath: "/System/Applications/Utilities/Terminal.app"),
                                configuration: NSWorkspace.OpenConfiguration())
    }
}

// MARK: - Shortcuts

struct ShortcutsTab: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text("Every shortcut the panel listens to. The global one is set in General.")
                    .font(sans(11.5)).foregroundStyle(Palette.ink(0.45))
                ShortcutsList(columns: 2)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Spacer(minLength: 0)
            }
        }
    }
}


private extension String {
    func ifEmpty(_ other: String) -> String { isEmpty ? other : self }
}
