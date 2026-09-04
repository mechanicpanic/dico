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
    dico -g "<phrase>"    corrige une PHRASE (Grammalecte hors-ligne) et nomme la règle
    dico -x "<phrase>"    rayons X : chaque mot → lemme, temps, genre, rôle, sens
    dico --mots-outils    noyau grammatical glosé (articles, prépositions, pronoms…)
    dico --mots-outils -s en faire des cartes (front = mot, dos = sens anglais)
    dico -mda <mot>       tout en même temps
    dico                  mode interactif (tape des mots en boucle)

Chaque mot français affiche un badge « 📊 fréquence · nature · genre » (Lexique
3.83, hors-ligne) et les cognats/faux-amis sont signalés (« table » reste
« table », « pain » EN est signalé « aussi français : un pain »).

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
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

try:
    import readline  # flèche ↑ = rappeler la commande précédente (interactif)
except ImportError:
    readline = None

_HERE = os.path.dirname(os.path.abspath(__file__))
DICO_HOME = os.environ.get("DICO_HOME") or os.path.expanduser("~/.dico")
# En dépôt git (dossier data/ à côté, ou dossier accessible en écriture hors
# site-packages) : tout reste local. Installé comme outil : ~/.dico/.
_IN_REPO = "site-packages" not in _HERE and os.path.isdir(os.path.join(_HERE, "data"))
DATA_DIR = os.environ.get("DICO_DATA") or (os.path.join(_HERE, "data") if _IN_REPO
                                           else os.path.join(DICO_HOME, "data"))
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
def _google_query(word, tl="fr", sl="auto"):
    """Endpoint gratuit de Google (auto-détection de la langue source), JSON brut.
    Réessaie une fois en cas de 429 (limite de débit)."""
    q = urllib.parse.quote(word)
    url = ("https://translate.googleapis.com/translate_a/single"
           f"?client=gtx&sl={sl}&tl={tl}&dt=t&dt=bd&q={q}")
    try:
        raw = _get(url)
    except urllib.error.HTTPError as e:
        if e.code != 429:
            raise
        time.sleep(1.5)
        raw = _get(url)
    return json.loads(raw)


_POS_FR = {"noun": "nom", "verb": "verbe", "adjective": "adjectif", "adverb": "adverbe",
           "preposition": "préposition", "pronoun": "pronom", "conjunction": "conjonction",
           "interjection": "interjection", "abbreviation": "abréviation",
           "article": "article", "phrase": "expression", "suffix": "suffixe",
           "auxiliary verb": "auxiliaire", "modal verb": "modal", "prefix": "préfixe"}


def translate_rich(word, tl="fr", sl="auto"):
    """(traduction, langue détectée, sens groupés par nature) —
    sens = [(nature, [(terme, [rétro-traductions]), …]), …]. C'est la structure
    d'un vrai dictionnaire, que « aussi : … » aplatissait."""
    data = _google_query(word, tl, sl)
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
    """Compatibilité : (traduction, langue détectée, alternatives plates)."""
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
    """Secours : API gratuite MyMemory."""
    q = urllib.parse.quote(word)
    url = f"https://api.mymemory.translated.net/get?q={q}&langpair={src}|{tl}"
    data = json.loads(_get(url))
    translation = data["responseData"]["translatedText"].strip()
    alts = []
    for m in data.get("matches", []):
        t = (m.get("translation") or "").strip()
        if t and t.lower() != translation.lower() and t not in alts:
            alts.append(t)
    return translation, src, alts[:6]


def translate(word, tl="fr"):
    """Essaie Google, puis MyMemory en secours (MyMemory : vers le français seulement)."""
    src_guess = detect_lang(word)
    try:
        return translate_google(word, tl)
    except Exception:
        if tl != "fr":
            raise
        return translate_mymemory(word, src_guess)


def _tatoeba(fr_word, to="eng", limit=1):
    """Phrases d'exemple réelles (Tatoeba, CC-BY) : [(phrase FR, traduction)]."""
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
    return out


_BAND_STARS = {"très courant": "★★★", "courant": "★★", "moyen": "★"}


def _lex_gender_row(word):
    """Pour un nom : la ligne Lexique AVEC genre (« maison » : la ligne la plus
    fréquente peut être l'adjectif « fait maison », sans genre)."""
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
    """Terme français → (recto avec article si nom, entrée Lexique)."""
    lex = lexique_lookup(term)
    if lex and " " not in term.strip() and lex["cgram"].startswith(("NOM", "ADJ")) \
            and not lex["genre"]:
        g = _lex_gender_row(term)                 # nom sans genre → chercher la ligne genrée
        if g:
            lex = dict(lex, genre=g, article={"m": "un", "f": "une"}[g], pos="nom")
    if lex and lex["article"] and " " not in term.strip():
        return f"{lex['article']} {lex['ortho']}", lex
    return term, lex


def _render_card_to_fr(word, src, translation, groups, examples=True):
    """Carte RU/EN → FR : sens numérotés, groupés par nature (« !s N » = sauver le N)."""
    print(f"  {FLAG.get(src, '🌐')} {BOLD}{word}{RESET}")
    # La traduction principale (celle que l'auto-save garde) doit être le sens 1.
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
    if _LAST["hints"] <= 2:
        print(f"     {DIM}!s N sauve le sens N (défaut : 1){RESET}")


