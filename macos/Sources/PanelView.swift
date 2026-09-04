import SwiftUI
import AppKit

// MARK: - A small "soft tricolore" palette

enum Palette {
    static let bleu = Color(red: 0.30, green: 0.44, blue: 0.86)     // masculine, accents
    static let rose = Color(red: 0.89, green: 0.42, blue: 0.60)     // feminine
    static let rouge = Color(red: 0.85, green: 0.32, blue: 0.34)
    static let vert = Color(red: 0.25, green: 0.65, blue: 0.44)
    static let jaune = Color(red: 0.95, green: 0.78, blue: 0.30)

    static func genderTint(_ g: String?) -> Color {
        switch g {
        case "m": return bleu
        case "f": return rose
        default: return .secondary
        }
    }
    /// ★ according to frequency.
    static func stars(_ band: String?) -> String {
        switch band {
        case "très courant": return "★★★"
        case "courant": return "★★"
        case "moyen": return "★"
        default: return ""
        }
    }
}

/// The content size of the panel. 600 pt fits the seven-tense grid.
enum PanelSize {
    static let width: CGFloat = 600
    static let height: CGFloat = 460
    static let margin: CGFloat = 12          // room for the native shadow
}

func rounded(_ size: CGFloat, _ weight: Font.Weight = .semibold) -> Font {
    .system(size: size, weight: weight, design: .rounded)
}

/// The panel's translucent material (light AND dark).
struct VisualEffect: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.wantsLayer = true
        v.layer?.cornerRadius = 16
        v.layer?.cornerCurve = .continuous
        v.layer?.masksToBounds = true
        v.material = .hudWindow
        v.blendingMode = .behindWindow
        v.state = .active
        return v
    }
    func updateNSView(_ v: NSVisualEffectView, context: Context) {}
}

/// Copies a shell command to the clipboard.
struct CopyButton: View {
    let text: String
    var label: String = "Copy"
    var tint: Color = Palette.vert
    @ObservedObject var model: DicoModel

    var body: some View {
        Button {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
            model.flash("✓ copied")
        } label: {
            Text(label).font(rounded(10.5, .medium))
                .padding(.horizontal, 8).padding(.vertical, 3)
                .background(tint.opacity(0.16), in: Capsule())
                .foregroundStyle(tint)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - The panel

struct PanelView: View {
    @ObservedObject var model: DicoModel
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().opacity(0.35)
            results
            Divider().opacity(0.35)
            footer
        }
        .frame(width: PanelSize.width, height: PanelSize.height)
        .background(VisualEffect())
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
        )
        // (shadow: native, through NSPanel.hasShadow — a SwiftUI shadow would be clipped at the window edges)
        .overlay(alignment: .bottom) { toast }
        .overlay {
            if model.showShortcuts {
                ZStack {
                    // Click anywhere beside the sheet to put it away.
                    Color.black.opacity(0.18)
                        .contentShape(Rectangle())
                        .onTapGesture { model.showShortcuts = false }
                    ShortcutsSheet { model.showShortcuts = false }
                }
                .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.16), value: model.showShortcuts)
        // Springy appearance
        .scaleEffect(model.shown ? 1 : 0.90)
        .opacity(model.shown ? 1 : 0)
        .animation(.spring(response: 0.32, dampingFraction: 0.68), value: model.shown)
        .padding(PanelSize.margin)
        .onReceive(NotificationCenter.default.publisher(for: .dicoFocusField)) { _ in
            focused = true
        }
    }

    // MARK: Header: field + mode chips

