import SwiftUI
import AppKit

// MARK: - 📖 Word — two panes: the card on the left, one section on the right

struct WordView: View {
    let lookup: Lookup
    @ObservedObject var model: DicoModel

    private var isFrench: Bool { lookup.direction == "fr" }

    /// The flag of the QUERY — `src_lang` when the CLI says so, otherwise
    /// Cyrillic → 🇷🇺, else 🇬🇧. Never 🇫🇷 unless the query itself is French.
    static func flag(forQuery q: String, srcLang: String?) -> String {
        switch (srcLang ?? "").lowercased().prefix(2) {
        case "ru": return "🇷🇺"
        case "en": return "🇬🇧"
        case "fr": return "🇫🇷"
        default: break
        }
        let cyrillic = q.unicodeScalars.contains { (0x0400...0x04FF).contains($0.value) }
        return cyrillic ? "🇷🇺" : "🇬🇧"
    }

    private var queryFlag: String {
        WordView.flag(forQuery: lookup.query ?? "", srcLang: lookup.src_lang)
    }

    /// Senses grouped by part of speech, in order of appearance, keeping the
    /// global number (the one used by the ⌘1…⌘9 shortcuts).
    private var groups: [(String, [(Int, Sense)])] {
        let senses = lookup.senses ?? []
        var order: [String] = []
        var dict: [String: [(Int, Sense)]] = [:]
        for (i, s) in senses.enumerated() {
            let key = s.pos ?? "—"
            if dict[key] == nil { order.append(key); dict[key] = [] }
            dict[key]?.append((i + 1, s))
        }
        return order.map { ($0, dict[$0] ?? []) }
    }

    /// The panes offered on the right.
    private var offered: [Section] {
        var s: [Section] = [.definitions, .russe, .exemples]
        if model.cardIsVerb { s.append(.conjugaison) }
        return s
    }

    private var selected: Section? { offered.first { model.open.contains($0) } }

    var body: some View {
        HStack(spacing: 0) {
            leftPane.frame(width: PanelSize.leftPane)
            Rectangle().fill(Palette.hairline).frame(width: 1)
            rightPane.frame(width: PanelSize.rightPane)
        }
        .frame(maxHeight: .infinity)
    }

    // MARK: Left: headword, senses, example

    private var headword: String {
        if isFrench { return lookup.head ?? lookup.query ?? "" }
        return lookup.translation ?? lookup.senses?.first?.term ?? ""
    }
    private var headGender: String? {
        let g = isFrench ? lookup.lexique?.genre : lookup.senses?.first?.gender
        return (g ?? "").isEmpty ? nil : g
    }

    private var leftPane: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .firstTextBaseline, spacing: 7) {
                        Text(headword).font(serif(28, .medium)).foregroundStyle(Palette.ink)
                            .lineLimit(2).minimumScaleFactor(0.6)
                        if let g = headGender {
                            Text(g).font(sans(10, .semibold)).foregroundStyle(Palette.genderTint(g))
                        }
                    }
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        if let ipa = lookup.lexique?.ipa, !ipa.isEmpty {
                            Text("/\(ipa)/").font(mono(10.5)).foregroundStyle(Palette.ink(0.35))
                        }
                        if let c = lookup.lexique?.cefr, !c.isEmpty { CEFRPill(level: c) }
                        let stars = Palette.stars(lookup.lexique?.band)
                        if !stars.isEmpty {
                            Text(stars).font(.system(size: 9.5)).foregroundStyle(Palette.jauneInk)
                                .help(lookup.lexique?.band ?? "")
                        }
                    }
                    if !isFrench, let q = lookup.query, !q.isEmpty {
                        Text("\(queryFlag) \(q)").font(sans(11)).foregroundStyle(Palette.ink(0.35))
                            .lineLimit(1)
                    }
                }

                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(groups.enumerated()), id: \.offset) { gi, group in
                        Text(group.0.uppercased()).font(mono(9)).tracking(0.9)
                            .foregroundStyle(Palette.ink(0.30))
                            .padding(.top, gi == 0 ? 0 : 8).padding(.bottom, 3)
                        ForEach(group.1, id: \.0) { n, s in
                            SenseRow(number: n, sense: s, accent: model.mode.accentInk,
                                     fill: model.mode.accent) {
                                model.save(sense: s, lookup: lookup)
                            }
                        }
                    }
                }

                if let ex = lookup.examples?.first, ex.count >= 2 {
                    ExampleLine(fr: ex[0], en: ex[1])
                }
            }
            .padding(.top, 14).padding(.horizontal, 14).padding(.bottom, 12)
        }
    }

    // MARK: Right: pane tabs, the pane, the action row

    private var rightPane: some View {
        VStack(spacing: 0) {
            HStack(spacing: 2) {
                ForEach(offered) { s in
                    PaneTab(section: s, active: selected == s, busy: isLoading(s)) {
                        model.toggle(s)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.top, 10).padding(.horizontal, 14)

            ScrollView {
                paneBody
                    .padding(.top, 12).padding(.horizontal, 14).padding(.bottom, 12)
                    .frame(width: PanelSize.rightPane, alignment: .leading)
            }
            .frame(maxHeight: .infinity)

            Hairline()
            HStack(spacing: 8) {
                Button { model.speak(model.cardTerm) } label: {
                    if model.speaking {
                        ProgressView().controlSize(.small).scaleEffect(0.55).frame(width: 14, height: 14)
                    } else {
                        Text("🔈").font(.system(size: 12))
                    }
                }
                .buttonStyle(.plain)
                .help("Hear \u{ab} \(model.cardTerm) \u{bb} said by a native speaker (⌘P)")
                Button { model.askAbout(model.cardTerm) } label: {
                    Text("💬").font(.system(size: 12))
                }
                .buttonStyle(.plain)
                .help("Ask the tutor about \u{ab} \(model.cardTerm) \u{bb} (⌘L)")
                Spacer(minLength: 0)
                KeyHint(offered.map(\.shortcut).joined(separator: " "), alpha: 0.25)
            }
            .padding(.top, 10).padding(.horizontal, 14).padding(.bottom, 12)
        }
    }

    private func isLoading(_ s: Section) -> Bool {
        if case .chargement = model.sections[s] { return true }
        return false
    }

    @ViewBuilder private var paneBody: some View {
        if let s = selected {
            switch model.sections[s] {
            case .none, .some(.chargement):
                HStack(spacing: 7) {
                    ProgressView().controlSize(.small).scaleEffect(0.7)
                    Text("loading…").font(sans(11)).foregroundStyle(Palette.ink(0.45))
                }
            case .some(.erreur(let issue)):
                VStack(alignment: .leading, spacing: 8) {
                    IssueView(issue: issue, model: model)
                    LinkButton(label: "Try again", tint: s.accentInk) { model.reload(s) }
                }
            case .some(.pret(let payload)):
                switch payload {
                case .definition(let d):   DefinitionBody(def: d)
                case .multitran(let m):    MultitranBody(entry: m)
                case .examples(let pack):
                    ExamplesBody(pack: pack, own: model.cardExamples) { fr, tr in model.saveExample(fr: fr, translation: tr) }
                case .conjugation(let c):  ConjugationView(conj: c, compact: true)
                }
            }
        } else {
            Text("Pick a pane above — or press \(offered.map(\.shortcut).joined(separator: " · ")).")
                .font(sans(11)).foregroundStyle(Palette.ink(0.35))
        }
    }
}

/// One sense: a row that saves the term when clicked. The first one is the
/// highlighted default and shows ⌘1.
struct SenseRow: View {
    let number: Int
    let sense: Sense
    let accent: Color
    let fill: Color
    let action: () -> Void
    @State private var hover = false

    private var first: Bool { number == 1 }

    var body: some View {
        Button(action: action) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("\(number)").font(mono(10))
                    .foregroundStyle(first ? accent : Palette.ink(0.30))
                Text(sense.display).font(serif(15.5))
                    .foregroundStyle(Palette.ink(first ? 1 : 0.85))
                    .lineLimit(2).minimumScaleFactor(0.8)
                if let g = sense.gender, !g.isEmpty {
                    Text(g).font(sans(9.5, .semibold)).foregroundStyle(Palette.genderTint(g))
                }
                if let c = sense.cefr, !c.isEmpty {
                    Text(c).font(sans(9, .semibold)).foregroundStyle(Palette.cefrTint(c).opacity(0.8))
                }
                Spacer(minLength: 0)
                if first || hover { KeyHint("⌘\(number)") }
            }
            .padding(.horizontal, 7).padding(.vertical, 5)
            .background(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(first ? fill.opacity(0.12) : (hover ? Palette.ink(0.05) : .clear)))
            .padding(.horizontal, -7)
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help("Click to save \u{ab} \(sense.display) \u{bb} (⌘\(number))")
    }
}

