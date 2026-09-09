#!/usr/bin/env python3
"""dico — a small pocket dictionary: Russian/English → French.

Levels (can be combined):
    dico <word>           quick translation          (Google, default)
    dico -m <word>        + Multitran OFFLINE         (rich, ru<->fr, no internet)
    dico -d <word>        + Wiktionary AFTER transl.  (RU/EN → French)
    dico -f <fr-word>     + Wiktionary DIRECT         (the word is already French)
    dico -c <verb>        + conjugation OFFLINE       (7 tenses)
    dico -c <verb> <tense>   a single tense          (e.g. "dico -c manger present")
    dico -a <word>        + quick AI explanation      (Claude Haiku: short card)
    dico -p <word>        + IN-DEPTH explanation      (Claude Opus: study card)
    dico -s  <word>       save THIS word to the vocabulary (JSON store)
    dico --autosave on    save EVERY lookup AUTOMATICALLY (persistent setting)
    dico --forget <word>  drop a word (subtractive curation)
    dico --render         regenerate the markdown from the store
    dico -g "<sentence>"  correct a SENTENCE (offline Grammalecte) and name the rule
    dico -x "<sentence>"  x-ray: every word → lemma, tense, gender, role, meaning
    dico --mots-outils    glossed grammatical core (articles, prepositions, pronouns…)
    dico --mots-outils -s turn them into cards (front = word, back = English meaning)
    dico -mda <word>      everything at once
    dico                  interactive mode (type words in a loop)

Every French word gets a "📊 frequency · part of speech · gender" badge (Lexique
3.83, offline), and cognates/false friends are flagged ("table" stays "table",
English "pain" is flagged "also French: un pain").

The JSON store (dico_vocab.json, next to the markdown) is the SOURCE OF TRUTH:
the .md is only a view regenerated automatically, and Anki reads it directly.

Detects the source language (Russian if Cyrillic, English otherwise). NOTE: the
quick translation ONLY goes RU/EN → FR (never the other way). To understand a
FRENCH word, use -m (Multitran fr→ru), -f (Wiktionary) or -a / -p (AI).

Zero dependencies: the Python 3 standard library only.
Translation and Wiktionary need internet; Multitran and the conjugations work
offline (databases in data/). The -a option uses the Anthropic API if
ANTHROPIC_API_KEY is set (fast, ~1-2 s), otherwise the `claude` command.
"""
import argparse
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

try:
    import readline  # ↑ arrow = recall the previous command (interactive mode)
except ImportError:
    readline = None

_HERE = os.path.dirname(os.path.abspath(__file__))
DICO_HOME = os.environ.get("DICO_HOME") or os.path.expanduser("~/.dico")
# In a git checkout (data/ next to us, or a writable directory outside
# site-packages): everything stays local. Installed as a tool: ~/.dico/.
_IN_REPO = "site-packages" not in _HERE and os.path.isdir(os.path.join(_HERE, "data"))
DATA_DIR = os.environ.get("DICO_DATA") or (os.path.join(_HERE, "data") if _IN_REPO
                                           else os.path.join(DICO_HOME, "data"))
HISTFILE = os.path.expanduser("~/.dico_history")

TIMEOUT = 8

# ANSI colors (disabled when the output is not a terminal)
if sys.stdout.isatty():
    BOLD, DIM, ITAL, BLUE, GREEN, YELLOW, RED, CYAN, RESET = (
        "\033[1m", "\033[2m", "\033[3m", "\033[34m", "\033[32m",
        "\033[33m", "\033[31m", "\033[36m", "\033[0m",
    )
else:
    BOLD = DIM = ITAL = BLUE = GREEN = YELLOW = RED = CYAN = RESET = ""

CYRILLIC = re.compile(r"[Ѐ-ӿ]")
FLAG = {"ru": "🇷🇺", "en": "🇬🇧", "fr": "🇫🇷"}


def detect_lang(text):
    """Russian if the text contains Cyrillic, English otherwise."""
    return "ru" if CYRILLIC.search(text) else "en"


def _deaccent(s):
    """Strip accents (é→e, ç→c…) and lowercase — the user cannot type
    accented characters in their terminal."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower().strip()


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8")


# --------------------------------------------------------------------------- #
#  Level 1: quick translation                                                 #
# --------------------------------------------------------------------------- #
class RateLimited(Exception):
    """Google refused the query (its "Sorry… automated queries" page, served as
    a 429) — the caller falls back to another source."""


# A lookup you have already done must never cost a request again: the same word
# comes back in a lesson, and Google's free endpoint starts answering 429 after
# a burst. Cached on disk, 30 days, oldest dropped past the cap.
_TR_CACHE_PATH = os.path.join(DATA_DIR, "translate_cache.json")
_TR_CACHE_TTL = 30 * 24 * 3600
_TR_CACHE_MAX = 3000
_TR_CACHE = None
_TR_DIRTY = False


def _cache_load():
    global _TR_CACHE
    if _TR_CACHE is None:
        try:
            with open(_TR_CACHE_PATH, encoding="utf-8") as f:
                _TR_CACHE = json.load(f)
        except Exception:
            _TR_CACHE = {}
    return _TR_CACHE


def _cache_get(key):
    row = _cache_load().get(key)
    if not row or time.time() - row.get("t", 0) > _TR_CACHE_TTL:
        return None
    return row.get("v")


def _cache_put(key, value):
    global _TR_DIRTY
    _cache_load()[key] = {"t": time.time(), "v": value}
    _TR_DIRTY = True


def cache_flush():
    """Written once, at exit — a lookup must not pay for a file write."""
    global _TR_DIRTY
    if not _TR_DIRTY or _TR_CACHE is None:
        return
    try:
        rows = _TR_CACHE
        if len(rows) > _TR_CACHE_MAX:                      # drop the oldest
            keep = sorted(rows.items(), key=lambda kv: -kv[1].get("t", 0))[:_TR_CACHE_MAX]
            rows = dict(keep)
        os.makedirs(os.path.dirname(_TR_CACHE_PATH), exist_ok=True)
        tmp = _TR_CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        os.replace(tmp, _TR_CACHE_PATH)
    except Exception:
        pass
    _TR_DIRTY = False


# Google's endpoint takes a `client` parameter, and the two values behave very
# differently: `gtx` is the one every scraping snippet uses, so it is the one
# Google blocks ("Sorry… we can't process your request", HTTP 429, and it does
# not clear by waiting). `dict-chrome-ex` is what Chrome's own dictionary uses:
# same JSON shape, same dt=bd sense groups, and it answers. Try it first and
# keep gtx as the spare in case that flips round one day.
_GOOGLE_CLIENTS = ("dict-chrome-ex", "gtx")

_RL_KEY = "!google_blocked_until"
_RL_COOLDOWN = 15 * 60          # every client refused: stop asking for a while


def _rate_limited_now():
    row = _cache_load().get(_RL_KEY)
    return bool(row) and time.time() < row.get("v", 0)


def _mark_blocked():
    global _TR_DIRTY
    _cache_load()[_RL_KEY] = {"t": time.time(), "v": time.time() + _RL_COOLDOWN}
    _TR_DIRTY = True


def _google_query(word, tl="fr", sl="auto"):
    """Google's free endpoint (auto-detects the source language), raw JSON.
    Cached; a 429 is retried once, briefly, then raises RateLimited so the
    caller can fall back instead of making you wait for nothing. While the
    throttle lasts we do not even try — that is the difference between a card
    in 0.5 s and a card in 3 s."""
    ck = f"g:{sl}>{tl}:{word.strip().lower()}"
    hit = _cache_get(ck)
    if hit is not None:
        return hit
    if _rate_limited_now():
        raise RateLimited("Google refused the query")
    q = urllib.parse.quote(word)
    refused = None
    for client in _GOOGLE_CLIENTS:
        url = ("https://translate.googleapis.com/translate_a/single"
               f"?client={client}&sl={sl}&tl={tl}&dt=t&dt=bd&q={q}")
        try:
            data = json.loads(_get(url))
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            refused = e
            continue                       # this client is blocked: try the next
        _cache_put(ck, data)
        return data
    _mark_blocked()
    raise RateLimited("Google refused the query") from refused


_FALLBACK_NOTE = ""      # set when a card came from the fallback, shown once

_POS_FR = {"noun": "nom", "verb": "verbe", "adjective": "adjectif", "adverb": "adverbe",
           "preposition": "préposition", "pronoun": "pronom", "conjunction": "conjonction",
           "interjection": "interjection", "abbreviation": "abréviation",
           "article": "article", "phrase": "expression", "suffix": "suffixe",
           "auxiliary verb": "auxiliaire", "modal verb": "modal", "prefix": "préfixe"}


def translate_rich(word, tl="fr", sl="auto"):
    """(translation, detected language, senses grouped by part of speech) —
    senses = [(pos, [(term, [back-translations]), …]), …]. This is the structure
    of a real dictionary, which the old flat "also: …" line squashed.

    When Google throttles us, MyMemory still gives the translation — a card with
    one sense beats an error message in the middle of a lesson."""
    global _FALLBACK_NOTE
    try:
        data = _google_query(word, tl, sl)
    except (RateLimited, urllib.error.HTTPError, urllib.error.URLError):
        if tl != "fr":                       # FR → EN back-translation: no fallback
            raise
        src = detect_lang(word)
        tr, _, alts = translate_mymemory(word, src)
        _FALLBACK_NOTE = "Google refused the query — translation via MyMemory (fewer senses)"
        lx = lexique_lookup(tr)
        # MyMemory gives no part of speech: only the main term can claim the one
        # Lexique knows; the alternatives stay in an unlabelled group.
        groups = [((lx["pos"] if lx else ""), [(tr, [])])]
        others = [(a, []) for a in alts[:3] if a.lower() != tr.lower()]
        if others:
            groups.append(("", others))
        return tr, src, groups
    _FALLBACK_NOTE = ""
    translation = "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
    detected = data[2] if len(data) > 2 and isinstance(data[2], str) else None
    groups = []
    for entry in (data[1] or []) if len(data) > 1 else []:
        pos = _POS_FR.get(str(entry[0]).lower(), str(entry[0]).lower())
        terms = []
        for t in (entry[2] if len(entry) > 2 and entry[2] else []):
            if t and t[0]:
                terms.append((t[0], [b for b in (t[1] if len(t) > 1 else []) if b][:4]))
        if not terms and len(entry) > 1:
            terms = [(x, []) for x in entry[1] if x]
        if terms:
            groups.append((pos, terms))
    return translation, detected, groups


def translate_google(word, tl="fr"):
    """Compatibility: (translation, detected language, flat alternatives)."""
    data = _google_query(word, tl)
    translation = "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
    detected = data[2] if len(data) > 2 and isinstance(data[2], str) else None
    alts = []
    if len(data) > 1 and data[1]:
        for entry in data[1]:
            for term in (entry[1] if len(entry) > 1 else []):
                if term and term != translation and term not in alts:
                    alts.append(term)
    return translation, detected, alts[:6]


def translate_mymemory(word, src, tl="fr"):
    """Fallback: the free MyMemory API (cached like the main one)."""
    ck = f"m:{src}>{tl}:{word.strip().lower()}"
    hit = _cache_get(ck)
    if hit is not None:
        return tuple(hit)
    q = urllib.parse.quote(word)
    url = f"https://api.mymemory.translated.net/get?q={q}&langpair={src}|{tl}"
    data = json.loads(_get(url))
    translation = data["responseData"]["translatedText"].strip()
    alts = []
    for m in data.get("matches", []):
        t = (m.get("translation") or "").strip()
        if t and t.lower() != translation.lower() and t not in alts:
            alts.append(t)
    _cache_put(ck, [translation, src, alts[:6]])
    return translation, src, alts[:6]


def translate(word, tl="fr"):
    """Try Google, then MyMemory as a fallback (MyMemory: into French only)."""
    src_guess = detect_lang(word)
    try:
        return translate_google(word, tl)
    except Exception:
        if tl != "fr":
            raise
        return translate_mymemory(word, src_guess)


def _tatoeba(fr_word, to="eng", limit=1):
    """Real example sentences (Tatoeba, CC-BY): [(FR sentence, translation)].
    Cached: Tatoeba answers in 0.3 s on a good day and 2 s on a bad one, and
    that latency was landing on every single card."""
    ck = f"t:{to}:{limit}:{fr_word.strip().lower()}"
    hit = _cache_get(ck)
    if hit is not None:
        return [tuple(x) for x in hit]
    try:
        url = ("https://tatoeba.org/en/api_v0/search?from=fra&to=" + to
               + "&query=" + urllib.parse.quote(f'"{fr_word}"')
               + "&sort=relevance&limit=8&word_count_min=4&word_count_max=12")
        data = json.loads(_get(url))
    except Exception:
        return []
    out = []
    for r in data.get("results", []):
        fr = r.get("text", "")
        trs = [t for grp in r.get("translations", []) for t in grp]
        if not fr or not trs or fr_word.lower() not in fr.lower():
            continue
        out.append((fr, trs[0].get("text", "")))
        if len(out) >= limit:
            break
    _cache_put(ck, [list(x) for x in out])
    return out


_BAND_STARS = {"très courant": "★★★", "courant": "★★", "moyen": "★"}


def _lex_gender_row(word):
    """For a noun: the Lexique row WITH a gender ("maison": the most frequent
    row can be the adjective "fait maison", which has no gender)."""
    if not os.path.exists(LEXIQUE_DB):
        return None
    try:
        con = sqlite3.connect(f"file:{LEXIQUE_DB}?mode=ro", uri=True)
        row = con.execute("SELECT genre FROM lexique WHERE (ortho=? OR northo=?) AND "
                          "cgram LIKE 'NOM%' AND genre IN ('m','f') ORDER BY freqfilms DESC "
                          "LIMIT 1", (word.lower(), _deaccent(word.lower()))).fetchone()
        con.close()
        return row[0] if row else None
    except Exception:
        return None


def _fr_head(term):
    """French term → (front with its article if a noun, Lexique entry)."""
    lex = lexique_lookup(term)
    if lex and " " not in term.strip() and lex["cgram"].startswith(("NOM", "ADJ")) \
            and not lex["genre"]:
        g = _lex_gender_row(term)                 # noun with no gender → find the gendered row
        if g:
            lex = dict(lex, genre=g, article={"m": "un", "f": "une"}[g], pos="nom")
    if lex and lex["article"] and " " not in term.strip():
        return f"{lex['article']} {lex['ortho']}", lex
    return term, lex


def _render_card_to_fr(word, src, translation, groups, examples=True):
    """RU/EN → FR card: numbered senses grouped by part of speech ("save N" saves sense N)."""
    print(f"  {FLAG.get(src, '🌐')} {BOLD}{word}{RESET}")
    if _FALLBACK_NOTE:
        print(f"     {DIM}⚠ {_FALLBACK_NOTE}{RESET}")
    # The main translation (the one autosave keeps) must be sense 1.
    tmain = (translation or "").strip().lower()
    groups = [(p, list(t)) for p, t in groups]
    hit = next((i for i, (_, t) in enumerate(groups) if any(x.lower() == tmain for x, _ in t)), None)
    if hit is None and translation:
        lx = lexique_lookup(translation)
        groups.insert(0, (lx["pos"] if lx else "", [(translation, [])]))
    elif hit is not None:
        pos, terms = groups.pop(hit)
        terms.sort(key=lambda x: x[0].lower() != tmain)
        groups.insert(0, (pos, terms))
    senses, n = [], 0
    for pos, terms in groups[:4]:
        cells = []
        for term, back in terms[:4]:
            n += 1
            front, lex = _fr_head(term)
            senses.append(front)
            stars = _BAND_STARS.get(lex["band"], "") if lex else ""
            cells.append(f"{DIM}{n}{RESET} {GREEN if n == 1 else ''}{front}{RESET}"
                         + (f" {DIM}{stars}{RESET}" if stars else ""))
        back = [b for b in terms[0][1] if b.lower() != word.lower()][:2]
        tail = f"   {DIM}← {', '.join(back)}{RESET}" if back else ""
        print(f"     {DIM}{pos:10}{RESET} " + "  ".join(cells) + tail)
    _LAST["senses"] = senses
    if examples and translation:
        for fr, tr in _tatoeba(translation.split()[-1] if " " in translation else translation, "eng"):
            print(f"     {DIM}« {fr} » — {tr}{RESET}")
    _LAST["hints"] = _LAST.get("hints", 0) + 1
    if _LAST["hints"] <= 3:
        print(f"     {DIM}{_FOLLOW_HINT}{RESET}")


def _render_card_fr(word, lex, examples=True):
    """Card for a FRENCH word: pos · gender/article · frequency, then EN senses."""
    head, lex2 = _fr_head(word)
    lex = lex2 or lex
    if lex and lex["cgram"].startswith("NOM") and not lex["genre"]:
        try:                                   # Lexique has no gender ("maison") → Wiktionary
            w = wiktionary(word)
            art = ARTICLE_FOR.get((w or {}).get("gender") or "")
            if art:
                g = "m" if art == "un" else "f"
                lex = dict(lex, genre=g, article=art)
                head = f"{art} {lex['ortho']}"
        except Exception:
            pass
    bits = []
    if lex:
        bits.append(lex["pos"] + (" " + ("m." if lex["genre"] == "m" else "f.") if lex["genre"] else ""))
        if head != word:
            bits.append(head)
        bits.append(lex["band"])
        if lex.get("cefr"):
            bits.append(lex["cefr"])
    line = f"  🇫🇷 {BOLD}{word}{RESET}" + (f"   {DIM}{' · '.join(bits)}{RESET}" if bits else "")
    if lex and lex.get("ipa"):
        line += f"   {DIM}/{lex['ipa']}/{RESET}"
    print(line)
    try:
        _, _, groups = translate_rich(word, tl="en", sl="fr")   # explicit sl → grouped senses
    except Exception:
        groups = []
        try:                                   # fallback: MyMemory fr→en (1 sense)
            t, _, _ = translate_mymemory(word, "fr", tl="en")
            if t and t.lower() != word.lower():
                groups = [("", [(t, [])])]
        except Exception:
            pass
    senses = []
    for pos, terms in groups[:3]:
        line = " · ".join(t for t, _ in terms[:6])
        print(f"     {DIM}{pos:10}{RESET} {line}")
        senses.extend(t for t, _ in terms[:6])
    _LAST["senses"] = [head]
    _LAST["hints"] = _LAST.get("hints", 0) + 1
    if _LAST["hints"] <= 3:
        print(f"     {DIM}{_FOLLOW_HINT}{RESET}")
    if lex and lex["cgram"].startswith(("VER", "AUX")) and not _LAST.get("conj_shown"):
        inf, data, _ = _conj_query(lex["lemma"])
        if data and data.get("présent"):
            print(f"     {DIM}présent{RESET}    " + "  ·  ".join(data["présent"])
                  + f"   {DIM}(« conj » for the full table){RESET}")
    if examples:
        for fr, tr in _tatoeba(word, "eng"):
            print(f"     {DIM}« {fr} » — {tr}{RESET}")


# --------------------------------------------------------------------------- #
#  Level 2: Wiktionary (the full dictionary)                                  #
# --------------------------------------------------------------------------- #
GENDER = {
    "{{m}}": "nom masculin (le / un)",
    "{{f}}": "nom féminin (la / une)",
    "{{mf}}": "masculin ou féminin",
    "{{n}}": "neutre",
}


def _fr_section(wikitext):
    """Isolate the French == {{langue|fr}} == section of the wikitext."""
    m = re.search(r"==\s*\{\{langue\|fr\}\}\s*==", wikitext)
    if not m:
        return None
    rest = wikitext[m.end():]
    nxt = re.search(r"\n==\s*\{\{langue\|", rest)
    return rest[:nxt.start()] if nxt else rest


def _clean_wiki(s):
    """Strip the wiki markup, keeping only readable text."""
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)                  # {{templates}}
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)    # [[a|b]] -> b
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)             # [[a]]   -> a
    s = s.replace("'''", "").replace("''", "")            # bold / italic
    s = re.sub(r"<[^>]+>", "", s)                         # HTML tags
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ;,.")


_ETYL_LANG = {
    "la": "latin", "grc": "grec ancien", "fro": "ancien français",
    "frm": "moyen français", "gem": "germanique", "gaul": "gaulois",
    "got": "gotique", "en": "anglais", "it": "italien", "es": "espagnol",
    "de": "allemand", "ar": "arabe", "nl": "néerlandais", "pt": "portugais",
    "ru": "russe", "xno": "anglo-normand",
}


def _render_etym(s):
    """Make Wiktionary's main etymology templates readable."""
    def etyl(m):
        parts = m.group(1).split("|")
        lang = _ETYL_LANG.get(parts[0].strip(), parts[0].strip()) if parts else ""
        kw = dict(p.split("=", 1) for p in parts if "=" in p)
        pos = [p.strip() for p in parts if "=" not in p]
        mot = kw.get("mot") or (pos[2] if len(pos) > 2 else "")
        out = lang + (f" « {mot} »" if mot else "")
        return out + (f" ({kw['sens']})" if kw.get("sens") else "")
    s = re.sub(r"(?is)<ref[^>]*>.*?</ref>", "", s)       # footnotes
    s = re.sub(r"\{\{étyl\|([^{}]*)\}\}", etyl, s)
    s = re.sub(r"\{\{(?:lien|polytonique|recons)\|([^|{}]+)[^{}]*\}\}", r"\1", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)                  # other templates → dropped
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s*\b[\w-]+=[^\s,;()«»]+", "", s)        # leftover template parameters
    return re.sub(r"\s+", " ", s).strip(" ;,.")


