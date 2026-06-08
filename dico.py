#!/usr/bin/env python3
"""dico — un petit dictionnaire de poche : russe/anglais → français.

Niveaux (cumulables) :
    dico <mot>            traduction rapide          (Google, par défaut)
    dico -m <mot>         + Multitran HORS-LIGNE      (riche, ru↔fr, sans internet)
    dico -d <mot>         + Wiktionnaire APRÈS trad   (RU/EN → français)
    dico -f <mot-fr>      + Wiktionnaire DIRECT       (le mot est déjà français)
    dico -c <verbe>       + conjugaison HORS-LIGNE    (7 temps)
    dico -c <verbe> <temps>  un seul temps           (ex: « dico -c manger present »)
    dico -a <mot>         + explication IA rapide     (Claude Haiku : fiche courte)
    dico -p <mot>         + explication APPROFONDIE   (Claude Opus : fiche d'étude)
    dico -s  <mot>        enregistre CE mot dans le vocabulaire (store JSON)
    dico --autosave on    enregistre AUTOMATIQUEMENT chaque recherche (persistant)
    dico --forget <mot>   retire un mot (curation soustractive)
    dico --render         régénère le markdown depuis le store
    dico -mda <mot>       tout en même temps
    dico                  mode interactif (tape des mots en boucle)

Le store JSON (dico_vocab.json, à côté du markdown) est la SOURCE DE VÉRITÉ :
le .md n'en est qu'une vue régénérée automatiquement, et Anki le lit directement.

Détecte la langue source (russe si cyrillique, sinon anglais). ATTENTION : la
traduction rapide va SEULEMENT RU/EN → FR (jamais l'inverse). Pour comprendre un
mot FRANÇAIS, utilise -m (Multitran fr→ru), -f (Wiktionnaire) ou -a / -p (IA).

Zéro dépendance : seulement la bibliothèque standard de Python 3.
La traduction et le Wiktionnaire ont besoin d'internet ; Multitran et les
conjugaisons marchent hors-ligne (bases dans data/). L'option -a utilise l'API
Anthropic si ANTHROPIC_API_KEY est défini (rapide ~1-2 s), sinon la commande `claude`.
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
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

try:
    import readline  # flèche ↑ = rappeler la commande précédente (interactif)
except ImportError:
    readline = None

HISTFILE = os.path.expanduser("~/.dico_history")

TIMEOUT = 8

# Couleurs ANSI (désactivées si la sortie n'est pas un terminal)
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
    """Russe si le texte contient du cyrillique, sinon anglais."""
    return "ru" if CYRILLIC.search(text) else "en"


def _deaccent(s):
    """Retire les accents (é→e, ç→c…) et met en minuscules — l'utilisateur ne
    peut pas taper les accents dans son terminal."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower().strip()


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8")


# --------------------------------------------------------------------------- #
#  Niveau 1 : traduction rapide                                               #
# --------------------------------------------------------------------------- #
def translate_google(word):
    """Endpoint gratuit de Google (auto-détection de la langue source)."""
    q = urllib.parse.quote(word)
    url = ("https://translate.googleapis.com/translate_a/single"
           f"?client=gtx&sl=auto&tl=fr&dt=t&dt=bd&q={q}")
    data = json.loads(_get(url))
    translation = "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
    detected = data[2] if len(data) > 2 and isinstance(data[2], str) else None
    alts = []
    if len(data) > 1 and data[1]:
        for entry in data[1]:
            for term in (entry[1] if len(entry) > 1 else []):
                if term and term != translation and term not in alts:
                    alts.append(term)
    return translation, detected, alts[:6]


def translate_mymemory(word, src):
    """Secours : API gratuite MyMemory."""
    q = urllib.parse.quote(word)
    url = f"https://api.mymemory.translated.net/get?q={q}&langpair={src}|fr"
    data = json.loads(_get(url))
    translation = data["responseData"]["translatedText"].strip()
    alts = []
    for m in data.get("matches", []):
        t = (m.get("translation") or "").strip()
        if t and t.lower() != translation.lower() and t not in alts:
            alts.append(t)
    return translation, src, alts[:6]


def translate(word):
    """Essaie Google, puis MyMemory en secours."""
    src_guess = detect_lang(word)
    try:
        return translate_google(word)
    except Exception:
        return translate_mymemory(word, src_guess)


# --------------------------------------------------------------------------- #
#  Niveau 2 : le Wiktionnaire (dictionnaire complet)                          #
# --------------------------------------------------------------------------- #
GENDER = {
    "{{m}}": "nom masculin (le / un)",
    "{{f}}": "nom féminin (la / une)",
    "{{mf}}": "masculin ou féminin",
    "{{n}}": "neutre",
}


