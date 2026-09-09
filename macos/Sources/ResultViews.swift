import SwiftUI
import AppKit

// MARK: - 📖 Word

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

    private var flag: String {
        isFrench ? "🇫🇷"
                 : WordView.flag(forQuery: lookup.query ?? "", srcLang: lookup.src_lang)
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

    /// The sections offered under the senses.
    private var offered: [Section] {
        var s: [Section] = [.definitions, .russe, .exemples]
        if model.cardIsVerb { s.append(.conjugaison) }
        return s
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            header
            ForEach(groups, id: \.0) { pos, items in
                VStack(alignment: .leading, spacing: 6) {
                    Text(pos.uppercased())
                        .font(rounded(9.5, .bold)).foregroundStyle(.tertiary).tracking(0.6)
                    FlowLayout(spacing: 6) {
                        ForEach(items, id: \.0) { n, s in
                            SenseChip(number: n, sense: s, highlighted: n == 1) {
                                model.save(sense: s, lookup: lookup)
                            }
                        }
                    }
                }
            }
            if let back = lookup.senses?.first?.back, !back.isEmpty {
                Text("← " + back.prefix(6).joined(separator: ", "))
                    .font(rounded(11, .regular)).foregroundStyle(.tertiary)
            }
            ForEach(Array((lookup.examples ?? []).prefix(2).enumerated()), id: \.offset) { _, ex in
                if ex.count >= 2 { ExampleLine(fr: ex[0], en: ex[1]) }
            }
            actions
            sections
        }
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(flag).font(.system(size: 17))
            Text(isFrench ? (lookup.head ?? lookup.query ?? "") : (lookup.query ?? ""))
                .font(rounded(21, .bold))
            if isFrench {
                if let g = lookup.lexique?.genre, !g.isEmpty {
                    Text(g).font(rounded(11, .bold))
                        .padding(.horizontal, 5).padding(.vertical, 1.5)
                        .background(Palette.genderTint(g).opacity(0.20), in: Capsule())
                        .foregroundStyle(Palette.genderTint(g))
                }
                if let b = lookup.lexique?.band, !b.isEmpty {
                    Text("\(Palette.stars(b)) \(b)")
                        .font(rounded(10, .medium)).foregroundStyle(.tertiary)
                }
                if let c = lookup.lexique?.cefr, !c.isEmpty {
                    CEFRPill(level: c)
                }
                if let ipa = lookup.lexique?.ipa, !ipa.isEmpty {
                    Text("/\(ipa)/").font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
            } else if let t = lookup.translation, !t.isEmpty {
                // « 🇷🇺 сказать → 🇫🇷 dire » — each side keeps its own flag.
                HStack(spacing: 5) {
                    Text("→").font(rounded(13, .medium)).foregroundStyle(.tertiary)
                    Text("🇫🇷").font(.system(size: 12))
                    Text(t).font(rounded(15, .semibold)).foregroundStyle(Palette.bleu)
                }
            }
            Spacer(minLength: 0)
        }
    }

    /// One button per section, plus "Ask ?" — no flags, no syntax.
    private var actions: some View {
        VStack(alignment: .leading, spacing: 6) {
            Divider().opacity(0.3)
            FlowLayout(spacing: 6) {
                ForEach(offered) { s in
                    ActionButton(icon: s.icon, label: s.label,
                                 active: model.open.contains(s),
                                 busy: isLoading(s),
                                 help: "\(s.label) (\(s.shortcut)) — \(s.blurb)") {
                        withAnimation(.easeOut(duration: 0.15)) { model.toggle(s) }
                    }
                }
                ActionButton(icon: "speaker.wave.2", label: "Listen",
                             active: false, busy: model.speaking,
                             help: "Hear \u{ab} \(model.cardTerm) \u{bb} said by a native speaker (⌘P) — Wiktionary/Commons") {
                    model.speak(model.cardTerm)
                }
                ActionButton(icon: "bubble.left.and.text.bubble.right", label: "Ask ?",
                             active: false, busy: false,
                             help: "Ask the tutor about \u{ab} \(model.cardTerm) \u{bb} (⌘L)") {
                    model.askAbout(model.cardTerm)
                }
            }
            if !model.cardTerm.isEmpty {
                Text("about \u{ab} \(model.cardTerm) \u{bb}")
                    .font(rounded(10, .regular)).foregroundStyle(.quaternary)
            }
        }
        .padding(.top, 2)
    }

    private func isLoading(_ s: Section) -> Bool {
        if case .chargement = model.sections[s] { return true }
        return false
    }

    private var sections: some View {
        VStack(alignment: .leading, spacing: 9) {
            ForEach(offered.filter { model.open.contains($0) }) { s in
                SectionView(section: s, state: model.sections[s], model: model).id(s)
            }
        }
    }
}