/// A pane tab: 4/8 pad, radius 6, accent fill at 0.16 when active.
struct PaneTab: View {
    let section: Section
    let active: Bool
    var busy = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                Text(section.tab).font(sans(10.5, active ? .semibold : .regular))
                if busy { ProgressView().controlSize(.small).scaleEffect(0.45).frame(width: 9, height: 9) }
            }
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(active ? section.accent.opacity(0.16) : .clear))
            .foregroundStyle(active ? section.accentInk : Palette.ink(0.5))
        }
        .buttonStyle(.plain)
        .help("\(section.label) (\(section.shortcut)) — \(section.blurb)")
    }
}

/// « Il faut cuire les légumes. » with its translation dimmed underneath,
/// behind a 2 pt rule in the accent.
struct ExampleLine: View {
    let fr: String
    let en: String
    var flag: String? = nil
    var tint: Color = Palette.bleu
    /// When set, « save » appears on hover and makes the sentence a card.
    var onSave: (() -> Void)? = nil
    @State private var hover = false

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(fr).font(serif(13)).italic().foregroundStyle(Palette.ink(0.9))
                    .fixedSize(horizontal: false, vertical: true)
                if let onSave, hover {
                    LinkButton(label: "save", tint: Palette.ink(0.4), size: 10, help: "Make this sentence a card", action: onSave)
                }
            }
            if !en.isEmpty {
                Text((flag.map { $0 + " " } ?? "") + en).font(sans(10.5)).foregroundStyle(Palette.ink(0.4))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.leading, 9)
        .overlay(alignment: .leading) { Rectangle().fill(tint.opacity(0.3)).frame(width: 2) }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .onHover { hover = $0 }
    }
}

// MARK: - The panes

struct DefinitionBody: View {
    let def: Definition
    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(def.word ?? "").font(serif(17)).foregroundStyle(Palette.ink)
                if let p = def.ipa, !p.isEmpty {
                    Text("[\(p)]").font(mono(10)).foregroundStyle(Palette.ink(0.35))
                }
                if let p = def.pos, !p.isEmpty {
                    Text(p).font(sans(10.5)).foregroundStyle(Palette.ink(0.45))
                }
                if let g = def.gender, !g.isEmpty {
                    Text(g).font(sans(9.5, .semibold)).foregroundStyle(Palette.genderTint(g))
                }
                if let c = def.cefr, !c.isEmpty { CEFRPill(level: c) }
                Spacer(minLength: 0)
            }
            ForEach(Array((def.defs ?? []).enumerated()), id: \.offset) { i, d in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("\(i + 1)").font(mono(9.5)).foregroundStyle(Palette.ink(0.30))
                    Text(d).font(sans(12.5)).lineSpacing(3).foregroundStyle(Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            if let e = def.etym, !e.isEmpty {
                Text(e).font(serif(12)).italic().foregroundStyle(Palette.ink(0.4))
                    .fixedSize(horizontal: false, vertical: true)
            }
            WordNoteRow(icon: "≈", title: "syn.", words: def.syn ?? [])
            WordNoteRow(icon: "♪", title: "homo.", words: def.homo ?? [])
            if let ru = def.ru, !ru.isEmpty {
                NoteRow(label: "🇷🇺 ru", content: WiktionaryRuBody.line(ru))
            }
        }
    }
}