def _etymology(sec):
    m = re.search(r"\{\{S\|étymologie[^{}]*\}\}", sec)
    if not m:
        return None
    rest = sec[m.end():]
    nxt = re.search(r"\n===? ", rest)
    block = rest[:nxt.start()] if nxt else rest
    out = []
    for line in block.splitlines():
        line = line.strip()
        if line[:1] in (":", "*", "#"):
            t = _render_etym(line.lstrip(":*# ").strip())
            if t:
                out.append(t)
    text = " ".join(out)
    return (text[:900] + "…") if len(text) > 900 else (text or None)   # asked for explicitly → (almost) whole


def _parse_wiktionary(wikitext):
    sec = _fr_section(wikitext)
    if not sec:
        return None
    head = sec.split("\n#", 1)[0]                         # before the 1st definition
    pm = re.search(r"\{\{S\|([^|}]+)\|fr", sec)
    pos = pm.group(1) if pm else None
    ipa = None
    pr = re.search(r"\{\{pron\|([^|}]+)\|", head)
    if pr:
        ipa = pr.group(1)
    gender = next((label for tag, label in GENDER.items() if tag in head), None)
    defs = []
    for line in sec.splitlines():
        if re.match(r"^#\s+\S", line):                    # "# definition" (not #* nor ##)
            d = _clean_wiki(line[1:])
            if d:
                defs.append(d)
        if len(defs) >= 3:
            break
    if not (defs or ipa or gender):
        return None
    return {"pos": pos, "ipa": ipa, "gender": gender, "defs": defs,
            "etym": _etymology(sec),
            "syn": _wikt_bullets(sec, "synonymes"),
            "homo": _wikt_bullets(sec, "homophones"),
            "ru": _wikt_translations(sec, "ru"),
            "audio": _wikt_audio_files(sec)}