def _render_card_fr(word, lex, examples=True):
    """Carte d'un mot FRANÇAIS : nature · genre/article · fréquence, puis sens EN."""
    head, lex2 = _fr_head(word)
    lex = lex2 or lex
    if lex and lex["cgram"].startswith("NOM") and not lex["genre"]:
        try:                                   # Lexique muet sur le genre (« maison ») → Wiktionnaire
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
    print(f"  🇫🇷 {BOLD}{word}{RESET}" + (f"   {DIM}{' · '.join(bits)}{RESET}" if bits else ""))
    try:
        _, _, groups = translate_rich(word, tl="en", sl="fr")   # sl explicite → sens groupés
    except Exception:
        groups = []
        try:                                   # secours : MyMemory fr→en (1 sens)
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
    if examples:
        for fr, tr in _tatoeba(word, "eng"):
            print(f"     {DIM}« {fr} » — {tr}{RESET}")


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


# --- Modèle local / compatible OpenAI (LM Studio, DGX Spark, Ollama, Mistral…) ---
# Réglages : DICO_LLM_URL (défaut http://localhost:1234/v1), DICO_LLM_MODEL,
# DICO_LLM_KEY — ou dans ~/.dico_config.json (llm_url / llm_model / llm_key).
def _llm_cfg():
    cfg = config_load()
    return (os.environ.get("DICO_LLM_URL") or cfg.get("llm_url") or "http://localhost:1234/v1",
            os.environ.get("DICO_LLM_MODEL") or cfg.get("llm_model") or "",
            os.environ.get("DICO_LLM_KEY") or cfg.get("llm_key") or "")


def _llm_models(url, key):
    """Modèles servis par l'endpoint (LM Studio : ceux chargés en premier)."""
    req = urllib.request.Request(url.rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {key}"} if key else {})
    with urllib.request.urlopen(req, timeout=3) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [m.get("id") for m in data.get("data", []) if m.get("id")]


def _llm_openai(system, user, max_tokens):
    """POST /chat/completions (compatible OpenAI). Renvoie (texte, erreur)."""
    url, model, key = _llm_cfg()
    try:
        if not model:
            ids = _llm_models(url, key)
            if not ids:
                return None, "aucun modèle chargé (LM Studio : charge un modèle)"
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
        text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S)   # modèles « pensants »
        return (text, None) if text else (None, "réponse vide")
    except urllib.error.URLError as e:
        return None, f"endpoint injoignable ({url}) — {getattr(e, 'reason', e)}"
    except Exception as e:
        return None, str(e)


def _llm_reachable():
    url, _, key = _llm_cfg()
    try:
        return bool(_llm_models(url, key))
    except Exception:
        return False


def llm_complete(system, user, max_tokens=400, deep=False):
    """1) endpoint local/compatible OpenAI s'il répond, 2) API Anthropic, 3) `claude`."""
    if os.environ.get("DICO_LLM_URL") or config_load().get("llm_url") or _llm_reachable():
        return _llm_openai(system, user, max_tokens)
    model = AI_MODEL_DEEP if deep else AI_MODEL
    prompt = system + "\n\n" + user
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return _ai_via_api(prompt, api_key, model, max_tokens)
    return _ai_via_cli(prompt, model)


_TUTOR_SYS = ("Tu es un professeur de français pour un adulte débutant (A1→A2) dont la "
              "langue maternelle est le russe et qui parle anglais. Réponds en français "
              "simple, TRÈS court (2 à 5 lignes), avec un exemple. Mets la traduction "
              "anglaise entre parenthèses pour les mots difficiles. Pas d'introduction, "
              "pas de tableau ; **gras** et listes « - » bienvenus.")
_LAST = {"word": "", "fr": "", "sentence": "", "senses": []}   # contexte « ? » / « !s N »


def ai_explain(word, deep=False):
    """Fiche d'un mot (« !a mot » / « -a mot »)."""
    prompt = _ai_prompt_deep(word) if deep else _ai_prompt(word)
    return llm_complete(_TUTOR_SYS, prompt, 1100 if deep else 400, deep=deep)


def ai_ask(question, deep=False):
    """Question libre au tuteur, avec le contexte du dernier mot / de la dernière phrase."""
    ctx = []
    if _LAST["sentence"]:
        ctx.append(f"La dernière phrase analysée : « {_LAST['sentence']} ».")
    if _LAST["word"]:
        ctx.append(f"Le dernier mot cherché : « {_LAST['word']} »"
                   + (f" (→ « {_LAST['fr']} »)" if _LAST["fr"] else "") + ".")
    user = ("Contexte : " + " ".join(ctx) + "\n\n" if ctx else "") + "Question : " + question
    return llm_complete(_TUTOR_SYS, user, 700 if deep else 350, deep=deep)


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


def _llm_label():
    url, model, _ = _llm_cfg()
    if os.environ.get("DICO_LLM_URL") or config_load().get("llm_url") or _llm_reachable():
        try:
            model = model or (_llm_models(url, _llm_cfg()[2]) or ["modèle local"])[0]
        except Exception:
            model = model or "modèle local"
        return model.split("/")[-1][:28]
    return "Claude"


