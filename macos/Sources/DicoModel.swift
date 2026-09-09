import SwiftUI
import AppKit

/// The five modes of the panel.
enum Mode: String, CaseIterable, Identifiable {
    case mot, conjuguer, grammaire, rayonsX, demander
    var id: String { rawValue }

    var label: String {
        switch self {
        case .mot: return "Word"
        case .conjuguer: return "Conjugate"
        case .grammaire: return "Grammar"
        case .rayonsX: return "X-ray"
        case .demander: return "Ask"
        }
    }
    var icon: String {
        switch self {
        case .mot: return "📖"
        case .conjuguer: return "🔁"
        case .grammaire: return "✅"
        case .rayonsX: return "🔬"
        case .demander: return "💬"
        }
    }
    var placeholder: String {
        switch self {
        case .mot: return "a word… (cook, кошка, maison)"
        case .conjuguer: return "a verb… (aller)"
        case .grammaire: return "a sentence to correct…"
        case .rayonsX: return "a sentence to dissect…"
        case .demander: return "a question for the tutor…"
        }
    }
}

/// A failure the panel knows how to dress up.
enum Issue {
    case notInstalled           // the CLI itself is missing
    case setupNeeded            // the offline databases were never built
    case plain(String)

    static func from(_ error: Error) -> Issue {
        if let d = error as? DicoError {
            switch d {
            case .notFound: return .notInstalled
            case .setupNeeded: return .setupNeeded
            default: break
            }
        }
        let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        return DicoError.meansMissingData(msg) ? .setupNeeded : .plain(msg)
    }

    var text: String {
        switch self {
        case .notInstalled: return DicoError.notFound.errorDescription ?? ""
        case .setupNeeded: return DicoError.setupNeeded.errorDescription ?? ""
        case .plain(let s): return s
        }
    }
}

/// What the panel is showing right now.
enum Outcome {
    case vide
    case chargement
    case mot(Lookup)
    case conjugaison(Conjugation)
    case grammaire(Grammar, String)     // + the queried sentence (for the offsets)
    case rayonsX([XrayToken])
    case reponse(Answer)
    case erreur(Issue)
}

// MARK: - The expandable sections of the Word card

enum Section: String, CaseIterable, Identifiable {
    case definitions, russe, exemples, conjugaison
    var id: String { rawValue }

    var label: String {
        switch self {
        case .definitions: return "Definitions"
        case .russe: return "Russian"
        case .exemples: return "Examples"
        case .conjugaison: return "Conjugate"
        }
    }
    var icon: String {
        switch self {
        case .definitions: return "book.closed"
        case .russe: return "character.book.closed"
        case .exemples: return "text.quote"
        case .conjugaison: return "arrow.triangle.2.circlepath"
        }
    }
    /// The keyboard shortcut that opens it — shown in the button's tooltip.
    var shortcut: String {
        switch self {
        case .definitions: return "⌘D"
        case .russe: return "⌘R"
        case .exemples: return "⌘E"
        case .conjugaison: return "⌘J"
        }
    }
    /// What it fetches, in one line — the rest of the tooltip.
    var blurb: String {
        switch self {
        case .definitions: return "the Wiktionary entry: IPA, definitions, etymology"
        case .russe: return "the offline Multitran entry, in full"
        case .exemples: return "Tatoeba example sentences"
        case .conjugaison: return "the seven-tense grid, inline"
        }
    }
}

enum SectionContent {
    case definition(Definition)
    case multitran(Multitran)
    case examples(ExamplePack)
    case conjugation(Conjugation)
}

enum SectionState {
    case chargement
    case pret(SectionContent)
    case erreur(Issue)
}

@MainActor
final class DicoModel: ObservableObject {
    @Published var query: String = ""
    @Published var mode: Mode = .mot
    @Published var outcome: Outcome = .vide
    @Published var busy: Bool = false
    @Published var toast: String? = nil
    @Published var shown: Bool = false          // drives the appearance animation
    /// The ⌘/ sheet.
    @Published var showShortcuts: Bool = false
    @Published private(set) var speaking: Bool = false
    private var player: NSSound?
    /// The configured global hotkey, as text — the footer and the sheet show it.
    @Published var hotkeyLabel: String = HotkeyChoice.fallback.display

    /// The last queries, most recent first — shown when the field is empty.
    @Published private(set) var recent: [String] = []
    /// The sections of the current Word card that the user opened.
    @Published private(set) var open: Set<Section> = []
    /// Their content, fetched on first open.
    @Published private(set) var sections: [Section: SectionState] = [:]
    /// The section opened last — the scroll view brings it into view.
    @Published private(set) var lastOpened: Section? = nil
    /// The word the tutor is being asked about (set by the card's "Ask ?" button).
    @Published private(set) var askContext: String? = nil

    /// Last word / sentence looked up — used as `--context` for the tutor.
    private(set) var lastContext: String = ""
    /// Source word of the current card (for `--sens` when saving).
    private(set) var currentSource: String = ""
    /// The FRENCH term the current card is about — what the sections query.
    private(set) var cardTerm: String = ""
    /// Is that term a verb? (drives the Conjugate button)
    private(set) var cardIsVerb: Bool = false
    /// The example(s) that came with the card — kept at the top of the
    /// Examples section when Tatoeba does not repeat them.
    private(set) var cardExamples: [[String]] = []

