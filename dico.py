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
__version__ = "1.0.6"

import argparse
import contextlib
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
from datetime import datetime, timedelta

# Windows consoles default to a legacy code page that cannot show « → » or « é »:
# speak UTF-8 regardless (the Windows build is run without a terminal anyway).
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

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


HISTORY_TURNS = 12               # what the tutor is told about: the last N turns…
HISTORY_ANSWER_CHARS = 300       # …with its own earlier answers trimmed to this


class Session:
    """The REPL's state and its driver — one per terminal session, per one-shot
    call, and (later) per --serve process.

    State (what used to be module globals):
    last          context for « ? » / « save N »: word, fr, sentence, senses,
                  hints (follow-up hint shown ≤ 3 times), conj_shown
    no_autosave   True while a follow-up or the --tour runs (never re-save)
    fallback_note set when a card came from the MyMemory fallback, shown once
    history       the last HISTORY_TURNS turns — lookups (the query AND the
                  French word, the sense saved), grammar checks, x-rays, the
                  sections asked for, questions with the tutor's (trimmed)
                  answers — the context « ? » questions are asked in

    Driver: handle(line) understands every REPL line; handle_args(args) the
    argparse flags. Both turn their input into a *request* ({"op": …}) and
    run() executes it — ONE dispatch, whatever the skin. Results are dicts:
    the keys --json emits, plus "_"-prefixed ones for render() only.
    """

    def __init__(self):
        self.last = {"word": "", "fr": "", "sentence": "", "senses": []}
        self.no_autosave = False
        self.fallback_note = ""
        self.history = []

    def remember(self, turn):
        """Append a turn, keeping the last HISTORY_TURNS."""
        self.history.append(turn)
        del self.history[:-HISTORY_TURNS]

    def _remember_result(self, req, r):
        """What a request leaves in the history (questions are recorded by ai_ask)."""
        op, kind = req["op"], r.get("_kind")
        if op == "lookup" and kind in ("card_fr", "card_to_fr"):
            turn = {"kind": "lookup", "query": req["text"], "direction": r["direction"],
                    "fr": (r.get("translation") if kind == "card_to_fr" else r["_card"]["word"]) or req["text"],
                    "sections": [k for k in ("conjugation", "definition", "multitran") if k in r]}
            if "saved" in r:
                turn["saved"] = r["saved"]["front"]
            self.remember(turn)
        elif kind in ("grammar", "xray"):
            turn = {"kind": kind, "sentence": r["sentence"]}
            if kind == "grammar" and not r.get("_unavailable"):
                turn["corrected"] = r["grammar"]["corrected"]
            self.remember(turn)
        elif op == "save_sense" and kind == "saved":
            for t in reversed(self.history):   # the sense chosen belongs to its card
                if t["kind"] == "lookup":
                    t["saved"] = r["saved"]["front"]
                    break
        elif op in ("definition", "multitran", "synonyms", "audio", "examples", "conj") and kind != "error":
            self.remember({"kind": op, "fr": req["text"]})

    # ---- the two languages → a request ---------------------------------
    _FOLLOW = re.compile(r"^(conj|conjugate|def|definition|define|ru|multitran|ex|examples|x|xray|x-ray"
                         r"|grammar|check|xray|say|listen|audio|syn|synonyms)(?:\s+(.+))?$", re.I)
    _SENTENCE_CMDS = ("grammar", "check", "x", "xray", "x-ray")

    def parse(self, line):
        """A REPL line → a request. « : » settings, « save N », the plain-word
        follow-ups (conj · def · ru · ex · say · syn · grammar · x, on the last
        card or on the word given), « ? question », a word / a sentence."""
        line = line.strip()
        if line.startswith(":"):               # a setting, not a lookup
            return {"op": "setting", "line": line}
        if line.lower() in ("help", "h", "?help"):
            return {"op": "help"}
        if line.lower() == "history":
            return {"op": "history"}
        m = re.match(r"^(?:save|s)\s+(\d+)$", line, re.I)
        if m:
            return {"op": "save_sense", "n": int(m.group(1))}
        m = self._FOLLOW.match(line)
        if m:
            cmd, arg = m.group(1).lower(), (m.group(2) or "").strip()
            fr = arg or self.last.get("fr") or ""
            sentence = arg or self.last.get("sentence") or fr
            if not fr and not sentence:
                return {"op": "message",
                        "text": f"look something up first, or give a word: « {cmd} manger »"}
            req = {"explicit": bool(arg)}
            if cmd in ("conj", "conjugate"):
                req.update(op="lookup", text=fr, conj=True, autosave=False)
            elif cmd in ("def", "definition", "define"):
                req.update(op="definition", text=fr)
            elif cmd in ("ru", "multitran"):
                req.update(op="multitran", text=fr)
            elif cmd in ("say", "listen", "audio"):
                req.update(op="audio", text=fr)
            elif cmd in ("syn", "synonyms"):
                req.update(op="synonyms", text=fr)
            elif cmd in ("ex", "examples"):
                req.update(op="examples", text=fr, en=3, ru=1, follow_up=True)
            elif cmd in ("grammar", "check"):
                req.update(op="grammar", text=sentence)
            else:
                req.update(op="xray", text=sentence)
            return req
        if line.startswith("?"):               # free question to the tutor (context = last word)
            q = line.lstrip("?").strip()
            if q:
                return {"op": "ai", "text": q, "deep": line.startswith("??"), "question": True}
            return {"op": "message", "text": "\u00ab ? your question \u00bb — e.g. ? cuisiner vs cuire · "
                                              "? pourquoi \u00ab de \u00bb ici · ?? (detailed answer)"}
        if line[:1] in "!-":                   # old prefix habit → point at the words
            return {"op": "message", "text": "no prefixes anymore — say it in words: conj · def · ru · ex · "
                                              f"grammar · x · save N · ? question   (e.g. « def {line.split()[-1]} »)"}
        return {"op": "lookup", "text": line}  # a word, a French word, or a sentence

    def handle(self, line, progress=None):
        """The REPL: a line → a Result."""
        return self.run(self.parse(line), progress)

    @staticmethod
    def request_from_args(args):
        """argparse flags → a request. --json keeps its contract: ONE section,
        in the priority it has always had; the terminal gets the composite
        lookup (card + the sections asked for), like a REPL line would."""
        text = " ".join(args.words).strip()
        if args.json:
            if args.ai or args.profond:
                return {"op": "ai", "text": text, "deep": bool(args.profond),
                        "question": len(text.split()) > 1}
            if args.grammaire or args.xray:
                return {"op": "grammar" if args.grammaire else "xray", "text": text, "translate_first": True}
            if args.examples:
                return {"op": "examples", "text": text}
            if args.francais or args.dico:
                return {"op": "definition", "text": text, "translate": bool(args.dico)}
            if args.say or args.syn:
                return {"op": "synonyms", "text": text, "audio": bool(args.say)}
            if args.multitran:
                return {"op": "multitran", "text": text}
            if args.conj:
                return {"op": "conj", "text": text}
            return {"op": "lookup", "text": text, "autosave": False, "examples": True}
        if args.examples:
            return {"op": "examples", "text": text}
        if args.say or args.syn:
            return ({"op": "synonyms", "text": text, "audio": bool(args.say)} if args.syn
                    else {"op": "audio", "text": text})
        return {"op": "lookup", "text": text, "dict": args.dico, "ai": args.ai, "save": args.save,
                "multi": args.multitran, "conj": args.conj, "deep": args.profond, "fr": args.francais,
                "save_main": args.save_main, "gram": args.grammaire, "xray": args.xray}

    def handle_args(self, args, progress=None):
        """The one-shot CLI: flags → a Result (see request_from_args)."""
        return self.run(self.request_from_args(args), progress)

    # ---- the one dispatch -------------------------------------------------
    def run(self, req, progress=None):
        """Execute a request → a Result dict ("_kind" names it)."""
        self.fallback_note = ""
        op, text = req["op"], req.get("text", "")
        r = {"query": text}
        if op in ("setting", "help", "message", "save_sense", "history"):
            r = self._run_local(op, req)
        elif not text:
            r["_kind"] = "empty"
        elif op == "lookup":
            prev = self.no_autosave
            if req.get("autosave") is False:   # a follow-up / the panel never (re-)saves
                self.no_autosave = True
            try:
                r = lookup_result(self, text, req.get("dict"), req.get("ai"), req.get("save"),
                                  req.get("multi"), req.get("conj"), req.get("deep"), req.get("fr"),
                                  req.get("save_main"), req.get("gram"), req.get("xray"),
                                  examples=req.get("examples"), progress=progress)
            finally:
                self.no_autosave = prev
        elif op in ("grammar", "xray"):
            if req.get("translate_first"):     # English or Russian in: translate first, analyse the French
                lang = _sentence_lang(text)
                if lang != "fr":
                    try:
                        tr = translate(text, "fr")[0].strip()
                    except Exception:
                        tr = ""
                    if tr:
                        r.update({"source": text, "source_lang": lang, "translated": tr})
                        text = tr
            r.update(grammar_result(text) if op == "grammar" else xray_result(text))
            r["_kind"] = op
        elif op == "definition":
            target = text
            if req.get("translate") and detect_lang(text) != "fr":
                try:
                    target = translate_rich(text, session=self)[0] or text
                except Exception:
                    pass
            r.update(definition_result(target), _kind="definition")
        elif op == "multitran":
            r.update(multitran_result(text), _kind="multitran")
        elif op == "synonyms":
            r.update(synonyms_result(text), _kind="synonyms")
            if req.get("audio"):
                r.update(audio_result(text))
        elif op == "audio":
            r.update(audio_result(text), _kind="audio")
        elif op == "examples":
            r.update(examples_result(text, req.get("en", 4), req.get("ru", 2)), _kind="examples")
            if req.get("follow_up"):
                r["_follow_up"] = True
        elif op == "conj":
            r.update(conj_result(text), _kind="conjugation")
        elif op == "ai":
            r.update(ai_result(self, text, bool(req.get("deep")),
                               question=text if req.get("question") else None, progress=progress))
            r["_kind"] = "answer"
        else:
            raise ValueError(f"unknown request: {op}")
        if req.get("explicit"):                # « def maison » — the next follow-ups act on it
            if op in ("grammar", "xray"):
                self.last["sentence"] = text
            else:
                self.last["fr"] = text
        if self.fallback_note and "note" not in r:
            r["note"] = self.fallback_note
        self._remember_result(req, r)
        return r

    def _run_local(self, op, req):
        """Requests that touch no dictionary: settings, help, « save N », a hint."""
        if op == "help":
            return {"_kind": "help"}
        if op == "history":
            return {"_kind": "history", "history": [dict(t) for t in self.history]}
        if op == "message":
            return {"_kind": "message", "message": req["text"]}
        if op == "save_sense":
            n, senses = req["n"], self.last.get("senses") or []
            if not 1 <= n <= len(senses):
                return {"_kind": "message", "message": f"no sense {n} — the last card has {len(senses)}"}
            word = self.last.get("word", "")
            front, status, cnt = _save_term(senses[n - 1], word, detect_lang(word), quiet=True)
            return {"_kind": "saved", "saved": {"front": front, "status": status, "count": cnt, "auto": False}}
        return setting_result(self, req["line"])