/// The CEFR level — coloured text, no capsule.
struct CEFRPill: View {
    let level: String
    var body: some View {
        Text(level).font(sans(9.5, .semibold)).tracking(0.6)
            .foregroundStyle(Palette.cefrTint(level))
            .help("Textbook level \(level) — the first CEFR level whose course books use this word (FLELex). A measure of curricula, not of difficulty: « chaton » is B1")
    }
}

/// « ≈ SYN.   mijoter · rôtir · bouillir (familier) » — a mono label and a
/// flowing list, the register notes dimmed after the word they belong to.
struct WordNoteRow: View {
    let icon: String
    let title: String
    let words: [WordNote]

    var body: some View {
        if !words.isEmpty {
            NoteRow(label: "\(icon) \(title)", content: WordNoteRow.line(words))
        }
    }

    static func line(_ words: [WordNote]) -> Text {
        var out = Text("")
        for (i, w) in words.enumerated() {
            if i > 0 { out = out + Text(" · ").foregroundStyle(Palette.ink(0.3)) }
            out = out + Text(w.word ?? "").foregroundStyle(Palette.ink(0.85))
            if let n = w.note, !n.isEmpty {
                out = out + Text(" \(n)").font(sans(10.5)).foregroundStyle(Palette.ink(0.45))
            }
        }
        return out
    }
}

/// A 44 pt mono label on the left, a wrapping line on the right.
struct NoteRow: View {
    let label: String
    let content: Text
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label.uppercased()).font(mono(9)).foregroundStyle(Palette.ink(0.30))
                .frame(width: 44, alignment: .leading).lineLimit(1)
            content.font(sans(12))
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.top, 2)
    }
}

/// Russian straight from the Wiktionnaire — what you get when Multitran, which
/// is proprietary and bring-your-own, is not installed.
struct WiktionaryRuBody: View {
    let terms: [RuTerm]

    static func line(_ terms: [RuTerm]) -> Text {
        var out = Text("")
        for (i, t) in terms.enumerated() {
            if i > 0 { out = out + Text(" · ").foregroundStyle(Palette.ink(0.3)) }
            out = out + Text(t.word ?? "").foregroundStyle(Palette.ink(0.85))
            if let tr = t.tr, !tr.isEmpty {
                out = out + Text(" \(tr)").font(mono(9.5)).foregroundStyle(Palette.ink(0.4))
            }
            if let g = t.gender, !g.isEmpty {
                out = out + Text(" \(g)").font(sans(9.5, .semibold)).foregroundStyle(Palette.genderTint(g))
            }
        }
        return out
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Eyebrow("Wiktionnaire", tint: Palette.roseInk)
            ForEach(terms, id: \.self) { t in
                HStack(alignment: .firstTextBaseline, spacing: 7) {
                    Text(t.word ?? "").font(serif(15.5)).foregroundStyle(Palette.ink)
                    if let tr = t.tr, !tr.isEmpty {
                        Text("[\(tr)]").font(mono(10)).foregroundStyle(Palette.ink(0.35))
                    }
                    if let g = t.gender, !g.isEmpty {
                        Text(g).font(sans(9.5, .semibold)).foregroundStyle(Palette.genderTint(g))
                    }
                    Spacer(minLength: 0)
                }
            }
        }
    }
}

/// The Multitran entry, in full: one section per part of speech, one row per
/// sense (number + domain tag on the left, the translations flowing on the
/// right). Notes are shown right after their translation and NEVER truncated —
/// they can be whole example sentences. No line caps, no fixed height: the
/// pane scrolls.
struct MultitranBody: View {
    let entry: Multitran
    private var arrow: String { entry.direction == "rufr" ? "ru → fr" : "fr → ru" }

    // MARK: The flowing translation list of one sense