struct ExampleLine: View {
    let fr: String
    let en: String
    /// A small 🇷🇺 in front of a Russian translation.
    var flag: String? = nil
    var tint: Color = Palette.bleu

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(fr).font(.system(size: 12.5, weight: .regular, design: .rounded))
                .italic().foregroundStyle(.primary.opacity(0.85))
                .fixedSize(horizontal: false, vertical: true)
            if !en.isEmpty {
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    if let f = flag { Text(f).font(.system(size: 9)) }
                    Text(en).font(rounded(11, .regular)).foregroundStyle(.tertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(.leading, 9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: 2).fill(tint.opacity(0.35)).frame(width: 3)
        }
    }
}

/// A flat button in the action row of the Word card.
struct ActionButton: View {
    let icon: String
    let label: String
    let active: Bool
    let busy: Bool
    var help: String = ""
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                if busy {
                    ProgressView().controlSize(.small).scaleEffect(0.55).frame(width: 11, height: 11)
                } else {
                    Image(systemName: icon).font(.system(size: 10, weight: .medium))
                }
                Text(label).font(rounded(11.5, .medium))
                if active {
                    Image(systemName: "chevron.up").font(.system(size: 7, weight: .bold))
                }
            }
            .padding(.horizontal, 9).padding(.vertical, 5)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(active ? Palette.bleu.opacity(0.16)
                                 : Color.primary.opacity(hover ? 0.12 : 0.07))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(Palette.bleu.opacity(active ? 0.45 : 0), lineWidth: 1)
            )
            .foregroundStyle(active ? Palette.bleu : Color.primary.opacity(0.8))
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(help.isEmpty ? label : help)
    }
}

/// One expanded section under the senses.
struct SectionView: View {
    let section: Section
    let state: SectionState?
    @ObservedObject var model: DicoModel

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(section.label.uppercased())
                .font(rounded(9.5, .bold)).foregroundStyle(.tertiary).tracking(0.6)
            content
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 10))
    }

    @ViewBuilder private var content: some View {
        switch state {
        case .none, .some(.chargement):
            HStack(spacing: 7) {
                ProgressView().controlSize(.small).scaleEffect(0.7)
                Text("loading…").font(rounded(11, .regular)).foregroundStyle(.secondary)
            }
        case .some(.erreur(let issue)):
            VStack(alignment: .leading, spacing: 6) {
                IssueView(issue: issue, model: model)
                Button { model.reload(section) } label: {
                    Text("Try again").font(rounded(10.5, .medium)).foregroundStyle(Palette.bleu)
                }
                .buttonStyle(.plain)
            }
        case .some(.pret(let payload)):
            switch payload {
            case .definition(let d):   DefinitionBody(def: d)
            case .multitran(let m):    MultitranBody(entry: m)
            case .examples(let pack):  ExamplesBody(pack: pack, own: model.cardExamples)
            case .conjugation(let c):  ConjugationView(conj: c, compact: true)
            }
        }
    }
}

