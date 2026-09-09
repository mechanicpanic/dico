import SwiftUI
import AppKit

// MARK: - 🎴 Cards — the Anki deck, reviewed in the panel

/// What the Cards mode is showing.
struct ReviewState {
    var cards: [AnkiCard] = []
    var index = 0
    var revealed = false
    var loading = false
    var unreachable = false
    var error: String? = nil
    var counts = AnkiCounts()
    var graded = 0
    var pushing = false
    var pushed: String? = nil
    var launching = false

    var current: AnkiCard? { index < cards.count ? cards[index] : nil }
    var remaining: Int { max(0, cards.count - index) }
}

struct ReviewView: View {
    @ObservedObject var model: DicoModel

    private var r: ReviewState { model.review }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Hairline(structural: true)
            Group {
                if r.loading && r.cards.isEmpty {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text("asking Anki…").font(sans(12)).foregroundStyle(Palette.ink(0.45))
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if r.unreachable {
                    unreachable
                } else if let card = r.current {
                    self.card(card)
                } else {
                    nothingDue
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    // MARK: The deck line

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text("🎴").font(.system(size: 13))
            Text(model.ankiDeck).font(serif(20)).foregroundStyle(Palette.ink)
                .lineLimit(1).minimumScaleFactor(0.7)
            Spacer(minLength: 0)
            if r.counts.total > 0 || r.graded > 0 {
                Text(countsLine).font(mono(9.5)).foregroundStyle(Palette.ink(0.35))
            }
        }
        .padding(.top, 14).padding(.horizontal, 16).padding(.bottom, 12)
    }

    private var countsLine: String {
        var parts: [String] = []
        if r.counts.due > 0 { parts.append("\(r.counts.due) due") }
        if r.counts.learning > 0 { parts.append("\(r.counts.learning) learning") }
        if r.counts.new > 0 { parts.append("\(r.counts.new) new") }
        if r.graded > 0 { parts.append("\(r.graded) done") }
        return parts.joined(separator: " · ")
    }

    // MARK: One card

    private func card(_ c: AnkiCard) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(c.isNew ? "new" : (c.isLearning ? "learning" : "review · \(c.interval) d"))
                    .font(mono(9)).tracking(0.9).foregroundStyle(c.isNew ? Palette.bleuInk : Palette.ink(0.30))
                Hairline()
                Text("\(r.index + 1) / \(r.cards.count)").font(mono(9.5)).foregroundStyle(Palette.ink(0.30))
            }
            Text(c.front).font(serif(34, .medium)).foregroundStyle(Palette.ink)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 6)
            if r.revealed {
                Hairline()
                let lines = c.backLines
                VStack(alignment: .leading, spacing: 6) {
                    if let first = lines.first {
                        Text(first).font(sans(15)).foregroundStyle(Palette.ink)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    ForEach(Array(lines.dropFirst().enumerated()), id: \.offset) { _, l in
                        Text(l).font(serif(13)).italic().foregroundStyle(Palette.ink(0.6))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .transition(.opacity)
            }
            Spacer(minLength: 0)
            if let e = r.error {
                Text(e).font(sans(11)).foregroundStyle(Palette.rougeInk)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if r.revealed {
                HStack(spacing: 8) {
                    TintButton(label: "Again", keys: "1", tint: Palette.rouge, ink: Palette.rougeInk,
                               help: "Again — see it soon (1)") { model.grade(1) }
                    TintButton(label: "Hard", keys: "2", tint: Palette.jaune, ink: Palette.jauneInk,
                               help: "Hard (2)") { model.grade(2) }
                    TintButton(label: "Good", keys: "3", tint: Palette.vert, ink: Palette.vertInk,
                               help: "Good (3, Space, ⏎)") { model.grade(3) }
                    TintButton(label: "Easy", keys: "4", tint: Palette.bleu, ink: Palette.bleuInk,
                               help: "Easy (4)") { model.grade(4) }
                    Spacer(minLength: 0)
                    KeyHint("in Anki, on the spot", alpha: 0.25)
                }
            } else {
                HStack(spacing: 10) {
                    TintButton(label: "Show the answer", keys: "Space", help: "Space or ⏎") { model.reveal() }
                    Spacer(minLength: 0)
                    LinkButton(label: "Look it up", tint: Palette.ink(0.4), size: 10.5,
                               help: "Open the Word card for \u{ab} \(c.front) \u{bb}") {
                        model.run(c.front, mode: .mot)
                    }
                }
            }
        }
        .padding(.top, 14).padding(.horizontal, 18).padding(.bottom, 14)
        .animation(.easeOut(duration: 0.12), value: r.revealed)
    }

    // MARK: Nothing due / Anki closed

    private var nothingDue: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(r.graded > 0 ? "Done for now." : "Nothing due.").font(serif(24)).foregroundStyle(Palette.ink)
            Text(r.graded > 0
                 ? "\(r.graded) card\(r.graded == 1 ? "" : "s") graded — Anki has the schedule."
                 : "Anki has no card waiting in this deck. New words you look up can join it below.")
                .font(sans(12.5)).lineSpacing(3).foregroundStyle(Palette.ink(0.5))
                .frame(maxWidth: 400, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
            pushRow
            LinkButton(label: "Check again", tint: Palette.ink(0.4)) { model.startReview() }
        }
        .padding(.top, 20).padding(.horizontal, 18)
    }

    private var pushRow: some View {
        HStack(spacing: 10) {
            TintButton(label: r.pushing ? "Pushing…" : "Push saved words to Anki",
                       help: "Every word dico saved that the deck does not have yet", busy: r.pushing) {
                model.pushToAnki()
            }
            if let p = r.pushed {
                Text(p).font(sans(11.5)).foregroundStyle(p.hasPrefix("✓") ? Palette.vertInk : Palette.rougeInk)
            }
            Spacer(minLength: 0)
        }
    }

    private var unreachable: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Anki is not running").font(serif(24)).foregroundStyle(Palette.ink)
                Text("The panel reviews through Anki itself, so Anki keeps the schedule. Open it — with the AnkiConnect add-on installed — and the cards appear here.")
                    .font(sans(12.5)).lineSpacing(3).foregroundStyle(Palette.ink(0.5))
                    .frame(maxWidth: 420, alignment: .leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 10) {
                TintButton(label: r.launching ? "Opening Anki…" : "Open Anki",
                           help: "Launches Anki and waits for it", busy: r.launching) { model.openAnki() }
                LinkButton(label: "Check again", tint: Palette.ink(0.4)) { model.startReview() }
            }
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Eyebrow("add-on", rule: false)
                Text("Anki ▸ Tools ▸ Add-ons ▸ Get Add-ons ▸ 2055492159, then restart Anki.")
                    .font(sans(11.5)).foregroundStyle(Palette.ink(0.4))
            }
        }
        .padding(.top, 20).padding(.horizontal, 18)
    }
}