    /// " · "-separated translations, each followed by its note in small italic
    /// grey. A single wrapping Text, so nothing can ever be cut off.
    static func translations(_ items: [MultitranItem]) -> Text {
        var out = Text("")
        var first = true
        for it in items {
            let tr = (it.tr ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if tr.isEmpty { continue }
            if !first {
                out = out + Text(" · ").font(sans(11.5)).foregroundStyle(Palette.ink(0.25))
            }
            first = false
            out = out + Text(tr).font(sans(12)).foregroundStyle(Palette.ink(0.88))
            let note = (it.note ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if !note.isEmpty {
                out = out + Text(" " + note).font(sans(10.5)).italic().foregroundStyle(Palette.ink(0.5))
            }
        }
        return out
    }

    /// The same thing as plain text — what `--selftest` checks for completeness.
    static func plain(_ items: [MultitranItem]) -> String {
        items.compactMap { it -> String? in
            let tr = (it.tr ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !tr.isEmpty else { return nil }
            let note = (it.note ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return note.isEmpty ? tr : "\(tr) \(note)"
        }.joined(separator: " · ")
    }

    /// Everything this view renders, flattened — the self-test's hook.
    var plainText: String {
        var out: [String] = []
        for g in entry.usableGroups {
            let pos = (g.pos ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if !pos.isEmpty { out.append(pos) }
            for sense in g.senses ?? [] {
                let head = [(sense.n ?? ""), (sense.domain ?? "")]
                    .filter { !$0.isEmpty }.joined(separator: " ")
                out.append((head.isEmpty ? "" : head + " ") + MultitranBody.plain(sense.items ?? []))
            }
        }
        if out.isEmpty { out = entry.lines ?? [] }
        return out.joined(separator: "\n")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(arrow).font(mono(9)).foregroundStyle(Palette.ink(0.30))
            if !entry.usableGroups.isEmpty {
                ForEach(Array(entry.usableGroups.enumerated()), id: \.offset) { _, g in
                    posGroup(g)
                }
            } else if !(entry.wiktionary_ru ?? []).isEmpty {
                WiktionaryRuBody(terms: entry.wiktionary_ru ?? [])
            } else {
                fallbackLines
            }
        }
    }

    private func posGroup(_ g: MultitranGroup) -> some View {
        let pos = (g.pos ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return VStack(alignment: .leading, spacing: 6) {
            if !pos.isEmpty { Eyebrow(pos, tint: Palette.roseInk) }
            ForEach(Array((g.senses ?? []).enumerated()), id: \.offset) { _, sense in
                senseRow(sense)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func senseRow(_ sense: MultitranSense) -> some View {
        let n = (sense.n ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let domain = (sense.domain ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return HStack(alignment: .firstTextBaseline, spacing: 8) {
            VStack(alignment: .trailing, spacing: 1) {
                if !n.isEmpty { Text(n).font(mono(9.5)).foregroundStyle(Palette.ink(0.30)) }
                if !domain.isEmpty {
                    Text(domain).font(mono(9)).foregroundStyle(Palette.ink(0.4))
                        .lineLimit(1).minimumScaleFactor(0.7)
                        .help("Multitran domain")
                }
            }
            .frame(width: 44, alignment: .trailing)
            MultitranBody.translations(sense.items ?? [])
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    /// Only when `groups` is empty: the flat `lines` the CLI also returns.
    private var fallbackLines: some View {
        VStack(alignment: .leading, spacing: 5) {
            ForEach(Array((entry.lines ?? []).enumerated()), id: \.offset) { _, line in
                let heading = !line.contains(")") && line.count <= 12
                if heading {
                    Eyebrow(line, tint: Palette.roseInk).padding(.top, 4)
                } else {
                    let (head, rest) = MultitranBody.splitLine(line)
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(head).font(mono(9)).foregroundStyle(Palette.ink(0.4))
                            .frame(width: 44, alignment: .trailing).lineLimit(1).minimumScaleFactor(0.7)
                        Text(rest).font(sans(12)).foregroundStyle(Palette.ink(0.88))
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }

    /// « 1) общ. кошка, кот » → ("1 общ.", "кошка, кот").
    static func splitLine(_ line: String) -> (String, String) {
        let parts = line.split(separator: " ", omittingEmptySubsequences: true).map(String.init)
        guard parts.count >= 2, parts[0].hasSuffix(")") else { return ("", line) }
        let n = String(parts[0].dropLast())
        if parts.count >= 3, parts[1].hasSuffix(".") {
            return ("\(n) \(parts[1])", parts.dropFirst(2).joined(separator: " "))
        }
        return (n, parts.dropFirst().joined(separator: " "))
    }
}

struct ExamplesBody: View {
    let pack: ExamplePack
    /// The example the card itself came with — kept first when Tatoeba
    /// does not already have it.
    var own: [[String]] = []
    /// Makes a sentence a card: (French, translation).
    var onSave: ((String, String) -> Void)? = nil

    /// A French sentence, folded for the duplicate check.
    private static func key(_ s: String) -> String {
        s.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "")
    }

    /// The card's own example(s) first, then everything Tatoeba returned.
    private var english: [ExampleSentence] {
        let fetched = pack.en ?? []
        var seen = Set(fetched.compactMap { $0.fr.map(ExamplesBody.key) })
        var out: [ExampleSentence] = []
        for ex in own where ex.count >= 2 {
            let k = ExamplesBody.key(ex[0])
            if seen.contains(k) { continue }
            seen.insert(k)
            out.append(ExampleSentence(fr: ex[0], en: ex[1], ru: nil))
        }
        return out + fetched
    }

    private var russian: [ExampleSentence] { pack.ru ?? [] }

    /// What `--selftest` prints: how the two lists came out after merging.
    var debugSummary: String {
        "merged \(english.count) en (+\(english.count - (pack.en ?? []).count) own) / \(russian.count) ru"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if english.isEmpty && russian.isEmpty {
                Text("No examples found").font(sans(11.5)).foregroundStyle(Palette.ink(0.45))
            }
            ForEach(Array(english.enumerated()), id: \.offset) { _, ex in
                ExampleLine(fr: ex.fr ?? "", en: ex.en ?? "",
                            onSave: onSave.map { f in { f(ex.fr ?? "", ex.en ?? "") } })
            }
            ForEach(Array(russian.enumerated()), id: \.offset) { _, ex in
                ExampleLine(fr: ex.fr ?? "", en: ex.ru ?? "", flag: "🇷🇺", tint: Palette.rose,
                            onSave: onSave.map { f in { f(ex.fr ?? "", ex.ru ?? "") } })
            }
        }
    }
}

/// A wrapping row layout — for recents and suggestions.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat? = nil
    private var rowGap: CGFloat { lineSpacing ?? spacing }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxW = proposal.width ?? 480
        var x: CGFloat = 0, y: CGFloat = 0, lineH: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > 0, x + s.width > maxW { x = 0; y += lineH + rowGap; lineH = 0 }
            x += s.width + spacing
            lineH = max(lineH, s.height)
        }
        return CGSize(width: maxW, height: y + lineH)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, lineH: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > bounds.minX, x + s.width > bounds.maxX { x = bounds.minX; y += lineH + rowGap; lineH = 0 }
            v.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
            x += s.width + spacing
            lineH = max(lineH, s.height)
        }
    }
}

// MARK: - 🔁 Conjugate — a ruled grid, endings in blue

/// The je/tu/il/nous/vous/ils × seven-tenses table: a 34 pt pronoun gutter,
/// seven equal columns, a hairline per row, the présent column ruled in bleu,
/// the ending of each form in bleu, compound forms with a dimmed auxiliary and
/// « — » where the impératif has no form.
///
/// Inside the Word card's pane there is no room for seven columns, so the
/// compact form stacks the tenses instead.
struct ConjugationView: View {
    let conj: Conjugation
    /// Inside a Word-card pane the grid becomes a stack.
    var compact: Bool = false

    static let pronouns = ["je", "tu", "il", "nous", "vous", "ils"]
    /// The impératif only has tu / nous / vous.
    static let imperativeRow: [Int?] = [nil, 0, nil, 1, 2, nil]

    // MARK: Geometry — the grid must fit the panel without scrolling sideways

    /// The content column is 543 pt wide; the grid keeps 16 pt on each side.
    static let fullBudget: CGFloat = PanelSize.content - 32     // 511
    /// The Word card's right pane, once its sides are paid.
    static let compactBudget: CGFloat = PanelSize.paneBody      // 290

    private var budget: CGFloat { compact ? ConjugationView.compactBudget : ConjugationView.fullBudget }
    private let gutter: CGFloat = 34
    private let gap: CGFloat = 5
    private var columnCount: CGFloat { CGFloat(max(1, conj.orderedTenses.count)) }

    /// What is left for one tense column once the gutter and the gaps are paid.
    var colWidth: CGFloat {
        if compact { return ((budget - 2 * gutter - 3 * gap) / 2).rounded(.down) }
        return ((budget - gutter - gap * columnCount) / columnCount).rounded(.down)
    }
    /// The grid's own width — `--selftest` asserts this fits the budget.
    var gridWidth: CGFloat {
        compact ? budget : gutter + (colWidth + gap) * columnCount
    }

    // MARK: Text

    /// "que je mange" → "mange"; "j'ai mangé" → "ai mangé"; "va" → "va".
    static func strip(_ form: String) -> String {
        var s = form
        for p in ["que ", "qu'"] where s.hasPrefix(p) { s = String(s.dropFirst(p.count)) }
        if s.hasPrefix("j'") { return String(s.dropFirst(2)) }
        let words = ["je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles"]
        for w in words where s.hasPrefix(w + " ") { return String(s.dropFirst(w.count + 1)) }
        return s
    }

    /// The auxiliaries a compound tense is built with — shown dimmed.
    static let auxiliaries: Set<String> = ["ai", "as", "a", "avons", "avez", "ont",
                                           "suis", "es", "est", "sommes", "êtes", "sont"]

    /// "ai dit" → ("ai", "dit"); "dis" → (nil, "dis").
    static func split(_ form: String) -> (String?, String) {
        let s = strip(form)
        let parts = s.split(separator: " ", maxSplits: 1, omittingEmptySubsequences: true)
        if parts.count == 2, ConjugationView.auxiliaries.contains(String(parts[0]).lowercased()) {
            return (String(parts[0]), String(parts[1]))
        }
        return (nil, s)
    }

    /// The form at (tense, row), or nil when there is none.
    static func form(_ name: String, _ forms: [String], row i: Int) -> String? {
        let idx: Int? = (name == "impératif") ? imperativeRow[i] : (i < forms.count ? i : nil)
        guard let idx, idx < forms.count else { return nil }
        return forms[idx]
    }

    /// What the six forms of a tense share — the rest is the ending, in bleu.
    /// Compound tenses have no stem: the participle is the same six times.
    static func stem(_ forms: [String]) -> String {
        let pairs = forms.map(split)
        if pairs.contains(where: { $0.0 != nil }) { return "" }
        let rests = pairs.map(\.1).filter { !$0.isEmpty }
        guard var p = rests.first else { return "" }
        for r in rests.dropFirst() {
            p = String(zip(p, r).prefix { $0 == $1 }.map { $0.0 })
        }
        if rests.contains(where: { $0.count <= p.count }) { p = String(p.dropLast()) }
        return p
    }

    /// The short mono heading of a tense.
    static let heads: [String: String] = [
        "présent": "PRÉSENT", "imparfait": "IMPARF.", "futur simple": "FUTUR", "futur": "FUTUR",
        "passé composé": "P.COMP.", "conditionnel": "CONDIT.", "conditionnel présent": "CONDIT.",
        "subjonctif": "SUBJ.", "subjonctif présent": "SUBJ.", "impératif": "IMPÉR.",
    ]
    static func head(_ name: String) -> String {
        heads[name] ?? Conjugation.shortLabels[name]?.uppercased() ?? String(name.prefix(7)).uppercased()
    }

    /// « 3ᵉ groupe » — from the infinitive and the présent.
    var group: String? {
        guard let inf = conj.infinitive, !inf.isEmpty else { return nil }
        if inf == "aller" { return "3ᵉ groupe" }
        if inf.hasSuffix("er") { return "1ᵉʳ groupe" }
        if inf.hasSuffix("ir"), let p = conj.tenses?["présent"], p.count > 3,
           ConjugationView.strip(p[3]).hasSuffix("issons") { return "2ᵉ groupe" }
        return "3ᵉ groupe"
    }
    /// « avoir » / « être » — from the passé composé.
    var auxiliary: String? {
        guard let pc = conj.tenses?["passé composé"]?.first,
              let aux = ConjugationView.split(pc).0 else { return nil }
        return ["ai", "as", "a", "avons", "avez", "ont"].contains(aux) ? "avoir" : "être"
    }

    // MARK: Body

    var body: some View {
        if compact { stacked } else { full }
    }

    private var full: some View {
        VStack(alignment: .leading, spacing: 11) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(conj.infinitive ?? "").font(serif(26, .medium)).foregroundStyle(Palette.ink)
                if group != nil || auxiliary != nil {
                    (Text(group ?? "") + Text(auxiliary != nil ? " · aux. " : "")
                        + Text(auxiliary ?? "").foregroundStyle(Palette.ink(0.7)))
                        .font(sans(11)).foregroundStyle(Palette.ink(0.4))
                }
                Spacer(minLength: 0)
                (Text("endings in ") + Text("blue").foregroundStyle(Palette.bleuInk))
                    .font(sans(10)).foregroundStyle(Palette.ink(0.28))
            }
            VStack(spacing: 0) {
                HStack(spacing: gap) {
                    Color.clear.frame(width: gutter, height: 1)
                    ForEach(conj.orderedTenses, id: \.0) { name, _ in
                        let present = name == "présent"
                        Text(ConjugationView.head(name)).font(mono(8.5)).tracking(0.4)
                            .foregroundStyle(present ? Palette.bleuInk : Palette.ink(0.35))
                            .lineLimit(1).minimumScaleFactor(0.7)
                            .frame(width: colWidth, alignment: .leading)
                            .help(Conjugation.hints[name] ?? name)
                    }
                }
                .padding(.bottom, 6)
                ForEach(0..<6, id: \.self) { i in
                    HStack(spacing: gap) {
                        Text(ConjugationView.pronouns[i]).font(mono(9.5)).foregroundStyle(Palette.ink(0.30))
                            .frame(width: gutter, alignment: .leading)
                            .padding(.vertical, 7)
                            .overlay(alignment: .top) { Hairline() }
                            .overlay(alignment: .bottom) { if i == 5 { Hairline() } }
                        ForEach(conj.orderedTenses, id: \.0) { name, forms in
                            let present = name == "présent"
                            cell(name: name, forms: forms, row: i, present: present)
                                .frame(width: colWidth, alignment: .leading)
                                .padding(.vertical, 7)
                                .overlay(alignment: .top) { rule(present) }
                                .overlay(alignment: .bottom) { if i == 5 { rule(present) } }
                        }
                    }
                }
            }
            .frame(width: gridWidth, alignment: .leading)
            (Text("Hover a heading for what the tense is for · ")
                + Text("⌘1").foregroundStyle(Palette.ink(0.5)) + Text(" saves the infinitive."))
                .font(sans(10.5)).foregroundStyle(Palette.ink(0.30))
        }
    }

    private func rule(_ present: Bool) -> some View {
        Rectangle().fill(present ? Palette.bleu.opacity(0.25) : Palette.hairline).frame(height: 1)
    }

    private func cell(name: String, forms: [String], row i: Int, present: Bool) -> some View {
        let raw = ConjugationView.form(name, forms, row: i)
        return ConjugationView.text(raw, stem: ConjugationView.stem(forms.compactMap { $0 }))
            .font(sans(11.5, present ? .medium : .regular))
            .lineLimit(1).minimumScaleFactor(0.6)
            .help(raw.map { "\(ConjugationView.pronouns[i]) — \(name): \($0)" }
                  ?? (Conjugation.hints[name] ?? name))
    }

    /// The form with its ending in bleu, its auxiliary dimmed, or « — ».
    static func text(_ raw: String?, stem: String) -> Text {
        guard let raw else { return Text("—").foregroundStyle(Palette.ink(0.18)) }
        let (aux, rest) = split(raw)
        if let aux {
            return Text(aux + " ").foregroundStyle(Palette.ink(0.35)) + Text(rest).foregroundStyle(Palette.ink)
        }
        if !stem.isEmpty, rest.hasPrefix(stem), rest.count > stem.count {
            return Text(stem).foregroundStyle(Palette.ink)
                + Text(String(rest.dropFirst(stem.count))).foregroundStyle(Palette.bleuInk)
        }
        return Text(rest).foregroundStyle(Palette.ink)
    }

    /// The pane version: one block per tense, six forms in two columns.
    private var stacked: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(conj.orderedTenses, id: \.0) { name, forms in
                let present = name == "présent"
                let stem = ConjugationView.stem(forms)
                VStack(alignment: .leading, spacing: 4) {
                    Eyebrow(name, tint: present ? Palette.bleuInk : nil)
                        .help(Conjugation.hints[name] ?? name)
                    HStack(alignment: .top, spacing: gap) {
                        ForEach([0, 3], id: \.self) { start in
                            VStack(alignment: .leading, spacing: 3) {
                                ForEach(start..<(start + 3), id: \.self) { i in
                                    HStack(spacing: gap) {
                                        Text(ConjugationView.pronouns[i]).font(mono(9.5))
                                            .foregroundStyle(Palette.ink(0.30))
                                            .frame(width: gutter, alignment: .leading)
                                        ConjugationView.text(ConjugationView.form(name, forms, row: i), stem: stem)
                                            .font(sans(11.5, present ? .medium : .regular))
                                            .lineLimit(1).minimumScaleFactor(0.6)
                                            .frame(width: colWidth, alignment: .leading)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        .frame(width: gridWidth, alignment: .leading)
    }
}

// MARK: - ✅ Grammar

struct GrammarView: View {
    let grammar: Grammar
    let sentence: String
    @ObservedObject var model: DicoModel

    /// Split the sentence on the offsets (code-point indices, Python-style).
    private var segments: [(String, Int)] {   // 0 = normal, 1 = grammar, 2 = spelling
        let scalars = Array(sentence.unicodeScalars)
        var kind = [Int](repeating: 0, count: scalars.count)
        for e in grammar.errors ?? [] {
            for i in max(0, e.start)..<min(scalars.count, e.end) { kind[i] = 1 }
        }
        for s in grammar.spelling ?? [] {
            for i in max(0, s.start)..<min(scalars.count, s.end) where kind[i] == 0 { kind[i] = 2 }
        }
        var out: [(String, Int)] = []
        var buf = String.UnicodeScalarView()
        var cur = kind.first ?? 0
        for (i, sc) in scalars.enumerated() {
            if kind[i] != cur { out.append((String(buf), cur)); buf = String.UnicodeScalarView(); cur = kind[i] }
            buf.append(sc)
        }
        if !buf.isEmpty { out.append((String(buf), cur)) }
        return out
    }

    /// « ACCORD », « ORTHO. » — the CLI's phrase for Grammalecte's rule, in
    /// six mono characters.
    static func label(_ type: String?) -> String {
        let t = (type ?? "").lowercased()
        let table: [(String, String)] = [
            ("participle", "ACCORD"), ("agreement", "ACCORD"), ("singular", "NOMBRE"),
            ("conjugation", "CONJ."), ("verb", "VERBE"), ("infinitive", "INFIN."), ("imperative", "IMPÉR."),
            ("question", "QUEST."), ("confusion", "CONFUS"), ("barbarism", "BARBAR"), ("elision", "ÉLIS."),
            ("typography", "TYPO."), ("spacing", "ESPACE"), ("non-breaking", "ESPACE"),
            ("capital", "MAJ."), ("apostrophe", "APOS."), ("phrasing", "STYLE"), ("redundancy", "STYLE"),
            ("pleonasm", "STYLE"), ("date", "DATE"), ("number", "NOMBRE"), ("punctuation", "PONCT."),
            ("comma", "VIRG."), ("compound", "MOT"), ("ocr", "OCR"), ("spelling", "ORTHO."),
        ]
        for (needle, label) in table where t.contains(needle) { return label }
        if t.isEmpty { return "RÈGLE" }
        let word = t.split(separator: " ").first.map(String.init) ?? t
        return word.count > 6 ? String(word.prefix(5)).uppercased() + "." : word.uppercased()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            // The sentence with the faulty spans highlighted.
            segments.reduce(Text("")) { acc, seg in
                acc + Text(seg.0)
                    .foregroundColor(seg.1 == 0 ? Palette.ink : (seg.1 == 1 ? Palette.rougeInk : Palette.jauneInk))
                    .underline(seg.1 != 0, color: (seg.1 == 1 ? Palette.rouge : Palette.jaune).opacity(0.6))
            }
            .font(serif(24)).lineSpacing(6)
            .fixedSize(horizontal: false, vertical: true)

            let errs = grammar.errors ?? []
            let sp = grammar.spelling ?? []
            if errs.isEmpty && sp.isEmpty {
                Text("✓ Nothing to correct").font(sans(12.5)).foregroundStyle(Palette.vertInk)
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(Array(errs.enumerated()), id: \.offset) { _, e in
                        note(label: GrammarView.label(e.type), message: e.message ?? e.type ?? "",
                             suggestions: e.suggestions ?? [], tint: Palette.rougeInk)
                    }
                    ForEach(Array(sp.enumerated()), id: \.offset) { _, s in
                        note(label: "ORTHO.", message: "\u{ab} \(s.text ?? "") \u{bb} is not in the dictionary.",
                             suggestions: s.suggestions ?? [], tint: Palette.jauneInk)
                    }
                }
            }
            if let c = grammar.corrected, !c.isEmpty {
                HStack(alignment: .top, spacing: 12) {
                    Text(c).font(serif(18)).lineSpacing(4).foregroundStyle(Palette.vertInk)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                    Button { model.saveCorrection(grammar) } label: {
                        HStack(spacing: 6) {
                            Text("Save").font(sans(11, .semibold))
                            Text("⌘S").font(mono(9)).opacity(0.7)
                        }
                        .padding(.horizontal, 9).padding(.vertical, 4)
                        .foregroundStyle(Palette.vertInk)
                    }
                    .buttonStyle(.plain)
                    .help("Make the corrected sentence a card (⌘S)")
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(c, forType: .string)
                        model.flash("✓ corrected sentence copied")
                    } label: {
                        HStack(spacing: 6) {
                            Text("Copy").font(sans(11, .semibold))
                            Text("⌘⇧C").font(mono(9)).opacity(0.7)
                        }
                        .padding(.horizontal, 9).padding(.vertical, 4)
                        .background(Palette.vert.opacity(0.18), in: RoundedRectangle(cornerRadius: 7, style: .continuous))
                        .foregroundStyle(Palette.vertInk)
                    }
                    .buttonStyle(.plain)
                    .help("Copy the corrected sentence (⌘⇧C)")
                }
                .padding(.horizontal, 14).padding(.vertical, 13)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Palette.vert.opacity(0.10), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(Palette.vert.opacity(0.22), lineWidth: 1))
            }
        }
    }

    private func note(label: String, message: String, suggestions: [String], tint: Color) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 11) {
            Text(label).font(mono(9.5)).foregroundStyle(tint)
                .frame(width: 52, alignment: .leading).lineLimit(1).minimumScaleFactor(0.8)
            VStack(alignment: .leading, spacing: 5) {
                Text(message).font(sans(12.5)).lineSpacing(3).foregroundStyle(Palette.ink)
                    .fixedSize(horizontal: false, vertical: true)
                if !suggestions.isEmpty {
                    FlowLayout(spacing: 14, lineSpacing: 2) {
                        ForEach(Array(suggestions.prefix(6).enumerated()), id: \.offset) { i, s in
                            Text(s).font(serif(16))
                                .foregroundStyle(i == 0 ? Palette.vertInk : Palette.ink(0.5))
                        }
                    }
                }
            }
        }
    }
}

// MARK: - 🔬 X-ray — the sentence, interlinear

/// The sentence as a row of tiles: the word in serif, its part of speech and
/// gender in mono underneath, the gloss under that. Click a word for the
/// rest (lemma, tense, role) and to look it up or save it.
struct XrayView: View {
    let tokens: [XrayToken]
    var onSave: ((XrayToken) -> Void)? = nil
    var onLookup: ((String) -> Void)? = nil
    @State private var selected: Int? = nil

    static let width: CGFloat = PanelSize.content - 36

    /// « nom », « verbe · présent », « adj. », « prép. »…
    static func tag(_ t: XrayToken) -> String {
        let pos = (t.pos ?? "").lowercased()
        let short: String
        switch true {
        case pos.hasPrefix("nom"): short = "nom"
        case pos.hasPrefix("verbe"): short = "verbe"
        case pos.hasPrefix("adjectif"): short = "adj."
        case pos.hasPrefix("adverbe"): short = "adv."
        case pos.hasPrefix("préposition"): short = "prép."
        case pos.hasPrefix("article"): short = "art."
        case pos.hasPrefix("déterminant"): short = "dét."
        case pos.hasPrefix("pronom"): short = "pron."
        case pos.hasPrefix("conjonction"): short = "conj."
        case pos.isEmpty: short = "?"
        default: short = String(pos.prefix(6))
        }
        if short == "verbe", let tense = (t.tense ?? "").split(separator: ";").first, !tense.isEmpty {
            return "verbe · \(tense.split(separator: "·").first?.trimmingCharacters(in: .whitespaces) ?? String(tense))"
        }
        return short
    }

    private func tint(_ t: XrayToken) -> Color {
        if let g = t.gender, !g.isEmpty { return Palette.genderTint(g) }
        return (t.pos ?? "").lowercased().hasPrefix("verbe") ? Palette.ink : Palette.ink(0.9)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            FlowLayout(spacing: 4, lineSpacing: 6) {
                ForEach(Array(tokens.enumerated()), id: \.offset) { i, t in
                    tile(i, t)
                }
            }
            if let i = selected, i < tokens.count {
                detail(tokens[i])
            } else {
                (Text("Click a word. Gender colours it: ") + Text("masculin").foregroundStyle(Palette.bleuInk)
                    + Text(" · ") + Text("féminin").foregroundStyle(Palette.roseInk)
                    + Text(". Roles come from spaCy when it is switched on in Settings."))
                    .font(sans(10.5)).foregroundStyle(Palette.ink(0.28))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(width: XrayView.width, alignment: .leading)
    }

    private func tile(_ i: Int, _ t: XrayToken) -> some View {
        let on = selected == i
        return Button { withAnimation(.easeOut(duration: 0.12)) { selected = on ? nil : i } } label: {
            VStack(alignment: .leading, spacing: 3) {
                Text(t.text ?? "").font(serif(22)).foregroundStyle(tint(t))
                HStack(spacing: 4) {
                    Text(XrayView.tag(t)).font(mono(9)).foregroundStyle(Palette.ink(0.35))
                    if let g = t.gender, !g.isEmpty {
                        Text(g).font(sans(9, .semibold)).foregroundStyle(Palette.genderTint(g))
                    }
                }
                if let gl = t.gloss, !gl.isEmpty {
                    Text(gl).font(sans(10.5)).foregroundStyle(Palette.ink(0.45)).lineLimit(1)
                }
            }
            .padding(.horizontal, 8).padding(.vertical, 6)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(on ? Palette.bleu.opacity(0.12) : Palette.surface))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Palette.bleu.opacity(on ? 0.3 : 0), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .help(t.lemma ?? t.text ?? "")
    }

    private func detail(_ t: XrayToken) -> some View {
        let rows: [(String, String)] = [
            ("lemma", t.lemma ?? ""),
            ("pos", [t.pos ?? "", (t.gender ?? "").isEmpty ? "" : (t.gender == "m" ? "masculin" : "féminin")]
                .filter { !$0.isEmpty }.joined(separator: " · ")),
            ("tense", (t.tense ?? "").replacingOccurrences(of: ";", with: " · ")),
            ("role", t.role ?? ""),
            ("meaning", t.gloss ?? ""),
            ("frequency", t.band ?? ""),
        ].filter { !$0.1.isEmpty }
        return VStack(alignment: .leading, spacing: 8) {
            Eyebrow(t.text ?? "", tint: (t.gender ?? "").isEmpty ? nil : Palette.genderTint(t.gender),
                    trailing: AnyView(HStack(spacing: 14) {
                        if let onLookup, let l = t.lemma ?? t.text, !l.isEmpty {
                            LinkButton(label: "Look up", size: 10.5, help: "The Word card for \u{ab} \(l) \u{bb}") { onLookup(l) }
                        }
                        if let onSave {
                            LinkButton(label: "save", tint: Palette.ink(0.4), size: 10.5,
                                       help: "Make \u{ab} \(t.lemma ?? t.text ?? "") \u{bb} a card") { onSave(t) }
                        }
                    }))
            ForEach(rows, id: \.0) { k, v in
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(k.uppercased()).font(mono(9)).tracking(0.9).foregroundStyle(Palette.ink(0.30))
                        .frame(width: 70, alignment: .leading)
                    Text(v).font(k == "lemma" ? serif(15) : sans(12.5)).foregroundStyle(Palette.ink(0.85))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .transition(.opacity)
    }
}

// MARK: - 💬 Ask (tutor)

struct AnswerView: View {
    let answer: Answer
    var context: String? = nil
    var onSave: (() -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 9) {
                ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                    if line.hasPrefix("- ") || line.hasPrefix("* ") || line.hasPrefix("— ") {
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text("—").font(sans(12)).foregroundStyle(Palette.roseInk)
                            markdown(String(line.dropFirst(2)), size: 13)
                        }
                    } else if !line.isEmpty {
                        markdown(line, size: 13.5)
                    }
                }
            }
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                if let m = answer.model, !m.isEmpty {
                    Text(m).font(mono(9.5)).foregroundStyle(Palette.ink(0.28))
                }
                Spacer(minLength: 0)
                if let onSave {
                    TintButton(label: "Save as card", keys: "⌘S", tint: Palette.rose, ink: Palette.roseInk,
                               help: "Front: \u{ab} \((context ?? "").isEmpty ? "the question" : (context ?? "")) \u{bb} · back: this answer",
                               action: onSave)
                }
            }
            .padding(.top, 2)
        }
    }

    private var lines: [String] {
        (answer.answer ?? "").components(separatedBy: "\n").map {
            $0.trimmingCharacters(in: .whitespaces)
        }
    }

    /// Minimal markdown rendering: **bold** and *italic* through AttributedString.
    private func markdown(_ s: String, size: CGFloat) -> some View {
        let attributed = (try? AttributedString(markdown: s,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(s)
        return Text(attributed)
            .font(sans(size)).lineSpacing(size * 0.4).foregroundStyle(Palette.ink)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}
