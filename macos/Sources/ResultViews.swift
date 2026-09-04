import SwiftUI
import AppKit

// MARK: - 📖 Word

struct WordView: View {
    let lookup: Lookup
    @ObservedObject var model: DicoModel

    private var isFrench: Bool { lookup.direction == "fr" }
    private var flag: String {
        if isFrench { return "🇫🇷" }
        return lookup.src_lang == "ru" ? "🇷🇺" : "🇬🇧"
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
            if let ex = lookup.examples?.first, ex.count >= 2 {
                VStack(alignment: .leading, spacing: 2) {
                    Text(ex[0]).font(.system(size: 12.5, weight: .regular, design: .rounded))
                        .italic().foregroundStyle(.primary.opacity(0.85))
                    Text(ex[1]).font(rounded(11, .regular)).foregroundStyle(.tertiary)
                }
                .padding(.leading, 9)
                .overlay(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2).fill(Palette.bleu.opacity(0.35)).frame(width: 3)
                }
                .padding(.top, 2)
            }
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
            } else if let t = lookup.translation, !t.isEmpty {
                Text("→ \(t)").font(rounded(13, .medium)).foregroundStyle(Palette.bleu)
            }
            Spacer(minLength: 0)
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
        .help("Click to save \u{201c}\(text)\u{201d} (⌘\(number))")
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

// MARK: - 🔁 Conjugate

struct ConjugationView: View {
    let conj: Conjugation
    private let pronouns = ["je", "tu", "il", "nous", "vous", "ils"]

    /// "que je mange" → "mange"; "j'ai mangé" → "ai mangé"; "va" → "va".
    static func strip(_ form: String) -> String {
        var s = form
        for p in ["que ", "qu'"] where s.hasPrefix(p) { s = String(s.dropFirst(p.count)) }
        if s.hasPrefix("j'") { return String(s.dropFirst(2)) }
        let words = ["je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles"]
        for w in words where s.hasPrefix(w + " ") { return String(s.dropFirst(w.count + 1)) }
        return s
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 7) {
                Text("🔁").font(.system(size: 15))
                Text(conj.infinitive ?? "").font(rounded(20, .bold))
                Spacer()
            }
            ScrollView(.horizontal, showsIndicators: false) {
                Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 3) {
                    GridRow {
                        Text("").frame(width: 34)
                        ForEach(conj.orderedTenses, id: \.0) { name, _ in
                            Text(Conjugation.shortLabels[name] ?? name)
                                .font(rounded(9.5, .bold)).tracking(0.4)
                                .foregroundStyle(name == "présent" ? Palette.bleu : Color.secondary)
                                .frame(width: 86, alignment: .leading)
                        }
                    }
                    ForEach(Array(pronouns.enumerated()), id: \.offset) { i, pron in
                        GridRow {
                            Text(pron).font(rounded(10.5, .medium)).foregroundStyle(.tertiary)
                                .frame(width: 34, alignment: .trailing)
                            ForEach(conj.orderedTenses, id: \.0) { name, forms in
                                let isImp = (name == "impératif")
                                // The impératif only has 3 forms: tu / nous / vous.
                                let idx: Int? = isImp ? [nil, 0, nil, 1, 2, nil][i] : (i < forms.count ? i : nil)
                                Text(idx.map { ConjugationView.strip(forms[$0]) } ?? "—")
                                    .font(.system(size: 11.5, weight: name == "présent" ? .semibold : .regular,
                                                  design: .rounded))
                                    .foregroundStyle(idx == nil ? Color.secondary.opacity(0.35) : .primary)
                                    .lineLimit(1)
                                    .frame(width: 86, alignment: .leading)
                                    .padding(.vertical, 2.5).padding(.horizontal, 4)
                                    .background(
                                        RoundedRectangle(cornerRadius: 5)
                                            .fill(name == "présent" ? Palette.bleu.opacity(0.10) : .clear)
                                    )
                            }
                        }
                    }
                }
            }
        }
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
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(c, forType: .string)
                        model.flash("✓ copied")
                    } label: {
                        Text("Copy").font(rounded(10.5, .medium))
                            .padding(.horizontal, 8).padding(.vertical, 3)
                            .background(Palette.vert.opacity(0.16), in: Capsule())
                            .foregroundStyle(Palette.vert)
                    }
                    .buttonStyle(.plain)
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
                cell("word", 74, .bold); cell("lemma", 70, .bold); cell("pos", 88, .bold)
                cell("tense", 96, .bold); cell("role", 78, .bold); cell("meaning", 80, .bold)
            }
            .foregroundStyle(.tertiary).padding(.bottom, 3)
            Divider().opacity(0.4)
            ForEach(Array(tokens.enumerated()), id: \.offset) { i, t in
                HStack(spacing: 0) {
                    Text(t.text ?? "").font(rounded(12, .semibold))
                        .foregroundStyle(Palette.genderTint(t.gender))
                        .frame(width: 74, alignment: .leading).lineLimit(1)
                    cell(t.lemma ?? "", 70); cell(t.pos ?? "", 88)
                    cell((t.tense ?? "").split(separator: ";").first.map(String.init) ?? "", 96)
                    cell(t.role ?? "", 78); cell(t.gloss ?? "", 80)
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

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
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