struct DefinitionBody: View {
    let def: Definition
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 7) {
                Text(def.word ?? "").font(rounded(14, .bold))
                if let p = def.ipa, !p.isEmpty {
                    Text("[\(p)]").font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
                if let p = def.pos, !p.isEmpty {
                    Text(p).font(rounded(10, .medium)).foregroundStyle(.secondary)
                }
                if let g = def.gender, !g.isEmpty {
                    Text(g).font(rounded(10, .bold)).foregroundStyle(Palette.genderTint(g))
                }
                Spacer(minLength: 0)
            }
            ForEach(Array((def.defs ?? []).enumerated()), id: \.offset) { i, d in
                HStack(alignment: .top, spacing: 7) {
                    Text("\(i + 1)").font(rounded(9, .bold))
                        .frame(width: 15, height: 15)
                        .background(Circle().fill(Palette.bleu.opacity(0.18)))
                        .foregroundStyle(Palette.bleu)
                    Text(d).font(rounded(12, .regular))
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            if let e = def.etym, !e.isEmpty {
                Text(e).font(rounded(10.5, .regular)).italic().foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            WordNoteRow(icon: "≈", title: "synonymes", words: def.syn ?? [])
            WordNoteRow(icon: "♪", title: "homophones", words: def.homo ?? [])
        }
    }
}

/// The CEFR level as a pill, greener the earlier a learner meets the word.
struct CEFRPill: View {
    let level: String

    private var tint: Color {
        switch level.prefix(1) {
        case "A": return Palette.vert
        case "B": return Palette.bleu
        default:  return Palette.rouge
        }
    }

    var body: some View {
        Text(level).font(rounded(10, .bold))
            .padding(.horizontal, 5).padding(.vertical, 1.5)
            .background(tint.opacity(0.18), in: Capsule())
            .foregroundStyle(tint)
            .help("CEFR level \(level) — when a learner is expected to meet this word (FLELex)")
    }
}

/// « ≈ synonymes  minet · greffier (familier) » — a label and its words, with
/// the register tag dimmed after the word it belongs to.
struct WordNoteRow: View {
    let icon: String
    let title: String
    let words: [WordNote]

    var body: some View {
        if !words.isEmpty {
            HStack(alignment: .top, spacing: 6) {
                Text("\(icon) \(title)").font(rounded(10, .medium))
                    .foregroundStyle(.tertiary)
                    .frame(width: 82, alignment: .leading)
                FlowLayout(spacing: 5) {
                    ForEach(words, id: \.self) { w in
                        HStack(spacing: 3) {
                            Text(w.word ?? "").font(rounded(11, .medium))
                            if let n = w.note, !n.isEmpty {
                                Text(n).font(rounded(9, .regular)).foregroundStyle(.tertiary)
                            }
                        }
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(RoundedRectangle(cornerRadius: 6, style: .continuous)
                            .fill(Color.primary.opacity(0.05)))
                    }
                }
            }
        }
    }
}

/// Russian straight from the Wiktionnaire — what you get when Multitran, which
/// is proprietary and bring-your-own, is not installed.
struct WiktionaryRuBody: View {
    let terms: [RuTerm]

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("Wiktionnaire").font(rounded(9.5, .medium)).foregroundStyle(.quaternary)
            ForEach(terms, id: \.self) { t in
                HStack(spacing: 7) {
                    Text(t.word ?? "").font(rounded(13, .semibold))
                    if let tr = t.tr, !tr.isEmpty {
                        Text("[\(tr)]").font(.system(size: 10.5, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                    if let g = t.gender, !g.isEmpty {
                        Text(g).font(rounded(10, .bold)).foregroundStyle(Palette.genderTint(g))
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
/// card scrolls.
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
                out = out + Text(" · ").font(rounded(11.5, .regular))
                    .foregroundStyle(Color.primary.opacity(0.25))
            }
            first = false
            out = out + Text(tr)
                .font(.system(size: 12, weight: .regular, design: .rounded))
                .foregroundStyle(Color.primary.opacity(0.88))
            let note = (it.note ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if !note.isEmpty {
                out = out + Text(" " + note)
                    .font(.system(size: 10.5, weight: .regular, design: .rounded))
                    .italic()
                    .foregroundStyle(Color.secondary.opacity(0.85))
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
        VStack(alignment: .leading, spacing: 9) {
            Text(arrow).font(rounded(9.5, .medium)).foregroundStyle(.quaternary)
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
        return VStack(alignment: .leading, spacing: 5) {
            if !pos.isEmpty {
                Text(pos.uppercased())
                    .font(rounded(9.5, .bold)).tracking(0.8)
                    .foregroundStyle(Palette.bleu.opacity(0.85))
            }
            ForEach(Array((g.senses ?? []).enumerated()), id: \.offset) { _, sense in
                senseRow(sense)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func senseRow(_ sense: MultitranSense) -> some View {
        let n = (sense.n ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let domain = (sense.domain ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return HStack(alignment: .top, spacing: 7) {
            VStack(alignment: .trailing, spacing: 2) {
                if !n.isEmpty {
                    Text(n).font(rounded(10.5, .bold)).foregroundStyle(.secondary)
                }
                if !domain.isEmpty {
                    Text(domain)
                        .font(rounded(9, .medium))
                        .lineLimit(1).minimumScaleFactor(0.7)
                        .padding(.horizontal, 4).padding(.vertical, 1.5)
                        .background(Color.primary.opacity(0.08),
                                    in: RoundedRectangle(cornerRadius: 4))
                        .foregroundStyle(.secondary)
                        .help("Multitran domain")
                }
            }
            .frame(width: 60, alignment: .trailing)

            MultitranBody.translations(sense.items ?? [])
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    /// Only when `groups` is empty: the flat `lines` the CLI also returns.
    private var fallbackLines: some View {
        VStack(alignment: .leading, spacing: 3) {
            ForEach(Array((entry.lines ?? []).enumerated()), id: \.offset) { _, line in
                let heading = !line.contains(")") && line.count <= 12
                Text(line)
                    .font(rounded(heading ? 11 : 12, heading ? .bold : .regular))
                    .foregroundStyle(heading ? Color.secondary : Color.primary.opacity(0.85))
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, heading ? 3 : 0)
            }
        }
    }
}

struct ExamplesBody: View {
    let pack: ExamplePack
    /// The example the card itself came with — kept first when Tatoeba
    /// does not already have it.
    var own: [[String]] = []

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
        VStack(alignment: .leading, spacing: 8) {
            if english.isEmpty && russian.isEmpty {
                Text("No examples found")
                    .font(rounded(11.5, .regular)).foregroundStyle(.secondary)
            }
            ForEach(Array(english.enumerated()), id: \.offset) { _, ex in
                ExampleLine(fr: ex.fr ?? "", en: ex.en ?? "")
            }
            ForEach(Array(russian.enumerated()), id: \.offset) { _, ex in
                ExampleLine(fr: ex.fr ?? "", en: ex.ru ?? "",
                            flag: "🇷🇺", tint: Palette.rose)
            }
        }
    }
}

/// One sense: a clickable numbered chip that saves the term.
struct SenseChip: View {
    let number: Int
    let sense: Sense
    let highlighted: Bool
    let action: () -> Void
    @State private var hover = false

    private var tint: Color {
        let g = sense.gender ?? ""
        return g.isEmpty ? (highlighted ? Palette.bleu : Color.primary.opacity(0.55))
                         : Palette.genderTint(g)
    }
    private var text: String { sense.display }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Text("\(number)")
                    .font(rounded(9.5, .bold))
                    .frame(width: 15, height: 15)
                    .background(Circle().fill(tint.opacity(highlighted ? 0.95 : 0.22)))
                    .foregroundStyle(highlighted ? Color.white : tint)
                Text(text).font(rounded(13, highlighted ? .semibold : .medium))
                let stars = Palette.stars(sense.band)
                if !stars.isEmpty {
                    Text(stars).font(.system(size: 8)).foregroundStyle(Palette.jaune)
                }
            }
            .padding(.horizontal, 8).padding(.vertical, 5)
            .background(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(tint.opacity(highlighted ? 0.16 : 0.08))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .strokeBorder(tint.opacity(hover ? 0.75 : (highlighted ? 0.45 : 0.14)), lineWidth: 1)
            )
            .scaleEffect(hover ? 1.03 : 1)
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .animation(.easeOut(duration: 0.12), value: hover)
        .help("Click to save \u{ab} \(text) \u{bb} (⌘\(number))")
    }
}

/// A wrapping row layout — for the sense chips.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxW = proposal.width ?? 480
        var x: CGFloat = 0, y: CGFloat = 0, lineH: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > 0, x + s.width > maxW { x = 0; y += lineH + spacing; lineH = 0 }
            x += s.width + spacing
            lineH = max(lineH, s.height)
        }
        return CGSize(width: maxW, height: y + lineH)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, lineH: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > bounds.minX, x + s.width > bounds.maxX { x = bounds.minX; y += lineH + spacing; lineH = 0 }
            v.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
            x += s.width + spacing
            lineH = max(lineH, s.height)
        }
    }
}

// MARK: - 🔁 Conjugate — a real grid

/// The je/tu/il/nous/vous/ils × seven-tenses table: full French tense names in
/// the header, a muted pronoun gutter, alternating row bands, the présent
/// column on a tinted rounded panel, compound forms with a dimmed auxiliary
/// and « — » where the impératif has no form.
///
/// Everything is sized from a width budget so the grid never scrolls sideways.
struct ConjugationView: View {
    let conj: Conjugation
    /// Inside a Word-card section the grid gets a little less room.
    var compact: Bool = false

    static let pronouns = ["je", "tu", "il", "nous", "vous", "ils"]
    /// The impératif only has tu / nous / vous.
    static let imperativeRow: [Int?] = [nil, 0, nil, 1, 2, nil]

    // MARK: Geometry — the grid must fit the panel without scrolling sideways

    /// The panel is 600 pt wide; the results area keeps 16 pt on each side,
    /// and a card section eats 20 pt more.
    static let fullBudget: CGFloat = PanelSize.width - 32          // 568
    static let compactBudget: CGFloat = PanelSize.width - 32 - 40  // 528

    private var budget: CGFloat { compact ? ConjugationView.compactBudget : ConjugationView.fullBudget }
    private var gutter: CGFloat { 32 }
    private var colSpacing: CGFloat { 2 }
    private var colPad: CGFloat { 2 }
    private var rowSpacing: CGFloat { 1.5 }
    private var rowHeight: CGFloat { compact ? 16.5 : 18 }
    private var headerHeight: CGFloat { compact ? 22 : 24 }
    private var bodySize: CGFloat { compact ? 10.5 : 11 }
    private var columnCount: CGFloat { CGFloat(max(1, conj.orderedTenses.count)) }

    /// What is left for one tense column once the gutter and the gaps are paid.
    var colWidth: CGFloat {
        let overhead = (colSpacing + 2 * colPad) * columnCount
        return max(44, ((budget - gutter - overhead) / columnCount).rounded(.down))
    }
    /// The grid's own width — `--selftest` asserts this fits the budget.
    var gridWidth: CGFloat {
        gutter + (colWidth + 2 * colPad + colSpacing) * columnCount
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

    // MARK: Body

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 6 : 9) {
            if !compact {
                HStack(spacing: 7) {
                    Text("🔁").font(.system(size: 15))
                    Text(conj.infinitive ?? "").font(rounded(20, .bold))
                    Spacer(minLength: 0)
                    Text("hover a column for what the tense is for")
                        .font(rounded(9.5, .regular)).foregroundStyle(.quaternary)
                }
            }
            HStack(alignment: .top, spacing: colSpacing) {
                pronounGutter
                ForEach(conj.orderedTenses, id: \.0) { name, forms in
                    column(name: name, forms: forms)
                }
            }
            .frame(width: gridWidth, alignment: .leading)
        }
    }

    private var pronounGutter: some View {
        VStack(spacing: rowSpacing) {
            Color.clear.frame(width: gutter, height: headerHeight)
            ForEach(0..<6, id: \.self) { i in
                Text(ConjugationView.pronouns[i])
                    .font(rounded(10.5, .medium))
                    .foregroundStyle(.tertiary)
                    .frame(width: gutter, height: rowHeight, alignment: .trailing)
                    .background(band(i))
            }
        }
    }

    private func column(name: String, forms: [String]) -> some View {
        let present = (name == "présent")
        return VStack(spacing: rowSpacing) {
            Text(name)
                .font(rounded(9.5, .bold)).tracking(0.2)
                .foregroundStyle(present ? Palette.bleu : Color.secondary)
                .lineLimit(2).minimumScaleFactor(0.68)
                .multilineTextAlignment(.leading)
                .frame(width: colWidth, height: headerHeight, alignment: .bottomLeading)
            ForEach(0..<6, id: \.self) { i in
                cell(name: name, forms: forms, row: i, present: present)
            }
        }
        .padding(.horizontal, colPad).padding(.vertical, 3)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(present ? Palette.bleu.opacity(0.11) : Color.clear)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Palette.bleu.opacity(present ? 0.22 : 0), lineWidth: 1)
        )
        .help(Conjugation.hints[name] ?? name)
    }

    @ViewBuilder
    private func cell(name: String, forms: [String], row i: Int, present: Bool) -> some View {
        let raw = ConjugationView.form(name, forms, row: i)
        Group {
            if let raw {
                let (aux, rest) = ConjugationView.split(raw)
                (aux.map { Text($0 + " ").foregroundStyle(Color.secondary.opacity(0.7)) } ?? Text(""))
                    + Text(rest).foregroundStyle(Color.primary)
            } else {
                Text("—").foregroundStyle(Color.secondary.opacity(0.30))
            }
        }
        .font(.system(size: bodySize, weight: present ? .semibold : .regular, design: .rounded))
        .lineLimit(1).minimumScaleFactor(0.55)
        .frame(width: colWidth, height: rowHeight, alignment: .leading)
        .background(band(i))
        .help(raw.map { "\(ConjugationView.pronouns[i]) — \(name): \($0)" }
              ?? (Conjugation.hints[name] ?? name))
    }

    /// The subtle alternating row band, drawn on top of the column tint.
    private func band(_ i: Int) -> some View {
        RoundedRectangle(cornerRadius: 4, style: .continuous)
            .fill(i % 2 == 1 ? Color.primary.opacity(0.045) : Color.clear)
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

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // The sentence with the faulty spans highlighted.
            segments.reduce(Text("")) { acc, seg in
                acc + Text(seg.0)
                    .font(.system(size: 14, weight: .regular, design: .rounded))
                    .foregroundColor(seg.1 == 0 ? .primary : (seg.1 == 1 ? Palette.rouge : Color.orange))
                    .underline(seg.1 != 0, color: seg.1 == 1 ? Palette.rouge : Palette.jaune)
            }
            .fixedSize(horizontal: false, vertical: true)

            let errs = grammar.errors ?? []
            let sp = grammar.spelling ?? []
            if errs.isEmpty && sp.isEmpty {
                Label("No mistakes found 🎉", systemImage: "checkmark.seal.fill")
                    .font(rounded(12, .medium)).foregroundStyle(Palette.vert)
            }
            ForEach(Array(errs.enumerated()), id: \.offset) { i, e in
                issue(number: i + 1, title: e.text ?? "", message: e.message ?? e.type ?? "",
                      suggestions: e.suggestions ?? [], color: Palette.rouge)
            }
            ForEach(Array(sp.enumerated()), id: \.offset) { i, s in
                issue(number: errs.count + i + 1, title: s.text ?? "", message: "Spelling",
                      suggestions: s.suggestions ?? [], color: Color.orange)
            }
            if let c = grammar.corrected, !c.isEmpty {
                HStack(alignment: .top, spacing: 8) {
                    Text(c).font(.system(size: 13, weight: .medium, design: .rounded))
                        .foregroundStyle(Palette.vert)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 4)
                    CopyButton(text: c, label: "Copy", model: model)
                        .help("Copy the corrected sentence (⌘⇧C)")
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Palette.vert.opacity(0.09), in: RoundedRectangle(cornerRadius: 10))
            }
        }
    }

    private func issue(number: Int, title: String, message: String,
                       suggestions: [String], color: Color) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text("\(number)").font(rounded(9.5, .bold))
                .frame(width: 16, height: 16)
                .background(Circle().fill(color.opacity(0.2))).foregroundStyle(color)
            VStack(alignment: .leading, spacing: 4) {
                Text(message).font(rounded(11.5, .regular))
                    .fixedSize(horizontal: false, vertical: true)
                if !suggestions.isEmpty {
                    FlowLayout(spacing: 5) {
                        ForEach(suggestions.prefix(6), id: \.self) { s in
                            Text(s).font(rounded(11, .medium))
                                .padding(.horizontal, 7).padding(.vertical, 2.5)
                                .background(Palette.vert.opacity(0.15), in: Capsule())
                                .foregroundStyle(Palette.vert)
                        }
                    }
                }
            }
        }
    }
}