def _wikt_bullets(sec, name):
    """The « * [[word]] » list under a {{S|name}} heading (synonyms, homophones)."""
    m = re.search(r"\{\{S\|" + name + r"[|}][^\n]*\n(.*?)(?=\n=|\Z)", sec, re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        if not line.startswith("*"):
            continue
        # Wiktionary writes these either as [[link]] or as {{lien|word|fr}};
        # the register tags ({{familier}}, {{vieilli}}…) come along as a note.
        words = (re.findall(r"\{\{lien\|([^|}]+)", line)
                 + re.findall(r"\[\[([^\]|#]+)", line))
        note = next((t for t in re.findall(r"\{\{(familier|vieilli|argot|soutenu|"
                                           r"populaire|rare|vulgaire)[|}]", line)), "")
        for w in words:
            w = w.strip()
            if w and not any(o["word"] == w for o in out):
                out.append({"word": w, "note": note})
    return out[:12]


def _wikt_translations(sec, lang):
    """« {{trad+|ru|кошка|tr=kóška|f}} » → [{"word", "tr", "gender"}]."""
    out = []
    for block in re.findall(r"\{\{T\|" + lang + r"\}\}([^\n]*)", sec):
        for tpl in re.findall(r"\{\{trad[+\-]?\|" + lang + r"\|([^}]+)\}\}", block):
            parts = [x.strip() for x in tpl.split("|")]
            word = parts[0]
            tr = next((x[3:] for x in parts[1:] if x.startswith("tr=")), "")
            gender = next((x for x in parts[1:] if x in ("m", "f", "n")), "")
            if word and not any(o["word"] == word for o in out):
                out.append({"word": word, "tr": tr, "gender": gender})
    return out[:10]


def _wikt_audio_files(sec):
    """Recording file names: « {{écouter|…|audio=Fr-chat.ogg}} »."""
    files = [f.strip() for f in re.findall(r"audio\s*=\s*([^|}\n]+)", sec)]
    return [f for f in dict.fromkeys(files) if f][:4]


def _wikt_fetch(title):
    """Fetch and parse the French entry for one exact Wiktionary title."""
    url = ("https://fr.wiktionary.org/w/api.php?action=parse&prop=wikitext"
           f"&format=json&formatversion=2&page={urllib.parse.quote(title)}")
    try:
        raw = json.loads(_get(url))
    except Exception:
        return None
    if "error" in raw or "parse" not in raw:
        return None
    parsed = _parse_wiktionary(raw["parse"]["wikitext"])
    if parsed:
        parsed["lemma"] = title
    return parsed


def _wikt_search_titles(word):
    """Titles whose unaccented form == the typed word ("creche" → "crèche":
    the user does not type accents)."""
    url = ("https://fr.wiktionary.org/w/api.php?action=query&list=search"
           f"&srsearch={urllib.parse.quote(word)}&srlimit=8&format=json"
           "&formatversion=2")
    try:
        hits = json.loads(_get(url))["query"]["search"]
    except Exception:
        return []
    target = _deaccent(word)
    return [h["title"] for h in hits if _deaccent(h["title"]) == target]


# Articles/determiners to skip at the head of a translation ("un cuisinier").
_FR_ARTICLES = {"un", "une", "le", "la", "les", "des", "du", "de",
                "d'", "l'", "se", "s'", "au", "aux", "à"}


def _wikt_candidates(word):
    """Variants to look up: drop the leading articles ("un cuisinier" →
    "cuisinier") and keep the head word (last word of the phrase)."""
    w = word.strip()
    cands = [w, w.lower()]
    parts = w.lower().split()
    while len(parts) > 1 and parts[0] in _FR_ARTICLES:
        parts = parts[1:]
    if parts:
        cands.append(" ".join(parts))     # without the leading articles
        cands.append(parts[-1])           # the head word (usually the noun/verb)
    return list(dict.fromkeys(c for c in cands if c))


def wiktionary(word):
    """French entry for a word. Tries the word as typed first (minus any leading
    article), then an accent-tolerant search — keeping the RICHEST entry (avoids
    "étre" for "être", or "un" for "cuisinier"). Cached, like every other
    network source."""
    ck = f"w2:{word.strip().lower()}"     # w2 = the enriched entry (syn/homo/ru/audio)
    hit = _cache_get(ck)
    if hit is not None:
        return hit
    tried = set()
    for cand in _wikt_candidates(word):
        if cand and cand not in tried:
            tried.add(cand)
            entry = _wikt_fetch(cand)
            if entry:
                _cache_put(ck, entry)
                return entry
    best = None
    for cand in _wikt_search_titles(word):
        if cand in tried:
            continue
        tried.add(cand)
        entry = _wikt_fetch(cand)
        if entry and (best is None or len(entry["defs"]) > len(best["defs"])):
            best = entry
    if best:
        _cache_put(ck, best)
    return best


AUDIO_DIR = os.path.join(DATA_DIR, "audio")


def _commons_mp3(filename):
    """The URL of a Commons recording, as MP3.

    Wikimedia stores these as .ogg/.wav — which macOS cannot play — but serves
    an MP3 transcode of every one of them, so no ffmpeg is needed anywhere."""
    api = ("https://fr.wiktionary.org/w/api.php?action=query&prop=imageinfo"
           "&iiprop=url&format=json&formatversion=2&titles="
           + urllib.parse.quote("File:" + filename))
    try:
        pages = json.loads(_get(api))["query"]["pages"]
        orig = pages[0]["imageinfo"][0]["url"].split("?")[0]
    except Exception:
        return None
    # …/commons/6/65/Fr-chat.ogg → …/commons/transcoded/6/65/Fr-chat.ogg/Fr-chat.ogg.mp3
    m = re.match(r"(https://upload\.wikimedia\.org/wikipedia/commons)/(\w/\w\w)/(.+)$", orig)
    if not m:
        return None
    base, path, name = m.groups()
    if name.lower().endswith(".mp3"):
        return orig
    return f"{base}/transcoded/{path}/{name}/{name}.mp3"


def audio_for(word):
    """(local mp3 path, error) for a French word — downloaded once, then cached."""
    try:
        entry = wiktionary(word)
    except Exception:
        entry = None
    files = (entry or {}).get("audio") or []
    if not files:
        return None, f"no recording for \u00ab {word} \u00bb on Wiktionary"
    safe = re.sub(r"[^\w.-]", "_", files[0])
    dest = os.path.join(AUDIO_DIR, safe + ".mp3")
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return dest, None
    url = _commons_mp3(files[0])
    if not url:
        return None, "could not resolve the recording"
    try:
        os.makedirs(AUDIO_DIR, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(dest + ".tmp", "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(dest + ".tmp", dest)
    except Exception as e:
        return None, str(e)
    return dest, None


def _show_audio(word):
    """« say » — play the native recording (macOS: afplay handles the MP3)."""
    path, err = audio_for(word)
    if err:
        print(f"  {DIM}🔈 {err}{RESET}")
        return None
    print(f"  🔈 {BOLD}{word}{RESET}  {DIM}(Wiktionnaire · Commons){RESET}")
    player = shutil.which("afplay") or shutil.which("ffplay")
    if not player:
        print(f"     {DIM}{path}{RESET}")
        return path
    try:
        subprocess.run([player, path] + ([] if player.endswith("afplay")
                                         else ["-nodisp", "-autoexit"]),
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"     {DIM}({e}){RESET}")
    return path


def _show_synonyms(word):
    """« syn » — synonyms and homophones, from the Wiktionnaire."""
    try:
        entry = wiktionary(word)
    except Exception:
        entry = None
    syn = (entry or {}).get("syn") or []
    homo = (entry or {}).get("homo") or []
    # Lexique settles the homophones offline and exactly (same `phon`); the
    # Wiktionnaire adds the ones it happens to list.
    known = {_deaccent(h["word"]) for h in homo}
    homo = homo + [{"word": w, "note": ""} for w in homophones(word)
                   if _deaccent(w) not in known]
    if syn:
        print(f"  {CYAN}≈ synonymes de {word}{RESET}  {_wikt_words(syn, 12)}")
    if homo:
        print(f"  {CYAN}♪ homophones{RESET}  {_wikt_words(homo, 12)}")
    if not (syn or homo):
        print(f"  {DIM}≈ no synonyms listed for « {word} »{RESET}")


def _wikt_words(items, limit=8):
    """[{"word","note"}] → « minet · greffier (familier) · matou »."""
    out = []
    for it in items[:limit]:
        out.append(it["word"] + (f" {DIM}({it['note']}){RESET}" if it.get("note") else ""))
    return " · ".join(out)


def _show_wikt(lookup_word):
    try:
        entry = wiktionary(lookup_word)
    except Exception:
        entry = None
    if entry:
        head = f"  {CYAN}📖 {entry['lemma']}{RESET}"
        if entry["ipa"]:
            head += f"  {DIM}[{entry['ipa']}]{RESET}"
        if entry["gender"]:
            head += f"  {DIM}·{RESET} {entry['gender']}"
        elif entry["pos"]:
            head += f"  {DIM}·{RESET} {entry['pos']}"
        print(head)
        for i, d in enumerate(entry["defs"], 1):
            print(f"     {DIM}{i}.{RESET} {d}")
        if entry.get("etym"):
            print(f"     {DIM}🌱 etym. {entry['etym']}{RESET}")
        if entry.get("syn"):
            print(f"     {DIM}≈ synonymes{RESET} {_wikt_words(entry['syn'])}")
        homo = entry.get("homo") or []
        known = {_deaccent(h["word"]) for h in homo}
        homo = homo + [{"word": w, "note": ""} for w in homophones(entry["lemma"])
                       if _deaccent(w) not in known]
        if homo:
            print(f"     {DIM}♪ homophones{RESET} {_wikt_words(homo)}")
        if entry.get("audio"):
            print(f"     {DIM}🔈 « say » to hear it{RESET}")
    else:
        print(f"  {DIM}📖 (no Wiktionary entry for \u00ab {lookup_word} \u00bb){RESET}")
    return entry


# --------------------------------------------------------------------------- #
#  Level 3: AI explanation (Claude CLI)                                       #
# --------------------------------------------------------------------------- #
AI_MODEL = "claude-haiku-4-5"        # fast tier (-a): short card, cheap
AI_MODEL_DEEP = "claude-opus-4-8"    # deep tier (-p): full study card


def _claude_bin():
    return shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")


def _ai_prompt(word):
    # Fast tier. We let Claude translate on its own (better than Google for
    # context/gender) instead of forcing Google's translation on it.
    return (
        "You are a French teacher for an absolute beginner who understands "
        "Russian and English.\n"
        f"They typed the word \u00ab {word} \u00bb. Give its best French translation, "
        "then a VERY SHORT card written in simple French (put the English "
        "translation in parentheses for difficult words). Format:\n"
        "1. The French translation + part of speech and gender (e.g. nom masculin "
        "→ un/le), or the conjugation if it is a verb.\n"
        "2. Pronunciation, explained simply.\n"
        "3. Two easy example sentences.\n"
        "4. The nuance against a close synonym (if useful).\n"
        "8 lines maximum. No preamble: get straight to the point. "
        "You are writing for a terminal: **bold** and \"- \" lists are welcome, no tables."
    )


def _ai_prompt_deep(word):
    # Deep tier: we ask the big model for a real study card.
    return (
        "You are an outstanding French teacher for a learner whose native language "
        "is Russian and who also speaks English.\n"
        f"Word to study: \u00ab {word} \u00bb (Russian, English or French — detect it).\n"
        "Give a COMPLETE but clear study card, written in simple French (put the "
        "English translation in parentheses for difficult words). Include:\n"
        "\u2022 The French translation(s) with gender and article (+ plural if useful).\n"
        "\u2022 Pronunciation: IPA transcription + a \"it sounds like…\" trick.\n"
        "\u2022 Register (familier / courant / soutenu) and how frequent it is.\n"
        "\u2022 3 example sentences, each richer than the last.\n"
        "\u2022 The nuance against 1 or 2 close synonyms: when to use which.\n"
        "\u2022 Traps for a Russian/English speaker (false friends, gender, pronunciation).\n"
        "\u2022 If it is a verb: its group and its conjugation in the présent.\n"
        "\u2022 A mnemonic (a Russian or English cognate if possible).\n"
        "Be pedagogical, concrete and well structured. No introductory sentence. "
        "You are writing for a terminal: **bold** and \"- \" lists; avoid tables."
    )


def _ai_via_api(prompt, api_key, model, max_tokens):
    """Direct POST to the Anthropic API — fast, zero dependencies (urllib)."""
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} ({e.read().decode('utf-8', 'replace')[:120]})"
    except Exception as e:
        return None, str(e)
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text").strip()
    return (text, None) if text else (None, "empty response")


def _ai_via_cli(prompt, model):
    """Fallback: the `claude` command (Claude Code auth, slower)."""
    bin_ = _claude_bin()
    if not bin_ or not os.path.exists(bin_):
        return None, "set ANTHROPIC_API_KEY or install the `claude` command"
    try:
        out = subprocess.run([bin_, "--model", model, "-p", prompt],
                             capture_output=True, text=True, timeout=180)
    except Exception as e:
        return None, str(e)
    text = (out.stdout or "").strip()
    if not text:
        return None, (out.stderr or "empty response").strip()
    return text, None


# --- Local / OpenAI-compatible model (LM Studio, DGX Spark, Ollama, Mistral…) ---
# Settings: DICO_LLM_URL (default http://localhost:1234/v1), DICO_LLM_MODEL,
# DICO_LLM_KEY — or in ~/.dico_config.json (llm_url / llm_model / llm_key).
def _llm_cfg():
    cfg = config_load()
    return (os.environ.get("DICO_LLM_URL") or cfg.get("llm_url") or "http://localhost:1234/v1",
            os.environ.get("DICO_LLM_MODEL") or cfg.get("llm_model") or "",
            os.environ.get("DICO_LLM_KEY") or cfg.get("llm_key") or "")


def _llm_models(url, key):
    """Models served by the endpoint (LM Studio: the loaded ones come first)."""
    req = urllib.request.Request(url.rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {key}"} if key else {})
    with urllib.request.urlopen(req, timeout=3) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [m.get("id") for m in data.get("data", []) if m.get("id")]


def _llm_openai(system, user, max_tokens):
    """POST /chat/completions (OpenAI-compatible). Returns (text, error)."""
    url, model, key = _llm_cfg()
    try:
        if not model:
            ids = _llm_models(url, key)
            if not ids:
                return None, "no model loaded (LM Studio: load a model)"
            model = ids[0]
        body = json.dumps({"model": model, "temperature": 0.3, "max_tokens": max_tokens,
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": user}]}).encode()
        hdr = {"Content-Type": "application/json"}
        if key:
            hdr["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(url.rstrip("/") + "/chat/completions", data=body,
                                     headers=hdr, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode("utf-8"))
        text = (data["choices"][0]["message"].get("content") or "").strip()
        text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S)   # "thinking" models
        return (text, None) if text else (None, "empty response")
    except urllib.error.URLError as e:
        return None, f"endpoint unreachable ({url}) — {getattr(e, 'reason', e)}"
    except Exception as e:
        return None, str(e)


def _llm_reachable():
    url, _, key = _llm_cfg()
    try:
        return bool(_llm_models(url, key))
    except Exception:
        return False


def llm_complete(system, user, max_tokens=400, deep=False):
    """1) local/OpenAI-compatible endpoint if it answers, 2) Anthropic API, 3) `claude`."""
    if config_load().get("llm") == "none":
        return None, "no tutor configured — run: dico --llm"
    if os.environ.get("DICO_LLM_URL") or config_load().get("llm_url") or _llm_reachable():
        return _llm_openai(system, user, max_tokens)
    model = AI_MODEL_DEEP if deep else AI_MODEL
    prompt = system + "\n\n" + user
    api_key = os.environ.get("ANTHROPIC_API_KEY") or config_load().get("anthropic_key")
    if api_key:
        return _ai_via_api(prompt, api_key, model, max_tokens)
    return _ai_via_cli(prompt, model)


# The tutor answers in simple French with English glosses: that is the pedagogy,
# so the language of the answer stays French even though the prompt is English.
_TUTOR_SYS = ("You are a French teacher for an adult beginner (A1→A2) whose native "
              "language is Russian and who also speaks English. ALWAYS answer in "
              "simple French, VERY short (2 to 5 lines), with an example. Put the "
              "English translation in parentheses for difficult words. No preamble, "
              "no tables; **bold** and \"- \" lists are welcome.")
_LAST = {"word": "", "fr": "", "sentence": "", "senses": []}   # context for "?" / "save N"


def ai_explain(word, deep=False):
    """Card for a word ("!a word" / "-a word")."""
    prompt = _ai_prompt_deep(word) if deep else _ai_prompt(word)
    return llm_complete(_TUTOR_SYS, prompt, 1100 if deep else 400, deep=deep)


def ai_ask(question, deep=False):
    """Free-form question to the tutor, with the last word / last sentence as context."""
    ctx = []
    if _LAST["sentence"]:
        ctx.append(f"Last sentence analysed: \u00ab {_LAST['sentence']} \u00bb.")
    if _LAST["word"]:
        ctx.append(f"Last word looked up: \u00ab {_LAST['word']} \u00bb"
                   + (f" (\u2192 \u00ab {_LAST['fr']} \u00bb)" if _LAST["fr"] else "") + ".")
    user = ("Context: " + " ".join(ctx) + "\n\n" if ctx else "") + "Question: " + question
    return llm_complete(_TUTOR_SYS, user, 700 if deep else 350, deep=deep)


def _render_md(text):
    """Small Markdown → terminal renderer (bold, italic, headings, lists, code).
    Zero dependencies; covers what Claude produces most of the time."""
    def inline(s):
        s = re.sub(r"\*\*(.+?)\*\*", BOLD + r"\1" + RESET, s)            # **bold**
        s = re.sub(r"__(.+?)__", BOLD + r"\1" + RESET, s)               # __bold__
        s = re.sub(r"`([^`]+)`", GREEN + r"\1" + RESET, s)              # `code`
        s = re.sub(r"(?<![*\w])\*(?!\s)([^*]+?)\*(?!\w)",               # *italic*
                   ITAL + r"\1" + RESET, s)
        s = re.sub(r"(?<![_\w])_(?!\s)([^_]+?)_(?!\w)",                 # _italic_
                   ITAL + r"\1" + RESET, s)
        return s

    lines = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            lines.append("")
        elif re.match(r"^\s*#{1,6}\s+", line):                          # heading
            lines.append(BOLD + CYAN + inline(re.sub(r"^\s*#{1,6}\s+", "", line)) + RESET)
        elif re.match(r"^\s*[-*•]\s+", line):                           # bullet
            lines.append("  • " + inline(re.sub(r"^\s*[-*•]\s+", "", line)))
        elif re.match(r"^\s*[-*_]{3,}\s*$", line):                      # --- rule
            lines.append(DIM + "─" * 28 + RESET)
        else:
            lines.append(inline(line))
    return lines


def _llm_label():
    url, model, _ = _llm_cfg()
    if os.environ.get("DICO_LLM_URL") or config_load().get("llm_url") or _llm_reachable():
        try:
            model = model or (_llm_models(url, _llm_cfg()[2]) or ["local model"])[0]
        except Exception:
            model = model or "local model"
        return model.split("/")[-1][:28]
    return "Claude"


def _show_ai(word, deep, question=None):
    icon = "🧠" if deep else "🤖"
    label = _llm_label()
    pad = " " * 12
    print(f"  {CYAN}{icon} {label} is thinking…{RESET}", end="\r", flush=True)
    t0 = time.time()
    text, err = (ai_ask(question, deep) if question else ai_explain(word, deep=deep))
    label += f"  {DIM}{time.time() - t0:.1f}s{RESET}{CYAN}"
    if text:
        print(f"  {CYAN}{icon} {label} :{RESET}{pad}")
        for line in _render_md(text):
            print(f"     {line}")
    else:
        print(f"  {YELLOW}{icon} AI unavailable:{RESET} {err}{pad}")


# --------------------------------------------------------------------------- #
#  Saving to the vocabulary                                                   #
# --------------------------------------------------------------------------- #
# --save target: DICO_VOCAB if set (e.g. your notes vault), otherwise local.
def _early_cfg(key):
    """Config value before config_load() exists (module import time)."""
    try:
        with open(os.path.expanduser("~/.dico_config.json"), encoding="utf-8") as f:
            return json.load(f).get(key)
    except Exception:
        return None


VOCAB = (os.environ.get("DICO_VOCAB") or _early_cfg("vocab_path")
         or os.path.join(_HERE if _IN_REPO else DICO_HOME, "vocabulaire.md"))
# -S target: the "clean" list (vocabulaire.md); otherwise the same log file.
VOCAB_MAIN = os.environ.get("DICO_VOCAB_MAIN") or VOCAB
# The TRUTH is the JSON store (next to the markdown). The .md is only a
# regenerated view of it. DICO_STORE can put it somewhere else.
STORE = os.environ.get("DICO_STORE") or _early_cfg("store_path") or os.path.join(
    os.path.dirname(os.path.abspath(VOCAB)), "dico_vocab.json")
# Persistent settings (e.g. autosave turned on once and for all).
CONFIG_PATH = os.path.expanduser("~/.dico_config.json")


def config_load():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def config_set(key, value):
    cfg = config_load()
    if value is None:
        cfg.pop(key, None)
    else:
        cfg[key] = value
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.chmod(CONFIG_PATH, 0o600)          # may hold an API key
    except OSError:
        pass
    return cfg


def _data_ready():
    return os.path.exists(LEXIQUE_DB) and os.path.exists(CONJ_DB)


_NO_AUTOSAVE = False                          # set during --tour


def autosave_on():
    return bool(config_load().get("autosave", False))


ARTICLE_FOR = {"nom masculin (le / un)": "un", "nom féminin (la / une)": "une"}


def vocab_front(french, entry=None):
    """The front to save: accented lemma + article (un/une) if it is a noun.
    Gender is the most valuable thing to learn — without it you never learn
    le/la!"""
    front = (entry.get("lemma") if entry else None) or french
    if entry:
        art = ARTICLE_FOR.get(entry.get("gender") or "")
        if art:
            front = f"{art} {front}"
    return front


# --- The JSON store: the single source of truth ---------------------------- #
def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def store_key(text):
    """Dedup key: no leading article, no accents, lowercase."""
    parts = (text or "").strip().lower().split()
    while len(parts) > 1 and parts[0] in _FR_ARTICLES:
        parts = parts[1:]
    return _deaccent(" ".join(parts))


def _md_rows(path):
    """Read the rows of a markdown table → [(word, meaning, example), …]."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return out
    for ln in lines:
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 2:
            continue
        mot, sens = cells[0], cells[1]
        ex = cells[2] if len(cells) > 2 else ""
        if not mot or mot.lower() in ("mot", "word") or set(mot) <= set("-: "):
            continue
        out.append((mot, sens, ex))
    return out


def _seed_entries():
    """One-off migration: pull the old markdown log into the store."""
    now, seen, entries = _now_iso(), set(), []
    for mot, sens, ex in _md_rows(VOCAB):
        k = store_key(mot)
        if not k or k in seen:
            continue
        seen.add(k)
        entries.append({
            "key": k, "front": mot, "lemma": mot.split()[-1], "sens": sens,
            "pos": "", "gender": "", "example": ex, "src_word": "",
            "src_lang": "", "tier": "import",
            "first_seen": now, "last_seen": now, "count": 1})
    return entries


def store_load():
    try:
        with open(STORE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data.get("entries"), list):
            return {"version": 1, "entries": data["entries"]}
    except (OSError, ValueError):
        pass
    data = {"version": 1, "entries": _seed_entries()}     # first run: migrate
    if data["entries"]:
        store_save(data)                                  # make the migration stick
    return data


def store_save(data):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(STORE)), exist_ok=True)
        with open(STORE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"  {YELLOW}💾 store not writable:{RESET} {e}")


_STORE_FIELDS = ("front", "lemma", "sens", "pos", "gender", "example",
                 "src_word", "src_lang", "tier")


def store_upsert(record):
    """Add or update a word. Returns (status, count)."""
    data = store_load()
    now = _now_iso()
    for e in data["entries"]:
        if e.get("key") == record["key"]:
            e["count"] = e.get("count", 1) + 1
            e["last_seen"] = now
            for k in _STORE_FIELDS:           # fill the gaps, never overwrite
                if not e.get(k) and record.get(k):
                    e[k] = record[k]
            store_save(data)
            store_render()
            return "seen before", e["count"]
    rec = {k: record.get(k, "") for k in _STORE_FIELDS}
    rec.update(key=record["key"], count=1, first_seen=now, last_seen=now)
    data["entries"].append(rec)
    store_save(data)
    store_render()
    return "added", 1


def store_forget(word):
    data = store_load()
    k = store_key(word)
    before = len(data["entries"])
    data["entries"] = [e for e in data["entries"] if e.get("key") != k]
    store_save(data)
    store_render()
    return before - len(data["entries"])


def store_render(path=None):
    """Regenerate the markdown view from the store (most recently seen first)."""
    path = path or VOCAB
    entries = sorted(store_load()["entries"],
                     key=lambda e: e.get("last_seen", ""), reverse=True)
    head = [
        "# 🔎 dico words",
        "",
        f"*{len(entries)} words — generated automatically from "
        "`dico_vocab.json` (the source of truth). **Do not edit by hand**: "
        "it is regenerated on every lookup. Everything you look up lands here. "
        "To drop one: `dico --forget <word>`.*",
        "",
        "| Word | Meaning | Example | Seen |",
        "|------|---------|---------|------|",
    ]
    for e in entries:
        mot = e.get("front") or e.get("lemma") or ""
        cnt = e.get("count", 1)
        head.append(f"| {mot} | {e.get('sens','')} | {e.get('example','')} | "
                    f"{('×' + str(cnt)) if cnt > 1 else ''} |")
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(head) + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
#  Level 4: offline Multitran (local SQLite database)                         #
# --------------------------------------------------------------------------- #
MULTI_DB = os.path.join(DATA_DIR, "multitran.db")


def clean_multitran(body):
    """Turn the HTML body of a Multitran entry into readable lines."""
    s = body.replace("\\n", "\n")
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</?p\b[^>]*>", "\n", s)      # paragraph start AND end
    s = re.sub(r"(?i)<h1>.*?</h1>", "", s)        # headword, already known
    s = re.sub(r"<[^>]+>", "", s)                 # any other tag
    s = html.unescape(s)
    lines = []
    for ln in s.splitlines():
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if ln:
            lines.append(ln)
    return lines


def _mt_text(fragment):
    """HTML fragment → text, keeping Multitran's blue notes as ⟨…⟩ markers."""
    s = re.sub(r'(?is)<i><font color="blue">(.*?)</font></i>', lambda m: "⟨" + m.group(1) + "⟩", fragment)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def _mt_split(text):
    """« a ⟨note⟩, b, c (x, y) » → [{"tr": "a", "note": "note"}, {"tr": "b"}, …] —
    split on commas that are outside (…) and ⟨…⟩."""
    items, buf, depth = [], "", 0
    for ch in text:
        if ch in "(⟨":
            depth += 1
        elif ch in ")⟩":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            items.append(buf); buf = ""
        else:
            buf += ch
    items.append(buf)
    out = []
    for it in items:
        it = it.strip(" ;")
        if not it:
            continue
        notes = re.findall(r"⟨(.*?)⟩", it)
        tr = re.sub(r"⟨.*?⟩", "", it).strip(" ,;")
        d = {"tr": tr}
        if notes:
            d["note"] = " ".join(n.strip("() ") for n in notes)
        if tr or notes:
            out.append(d)
    return out


def multitran_structured(word):
    """Multitran entry as data: [{"pos": "гл.", "senses": [{"n": "1)", "domain": "общ.",
    "items": [{"tr": "…", "note": "…"}]}]}] — for the popup. Direction like multitran_lookup."""
    direction = "rufr" if detect_lang(word) == "ru" else "frru"
    if not os.path.exists(MULTI_DB):
        return [], direction
    key = word.strip().lower()
    try:
        con = sqlite3.connect(f"file:{MULTI_DB}?mode=ro", uri=True)
        row = con.execute("SELECT body FROM entries WHERE key=? AND dir=? LIMIT 1",
                          (key, direction)).fetchone()
        if row is None:
            row = con.execute("SELECT body FROM entries WHERE nkey=? AND dir=? LIMIT 1",
                              (_deaccent(key), direction)).fetchone()
        con.close()
    except Exception:
        return [], direction
    if not row:
        return [], direction
    body = row[0].replace("\\n", "\n")
    groups = []
    # POS groups: <b>1.</b> <i class="p">…teal…POS…</i> then <p>…</p> senses until next <b>N.</b>
    parts = re.split(r"(?is)<b>\s*\d+\.\s*</b>", body)
    for part in parts[1:]:
        mpos = re.search(r'(?is)<i class="p">.*?<font color="teal">(.*?)</font>', part)
        pos = _mt_text(mpos.group(1)) if mpos else ""
        senses = []
        for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", part):
            mn = re.match(r"\s*(\d+\))\s*", p)
            n = mn.group(1) if mn else ""
            p2 = p[mn.end():] if mn else p
            md = re.match(r'(?is)\s*<i class="p">.*?<font color="green">(.*?)</font>\s*</font>\s*</i>\s*', p2)
            domain = _mt_text(md.group(1)) if md else ""
            rest = p2[md.end():] if md else p2
            senses.append({"n": n, "domain": domain, "items": _mt_split(_mt_text(rest))})
        if senses:
            groups.append({"pos": pos, "senses": senses})
    return groups, direction


def multitran_lookup(word):
    """Look a word up in offline Multitran. Cyrillic → ru-fr, else fr-ru.
    Accent-tolerant through the nkey column. Returns (lines, direction, error)."""
    direction = "rufr" if detect_lang(word) == "ru" else "frru"
    if not os.path.exists(MULTI_DB):
        return None, direction, "Multitran not installed (optional: needs the Apple dictionaries, see README)"
    key = word.strip().lower()
    nkey = _deaccent(key)
    try:
        con = sqlite3.connect(f"file:{MULTI_DB}?mode=ro", uri=True)
        row = con.execute(
            "SELECT body FROM entries WHERE key=? AND dir=? LIMIT 1",
            (key, direction)).fetchone()
        if row is None and nkey != key:           # accents: cafe → café
            try:
                row = con.execute(
                    "SELECT body FROM entries WHERE nkey=? AND dir=? LIMIT 1",
                    (nkey, direction)).fetchone()
            except sqlite3.OperationalError:
                pass                              # database without nkey → rebuild it
        con.close()
    except Exception as e:
        return None, direction, str(e)
    if not row:
        return None, direction, None
    return clean_multitran(row[0]), direction, None


# --------------------------------------------------------------------------- #
#  Level 5: offline conjugation (local SQLite database)                       #
# --------------------------------------------------------------------------- #
CONJ_DB = os.path.join(DATA_DIR, "conjugations.db")


def _conj_query(verb):
    if not os.path.exists(CONJ_DB):
        return None, None, "conjugation data not built — run: dico --setup"
    try:
        con = sqlite3.connect(f"file:{CONJ_DB}?mode=ro", uri=True)
        row = con.execute("SELECT verb, data FROM verbs WHERE verb=? LIMIT 1",
                          (verb,)).fetchone()
        if row is None:                       # typed without accents? (etudier→étudier)
            con.create_function("noacc", 1, _deaccent, deterministic=True)
            row = con.execute(
                "SELECT verb, data FROM verbs WHERE noacc(verb)=? LIMIT 1",
                (_deaccent(verb),)).fetchone()
        con.close()
    except Exception as e:
        return None, None, str(e)
    if not row:
        return None, None, None
    return row[0], json.loads(row[1]), None


def _form_to_infinitive(word):
    """Conjugated form → infinitive, offline ("doit" → "devoir"). Returns None
    if the `forms` table is missing (old database) or the word is unknown."""
    if not os.path.exists(CONJ_DB):
        return None
    nform = _deaccent(word.strip().lower())
    if not nform:
        return None
    try:
        con = sqlite3.connect(f"file:{CONJ_DB}?mode=ro", uri=True)
        rows = con.execute(
            "SELECT verb FROM forms WHERE nform=? LIMIT 12", (nform,)).fetchall()
        con.close()
    except Exception:                         # `forms` table missing / SQLite failed
        return None
    if not rows:
        return None
    # ambiguous ("suis" → être/suivre): keep the shortest infinitive, which is
    # usually the most common one.
    return min((r[0] for r in rows), key=len)


def conjugate_lookup(word):
    """Find the French infinitive, then its conjugations. Tries: (1) the word as
    typed, (2) as a conjugated form ("doit" → "devoir", offline), (3) through a
    translation. Returns (infinitive, tenses, error, came_from_french)."""
    w = word.strip().lower()
    real, data, err = _conj_query(w)
    if data:
        return real, data, None, True
    if err:                                   # database missing / SQLite error
        return None, None, err, False
    inf = _form_to_infinitive(w)              # a conjugated form? (offline)
    if inf:
        real, data, _ = _conj_query(inf)
        if data:
            return real, data, None, True
    try:                                      # not found → try a translation
        translation, _, _ = translate(word)
    except Exception:
        return None, None, None, False
    parts = (translation or "").strip().lower().split()
    if parts:
        cand = parts[0]
        real, data, _ = _conj_query(cand)
        if not data:
            inf = _form_to_infinitive(cand)   # translation is a conjugated form? (doit → devoir)
            if inf:
                real, data, _ = _conj_query(inf)
        if data:
            return real, data, None, False    # came from a translation (foreign word)
    return None, None, None, False


# Tense asked for after the verb: "dico -c manger present" / "conj manger futur".
TENSE_ALIASES = {
    "present": "présent", "pres": "présent",
    "passe": "passé composé", "pc": "passé composé", "passecompose": "passé composé",
    "imparfait": "imparfait", "imp": "imparfait",
    "futur": "futur simple", "fut": "futur simple", "futursimple": "futur simple",
    "conditionnel": "conditionnel", "cond": "conditionnel",
    "subjonctif": "subjonctif", "subj": "subjonctif", "sub": "subjonctif",
    "imperatif": "impératif", "imper": "impératif",
}


def _norm_tense(s):
    return TENSE_ALIASES.get(_deaccent(s or "").replace(" ", "")) if s else None


def _split_tense(word):
    """"manger present" or "present manger" → ("manger", "présent")."""
    parts = word.split()
    if len(parts) >= 2:
        t = _norm_tense(parts[-1])
        if t:
            return " ".join(parts[:-1]), t
        t = _norm_tense(parts[0])
        if t:
            return " ".join(parts[1:]), t
    return word, None


# --- Conjugation table: pronoun × tense grid (readable at a glance) --------- #
_CONJ_PERSONS = ["je", "tu", "il", "nous", "vous", "ils"]
_CONJ_IMP = {0: 1, 1: 3, 2: 4}              # impératif (tu/nous/vous) → rows 1,3,4
_CONJ_SUBJ = ("je", "j'", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles")
_CONJ_SHORT = {
    "présent": "prés.", "passé composé": "passé c.", "imparfait": "imparf.",
    "futur simple": "futur", "conditionnel": "cond.", "subjonctif": "subj.",
    "impératif": "impér.",
}


def _bare_form(form):
    """"je doive" / "qu'il doive" / "j'ai dû" → the form without its subject pronoun."""
    s = form.strip()
    low = s.lower()
    if low.startswith("que "):
        s = s[4:].strip()
    elif low.startswith("qu'"):
        s = s[3:].strip()
    low = s.lower()
    for p in _CONJ_SUBJ:
        if p.endswith("'") and low.startswith(p):
            return s[len(p):].strip()
        if not p.endswith("'") and low.startswith(p + " "):
            return s[len(p) + 1:].strip()
    return s                                  # impératif ("éteins"): no pronoun


def _conj_lines(shown):
    """Colored lines of a pronoun × tense grid, from {tense: [forms]}."""
    tenses = list(shown.keys())
    cells = [["" for _ in tenses] for _ in _CONJ_PERSONS]
    for ti, t in enumerate(tenses):
        forms = shown[t]
        if len(forms) == 3:                   # impératif
            for fi, pi in _CONJ_IMP.items():
                if fi < len(forms):
                    cells[pi][ti] = _bare_form(forms[fi])
        else:
            for pi in range(min(len(forms), 6)):
                cells[pi][ti] = _bare_form(forms[pi])
    headers = [_CONJ_SHORT.get(t, t) for t in tenses]
    widths = [max([len(headers[ti])] + [len(cells[pi][ti]) for pi in range(6)])
              for ti in range(len(tenses))]
    pw = max(len(p) for p in _CONJ_PERSONS)
    pres = tenses.index("présent") if "présent" in tenses else -1
    # header: the présent stands out (bold), the rest is dimmed
    hparts = [(f"{RESET}{BOLD}{h.ljust(widths[i])}{RESET}{DIM}" if i == pres
               else h.ljust(widths[i])) for i, h in enumerate(headers)]
    out = [f"{DIM}{' ' * pw}   " + "  ".join(hparts).rstrip() + RESET]
    for pi, p in enumerate(_CONJ_PERSONS):
        parts = [(f"{BOLD}{GREEN}{cells[pi][ti].ljust(widths[ti])}{RESET}"
                  if ti == pres else cells[pi][ti].ljust(widths[ti]))
                 for ti in range(len(tenses))]
        out.append(f"{DIM}{p.ljust(pw)}{RESET}   " + "  ".join(parts).rstrip())
    return out


# --------------------------------------------------------------------------- #
#  Level 6: offline Lexique 3.83 (lemma, pos, gender, frequency)              #
# --------------------------------------------------------------------------- #
LEXIQUE_DB = os.path.join(DATA_DIR, "lexique.db")

_CGRAM_LABEL = {
    "NOM": "nom", "VER": "verbe", "ADJ": "adjectif", "ADV": "adverbe",
    "PRE": "préposition", "CON": "conjonction", "AUX": "auxiliaire",
    "ART:def": "article défini", "ART:ind": "article indéfini",
    "PRO:per": "pronom personnel", "PRO:dem": "pronom démonstratif",
    "PRO:pos": "pronom possessif", "PRO:ind": "pronom indéfini",
    "PRO:rel": "pronom relatif", "ONO": "onomatopée", "LIA": "liaison",
}

# Closed classes = the "mots-outils" (the grammatical glue you cannot guess).
MOTS_OUTILS_CGRAM = ("ART:def", "ART:ind", "PRE", "CON", "AUX",
                     "PRO:per", "PRO:dem", "PRO:pos", "PRO:ind", "PRO:rel")


def _cgram_label(cgram):
    return _CGRAM_LABEL.get(cgram, (cgram or "").lower())


def _freq_band(ff):
    """freqfilms2 = occurrences per million (subtitles). → readable band label."""
    if ff >= 500:
        return "très courant"
    if ff >= 50:
        return "courant"
    if ff >= 5:
        return "moyen"
    if ff >= 0.5:
        return "peu courant"
    return "rare"


def lexique_lookup(word):
    """Offline: a surface form (even unaccented) → its best Lexique record (the
    most frequent one, to resolve homographs: "doit" → devoir, "de" →
    préposition). Returns a dict or None."""
    if not os.path.exists(LEXIQUE_DB):
        return None
    w = (word or "").strip().lower()
    if not w:
        return None
    cols = ("ortho,lemme,cgram,genre,nombre,freqfilms,freqlivres,"
            "phon,syll,nbsyll,nbhomoph")
    try:
        con = sqlite3.connect(f"file:{LEXIQUE_DB}?mode=ro", uri=True)
        rows = con.execute(f"SELECT {cols} FROM lexique WHERE ortho=? "
                           "ORDER BY freqfilms DESC LIMIT 1", (w,)).fetchone()
        if rows is None:                      # typed without accents: etre → être
            rows = con.execute(f"SELECT {cols} FROM lexique WHERE northo=? "
                               "ORDER BY freqfilms DESC LIMIT 1",
                               (_deaccent(w),)).fetchone()
        con.close()
    except Exception:
        return None
    if not rows:
        return None
    ortho, lemme, cgram, genre, nombre, ff, fl, phon, syll, nbsyll, nbhomoph = rows
    article = None
    if (cgram or "").startswith("NOM"):
        article = {"m": "un", "f": "une"}.get(genre)
    return {"ortho": ortho, "lemma": lemme, "cgram": cgram,
            "pos": _cgram_label(cgram), "genre": genre or None,
            "nombre": nombre or None, "freqfilms": ff, "freqlivres": fl,
            "article": article, "band": _freq_band(ff),
            "phon": phon or "", "ipa": sampa_to_ipa(phon or ""),
            "syll": sampa_to_ipa(syll or ""), "nbsyll": nbsyll or 0,
            "nbhomoph": nbhomoph or 0,
            "cefr": cefr_level(lemme or ortho, cgram)}


# Lexique writes pronunciations in its own SAMPA-like alphabet ("vER" = /vɛʁ/).
# The table below turns it into IPA — offline, for every one of the 142 000
# forms, so a word has a pronunciation even when Wiktionary has no recording.
_SAMPA_IPA = {"A": "ɑ", "E": "ɛ", "O": "ɔ", "9": "œ", "2": "ø", "°": "ə",
              "@": "ɑ̃", "§": "ɔ̃", "5": "ɛ̃", "1": "œ̃", "S": "ʃ", "Z": "ʒ",
              "N": "ŋ", "J": "ɲ", "R": "ʁ", "8": "ɥ", "y": "y", "j": "j",
              "w": "w", "g": "ɡ", "x": "x"}


def sampa_to_ipa(phon):
    return "".join(_SAMPA_IPA.get(c, c) for c in phon)


def cefr_level(lemma, cgram=None):
    """A1…C2 from FLELex — the level at which a learner is expected to meet the
    word (a different question from how frequent it is for a native)."""
    if not lemma or not os.path.exists(LEXIQUE_DB):
        return None
    try:
        con = sqlite3.connect(f"file:{LEXIQUE_DB}?mode=ro", uri=True)
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                           "AND name='cefr'").fetchone():
            con.close()
            return None
        w = lemma.strip().lower()
        row = None
        if cgram:
            row = con.execute("SELECT level FROM cefr WHERE nlemma=? AND cgram=? "
                              "ORDER BY freq DESC LIMIT 1",
                              (_deaccent(w), (cgram or "")[:3])).fetchone()
        if row is None:
            row = con.execute("SELECT level FROM cefr WHERE nlemma=? "
                              "ORDER BY freq DESC LIMIT 1", (_deaccent(w),)).fetchone()
        con.close()
    except Exception:
        return None
    return row[0] if row else None


def homophones(word, limit=10):
    """Offline homophones: every other spelling with the same Lexique `phon`
    (vert → vair · ver · verre · vers). Beats a network lookup, and it is exact."""
    if not os.path.exists(LEXIQUE_DB):
        return []
    lex = lexique_lookup(word)
    if not lex or not lex.get("phon"):
        return []
    try:
        con = sqlite3.connect(f"file:{LEXIQUE_DB}?mode=ro", uri=True)
        rows = con.execute(
            "SELECT ortho, lemme, max(freqfilms) f FROM lexique WHERE phon=? "
            "GROUP BY ortho ORDER BY f DESC", (lex["phon"],)).fetchall()
        con.close()
    except Exception:
        return []
    # « verts » is not a homophone of « vert », it is the same word: drop
    # everything that shares its lemma.
    mine = _deaccent(lex.get("lemma") or lex["ortho"])
    me = _deaccent(lex["ortho"])
    return [o for o, lem, _ in rows
            if _deaccent(o) != me and _deaccent(lem or o) != mine][:limit]


# English gloss (+ a usage hint for the trickiest ones) for the function words.
# A closed set → a hand-written table, correct and offline. Used to display
# "--mots-outils" and to turn them into cards ("--mots-outils -s").
MOTS_OUTILS_GLOSS = {
    # determiners / articles
    "le": "the (m.)", "la": "the (f.)", "les": "the (pl.)", "l'": "the (+ voyelle)",
    "un": "a / one (m.)", "une": "a / one (f.)", "des": "some / (of) the (pl.)",
    "du": "some / of the (m.)", "ce": "this/that (m.); it (ce + être)",
    "cet": "this/that (m., + voyelle)", "cette": "this / that (f.)",
    "ces": "these / those", "mon": "my (m.)", "ma": "my (f.)", "mes": "my (pl.)",
    "ton": "your (m., informel)", "ta": "your (f.)", "tes": "your (pl.)",
    "son": "his/her/its (m.)", "sa": "his/her/its (f.)", "ses": "his/her/its (pl.)",
    "notre": "our", "nos": "our (pl.)", "votre": "your (poli/pl.)", "vos": "your (pl.)",
    "leurs": "their (pl.)", "quel": "which / what (m.)", "quelle": "which / what (f.)",
    "tout": "all / every / everything", "toute": "all / every (f.)", "chaque": "each",
    "plusieurs": "several", "quelque": "some / a few", "aucun": "no / none",
    "même": "same / even", "autre": "other",
    # prepositions
    "de": "of / from", "d'": "of / from (+ voyelle)", "à": "to / at / in",
    "au": "to the / at the (à + le)", "aux": "to the (à + les, pl.)",
    "pour": "for / (in order) to", "dans": "in / inside", "sur": "on / about",
    "sous": "under", "avec": "with", "sans": "without", "par": "by / through / per",
    "chez": "at (someone's) place", "vers": "towards / around (heure)",
    "entre": "between", "contre": "against", "depuis": "since / for (durée)",
    "pendant": "during", "avant": "before", "après": "after", "devant": "in front of",
    "derrière": "behind", "jusque": "until / up to", "jusqu'": "until (+ voyelle)",
    "selon": "according to", "malgré": "despite", "parmi": "among",
    "dès": "from / as early as", "hors": "outside / except", "envers": "towards (sentiment)",
    # conjunctions
    "et": "and", "ou": "or", "mais": "but", "donc": "so / therefore",
    "car": "because / for", "ni": "nor / neither", "or": "now / yet (récit)",
    "que": "that / than (conj.); whom / which (rel., objet)", "comme": "as / like / since",
    "quand": "when", "si": "if / whether", "lorsque": "when", "puisque": "since (cause)",
    "quoique": "although",
    # personal pronouns
    "je": "I", "tu": "you (sg., informel)", "il": "he / it", "elle": "she / it",
    "on": "one / we (informel)", "nous": "we / us", "vous": "you (poli / pl.)",
    "ils": "they (m.)", "elles": "they (f.)", "me": "me / to me",
    "m'": "me (+ voyelle)", "te": "you / to you", "t'": "you (+ voyelle)",
    "se": "oneself (réfléchi)", "s'": "oneself (+ voyelle)", "lui": "(to) him / her",
    "moi": "me (accentué)", "toi": "you (accentué)", "soi": "oneself (accentué)",
    "eux": "them (m., accentué)", "leur": "(to) them; their",
    "y": "there / to it  (remplace à + chose)",
    "en": "in / by (prép.); of it / some  (pron. : remplace de + nom)",
    # demonstratives
    "ça": "that / it (informel)", "c'": "it / this (c' + est)", "cela": "that",
    "ceci": "this", "celui": "the one (m.)", "celle": "the one (f.)",
    "ceux": "the ones (m.pl.)", "celles": "the ones (f.pl.)",
    # relatives / interrogatives
    "qui": "who / which (sujet); whom (après prép.)", "dont": "whose / of which / about which",
    "où": "where / when (temps)", "lequel": "which one (m.)", "laquelle": "which one (f.)",
    "quoi": "what (après prép. / seul)",
    # indefinites
    "rien": "nothing", "personne": "no one / anyone", "chacun": "each one",
    # auxiliaries
    "avoir": "to have (auxiliaire du passé composé)",
    "être": "to be (auxiliaire; + verbes de mouvement/pronominaux)",
}


def mots_outils(limit=120):
    """Top function words (closed classes) by frequency, deduplicated by lemma.
    → [(lemma, cgram, freqfilms)]. This is the grammatical scaffolding to learn."""
    if not os.path.exists(LEXIQUE_DB):
        return []
    qs = ",".join("?" * len(MOTS_OUTILS_CGRAM))
    try:
        con = sqlite3.connect(f"file:{LEXIQUE_DB}?mode=ro", uri=True)
        rows = con.execute(
            f"SELECT lemme, cgram, MAX(freqfilms) f FROM lexique "
            f"WHERE cgram IN ({qs}) GROUP BY lemme "
            f"ORDER BY f DESC LIMIT ?", (*MOTS_OUTILS_CGRAM, limit)).fetchall()
        con.close()
    except Exception:
        return []
    return rows


def show_mots_outils(limit=120, save=False):
    """Show the core function words (word — meaning), grouped by category.
    With save=True, add the ones that have a gloss to the vocabulary (→ cards)."""
    rows = mots_outils(limit)
    if not rows:
        print(f"{YELLOW}Lexique not built — run: dico --setup{RESET}")
        return
    groups = {}
    for lemme, cgram, f in rows:
        groups.setdefault(_cgram_label(cgram), []).append(lemme)
    order = ["article défini", "article indéfini", "préposition", "conjonction",
             "pronom personnel", "pronom démonstratif", "pronom possessif",
             "pronom indéfini", "pronom relatif", "auxiliaire"]
    print(f"{BOLD}🧩 Core function words{RESET} {DIM}(the {len(rows)} most "
          f"frequent — the grammatical glue){RESET}\n")
    saved = 0
    for label in order:
        words = groups.get(label)
        if not words:
            continue
        print(f"  {CYAN}{label}{RESET}")
        width = max(len(w) for w in words)
        for w in words:
            gloss = MOTS_OUTILS_GLOSS.get(w, "")
            tail = f"  {DIM}—{RESET} {gloss}" if gloss else ""
            print(f"     {w.ljust(width)}{tail}")
            if save and gloss:
                store_upsert({"key": store_key(w), "front": w, "lemma": w,
                              "sens": gloss, "pos": label, "gender": "",
                              "example": "", "src_word": w, "src_lang": "fr",
                              "tier": "mots-outils"})
                saved += 1
        print()
    if save:
        print(f"  {GREEN}💾 {saved} function words added to the vocabulary "
              f"(→ Anki){RESET}")
    else:
        print(f"  {DIM}tip: \u00ab dico --mots-outils {limit} -s \u00bb adds them "
              f"to your cards.{RESET}")




# --------------------------------------------------------------------------- #
#  X-ray: sentence analysis (Lexique + conjugations, spaCy optional)          #
# --------------------------------------------------------------------------- #
XRAY_SPACY = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "tools", "xray_spacy.py")
_PERSON_LABEL = ["je", "tu", "il/elle", "nous", "vous", "ils/elles"]
_DEP_FR = {
    "nsubj": "sujet", "nsubj:pass": "sujet", "obj": "COD", "iobj": "COI",
    "obl": "complément", "obl:arg": "complément", "obl:mod": "complément",
    "ROOT": "verbe principal", "root": "verbe principal", "det": "déterminant",
    "case": "préposition", "amod": "adjectif", "advmod": "adverbe", "cc": "coord.",
    "conj": "coordonné", "mark": "subordonnant", "aux": "auxiliaire",
    "aux:tense": "auxiliaire", "aux:pass": "auxiliaire", "cop": "copule",
    "nmod": "compl. du nom", "xcomp": "compl. verbal", "ccomp": "compl. verbal",
    "expl": "explétif", "expl:subj": "sujet", "fixed": "locution", "flat": "nom propre",
    "flat:name": "nom propre", "appos": "apposition", "acl": "relative",
    "acl:relcl": "relative", "punct": "", "dep": "",
}
_SPACY_POS_FR = {
    "PRON": "pronom", "PROPN": "nom propre", "VERB": "verbe", "NOUN": "nom",
    "ADJ": "adjectif", "ADV": "adverbe", "ADP": "préposition", "DET": "déterminant",
    "CCONJ": "conjonction", "SCONJ": "conjonction", "AUX": "auxiliaire",
    "NUM": "nombre", "INTJ": "interjection", "PART": "particule", "SYM": "symbole",
}
_ELISION_GLOSS = {"j'": "je (+ voyelle) = I", "qu'": "que (+ voyelle)",
                  "n'": "ne (+ voyelle) : ne… pas", "ne": "not (ne… pas, 1re partie)",
                  "pas": "not (ne… pas, 2e partie)"}


_CLITICS = r"(moi|toi|nous|vous|le|la|les|lui|leur|y|en|ce|il|elle|ils|elles|on|je|tu)"


def _xray_tokens(sentence):
    """Simple tokenizer: splits elisions (j'habite → j' + habite) and attached
    pronouns (tiens-moi → tiens + moi), without breaking Saint-Pétersbourg."""
    s = re.sub(r"(?i)\b(j|l|d|m|n|t|s|c|qu)['’]", lambda m: m.group(1) + "' ", sentence)
    s = re.sub(r"(?i)(\w)-" + _CLITICS + r"\b", r"\1 \2", s)
    toks = []
    for raw in s.split():
        w = raw.strip(".,;:!?…«»\"()[]")
        if w:
            toks.append(w)
    # "j habitais" typed without the apostrophe → j' (elision before a vowel / h)
    for i in range(len(toks) - 1):
        if toks[i].lower() in ("j", "l", "d", "m", "n", "t", "s", "c", "qu") \
                and toks[i + 1][:1].lower() in "aeiouyhàâéèêëîïôûùœ":
            toks[i] += "'"
    return toks


def _conj_tense_of(inf, form):
    """Which tense(s) / person(s) does "form" belong to for "inf"?
    → compact text ("présent · je/tu · impératif · tu") or None. Matches exactly
    first (mangé != mange); unaccented only if you typed no accents. The past
    participle is tolerant of agreement (partie/partis → parti)."""
    _, data, _ = _conj_query(inf)
    if not data:
        return None
    f = form.lower()
    typed_plain = _deaccent(f) == f            # typed without accents → be lenient
    hits = {}                                  # tense → [persons]
    for tense, forms in data.items():
        for i, full in enumerate(forms):
            bare = _bare_form(full).lower()
            if tense == "passé composé":
                pp = bare.split()[-1]
                if f.rstrip("s").rstrip("e") == pp or (
                        typed_plain and _deaccent(f).rstrip("s").rstrip("e") == _deaccent(pp)):
                    hits.setdefault("participe passé", [])
                break
            same = bare == f or (typed_plain and _deaccent(bare) == f)
            if same:
                pi = _CONJ_IMP.get(i, i) if tense == "impératif" else i
                if pi < 6:
                    hits.setdefault(tense, []).append(_PERSON_LABEL[pi])
    if not hits:
        return None
    parts = []
    for tense, who in hits.items():
        parts.append(tense + (" · " + "/".join(who) if who else ""))
    return " ; ".join(parts)


def _spacy_tokens(sentence):
    """spaCy analysis through the sidecar (uv). None if unavailable / disabled."""
    if not config_load().get("xray_spacy", True):
        return None
    if not (shutil.which("uv") and os.path.exists(XRAY_SPACY)):
        return None
    try:
        r = subprocess.run(["uv", "run", "--quiet", XRAY_SPACY, sentence],
                           capture_output=True, text=True, timeout=120)
        out = r.stdout
        i = out.find("[")
        return json.loads(out[i:]) if i >= 0 else None
    except Exception:
        return None


def _gloss_for(lemma, token):
    for k in (token.lower(), lemma.lower()):
        if k in _ELISION_GLOSS:
            return _ELISION_GLOSS[k]
        if k in MOTS_OUTILS_GLOSS:
            return MOTS_OUTILS_GLOSS[k]
    key = store_key(lemma)
    for e in store_load()["entries"]:
        if e.get("key") == key and e.get("sens"):
            sens = e["sens"]
            lx = lexique_lookup(sens) if " " not in sens.strip() else None
            if lx and _deaccent(lx["lemma"].lower()) == _deaccent(lemma.lower()):
                continue                       # "doit" does not explain "devoir"
            return sens[:40]
    return ""


def _show_multitran(word):
    lines, direction, err = multitran_lookup(word)
    arrow = "ru→fr" if direction == "rufr" else "fr→ru"
    if lines:
        print(f"  {CYAN}📚 Multitran ({arrow}){RESET}")
        for ln in lines[:40]:
            print(f"     {ln}")
        if len(lines) > 40:
            print(f"     {DIM}… (full entry in Dictionary.app — ⌃⌘D){RESET}")
    elif _show_wikt_ru(word):
        pass                       # Wiktionary carried the Russian instead
    elif err:
        print(f"  {DIM}📚 Multitran: {err}{RESET}")
    else:
        print(f"  {DIM}📚 (not in Multitran {arrow}: « {word} »){RESET}")


def _show_wikt_ru(word):
    """Russian from the Wiktionnaire — what you get without Multitran
    (proprietary, bring-your-own). True when something was printed."""
    try:
        entry = wiktionary(word)
    except Exception:
        return False
    rows = (entry or {}).get("ru") or []
    if not rows:
        return False
    print(f"  {CYAN}📚 russe {DIM}(Wiktionnaire){RESET}")
    for r in rows[:8]:
        bits = r["word"]
        if r.get("tr"):
            bits += f"  {DIM}[{r['tr']}]{RESET}"
        if r.get("gender"):
            bits += f"  {DIM}{r['gender']}.{RESET}"
        print(f"     {bits}")
    return True


def _show_xray(sentence):
    """Every word: lemma · pos · tense/person · gender · frequency · role · meaning."""
    sentence = sentence.strip()
    print(f"  {BOLD}🩻 {sentence}{RESET}")
    try:                                       # translation of the whole sentence (1 call)
        tr, _, _ = translate(sentence, tl="en")
        if tr and _deaccent(tr.lower()) != _deaccent(sentence.lower()):
            print(f"  {DIM}→{RESET} {tr}")
    except Exception:
        pass
    spacy_on = config_load().get("xray_spacy", True)
    sp = _spacy_tokens(sentence) if spacy_on else None
    if sp:
        toks = [(t["text"], t["lemma"], t["pos"], _DEP_FR.get(t["dep"], t["dep"]))
                for t in sp if t["pos"] != "PUNCT" and t["text"].strip()]
        src_tag = "spaCy + Lexique + conjugations"
    else:
        toks = [(w, None, None, "") for w in _xray_tokens(sentence)]
        src_tag = ("Lexique + conjugations — spaCy off (\u00ab :spacy on \u00bb for roles)"
                   if not spacy_on else
                   "Lexique + conjugations — spaCy unavailable (uv?)" if not shutil.which("uv")
                   else "Lexique + conjugations — spaCy: failed")
    rows = []
    for text, lemma, pos, role in toks:
        text = text.strip("-–")                # spaCy leaves "-moi"
        if not text:
            continue
        lex = lexique_lookup(text)
        lem = (lex["lemma"] if lex else None) or lemma or text
        nature = (lex["pos"] if lex else "") or _SPACY_POS_FR.get(pos or "", (pos or "").lower())
        if not nature and text[:1].isupper() and rows:
            nature = "nom propre"
        detail, genre, band = "", "", ""
        # A verb? The conjugation database has the last word ("tiens": Lexique
        # says interjection, spaCy says verb, the database says tenir → verb).
        inf = _form_to_infinitive(text)
        is_verb = bool(inf) and (
            pos in ("VERB", "AUX") or lex is None
            or lex["cgram"].startswith(("VER", "AUX", "ONO")))
        if not inf and (pos in ("VERB", "AUX") or (lex and lex["cgram"].startswith(("VER", "AUX")))):
            for cand in (lemma, lem):          # spaCy lemma (partie → partir), then Lexique
                if cand and _conj_query(cand)[1]:
                    inf = _conj_query(cand)[0]
                    break
            is_verb = bool(inf)
        if is_verb:
            nature = "verbe"
            if inf:
                lem = inf
                if _deaccent(text.lower()) == _deaccent(inf.lower()):
                    detail = "infinitif"
                else:
                    detail = _conj_tense_of(inf, text) or ""
        if lex:
            if lex["genre"] and (lex["cgram"].startswith("NOM") or lex["cgram"] == "ADJ"):
                genre = "m." if lex["genre"] == "m" else "f."
            band = lex["band"]
        rows.append((text, lem if lem.lower() != text.lower() else "", nature,
                     detail, " ".join(x for x in (genre, band) if x), role,
                     _gloss_for(lem, text)))
    content = {"nom", "verbe", "adjectif", "adverbe"}
    todo = [i for i, r in enumerate(rows) if not r[6] and r[2] in content]
    if todo:
        try:                                   # a single call for every missing word
            lem = [rows[i][1] or rows[i][0] for i in todo]
            tr, _, _ = translate_google("\n".join(lem), tl="en")
            parts = [p.strip() for p in tr.split("\n")]
            if len(parts) == len(todo):
                for i, g in zip(todo, parts):
                    r = rows[i]
                    rows[i] = r[:6] + (g.lower() if g.lower() != (r[1] or r[0]).lower() else "",)
        except Exception:
            pass
    heads = ("word", "lemma", "pos", "tense", "gender·freq", "role", "meaning")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(heads)]
    print("  " + DIM + "  ".join(h.ljust(widths[i]) for i, h in enumerate(heads)).rstrip() + RESET)
    for r in rows:
        cells = []
        for i, c in enumerate(r):
            c = c.ljust(widths[i])
            if i == 0:
                c = f"{BOLD}{c}{RESET}"
            elif i == 3 and r[3]:
                c = f"{GREEN}{c}{RESET}"
            elif i in (5, 6) and r[i]:
                c = f"{DIM}{c}{RESET}"
            cells.append(c)
        print("  " + "  ".join(cells).rstrip())
    print(f"  {DIM}({src_tag}){RESET}")


# --------------------------------------------------------------------------- #
#  Grammar: offline Grammalecte (data/grammalecte, via build_grammalecte.py)
# --------------------------------------------------------------------------- #
GRAMMALECTE_DIR = os.path.join(DATA_DIR, "grammalecte")
_GC = None
_GRAM_TYPE = {
    "ppas": "past participle", "gn": "agreement (noun phrase)", "conj": "conjugation",
    "gv": "verb phrase", "vmode": "verb mood", "infi": "infinitive",
    "imp": "imperative", "inte": "question", "sgpl": "singular / plural",
    "conf": "confusion", "bs": "barbarism", "eleu": "elision", "elis": "elision",
    "typo": "typography", "esp": "spacing", "nbsp": "non-breaking space",
    "maj": "capitalization", "apos": "apostrophe", "tu": "phrasing", "redon": "redundancy",
    "pleo": "pleonasm", "date": "date", "num": "number", "poncfin": "punctuation",
    "virg": "comma", "mc": "compound word", "ocr": "OCR",
}


def _grammalecte():
    """Load (once) the checker vendored in data/grammalecte. None if missing."""
    global _GC
    if _GC is not None:
        return _GC or None
    if not os.path.isdir(os.path.join(GRAMMALECTE_DIR, "grammalecte")):
        _GC = False
        return None
    try:
        if GRAMMALECTE_DIR not in sys.path:
            sys.path.insert(0, GRAMMALECTE_DIR)
        import grammalecte as _g
        _GC = _g.GrammarChecker("fr")
    except Exception:
        _GC = False
    return _GC or None


def _show_grammar(sentence):
    """Highlighted sentence → each mistake (what, why, suggestion) → fixed version."""
    gc = _grammalecte()
    if gc is None:
        print(f"  {YELLOW}✗ Grammalecte not installed — run: dico --setup{RESET}")
        return
    text = sentence.strip()
    try:
        gram, spell = gc.getParagraphErrors(text, bSpellSugg=True)
    except Exception as e:
        print(f"  {YELLOW}✗ Grammalecte : {e}{RESET}")
        return
    errs = sorted(gram, key=lambda e: e["nStart"])
    sp = sorted(spell, key=lambda e: e["nStart"])
    spans = sorted([(e["nStart"], e["nEnd"], RED) for e in errs]
                   + [(e["nStart"], e["nEnd"], YELLOW) for e in sp])
    out, pos = "", 0
    for a, b, col in spans:                    # the sentence, mistakes highlighted
        if a < pos:
            continue
        out += text[pos:a] + f"{col}{BOLD}{text[a:b]}{RESET}"
        pos = b
    out += text[pos:]
    print(f"  📝 {out}")
    if not errs and not sp:
        print(f"  {GREEN}✓ Nothing to report — this is correct!{RESET}")
        return
    n = 0
    for e in errs:                             # each mistake: what, why, → suggestion
        n += 1
        msg = (e.get("sMessage") or "").replace("\xa0", " ").strip()
        typ = _GRAM_TYPE.get(e.get("sType", ""), e.get("sType", ""))
        print(f"  {RED}{n}.{RESET} « {BOLD}{text[e['nStart']:e['nEnd']]}{RESET} » — {msg}"
              + (f"  {DIM}[{typ}]{RESET}" if typ else ""))
        sug = e.get("aSuggestions") or []
        if sug:
            print(f"     {GREEN}→ {' / '.join(sug[:4])}{RESET}")
    for e in sp:
        n += 1
        sug = [s for s in (e.get("aSuggestions") or [])
               if s.lower() != e["sValue"].lower()][:4]
        print(f"  {YELLOW}{n}.{RESET} \u00ab {BOLD}{e['sValue']}{RESET} \u00bb — unknown word "
              f"(spelling? accent?)" + (f"  {DIM}→ {' / '.join(sug)}{RESET}" if sug else ""))
    fixed, changed = text, False              # corrected version (1st suggestion)
    for e in sorted(errs, key=lambda e: -e["nStart"]):
        sug = e.get("aSuggestions") or []
        if sug:
            fixed = fixed[:e["nStart"]] + sug[0] + fixed[e["nEnd"]:]
            changed = True
    if changed:
        print(f"  {GREEN}✓ {fixed}{RESET}")

# --------------------------------------------------------------------------- #
#  Display                                                                    #
# --------------------------------------------------------------------------- #
# Lexique lists borrowings and single letters, so "put", "out", "the", "i", "go"
# and "home" are all "known French words" — enough to send « put out the fire »
# to the grammar checker instead of translating it. These are the words that
# settle it the other way; French homographs (a, on, or, car, son, ton, pour,
# sale, pain, coin, vie…) are deliberately NOT in the list.
_EN_MARKERS = {
    "the", "is", "are", "was", "were", "be", "been", "am", "does", "did", "doing",
    "to", "of", "in", "at", "for", "with", "and", "but", "this", "that", "these",
    "those", "it", "its", "you", "your", "i", "my", "me", "he", "him", "his",
    "she", "her", "they", "them", "their", "we", "our", "out", "up", "off",
    "put", "get", "got", "make", "made", "have", "has", "had", "can", "could",
    "will", "would", "should", "what", "how", "why", "when", "where", "who",
    "not", "there", "here", "from", "into", "about", "over", "under", "back",
    "want", "need", "know", "think", "say", "said", "go", "going", "went",
    "come", "like", "just", "very", "some", "any", "all", "more", "most",
    "then", "than", "because", "if", "too", "also", "only", "still", "again",
    "never", "always", "now", "today", "tomorrow", "yesterday", "home", "house",
    "don't", "doesn't", "isn't", "can't", "won't", "i'm", "it's", "let's",
}


def _looks_french_sentence(text):
    """>= 3 words, no Cyrillic, most of the words known to Lexique — and not
    plainly English (Lexique knows too many English-looking strings)."""
    toks = [t for t in re.findall(r"[\w'’-]+", text) if not t.isdigit()]
    if len(toks) < 3 or re.search(r"[\u0400-\u04FF]", text):
        return False
    if sum(1 for t in toks if t.lower() in _EN_MARKERS) / len(toks) >= 0.34:
        return False
    hits = sum(1 for t in toks if lexique_lookup(t.strip("'’")) is not None)
    return hits / len(toks) >= 0.6


def show(word, want_dict=False, want_ai=False, want_save=False,
         want_multi=False, want_conj=False, want_deep=False, want_fr=False,
         want_save_main=False, want_gram=False, want_xray=False):
    # Intent detection: a French SENTENCE with no prefix → grammar check.
    if not any((want_dict, want_ai, want_save, want_multi, want_conj, want_deep,
                want_fr, want_save_main, want_gram, want_xray)) and _looks_french_sentence(word):
        want_gram = True
        print(f"  {DIM}French sentence → grammar  (\u00ab !x \u00bb for the x-ray, \u00ab ? \u00bb to ask){RESET}")
    if (want_ai or want_deep) and len(word.split()) > 1 and not (
            want_dict or want_fr or want_multi or want_conj):
        _show_ai(word, deep=bool(want_deep), question=word)   # free-form question
        return
    if want_gram or want_xray:                # "sentence" tools: their own pipeline
        _LAST["sentence"] = word.strip()
        if want_xray:
            _show_xray(word)
        if want_gram:
            _show_grammar(word)
        return
    src_guess = detect_lang(word)
    offline_ok = want_multi or want_conj      # sections that work offline

    # If the word is already French (a known verb, or -f "French Wiktionary"
    # mode), sending it to Google is useless and misleading ("manger" is also an
    # English word → "crèche").
    conj_inf = conj_tenses = conj_err = None
    conj_tense = None
    conj_from_fr = False
    _LAST["conj_shown"] = bool(want_conj)
    if want_conj:
        word, conj_tense = _split_tense(word)   # "manger present" → filter to one tense
        conj_inf, conj_tenses, conj_err, conj_from_fr = conjugate_lookup(word)
    # -c found a French verb (infinitive OR conjugated form) → skip the useless
    # Google fr→fr "translation" (doit → doit).
    direct_fr_verb = bool(conj_inf) and conj_from_fr
    # Multitran is ru<->fr: a word in the Latin alphabet IS French → skip the
    # useless Google fr→fr "translation" (eventail → eventail).
    multi_fr = want_multi and detect_lang(word) == "en"
    input_is_french = want_fr or direct_fr_verb or multi_fr

    translation, detected, alts, groups = None, None, [], []
    if input_is_french:
        translation = conj_inf if direct_fr_verb else word.strip().lower()
        detected = "fr"
    else:
        groups = []
        try:
            translation, detected, groups = translate_rich(word)      # Google
            alts = [t for _, terms in groups for t, _ in terms][:6]
        except Exception as e:
            try:
                translation, detected, alts = translate_mymemory(word, src_guess)
            except Exception:
                translation = None
            if translation:
                pass
            elif not offline_ok:
                print(f"{RED}✗ Error / no connection:{RESET} {e}")
                print(f"{DIM}  (the quick translation needs internet){RESET}")
                return
            else:
                print(f"  {DIM}(offline: no quick translation){RESET}")
    src = detected or src_guess
    _LAST.update(word=word, fr=translation or "")

    # Cognate / false friend: is the TYPED word itself a common French word?
    # ("table" EN → Google says "tableau", but "table" IS French.)
    cognate = None
    if (translation and not input_is_french and len(word.strip()) >= 3):
        c = lexique_lookup(word)
        if (c and c["freqfilms"] >= 1 and c["cgram"][:3] in ("NOM", "ADJ", "VER")
                and _deaccent(c["lemma"]) != _deaccent(translation)):
            cands = {a.strip().lower() for a in [translation, *alts]}
            if word.strip().lower() in cands or c["ortho"].lower() in cands:
                translation = c["ortho"]      # Google offers it too → prefer it
            else:
                cognate = c                   # otherwise: just flag "also French"

    lex_fr = lexique_lookup(translation) if translation else None
    if not translation and not offline_ok:
        print(f"{YELLOW}No translation found for \u00ab {word} \u00bb.{RESET}")
        return
    if translation:
        ex_on = config_load().get("examples", True)
        is_fr = input_is_french or _deaccent(translation.lower()) == _deaccent(word.strip().lower())
        if is_fr:
            _render_card_fr(translation, lex_fr, examples=ex_on and not want_conj)
        else:
            _render_card_to_fr(word, src, translation, groups if not input_is_french else [],
                               examples=ex_on)

    if cognate:                               # possible false friend: flag it
        art = (cognate["article"] + " ") if cognate["article"] else ""
        g = (" " + ("masc." if cognate["genre"] == "m" else "fém.")) \
            if cognate["genre"] else ""
        print(f"  {YELLOW}↔ \u00ab {word} \u00bb is also a French word{RESET}: "
              f"{BOLD}{art}{cognate['lemma']}{RESET} {DIM}({cognate['pos']}{g}, "
              f"{cognate['band']}) — \u00ab def {word} \u00bb for its meaning{RESET}")

    if want_multi:
        _show_multitran(word)

    if want_conj:
        shown = conj_tenses
        if conj_tenses and conj_tense:
            shown = {k: v for k, v in conj_tenses.items() if k == conj_tense}
        if shown:
            if conj_inf and _deaccent(conj_inf) != _deaccent(word):
                print(f"  {DIM}\u00ab {word} \u00bb → a form of{RESET} {BOLD}{conj_inf}{RESET}")
            print(f"  {CYAN}🔄 {conj_inf}{RESET}  {DIM}(conjugation){RESET}")
            for line in _conj_lines(shown):       # aligned pronoun × tense grid
                print(f"     {line}")
        elif conj_tenses and conj_tense:
            print(f"  {DIM}🔄 (\u00ab {conj_tense} \u00bb unavailable for \u00ab {conj_inf} \u00bb){RESET}")
        elif conj_err:
            print(f"  {DIM}🔄 conjugation: {conj_err}{RESET}")
        else:
            print(f"  {DIM}🔄 (verb not found: \u00ab {word} \u00bb){RESET}")

    wikt_entry = None
    if want_fr:                               # Wiktionary for the word as typed
        wikt_entry = _show_wikt(word)

    if want_dict and translation:             # Wiktionary for the translation
        wikt_entry = _show_wikt(translation)

    if want_ai or want_deep:
        q = word if len(word.split()) > 1 else None   # several words = free-form question
        _show_ai(word, deep=bool(want_deep), question=q)

    auto = autosave_on() and not _NO_AUTOSAVE
    if (auto or want_save or want_save_main) and translation:
        # Enrichment: 1) the Wiktionary entry already shown (-f/-d, rich),
        # 2) OFFLINE Lexique (lemma/gender/pos, no network),
        # 3) only as a last resort, a Wiktionary request.
        entry, lex = wikt_entry, lex_fr
        # A phrase (several words, leading article aside)? Keep the WHOLE group
        # ("éteindre le feu") instead of shrinking it to "un feu".
        core = translation.strip().split()
        while len(core) > 1 and core[0].lower() in _FR_ARTICLES:
            core = core[1:]
        is_phrase = len(core) > 1
        if not is_phrase and entry is None and lex is None:
            try:
                entry = wiktionary(translation)    # network, only for a single word
            except Exception:
                entry = None
        if is_phrase:
            lemma = " ".join(core)
            front = lemma                          # no article in front of a phrase
        else:
            lemma = ((entry.get("lemma") if entry else None)
                     or (lex.get("lemma") if lex else None)
                     or (core[0] if core else translation))
            article = ARTICLE_FOR.get((entry.get("gender") if entry else "") or "")
            if not article and lex:
                article = lex.get("article")
            front = f"{article} {lemma}" if article else lemma
        if input_is_french and entry and entry["defs"]:
            d = entry["defs"][0]
            sens = d[:55] + ("…" if len(d) > 55 else "")
        elif want_conj and input_is_french:
            sens = ""                              # conj. card: the back = the forms
        else:
            sens = word                            # the original (ru/en) word = the meaning
        # Conjugation → put the PRÉSENT on the back of the card (other tenses: later).
        example = ""
        if want_conj and conj_tenses and conj_tenses.get("présent"):
            example = "prés. : " + ", ".join(conj_tenses["présent"])
        record = {
            "key": store_key(lemma),
            "front": front,
            "lemma": lemma,
            "sens": sens,
            "pos": ((entry.get("pos") if entry else None)
                    or (lex.get("pos") if lex else "") or ""),
            "gender": ((entry.get("gender") if entry else None)
                       or (lex.get("genre") if lex else "") or ""),
            "example": example,
            "src_word": word,
            "src_lang": src,
            "tier": ("wiktionnaire" if input_is_french
                     else "multitran" if want_multi else "google"),
        }
        try:
            status, cnt = store_upsert(record)
            tag = f"  {DIM}×{cnt}{RESET}" if cnt > 1 else ""
            badge = (f"  {DIM}auto{RESET}"
                     if auto and not (want_save or want_save_main) else "")
            print(f"  {GREEN}💾 \u00ab {front} \u00bb → {status}{RESET}{tag}{badge}")
        except Exception as e:
            print(f"  {YELLOW}💾 save failed:{RESET} {e}")


# --------------------------------------------------------------------------- #
#  Interactive mode                                                           #
# --------------------------------------------------------------------------- #
_FOLLOW_HINT = "↳  save N · conj · def · ru · ex · say · syn · ? question"


def _follow_up(line):
    """Plain-word commands. « conj », « def », « ru », « ex », « x », « grammar » act on
    the last card, or on the word/sentence you give: « conj manger ». True if handled."""
    low = line.strip()
    m = re.match(r"^(?:save|s)\s+(\d+)$", low, re.I)
    if m:
        n = int(m.group(1)); senses = _LAST.get("senses") or []
        if 1 <= n <= len(senses):
            _save_term(senses[n - 1], _LAST.get("word", ""), detect_lang(_LAST.get("word", "")))
        else:
            print(f"  {DIM}no sense {n} — the last card has {len(senses)}{RESET}")
        return True
    if low.lower() in ("help", "h", ":help", "?help"):
        _print_cheatsheet()
        return True
    m = re.match(r"^(conj|conjugate|def|definition|define|ru|multitran|ex|examples|x|xray|x-ray"
                 r"|grammar|check|xray|say|listen|audio|syn|synonyms)(?:\s+(.+))?$", low, re.I)
    if not m:
        return False
    cmd, arg = m.group(1).lower(), (m.group(2) or "").strip()
    fr = arg or _LAST.get("fr") or ""
    sentence = arg or _LAST.get("sentence") or fr
    if not fr and not sentence:
        print(f"  {DIM}look something up first, or give a word: « {cmd} manger »{RESET}")
        return True
    global _NO_AUTOSAVE
    prev, _NO_AUTOSAVE = _NO_AUTOSAVE, True     # a follow-up never re-saves
    try:
        if cmd in ("conj", "conjugate"):
            show(fr, want_conj=True)
        elif cmd in ("def", "definition", "define"):
            _show_wikt(fr)
        elif cmd in ("ru", "multitran"):
            _show_multitran(fr)
        elif cmd in ("say", "listen", "audio"):
            _show_audio(fr)
        elif cmd in ("syn", "synonyms"):
            _show_synonyms(fr)
        elif cmd in ("ex", "examples"):
            exs = _tatoeba(fr, "eng", limit=3) + _tatoeba(fr, "rus", limit=1)
            for s, t in exs:
                print(f"     {DIM}« {s} » — {t}{RESET}")
            if not exs:
                print(f"  {DIM}no example sentences found for « {fr} »{RESET}")
        elif cmd in ("grammar", "check"):
            _show_grammar(sentence)
        else:
            _show_xray(sentence)
    finally:
        _NO_AUTOSAVE = prev
    if arg:
        _LAST["fr"] = arg if cmd not in ("grammar", "check", "x", "xray", "x-ray") else _LAST.get("fr", "")
        if cmd in ("grammar", "check", "x", "xray", "x-ray"):
            _LAST["sentence"] = arg
    return True


def _repl_command(line):
    """":" commands of the interactive mode (settings, not lookups)."""
    parts = line[1:].split()
    cmd = parts[0].lower() if parts else ""
    arg = " ".join(parts[1:]).strip()
    if cmd in ("save", "autosave"):
        if arg.lower() in ("on", "off"):
            config_set("autosave", arg.lower() == "on")
            state = "on" if arg.lower() == "on" else "off"
            print(f"  {GREEN}✓ autosave {state}{RESET}")
        else:
            print(f"  autosave: {'ON' if autosave_on() else 'off'}"
                  f"   {DIM}(:save on | :save off){RESET}")
    elif cmd == "forget" and arg:
        n = store_forget(arg)
        print(f"  {GREEN}✓ \u00ab {arg} \u00bb dropped{RESET}" if n
              else f"  {DIM}\u00ab {arg} \u00bb not found{RESET}")
    elif cmd == "render":
        store_render()
        print(f"  {GREEN}✓ markdown regenerated{RESET}")
    elif cmd == "llm":
        url, model, _ = _llm_cfg()
        if arg:
            parts = arg.split()
            config_set("llm_url", parts[0]) if "://" in parts[0] else config_set("llm_model", parts[0])
            if len(parts) > 1:
                config_set("llm_model", parts[1])
            url, model, _ = _llm_cfg()
        state = "OK" if _llm_reachable() else "unreachable"
        print(f"  tutor: {url}  ·  model: {model or '(first one loaded)'}  ·  {state}"
              f"   {DIM}(:llm <url> [model] · :llm <model>){RESET}")
    elif cmd in ("examples", "exemples"):
        if arg.lower() in ("on", "off"):
            config_set("examples", arg.lower() == "on")
        print(f"  Tatoeba examples: {'ON' if config_load().get('examples', True) else 'off'}")
    elif cmd == "spacy":
        if arg.lower() in ("on", "off"):
            config_set("xray_spacy", arg.lower() == "on")
        state = "ON" if config_load().get("xray_spacy", True) else "off"
        print(f"  spaCy for \u00ab !x \u00bb: {state}   {DIM}(:spacy on | :spacy off — off = "
              f"instant, Lexique only){RESET}")
    else:
        print(f"  {DIM}commands: :save on|off · :forget <word> · :render · :spacy on|off · :llm{RESET}")


def _load_history():
    if not readline:
        return
    try:
        readline.read_history_file(HISTFILE)
    except OSError:
        pass
    readline.set_history_length(1000)


def _save_term(french, sens, src_lang="en", tier="google", quiet=False):
    """Save a French term (front with its article if a noun), "sens" on the back."""
    front, lex = _fr_head(french)
    lemma = (lex["lemma"] if lex else french)
    rec = {"key": store_key(lemma), "front": front, "lemma": lemma, "sens": sens,
           "pos": (lex["pos"] if lex else ""), "gender": (lex["genre"] if lex else "") or "",
           "example": "", "src_word": sens, "src_lang": src_lang, "tier": tier,
           # Offline extras, so a card carries them into Anki/Obsidian too.
           "cefr": (lex or {}).get("cefr") or "", "ipa": (lex or {}).get("ipa") or ""}
    status, cnt = store_upsert(rec)
    if quiet:
        return front, status, cnt
    tag = f"  {DIM}×{cnt}{RESET}" if cnt > 1 else ""
    print(f"  {GREEN}💾 « {front} » → {status}{RESET}{tag}")
    return front, status, cnt


def _save_history():
    if readline:
        try:
            readline.write_history_file(HISTFILE)
        except OSError:
            pass


def interactive():
    if not _data_ready():
        print(f"\n{BOLD}👋 Welcome to dico.{RESET} The offline data (conjugations, Lexique, "
              f"Grammalecte — ~50 MB, 2 min) isn't built yet.")
        if sys.stdin.isatty() and _ask("   Build it now? [Y/n] ", "y").lower().startswith("y"):
            run_setup()
        else:
            print(f"   {DIM}later: dico --setup{RESET}")
    _load_history()                            # ↑ recalls the previous words
    try:                                       # to detect a REPL that went stale
        src_mtime = os.path.getmtime(os.path.abspath(__file__))
    except OSError:
        src_mtime = 0
    warned_stale = False
    # Colors are wrapped in \001..\002 so readline measures the prompt width
    # correctly (otherwise the cursor drifts when recalling history).
    if sys.stdout.isatty() and readline:
        prompt = f"\001{BLUE}\002»\001{RESET}\002 "
    else:
        prompt = f"{BLUE}»{RESET} "
    state = f"{GREEN}ON{RESET}" if autosave_on() else f"{DIM}off{RESET}"
    print(f"\n{BOLD}📖 dico{RESET}  —  Russian / English → French"
          f"        {DIM}autosave{RESET} {state}   {DIM}tutor {_llm_label()}{RESET}\n")
    _print_cheatsheet()
    print(f"\n   {DIM}↑ history  ·  « help » shows this again{RESET}\n")
    try:
        while True:
            try:
                line = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{DIM}See you soon! 👋{RESET}")
                break
            if not line:
                continue
            if not warned_stale:                # has dico.py changed since launch?
                try:
                    if os.path.getmtime(os.path.abspath(__file__)) > src_mtime:
                        warned_stale = True
                        print(f"{YELLOW}⚠ dico.py changed since this session "
                              f"started — type \u00ab q \u00bb and relaunch \u00ab dico \u00bb "
                              f"to get the latest version.{RESET}")
                except OSError:
                    pass
            if line.lower() in ("q", "quit", "exit", "quitter"):
                print(f"{DIM}See you soon! 👋{RESET}")
                break
            if line.startswith(":"):           # a setting, not a lookup
                _repl_command(line)
                continue
            if _follow_up(line):                  # "save 2", "conj", "def", "ru", "ex", "x", "help"
                continue
            if line.startswith("?"):           # free question to the tutor (context = last word)
                deep = line.startswith("??")
                q = line.lstrip("?").strip()
                if q:
                    _show_ai(None, deep, question=q)
                else:
                    print(f"  {DIM}\u00ab ? your question \u00bb — e.g. ? cuisiner vs cuire · "
                          f"? pourquoi \u00ab de \u00bb ici · ?? (detailed answer){RESET}")
                continue
            if line[:1] in "!-":               # old prefix habit → point at the words
                print(f"  {DIM}no prefixes anymore — say it in words: conj · def · ru · ex · "
                      f"grammar · x · save N · ? question   (e.g. « def {line.split()[-1]} »){RESET}")
                continue
            show(line)                         # a word, a French word, or a sentence
    finally:
        _save_history()


_PROVIDERS = [
    ("Anthropic (Claude)", "anthropic", None, "claude-haiku-4-5"),
    ("OpenAI", "openai", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("Mistral (French-native)", "mistral", "https://api.mistral.ai/v1", "mistral-small-latest"),
    ("Groq (very fast, free tier)", "groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    ("Google Gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash"),
    ("Custom OpenAI-compatible URL", "custom", "", ""),
]


def _detect_local_llm():
    """(url, model) of a local server that answers: LM Studio, then Ollama."""
    for url in ("http://localhost:1234/v1", "http://localhost:11434/v1"):
        try:
            ids = _llm_models(url, "")
            if ids:
                return url, ids[0]
        except Exception:
            pass
    return None, None


def _ask(prompt, default=""):
    try:
        v = input(prompt).strip()
    except EOFError:
        return default
    return v or default


def setup_llm():
    """Interactive: local model, bring-your-own-key, or none. Saves to config."""
    import getpass
    print(f"\n{BOLD}🤖 Tutor{RESET} — answers « ? your question » and « -a » in simple French.")
    url, model = _detect_local_llm()
    if url:
        print(f"   local model found: {GREEN}{model}{RESET} at {url}")
    else:
        print(f"   {DIM}no local model server found (LM Studio / Ollama){RESET}")
    print("   1) local model (LM Studio or Ollama — free, private)")
    print("   2) bring your own API key (Anthropic, OpenAI, Mistral, Groq, Gemini, custom)")
    print("   3) none for now")
    choice = _ask(f"   choose [{'1' if url else '2'}]: ", "1" if url else "2")
    if choice == "1":
        for k in ("llm_url", "llm_model", "llm_key", "anthropic_key"):
            config_set(k, None)
        config_set("llm", "local")
        print(f"   {GREEN}✓{RESET} local model — auto-detected each time (LM Studio :1234, Ollama :11434)")
        return
    if choice == "3":
        config_set("llm", "none")
        print(f"   {DIM}ok — run « dico --llm » whenever you want a tutor{RESET}")
        return
    for i, (name, _, _, _) in enumerate(_PROVIDERS, 1):
        print(f"   {i}) {name}")
    pi = _ask("   provider [3]: ", "3")
    try:
        name, key_id, base, default_model = _PROVIDERS[int(pi) - 1]
    except (ValueError, IndexError):
        print("   ?"); return
    key = getpass.getpass("   API key (hidden): ").strip() if sys.stdin.isatty() else _ask("   API key: ")
    if not key:
        print("   no key — skipped"); return
    if key_id == "anthropic":
        config_set("anthropic_key", key)
        for k in ("llm_url", "llm_model", "llm_key"):
            config_set(k, None)
        config_set("llm", "anthropic")
        text, err = _ai_via_api("Réponds juste « ok ».", key, AI_MODEL, 10)
    else:
        if key_id == "custom":
            base = _ask("   base URL (…/v1): ")
        model = _ask(f"   model [{default_model}]: ", default_model)
        config_set("llm_url", base); config_set("llm_model", model); config_set("llm_key", key)
        config_set("anthropic_key", None); config_set("llm", "byok")
        text, err = _llm_openai("Reply with the single word: ok", "ok?", 10)
    if err:
        print(f"   {YELLOW}✗ test failed: {err}{RESET}  (saved anyway — fix with « dico --llm »)")
    else:
        print(f"   {GREEN}✓ {name} answers{RESET}  — key stored in {CONFIG_PATH} (chmod 600)")


def _print_cheatsheet():
    rows = [("a word (RU/EN)", "card: numbered senses · gender · example"),
            ("a French word", "its card (+ présent if it's a verb)"),
            ("a French sentence", "grammar check + the rule"),
            ("save N", "save sense N of the last card"),
            ("conj · def · ru · ex", "on the last card — or give a word: « conj manger », « def maison »"),
            ("say · syn", "hear a native recording · synonyms and homophones"),
            ("grammar · x [sentence]", "grammar check · x-ray, on the last sentence or the one you give"),
            ("? question", "ask the tutor, in context (?? = detailed)"),
            (":save on|off", "auto-save every lookup (also :forget word, :render, :llm, :spacy)"),
            ("q", "quit")]
    w = max(len(k) for k, _ in rows)
    for k, d in rows:
        print(f"   {BOLD}{CYAN}{k.ljust(w)}{RESET}  {d}")


def run_tour():
    """A 2-minute guided tour. Needs internet; does not auto-save your store."""
    global _NO_AUTOSAVE
    _NO_AUTOSAVE = True
    steps = [
        ("Type an English or Russian word. You get a card: senses numbered and grouped by "
         "part of speech, each noun with its article and gender, ★ = how common.", "cook",
         lambda: show("cook")),
        ("The first sense is what auto-save keeps. Want another one? Just say « save 5 ».",
         "save 5", lambda: _follow_up("save 5")),
        ("A French word gives its own card: nature, gender, frequency, English senses, an example.",
         "maison", lambda: show("maison")),
        ("A French verb shows its présent right away. « conj » gives the whole grid.",
         "aller  →  conj", lambda: (show("aller"), _follow_up("conj"))),
        ("Type a French sentence and dico corrects it — and names the rule.",
         "elle est parti hier et je mange un pomme",
         lambda: show("elle est parti hier et je mange un pomme")),
        ("Ask the tutor anything about what you're looking at: « ? … ».",
         "? tu ou vous ?", lambda: _show_ai(None, False, question="tu ou vous ?")),
    ]
    print(f"\n{BOLD}📖 dico — the tour{RESET}  {DIM}(Enter = next, q = stop){RESET}")
    for text, cmd, run in steps:
        print(f"\n{text}\n{BLUE}»{RESET} {BOLD}{cmd}{RESET}")
        try:
            run()
        except Exception as e:
            print(f"  {DIM}(skipped: {e}){RESET}")
        if _ask("").lower() == "q":
            break
    print(f"\n{BOLD}That's it.{RESET} Everything else:")
    _print_cheatsheet()
    print(f"\n{DIM}Auto-save is {'ON' if autosave_on() else 'off'} — your lookups become flashcards "
          f"(Obsidian / Anki, see README). « dico --llm » sets up the tutor.{RESET}\n")
    _NO_AUTOSAVE = False


def run_setup(ask_llm=True):
    """Build the databases in DATA_DIR: conjugations (verbecc through uv), the
    form index, Lexique, Grammalecte, and Multitran if the Apple .dictionary
    bundles exist."""
    os.makedirs(DATA_DIR, exist_ok=True)
    env = dict(os.environ, DICO_DATA=DATA_DIR)
    steps = [("Conjugations (verbecc, through uv)", ["uv", "run", os.path.join(_HERE, "build_conjugations.py")]),
             ("Form index (doit → devoir)", [sys.executable, os.path.join(_HERE, "build_conj_forms.py")]),
             ("Lexique 3.83 (frequency, genders)", [sys.executable, os.path.join(_HERE, "build_lexique.py")]),
             ("FLELex (CEFR levels A1…C2)", [sys.executable, os.path.join(_HERE, "build_flelex.py")]),
             ("Grammalecte (dico -g)", [sys.executable, os.path.join(_HERE, "build_grammalecte.py")])]
    bundles = os.path.expanduser("~/Library/Dictionaries")
    if all(os.path.isdir(os.path.join(bundles, f"multitran_{d}.dictionary")) for d in ("rufr", "frru")):
        steps.append(("Multitran (Apple dictionaries)", ["bash", os.path.join(_HERE, "setup.sh"), "--multitran-only"]))
    else:
        print(f"{DIM}(Multitran: Apple dictionaries missing — the -m option stays inactive){RESET}")
    for label, cmd in steps:
        print(f"{BOLD}==> {label}{RESET}", flush=True)
        if cmd[0] == "uv" and not shutil.which("uv"):
            print(f"  {YELLOW}uv missing — install it (https://docs.astral.sh/uv/) then run again{RESET}")
            continue
        r = subprocess.run(cmd, env=env)
        if r.returncode:
            print(f"  {YELLOW}✗ step failed ({r.returncode}){RESET}")
    print(f"{GREEN}✓ Done → {DATA_DIR}{RESET}")
    if ask_llm and sys.stdin.isatty():
        setup_llm()
        print(f"\n{DIM}Try « dico --tour » for a 2-minute walkthrough.{RESET}")


def as_json(text, args):
    """JSON representation of a lookup — for a graphical front-end."""
    out = _as_json(text, args)
    if _FALLBACK_NOTE and "note" not in out:
        out["note"] = _FALLBACK_NOTE
    return out


def _as_json(text, args):
    text = text.strip()
    out = {"query": text}
    if not text:
        return out
    if args.ai or args.profond:
        q = text if len(text.split()) > 1 else None
        ans, err = (ai_ask(q, args.profond) if q else ai_explain(text, deep=args.profond))
        out.update({"answer": ans, "error": err, "model": _llm_label()})
        return out
    if args.grammaire:
        gc = _grammalecte()
        gram, spell = gc.getParagraphErrors(text, bSpellSugg=True) if gc else ([], [])
        fixed = text
        for e in sorted(gram, key=lambda e: -e["nStart"]):
            if e.get("aSuggestions"):
                fixed = fixed[:e["nStart"]] + e["aSuggestions"][0] + fixed[e["nEnd"]:]
        out["grammar"] = {"errors": [{"start": e["nStart"], "end": e["nEnd"],
                                      "text": text[e["nStart"]:e["nEnd"]],
                                      "message": (e.get("sMessage") or "").replace("\xa0", " "),
                                      "type": _GRAM_TYPE.get(e.get("sType", ""), e.get("sType", "")),
                                      "suggestions": e.get("aSuggestions") or []} for e in gram],
                          "spelling": [{"start": e["nStart"], "end": e["nEnd"], "text": e["sValue"],
                                        "suggestions": (e.get("aSuggestions") or [])[:4]} for e in spell],
                          "corrected": fixed}
        return out
    if args.xray:
        sp = _spacy_tokens(text) if config_load().get("xray_spacy", True) else None
        toks = ([(t["text"].strip("-–"), t["lemma"], t["pos"], _DEP_FR.get(t["dep"], t["dep"]))
                 for t in sp if t["pos"] != "PUNCT"] if sp
                else [(w, None, None, "") for w in _xray_tokens(text)])
        words = []
        for tx, lemma, pos, role in toks:
            if not tx:
                continue
            lex = lexique_lookup(tx)
            inf = _form_to_infinitive(tx)
            words.append({"text": tx, "lemma": inf or (lex["lemma"] if lex else lemma or tx),
                          "pos": (lex["pos"] if lex else _SPACY_POS_FR.get(pos or "", "")),
                          "tense": (_conj_tense_of(inf, tx) if inf else "") or "",
                          "gender": (lex["genre"] if lex else "") or "", "band": lex["band"] if lex else "",
                          "role": role, "gloss": _gloss_for(inf or (lex["lemma"] if lex else tx), tx)})
        out["xray"] = words
        return out
    if args.examples:
        out["examples"] = {"en": [{"fr": s, "en": t} for s, t in _tatoeba(text, "eng", limit=4)],
                           "ru": [{"fr": s, "ru": t} for s, t in _tatoeba(text, "rus", limit=2)]}
        return out
    if args.francais or args.dico:
        target = text
        if args.dico and detect_lang(text) != "fr":
            try:
                target = translate_rich(text)[0] or text
            except Exception:
                pass
        e = None
        try:
            e = wiktionary(target)
        except Exception:
            pass
        out["definition"] = ({"word": e["lemma"], "ipa": e["ipa"], "gender": e["gender"],
                              "pos": e["pos"], "defs": e["defs"], "etym": e.get("etym"),
                              "syn": e.get("syn") or [], "homo": e.get("homo") or [],
                              "ru": e.get("ru") or [], "has_audio": bool(e.get("audio"))}
                             if e else None)
        return out
    if args.say or args.syn:
        e = None
        try:
            e = wiktionary(text)
        except Exception:
            pass
        out["synonyms"] = (e or {}).get("syn") or []
        known = {_deaccent(h["word"]) for h in ((e or {}).get("homo") or [])}
        out["homophones"] = ((e or {}).get("homo") or []) + [
            {"word": w, "note": ""} for w in homophones(text) if _deaccent(w) not in known]
        lx = lexique_lookup(text)
        out["cefr"] = (lx or {}).get("cefr")
        out["ipa"] = (lx or {}).get("ipa")
        if args.say:
            path, err = audio_for(text)
            out["audio"] = {"path": path, "error": err}
        return out
    if args.multitran:
        lines, direction, err = multitran_lookup(text)
        groups, _ = multitran_structured(text)
        out["multitran"] = {"direction": direction, "lines": lines or [], "groups": groups,
                            "error": err}
        if not groups and not (lines or []):          # no Multitran → Wiktionary's Russian
            try:
                out["multitran"]["wiktionary_ru"] = (wiktionary(text) or {}).get("ru") or []
            except Exception:
                pass
        return out
    if args.conj:
        w, tense = _split_tense(text)
        inf, data, err, _ = conjugate_lookup(w)
        out["conjugation"] = {"infinitive": inf, "tenses": data, "error": err}
        return out
    lang = detect_lang(text)
    lex = lexique_lookup(text)
    if lang == "en" and lex and lex["freqfilms"] >= 1 and lex["cgram"][:3] in ("NOM", "ADJ", "VER", "ADV", "PRE", "PRO", "CON", "ART"):
        head, lx = _fr_head(text)
        try:
            _, _, groups = translate_rich(text, tl="en", sl="fr")
        except Exception:
            groups = []
        out.update({"direction": "fr", "head": head, "lexique": lx,
                    "senses": [{"pos": p, "terms": [t for t, _ in ts]} for p, ts in groups],
                    "examples": _tatoeba(text, "eng")})
        return out
    try:
        tr, det, groups = translate_rich(text)
    except Exception as e:
        out["error"] = str(e)
        return out
    senses = []
    for pos, terms in groups:
        for term, back in terms:
            front, lx = _fr_head(term)
            senses.append({"pos": pos, "term": term, "front": front, "back": back,
                           "gender": (lx["genre"] if lx else "") or "", "band": lx["band"] if lx else ""})
    out.update({"direction": "to_fr", "src_lang": det or lang, "translation": tr,
                "senses": senses, "examples": _tatoeba(tr, "eng") if tr else []})
    return out


def main():
    p = argparse.ArgumentParser(
        prog="dico", add_help=True,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Pocket dictionary: Russian/English → French.",
        epilog=(
            "⚠ The quick translation only goes RU/EN → FR (never the other way).\n"
            "To go from FR to Russian: -m (Multitran fr→ru).\n"
            "For the MEANING of a French word: -f (Wiktionary) or -a / -p (Claude)."))
    p.add_argument("words", nargs="*", help="the word(s) to translate")
    p.add_argument("-m", "--multitran", action="store_true",
                   help="add the offline Multitran entry (rich, ru<->fr)")
    p.add_argument("-c", "--conj", action="store_true",
                   help="offline conjugation; \"-c manger present\" for a single tense "
                        "(present, passe, imparfait, futur, conditionnel, subjonctif, imperatif)")
    p.add_argument("-f", "--francais", action="store_true",
                   help="Wiktionary for the word as typed (already French, no translation)")
    p.add_argument("-d", "--dico", action="store_true",
                   help="Wiktionary after translation (RU/EN → French)")
    p.add_argument("-a", "--ai", action="store_true",
                   help="add a quick explanation from Claude (Haiku)")
    p.add_argument("-p", "--profond", action="store_true",
                   help="add an IN-DEPTH explanation (Opus: study card)")
    p.add_argument("-s", "--save", action="store_true",
                   help="save THIS word now (into the vocabulary store)")
    p.add_argument("-S", "--save-main", action="store_true",
                   help="alias of -s (same single store; kept out of habit)")
    p.add_argument("-g", "--grammaire", action="store_true",
                   help="correct a French SENTENCE (Grammalecte, offline) and name the rule")
    p.add_argument("-x", "--xray", action="store_true",
                   help="x-ray a SENTENCE: every word → lemma, pos, gender, frequency")
    p.add_argument("--autosave", nargs="?", const="status",
                   choices=["on", "off", "status"], metavar="on|off",
                   help="save EVERY lookup AUTOMATICALLY (persistent setting)")
    p.add_argument("--render", action="store_true",
                   help="regenerate the markdown from the JSON store, then exit")
    p.add_argument("--forget", metavar="WORD",
                   help="drop a word from the vocabulary (subtractive curation)")
    p.add_argument("--setup", action="store_true",
                   help="download/build the offline databases (conjugations, Lexique, "
                        "Grammalecte; Multitran if the Apple dictionaries are present)")
    p.add_argument("--llm", action="store_true",
                   help="set up the tutor: local model, your own API key, or none")
    p.add_argument("--no-llm", action="store_true", help="with --setup: skip the tutor step")
    p.add_argument("--tour", action="store_true", help="a 2-minute guided tour")
    p.add_argument("--say", action="store_true",
                   help="play a native recording of the word (Wiktionary/Commons)")
    p.add_argument("--syn", action="store_true",
                   help="synonyms and homophones (Wiktionnaire)")
    p.add_argument("--examples", action="store_true",
                   help="example sentences for a French word (Tatoeba, EN + RU); with --json for GUIs")
    p.add_argument("--json", action="store_true",
                   help="JSON output (for a graphical front-end / Raycast / etc.)")
    p.add_argument("--save-term", metavar="TERM",
                   help="save this French term (with --sens: the meaning on the back)")
    p.add_argument("--sens", metavar="TEXT", default="",
                   help="meaning (original word / translation) for --save-term")
    p.add_argument("--context", metavar="TEXT", default="",
                   help="context for a question (-a): last word / last sentence")
    p.add_argument("--mots-outils", nargs="?", const=120, type=int, metavar="N",
                   help="show the CORE function words (articles, prepositions, "
                        "pronouns, conjunctions, auxiliaries) — the grammatical scaffolding")
    args = p.parse_args()

    if args.setup:
        return run_setup(ask_llm=not args.no_llm)
    if args.llm:
        return setup_llm()
    if args.tour:
        return run_tour()
    if args.save_term:
        if args.json:
            front, status, cnt = _save_term(args.save_term, args.sens,
                                            detect_lang(args.sens or "en"), quiet=True)
            return print(json.dumps({"saved": front, "status": status, "count": cnt,
                                     "sens": args.sens}, ensure_ascii=False))
        return _save_term(args.save_term, args.sens, detect_lang(args.sens or "en"))
    if args.context:
        _LAST["word"] = args.context
    if args.examples and not args.json:
        w = " ".join(args.words if "words" in args else args.mots)
        exs = _tatoeba(w, "eng", limit=4) + _tatoeba(w, "rus", limit=2)
        for s, t in exs:
            print(f"  « {s} » — {DIM}{t}{RESET}")
        return None if exs else print(f"  {DIM}no examples found for « {w} »{RESET}")
    if args.json:
        return print(json.dumps(as_json(" ".join(args.words), args), ensure_ascii=False, indent=2))
    if args.mots_outils is not None:
        show_mots_outils(args.mots_outils, save=(args.save or args.save_main))
        return
    if args.autosave is not None:
        if args.autosave == "status":
            print(f"autosave: {'ON' if autosave_on() else 'off'}")
        else:
            config_set("autosave", args.autosave == "on")
            print(f"✓ autosave {'on' if args.autosave == 'on' else 'off'}.")
        return
    if args.forget:
        n = store_forget(args.forget)
        print(f"✓ \u00ab {args.forget} \u00bb dropped ({n})." if n
              else f"\u00ab {args.forget} \u00bb not found in the store.")
        return
    if args.render:
        store_render()
        print(f"✓ markdown regenerated → {VOCAB}")
        return

    if not _data_ready() and args.words:
        print(f"  {DIM}(offline data not built — run: dico --setup){RESET}")
    if args.words and (args.say or args.syn) and not args.json:
        text = " ".join(args.words)
        if args.syn:
            _show_synonyms(text)
        if args.say:
            _show_audio(text)
        return
    if args.words:
        show(" ".join(args.words), args.dico, args.ai, args.save,
             args.multitran, args.conj, args.profond, args.francais, args.save_main,
             args.grammaire, args.xray)
    else:
        interactive()


if __name__ == "__main__":
    try:
        main()
    finally:
        cache_flush()
