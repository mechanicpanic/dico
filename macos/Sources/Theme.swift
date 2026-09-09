import SwiftUI
import AppKit

// MARK: - Atelier — the visual language of the panel and the Settings window
//
// Three faces: serif for the French the user is learning (New York), sans for
// the interface (SF Pro), mono for what a machine wrote (SF Mono). One accent
// per screen. Hairlines, not boxes. Every tinted surface is the accent at a
// fixed alpha, never a new hex.

enum Palette {
    // Accents — `x` is the fill base (used at an alpha), `xInk` the text colour.
    static let bleu     = dyn(0x6E8AE8, 0x3E5FCB)
    static let bleuInk  = dyn(0x8EA3EE, 0x3E5FCB)
    static let rose     = dyn(0xE88FB0, 0xC9558A)
    static let roseInk  = dyn(0xE88FB0, 0xC9558A)
    static let vert     = dyn(0x56B786, 0x2E8A5E)
    static let vertInk  = dyn(0x8AD9AE, 0x2E8A5E)
    static let jaune    = dyn(0xE8C46A, 0xC9962E)
    static let jauneInk = dyn(0xE8C46A, 0xC9962E)
    static let rouge    = dyn(0xE2686C, 0xCB4C50)
    static let rougeInk = dyn(0xE2686C, 0xCB4C50)

    // Surfaces
    static let panel    = dyn(0x1B1C21, 0xFAF9F6)
    static let sheet    = dyn(0x232429, 0xFFFFFF)
    static let rail     = dyn(0x000000, 0.22, 0x000000, 0.035)
    static let surface  = dyn(0xFFFFFF, 0.045, 0x000000, 0.035)
    static let hairline = dyn(0xFFFFFF, 0.07, 0x000000, 0.08)   // inner
    static let rule     = dyn(0xFFFFFF, 0.09, 0x000000, 0.10)   // structural
    static let well     = dyn(0x000000, 0.25, 0x000000, 0.05)   // code / log
    static let scrim    = Color.black.opacity(0.45)

    // Ink
    static let ink = dyn(0xF2F1EE, 0x1B1C20)
    static func ink(_ alpha: Double) -> Color { ink.opacity(alpha) }
    /// On the ink-inverted toast, the check mark.
    static let toastCheck = dyn(0x2E8A5E, 0x7FD3A6)

    static func genderTint(_ g: String?) -> Color {
        switch g {
        case "m": return bleuInk
        case "f": return roseInk
        default: return ink(0.45)
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
    /// CEFR: A green, B blue, C red — coloured text, never a capsule.
    static func cefrTint(_ level: String) -> Color {
        switch level.prefix(1) {
        case "A": return vertInk
        case "B": return bleuInk
        default:  return rougeInk
        }
    }

    // MARK: Dynamic colours (dark / light)

    static func dyn(_ dark: UInt32, _ light: UInt32) -> Color {
        dyn(dark, 1, light, 1)
    }
    static func dyn(_ dark: UInt32, _ darkAlpha: CGFloat, _ light: UInt32, _ lightAlpha: CGFloat) -> Color {
        let d = nsColor(dark, darkAlpha), l = nsColor(light, lightAlpha)
        return Color(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? d : l
        })
    }
    static func nsColor(_ hex: UInt32, _ alpha: CGFloat = 1) -> NSColor {
        NSColor(red: CGFloat((hex >> 16) & 0xFF) / 255,
                green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
    }
}

extension Mode {
    /// The one accent of the screen: bleu by default, vert for Grammar, rose for Ask.
    var accent: Color {
        switch self {
        case .grammaire: return Palette.vert
        case .demander: return Palette.rose
        case .cartes: return Palette.jaune
        default: return Palette.bleu
        }
    }
    var accentInk: Color {
        switch self {
        case .grammaire: return Palette.vertInk
        case .demander: return Palette.roseInk
        case .cartes: return Palette.jauneInk
        default: return Palette.bleuInk
        }
    }
    /// The rail label — short enough for 44 pt.
    var short: String {
        switch self {
        case .mot: return "Word"
        case .conjuguer: return "Conj."
        case .grammaire: return "Gram."
        case .rayonsX: return "X-ray"
        case .demander: return "Ask"
        case .cartes: return "Cards"
        }
    }
}

extension Section {
    /// The pane in focus tints its own colour: rose for Russian.
    var accent: Color { self == .russe ? Palette.rose : Palette.bleu }
    var accentInk: Color { self == .russe ? Palette.roseInk : Palette.bleuInk }
    var tab: String {
        switch self {
        case .definitions: return "Definitions"
        case .russe: return "Russian"
        case .exemples: return "Examples"
        case .conjugaison: return "Conj."
        }
    }
}

// MARK: - Appearance

enum Appearance {
    static let configKey = "popup_appearance"
    static let choices: [(String, String)] = [("system", "System"), ("dark", "Dark"), ("light", "Light")]

    /// Applies the configured appearance to every window of the app.
    @MainActor static func apply(_ raw: [String: Any]) {
        apply(raw[configKey] as? String ?? "system")
    }
    @MainActor static func apply(_ choice: String) {
        switch choice {
        case "dark": NSApp.appearance = NSAppearance(named: .darkAqua)
        case "light": NSApp.appearance = NSAppearance(named: .aqua)
        default: NSApp.appearance = nil
        }
    }
}

// MARK: - Geometry

/// The content size of the panel. 600 pt fits the seven-tense grid.
enum PanelSize {
    static let width: CGFloat = 600
    static let height: CGFloat = 460
    static let margin: CGFloat = 12          // room for the native shadow
    static let rail: CGFloat = 56
    /// Everything right of the rail (and its hairline).
    static let content: CGFloat = width - rail - 1          // 543
    static let leftPane: CGFloat = 224
    static let rightPane: CGFloat = content - leftPane - 1  // 318
    /// The right pane's body, once its 14 pt sides are paid.
    static let paneBody: CGFloat = rightPane - 28           // 290
}

// MARK: - Type

/// Serif — the French: headwords, senses, examples, recents, sheet titles.
func serif(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
    .system(size: size, weight: weight, design: .serif)
}
/// Sans — the chrome: labels, body copy, buttons, settings, tutor answers.
func sans(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
    .system(size: size, weight: weight, design: .default)
}
/// Mono — the machine: IPA, shortcut keys, eyebrows, domains, paths, CLI output.
func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
    .system(size: size, weight: weight, design: .monospaced)
}

// MARK: - Small shared pieces

/// A 1 pt inner rule.
struct Hairline: View {
    var structural = false
    var body: some View {
        Rectangle().fill(structural ? Palette.rule : Palette.hairline).frame(height: 1)
    }
}

/// « VERBE ——————— » — a mono eyebrow riding on a hairline, with room for a
/// small control on the right.
struct Eyebrow: View {
    let text: String
    var tint: Color? = nil
    var trailing: AnyView? = nil
    var rule = true