// MARK: - 🔬 X-ray

struct XrayView: View {
    let tokens: [XrayToken]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 0) {
                cell("word", 84, .bold); cell("lemma", 80, .bold); cell("pos", 96, .bold)
                cell("tense", 104, .bold); cell("role", 88, .bold); cell("meaning", 100, .bold)
            }
            .foregroundStyle(.tertiary).padding(.bottom, 3)
            Divider().opacity(0.4)
            ForEach(Array(tokens.enumerated()), id: \.offset) { i, t in
                HStack(spacing: 0) {
                    Text(t.text ?? "").font(rounded(12, .semibold))
                        .foregroundStyle(Palette.genderTint(t.gender))
                        .frame(width: 84, alignment: .leading).lineLimit(1)
                    cell(t.lemma ?? "", 80); cell(t.pos ?? "", 96)
                    cell((t.tense ?? "").split(separator: ";").first.map(String.init) ?? "", 104)
                    cell(t.role ?? "", 88); cell(t.gloss ?? "", 100)
                }
                .padding(.vertical, 3.5)
                .background(i % 2 == 1 ? Color.primary.opacity(0.035) : .clear)
            }
        }
    }

    private func cell(_ s: String, _ w: CGFloat, _ weight: Font.Weight = .regular) -> some View {
        Text(s).font(.system(size: weight == .bold ? 9 : 10.5, weight: weight, design: .rounded))
            .foregroundStyle(weight == .bold ? Color.secondary : Color.secondary.opacity(0.95))
            .frame(width: w, alignment: .leading).lineLimit(1).truncationMode(.tail)
            .help(s)
    }
}