def _fr_section(wikitext):
    """Isole la section française == {{langue|fr}} == du wikitexte."""
    m = re.search(r"==\s*\{\{langue\|fr\}\}\s*==", wikitext)
    if not m:
        return None
    rest = wikitext[m.end():]
    nxt = re.search(r"\n==\s*\{\{langue\|", rest)
    return rest[:nxt.start()] if nxt else rest


def _clean_wiki(s):
    """Enlève le balisage wiki pour ne garder que le texte lisible."""
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)                  # {{templates}}
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)    # [[a|b]] -> b
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)             # [[a]]   -> a
    s = s.replace("'''", "").replace("''", "")            # gras / italique
    s = re.sub(r"<[^>]+>", "", s)                         # balises HTML
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
    """Rend lisibles les principaux modèles d'étymologie du Wiktionnaire."""
    def etyl(m):
        parts = m.group(1).split("|")
        lang = _ETYL_LANG.get(parts[0].strip(), parts[0].strip()) if parts else ""
        kw = dict(p.split("=", 1) for p in parts if "=" in p)
        pos = [p.strip() for p in parts if "=" not in p]
        mot = kw.get("mot") or (pos[2] if len(pos) > 2 else "")
        out = lang + (f" « {mot} »" if mot else "")
        return out + (f" ({kw['sens']})" if kw.get("sens") else "")
    s = re.sub(r"(?is)<ref[^>]*>.*?</ref>", "", s)       # notes de bas de page
    s = re.sub(r"\{\{étyl\|([^{}]*)\}\}", etyl, s)
    s = re.sub(r"\{\{(?:lien|polytonique|recons)\|([^|{}]+)[^{}]*\}\}", r"\1", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)                  # autres modèles → vide
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s*\b[\w-]+=[^\s,;()«»]+", "", s)        # paramètres de modèle résiduels
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
    return (text[:240] + "…") if len(text) > 240 else (text or None)


def _parse_wiktionary(wikitext):
    sec = _fr_section(wikitext)
    if not sec:
        return None
    head = sec.split("\n#", 1)[0]                         # avant la 1re définition
    pm = re.search(r"\{\{S\|([^|}]+)\|fr", sec)
    pos = pm.group(1) if pm else None
    ipa = None
    pr = re.search(r"\{\{pron\|([^|}]+)\|", head)
    if pr:
        ipa = pr.group(1)
    gender = next((label for tag, label in GENDER.items() if tag in head), None)
    defs = []
    for line in sec.splitlines():
        if re.match(r"^#\s+\S", line):                    # # définition (pas #* ni ##)
            d = _clean_wiki(line[1:])
            if d:
                defs.append(d)
        if len(defs) >= 3:
            break
    if not (defs or ipa or gender):
        return None
    return {"pos": pos, "ipa": ipa, "gender": gender, "defs": defs,
            "etym": _etymology(sec)}


def _wikt_fetch(title):
    """Récupère et parse la fiche française d'un titre précis du Wiktionnaire."""
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
    """Titres dont la forme sans accent == le mot tapé (« creche » → « crèche » :
    l'utilisateur ne tape pas les accents)."""
    url = ("https://fr.wiktionary.org/w/api.php?action=query&list=search"
           f"&srsearch={urllib.parse.quote(word)}&srlimit=8&format=json"
           "&formatversion=2")
    try:
        hits = json.loads(_get(url))["query"]["search"]
    except Exception:
        return []
    target = _deaccent(word)
    return [h["title"] for h in hits if _deaccent(h["title"]) == target]


# Articles/déterminants à ignorer en tête d'une traduction (« un cuisinier »).
_FR_ARTICLES = {"un", "une", "le", "la", "les", "des", "du", "de",
                "d'", "l'", "se", "s'", "au", "aux", "à"}


def _wikt_candidates(word):
    """Variantes à chercher : enlève les articles de tête (« un cuisinier » →
    « cuisinier ») et garde le mot-tête (dernier mot du groupe)."""
    w = word.strip()
    cands = [w, w.lower()]
    parts = w.lower().split()
    while len(parts) > 1 and parts[0] in _FR_ARTICLES:
        parts = parts[1:]
    if parts:
        cands.append(" ".join(parts))     # sans les articles de tête
        cands.append(parts[-1])           # le mot-tête (souvent le nom/verbe)
    return list(dict.fromkeys(c for c in cands if c))


def wiktionary(word):
    """Fiche française d'un mot. Essaie d'abord le mot tel quel (sans article de
    tête), puis une recherche tolérante aux accents — en gardant la fiche la PLUS
    riche (évite « étre » pour « être », ou « un » pour « cuisinier »)."""
    tried = set()
    for cand in _wikt_candidates(word):
        if cand and cand not in tried:
            tried.add(cand)
            entry = _wikt_fetch(cand)
            if entry:
                return entry
    best = None
    for cand in _wikt_search_titles(word):
        if cand in tried:
            continue
        tried.add(cand)
        entry = _wikt_fetch(cand)
        if entry and (best is None or len(entry["defs"]) > len(best["defs"])):
            best = entry
    return best


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
            print(f"     {DIM}🌱 étym. {entry['etym']}{RESET}")
    else:
        print(f"  {DIM}📖 (pas de fiche Wiktionnaire pour « {lookup_word} »){RESET}")
    return entry


