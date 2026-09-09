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
    @StateObject private var store = ConfigStore()
    @State private var tab = "tutor"

    var body: some View {
        TabView(selection: $tab) {
            TutorTab(store: store)
                .tabItem { Label("Tutor", systemImage: "bubble.left.and.text.bubble.right") }
                .tag("tutor")
            VocabularyTab(store: store)
                .tabItem { Label("Vocabulary", systemImage: "square.and.arrow.down") }
                .tag("vocab")
            GeneralTab(store: store, onHotkeyChange: onHotkeyChange)
                .tabItem { Label("General", systemImage: "gearshape") }
                .tag("general")
            OfflineDataTab()
                .tabItem { Label("Offline data", systemImage: "internaldrive") }
                .tag("data")
            ShortcutsTab()
                .tabItem { Label("Shortcuts", systemImage: "keyboard") }
                .tag("keys")
        }
        .padding(16)
        .frame(width: 640, height: 540)
    }
}

// MARK: - Shared bits of visual language

/// A titled block, rounded like the panel's sections.
struct SettingsCard<Content: View>: View {
    let title: String
    var caption: String? = nil
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased())
                .font(rounded(9.5, .bold)).foregroundStyle(.tertiary).tracking(0.7)
            content
            if let caption {
                Text(caption).font(rounded(10.5, .regular)).foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 10))
    }
}