def _public(obj):
    """A Result without its terminal-only fields (keys starting with "_")."""
    if isinstance(obj, dict):
        return {k: _public(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_public(v) for v in obj]
    return obj


_POS_FR = {"noun": "nom", "verb": "verbe", "adjective": "adjectif", "adverb": "adverbe",
           "preposition": "préposition", "pronoun": "pronom", "conjunction": "conjonction",
           "interjection": "interjection", "abbreviation": "abréviation",
           "article": "article", "phrase": "expression", "suffix": "suffixe",
           "auxiliary verb": "auxiliaire", "modal verb": "modal", "prefix": "préfixe"}


def translate_rich(word, tl="fr", sl="auto", session=None):
    """(translation, detected language, senses grouped by part of speech) —
    senses = [(pos, [(term, [back-translations]), …]), …]. This is the structure
    of a real dictionary, which the old flat "also: …" line squashed.

    When Google throttles us, MyMemory still gives the translation — a card with
    one sense beats an error message in the middle of a lesson."""
    try:
        data = _google_query(word, tl, sl)
    except (RateLimited, urllib.error.HTTPError, urllib.error.URLError):
        if tl != "fr":                       # FR → EN back-translation: no fallback
            raise
        src = detect_lang(word)
        tr, _, alts = translate_mymemory(word, src)
        if session is not None:
            session.fallback_note = "Google refused the query — translation via MyMemory (fewer senses)"
        lx = lexique_lookup(tr)
        # MyMemory gives no part of speech: only the main term can claim the one
        # Lexique knows; the alternatives stay in an unlabelled group.
        groups = [((lx["pos"] if lx else ""), [(tr, [])])]
        others = [(a, []) for a in alts[:3] if a.lower() != tr.lower()]
        if others:
            groups.append(("", others))
        return tr, src, groups
    if session is not None:
        session.fallback_note = ""
    translation = "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
    detected = data[2] if len(data) > 2 and isinstance(data[2], str) else None
    groups = []
    for entry in (data[1] or []) if len(data) > 1 else []:
        pos = _POS_FR.get(str(entry[0]).lower(), str(entry[0]).lower())
        terms = []
        for t in (entry[2] if len(entry) > 2 and entry[2] else []):
            if t and t[0]:
                # Google leaves the back-translations null for some words (« государство »).
                backs = t[1] if len(t) > 1 and isinstance(t[1], list) else []
                terms.append((t[0], [b for b in backs if b][:4]))
        if not terms and len(entry) > 1 and isinstance(entry[1], list):
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


def card_to_fr_result(session, word, src, translation, groups, examples=True):
    """RU/EN → FR card: {"direction": "to_fr", "src_lang", "translation", "lexique",
    "senses", "examples"} — the panels' contract — plus "_card" for the terminal:
    the senses renumbered so that the main translation is sense 1 ("save N"
    saves sense N), their ★ bands, back-translations, the hint. Sets
    session.last["senses"]."""
    out = {"direction": "to_fr", "src_lang": src, "translation": translation,
           "lexique": lexique_lookup(translation) if translation else None}
    senses = []
    for pos, terms in groups:
        for term, back in terms:
            front, lx = _fr_head(term)
            senses.append({"pos": pos, "term": term, "front": front, "back": back,
                           "gender": (lx["genre"] if lx else "") or "",
                           "band": lx["band"] if lx else "",
                           "cefr": (lx or {}).get("cefr") or ""})
    out["senses"] = senses
    out["examples"] = _tatoeba(translation, "eng") if translation else []
    # The terminal's rows. The main translation (the one autosave keeps) must be sense 1.
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
    fronts, rows, n = [], [], 0
    for pos, terms in groups[:4]:
        cells = []
        for term, back in terms[:4]:
            n += 1
            front, lex = _fr_head(term)
            fronts.append(front)
            cells.append((n, front, _BAND_STARS.get(lex["band"], "") if lex else ""))
        back = [b for b in terms[0][1] if b.lower() != word.lower()][:2]
        rows.append((pos, cells, back))
    session.last["senses"] = fronts
    shown = []
    if examples and translation:
        shown = _tatoeba(translation.split()[-1] if " " in translation else translation, "eng")
    session.last["hints"] = session.last.get("hints", 0) + 1
    out["_card"] = {"word": word, "src": src, "rows": rows, "examples": shown,
                    "hint": session.last["hints"] <= 3}
    return out


def render_card_to_fr(r):
    c = r["_card"]
    lines = [f"  {FLAG.get(c['src'], '🌐')} {BOLD}{c['word']}{RESET}"]
    if r.get("note"):
        lines.append(f"     {DIM}⚠ {r['note']}{RESET}")
    for pos, cells, back in c["rows"]:
        cs = [f"{DIM}{n}{RESET} {GREEN if n == 1 else ''}{front}{RESET}"
              + (f" {DIM}{stars}{RESET}" if stars else "") for n, front, stars in cells]
        tail = f"   {DIM}← {', '.join(back)}{RESET}" if back else ""
        lines.append(f"     {DIM}{pos:10}{RESET} " + "  ".join(cs) + tail)
    for fr, tr in c["examples"]:
        lines.append(f"     {DIM}« {fr} » — {tr}{RESET}")
    if c["hint"]:
        lines.append(f"     {DIM}{_FOLLOW_HINT}{RESET}")
    return lines


def card_fr_result(session, word, lex=None, examples=True):
    """Card for a FRENCH word: {"direction": "fr", "head", "lexique", "senses",
    "examples"} — the panels' contract — plus "_card" for the terminal: the head
    with the gender Wiktionary supplies when Lexique lacks it, the badges, the
    présent preview of a verb, the hint. Sets session.last["senses"]."""
    head, lex2 = _fr_head(word)
    out = {"direction": "fr", "head": head, "lexique": lex2}
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
    try:
        _, _, groups = translate_rich(word, tl="en", sl="fr", session=session)   # explicit sl → grouped senses
    except Exception:
        groups = []
        try:                                   # fallback: MyMemory fr→en (1 sense)
            t, _, _ = translate_mymemory(word, "fr", tl="en")
            if t and t.lower() != word.lower():
                groups = [("", [(t, [])])]
        except Exception:
            pass
    out["senses"] = [{"pos": p, "terms": [t for t, _ in ts]} for p, ts in groups]
    session.last["senses"] = [head]
    session.last["hints"] = session.last.get("hints", 0) + 1
    present = None
    if lex and lex["cgram"].startswith(("VER", "AUX")) and not session.last.get("conj_shown"):
        inf, data, _ = _conj_query(lex["lemma"])
        if data and data.get("présent"):
            present = data["présent"]
    out["examples"] = _tatoeba(word, "eng") if examples else []
    out["_card"] = {"word": word, "head": head, "bits": bits,
                    "ipa": (lex or {}).get("ipa") or "", "groups": groups[:3],
                    "hint": session.last["hints"] <= 3, "present": present,
                    "examples": out["examples"] if examples else []}
    return out


def render_card_fr(r):
    c = r["_card"]
    line = f"  🇫🇷 {BOLD}{c['word']}{RESET}" + (f"   {DIM}{' · '.join(c['bits'])}{RESET}" if c["bits"] else "")
    if c["ipa"]:
        line += f"   {DIM}/{c['ipa']}/{RESET}"
    lines = [line]
    for pos, terms in c["groups"]:
        lines.append(f"     {DIM}{pos:10}{RESET} " + " · ".join(t for t, _ in terms[:6]))
    if c["hint"]:
        lines.append(f"     {DIM}{_FOLLOW_HINT}{RESET}")
    if c["present"]:
        lines.append(f"     {DIM}présent{RESET}    " + "  ·  ".join(c["present"])
                     + f"   {DIM}(« conj » for the full table){RESET}")
    for fr, tr in c["examples"]:
        lines.append(f"     {DIM}« {fr} » — {tr}{RESET}")
    return lines


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


def audio_result(word):
    """{"audio": {"path", "error"}} — the native recording, fetched and cached."""
    path, err = audio_for(word)
    return {"audio": {"path": path, "error": err}, "_word": word}


def render_audio(r):
    a = r["audio"]
    if a["error"]:
        return [f"  {DIM}🔈 {a['error']}{RESET}"]
    return [f"  🔈 {BOLD}{r['_word']}{RESET}  {DIM}(Wiktionnaire · Commons){RESET}"]


def _play_audio(r):
    """After render(): play the recording a « say » fetched (macOS: afplay
    handles the MP3). The driver never plays — --serve's panel does."""
    path = (r.get("audio") or {}).get("path")
    if not path:
        return
    if sys.platform == "win32":                       # no afplay: hand it to the default player
        try:
            os.startfile(path)                        # noqa: S606 — a local MP3 we just wrote
        except OSError as e:
            print(f"  {YELLOW}✗ cannot play: {e}{RESET}")
        return
    player = shutil.which("afplay") or shutil.which("ffplay")
    if not player:
        print(f"     {DIM}{path}{RESET}")
        return
    try:
        subprocess.run([player, path] + ([] if player.endswith("afplay")
                                         else ["-nodisp", "-autoexit"]),
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"     {DIM}({e}){RESET}")


def synonyms_result(word):
    """{"synonyms", "homophones", "cefr", "ipa"} — Wiktionnaire synonyms, the
    homophones Lexique settles offline (same `phon`) plus the ones the
    Wiktionnaire happens to list."""
    try:
        entry = wiktionary(word)
    except Exception:
        entry = None
    homo = (entry or {}).get("homo") or []
    known = {_deaccent(h["word"]) for h in homo}
    homo = homo + [{"word": w, "note": ""} for w in homophones(word)
                   if _deaccent(w) not in known]
    lx = lexique_lookup(word)
    return {"synonyms": (entry or {}).get("syn") or [], "homophones": homo,
            "cefr": (lx or {}).get("cefr"), "ipa": (lx or {}).get("ipa"), "_word": word}


def render_synonyms(r):
    """« syn » — synonyms and homophones."""
    lines = []
    if r["synonyms"]:
        lines.append(f"  {CYAN}≈ synonymes de {r['_word']}{RESET}  {_wikt_words(r['synonyms'], 12)}")
    if r["homophones"]:
        lines.append(f"  {CYAN}♪ homophones{RESET}  {_wikt_words(r['homophones'], 12)}")
    if not lines:
        lines.append(f"  {DIM}≈ no synonyms listed for « {r['_word']} »{RESET}")
    return lines


def _wikt_words(items, limit=8):
    """[{"word","note"}] → « minet · greffier (familier) · matou »."""
    out = []
    for it in items[:limit]:
        out.append(it["word"] + (f" {DIM}({it['note']}){RESET}" if it.get("note") else ""))
    return " · ".join(out)


def definition_result(word):
    """Result section of a Wiktionary lookup: {"definition": {...} | None} plus
    "definition_error" when the request failed — the panels' contract — and,
    for the terminal / the save block, "_entry" (the raw entry), "_ipa" (the
    Wiktionary IPA alone; the JSON falls back to Lexique) and "_word"."""
    e, out = None, {"_word": word}
    try:
        e = wiktionary(word)
    except Exception as exc:                  # say why: the panel shows it
        out["definition_error"] = f"{type(exc).__name__}: {exc}"
    if e:
        known = {_deaccent(h["word"]) for h in (e.get("homo") or [])}
        homo = (e.get("homo") or []) + [{"word": w, "note": ""}
                                        for w in homophones(e["lemma"])
                                        if _deaccent(w) not in known]
        lx = lexique_lookup(e["lemma"])
        out["definition"] = {"word": e["lemma"], "ipa": e["ipa"] or (lx or {}).get("ipa"),
                             "gender": e["gender"], "pos": e["pos"], "defs": e["defs"],
                             "etym": e.get("etym"), "syn": e.get("syn") or [],
                             "homo": homo, "ru": e.get("ru") or [],
                             "cefr": (lx or {}).get("cefr") or "",
                             "has_audio": bool(e.get("audio"))}
        out["_ipa"] = e["ipa"]
    else:
        out["definition"] = None
    out["_entry"] = e
    return out


def render_definition(r):
    """The Wiktionary entry as the terminal prints it."""
    d = r["definition"]
    if not d:
        return [f"  {DIM}📖 (no Wiktionary entry for \u00ab {r['_word']} \u00bb){RESET}"]
    head = f"  {CYAN}📖 {d['word']}{RESET}"
    if r["_ipa"]:
        head += f"  {DIM}[{r['_ipa']}]{RESET}"
    if d["gender"]:
        head += f"  {DIM}·{RESET} {d['gender']}"
    elif d["pos"]:
        head += f"  {DIM}·{RESET} {d['pos']}"
    lines = [head]
    for i, x in enumerate(d["defs"], 1):
        lines.append(f"     {DIM}{i}.{RESET} {x}")
    if d["etym"]:
        lines.append(f"     {DIM}🌱 etym. {d['etym']}{RESET}")
    if d["syn"]:
        lines.append(f"     {DIM}≈ synonymes{RESET} {_wikt_words(d['syn'])}")
    if d["homo"]:
        lines.append(f"     {DIM}♪ homophones{RESET} {_wikt_words(d['homo'])}")
    if d["has_audio"]:
        lines.append(f"     {DIM}🔈 « say » to hear it{RESET}")
    return lines


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


def ai_explain(word, deep=False):
    """Card for a word ("!a word" / "-a word")."""
    prompt = _ai_prompt_deep(word) if deep else _ai_prompt(word)
    return llm_complete(_TUTOR_SYS, prompt, 1100 if deep else 400, deep=deep)


def _turn_line(t):
    """One history turn, in words (for the tutor's prompt and « history »)."""
    k = t["kind"]
    if k == "lookup":
        s = f"Looked up \u00ab {t['query']} \u00bb"
        s += (f" \u2192 \u00ab {t['fr']} \u00bb" if t["fr"].lower() != t["query"].lower()
              else " (a French word)")
        if t.get("sections"):
            s += f" ({', '.join(t['sections'])} shown)"
        if t.get("saved"):
            s += f", saved \u00ab {t['saved']} \u00bb"
        return s
    if k == "grammar":
        fixed = t.get("corrected")
        return (f"Grammar check: \u00ab {t['sentence']} \u00bb"
                + (f" \u2192 \u00ab {fixed} \u00bb" if fixed and fixed != t["sentence"] else " (correct)"))
    if k == "xray":
        return f"X-ray of \u00ab {t['sentence']} \u00bb"
    if k == "question":
        return f"Asked: {t['question']}\n  Answered: {t['answer']}"
    label = {"definition": "Definition", "multitran": "Russian (Multitran)", "synonyms": "Synonyms",
             "examples": "Examples", "audio": "Pronunciation", "conj": "Conjugation"}.get(k, k)
    return f"{label} of \u00ab {t['fr']} \u00bb"


def _trim(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "\u2026"


def ai_ask(session, question, deep=False):
    """Free-form question to the tutor, in context: the session's history
    (lookups, saves, grammar checks, earlier questions and answers — oldest
    first, capped), plus the last word / sentence when the history does not
    already show them (a one-shot « --context »)."""
    last, hist = session.last, session.history
    ctx = []
    if last["sentence"] and not any(t.get("sentence") == last["sentence"] for t in hist):
        ctx.append(f"Last sentence analysed: \u00ab {last['sentence']} \u00bb.")
    if last["word"] and not any(t["kind"] == "lookup" and last["word"] in (t["query"], t["fr"]) for t in hist):
        ctx.append(f"Last word looked up: \u00ab {last['word']} \u00bb"
                   + (f" (\u2192 \u00ab {last['fr']} \u00bb)" if last["fr"] else "") + ".")
    parts = []
    if hist:
        parts.append("Earlier in this session, oldest first:\n" + "\n".join("- " + _turn_line(t) for t in hist))
    if ctx:
        parts.append("Context: " + " ".join(ctx))
    user = ("\n\n".join(parts) + "\n\n" if parts else "") + "Question: " + question
    text, err = llm_complete(_TUTOR_SYS, user, 700 if deep else 350, deep=deep)
    if text:
        session.remember({"kind": "question", "question": _trim(question, 200),
                          "answer": _trim(text, HISTORY_ANSWER_CHARS)})
    return text, err


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


def ai_result(session, word, deep, question=None, progress=None):
    """{"answer", "error", "model"} from the tutor — a card for a word, or the
    answer to a free-form question (with the session's last word / sentence as
    context). `progress(line)` is called before the call: the terminal shows
    « thinking… », --serve nothing."""
    icon = "🧠" if deep else "🤖"
    label = _llm_label()
    if progress:
        progress(f"  {CYAN}{icon} {label} is thinking…{RESET}")
    t0 = time.time()
    text, err = (ai_ask(session, question, deep) if question else ai_explain(word, deep=deep))
    return {"answer": text, "error": err, "model": label,
            "_deep": deep, "_elapsed": time.time() - t0}


def render_ai(r):
    icon = "🧠" if r["_deep"] else "🤖"
    pad = " " * 12
    label = r["model"] + f"  {DIM}{r['_elapsed']:.1f}s{RESET}{CYAN}"
    if r["answer"]:
        lines = [f"  {CYAN}{icon} {label} :{RESET}{pad}"]
        lines += [f"     {line}" for line in _render_md(r["answer"])]
        return lines
    return [f"  {YELLOW}{icon} AI unavailable:{RESET} {r['error']}{pad}"]


def _progress(line):
    """The terminal's « thinking… » line, overwritten by the answer."""
    print(line, end="\r", flush=True)


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


_STORE_FIELDS = ("front", "lemma", "sens", "gloss", "pos", "gender", "example", "example_en",
                 "src_word", "src_lang", "tier", "cefr", "ipa")


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


# ---------------------------------------------------------------------------
# Spaced repetition — the store IS the deck.
#
# An Anki-style SM-2: new → learning (1 min, 10 min) → review, the interval
# multiplied by an ease that Again/Hard/Easy nudge. Each entry keeps its own
# state under "srs"; nothing else changes. Anki stays an optional export.
# ---------------------------------------------------------------------------

SRS_STEPS = (60, 600)                 # learning steps, seconds
SRS_NEW_PER_DAY = 20
SRS_AGAIN, SRS_HARD, SRS_GOOD, SRS_EASY = 1, 2, 3, 4


def _srs_now():
    return datetime.now().replace(microsecond=0)


def _srs_parse(iso):
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def srs_state(entry):
    """The scheduling record of an entry, with defaults for a fresh word."""
    s = entry.get("srs") or {}
    return {"state": s.get("state", "new"), "due": s.get("due", ""),
            "ivl": int(s.get("ivl", 0)), "ease": int(s.get("ease", 2500)),
            "reps": int(s.get("reps", 0)), "lapses": int(s.get("lapses", 0)),
            "step": int(s.get("step", 0))}


def srs_grade(state, ease, now=None):
    """Apply a grade (1 again · 2 hard · 3 good · 4 easy). Returns the new state."""
    now = now or _srs_now()
    st = dict(state)
    st["reps"] += 1
    day = 86400

    def due_in(seconds):
        return (now + timedelta(seconds=seconds)).isoformat(timespec="seconds")

    def graduate(days, easy=False):
        st.update(state="review", step=0, ivl=max(1, int(days)))
        if easy:
            st["ease"] = st["ease"] + 150
        st["due"] = (now + timedelta(days=st["ivl"])).isoformat(timespec="seconds")

    if st["state"] in ("new", "learning", "relearning"):
        if ease == SRS_EASY:
            graduate(4, easy=True)
        elif ease == SRS_AGAIN:
            st.update(state="learning" if st["state"] == "new" else st["state"],
                      step=0, due=due_in(SRS_STEPS[0]))
        elif ease == SRS_HARD:
            st.update(state="learning" if st["state"] == "new" else st["state"],
                      due=due_in(SRS_STEPS[min(st["step"], len(SRS_STEPS) - 1)]))
        else:                                              # good: next step, or out
            nxt = st["step"] + 1
            if st["state"] == "relearning" or nxt >= len(SRS_STEPS):
                graduate(1 if st["state"] != "relearning" else max(1, st["ivl"]))
            else:
                st.update(state="learning", step=nxt, due=due_in(SRS_STEPS[nxt]))
        return st

    # review
    if ease == SRS_AGAIN:
        st["lapses"] += 1
        st["ease"] = max(1300, st["ease"] - 200)
        st.update(state="relearning", step=0, ivl=max(1, st["ivl"] // 2),
                  due=due_in(SRS_STEPS[-1]))
        return st
    if ease == SRS_HARD:
        st["ease"] = max(1300, st["ease"] - 150)
        st["ivl"] = max(st["ivl"] + 1, int(st["ivl"] * 1.2))
    elif ease == SRS_GOOD:
        st["ivl"] = max(st["ivl"] + 1, int(st["ivl"] * st["ease"] / 1000))
    else:
        st["ease"] += 150
        st["ivl"] = max(st["ivl"] + 2, int(st["ivl"] * st["ease"] / 1000 * 1.3))
    st["due"] = (now + timedelta(days=st["ivl"])).isoformat(timespec="seconds")
    return st


def _card_back(entry):
    """The lines behind a card: the meaning (English gloss, plus the Russian
    you typed when that is how you got there), then the example and its
    translation."""
    sens = (entry.get("sens") or "").strip()
    gloss = (entry.get("gloss") or "").strip()
    lemma = (entry.get("lemma") or "").strip()
    typed_is_french = entry.get("src_lang") == "fr" or (sens and _deaccent(sens) == _deaccent(lemma))
    if entry.get("tier") == "tutor":
        first = sens
    elif gloss and sens and not typed_is_french and _deaccent(sens) != _deaccent(gloss):
        first = f"{sens} · {gloss}"
    else:
        first = gloss or ("" if typed_is_french else sens)
    lines = [first]
    if entry.get("example"):
        lines.append(entry["example"])
        if entry.get("example_en"):
            lines.append(entry["example_en"])
    return [l for l in lines if l]


def _srs_card(entry):
    st = srs_state(entry)
    return {"key": entry.get("key", ""), "front": entry.get("front") or entry.get("lemma", ""),
            "back": _card_back(entry), "state": st["state"], "ivl": st["ivl"],
            "reps": st["reps"], "due": st["due"], "gender": _short_gender(entry.get("gender", "")),
            "pos": entry.get("pos", ""), "cefr": entry.get("cefr", ""), "ipa": entry.get("ipa", "")}


def _short_gender(g):
    g = (g or "").lower()
    if g in ("m", "f"):
        return g
    if "fémin" in g or "femin" in g:
        return "f"
    if "mascul" in g:
        return "m"
    return ""


def _gloss_en(lemma):
    """An English gloss of a French lemma — Google, cached, or nothing."""
    try:
        data = _google_query(lemma, tl="en", sl="fr")        # sl=auto mistakes « ligne » for English
        tr = "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
        return tr                                            # a cognate (« orientation ») is a fine gloss
    except Exception:
        return ""


def _example_for(lemma):
    """A real sentence with the word, and its English — Tatoeba, cached."""
    try:
        ex = _tatoeba(lemma, "eng", limit=1)
    except Exception:
        ex = []
    return (ex[0][0], ex[0][1]) if ex else ("", "")


def enrich_entry(e, network=True):
    """Fill what a card needs and the entry lacks. Returns what changed."""
    changed = []
    lemma = e.get("lemma") or e.get("front") or ""
    if not lemma:
        return changed
    tier = e.get("tier") or ""
    # A tutor note keeps its answer as the back; a sentence has no example of itself.
    wants_gloss = tier != "tutor"
    wants_example = tier not in ("tutor", "sentence")
    g = _short_gender(e.get("gender", ""))
    if g != (e.get("gender") or ""):
        e["gender"] = g
        changed.append("gender")
    lex = lexique_lookup(lemma) if (not e.get("cefr") or not e.get("ipa")) else None
    if lex:
        if not e.get("cefr") and lex.get("cefr"):
            e["cefr"] = lex["cefr"]; changed.append("cefr")
        if not e.get("ipa") and lex.get("ipa"):
            e["ipa"] = lex["ipa"]; changed.append("ipa")
        if not e.get("gender") and lex.get("genre"):
            e["gender"] = lex["genre"]; changed.append("gender")
        if not e.get("pos") and lex.get("pos"):
            e["pos"] = lex["pos"]; changed.append("pos")
    sens = (e.get("sens") or "").strip()
    typed_is_french = e.get("src_lang") == "fr" or (sens and _deaccent(sens) == _deaccent(lemma))
    if not e.get("gloss") and wants_gloss:
        if e.get("src_lang") == "en" and sens and not typed_is_french:
            e["gloss"] = sens; changed.append("gloss")
        elif network:
            gl = _gloss_en(lemma)
            if gl:
                e["gloss"] = gl; changed.append("gloss")
    # A conjugation stub is not an example.
    if (e.get("example") or "").startswith("prés. :"):
        e["example"] = ""; changed.append("example")
    if not e.get("example") and network and wants_example:
        fr, en = _example_for(lemma)
        if fr:
            e["example"], e["example_en"] = fr, en
            changed.append("example")
    return changed


def run_enrich(as_json=False):
    """dico --enrich: backfill gloss, example, IPA, CEFR, gender on every saved word."""
    data = store_load()
    entries = data["entries"]
    touched = 0
    for i, e in enumerate(entries, 1):
        changed = enrich_entry(e)
        if changed:
            touched += 1
            store_save(data)                          # resumable: every change sticks
            if not as_json:
                print(f"  {GREEN}✓{RESET} {e.get('front') or e.get('lemma')}  "
                      f"{DIM}{', '.join(changed)}{RESET}")
        elif not as_json:
            print(f"  {DIM}· {e.get('front') or e.get('lemma')}{RESET}")
        if i % 10 == 0:
            time.sleep(0.4)                           # be gentle with Google and Tatoeba
    store_render()
    if as_json:
        print(json.dumps({"entries": len(entries), "enriched": touched}, ensure_ascii=False))
    else:
        print(f"{BOLD}✓ {touched} of {len(entries)} entries enriched.{RESET}")


def srs_queue(new_limit=SRS_NEW_PER_DAY, now=None):
    """What to review now: learning steps that are due, reviews due today,
    then the newest words never seen (at most `new_limit`). Plus the counts."""
    now = now or _srs_now()
    end_of_day = now.replace(hour=23, minute=59, second=59)
    learning, review, new = [], [], []
    for e in store_load()["entries"]:
        if not (e.get("front") or e.get("lemma")):
            continue
        st = srs_state(e)
        due = _srs_parse(st["due"])
        if st["state"] == "new":
            new.append(e)
        elif st["state"] in ("learning", "relearning"):
            if due is None or due <= now:
                learning.append((due or now, e))
        elif due is None or due <= end_of_day:
            review.append((due or now, e))
    learning.sort(key=lambda t: t[0])
    review.sort(key=lambda t: t[0])
    new.sort(key=lambda e: e.get("last_seen", ""), reverse=True)
    cards = [_srs_card(e) for _, e in learning] + [_srs_card(e) for _, e in review] \
        + [_srs_card(e) for e in new[:new_limit]]
    counts = {"learning": len(learning), "due": len(review), "new": len(new)}
    return cards, counts


def srs_answer(key, ease):
    """Grade one word. Returns its card, rescheduled — or None if unknown."""
    if ease not in (SRS_AGAIN, SRS_HARD, SRS_GOOD, SRS_EASY):
        raise ValueError("ease must be 1, 2, 3 or 4")
    data = store_load()
    for e in data["entries"]:
        if e.get("key") == key:
            e["srs"] = srs_grade(srs_state(e), ease)
            store_save(data)
            return _srs_card(e)
    return None


def run_review():
    """dico --review: the deck in the terminal. Space/⏎ shows, 1–4 grades, q quits."""
    cards, counts = srs_queue()
    if not cards:
        print(f"{GREEN}✓ Nothing due.{RESET} {DIM}Look words up — they become cards.{RESET}")
        return
    print(f"\n{BOLD}🎴 {len(cards)} card(s){RESET}  {DIM}{counts['due']} due · "
          f"{counts['learning']} learning · {counts['new']} new{RESET}\n")
    done = 0
    i = 0
    while i < len(cards):
        c = cards[i]
        print(f"{BOLD}{c['front']}{RESET}  {DIM}{c['state']}{RESET}")
        try:
            input(f"   {DIM}⏎ to show{RESET} ")
        except (EOFError, KeyboardInterrupt):
            break
        for line in c["back"]:
            print(f"   {line}")
        try:
            ans = input(f"   {DIM}1 again · 2 hard · 3 good · 4 easy · q{RESET} ").strip() or "3"
        except (EOFError, KeyboardInterrupt):
            break
        if ans.lower().startswith("q"):
            break
        if ans not in "1234" or len(ans) != 1:
            continue
        srs_answer(c["key"], int(ans))
        done += 1
        if ans == "1":
            cards.append(c)
        i += 1
        print()
    print(f"{GREEN}✓ {done} graded.{RESET}")


# ---------------------------------------------------------------------------
# Backup: the store's directory is a git repository with a remote.
# ---------------------------------------------------------------------------

def _git(args, cwd):
    """Run git quietly. Returns (ok, output)."""
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def cards_repo():
    """The directory holding the store, if it is a git repository — else None."""
    d = os.path.dirname(os.path.abspath(STORE))
    return d if os.path.isdir(os.path.join(d, ".git")) else None


def cards_autosync():
    """Back up after every save? On by default once the store lives in a repo."""
    v = _early_cfg("cards_autosync")
    return bool(cards_repo()) if v is None else bool(v)


def run_backup(as_json=False, pull_only=False):
    """dico --backup: pull what other sources wrote, render vocabulaire.md,
    commit and push. Silent when nothing changed."""
    repo = cards_repo()
    if not repo:
        msg = {"error": f"{os.path.dirname(os.path.abspath(STORE))} is not a git repository"}
        return print(json.dumps(msg) if as_json else f"{YELLOW}✗ {msg['error']}{RESET}")
    ok_remote, remote = _git(["remote", "get-url", "origin"], repo)
    steps = []
    if ok_remote:
        ok, out = _git(["pull", "--rebase", "--autostash", "-q", "origin", "HEAD"], repo)
        steps.append(("pull", ok, out))
        if not ok:
            _git(["rebase", "--abort"], repo)
    if not pull_only:
        try:
            store_render(os.path.join(repo, "vocabulaire.md"))
        except Exception as e:                  # the view is optional
            steps.append(("render", False, str(e)))
        n = len(store_load()["entries"])
        _git(["add", "-A"], repo)
        ok, out = _git(["diff", "--cached", "--quiet"], repo)
        if not ok:                              # something to commit
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            ok, out = _git(["-c", "commit.gpgsign=false", "commit", "-q", "-m", f"cards: {n} words — {stamp}"], repo)
            steps.append(("commit", ok, out))
        if ok_remote:
            ok, out = _git(["push", "-q", "origin", "HEAD"], repo)
            steps.append(("push", ok, out))
    failed = [(k, o) for k, ok, o in steps if not ok]
    result = {"repo": repo, "remote": remote if ok_remote else "", "steps": [k for k, ok, _ in steps if ok],
              "error": "; ".join(f"{k}: {o.splitlines()[-1] if o else '?'}" for k, o in failed) or None}
    if as_json:
        return print(json.dumps(result, ensure_ascii=False))
    if failed:
        print(f"{YELLOW}✗ backup: {result['error']}{RESET}")
    else:
        done = ", ".join(result["steps"]) or "nothing to do"
        print(f"{GREEN}✓ cards backed up{RESET} {DIM}({done}) → {remote if ok_remote else repo}{RESET}")


def _config_set(**kv):
    """Write keys into ~/.dico_config.json (chmod 600), keeping the rest."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    for k, v in kv.items():
        if v is None:
            cfg.pop(k, None)
        else:
            cfg[k] = v
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(CONFIG_PATH, 0o600)


def run_backup_init(remote="", as_json=False):
    """dico --backup-init [URL]: give the cards a git repository of their own.

    The store moves to <its folder>/cards/ (or stays where it is when that
    folder is already a repo), gets a README and a .gitignore, a first
    commit, and — with a URL — a remote and a first push. The config then
    points at the new place and turns the automatic backup on."""
    result = {"repo": "", "remote": remote or "", "moved": False, "pushed": False, "error": None}
    repo = cards_repo()
    if not repo:
        base = os.path.dirname(os.path.abspath(STORE))
        repo = base if os.path.basename(base) == "cards" else os.path.join(base, "cards")
        os.makedirs(repo, exist_ok=True)
        target = os.path.join(repo, "dico_vocab.json")
        if os.path.abspath(STORE) != os.path.abspath(target):
            if os.path.exists(STORE):
                shutil.move(STORE, target)
            elif not os.path.exists(target):
                with open(target, "w", encoding="utf-8") as f:
                    json.dump({"version": 1, "entries": []}, f)
            result["moved"] = True
            _config_set(store_path=target)
            globals()["STORE"] = target
        readme = os.path.join(repo, "README.md")
        if not os.path.exists(readme):
            with open(readme, "w", encoding="utf-8") as f:
                f.write("# dico — cards\n\nThe vocabulary store of dico: every word looked up, with its "
                        "gloss, example, IPA, CEFR level and spaced-repetition state. `dico_vocab.json` "
                        "is the source of truth; `vocabulaire.md` is regenerated from it.\n\n"
                        "`dico --backup` pulls, renders, commits and pushes.\n")
        with open(os.path.join(repo, ".gitignore"), "w", encoding="utf-8") as f:
            f.write(".DS_Store\n*.before-*.json\n")
        ok, out = _git(["init", "-q", "-b", "main"], repo)
        if not ok:
            result["error"] = f"git init: {out or 'is git installed? (xcode-select --install)'}"
            return print(json.dumps(result)) if as_json else print(f"{YELLOW}✗ {result['error']}{RESET}")
        store_render(os.path.join(repo, "vocabulaire.md"))
        _git(["add", "-A"], repo)
        _git(["-c", "commit.gpgsign=false", "-c", "user.name=dico", "-c", "user.email=dico@localhost",
              "commit", "-q", "-m", "cards: first backup"], repo)
    result["repo"] = repo
    if remote:
        ok, cur = _git(["remote", "get-url", "origin"], repo)
        if ok:
            _git(["remote", "set-url", "origin", remote], repo)
        else:
            _git(["remote", "add", "origin", remote], repo)
        ok, out = _git(["push", "-q", "-u", "origin", "HEAD"], repo)
        result["pushed"] = ok
        if not ok:
            lines = out.splitlines() or ["?"]
            last = next((l for l in lines if "fatal:" in l or "error:" in l or "denied" in l.lower()), lines[-1])
            result["error"] = (f"push: {last.strip()} — create an empty repository at that address first "
                               "(no README), then press again")
    _config_set(cards_autosync=True)
    if as_json:
        return print(json.dumps(result, ensure_ascii=False))
    if result["error"]:
        print(f"{YELLOW}✗ {result['error']}{RESET}")
    print(f"{GREEN}✓ cards repository:{RESET} {repo}" + (f"  → {remote}" if result["pushed"] else ""))


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


def conj_result(text):
    """{"conjugation": {"infinitive", "tenses", "error"}} for a verb (infinitive
    or conjugated form; « manger présent » filters to one tense — "_conj" keeps
    the word and the tense for the terminal)."""
    w, tense = _split_tense(text)
    inf, data, err, from_fr = conjugate_lookup(w)
    return {"conjugation": {"infinitive": inf, "tenses": data, "error": err},
            "_conj": {"word": w, "tense": tense, "from_fr": from_fr}}


def render_conjugation(r):
    c, extra = r["conjugation"], r["_conj"]
    inf, tenses, tense, word = c["infinitive"], c["tenses"], extra["tense"], extra["word"]
    shown = tenses
    if tenses and tense:
        shown = {k: v for k, v in tenses.items() if k == tense}
    lines = []
    if shown:
        if inf and _deaccent(inf) != _deaccent(word):
            lines.append(f"  {DIM}\u00ab {word} \u00bb → a form of{RESET} {BOLD}{inf}{RESET}")
        lines.append(f"  {CYAN}🔄 {inf}{RESET}  {DIM}(conjugation){RESET}")
        lines += [f"     {line}" for line in _conj_lines(shown)]   # aligned pronoun × tense grid
    elif tenses and tense:
        lines.append(f"  {DIM}🔄 (\u00ab {tense} \u00bb unavailable for \u00ab {inf} \u00bb){RESET}")
    elif c["error"]:
        lines.append(f"  {DIM}🔄 conjugation: {c['error']}{RESET}")
    else:
        lines.append(f"  {DIM}🔄 (verb not found: \u00ab {word} \u00bb){RESET}")
    return lines


def examples_result(text, en=4, ru=2):
    """{"examples": {"en": [{"fr", "en"}], "ru": [{"fr", "ru"}]}} — Tatoeba."""
    return {"examples": {"en": [{"fr": s, "en": t} for s, t in _tatoeba(text, "eng", limit=en)],
                         "ru": [{"fr": s, "ru": t} for s, t in _tatoeba(text, "rus", limit=ru)]},
            "_word": text}


def render_examples(r, follow_up=False):
    """The sentences; `follow_up` is the REPL's « ex » (indented, dimmed)."""
    ex = r["examples"]
    pairs = [(x["fr"], x["en"]) for x in ex["en"]] + [(x["fr"], x["ru"]) for x in ex["ru"]]
    if follow_up:
        lines = [f"     {DIM}« {s} » — {t}{RESET}" for s, t in pairs]
        return lines or [f"  {DIM}no example sentences found for « {r['_word']} »{RESET}"]
    lines = [f"  « {s} » — {DIM}{t}{RESET}" for s, t in pairs]
    return lines or [f"  {DIM}no examples found for « {r['_word']} »{RESET}"]


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


def multitran_result(word):
    """{"multitran": {"direction", "lines", "groups", "error"[, "wiktionary_ru"]}}
    — offline Multitran; without it, the Wiktionnaire's Russian."""
    lines, direction, err = multitran_lookup(word)
    groups, _ = multitran_structured(word)
    m = {"direction": direction, "lines": lines or [], "groups": groups, "error": err}
    if not groups and not (lines or []):          # no Multitran → Wiktionary's Russian
        try:
            m["wiktionary_ru"] = (wiktionary(word) or {}).get("ru") or []
        except Exception:
            pass
    return {"multitran": m, "_word": word}


def render_multitran(r):
    m = r["multitran"]
    arrow = "ru→fr" if m["direction"] == "rufr" else "fr→ru"
    lines = []
    if m["lines"]:
        lines.append(f"  {CYAN}📚 Multitran ({arrow}){RESET}")
        for ln in m["lines"][:40]:
            lines.append(f"     {ln}")
        if len(m["lines"]) > 40:
            lines.append(f"     {DIM}… (full entry in Dictionary.app — ⌃⌘D){RESET}")
    elif m.get("wiktionary_ru"):               # Wiktionary carried the Russian instead
        lines.append(f"  {CYAN}📚 russe {DIM}(Wiktionnaire){RESET}")
        for x in m["wiktionary_ru"][:8]:
            bits = x["word"]
            if x.get("tr"):
                bits += f"  {DIM}[{x['tr']}]{RESET}"
            if x.get("gender"):
                bits += f"  {DIM}{x['gender']}.{RESET}"
            lines.append(f"     {bits}")
    elif m["error"]:
        lines.append(f"  {DIM}📚 Multitran: {m['error']}{RESET}")
    else:
        lines.append(f"  {DIM}📚 (not in Multitran {arrow}: « {r['_word']} »){RESET}")
    return lines


def xray_result(sentence):
    """Result section of the x-ray: {"sentence", "xray": [token dicts]} — the
    panels' contract — plus, for the terminal, "_rows" (the table, richer verb
    detection and a batch gloss), "_translation" and "_src_tag"."""
    sentence = sentence.strip()
    out = {"sentence": sentence, "_translation": "", "_rows": [], "_src_tag": ""}
    try:                                       # translation of the whole sentence (1 call)
        tr, _, _ = translate(sentence, tl="en")
        if tr and _deaccent(tr.lower()) != _deaccent(sentence.lower()):
            out["_translation"] = tr
    except Exception:
        pass
    spacy_on = config_load().get("xray_spacy", True)
    sp = _spacy_tokens(sentence) if spacy_on else None
    # The panels' tokens (what --json has always emitted).
    toks = ([(t["text"].strip("-–"), t["lemma"], t["pos"], _DEP_FR.get(t["dep"], t["dep"]))
             for t in sp if t["pos"] != "PUNCT"] if sp
            else [(w, None, None, "") for w in _xray_tokens(sentence)])
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
    # The terminal's table.
    if sp:
        toks = [(t["text"], t["lemma"], t["pos"], _DEP_FR.get(t["dep"], t["dep"]))
                for t in sp if t["pos"] != "PUNCT" and t["text"].strip()]
        out["_src_tag"] = "spaCy + Lexique + conjugations"
    else:
        toks = [(w, None, None, "") for w in _xray_tokens(sentence)]
        out["_src_tag"] = ("Lexique + conjugations — spaCy off (\u00ab :spacy on \u00bb for roles)"
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
    out["_rows"] = rows
    return out


def render_xray(r):
    """The x-ray as the terminal prints it: sentence, translation, table, source."""
    lines = [f"  {BOLD}🩻 {r['sentence']}{RESET}"]
    if r["_translation"]:
        lines.append(f"  {DIM}→{RESET} {r['_translation']}")
    rows = r["_rows"]
    heads = ("word", "lemma", "pos", "tense", "gender·freq", "role", "meaning")
    widths = [max(len(h), *(len(x[i]) for x in rows)) for i, h in enumerate(heads)]
    lines.append("  " + DIM + "  ".join(h.ljust(widths[i]) for i, h in enumerate(heads)).rstrip() + RESET)
    for x in rows:
        cells = []
        for i, c in enumerate(x):
            c = c.ljust(widths[i])
            if i == 0:
                c = f"{BOLD}{c}{RESET}"
            elif i == 3 and x[3]:
                c = f"{GREEN}{c}{RESET}"
            elif i in (5, 6) and x[i]:
                c = f"{DIM}{c}{RESET}"
            cells.append(c)
        lines.append("  " + "  ".join(cells).rstrip())
    lines.append(f"  {DIM}({r['_src_tag']}){RESET}")
    return lines


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


def grammar_result(sentence):
    """Result section of a grammar check: {"sentence", "grammar": {"errors",
    "spelling", "corrected"}} — the panels' contract; "_unavailable" carries the
    reason when Grammalecte cannot run (the lists are then empty), "_spell_all"
    the untrimmed spelling suggestions the terminal filters differently."""
    text = sentence.strip()
    gc = _grammalecte()
    gram, spell, unavailable = [], [], ""
    if gc is None:
        unavailable = "Grammalecte not installed — run: dico --setup"
    else:
        try:
            gram, spell = gc.getParagraphErrors(text, bSpellSugg=True)
        except Exception as e:
            unavailable = f"Grammalecte : {e}"
    fixed = text
    for e in sorted(gram, key=lambda e: -e["nStart"]):
        if e.get("aSuggestions"):
            fixed = fixed[:e["nStart"]] + e["aSuggestions"][0] + fixed[e["nEnd"]:]
    return {"sentence": text,
            "grammar": {"errors": [{"start": e["nStart"], "end": e["nEnd"],
                                    "text": text[e["nStart"]:e["nEnd"]],
                                    "message": (e.get("sMessage") or "").replace("\xa0", " "),
                                    "type": _GRAM_TYPE.get(e.get("sType", ""), e.get("sType", "")),
                                    "suggestions": e.get("aSuggestions") or []} for e in gram],
                        "spelling": [{"start": e["nStart"], "end": e["nEnd"], "text": e["sValue"],
                                      "suggestions": (e.get("aSuggestions") or [])[:4]} for e in spell],
                        "corrected": fixed},
            "_unavailable": unavailable,
            "_spell_all": [e.get("aSuggestions") or [] for e in spell]}


def render_grammar(r):
    """Highlighted sentence → each mistake (what, why, suggestion) → fixed version."""
    if r["_unavailable"]:
        return [f"  {YELLOW}✗ {r['_unavailable']}{RESET}"]
    text, g = r["sentence"], r["grammar"]
    errs = sorted(g["errors"], key=lambda e: e["start"])
    sp = sorted(zip(g["spelling"], r["_spell_all"]), key=lambda e: e[0]["start"])
    spans = sorted([(e["start"], e["end"], RED) for e in errs]
                   + [(e["start"], e["end"], YELLOW) for e, _ in sp])
    out, pos = "", 0
    for a, b, col in spans:                    # the sentence, mistakes highlighted
        if a < pos:
            continue
        out += text[pos:a] + f"{col}{BOLD}{text[a:b]}{RESET}"
        pos = b
    out += text[pos:]
    lines = [f"  📝 {out}"]
    if not errs and not sp:
        lines.append(f"  {GREEN}✓ Nothing to report — this is correct!{RESET}")
        return lines
    n = 0
    for e in errs:                             # each mistake: what, why, → suggestion
        n += 1
        msg = e["message"].strip()
        typ = e["type"]
        lines.append(f"  {RED}{n}.{RESET} « {BOLD}{e['text']}{RESET} » — {msg}"
                     + (f"  {DIM}[{typ}]{RESET}" if typ else ""))
        if e["suggestions"]:
            lines.append(f"     {GREEN}→ {' / '.join(e['suggestions'][:4])}{RESET}")
    for e, all_sug in sp:
        n += 1
        sug = [s for s in all_sug if s.lower() != e["text"].lower()][:4]
        lines.append(f"  {YELLOW}{n}.{RESET} \u00ab {BOLD}{e['text']}{RESET} \u00bb — unknown word "
                     f"(spelling? accent?)" + (f"  {DIM}→ {' / '.join(sug)}{RESET}" if sug else ""))
    if any(e["suggestions"] for e in errs):    # corrected version (1st suggestion)
        lines.append(f"  {GREEN}✓ {g['corrected']}{RESET}")
    return lines


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


def _sentence_lang(text):
    """« fr », « en » or « ru » — what the grammar checker and the x-ray are
    being handed. Lexique knows too many English-looking strings (« go » is a
    noun) for coverage alone to decide, so plain English markers weigh in."""
    if re.search(r"[\u0400-\u04FF]", text):
        return "ru"
    toks = [t for t in re.findall(r"[\w'’-]+", text) if not t.isdigit()]
    if not toks:
        return "fr"
    en = sum(1 for t in toks if t.lower() in _EN_MARKERS) / len(toks)
    hits = sum(1 for t in toks if lexique_lookup(t.strip("'’")) is not None) / len(toks)
    if en >= 0.34:
        return "en"
    return "fr" if hits >= 0.5 else "en"


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


# The card's direction, decided ONCE for the terminal and the panels.
LEXIQUE_FRENCH_MIN = 50          # films per million (Lexique's freqfilms)


def decide_direction(word):
    """« fr » when the typed word is, offline, a real French word: Lexique has it
    as a LEMMA with this exact spelling (accents included — « the » must not
    become « thé »; « mange » is a form, not a lemma), a content word (NOM, ADJ,
    VER, ADV — « car », « pour », « on », « son » are grammatical words, and
    their English readings win) and frequent enough: freqfilms >=
    LEXIQUE_FRENCH_MIN. At 50/million manger (208), table (111), dire (1565)
    and chat (58) are French; chair (36), four (14), go (15) get translated —
    with the cognate flag when Lexique knows them. Everything else, phrases
    and anything under 3 letters included, is « to_fr »: translate first."""
    w = word.strip().lower()
    if len(w) < 3 or " " in w or CYRILLIC.search(w):
        return "to_fr"
    lex = lexique_lookup(w)
    if (lex and lex["lemma"] == w and lex["cgram"] in ("NOM", "ADJ", "VER", "ADV")
            and lex["freqfilms"] >= LEXIQUE_FRENCH_MIN):
        return "fr"
    return "to_fr"


def lookup_result(session, word, want_dict=False, want_ai=False, want_save=False,
                  want_multi=False, want_conj=False, want_deep=False, want_fr=False,
                  want_save_main=False, want_gram=False, want_xray=False, examples=None,
                  progress=None):
    """The REPL's lookup, as data: what a line means — a card (with the extra
    sections asked for under their keys), a grammar check / x-ray, an answer
    from the tutor, or an error. "_kind" names it; "_"-prefixed keys serve
    render() only. Autosave happens here and is reported under "saved"."""
    session.fallback_note = ""
    r = {"_kind": "", "query": word}
    # Intent detection: a French SENTENCE with no prefix → grammar check.
    if not any((want_dict, want_ai, want_save, want_multi, want_conj, want_deep,
                want_fr, want_save_main, want_gram, want_xray)) and _looks_french_sentence(word):
        want_gram = True
        r["_sentence_note"] = True
    if (want_ai or want_deep) and len(word.split()) > 1 and not (
            want_dict or want_fr or want_multi or want_conj):
        r.update(ai_result(session, word, bool(want_deep), question=word, progress=progress))
        r["_kind"] = "answer"                  # free-form question
        return r
    if want_gram or want_xray:                # "sentence" tools: their own pipeline
        session.last["sentence"] = word.strip()
        if want_xray:
            r.update(xray_result(word))
        if want_gram:
            r.update(grammar_result(word))
        r["_kind"] = "grammar" if want_gram else "xray"
        return r
    src_guess = detect_lang(word)
    offline_ok = want_multi or want_conj      # sections that work offline

    # If the word is already French (a known verb, or -f "French Wiktionary"
    # mode), sending it to Google is useless and misleading ("manger" is also an
    # English word → "crèche").
    conj_inf = conj_tenses = None
    conj_from_fr = False
    session.last["conj_shown"] = bool(want_conj)
    if want_conj:
        conj = conj_result(word)               # "manger present" → filter to one tense
        word = conj["_conj"]["word"]
        conj_inf, conj_tenses = conj["conjugation"]["infinitive"], conj["conjugation"]["tenses"]
        conj_from_fr = conj["_conj"]["from_fr"]
    # -c found a French verb (infinitive OR conjugated form) → skip the useless
    # Google fr→fr "translation" (doit → doit).
    direct_fr_verb = bool(conj_inf) and conj_from_fr
    # Multitran is ru<->fr: a word in the Latin alphabet IS French → skip the
    # useless Google fr→fr "translation" (eventail → eventail).
    multi_fr = want_multi and detect_lang(word) == "en"
    input_is_french = want_fr or direct_fr_verb or multi_fr or decide_direction(word) == "fr"

    translation, detected, alts, groups = None, None, [], []
    if input_is_french:
        translation = conj_inf if direct_fr_verb else word.strip().lower()
        detected = "fr"
    else:
        groups = []
        try:
            translation, detected, groups = translate_rich(word, session=session)      # Google
            alts = [t for _, terms in groups for t, _ in terms][:6]
        except Exception as e:
            try:
                translation, detected, alts = translate_mymemory(word, src_guess)
            except Exception:
                translation = None
            if translation:
                pass
            elif not offline_ok:
                r.update({"_kind": "error", "error": str(e)})
                return r
            else:
                r["_offline_note"] = True
    src = detected or src_guess
    session.last.update(word=word, fr=translation or "")

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
        r.update({"_kind": "error", "_no_translation": True})
        return r
    if translation:
        ex_on = config_load().get("examples", True) if examples is None else examples
        is_fr = input_is_french or _deaccent(translation.lower()) == _deaccent(word.strip().lower())
        if is_fr:
            r.update(card_fr_result(session, translation, lex_fr, examples=ex_on and not want_conj))
            r["_kind"] = "card_fr"
        else:
            r.update(card_to_fr_result(session, word, src, translation,
                                       groups if not input_is_french else [], examples=ex_on))
            r["_kind"] = "card_to_fr"
    if session.fallback_note:
        r["note"] = session.fallback_note
    if cognate:                               # possible false friend: flag it
        r["_cognate"] = {"word": word, "lemma": cognate["lemma"], "article": cognate["article"],
                         "genre": cognate["genre"], "pos": cognate["pos"], "band": cognate["band"]}

    if want_multi:
        r.update(multitran_result(word))

    if want_conj:
        r.update(conj)

    r["_definitions"] = []
    if want_fr:                               # Wiktionary for the word as typed
        r["_definitions"].append(definition_result(word))
    if want_dict and translation:             # Wiktionary for the translation
        r["_definitions"].append(definition_result(translation))
    if r["_definitions"]:
        r.update(r["_definitions"][-1])
    wikt_entry = r["_definitions"][-1]["_entry"] if r["_definitions"] else None

    if want_ai or want_deep:
        q = word if len(word.split()) > 1 else None   # several words = free-form question
        r.update(ai_result(session, word, bool(want_deep), question=q, progress=progress))

    auto = autosave_on() and not session.no_autosave
    if (auto or want_save or want_save_main) and translation:
        r.update(save_from_card(word, src, translation, wikt_entry, lex_fr, input_is_french,
                                want_conj, conj_tenses, want_multi,
                                auto and not (want_save or want_save_main)))
    return r


def save_from_card(word, src, translation, entry, lex, input_is_french, want_conj,
                   conj_tenses, want_multi, auto):
    """Store the card that was just shown: {"saved": {"front", "status", "count",
    "auto"}} or {"_save_error": str}. Enrichment: 1) the Wiktionary entry
    already shown (-f/-d, rich), 2) OFFLINE Lexique (lemma/gender/pos, no
    network), 3) only as a last resort, a Wiktionary request."""
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
    except Exception as e:
        return {"_save_error": str(e)}
    return {"saved": {"front": front, "status": status, "count": cnt, "auto": auto}}


def render(r):
    """THE terminal printer: a Result → its lines, sections in the order the
    REPL has always shown them. Colours live here and in the render_* it calls."""
    kind = r.get("_kind", "")
    if kind == "help":
        return cheatsheet_lines()
    if kind == "setting":
        return render_setting(r)
    if kind == "message":
        return [f"  {DIM}{r['message']}{RESET}"]
    if kind == "history":
        if not r["history"]:
            return [f"  {DIM}(nothing yet — look something up, then ask « ? … »){RESET}"]
        return [f"  {DIM}{i}.{RESET} " + _turn_line(t).replace("\n  ", f"\n     {DIM}") + (RESET if t["kind"] == "question" else "")
                for i, t in enumerate(r["history"], 1)]
    if kind == "empty":
        return []
    lines = []
    if r.get("_sentence_note"):
        lines.append(f"  {DIM}French sentence → grammar  (\u00ab !x \u00bb for the x-ray, \u00ab ? \u00bb to ask){RESET}")
    if kind == "answer":
        return lines + render_ai(r)
    if "xray" in r:
        lines += render_xray(r)
    if "grammar" in r:
        lines += render_grammar(r)
    if kind == "error":
        if r.get("_no_translation"):
            lines.append(f"{YELLOW}No translation found for \u00ab {r['query']} \u00bb.{RESET}")
        else:
            lines.append(f"{RED}✗ Error / no connection:{RESET} {r['error']}")
            lines.append(f"{DIM}  (the quick translation needs internet){RESET}")
        return lines
    if r.get("_offline_note"):
        lines.append(f"  {DIM}(offline: no quick translation){RESET}")
    if "_card" in r:
        lines += render_card_fr(r) if r["direction"] == "fr" else render_card_to_fr(r)
    if r.get("_cognate"):
        c = r["_cognate"]
        art = (c["article"] + " ") if c["article"] else ""
        g = (" " + ("masc." if c["genre"] == "m" else "fém.")) if c["genre"] else ""
        lines.append(f"  {YELLOW}↔ \u00ab {c['word']} \u00bb is also a French word{RESET}: "
                     f"{BOLD}{art}{c['lemma']}{RESET} {DIM}({c['pos']}{g}, "
                     f"{c['band']}) — \u00ab def {c['word']} \u00bb for its meaning{RESET}")
    if "multitran" in r:
        lines += render_multitran(r)
    if "conjugation" in r:
        lines += render_conjugation(r)
    for d in r.get("_definitions", [r] if "definition" in r else []):
        lines += render_definition(d)
    if "synonyms" in r:
        lines += render_synonyms(r)
    if "audio" in r:
        lines += render_audio(r)
    if "examples" in r and isinstance(r["examples"], dict):
        lines += render_examples(r, follow_up=r.get("_follow_up", False))
    if "model" in r:
        lines += render_ai(r)
    if "saved" in r:
        s = r["saved"]
        tag = f"  {DIM}×{s['count']}{RESET}" if s["count"] > 1 else ""
        badge = f"  {DIM}auto{RESET}" if s["auto"] else ""
        lines.append(f"  {GREEN}💾 « {s['front']} » → {s['status']}{RESET}{tag}{badge}")
    if r.get("_save_error"):
        lines.append(f"  {YELLOW}💾 save failed:{RESET} {r['_save_error']}")
    return lines


# --------------------------------------------------------------------------- #
#  Interactive mode                                                           #
# --------------------------------------------------------------------------- #
_FOLLOW_HINT = "↳  save N · conj · def · ru · ex · say · syn · ? question"


def setting_result(session, line):
    """« : » commands of the interactive mode (settings, not lookups) → a Result
    {"_kind": "setting", "setting": name, …}."""
    parts = line[1:].split()
    cmd = parts[0].lower() if parts else ""
    arg = " ".join(parts[1:]).strip()
    r = {"_kind": "setting", "setting": cmd}
    if cmd in ("save", "autosave"):
        r["setting"] = "autosave"
        if arg.lower() in ("on", "off"):
            config_set("autosave", arg.lower() == "on")
            r["changed"] = True
        r["value"] = autosave_on()
    elif cmd == "forget" and arg:
        r.update(word=arg, count=store_forget(arg))
    elif cmd == "forget":                     # alone: the tutor forgets this session
        session.history.clear()
        r["setting"] = "forget_history"
    elif cmd == "render":
        store_render()
    elif cmd == "llm":
        url, model, _ = _llm_cfg()
        if arg:
            parts = arg.split()
            config_set("llm_url", parts[0]) if "://" in parts[0] else config_set("llm_model", parts[0])
            if len(parts) > 1:
                config_set("llm_model", parts[1])
            url, model, _ = _llm_cfg()
        r.update(url=url, model=model, reachable=_llm_reachable())
    elif cmd in ("examples", "exemples"):
        r["setting"] = "examples"
        if arg.lower() in ("on", "off"):
            config_set("examples", arg.lower() == "on")
        r["value"] = config_load().get("examples", True)
    elif cmd == "spacy":
        if arg.lower() in ("on", "off"):
            config_set("xray_spacy", arg.lower() == "on")
        r["value"] = config_load().get("xray_spacy", True)
    else:
        r["setting"] = ""
    return r


def render_setting(r):
    s = r["setting"]
    if s == "autosave":
        if r.get("changed"):
            return [f"  {GREEN}✓ autosave {'on' if r['value'] else 'off'}{RESET}"]
        return [f"  autosave: {'ON' if r['value'] else 'off'}   {DIM}(:save on | :save off){RESET}"]
    if s == "forget":
        return [f"  {GREEN}✓ \u00ab {r['word']} \u00bb dropped{RESET}" if r["count"]
                else f"  {DIM}\u00ab {r['word']} \u00bb not found{RESET}"]
    if s == "forget_history":
        return [f"  {GREEN}✓ tutor history cleared{RESET}"]
    if s == "render":
        return [f"  {GREEN}✓ markdown regenerated{RESET}"]
    if s == "llm":
        return [f"  tutor: {r['url']}  ·  model: {r['model'] or '(first one loaded)'}  ·  "
                f"{'OK' if r['reachable'] else 'unreachable'}"
                f"   {DIM}(:llm <url> [model] · :llm <model>){RESET}"]
    if s == "examples":
        return [f"  Tatoeba examples: {'ON' if r['value'] else 'off'}"]
    if s == "spacy":
        return [f"  spaCy for \u00ab !x \u00bb: {'ON' if r['value'] else 'off'}   {DIM}(:spacy on | :spacy off — off = "
                f"instant, Lexique only){RESET}"]
    return [f"  {DIM}commands: :save on|off · :forget [word] · :render · :spacy on|off · :llm{RESET}"]


def _load_history():
    if not readline:
        return
    try:
        readline.read_history_file(HISTFILE)
    except OSError:
        pass
    readline.set_history_length(1000)


def _save_term(french, sens, src_lang="en", tier="google", quiet=False,
               example="", example_en=""):
    """Save a French term (front with its article if a noun); the back gets an
    English gloss, the word you typed when it was Russian, and an example."""
    front, lex = _fr_head(french)
    lemma = (lex["lemma"] if lex else french)
    rec = {"key": store_key(lemma), "front": front, "lemma": lemma, "sens": sens, "gloss": "",
           "pos": (lex["pos"] if lex else ""), "gender": (lex["genre"] if lex else "") or "",
           "example": example or "", "example_en": example_en or "",
           "src_word": sens, "src_lang": src_lang, "tier": tier,
           # Offline extras, so a card carries them into Anki/Obsidian too.
           "cefr": (lex or {}).get("cefr") or "", "ipa": (lex or {}).get("ipa") or ""}
    enrich_entry(rec)                                 # gloss + example, cached lookups
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


def _print_result(r):
    """render → print, then the one side effect a Result asks for (audio)."""
    for line in render(r):
        print(line)
    _play_audio(r)


def interactive(session):
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
            _print_result(session.handle(line, progress=_progress))
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


def cheatsheet_lines():
    rows = [("a word (RU/EN)", "card: numbered senses · gender · example"),
            ("a French word", "its card (+ présent if it's a verb)"),
            ("a French sentence", "grammar check + the rule"),
            ("save N", "save sense N of the last card"),
            ("conj · def · ru · ex", "on the last card — or give a word: « conj manger », « def maison »"),
            ("say · syn", "hear a native recording · synonyms and homophones"),
            ("grammar · x [sentence]", "grammar check · x-ray, on the last sentence or the one you give"),
            ("? question", "ask the tutor, in context (?? = detailed) · « history » shows what it knows"),
            (":save on|off", "auto-save every lookup (also :forget [word], :render, :llm, :spacy)"),
            ("q", "quit")]
    w = max(len(k) for k, _ in rows)
    return [f"   {BOLD}{CYAN}{k.ljust(w)}{RESET}  {d}" for k, d in rows]


def _print_cheatsheet():
    for line in cheatsheet_lines():
        print(line)


def run_tour(session):
    """A 2-minute guided tour. Needs internet; does not auto-save your store."""
    session.no_autosave = True

    def go(*lines):
        for line in lines:
            _print_result(session.handle(line, progress=_progress))
    steps = [
        ("Type an English or Russian word. You get a card: senses numbered and grouped by "
         "part of speech, each noun with its article and gender, ★ = how common.", "cook",
         lambda: go("cook")),
        ("The first sense is what auto-save keeps. Want another one? Just say « save 5 ».",
         "save 5", lambda: go("save 5")),
        ("A French word gives its own card: nature, gender, frequency, English senses, an example.",
         "maison", lambda: go("maison")),
        ("A French verb shows its présent right away. « conj » gives the whole grid.",
         "aller  →  conj", lambda: go("aller", "conj")),
        ("Type a French sentence and dico corrects it — and names the rule.",
         "elle est parti hier et je mange un pomme",
         lambda: go("elle est parti hier et je mange un pomme")),
        ("Ask the tutor anything about what you're looking at: « ? … ».",
         "? tu ou vous ?", lambda: go("? tu ou vous ?")),
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
    session.no_autosave = False


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


def _build_parser():
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
    p.add_argument("--version", action="version", version=f"dico {__version__}")
    p.add_argument("--review", action="store_true",
                   help="review the saved words (spaced repetition, in the terminal)")
    p.add_argument("--due", action="store_true",
                   help="with --json: the cards to review now, and the counts")
    p.add_argument("--grade", metavar="KEY", help="with --ease N and --json: grade one card")
    p.add_argument("--card", metavar="KEY", help="with --json: one card, filled in (gloss, example, IPA…) if it was bare")
    p.add_argument("--ease", type=int, default=3, choices=(1, 2, 3, 4),
                   help="1 again · 2 hard · 3 good · 4 easy (with --grade)")
    p.add_argument("--backup", action="store_true",
                   help="pull, commit and push the cards (the store's folder must be a git repo)")
    p.add_argument("--backup-init", nargs="?", const="", metavar="URL",
                   help="give the cards a git repository of their own (with a remote, when a URL is given)")
    p.add_argument("--pull", action="store_true",
                   help="only pull what other sources wrote to the cards")
    p.add_argument("--paths", action="store_true",
                   help="where the config, the vocabulary, the store and the data live (JSON with --json)")
    p.add_argument("--say", action="store_true",
                   help="play a native recording of the word (Wiktionary/Commons)")
    p.add_argument("--syn", action="store_true",
                   help="synonyms and homophones (Wiktionnaire)")
    p.add_argument("--examples", action="store_true",
                   help="example sentences for a French word (Tatoeba, EN + RU); with --json for GUIs")
    p.add_argument("--serve", action="store_true",
                   help="long-lived: one JSON request per stdin line, one JSON response per stdout line")
    p.add_argument("--json", action="store_true",
                   help="JSON output (for a graphical front-end / Raycast / etc.)")
    p.add_argument("--save-term", metavar="TERM",
                   help="save this French term (with --sens: the meaning on the back)")
    p.add_argument("--sens", metavar="TEXT", default="",
                   help="meaning (original word / translation) for --save-term")
    p.add_argument("--example", metavar="TEXT", default="", help="with --save-term: an example sentence")
    p.add_argument("--example-en", metavar="TEXT", default="", help="with --save-term: its translation")
    p.add_argument("--tier", metavar="KIND", default="",
                   help="with --save-term: what the card is — word (default), phrase, sentence, tutor")
    p.add_argument("--enrich", action="store_true",
                   help="backfill every saved word: English gloss, example, IPA, CEFR, gender")
    p.add_argument("--context", metavar="TEXT", default="",
                   help="context for a question (-a): last word / last sentence")
    p.add_argument("--mots-outils", nargs="?", const=120, type=int, metavar="N",
                   help="show the CORE function words (articles, prepositions, "
                        "pronouns, conjunctions, auxiliaries) — the grammatical scaffolding")
    return p


def command_result(args):
    """The store / SRS / paths commands the apps call with --json (--due, --card,
    --grade, --paths, --save-term) → their dict, exactly as printed today; None
    when the flags ask for a lookup instead."""
    if args.due:
        cards, counts = srs_queue()
        entries = store_load()["entries"]
        latest = sorted((e for e in entries if e.get("front") or e.get("lemma")),
                        key=lambda e: e.get("last_seen", ""), reverse=True)[:6]
        recent = [{"front": e.get("front") or e.get("lemma"), "gloss": (e.get("gloss") or e.get("sens") or "")}
                  for e in latest]
        return {"deck": "dico", "cards": cards, "counts": counts, "total": len(entries),
                "recent": recent, "_kind": "deck"}
    if args.card:
        data = store_load()
        for e in data["entries"]:
            if e.get("key") == args.card:
                if enrich_entry(e):
                    store_save(data)
                return {"card": _srs_card(e), "_kind": "card"}
        return {"error": f"no card « {args.card} »", "_kind": "error"}
    if args.grade:
        card = srs_answer(args.grade, args.ease)
        if card is None:
            return {"error": f"no card « {args.grade} »", "_kind": "error"}
        return {"card": card, "_kind": "card"}
    if args.paths:
        return {"config": CONFIG_PATH, "vocab": VOCAB, "store": STORE, "data": DATA_DIR,
                "home": DICO_HOME, "cards_repo": cards_repo() or "",
                "cards_autosync": cards_autosync(), "_kind": "paths"}
    if args.save_term:
        lang = "fr" if _deaccent(args.sens or "") == _deaccent(args.save_term) else detect_lang(args.sens or "en")
        front, status, cnt = _save_term(args.save_term, args.sens, lang, quiet=True,
                                        example=args.example, example_en=args.example_en,
                                        tier=args.tier or "google")
        return {"saved": front, "status": status, "count": cnt, "sens": args.sens, "_kind": "saved"}
    return None


def serve(session, parser, stdin=None, stdout=None):
    """dico --serve: one JSON request per stdin line → one JSON response per
    stdout line, over ONE Session (state persists; the interpreter, Lexique,
    Grammalecte and the spaCy sidecar load once).

      {"id": …, "line": "save 2"}                  the REPL's language
      {"id": …, "args": ["--json", "-c", "dire"]}  argv-style, the apps' flags as today
      {"id": …, "op": "ping"}                      → {"id": …, "ok": true, "version": …}
      {"id": …, "op": "history"}                   the tutor's context, as turns
      →  {"id": …, "kind": <_kind>, "result": <the --json dict>}
      →  {"id": …, "error": "…"}   (a bad line has no id; nothing ever kills the loop)

    Stdout carries only responses (anything a lookup prints goes to stderr);
    the cache is flushed after every request. EOF ends it."""
    stdin = stdin or sys.stdin
    out = stdout or sys.stdout
    parser.exit = lambda status=0, message=None: (_ for _ in ()).throw(SystemExit(message or status))

    def reply(obj):
        out.write(json.dumps(obj, ensure_ascii=False) + "\n")
        out.flush()

    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except ValueError as e:
            reply({"error": f"invalid JSON: {e}"})
            continue
        if not isinstance(req, dict):
            reply({"error": "a request is a JSON object: {\"id\", \"line\" | \"args\" | \"op\": \"ping\"}"})
            continue
        rid = req.get("id")
        try:
            with contextlib.redirect_stdout(sys.stderr):   # only responses on stdout
                if req.get("op") == "ping":
                    reply({"id": rid, "ok": True, "version": __version__})
                    continue
                if "line" in req:
                    r = session.handle(str(req["line"]))
                elif "op" in req:              # e.g. {"op": "history"}
                    r = session.run({"op": str(req["op"]), "text": str(req.get("text", ""))})
                elif "args" in req:
                    args = parser.parse_args([str(a) for a in req["args"]])
                    if args.context:
                        session.last["word"] = args.context
                    r = command_result(args)
                    if r is None:
                        r = session.handle_args(args)
                else:
                    raise ValueError('a request needs "line", "args" or "op" (ping, history)')
                cache_flush()
            reply({"id": rid, "kind": r.get("_kind", ""), "result": _public(r)})
        except SystemExit as e:                 # argparse refused the flags
            reply({"id": rid, "error": f"bad args: {e}"})
        except Exception as e:
            reply({"id": rid, "error": f"{type(e).__name__}: {e}"})


def main():
    p = _build_parser()
    args = p.parse_args()
    session = Session()
    if args.serve:
        return serve(session, p)

    if args.review:
        return run_review()
    if args.due or args.card or args.grade:      # always JSON: the apps' deck
        return print(json.dumps(_public(command_result(args)), ensure_ascii=False))
    if args.backup_init is not None:
        return run_backup_init(args.backup_init, as_json=args.json)
    if args.backup or args.pull:
        return run_backup(as_json=args.json, pull_only=args.pull)
    if args.paths:
        paths = _public(command_result(args))
        if args.json:
            return print(json.dumps(paths, ensure_ascii=False))
        for k, v in paths.items():
            print(f"{k:7} {v}")
        return
    if args.setup:
        return run_setup(ask_llm=not args.no_llm)
    if args.llm:
        return setup_llm()
    if args.tour:
        return run_tour(session)
    if args.enrich:
        return run_enrich(as_json=args.json)
    if args.save_term:
        if args.json:
            return print(json.dumps(_public(command_result(args)), ensure_ascii=False))
        lang = "fr" if _deaccent(args.sens or "") == _deaccent(args.save_term) else detect_lang(args.sens or "en")
        return _save_term(args.save_term, args.sens, lang, example=args.example, example_en=args.example_en,
                          tier=args.tier or "google")
    if args.context:
        session.last["word"] = args.context
    if args.json:
        return print(json.dumps(_public(session.handle_args(args)), ensure_ascii=False, indent=2))
    if args.examples:
        return _print_result(session.handle_args(args))
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
    if args.words:
        _print_result(session.handle_args(args, progress=_progress))
    else:
        interactive(session)


if __name__ == "__main__":
    try:
        main()
    finally:
        cache_flush()