# --------------------------------------------------------------------------- #
#  Niveau 3 : explication par l'IA (Claude CLI)                               #
# --------------------------------------------------------------------------- #
AI_MODEL = "claude-haiku-4-5"        # tier rapide (-a) : fiche courte, bon marché
AI_MODEL_DEEP = "claude-opus-4-8"    # tier profond (-p) : fiche d'étude complète


def _claude_bin():
    return shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")


def _ai_prompt(word):
    # Tier rapide. On laisse Claude traduire lui-même (meilleur que Google pour le
    # contexte/genre), sans lui imposer la traduction de Google.
    return (
        "Tu es un professeur de français pour un grand débutant qui comprend "
        "le russe et l'anglais.\n"
        f"Il a tapé le mot « {word} ». Donne sa meilleure traduction française, "
        "puis une fiche TRÈS COURTE en français simple (mets la traduction anglaise "
        "entre parenthèses pour les mots difficiles). Format :\n"
        "1. La traduction française + nature et genre (ex: nom masculin → un/le), "
        "ou la conjugaison si c'est un verbe.\n"
        "2. Prononciation expliquée simplement.\n"
        "3. Deux phrases d'exemple faciles.\n"
        "4. Nuance avec un synonyme proche (si utile).\n"
        "Maximum 8 lignes. Pas d'introduction : va droit au but. "
        "Tu écris pour un terminal : **gras** et listes « - » bienvenus, pas de tableaux."
    )


def _ai_prompt_deep(word):
    # Tier profond : on demande au gros modèle une vraie fiche d'étude.
    return (
        "Tu es un professeur de français exceptionnel pour un apprenant dont la "
        "langue maternelle est le russe et qui parle aussi anglais.\n"
        f"Mot à étudier : « {word} » (russe, anglais ou français — détecte-le).\n"
        "Donne une fiche d'étude COMPLÈTE mais claire, en français simple (mets la "
        "traduction anglaise entre parenthèses pour les mots difficiles). Inclus :\n"
        "• La/les traduction(s) française(s) avec genre et article (+ pluriel si utile).\n"
        "• Prononciation : transcription IPA + une astuce « ça se prononce comme… ».\n"
        "• Registre (familier / courant / soutenu) et fréquence d'usage.\n"
        "• 3 phrases d'exemple, de plus en plus riches.\n"
        "• Nuance avec 1 ou 2 synonymes proches : quand utiliser lequel.\n"
        "• Pièges pour un russophone/anglophone (faux-amis, genre, prononciation).\n"
        "• Si c'est un verbe : son groupe et sa conjugaison au présent.\n"
        "• Une astuce pour mémoriser (cognat russe ou anglais si possible).\n"
        "Sois pédagogique, concret et bien structuré. Aucune phrase d'introduction. "
        "Tu écris pour un terminal : **gras** et listes « - » ; évite les tableaux."
    )


def _ai_via_api(prompt, api_key, model, max_tokens):
    """POST direct à l'API Anthropic — rapide, zéro dépendance (urllib)."""
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
    return (text, None) if text else (None, "réponse vide")


def _ai_via_cli(prompt, model):
    """Repli : commande `claude` (auth Claude Code, plus lent)."""
    bin_ = _claude_bin()
    if not bin_ or not os.path.exists(bin_):
        return None, "définis ANTHROPIC_API_KEY ou installe la commande `claude`"
    try:
        out = subprocess.run([bin_, "--model", model, "-p", prompt],
                             capture_output=True, text=True, timeout=180)
    except Exception as e:
        return None, str(e)
    text = (out.stdout or "").strip()
    if not text:
        return None, (out.stderr or "réponse vide").strip()
    return text, None


def ai_explain(word, deep=False):
    """Préfère l'API directe (si ANTHROPIC_API_KEY) ; sinon la commande `claude`.
    deep=True → modèle Opus + prompt riche. Claude traduit le mot lui-même."""
    if deep:
        model, prompt, max_tokens = AI_MODEL_DEEP, _ai_prompt_deep(word), 1100
    else:
        model, prompt, max_tokens = AI_MODEL, _ai_prompt(word), 400
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return _ai_via_api(prompt, api_key, model, max_tokens)
    return _ai_via_cli(prompt, model)