// MARK: - 💬 Ask (tutor)

struct AnswerView: View {
    let answer: Answer
    var context: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let c = context, !c.isEmpty {
                Text("about \u{ab} \(c) \u{bb}")
                    .font(rounded(10.5, .medium)).foregroundStyle(.tertiary)
            }
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                if line.hasPrefix("- ") || line.hasPrefix("* ") {
                    HStack(alignment: .firstTextBaseline, spacing: 7) {
                        Text("•").foregroundStyle(Palette.bleu).font(rounded(12, .bold))
                        markdown(String(line.dropFirst(2)))
                    }
                } else if !line.isEmpty {
                    markdown(line)
                }
            }
            if let m = answer.model, !m.isEmpty {
                Text(m).font(rounded(9.5, .regular)).foregroundStyle(.quaternary).padding(.top, 4)
            }
        }
    }

    private var lines: [String] {
        (answer.answer ?? "").components(separatedBy: "\n").map {
            $0.trimmingCharacters(in: .whitespaces)
        }
    }

    /// Minimal markdown rendering: **bold** and *italic* through AttributedString.
    private func markdown(_ s: String) -> some View {
        let attributed = (try? AttributedString(markdown: s,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(s)
        return Text(attributed)
            .font(.system(size: 12.5, weight: .regular, design: .rounded))
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}