def _show_ai(word, deep, question=None):
    icon = "🧠" if deep else "🤖"
    label = _llm_label()
    pad = " " * 12
    print(f"  {CYAN}{icon} {label} réfléchit…{RESET}", end="\r", flush=True)
    t0 = time.time()
    text, err = (ai_ask(question, deep) if question else ai_explain(word, deep=deep))
    label += f"  {DIM}{time.time() - t0:.1f}s{RESET}{CYAN}"
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
    _HERE if _IN_REPO else DICO_HOME, "vocabulaire.md")
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
MULTI_DB = os.path.join(DATA_DIR, "multitran.db")


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
CONJ_DB = os.path.join(DATA_DIR, "conjugations.db")


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
        cand = parts[0]
        real, data, _ = _conj_query(cand)
        if not data:
            inf = _form_to_infinitive(cand)   # trad. = forme conjuguée ? (doit → devoir)
            if inf:
                real, data, _ = _conj_query(inf)
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
    """« manger present » ou « present manger » → (« manger », « présent »)."""
    parts = word.split()
    if len(parts) >= 2:
        t = _norm_tense(parts[-1])
        if t:
            return " ".join(parts[:-1]), t
        t = _norm_tense(parts[0])
        if t:
            return " ".join(parts[1:]), t
    return word, None