    init(_ text: String, tint: Color? = nil, rule: Bool = true, trailing: AnyView? = nil) {
        self.text = text; self.tint = tint; self.rule = rule; self.trailing = trailing
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(text.uppercased()).font(mono(9)).tracking(0.9)
                .foregroundStyle(tint ?? Palette.ink(0.30))
                .lineLimit(1)
            if rule { Hairline() }
            if let trailing { trailing }
        }
    }
}

/// « ⌘D » — a key, in mono, at ink 25–30 %, next to the thing it does.
struct KeyHint: View {
    let keys: String
    var alpha: Double = 0.30
    init(_ keys: String, alpha: Double = 0.30) { self.keys = keys; self.alpha = alpha }
    var body: some View {
        Text(keys).font(mono(9)).foregroundStyle(Palette.ink(alpha)).lineLimit(1)
    }
}

/// A small tinted button: accent fill at 0.16, accent ink text.
struct TintButton: View {
    let label: String
    var keys: String? = nil
    var tint: Color = Palette.bleu
    var ink: Color = Palette.bleuInk
    var help: String = ""
    var busy = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if busy { ProgressView().controlSize(.small).scaleEffect(0.5).frame(width: 10, height: 10) }
                Text(label).font(sans(12, .semibold))
                if let keys { Text(keys).font(mono(9)).opacity(0.7) }
            }
            .padding(.horizontal, 13).padding(.vertical, 6)
            .background(tint.opacity(0.16), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .foregroundStyle(ink)
        }
        .buttonStyle(.plain)
        .help(help.isEmpty ? label : help)
    }
}

/// A quiet text button — « Clear », « Choose… », « Detect again ».
struct LinkButton: View {
    let label: String
    var tint: Color = Palette.bleuInk
    var size: CGFloat = 11
    var help: String = ""
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(label).font(sans(size)).foregroundStyle(tint)
        }
        .buttonStyle(.plain)
        .help(help.isEmpty ? label : help)
    }
}

/// « local · bring your own key · Anthropic · none » — one chip selected.
struct ChipRow<T: Hashable>: View {
    let items: [(T, String)]
    @Binding var selection: T
    var monoKeys = false
    var body: some View {
        HStack(spacing: monoKeys ? 7 : 6) {
            ForEach(items, id: \.0) { value, label in
                let on = selection == value
                Button { selection = value } label: {
                    Text(label)
                        .font(monoKeys ? mono(12.5) : sans(12, on ? .semibold : .regular))
                        .padding(.horizontal, 13).padding(.vertical, monoKeys ? 7 : 6)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(on ? Palette.bleu.opacity(0.18) : Palette.ink(0.05)))
                        .overlay(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .strokeBorder(Palette.bleu.opacity(on ? 0.35 : 0), lineWidth: 1))
                        .foregroundStyle(on ? Palette.bleuInk : Palette.ink(0.65))
                }
                .buttonStyle(.plain)
                .focusable(false)
            }
        }
    }
}
