import SwiftUI
import AppKit

// MARK: - The panel: a rail of modes on the left, the query bar, the result

struct PanelView: View {
    @ObservedObject var model: DicoModel
    @FocusState private var focused: Bool

    /// The Word card carries its own footer (🔈 💬 … ⌘D ⌘R ⌘E ⌘J).
    private var showsFooter: Bool {
        if case .mot = model.outcome { return false }
        return true
    }

    var body: some View {
        HStack(spacing: 0) {
            Rail(model: model) { m in
                model.setMode(m)
                focused = true
            }
            Rectangle().fill(Palette.hairline).frame(width: 1)
            VStack(spacing: 0) {
                if model.mode == .cartes {
                    ReviewView(model: model)
                } else {
                    queryBar
                    Hairline(structural: true)
                    results
                }
                if showsFooter {
                    Hairline(structural: true)
                    footer
                }
            }
            .frame(width: PanelSize.content)
        }
        .frame(width: PanelSize.width, height: PanelSize.height)
        .background(Palette.panel)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Palette.ink(0.10), lineWidth: 1)
        )
        // (shadow: native, through NSPanel.hasShadow — a SwiftUI shadow would be clipped at the window edges)
        .overlay(alignment: .bottom) { toast }
        .overlay {
            if model.showShortcuts {
                ZStack {
                    // Click anywhere beside the sheet to put it away.
                    Palette.scrim
                        .contentShape(Rectangle())
                        .onTapGesture { model.showShortcuts = false }
                    ShortcutsSheet { model.showShortcuts = false }
                }
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.16), value: model.showShortcuts)
        // Springy appearance
        .scaleEffect(model.shown ? 1 : 0.90)
        .opacity(model.shown ? 1 : 0)
        .animation(.spring(response: 0.32, dampingFraction: 0.68), value: model.shown)
        .padding(PanelSize.margin)
        .tint(model.mode.accentInk)
        .onReceive(NotificationCenter.default.publisher(for: .dicoFocusField)) { _ in
            focused = true
        }
    }

    // MARK: Query bar

    /// 🇷🇺 as soon as the field holds Cyrillic; 🇫🇷 otherwise.
    private var queryFlag: String {
        model.query.unicodeScalars.contains { (0x0400...0x04FF).contains($0.value) } ? "🇷🇺" : "🇫🇷"
    }

    private var queryBar: some View {
        HStack(spacing: 10) {
            Text(queryFlag).font(.system(size: 13))
            TextField("", text: $model.query,
                      prompt: Text(model.mode.placeholder).font(serif(20)).foregroundColor(Palette.ink(0.28)))
                .textFieldStyle(.plain)
                .font(serif(20))
                .foregroundStyle(Palette.ink)
                .focused($focused)
                .onSubmit { model.submit() }
                .onChange(of: model.query) { _, _ in model.inputChanged() }
                .help("Type and press ⏎. ⌘K clears, ⌘/ lists every shortcut.")
            if model.busy {
                ProgressView().controlSize(.small).scaleEffect(0.7)
            } else if !model.query.isEmpty {
                Button { model.clear(); focused = true } label: {
                    KeyHint("⌘K clear", alpha: 0.25)
                }
                .buttonStyle(.plain)
                .help("Clear the field (⌘K)")
            }
            if model.mode == .demander, let c = model.askContext, !c.isEmpty {
                Button { model.dropAskContext() } label: {
                    HStack(spacing: 6) {
                        Text("about \u{ab} \(c) \u{bb}").font(sans(10.5))
                        Text("✕").font(.system(size: 9)).opacity(0.7)
                    }
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(Palette.rose.opacity(0.14), in: Capsule())
                    .foregroundStyle(Palette.roseInk)
                }
                .buttonStyle(.plain)
                .help("The tutor gets this word as context — click to drop it")
            }
        }
        .padding(.top, 14).padding(.horizontal, 16).padding(.bottom, 12)
    }

    // MARK: Results area

    @ViewBuilder private var results: some View {
        switch model.outcome {
        case .vide:
            EmptyStateView(model: model)
        case .chargement:
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text(model.mode == .demander ? "thinking…" : "searching…")
                    .font(sans(12)).foregroundStyle(Palette.ink(0.45))
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .mot(let l):
            WordView(lookup: l, model: model)
        case .conjugaison(let c):
            scroll(top: 13) { ConjugationView(conj: c) }
        case .grammaire(let g, let sentence):
            scroll(top: 16, side: 18) { GrammarView(grammar: g, sentence: sentence, model: model) }
        case .rayonsX(let toks):
            scroll(top: 14, side: 18) { XrayView(tokens: toks) { model.saveToken($0) } }
        case .reponse(let a):
            scroll(top: 16, side: 18) {
                AnswerView(answer: a, context: model.askContext) { model.saveAnswer(a) }
            }
        case .erreur(let issue):
            scroll(top: 20, side: 18) { IssueView(issue: issue, model: model) }
        }
    }

    private func scroll<V: View>(top: CGFloat, side: CGFloat = 16,
                                 @ViewBuilder _ content: () -> V) -> some View {
        ScrollView {
            content()
                .padding(.top, top).padding(.horizontal, side).padding(.bottom, 12)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    /// One line, always: how to see the rest, how to get out, how to get in.
    private var footer: some View {
        HStack(spacing: 14) {
            Button { model.showShortcuts = true } label: { Text("⌘/ shortcuts") }
                .buttonStyle(.plain)
                .help("Show every keyboard shortcut (⌘/)")
            Text("Esc clear")
            Text("\(model.hotkeyLabel) anywhere")
                .help("\(model.hotkeyLabel) opens the panel from any app — change it in Settings (⌘,)")
            Spacer(minLength: 0)
        }
        .font(mono(9.5)).foregroundStyle(Palette.ink(0.28))
        .padding(.top, 10).padding(.horizontal, 16).padding(.bottom, 12)
    }

    @ViewBuilder private var toast: some View {
        if let t = model.toast {
            let check = t.hasPrefix("✓ ")
            HStack(spacing: 8) {
                if check { Text("✓").font(sans(12)).foregroundStyle(Palette.toastCheck) }
                Text(check ? String(t.dropFirst(2)) : t).font(sans(12)).lineLimit(1)
            }
            .padding(.horizontal, 14).padding(.vertical, 7)
            .background(Palette.ink, in: Capsule())
            .foregroundStyle(Palette.panel)
            .shadow(color: .black.opacity(0.28), radius: 12, y: 5)
            .padding(.leading, PanelSize.rail)       // centred over the content, not the rail
            .padding(.bottom, 56)                    // clears the action row
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}

// MARK: - The rail

/// The five modes, stacked; the « é » on top, ⚙︎ at the bottom.
struct Rail: View {
    @ObservedObject var model: DicoModel
    let pick: (Mode) -> Void

    var body: some View {
        VStack(spacing: 4) {
            Text("é").font(serif(20))
                .foregroundStyle(LinearGradient(colors: [Palette.bleu, Palette.rose],
                                                startPoint: .topLeading, endPoint: .bottomTrailing))
                .padding(.bottom, 10)
            ForEach(Mode.allCases) { m in
                RailItem(mode: m, active: model.mode == m) { pick(m) }
            }
            Spacer(minLength: 0)
            Button { NotificationCenter.default.post(name: .dicoOpenSettings, object: nil) } label: {
                Text("⚙︎").font(sans(12)).foregroundStyle(Palette.ink).opacity(0.4)
            }
            .buttonStyle(.plain)
            .help("Settings (⌘,)")
        }
        .padding(.top, 14).padding(.bottom, 12)
        .frame(width: PanelSize.rail).frame(maxHeight: .infinity)
        .background(Palette.rail)
    }
}

struct RailItem: View {
    let mode: Mode
    let active: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            VStack(spacing: 3) {
                Text(mode.icon).font(.system(size: 14))
                Text(mode.short).font(sans(8.5, active ? .semibold : .regular))
                    .foregroundStyle(active ? mode.accentInk : Palette.ink)
            }
            .frame(width: 44)
            .padding(.vertical, 7)
            .background(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(active ? mode.accent.opacity(0.18) : (hover ? Palette.ink(0.05) : .clear)))
            .opacity(active || hover ? 1 : 0.45)
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help("\(mode.label) mode \(mode.icon) — ⌘⇧\((Mode.allCases.firstIndex(of: mode) ?? 0) + 1)")
    }
}

/// Copies text to the clipboard — « Copy », in the accent, no capsule.
struct CopyButton: View {
    let text: String
    var label: String = "Copy"
    var tint: Color = Palette.bleuInk
    @ObservedObject var model: DicoModel

    var body: some View {
        Button {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
            model.flash("✓ copied")
        } label: {
            Text(label).font(sans(10.5, .semibold)).foregroundStyle(tint)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Empty state: something to press, and the recent queries

struct EmptyStateView: View {
    @ObservedObject var model: DicoModel

    /// One example per thing dico can do, so the first click teaches the tool.
    static let examples: [(query: String, what: String, mode: Mode)] = [
        ("cook", "a word", .mot),
        ("maison", "a French word", .mot),
        ("aller", "a verb to conjugate", .conjuguer),
        ("elle est parti", "to correct", .grammaire),
    ]

    /// Someone with a deck and a history does not need the examples.
    private var seasoned: Bool { !model.recent.isEmpty || (model.home?.total ?? 0) > 0 }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            if seasoned { today }
            if !seasoned { VStack(alignment: .leading, spacing: 9) {
                Eyebrow("try one")
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 8), GridItem(.flexible(), spacing: 8)],
                          spacing: 8) {
                    ForEach(EmptyStateView.examples, id: \.query) { ex in
                        Button { model.run(ex.query, mode: ex.mode) } label: {
                            HStack(alignment: .firstTextBaseline, spacing: 9) {
                                Text(ex.query).font(serif(17)).foregroundStyle(Palette.ink)
                                Text(ex.what).font(sans(10.5)).foregroundStyle(Palette.ink(0.35))
                                Spacer(minLength: 0)
                            }
                            .padding(.horizontal, 11).padding(.vertical, 9)
                            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                        }
                        .buttonStyle(.plain)
                        .help("Run \u{ab} \(ex.query) \u{bb}")
                    }
                }
            } }

            if !model.recent.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Eyebrow("recent", trailing: AnyView(
                        LinkButton(label: "Clear", tint: Palette.ink(0.30), size: 10.5,
                                   help: "Forget the recent queries") { model.forgetRecent() }))
                    FlowLayout(spacing: 18, lineSpacing: 2) {
                        ForEach(model.recent, id: \.self) { q in
                            RecentChip(text: q) { model.run(q, mode: model.mode) }
                        }
                    }
                }
            } else if !seasoned {
                Text("\(model.hotkeyLabel) opens this from any app · ⌘/ shows every shortcut")
                    .font(sans(10.5)).foregroundStyle(Palette.ink(0.30))
            }
        }
        .padding(.top, 20).padding(.horizontal, 18)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .onAppear { model.refreshHome() }
    }

    /// « TODAY — 12 due · 3 learning · 20 new   Review → » and the last words saved.
    private var today: some View {
        let d = model.home
        let c = d?.ankiCounts ?? AnkiCounts()
        let waiting = c.due + c.learning + min(c.new, 20)
        return VStack(alignment: .leading, spacing: 9) {
            Eyebrow("today", trailing: AnyView(
                Text("\(d?.total ?? 0) words in the deck").font(sans(10.5)).foregroundStyle(Palette.ink(0.30))))
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                if waiting > 0 {
                    (Text("\(waiting) card\(waiting == 1 ? "" : "s") to review").foregroundStyle(Palette.ink)
                        + Text(" — \(c.due) due · \(c.learning) learning · \(c.new) new").foregroundStyle(Palette.ink(0.4)))
                        .font(sans(12.5))
                    TintButton(label: "Review", keys: "⌘⇧6", tint: Palette.jaune, ink: Palette.jauneInk,
                               help: "Open the Cards mode") { model.setMode(.cartes) }
                } else if d != nil {
                    Text("Nothing to review. Every word you look up becomes a card.")
                        .font(sans(12.5)).foregroundStyle(Palette.ink(0.5))
                } else {
                    Text("…").font(sans(12.5)).foregroundStyle(Palette.ink(0.3))
                }
                Spacer(minLength: 0)
            }
            if let saved = d?.recent, !saved.isEmpty {
                Eyebrow("saved lately").padding(.top, 8)
                FlowLayout(spacing: 18, lineSpacing: 4) {
                    ForEach(saved, id: \.self) { w in
                        Button { model.run(w.front ?? "", mode: .mot) } label: {
                            HStack(alignment: .firstTextBaseline, spacing: 6) {
                                Text(w.front ?? "").font(serif(16)).foregroundStyle(Palette.ink(0.85))
                                if let g = w.gloss, !g.isEmpty {
                                    Text(g).font(sans(10.5)).foregroundStyle(Palette.ink(0.35)).lineLimit(1)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                        .help("Look \u{ab} \(w.front ?? "") \u{bb} up again")
                    }
                }
            }
        }
    }
}

struct RecentChip: View {
    let text: String
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Text(text.count > 34 ? String(text.prefix(33)) + "…" : text)
                .font(serif(16)).lineLimit(1)
                .foregroundStyle(Palette.ink(hover ? 1 : 0.75))
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help("Run \u{ab} \(text) \u{bb} again")
    }
}