def _render_md(text):
    """Petit rendu Markdown → terminal (gras, italique, titres, listes, code).
    Zéro dépendance ; couvre ce que Claude produit le plus souvent."""
    def inline(s):
        s = re.sub(r"\*\*(.+?)\*\*", BOLD + r"\1" + RESET, s)            # **gras**
        s = re.sub(r"__(.+?)__", BOLD + r"\1" + RESET, s)               # __gras__
        s = re.sub(r"`([^`]+)`", GREEN + r"\1" + RESET, s)              # `code`
        s = re.sub(r"(?<![*\w])\*(?!\s)([^*]+?)\*(?!\w)",               # *italique*
                   ITAL + r"\1" + RESET, s)
        s = re.sub(r"(?<![_\w])_(?!\s)([^_]+?)_(?!\w)",                 # _italique_
                   ITAL + r"\1" + RESET, s)
        return s

    lines = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            lines.append("")
        elif re.match(r"^\s*#{1,6}\s+", line):                          # titre
            lines.append(BOLD + CYAN + inline(re.sub(r"^\s*#{1,6}\s+", "", line)) + RESET)
        elif re.match(r"^\s*[-*•]\s+", line):                           # puce
            lines.append("  • " + inline(re.sub(r"^\s*[-*•]\s+", "", line)))
        elif re.match(r"^\s*[-*_]{3,}\s*$", line):                      # ligne ---
            lines.append(DIM + "─" * 28 + RESET)
        else:
            lines.append(inline(line))
    return lines


def _show_ai(word, deep):
    icon, label = ("🧠", "Claude approfondi") if deep else ("🤖", "Claude")
    pad = " " * 12
    print(f"  {CYAN}{icon} {label} réfléchit…{RESET}", end="\r")
    text, err = ai_explain(word, deep=deep)
    if text:
        print(f"  {CYAN}{icon} {label} :{RESET}{pad}")
        for line in _render_md(text):
            print(f"     {line}")
    else:
        print(f"  {YELLOW}{icon} IA indisponible :{RESET} {err}{pad}")


# --------------------------------------------------------------------------- #
#  Sauvegarde dans le vocabulaire                                             #
# --------------------------------------------------------------------------- #
# Cible de --save : DICO_VOCAB si défini (ex. ton coffre de notes), sinon local.
VOCAB = os.environ.get("DICO_VOCAB") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "vocabulaire.md")
# Cible de -S : la liste « propre » (vocabulaire.md) ; sinon = le journal.
VOCAB_MAIN = os.environ.get("DICO_VOCAB_MAIN") or VOCAB
# La VÉRITÉ, c'est le store JSON (à côté du markdown). Le .md n'en est qu'une
# vue régénérée. DICO_STORE peut le placer ailleurs.
STORE = os.environ.get("DICO_STORE") or os.path.join(
    os.path.dirname(os.path.abspath(VOCAB)), "dico_vocab.json")
# Réglages persistants (ex. l'auto-save activé une fois pour toutes).
CONFIG_PATH = os.path.expanduser("~/.dico_config.json")


def config_load():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def config_set(key, value):
    cfg = config_load()
    cfg[key] = value
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return cfg


def autosave_on():
    return bool(config_load().get("autosave", False))


ARTICLE_FOR = {"nom masculin (le / un)": "un", "nom féminin (la / une)": "une"}


def vocab_front(french, entry=None):
    """Le recto à enregistrer : lemme accentué + article (un/une) si c'est un nom.
    Le genre est l'info la plus précieuse à apprendre — sans lui, on n'apprend
    jamais le/la !"""
    front = (entry.get("lemma") if entry else None) or french
    if entry:
        art = ARTICLE_FOR.get(entry.get("gender") or "")
        if art:
            front = f"{art} {front}"
    return front


# --- Le store JSON : source de vérité unique ------------------------------- #
def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def store_key(text):
    """Clé de dédup : sans article de tête, sans accents, minuscule."""
    parts = (text or "").strip().lower().split()
    while len(parts) > 1 and parts[0] in _FR_ARTICLES:
        parts = parts[1:]
    return _deaccent(" ".join(parts))


def _md_rows(path):
    """Lit les lignes d'un tableau markdown → [(mot, sens, exemple), …]."""
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
        if not mot or mot.lower() == "mot" or set(mot) <= set("-: "):
            continue
        out.append((mot, sens, ex))
    return out


def _seed_entries():
    """Migration unique : récupère l'ancien journal markdown dans le store."""
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
    data = {"version": 1, "entries": _seed_entries()}     # 1re fois : migration
    if data["entries"]:
        store_save(data)                                  # rend la migration durable
    return data


def store_save(data):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(STORE)), exist_ok=True)
        with open(STORE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"  {YELLOW}💾 store illisible :{RESET} {e}")


_STORE_FIELDS = ("front", "lemma", "sens", "pos", "gender", "example",
                 "src_word", "src_lang", "tier")