/// A small pill button, like the panel's chips.
struct PillButton: View {
    let label: String
    var tint: Color = Palette.bleu
    var help: String = ""
    var busy: Bool = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                if busy { ProgressView().controlSize(.small).scaleEffect(0.5).frame(width: 10, height: 10) }
                Text(label).font(rounded(11.5, .medium))
            }
            .padding(.horizontal, 10).padding(.vertical, 5)
            .background(tint.opacity(0.15), in: Capsule())
            .foregroundStyle(tint)
        }
        .buttonStyle(.plain)
        .help(help.isEmpty ? label : help)
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
            VStack(alignment: .leading, spacing: 12) {
                SettingsCard(title: "Tutor",
                             caption: "Powers Ask mode 💬 and « ? » in the CLI. Stored as « llm » in ~/.dico_config.json.") {
                    Picker("", selection: $store.tutor) {
                        ForEach(TutorKind.allCases) { k in Text(k.label).tag(k) }
                    }
                    .pickerStyle(.segmented).labelsHidden()
                    .onChange(of: store.tutor) { _, new in
                        if new == .byok, store.llmURL.isEmpty {
                            apply(ProviderPreset.all[0])
                        }
                        store.save()
                    }
                    Text(store.tutor.blurb).font(rounded(11, .regular)).foregroundStyle(.secondary)
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
                            Text(r).font(rounded(11, .regular))
                                .foregroundStyle(r.hasPrefix("✓") ? Palette.vert : Palette.rouge)
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
                    Text("looking for a local server…").font(rounded(11, .regular)).foregroundStyle(.secondary)
                } else if detected.isEmpty {
                    Text("No local server answered.").font(rounded(11, .regular)).foregroundStyle(Palette.rouge)
                } else {
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(detected, id: \.self) { d in
                            Text("✓ " + d).font(rounded(11, .regular)).foregroundStyle(Palette.vert)
                        }
                        Text("Click a model to pin it — otherwise dico takes whichever answers first.")
                            .font(rounded(10, .regular)).foregroundStyle(.secondary)
                        ForEach(found, id: \.model) { f in
                            Button {
                                store.llmURL = f.url
                                store.llmModel = f.model
                                store.save()
                            } label: {
                                HStack(spacing: 5) {
                                    Image(systemName: store.llmModel == f.model
                                          ? "largecircle.fill.circle" : "circle")
                                        .foregroundStyle(store.llmModel == f.model ? Palette.vert : .secondary)
                                    Text(f.model).font(rounded(11, .medium))
                                    Text(f.name).font(rounded(10, .regular)).foregroundStyle(.secondary)
                                }
                            }
                            .buttonStyle(.plain)
                            .help("Pin \(f.model) at \(f.url)")
                        }
                    }
                }
                Spacer(minLength: 0)
                PillButton(label: "Detect again", tint: .secondary, help: "GET /v1/models on :1234 and :11434") { probe() }
            }
        }
    }

    private var byokCard: some View {
        SettingsCard(title: "Bring your own key",
                     caption: "Any OpenAI-compatible endpoint. The base URL ends in /v1. The key is stored in ~/.dico_config.json (chmod 600).") {
            HStack(spacing: 6) {
                Text("Provider").font(rounded(11, .medium)).frame(width: 66, alignment: .leading)
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
            Text(label).font(rounded(11, .medium)).frame(width: 66, alignment: .leading)
            TextField(placeholder, text: text)
                .textFieldStyle(.roundedBorder).font(rounded(11.5, .regular))
                .onChange(of: text.wrappedValue) { _, _ in store.scheduleSave() }
        }
    }

    private func secureField(_ label: String, text: Binding<String>) -> some View {
        HStack(spacing: 6) {
            Text(label).font(rounded(11, .medium)).frame(width: 66, alignment: .leading)
            SecureField("sk-…", text: text)
                .textFieldStyle(.roundedBorder).font(rounded(11.5, .regular))
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

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                SettingsCard(title: "Auto-save",
                             caption: "With it on, every lookup becomes a flashcard — no need to click a sense.") {
                    Toggle(isOn: $store.autosave) {
                        Text("Save every lookup automatically").font(rounded(12, .medium))
                    }
                    .toggleStyle(.switch)
                    .onChange(of: store.autosave) { _, _ in store.save() }
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
            Text(label).font(rounded(11, .medium)).frame(width: 78, alignment: .leading)
            TextField(placeholder, text: text)
                .textFieldStyle(.roundedBorder).font(rounded(11, .regular))
                .onChange(of: text.wrappedValue) { _, _ in store.scheduleSave() }
                .help(help)
            PillButton(label: "Choose…", tint: .secondary, help: help) {
                pick(into: text, types: types)
            }
            if !text.wrappedValue.isEmpty {
                PillButton(label: "Default", tint: .secondary, help: "Back to ~/.dico/") {
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
            VStack(alignment: .leading, spacing: 12) {
                SettingsCard(title: "Word card") {
                    Toggle(isOn: $store.examples) {
                        Text("Show an example sentence").font(rounded(12, .medium))
                    }
                    .toggleStyle(.switch)
                    .onChange(of: store.examples) { _, _ in store.save() }
                }

                SettingsCard(title: "X-ray roles",
                             caption: "off = instant · on = about 3 s, and it needs `uv` on the PATH.") {
                    Toggle(isOn: $store.xraySpacy) {
                        Text("Grammatical roles via spaCy").font(rounded(12, .medium))
                    }
                    .toggleStyle(.switch)
                    .onChange(of: store.xraySpacy) { _, _ in store.save() }
                }

                SettingsCard(title: "Global hotkey",
                             caption: "Opens and closes the panel from any app. Registered with Carbon — no Accessibility permission is asked for.") {
                    HStack(spacing: 6) {
                        ForEach(HotkeyChoice.all) { h in
                            Button {
                                store.hotkey = h
                                store.save()
                                onHotkeyChange(h)
                            } label: {
                                Text(h.display)
                                    .font(.system(size: 12, weight: .semibold, design: .rounded))
                                    .padding(.horizontal, 11).padding(.vertical, 6)
                                    .background(
                                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                                            .fill(store.hotkey.id == h.id
                                                  ? Palette.bleu.opacity(0.85)
                                                  : Color.primary.opacity(0.08))
                                    )
                                    .foregroundStyle(store.hotkey.id == h.id ? Color.white : Color.primary)
                            }
                            .buttonStyle(.plain)
                            .help("Use \(h.display) to open the panel")
                        }
                        Spacer(minLength: 0)
                    }
                }

                SettingsCard(title: "Look up the selection",
                             caption: selectionCaption) {
                    Toggle(isOn: $store.selection) {
                        Text("\(store.hotkey.display) with text selected looks it up").font(rounded(12, .medium))
                    }
                    .toggleStyle(.switch)
                    .onChange(of: store.selection) { _, on in
                        store.save()
                        if on && !Selection.trusted { Selection.requestAccess() }
                        axTrusted = Selection.trusted
                    }
                    if store.selection && !axTrusted {
                        HStack(spacing: 8) {
                            Button("Grant access…") { Selection.requestAccess() }
                                .help("Opens System Settings ▸ Privacy & Security ▸ Accessibility")
                            Button("Check again") { axTrusted = Selection.trusted }
                        }
                        .controlSize(.small)
                    }
                }

                SettingsCard(title: "Launch at login",
                             caption: loginError ?? "macOS keeps Dico in the menu bar from the next login on.") {
                    Toggle(isOn: $loginItem) {
                        Text("Start Dico when I log in").font(rounded(12, .medium))
                    }
                    .toggleStyle(.switch)
                    .onChange(of: loginItem) { _, want in setLogin(want) }
                }
                Spacer(minLength: 0)
            }
        }
        .onAppear {
            loginItem = SMAppService.mainApp.status == .enabled
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
                }
            }
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 2) {
                        if log.isEmpty {
                            Text("Nothing yet — the output of « dico --setup » will show up here.")
                                .font(rounded(11, .regular)).foregroundStyle(.tertiary)
                        }
                        ForEach(Array(log.enumerated()), id: \.offset) { i, line in
                            Text(line)
                                .font(.system(size: 10.5, design: .monospaced))
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .id(i)
                        }
                    }
                    .padding(9)
                }
                .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 10))
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
                    .font(rounded(11, .regular)).foregroundStyle(.secondary)
                ShortcutsList(columns: 2)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 10))
                Spacer(minLength: 0)
            }
        }
    }
}
