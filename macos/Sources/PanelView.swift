import SwiftUI
import AppKit

// MARK: - Petite palette « tricolore douce »

enum Palette {
    static let bleu = Color(red: 0.30, green: 0.44, blue: 0.86)     // masculin, accents
    static let rose = Color(red: 0.89, green: 0.42, blue: 0.60)     // féminin
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
    /// ★ selon la fréquence.
    static func stars(_ band: String?) -> String {
        switch band {
        case "très courant": return "★★★"
        case "courant": return "★★"
        case "moyen": return "★"
        default: return ""
        }
    }
}

func rounded(_ size: CGFloat, _ weight: Font.Weight = .semibold) -> Font {
    .system(size: size, weight: weight, design: .rounded)
}

/// Le matériau translucide du panneau (clair ET sombre).
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

// MARK: - Le panneau

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
        .frame(width: 520, height: 420)
        .background(VisualEffect())
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
        )
        // (ombre : native, via NSPanel.hasShadow — une ombre SwiftUI serait rognée aux bords de la fenêtre)
        .overlay(alignment: .bottom) { toast }
        // Apparition élastique
        .scaleEffect(model.shown ? 1 : 0.90)
        .opacity(model.shown ? 1 : 0)
        .animation(.spring(response: 0.32, dampingFraction: 0.68), value: model.shown)
        .padding(12)
        .onReceive(NotificationCenter.default.publisher(for: .dicoFocusField)) { _ in
            focused = true
        }
    }

    // MARK: En-tête : champ + puces de mode

    private var header: some View {
        VStack(spacing: 10) {
            HStack(spacing: 8) {
                Text("🇫🇷").font(.system(size: 15))
                TextField(model.mode.placeholder, text: $model.query)
                    .textFieldStyle(.plain)
                    .font(rounded(16, .medium))
                    .focused($focused)
                    .onSubmit { model.submit() }
                    .onChange(of: model.query) { _, _ in model.normalizeInput() }
                if model.busy {
                    ProgressView().controlSize(.small).scaleEffect(0.7)
                } else if !model.query.isEmpty {
                    Button { model.clear(); focused = true } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(.tertiary)
                    }
                    .buttonStyle(.plain)
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
                }
                Spacer(minLength: 0)
            }
            .animation(.easeOut(duration: 0.15), value: model.mode)
        }
        .padding(.horizontal, 14).padding(.top, 13).padding(.bottom, 11)
    }

    // MARK: Zone de résultats

    private var results: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                switch model.outcome {
                case .vide:
                    EmptyStateView()
                case .chargement:
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text(model.mode == .demander ? "réfléchit…" : "cherche…")
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
                    AnswerView(answer: a)
                case .erreur(let msg):
                    ErrorView(message: msg)
                }
            }
            .padding(.horizontal, 16).padding(.vertical, 13)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var footer: some View {
        HStack {
            Text("⌘1-9 sauver · Esc fermer · ⌥D partout")
                .font(rounded(10, .regular)).foregroundStyle(.tertiary)
            Spacer()
            Text("dico").font(rounded(10, .medium)).foregroundStyle(.tertiary)
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

struct EmptyStateView: View {
    var body: some View {
        VStack(spacing: 10) {
            Text("📖").font(.system(size: 38))
            Text("Tape un mot, puis Entrée")
                .font(rounded(13, .medium)).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 3) {
                hint("-c", "conjuguer un verbe")
                hint("-g", "corriger une phrase")
                hint("-x", "disséquer une phrase")
                hint("?", "demander au tuteur")
            }
            .padding(.top, 4)
        }
        .frame(maxWidth: .infinity).padding(.top, 34)
    }
    private func hint(_ k: String, _ v: String) -> some View {
        HStack(spacing: 7) {
            Text(k).font(.system(size: 10, design: .monospaced))
                .padding(.horizontal, 5).padding(.vertical, 1)
                .background(Color.primary.opacity(0.08), in: RoundedRectangle(cornerRadius: 4))
                .frame(width: 30, alignment: .trailing)
            Text(v).font(rounded(11, .regular)).foregroundStyle(.tertiary)
        }
    }
}

struct ErrorView: View {
    let message: String
    var body: some View {
        HStack(alignment: .top, spacing: 9) {
            Text("😕").font(.system(size: 20))
            Text(message).font(rounded(12, .regular)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.rouge.opacity(0.10), in: RoundedRectangle(cornerRadius: 10))
    }
}

extension Notification.Name {
    static let dicoFocusField = Notification.Name("dicoFocusField")
}