def store_upsert(record):
    """Ajoute ou met à jour un mot. Renvoie (statut, count)."""
    data = store_load()
    now = _now_iso()
    for e in data["entries"]:
        if e.get("key") == record["key"]:
            e["count"] = e.get("count", 1) + 1
            e["last_seen"] = now
            for k in _STORE_FIELDS:           # complète les trous, sans écraser
                if not e.get(k) and record.get(k):
                    e[k] = record[k]
            store_save(data)
            store_render()
            return "déjà vu", e["count"]
    rec = {k: record.get(k, "") for k in _STORE_FIELDS}
    rec.update(key=record["key"], count=1, first_seen=now, last_seen=now)
    data["entries"].append(rec)
    store_save(data)
    store_render()
    return "ajouté", 1


def store_forget(word):
    data = store_load()
    k = store_key(word)
    before = len(data["entries"])
    data["entries"] = [e for e in data["entries"] if e.get("key") != k]
    store_save(data)
    store_render()
    return before - len(data["entries"])


def store_render(path=None):
    """Régénère la vue markdown depuis le store (tri : vus récemment d'abord)."""
    path = path or VOCAB
    entries = sorted(store_load()["entries"],
                     key=lambda e: e.get("last_seen", ""), reverse=True)
    head = [
        "# 🔎 Mots du dico",
        "",
        f"*{len(entries)} mots — généré automatiquement depuis "
        "`dico_vocab.json` (la source de vérité). **Ne pas éditer à la main** : "
        "régénéré à chaque recherche. Tout ce que tu cherches atterrit ici. "
        "Pour en retirer un : `dico --forget <mot>`.*",
        "",
        "| Mot | Sens | Exemple | Vu |",
        "|-----|------|---------|----|",
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
#  Niveau 4 : Multitran hors-ligne (base SQLite locale)                       #
# --------------------------------------------------------------------------- #
MULTI_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "multitran.db")


def clean_multitran(body):
    """Transforme le corps HTML d'une entrée Multitran en lignes lisibles."""
    s = body.replace("\\n", "\n")
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</?p\b[^>]*>", "\n", s)      # début ET fin de paragraphe
    s = re.sub(r"(?i)<h1>.*?</h1>", "", s)        # titre déjà connu
    s = re.sub(r"<[^>]+>", "", s)                 # autres balises
    s = html.unescape(s)
    lines = []
    for ln in s.splitlines():
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if ln:
            lines.append(ln)
    return lines


def multitran_lookup(word):
    """Cherche un mot dans Multitran hors-ligne. Cyrillique → ru-fr, sinon fr-ru.
    Tolère les accents via la colonne nkey. Renvoie (lignes, sens, erreur)."""
    direction = "rufr" if detect_lang(word) == "ru" else "frru"
    if not os.path.exists(MULTI_DB):
        return None, direction, "base absente (lance build_multitran.py)"
    key = word.strip().lower()
    nkey = _deaccent(key)
    try:
        con = sqlite3.connect(f"file:{MULTI_DB}?mode=ro", uri=True)
        row = con.execute(
            "SELECT body FROM entries WHERE key=? AND dir=? LIMIT 1",
            (key, direction)).fetchone()
        if row is None and nkey != key:           # accents : cafe → café
            try:
                row = con.execute(
                    "SELECT body FROM entries WHERE nkey=? AND dir=? LIMIT 1",
                    (nkey, direction)).fetchone()
            except sqlite3.OperationalError:
                pass                              # base sans nkey → reconstruis-la
        con.close()
    except Exception as e:
        return None, direction, str(e)
    if not row:
        return None, direction, None
    return clean_multitran(row[0]), direction, None


# --------------------------------------------------------------------------- #
#  Niveau 5 : conjugaison hors-ligne (base SQLite locale)                     #
# --------------------------------------------------------------------------- #
CONJ_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "data", "conjugations.db")


def _conj_query(verb):
    if not os.path.exists(CONJ_DB):
        return None, None, "base absente (lance : uv run build_conjugations.py)"
    try:
        con = sqlite3.connect(f"file:{CONJ_DB}?mode=ro", uri=True)
        row = con.execute("SELECT verb, data FROM verbs WHERE verb=? LIMIT 1",
                          (verb,)).fetchone()
        if row is None:                       # tapé sans accents ? (etudier→étudier)
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
    """Forme conjuguée → infinitif, hors-ligne (« doit » → « devoir »). Renvoie
    None si la table `forms` est absente (vieille base) ou le mot inconnu."""
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
    except Exception:                         # table `forms` absente / SQLite KO
        return None
    if not rows:
        return None
    # ambigu (« suis » → être/suivre) : on garde l'infinitif le plus court,
    # souvent le plus courant.
    return min((r[0] for r in rows), key=len)