// MARK: - Errors

struct IssueView: View {
    let issue: Issue
    @ObservedObject var model: DicoModel

    var body: some View {
        switch issue {
        case .notInstalled:
            recipe(title: "dico is not installed",
                   body: "The panel drives the dico command line tool. Install it, then build the offline data.",
                   commands: ["uv tool install git+https://github.com/mechanicpanic/dico", "dico --setup"])
        case .setupNeeded:
            recipe(title: "Offline data not built",
                   body: "The conjugations, Lexique and Grammalecte databases have not been downloaded yet.",
                   commands: ["dico --setup"])
        case .plain(let msg):
            VStack(alignment: .leading, spacing: 9) {
                Eyebrow("problem", tint: Palette.rougeInk)
                Text(msg).font(sans(12.5)).lineSpacing(3).foregroundStyle(Palette.ink(0.85))
                    .fixedSize(horizontal: false, vertical: true)
                Text("Esc clears · ⌘/ lists every shortcut")
                    .font(mono(9.5)).foregroundStyle(Palette.ink(0.28))
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func recipe(title: String, body: String, commands: [String]) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(serif(24)).foregroundStyle(Palette.ink)
                Text(body).font(sans(12.5)).lineSpacing(3).foregroundStyle(Palette.ink(0.5))
                    .frame(maxWidth: 400, alignment: .leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            VStack(alignment: .leading, spacing: 8) {
                ForEach(commands, id: \.self) { cmd in
                    HStack(spacing: 10) {
                        Text(cmd).font(mono(11)).foregroundStyle(Palette.ink(0.85))
                            .textSelection(.enabled)
                            .lineLimit(1).truncationMode(.tail)
                        Spacer(minLength: 0)
                        CopyButton(text: cmd, model: model)
                    }
                    .padding(.horizontal, 11).padding(.vertical, 9)
                    .background(Palette.surface, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Palette.ink(0.06), lineWidth: 1))
                }
            }
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Eyebrow("also", rule: false)
                Text("Multitran is optional — the Russian pane falls back to the Wiktionnaire without it.")
                    .font(sans(11.5)).foregroundStyle(Palette.ink(0.4))
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.top, 4)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

extension Notification.Name {
    static let dicoFocusField = Notification.Name("dicoFocusField")
    /// Posted by the ⚙︎ button; the delegate opens the window (and wires the
    /// hotkey callback, which only it can honour).
    static let dicoOpenSettings = Notification.Name("dicoOpenSettings")
}