    private var header: some View {
        VStack(spacing: 10) {
            HStack(spacing: 8) {
                Text("🇫🇷").font(.system(size: 15))
                TextField(model.mode.placeholder, text: $model.query)
                    .textFieldStyle(.plain)
                    .font(rounded(16, .medium))
                    .focused($focused)
                    .onSubmit { model.submit() }
                    .onChange(of: model.query) { _, _ in model.inputChanged() }
                    .help("Type and press ⏎. ⌘K clears, ⌘/ lists every shortcut.")
                if model.busy {
                    ProgressView().controlSize(.small).scaleEffect(0.7)
                } else if !model.query.isEmpty {
                    Button { model.clear(); focused = true } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(.tertiary)
                    }
                    .buttonStyle(.plain)
                    .help("Clear the field (⌘K)")
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 9)
            .background(Color.primary.opacity(0.07), in: Capsule())

            HStack(spacing: 6) {
                ForEach(Mode.allCases) { m in
                    Button {
                        model.mode = m
                        focused = true
                        if !model.query.trimmingCharacters(in: .whitespaces).isEmpty { model.submit() }
                    } label: {
                        HStack(spacing: 4) {
                            Text(m.icon).font(.system(size: 10))
                            Text(m.label).font(rounded(11, .medium))
                        }
                        .padding(.horizontal, 9).padding(.vertical, 5)
                        .background(
                            Capsule().fill(model.mode == m
                                           ? Palette.bleu.opacity(0.85)
                                           : Color.primary.opacity(0.07))
                        )
                        .foregroundStyle(model.mode == m ? Color.white : Color.primary.opacity(0.75))
                    }
                    .buttonStyle(.plain)
                    .help("\(m.label) mode \(m.icon) — ⌘⇧\((Mode.allCases.firstIndex(of: m) ?? 0) + 1)")
                }
                Spacer(minLength: 0)
                if model.mode == .demander, let c = model.askContext, !c.isEmpty {
                    Button { model.dropAskContext() } label: {
                        HStack(spacing: 4) {
                            Text("about \u{ab} \(c) \u{bb}")
                                .font(rounded(10.5, .medium)).foregroundStyle(Palette.bleu)
                            Image(systemName: "xmark").font(.system(size: 7, weight: .bold))
                                .foregroundStyle(Palette.bleu.opacity(0.7))
                        }
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(Palette.bleu.opacity(0.12), in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .help("The tutor gets this word as context — click to drop it")
                }
            }
            .animation(.easeOut(duration: 0.15), value: model.mode)
        }
        .padding(.horizontal, 14).padding(.top, 13).padding(.bottom, 11)
    }

    // MARK: Results area

    private var results: some View {
        ScrollViewReader { proxy in
            resultsBody
                .onChange(of: model.lastOpened) { _, section in
                    guard let section else { return }
                    withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo(section, anchor: .bottom) }
                }
        }
    }

    private var resultsBody: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                switch model.outcome {
                case .vide:
                    EmptyStateView(model: model)
                case .chargement:
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text(model.mode == .demander ? "thinking…" : "searching…")
                            .font(rounded(12, .regular)).foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .center).padding(.top, 40)
                case .mot(let l):
                    WordView(lookup: l, model: model)
                case .conjugaison(let c):
                    ConjugationView(conj: c)
                case .grammaire(let g, let sentence):
                    GrammarView(grammar: g, sentence: sentence, model: model)
                case .rayonsX(let toks):
                    XrayView(tokens: toks)
                case .reponse(let a):
                    AnswerView(answer: a, context: model.askContext)
                case .erreur(let issue):
                    IssueView(issue: issue, model: model)
                }
            }
            .padding(.horizontal, 16).padding(.vertical, 13)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    /// One line, always: how to see the rest, how to get out, how to get in.
    private var footer: some View {
        HStack(spacing: 0) {
            Button { model.showShortcuts = true } label: {
                Text("⌘/ shortcuts").font(rounded(10, .medium)).foregroundStyle(.tertiary)
            }
            .buttonStyle(.plain)
            .help("Show every keyboard shortcut (⌘/)")
            Text(" · Esc clear/close · \(model.hotkeyLabel) anywhere")
                .font(rounded(10, .regular)).foregroundStyle(.tertiary)
                .help("\(model.hotkeyLabel) opens the panel from any app — change it in Settings (⌘,)")
            Spacer()
            Button { NotificationCenter.default.post(name: .dicoOpenSettings, object: nil) } label: {
                Text("⚙︎").font(rounded(11, .medium)).foregroundStyle(.tertiary)
            }
            .buttonStyle(.plain)
            .help("Settings (⌘,)")
            Text(" dico").font(rounded(10, .medium)).foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 14).padding(.vertical, 7)
    }

    @ViewBuilder private var toast: some View {
        if let t = model.toast {
            Text(t)
                .font(rounded(12, .medium))
                .padding(.horizontal, 14).padding(.vertical, 8)
                .background(.ultraThickMaterial, in: Capsule())
                .overlay(Capsule().strokeBorder(Palette.vert.opacity(0.5), lineWidth: 1))
                .shadow(radius: 8, y: 3)
                .padding(.bottom, 34)
                .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}

// MARK: - Empty state + recent queries

struct EmptyStateView: View {
    @ObservedObject var model: DicoModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(spacing: 8) {
                Text("📖").font(.system(size: 34))
                Text("Type a word, a French sentence, or a question.")
                    .font(rounded(13, .medium)).foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(.top, model.recent.isEmpty ? 34 : 18)

            if !model.recent.isEmpty {
                VStack(alignment: .leading, spacing: 7) {
                    HStack {
                        Text("RECENT").font(rounded(9.5, .bold))
                            .foregroundStyle(.tertiary).tracking(0.6)
                        Spacer()
                        Button { model.forgetRecent() } label: {
                            Text("Clear").font(rounded(10, .medium)).foregroundStyle(.tertiary)
                        }
                        .buttonStyle(.plain)
                        .help("Forget the recent queries")
                    }
                    FlowLayout(spacing: 6) {
                        ForEach(model.recent, id: \.self) { q in
                            RecentChip(text: q) { model.run(q, mode: model.mode) }
                        }
                    }
                }
                .padding(.top, 6)
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
                .font(rounded(12, .medium))
                .lineLimit(1)
                .padding(.horizontal, 9).padding(.vertical, 4.5)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(Color.primary.opacity(hover ? 0.13 : 0.07))
                )
                .foregroundStyle(.secondary)
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
            recipe(emoji: "📦", title: "dico is not installed",
                   body: "The panel drives the `dico` command line tool. Install it, then build the offline data:",
                   commands: ["uv tool install git+https://github.com/mechanicpanic/dico", "dico --setup"])
        case .setupNeeded:
            recipe(emoji: "🧱", title: "Offline data not built",
                   body: "The conjugations, Lexique and Grammalecte databases have not been downloaded yet.",
                   commands: ["dico --setup"])
        case .plain(let msg):
            HStack(alignment: .top, spacing: 9) {
                Text("😕").font(.system(size: 20))
                Text(msg).font(rounded(12, .regular)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.rouge.opacity(0.10), in: RoundedRectangle(cornerRadius: 10))
        }
    }

    private func recipe(emoji: String, title: String, body: String, commands: [String]) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 8) {
                Text(emoji).font(.system(size: 18))
                Text(title).font(rounded(14, .bold))
            }
            Text(body).font(rounded(11.5, .regular)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(commands, id: \.self) { cmd in
                HStack(spacing: 8) {
                    Text(cmd).font(.system(size: 11, design: .monospaced))
                        .textSelection(.enabled)
                        .lineLimit(1).minimumScaleFactor(0.7)
                        .padding(.horizontal, 8).padding(.vertical, 5)
                        .background(Color.primary.opacity(0.07),
                                    in: RoundedRectangle(cornerRadius: 6))
                    Spacer(minLength: 0)
                    CopyButton(text: cmd, tint: Palette.bleu, model: model)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.jaune.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
    }
}

extension Notification.Name {
    static let dicoFocusField = Notification.Name("dicoFocusField")
    /// Posted by the ⚙︎ button; the delegate opens the window (and wires the
    /// hotkey callback, which only it can honour).
    static let dicoOpenSettings = Notification.Name("dicoOpenSettings")
}