def conjugate_lookup(word):
    """Trouve l'infinitif français puis ses conjugaisons. Essaie : (1) le mot tel
    quel, (2) comme forme conjuguée (« doit » → « devoir », hors-ligne),
    (3) via traduction. Renvoie (infinitif, temps, erreur, vient_du_français)."""
    w = word.strip().lower()
    real, data, err = _conj_query(w)
    if data:
        return real, data, None, True
    if err:                                   # base absente / erreur SQLite
        return None, None, err, False
    inf = _form_to_infinitive(w)              # forme conjuguée ? (hors-ligne)
    if inf:
        real, data, _ = _conj_query(inf)
        if data:
            return real, data, None, True
    try:                                      # pas trouvé → tenter une traduction
        translation, _, _ = translate(word)
    except Exception:
        return None, None, None, False
    parts = (translation or "").strip().lower().split()
    if parts:
        real, data, _ = _conj_query(parts[0])
        if data:
            return real, data, None, False    # vient d'une traduction (mot étranger)
    return None, None, None, False


# Temps demandé après le verbe : « dico -c manger present » / « !c manger futur ».
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
    """« manger present » → (« manger », « présent »). Sinon (word, None)."""
    parts = word.split()
    if len(parts) >= 2:
        t = _norm_tense(parts[-1])
        if t:
            return " ".join(parts[:-1]), t
    return word, None