# --- Tableau de conjugaison : grille pronom × temps (lisible d'un coup d'œil) -- #
_CONJ_PERSONS = ["je", "tu", "il", "nous", "vous", "ils"]
_CONJ_IMP = {0: 1, 1: 3, 2: 4}              # impératif (tu/nous/vous) → lignes 1,3,4
_CONJ_SUBJ = ("je", "j'", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles")
_CONJ_SHORT = {
    "présent": "prés.", "passé composé": "passé c.", "imparfait": "imparf.",
    "futur simple": "futur", "conditionnel": "cond.", "subjonctif": "subj.",
    "impératif": "impér.",
}


def _bare_form(form):
    """« je doive » / « qu'il doive » / « j'ai dû » → la forme sans pronom sujet."""
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
    return s                                  # impératif (« éteins ») : pas de pronom


def _conj_lines(shown):
    """Lignes colorées d'une grille pronom × temps à partir de {temps: [formes]}."""
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
    # en-tête : le présent ressort (gras), le reste est atténué
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
#  Niveau 6 : Lexique 3.83 hors-ligne (lemme, nature, genre, fréquence)       #
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

# Classes fermées = les « mots-outils » (la colle grammaticale qui ne se devine pas).
MOTS_OUTILS_CGRAM = ("ART:def", "ART:ind", "PRE", "CON", "AUX",
                     "PRO:per", "PRO:dem", "PRO:pos", "PRO:ind", "PRO:rel")


def _cgram_label(cgram):
    return _CGRAM_LABEL.get(cgram, (cgram or "").lower())


def _freq_band(ff):
    """freqfilms2 = occurrences par million (sous-titres). → étiquette lisible."""
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
    """Hors-ligne : une forme (même sans accents) → son meilleur enregistrement
    Lexique (le plus fréquent, pour lever les homographes : « doit » → devoir,
    « de » → préposition). Renvoie un dict ou None."""
    if not os.path.exists(LEXIQUE_DB):
        return None
    w = (word or "").strip().lower()
    if not w:
        return None
    cols = "ortho,lemme,cgram,genre,nombre,freqfilms,freqlivres"
    try:
        con = sqlite3.connect(f"file:{LEXIQUE_DB}?mode=ro", uri=True)
        rows = con.execute(f"SELECT {cols} FROM lexique WHERE ortho=? "
                           "ORDER BY freqfilms DESC LIMIT 1", (w,)).fetchone()
        if rows is None:                      # tapé sans accents : etre → être
            rows = con.execute(f"SELECT {cols} FROM lexique WHERE northo=? "
                               "ORDER BY freqfilms DESC LIMIT 1",
                               (_deaccent(w),)).fetchone()
        con.close()
    except Exception:
        return None
    if not rows:
        return None
    ortho, lemme, cgram, genre, nombre, ff, fl = rows
    article = None
    if (cgram or "").startswith("NOM"):
        article = {"m": "un", "f": "une"}.get(genre)
    return {"ortho": ortho, "lemma": lemme, "cgram": cgram,
            "pos": _cgram_label(cgram), "genre": genre or None,
            "nombre": nombre or None, "freqfilms": ff, "freqlivres": fl,
            "article": article, "band": _freq_band(ff)}


# Glose anglaise (+ astuce d'usage pour les plus traîtres) des mots-outils.
# Ensemble fermé → table écrite à la main, juste et hors-ligne. Sert à l'affichage
# de « --mots-outils » et à en faire des cartes (« --mots-outils -s »).
MOTS_OUTILS_GLOSS = {
    # déterminants / articles
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
    # prépositions
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
    # conjonctions
    "et": "and", "ou": "or", "mais": "but", "donc": "so / therefore",
    "car": "because / for", "ni": "nor / neither", "or": "now / yet (récit)",
    "que": "that / than (conj.); whom / which (rel., objet)", "comme": "as / like / since",
    "quand": "when", "si": "if / whether", "lorsque": "when", "puisque": "since (cause)",
    "quoique": "although",
    # pronoms personnels
    "je": "I", "tu": "you (sg., informel)", "il": "he / it", "elle": "she / it",
    "on": "one / we (informel)", "nous": "we / us", "vous": "you (poli / pl.)",
    "ils": "they (m.)", "elles": "they (f.)", "me": "me / to me",
    "m'": "me (+ voyelle)", "te": "you / to you", "t'": "you (+ voyelle)",
    "se": "oneself (réfléchi)", "s'": "oneself (+ voyelle)", "lui": "(to) him / her",
    "moi": "me (accentué)", "toi": "you (accentué)", "soi": "oneself (accentué)",
    "eux": "them (m., accentué)", "leur": "(to) them; their",
    "y": "there / to it  (remplace à + chose)",
    "en": "in / by (prép.); of it / some  (pron. : remplace de + nom)",
    # démonstratifs
    "ça": "that / it (informel)", "c'": "it / this (c' + est)", "cela": "that",
    "ceci": "this", "celui": "the one (m.)", "celle": "the one (f.)",
    "ceux": "the ones (m.pl.)", "celles": "the ones (f.pl.)",
    # relatifs / interrogatifs
    "qui": "who / which (sujet); whom (après prép.)", "dont": "whose / of which / about which",
    "où": "where / when (temps)", "lequel": "which one (m.)", "laquelle": "which one (f.)",
    "quoi": "what (après prép. / seul)",
    # indéfinis
    "rien": "nothing", "personne": "no one / anyone", "chacun": "each one",
    # auxiliaires
    "avoir": "to have (auxiliaire du passé composé)",
    "être": "to be (auxiliaire; + verbes de mouvement/pronominaux)",
}


def mots_outils(limit=120):
    """Top des mots-outils (classes fermées) par fréquence, dédupliqués par lemme.
    → [(lemme, cgram, freqfilms)]. C'est l'échafaudage grammatical à apprendre."""
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
    """Affiche le noyau de mots-outils (mot — sens), groupé par catégorie.
    Avec save=True, ajoute au vocabulaire ceux qui ont une glose (→ cartes)."""
    rows = mots_outils(limit)
    if not rows:
        print(f"{YELLOW}Lexique absent — lance : python3 build_lexique.py{RESET}")
        return
    groups = {}
    for lemme, cgram, f in rows:
        groups.setdefault(_cgram_label(cgram), []).append(lemme)
    order = ["article défini", "article indéfini", "préposition", "conjonction",
             "pronom personnel", "pronom démonstratif", "pronom possessif",
             "pronom indéfini", "pronom relatif", "auxiliaire"]
    print(f"{BOLD}🧩 Noyau de mots-outils{RESET} {DIM}(les {len(rows)} plus "
          f"fréquents — la colle grammaticale){RESET}\n")
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
        print(f"  {GREEN}💾 {saved} mots-outils ajoutés au vocabulaire "
              f"(→ Anki){RESET}")
    else:
        print(f"  {DIM}astuce : « dico --mots-outils {limit} -s » pour les "
              f"ajouter à tes cartes.{RESET}")




# --------------------------------------------------------------------------- #
#  Rayons X : analyse d'une phrase (Lexique + conjugaisons, spaCy en option)   #
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
    """Découpe simple : sépare les élisions (j'habite → j' + habite) et les
    pronoms accrochés (tiens-moi → tiens + moi), sans casser Saint-Pétersbourg."""
    s = re.sub(r"(?i)\b(j|l|d|m|n|t|s|c|qu)['’]", lambda m: m.group(1) + "' ", sentence)
    s = re.sub(r"(?i)(\w)-" + _CLITICS + r"\b", r"\1 \2", s)
    toks = []
    for raw in s.split():
        w = raw.strip(".,;:!?…«»\"()[]")
        if w:
            toks.append(w)
    # « j habitais » tapé sans apostrophe → j' (élision devant voyelle / h)
    for i in range(len(toks) - 1):
        if toks[i].lower() in ("j", "l", "d", "m", "n", "t", "s", "c", "qu") \
                and toks[i + 1][:1].lower() in "aeiouyhàâéèêëîïôûùœ":
            toks[i] += "'"
    return toks


def _conj_tense_of(inf, form):
    """À quel(s) temps / personne(s) « form » appartient-elle pour « inf » ?
    → texte compact (« présent · je/tu · impératif · tu ») ou None. Compare
    d'abord à l'exact (mangé ≠ mange) ; sans accents seulement si tu n'en as
    pas tapé. Participe passé tolérant à l'accord (partie/partis → parti)."""
    _, data, _ = _conj_query(inf)
    if not data:
        return None
    f = form.lower()
    typed_plain = _deaccent(f) == f            # tapé sans accents → tolérance
    hits = {}                                  # temps → [personnes]
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
    """Analyse spaCy via le sidecar (uv). None si indisponible / désactivé."""
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
                continue                       # « doit » n'explique pas « devoir »
            return sens[:40]
    return ""


def _show_xray(sentence):
    """Chaque mot : lemme · nature · temps/personne · genre · fréquence · rôle · sens."""
    sentence = sentence.strip()
    print(f"  {BOLD}🩻 {sentence}{RESET}")
    try:                                       # traduction de la phrase entière (1 appel)
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
        src_tag = "spaCy + Lexique + conjugaisons"
    else:
        toks = [(w, None, None, "") for w in _xray_tokens(sentence)]
        src_tag = ("Lexique + conjugaisons — spaCy désactivé (« :spacy on » pour les rôles)"
                   if not spacy_on else
                   "Lexique + conjugaisons — spaCy indisponible (uv ?)" if not shutil.which("uv")
                   else "Lexique + conjugaisons — spaCy : échec")
    rows = []
    for text, lemma, pos, role in toks:
        text = text.strip("-–")                # spaCy laisse « -moi »
        if not text:
            continue
        lex = lexique_lookup(text)
        lem = (lex["lemma"] if lex else None) or lemma or text
        nature = (lex["pos"] if lex else "") or _SPACY_POS_FR.get(pos or "", (pos or "").lower())
        if not nature and text[:1].isupper() and rows:
            nature = "nom propre"
        detail, genre, band = "", "", ""
        # Verbe ? La base de conjugaison a le dernier mot (« tiens » : Lexique dit
        # interjection, spaCy dit verbe, la base dit tenir → verbe).
        inf = _form_to_infinitive(text)
        is_verb = bool(inf) and (
            pos in ("VERB", "AUX") or lex is None
            or lex["cgram"].startswith(("VER", "AUX", "ONO")))
        if not inf and (pos in ("VERB", "AUX") or (lex and lex["cgram"].startswith(("VER", "AUX")))):
            for cand in (lemma, lem):          # lemme spaCy (partie → partir) puis Lexique
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
        try:                                   # 1 seul appel pour tous les mots manquants
            lem = [rows[i][1] or rows[i][0] for i in todo]
            tr, _, _ = translate_google("\n".join(lem), tl="en")
            parts = [p.strip() for p in tr.split("\n")]
            if len(parts) == len(todo):
                for i, g in zip(todo, parts):
                    r = rows[i]
                    rows[i] = r[:6] + (g.lower() if g.lower() != (r[1] or r[0]).lower() else "",)
        except Exception:
            pass
    heads = ("mot", "lemme", "nature", "temps", "genre·fréq", "rôle", "sens")
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
#  Grammaire : Grammalecte hors-ligne (data/grammalecte, via build_grammalecte.py)
# --------------------------------------------------------------------------- #
GRAMMALECTE_DIR = os.path.join(DATA_DIR, "grammalecte")
_GC = None
_GRAM_TYPE = {
    "ppas": "participe passé", "gn": "accord (groupe nominal)", "conj": "conjugaison",
    "gv": "groupe verbal", "vmode": "mode du verbe", "infi": "infinitif",
    "imp": "impératif", "inte": "interrogation", "sgpl": "singulier / pluriel",
    "conf": "confusion", "bs": "barbarisme", "eleu": "élision", "elis": "élision",
    "typo": "typographie", "esp": "espaces", "nbsp": "espace insécable",
    "maj": "majuscule", "apos": "apostrophe", "tu": "tournure", "redon": "redondance",
    "pleo": "pléonasme", "date": "date", "num": "nombre", "poncfin": "ponctuation",
    "virg": "virgule", "mc": "mot composé", "ocr": "OCR",
}


def _grammalecte():
    """Charge (une fois) le correcteur vendu dans data/grammalecte. None si absent."""
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
    """Phrase surlignée → chaque faute (quoi, pourquoi, suggestion) → version corrigée."""
    gc = _grammalecte()
    if gc is None:
        print(f"  {YELLOW}✗ Grammalecte absent — lance : python3 build_grammalecte.py "
              f"(ou ./setup.sh){RESET}")
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
    for a, b, col in spans:                    # la phrase, fautes surlignées
        if a < pos:
            continue
        out += text[pos:a] + f"{col}{BOLD}{text[a:b]}{RESET}"
        pos = b
    out += text[pos:]
    print(f"  📝 {out}")
    if not errs and not sp:
        print(f"  {GREEN}✓ Rien à signaler — c'est correct !{RESET}")
        return
    n = 0
    for e in errs:                             # chaque faute : quoi, pourquoi, → suggestion
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
        print(f"  {YELLOW}{n}.{RESET} « {BOLD}{e['sValue']}{RESET} » — mot inconnu "
              f"(orthographe ? accent ?)" + (f"  {DIM}→ {' / '.join(sug)}{RESET}" if sug else ""))
    fixed, changed = text, False              # version corrigée (1re suggestion)
    for e in sorted(errs, key=lambda e: -e["nStart"]):
        sug = e.get("aSuggestions") or []
        if sug:
            fixed = fixed[:e["nStart"]] + sug[0] + fixed[e["nEnd"]:]
            changed = True
    if changed:
        print(f"  {GREEN}✓ {fixed}{RESET}")

# --------------------------------------------------------------------------- #
#  Affichage                                                                  #
# --------------------------------------------------------------------------- #
def show(word, want_dict=False, want_ai=False, want_save=False,
         want_multi=False, want_conj=False, want_deep=False, want_fr=False,
         want_save_main=False, want_gram=False, want_xray=False):
    if (want_ai or want_deep) and len(word.split()) > 1 and not (
            want_dict or want_fr or want_multi or want_conj):
        _show_ai(word, deep=bool(want_deep), question=word)   # question libre
        return
    if want_gram or want_xray:                # outils « phrase » : pipeline à part
        _LAST["sentence"] = word.strip()
        if want_xray:
            _show_xray(word)
        if want_gram:
            _show_grammar(word)
        return
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
                print(f"{RED}✗ Erreur / pas de connexion :{RESET} {e}")
                print(f"{DIM}  (le dico a besoin d'internet){RESET}")
                return
            else:
                print(f"  {DIM}(hors-ligne : pas de traduction rapide){RESET}")
    src = detected or src_guess
    _LAST.update(word=word, fr=translation or "")

    # Cognat / faux-ami : le mot TAPÉ est-il lui-même un mot français courant ?
    # (« table » EN → Google dit « tableau », mais « table » EST français.)
    cognate = None
    if (translation and not input_is_french and len(word.strip()) >= 3):
        c = lexique_lookup(word)
        if (c and c["freqfilms"] >= 1 and c["cgram"][:3] in ("NOM", "ADJ", "VER")
                and _deaccent(c["lemma"]) != _deaccent(translation)):
            cands = {a.strip().lower() for a in [translation, *alts]}
            if word.strip().lower() in cands or c["ortho"].lower() in cands:
                translation = c["ortho"]      # Google le propose aussi → on le préfère
            else:
                cognate = c                   # sinon : simple alerte « aussi français »

    lex_fr = lexique_lookup(translation) if translation else None
    if not translation and not offline_ok:
        print(f"{YELLOW}Aucune traduction trouvée pour « {word} ».{RESET}")
        return
    if translation:
        ex_on = config_load().get("examples", True)
        is_fr = input_is_french or _deaccent(translation.lower()) == _deaccent(word.strip().lower())
        if is_fr:
            _render_card_fr(translation, lex_fr, examples=ex_on and not want_conj)
        else:
            _render_card_to_fr(word, src, translation, groups if not input_is_french else [],
                               examples=ex_on)

    if cognate:                               # faux-ami potentiel : on le signale
        art = (cognate["article"] + " ") if cognate["article"] else ""
        g = (" " + ("masc." if cognate["genre"] == "m" else "fém.")) \
            if cognate["genre"] else ""
        print(f"  {YELLOW}↔ « {word} » est aussi un mot français{RESET} : "
              f"{BOLD}{art}{cognate['lemma']}{RESET} {DIM}({cognate['pos']}{g}, "
              f"{cognate['band']}) — « !f {word} » pour le sens{RESET}")

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
            for line in _conj_lines(shown):       # grille pronom × temps, alignée
                print(f"     {line}")
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

    if want_ai or want_deep:
        q = word if len(word.split()) > 1 else None   # plusieurs mots = question libre
        _show_ai(word, deep=bool(want_deep), question=q)

    auto = autosave_on()
    if (auto or want_save or want_save_main) and translation:
        # Enrichissement : 1) fiche Wiktionnaire déjà affichée (-f/-d, riche),
        # 2) Lexique HORS-LIGNE (lemme/genre/nature, sans réseau),
        # 3) en tout dernier recours seulement, une requête Wiktionnaire.
        entry, lex = wikt_entry, lex_fr
        # Locution (plusieurs mots, hors article de tête) ? On garde le GROUPE
        # entier (« éteindre le feu ») au lieu de le réduire à « un feu ».
        core = translation.strip().split()
        while len(core) > 1 and core[0].lower() in _FR_ARTICLES:
            core = core[1:]
        is_phrase = len(core) > 1
        if not is_phrase and entry is None and lex is None:
            try:
                entry = wiktionary(translation)    # réseau, seulement pour un mot seul
            except Exception:
                entry = None
        if is_phrase:
            lemma = " ".join(core)
            front = lemma                          # pas d'article devant une locution
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
            sens = ""                              # carte de conj. : le verso = les formes
        else:
            sens = word                            # le mot d'origine (ru/en) = le sens
        # Conjugaison → on met le PRÉSENT au dos de la carte (autres temps : plus tard).
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
            print(f"  {GREEN}💾 « {front} » → {status}{RESET}{tag}{badge}")
        except Exception as e:
            print(f"  {YELLOW}💾 échec de la sauvegarde :{RESET} {e}")


# --------------------------------------------------------------------------- #
#  Mode interactif                                                            #
# --------------------------------------------------------------------------- #
_FLAG_SET = set("damscpfgx")
_FLAG_LONG = {
    "conj": "c", "conjugaison": "c", "dico": "d", "wikt": "d",
    "francais": "f", "fr": "f", "multitran": "m", "multi": "m",
    "ai": "a", "ia": "a", "profond": "p", "deep": "p",
    "save": "s", "sauve": "s", "sauver": "s",
    "gram": "g", "grammaire": "g", "grammar": "g",
    "xray": "x", "analyse": "x", "rayons": "x",
}
_FLAG_HELP = ("d=Wiktionnaire+trad  f=Wiktionnaire(FR)  m=Multitran  c=conjugaison  "
              "a=IA  p=IA profonde  s=sauver  g=grammaire  x=analyse")
_FLAG_TOKEN = re.compile(r"(?:(?<=\s)|^)(--?|!)\s*([A-Za-z]+)(?=\s|$)")


def _parse_line(line):
    """Préfixes de commande N'IMPORTE OÙ dans la ligne, tolérants :
       « !c manger » · « ! c manger » · « manger !c » · « -c manger » ·
       « --conj manger » · « !cf mot » · « !c !f mot ». Insensible à la casse.
       Renvoie (mot, flags:set, erreur|None)."""
    flags, err = set(), None

    def take(m):
        nonlocal err
        pre, letters = m.group(1), m.group(2)
        low = letters.lower()
        if low in _FLAG_LONG:                       # --conj / -conj / !conj
            flags.add(_FLAG_LONG[low])
            return " "
        if pre == "--":
            err = f"option inconnue « {pre}{letters} »"
            return " "
        if any(ch not in _FLAG_SET for ch in low):
            if pre == "!":                          # « ! » = intention claire
                err = f"préfixe inconnu « !{letters} » — {_FLAG_HELP}"
                return " "
            return m.group(0)                       # « -er » : fait partie du mot
        flags.update(low)                           # S ≡ s (même store)
        return " "

    rest = _FLAG_TOKEN.sub(take, line)
    word = " ".join(rest.split())
    return word, flags, err


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
    elif cmd == "llm":
        url, model, _ = _llm_cfg()
        if arg:
            parts = arg.split()
            config_set("llm_url", parts[0]) if "://" in parts[0] else config_set("llm_model", parts[0])
            if len(parts) > 1:
                config_set("llm_model", parts[1])
            url, model, _ = _llm_cfg()
        etat = "OK" if _llm_reachable() else "injoignable"
        print(f"  tuteur : {url}  ·  modèle : {model or '(premier chargé)'}  ·  {etat}"
              f"   {DIM}(:llm <url> [modèle] · :llm <modèle>){RESET}")
    elif cmd in ("examples", "exemples"):
        if arg.lower() in ("on", "off"):
            config_set("examples", arg.lower() == "on")
        print(f"  exemples Tatoeba : {'ON' if config_load().get('examples', True) else 'off'}")
    elif cmd == "spacy":
        if arg.lower() in ("on", "off"):
            config_set("xray_spacy", arg.lower() == "on")
        etat = "ON" if config_load().get("xray_spacy", True) else "off"
        print(f"  spaCy pour « !x » : {etat}   {DIM}(:spacy on | :spacy off — off = "
              f"instantané, Lexique seul){RESET}")
    else:
        print(f"  {DIM}commandes : :save on|off · :forget <mot> · :render · :spacy on|off · :llm{RESET}")


def _load_history():
    if not readline:
        return
    try:
        readline.read_history_file(HISTFILE)
    except OSError:
        pass
    readline.set_history_length(1000)


def _save_term(french, sens, src_lang="en", tier="google", quiet=False):
    """Sauve un terme français (recto avec article si nom) avec « sens » au dos."""
    front, lex = _fr_head(french)
    lemma = (lex["lemma"] if lex else french)
    rec = {"key": store_key(lemma), "front": front, "lemma": lemma, "sens": sens,
           "pos": (lex["pos"] if lex else ""), "gender": (lex["genre"] if lex else "") or "",
           "example": "", "src_word": sens, "src_lang": src_lang, "tier": tier}
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


def interactive(base_d=False, base_a=False, base_s=False, base_m=False,
                base_c=False, base_p=False, base_f=False, base_S=False,
                base_g=False, base_x=False):
    base_flags = {k for k, v in (("d", base_d), ("a", base_a), ("s", base_s or base_S),
                                 ("m", base_m), ("c", base_c), ("p", base_p),
                                 ("f", base_f), ("g", base_g), ("x", base_x)) if v}
    _load_history()                            # ↑ rappelle les mots précédents
    try:                                       # pour détecter un REPL devenu obsolète
        src_mtime = os.path.getmtime(os.path.abspath(__file__))
    except OSError:
        src_mtime = 0
    warned_stale = False
    # On entoure les couleurs de \001..\002 pour que readline compte bien la
    # largeur du prompt (sinon décalage du curseur en rappelant l'historique).
    if sys.stdout.isatty() and readline:
        prompt = f"\001{BLUE}\002»\001{RESET}\002 "
    else:
        prompt = f"{BLUE}»{RESET} "
    etat = f"{GREEN}ON{RESET}" if autosave_on() else f"{DIM}off{RESET}"
    print(f"\n{BOLD}📖 dico{RESET}  —  russe / anglais → français"
          f"        {DIM}auto-save{RESET} {etat}   {DIM}tuteur {_llm_label()}{RESET}\n")
    left = [("mot", "carte : sens numérotés · genre · exemple"),
            ("!c verbe", "conjugaison"),
            ("!g phrase", "grammaire : corrige + explique la règle"),
            ("!x phrase", "rayons X : lemme · temps · rôle · sens"),
            ("? question", "tuteur IA (contexte : le dernier mot)")]
    right = [("!s N", "sauve le sens N de la carte"),
             ("!f  !d", "Wiktionnaire : mot FR / après trad."),
             ("!m mot", "Multitran ru↔fr, hors-ligne"),
             ("!a  !p", "fiche IA courte / longue"),
             ("q", "quitter")]
    kw, dw = max(len(k) for k, _ in left), max(len(d) for _, d in left)
    kw2 = max(len(k) for k, _ in right)
    for (k1, d1), (k2, d2) in zip(left, right):
        print(f"   {BOLD}{CYAN}{k1.ljust(kw)}{RESET}  {d1.ljust(dw)}    "
              f"{BOLD}{CYAN}{k2.ljust(kw2)}{RESET}  {d2}")
    print(f"\n   {DIM}préfixe avant ou après le mot (« -c » = « !c »)  ·  "
          f":save  :forget  :render  :spacy  :llm  ·  ↑ historique{RESET}\n")
    try:
        while True:
            try:
                line = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{DIM}À bientôt ! 👋{RESET}")
                break
            if not line:
                continue
            if not warned_stale:                # dico.py modifié depuis le lancement ?
                try:
                    if os.path.getmtime(os.path.abspath(__file__)) > src_mtime:
                        warned_stale = True
                        print(f"{YELLOW}⚠ dico.py a changé depuis le lancement de "
                              f"cette session — tape « q » puis relance « dico » "
                              f"pour la dernière version.{RESET}")
                except OSError:
                    pass
            if line.lower() in ("q", "quit", "exit", "quitter"):
                print(f"{DIM}À bientôt ! 👋{RESET}")
                break
            if line.startswith(":"):           # réglage, pas une recherche
                _repl_command(line)
                continue
            ms = re.match(r"^[!-]\s*s\s*(\d+)$", line, re.I)   # « !s 2 » : sauver le sens 2
            if ms:
                n = int(ms.group(1)); senses = _LAST.get("senses") or []
                if 1 <= n <= len(senses):
                    _save_term(senses[n - 1], _LAST.get("word", ""),
                               detect_lang(_LAST.get("word", "")))
                else:
                    print(f"  {DIM}sens {n} inconnu — la dernière carte en a {len(senses)}{RESET}")
                continue
            if line.startswith("?"):           # question libre au tuteur (contexte = dernier mot)
                deep = line.startswith("??")
                q = line.lstrip("?").strip()
                if q:
                    _show_ai(None, deep, question=q)
                else:
                    print(f"  {DIM}« ? ta question » — ex : ? cuisiner vs cuire · "
                          f"? pourquoi « de » ici · ?? (réponse détaillée){RESET}")
                continue
            word, fl, perr = _parse_line(line)
            if perr:
                print(f"  {YELLOW}✗ {perr}{RESET}")
                continue
            fl |= base_flags
            if not word:
                print(f"  {DIM}il manque le mot : « !{''.join(sorted(fl)) or 'c'} <mot> »"
                      f"   ({_FLAG_HELP}){RESET}")
                continue
            show(word, "d" in fl, "a" in fl, "s" in fl, "m" in fl, "c" in fl,
                 "p" in fl, "f" in fl, False, "g" in fl, "x" in fl)
    finally:
        _save_history()


def run_setup():
    """Construit les bases dans DATA_DIR : conjugaisons (verbecc via uv), index des
    formes, Lexique, Grammalecte, et Multitran si les .dictionary Apple existent."""
    os.makedirs(DATA_DIR, exist_ok=True)
    env = dict(os.environ, DICO_DATA=DATA_DIR)
    steps = [("Conjugaisons (verbecc, via uv)", ["uv", "run", os.path.join(_HERE, "build_conjugations.py")]),
             ("Index des formes (doit → devoir)", [sys.executable, os.path.join(_HERE, "build_conj_forms.py")]),
             ("Lexique 3.83 (fréquence, genres)", [sys.executable, os.path.join(_HERE, "build_lexique.py")]),
             ("Grammalecte (dico -g)", [sys.executable, os.path.join(_HERE, "build_grammalecte.py")])]
    bundles = os.path.expanduser("~/Library/Dictionaries")
    if all(os.path.isdir(os.path.join(bundles, f"multitran_{d}.dictionary")) for d in ("rufr", "frru")):
        steps.append(("Multitran (dictionnaires Apple)", ["bash", os.path.join(_HERE, "setup.sh"), "--multitran-only"]))
    else:
        print(f"{DIM}(Multitran : dictionnaires Apple absents — l'option -m restera inactive){RESET}")
    for label, cmd in steps:
        print(f"{BOLD}==> {label}{RESET}")
        if cmd[0] == "uv" and not shutil.which("uv"):
            print(f"  {YELLOW}uv absent — installe-le (https://docs.astral.sh/uv/) puis relance{RESET}")
            continue
        r = subprocess.run(cmd, env=env)
        if r.returncode:
            print(f"  {YELLOW}✗ étape en échec ({r.returncode}){RESET}")
    print(f"{GREEN}✓ Terminé → {DATA_DIR}{RESET}")


def as_json(text, args):
    """Représentation JSON d'une recherche — pour une interface graphique."""
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
    p.add_argument("-g", "--grammaire", action="store_true",
                   help="corrige une PHRASE française (Grammalecte, hors-ligne) et nomme la règle")
    p.add_argument("-x", "--xray", action="store_true",
                   help="passe une PHRASE aux rayons X : chaque mot → lemme, nature, genre, fréquence")
    p.add_argument("--autosave", nargs="?", const="status",
                   choices=["on", "off", "status"], metavar="on|off",
                   help="enregistre AUTOMATIQUEMENT chaque recherche (réglage persistant)")
    p.add_argument("--render", action="store_true",
                   help="régénère le markdown depuis le store JSON, puis quitte")
    p.add_argument("--forget", metavar="MOT",
                   help="retire un mot du vocabulaire (curation soustractive)")
    p.add_argument("--setup", action="store_true",
                   help="télécharge/construit les bases hors-ligne (conjugaisons, Lexique, "
                        "Grammalecte ; Multitran si les dictionnaires Apple sont présents)")
    p.add_argument("--json", action="store_true",
                   help="sortie JSON (pour une interface graphique / Raycast / etc.)")
    p.add_argument("--save-term", metavar="TERME",
                   help="enregistre ce terme français (avec --sens : le sens au dos)")
    p.add_argument("--sens", metavar="TEXTE", default="",
                   help="sens (mot d'origine / traduction) pour --save-term")
    p.add_argument("--context", metavar="TEXTE", default="",
                   help="contexte pour une question (-a) : dernier mot / dernière phrase")
    p.add_argument("--mots-outils", nargs="?", const=120, type=int, metavar="N",
                   help="affiche le NOYAU de mots-outils (articles, prépositions, "
                        "pronoms, conjonctions, auxiliaires) — l'échafaudage grammatical")
    args = p.parse_args()

    if args.setup:
        return run_setup()
    if args.save_term:
        if args.json:
            front, status, cnt = _save_term(args.save_term, args.sens,
                                            detect_lang(args.sens or "en"), quiet=True)
            return print(json.dumps({"saved": front, "status": status, "count": cnt,
                                     "sens": args.sens}, ensure_ascii=False))
        return _save_term(args.save_term, args.sens, detect_lang(args.sens or "en"))
    if args.context:
        _LAST["word"] = args.context
    if args.json:
        return print(json.dumps(as_json(" ".join(args.mots), args), ensure_ascii=False, indent=2))
    if args.mots_outils is not None:
        show_mots_outils(args.mots_outils, save=(args.save or args.save_main))
        return
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
             args.multitran, args.conj, args.profond, args.francais, args.save_main,
             args.grammaire, args.xray)
    else:
        interactive(args.dico, args.ai, args.save, args.multitran,
                    args.conj, args.profond, args.francais, args.save_main,
                    args.grammaire, args.xray)


if __name__ == "__main__":
    main()