    private var generation = 0
    private var toastTask: Task<Void, Never>?
    private let recentKey: String
    static let recentLimit = 8

    init(recentKey: String = "dico.recent") {
        self.recentKey = recentKey
        recent = (UserDefaults.standard.array(forKey: recentKey) as? [String]) ?? []
        hotkeyLabel = Shortcuts.globalHotkey
    }

    /// Called after Settings changed the hotkey.
    func refreshHotkeyLabel() { hotkeyLabel = Shortcuts.globalHotkey }

    // MARK: Recent list

    func remember(_ q: String) {
        let t = q.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        var list = recent.filter { $0.caseInsensitiveCompare(t) != .orderedSame }
        list.insert(t, at: 0)
        if list.count > DicoModel.recentLimit { list = Array(list.prefix(DicoModel.recentLimit)) }
        recent = list
        UserDefaults.standard.set(list, forKey: recentKey)
    }

    func forgetRecent() {
        recent = []
        UserDefaults.standard.removeObject(forKey: recentKey)
    }

    // MARK: Input

    /// Called on every keystroke. A leading `-c`, `-g`, `-x` or `?` switches
    /// mode and is removed (a silent power-user shortcut — never advertised).
    /// Emptying the field wipes the results.
    func inputChanged() {
        let prefixes: [(String, Mode)] = [("-c ", .conjuguer), ("-g ", .grammaire),
                                          ("-x ", .rayonsX), ("? ", .demander), ("?", .demander)]
        for (p, m) in prefixes where query.hasPrefix(p) {
            mode = m
            query = String(query.dropFirst(p.count))
            break
        }
        if query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { clearResults() }
    }

    /// Drops the results (and any in-flight query) but keeps the field.
    func clearResults() {
        generation += 1
        busy = false
        outcome = .vide
        open = []
        sections = [:]
        lastOpened = nil
    }

    func clear() {
        query = ""
        askContext = nil
        clearResults()
    }

    /// Esc: first press clears, second one closes. Returns true if it cleared.
    func escape() -> Bool {
        let hasText = !query.isEmpty
        var hasResult = false
        if case .vide = outcome {} else { hasResult = true }
        guard hasText || hasResult else { return false }
        clear()
        return true
    }

    // MARK: Query

    func run(_ text: String, mode m: Mode) {
        query = text
        mode = m
        submit()
    }

    func submit() {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { clearResults(); return }
        generation += 1
        let gen = generation
        let mode = self.mode
        let ctx = askContext ?? lastContext
        // The "about « … »" context belongs to the tutor only.
        if mode != .demander { askContext = nil }
        busy = true
        open = []
        sections = [:]
        lastOpened = nil
        outcome = .chargement

        Task.detached(priority: .userInitiated) {
            let result: Result<Outcome, Error>
            do {
                switch mode {
                case .mot:       result = .success(.mot(try DicoClient.lookup(q)))
                case .conjuguer: result = .success(.conjugaison(try DicoClient.conjugate(q)))
                case .grammaire: result = .success(.grammaire(try DicoClient.grammar(q), q))
                case .rayonsX:   result = .success(.rayonsX(try DicoClient.xray(q)))
                case .demander:  result = .success(.reponse(try DicoClient.ask(q, context: ctx)))
                }
            } catch {
                result = .failure(error)
            }
            await MainActor.run { [weak self] in
                guard let self, gen == self.generation else { return }
                self.busy = false
                switch result {
                case .success(let o):
                    self.outcome = o
                    self.remember(q)
                    if mode != .demander { self.lastContext = q }
                    if case .mot(let l) = o { self.adopt(card: l, query: q) }
                case .failure(let e):
                    self.outcome = .erreur(Issue.from(e))
                }
            }
        }
    }

    /// Works out what French term the card's sections should query.
    private func adopt(card l: Lookup, query q: String) {
        currentSource = q
        cardExamples = (l.examples ?? []).filter { $0.count >= 2 }
        if l.direction == "fr" {
            cardTerm = l.lexique?.lemma ?? l.query ?? q
            cardIsVerb = (l.lexique?.pos ?? "").contains("verbe")
                || (l.senses?.first?.pos ?? "").contains("verbe")
        } else {
            let first = l.senses?.first
            cardTerm = first?.term ?? l.translation ?? q
            cardIsVerb = (first?.pos ?? "").contains("verbe")
        }
    }

    // MARK: Sections of the Word card

    func toggle(_ section: Section) {
        if open.contains(section) {
            open.remove(section)
            return
        }
        open.insert(section)
        lastOpened = section
        guard sections[section] == nil else { return }
        load(section)
    }

    func reload(_ section: Section) {
        sections[section] = nil
        load(section)
    }