# --------------------------------------------------------------------------- #
#  Affichage                                                                  #
# --------------------------------------------------------------------------- #
def show(word, want_dict=False, want_ai=False, want_save=False,
         want_multi=False, want_conj=False, want_deep=False, want_fr=False,
         want_save_main=False):
    src_guess = detect_lang(word)
    offline_ok = want_multi or want_conj      # sections qui marchent hors-ligne

    # Si le mot est déjà français (verbe connu, ou mode -f « Wiktionnaire
    # français »), inutile et trompeur de le faire traduire par Google
    # (« manger » est aussi un mot anglais → « crèche »).
    conj_inf = conj_tenses = conj_err = None
    conj_tense = None
    conj_from_fr = False
    if want_conj:
        word, conj_tense = _split_tense(word)   # « manger present » → temps filtré
        conj_inf, conj_tenses, conj_err, conj_from_fr = conjugate_lookup(word)
    # -c a trouvé un verbe français (infinitif OU forme conjuguée) → pas de
    # « traduction » Google fr→fr inutile (doit → doit).
    direct_fr_verb = bool(conj_inf) and conj_from_fr
    # Multitran est ru↔fr : un mot en alphabet latin EST du français → pas de
    # « traduction » Google fr→fr inutile (eventail → eventail).
    multi_fr = want_multi and detect_lang(word) == "en"
    input_is_french = want_fr or direct_fr_verb or multi_fr

    translation, detected, alts = None, None, []
    if input_is_french:
        translation = conj_inf if direct_fr_verb else word.strip().lower()
        detected = "fr"
    else:
        try:
            translation, detected, alts = translate(word)
        except Exception as e:
            if not offline_ok:
                print(f"{RED}✗ Erreur / pas de connexion :{RESET} {e}")
                print(f"{DIM}  (le dico a besoin d'internet){RESET}")
                return
            print(f"  {DIM}(hors-ligne : pas de traduction rapide){RESET}")
    src = detected or src_guess
    if translation and not input_is_french:
        print(f"  {FLAG.get(src, '🌐')} {BOLD}{word}{RESET}  {DIM}→{RESET}  "
              f"🇫🇷 {BOLD}{GREEN}{translation}{RESET}")
        if alts:
            print(f"  {DIM}aussi :{RESET} {', '.join(alts)}")
    elif not translation and not offline_ok:
        print(f"{YELLOW}Aucune traduction trouvée pour « {word} ».{RESET}")
        return

    if want_multi:
        lines, direction, err = multitran_lookup(word)
        arrow = "ru→fr" if direction == "rufr" else "fr→ru"
        if lines:
            print(f"  {CYAN}📚 Multitran ({arrow}){RESET}")
            for ln in lines[:14]:
                print(f"     {ln}")
            if len(lines) > 14:
                print(f"     {DIM}… (entrée complète dans Dictionary.app — ⌃⌘D){RESET}")
        elif err:
            print(f"  {DIM}📚 Multitran : {err}{RESET}")
        else:
            print(f"  {DIM}📚 (pas dans Multitran {arrow} : « {word} »){RESET}")

    if want_conj:
        shown = conj_tenses
        if conj_tenses and conj_tense:
            shown = {k: v for k, v in conj_tenses.items() if k == conj_tense}
        if shown:
            if conj_inf and _deaccent(conj_inf) != _deaccent(word):
                print(f"  {DIM}« {word} » → forme de{RESET} {BOLD}{conj_inf}{RESET}")
            print(f"  {CYAN}🔄 {conj_inf}{RESET}  {DIM}(conjugaison){RESET}")
            width = max((len(lbl) for lbl in shown), default=0)
            sep = "  " + DIM + "·" + RESET + "  "
            for label, forms in shown.items():
                print(f"     {DIM}{label.ljust(width)}{RESET}  {sep.join(forms)}")
        elif conj_tenses and conj_tense:
            print(f"  {DIM}🔄 (« {conj_tense} » indisponible pour « {conj_inf} »){RESET}")
        elif conj_err:
            print(f"  {DIM}🔄 conjugaison : {conj_err}{RESET}")
        else:
            print(f"  {DIM}🔄 (verbe introuvable : « {word} »){RESET}")

    wikt_entry = None
    if want_fr:                               # Wiktionnaire du mot tel quel
        wikt_entry = _show_wikt(word)

    if want_dict and translation:             # Wiktionnaire de la traduction
        wikt_entry = _show_wikt(translation)

    if want_ai:
        _show_ai(word, deep=False)
    if want_deep:
        _show_ai(word, deep=True)

    auto = autosave_on()
    if (auto or want_save or want_save_main) and translation:
        entry = wikt_entry                         # réutilise la fiche déjà chargée
        if entry is None:
            try:
                entry = wiktionary(translation)    # sinon : genre (un/une) + lemme
            except Exception:
                entry = None
        front = vocab_front(translation, entry)
        if input_is_french and entry and entry["defs"]:
            d = entry["defs"][0]
            sens = d[:55] + ("…" if len(d) > 55 else "")
        else:
            sens = word                            # le mot d'origine (ru/en) = le sens
        record = {
            "key": store_key((entry.get("lemma") if entry else None) or translation),
            "front": front,
            "lemma": (entry.get("lemma") if entry else None) or translation,
            "sens": sens,
            "pos": (entry.get("pos") if entry else "") or "",
            "gender": (entry.get("gender") if entry else "") or "",
            "example": "",
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
            print(f"  {GREEN}💾 « {front} » → {status}{RESET}{tag}{badge}")
        except Exception as e:
            print(f"  {YELLOW}💾 échec de la sauvegarde :{RESET} {e}")


# --------------------------------------------------------------------------- #
#  Mode interactif                                                            #
# --------------------------------------------------------------------------- #
def _parse_inline(line, base_d, base_a, base_s, base_m, base_c, base_p, base_f, base_S):
    """Préfixe : '!f' '!d' '!m' '!c' '!a' '!p' '!s' (journal) '!S' (vocab propre)…"""
    m = re.match(r"^!([damscpfS]+)\s+(.*)$", line)
    if m:
        flags = m.group(1)
        return (m.group(2).strip(), "d" in flags, "a" in flags, "s" in flags,
                "m" in flags, "c" in flags, "p" in flags, "f" in flags, "S" in flags)
    return line, base_d, base_a, base_s, base_m, base_c, base_p, base_f, base_S


def _repl_command(line):
    """Commandes « : » du mode interactif (réglages, pas des recherches)."""
    parts = line[1:].split()
    cmd = parts[0].lower() if parts else ""
    arg = " ".join(parts[1:]).strip()
    if cmd in ("save", "autosave"):
        if arg.lower() in ("on", "off"):
            config_set("autosave", arg.lower() == "on")
            etat = "activé" if arg.lower() == "on" else "désactivé"
            print(f"  {GREEN}✓ auto-save {etat}{RESET}")
        else:
            print(f"  auto-save : {'ON' if autosave_on() else 'off'}"
                  f"   {DIM}(:save on | :save off){RESET}")
    elif cmd == "forget" and arg:
        n = store_forget(arg)
        print(f"  {GREEN}✓ « {arg} » retiré{RESET}" if n
              else f"  {DIM}« {arg} » introuvable{RESET}")
    elif cmd == "render":
        store_render()
        print(f"  {GREEN}✓ markdown régénéré{RESET}")
    else:
        print(f"  {DIM}commandes : :save on|off · :forget <mot> · :render{RESET}")


def _load_history():
    if not readline:
        return
    try:
        readline.read_history_file(HISTFILE)
    except OSError:
        pass
    readline.set_history_length(1000)


def _save_history():
    if readline:
        try:
            readline.write_history_file(HISTFILE)
        except OSError:
            pass


def interactive(base_d=False, base_a=False, base_s=False, base_m=False,
                base_c=False, base_p=False, base_f=False, base_S=False):
    _load_history()                            # ↑ rappelle les mots précédents
    # On entoure les couleurs de \001..\002 pour que readline compte bien la
    # largeur du prompt (sinon décalage du curseur en rappelant l'historique).
    if sys.stdout.isatty() and readline:
        prompt = f"\001{BLUE}\002»\001{RESET}\002 "
    else:
        prompt = f"{BLUE}»{RESET} "
    print(f"{BOLD}📖 dico{RESET} — russe/anglais → français")
    print(f"{DIM}Tape un mot puis Entrée.  Astuce : « !f » Wikt. français · "
          f"« !d » Wikt.+trad · « !m » Multitran · « !c » conjugaison · « !a » IA · "
          f"« !p » IA profonde · « !s » journal · « !S » vocab.{RESET}")
    print(f"{DIM}⚠ Trad. rapide = RU/EN → FR seulement. Pour FR→russe : « !m » ; "
          f"sens d'un mot FR : « !f » ou « !a »/« !p ».{RESET}")
    etat = "ON" if autosave_on() else "off"
    print(f"{DIM}💾 auto-save : {etat}  ·  « :save on|off » · « :forget <mot> » · "
          f"« :render ».{RESET}")
    print(f"{DIM}↑ = commande précédente · « q » ou Ctrl-D pour quitter.{RESET}\n")
    try:
        while True:
            try:
                line = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{DIM}À bientôt ! 👋{RESET}")
                break
            if not line:
                continue
            if line.lower() in ("q", "quit", "exit", "quitter"):
                print(f"{DIM}À bientôt ! 👋{RESET}")
                break
            if line.startswith(":"):           # réglage, pas une recherche
                _repl_command(line)
                continue
            word, d, a, s, m, c, pf, f, sv = _parse_inline(
                line, base_d, base_a, base_s, base_m, base_c, base_p, base_f, base_S)
            if word:
                show(word, d, a, s, m, c, pf, f, sv)
    finally:
        _save_history()


def main():
    p = argparse.ArgumentParser(
        prog="dico", add_help=True,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Dictionnaire de poche : russe/anglais → français.",
        epilog=(
            "⚠ La traduction rapide va seulement RU/EN → FR (jamais l'inverse).\n"
            "Pour aller de FR vers le russe : -m (Multitran fr→ru).\n"
            "Pour le SENS d'un mot français : -f (Wiktionnaire) ou -a / -p (Claude)."))
    p.add_argument("mots", nargs="*", help="le(s) mot(s) à traduire")
    p.add_argument("-m", "--multitran", action="store_true",
                   help="ajoute l'entrée Multitran hors-ligne (riche, ru↔fr)")
    p.add_argument("-c", "--conj", action="store_true",
                   help="conjugaison hors-ligne ; « -c manger present » pour un seul temps "
                        "(present, passe, imparfait, futur, conditionnel, subjonctif, imperatif)")
    p.add_argument("-f", "--francais", action="store_true",
                   help="Wiktionnaire du mot tel quel (déjà français, sans traduction)")
    p.add_argument("-d", "--dico", action="store_true",
                   help="Wiktionnaire après traduction (RU/EN → français)")
    p.add_argument("-a", "--ai", action="store_true",
                   help="ajoute une explication rapide de Claude (Haiku)")
    p.add_argument("-p", "--profond", action="store_true",
                   help="ajoute une explication APPROFONDIE (Opus : fiche d'étude)")
    p.add_argument("-s", "--save", action="store_true",
                   help="enregistre CE mot maintenant (dans le store de vocabulaire)")
    p.add_argument("-S", "--save-main", action="store_true",
                   help="alias de -s (même store unique ; gardé par habitude)")
    p.add_argument("--autosave", nargs="?", const="status",
                   choices=["on", "off", "status"], metavar="on|off",
                   help="enregistre AUTOMATIQUEMENT chaque recherche (réglage persistant)")
    p.add_argument("--render", action="store_true",
                   help="régénère le markdown depuis le store JSON, puis quitte")
    p.add_argument("--forget", metavar="MOT",
                   help="retire un mot du vocabulaire (curation soustractive)")
    args = p.parse_args()

    if args.autosave is not None:
        if args.autosave == "status":
            print(f"auto-save : {'ON' if autosave_on() else 'off'}")
        else:
            config_set("autosave", args.autosave == "on")
            print(f"✓ auto-save {'activé' if args.autosave == 'on' else 'désactivé'}.")
        return
    if args.forget:
        n = store_forget(args.forget)
        print(f"✓ « {args.forget} » retiré ({n})." if n
              else f"« {args.forget} » introuvable dans le store.")
        return
    if args.render:
        store_render()
        print(f"✓ markdown régénéré → {VOCAB}")
        return

    if args.mots:
        show(" ".join(args.mots), args.dico, args.ai, args.save,
             args.multitran, args.conj, args.profond, args.francais, args.save_main)
    else:
        interactive(args.dico, args.ai, args.save, args.multitran,
                    args.conj, args.profond, args.francais, args.save_main)


if __name__ == "__main__":
    main()