    private func load(_ section: Section) {
        let term = cardTerm
        guard !term.isEmpty else {
            sections[section] = .erreur(.plain("No French term on this card."))
            return
        }
        sections[section] = .chargement
        let gen = generation
        Task.detached(priority: .userInitiated) {
            let state: SectionState
            do {
                switch section {
                case .definitions:  state = .pret(.definition(try DicoClient.definition(term)))
                case .russe:        state = .pret(.multitran(try DicoClient.multitran(term)))
                case .exemples:     state = .pret(.examples(try DicoClient.examples(term)))
                case .conjugaison:  state = .pret(.conjugation(try DicoClient.conjugate(term)))
                }
            } catch {
                state = .erreur(Issue.from(error))
            }
            await MainActor.run { [weak self] in
                guard let self, gen == self.generation else { return }
                self.sections[section] = state
            }
        }
    }

    /// Used by `--selftest`: install a finished card, optionally with one
    /// section already expanded, without touching the CLI a second time.
    func preload(card: Lookup, query q: String,
                 section: Section? = nil, content: SectionContent? = nil) {
        outcome = .mot(card)
        adopt(card: card, query: q)
        if let s = section, let c = content {
            open = [s]
            sections[s] = .pret(c)
        }
    }

    // MARK: Ask about the current word

    /// « Listen »: the CLI downloads the Wiktionary/Commons recording (as MP3,
    /// which AppKit can play) and hands back its path.
    func speak(_ word: String) {
        let w = word.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !w.isEmpty, !speaking else { return }
        speaking = true
        Task.detached(priority: .userInitiated) {
            let outcome: (path: String?, problem: String?)
            do {
                let a = try DicoClient.audio(w)
                outcome = (a.path, a.error)
            } catch {
                outcome = (nil, (error as? LocalizedError)?.errorDescription
                                ?? error.localizedDescription)
            }
            let path = outcome.path, problem = outcome.problem
            await MainActor.run {
                self.speaking = false
                if let path, !path.isEmpty, let sound = NSSound(contentsOfFile: path, byReference: true) {
                    self.player = sound
                    sound.play()
                } else {
                    self.flash(problem ?? "no recording for \u{ab} \(w) \u{bb}")
                }
            }
        }
    }

    func askAbout(_ word: String) {
        askContext = word
        mode = .demander
        query = ""
        clearResults()
    }

    func dropAskContext() { askContext = nil }

    // MARK: Saving a sense

    /// Save the n-th sense of the current card (1-indexed), for ⌘1…⌘9.
    func saveSense(number n: Int) {
        guard case .mot(let lookup) = outcome else { return }
        if let senses = lookup.senses, n >= 1, n <= senses.count {
            save(sense: senses[n - 1], lookup: lookup)
        }
    }

    func save(sense: Sense, lookup: Lookup) {
        // For a French card, the entry to save is the head ("une maison").
        let term = sense.saveTerm ?? lookup.head ?? lookup.query ?? ""
        guard !term.isEmpty else { return }
        let sens = currentSource.isEmpty ? (lookup.query ?? term) : currentSource
        let shown = sense.front ?? term
        Task.detached(priority: .userInitiated) {
            let msg: String
            do {
                let r = try DicoClient.save(term: term, sens: sens)
                let status = r.status ?? "added"
                msg = "✓ \u{ab} \(r.saved ?? shown) \u{bb} \(status)"
            } catch {
                msg = "⚠︎ not saved — \((error as? LocalizedError)?.errorDescription ?? "error")"
            }
            await MainActor.run { [weak self] in self?.flash(msg) }
        }
    }

    // MARK: What the keyboard shortcuts drive

    /// ⌘⇧1…⌘⇧5 — switch mode, and re-run the current query in it.
    func setMode(_ m: Mode) {
        guard mode != m else { return }
        mode = m
        if !query.trimmingCharacters(in: .whitespaces).isEmpty { submit() }
    }

    /// The sections the current card offers — nil when there is no card.
    var offeredSections: [Section]? {
        guard case .mot = outcome else { return nil }
        var s: [Section] = [.definitions, .russe, .exemples]
        if cardIsVerb { s.append(.conjugaison) }
        return s
    }

    /// ⌘D / ⌘R / ⌘E / ⌘J — open (or close) a section of the Word card.
    /// Returns false when there is no card, or the card does not offer it.
    @discardableResult
    func toggleSectionShortcut(_ s: Section) -> Bool {
        guard let offered = offeredSections, offered.contains(s) else { return false }
        toggle(s)
        return true
    }

    /// ⌘L — ask the tutor about the word the card is on.
    @discardableResult
    func askAboutCurrentCard() -> Bool {
        guard case .mot = outcome, !cardTerm.isEmpty else { return false }
        askAbout(cardTerm)
        return true
    }

    /// ⌘⇧C — copy the corrected sentence of a Grammar result.
    @discardableResult
    func copyCorrected() -> Bool {
        guard case .grammaire(let g, _) = outcome,
              let c = g.corrected, !c.isEmpty else { return false }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(c, forType: .string)
        flash("✓ corrected sentence copied")
        return true
    }

    func flash(_ message: String) {
        toast = message
        toastTask?.cancel()
        toastTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard !Task.isCancelled else { return }
            await MainActor.run { self?.toast = nil }
        }
    }
}
