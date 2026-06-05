#!/usr/bin/env python3
"""dico — un petit dictionnaire de poche : russe/anglais → français.

Niveaux (cumulables) :
    dico <mot>            traduction rapide          (Google, par défaut)
    dico -m <mot>         + Multitran HORS-LIGNE      (riche, ru↔fr, sans internet)
    dico -d <mot>         + Wiktionnaire APRÈS trad   (RU/EN → français)
    dico -f <mot-fr>      + Wiktionnaire DIRECT       (le mot est déjà français)
    dico -c <verbe>       + conjugaison HORS-LIGNE    (présent, passé composé, futur…)
    dico -a <mot>         + explication IA rapide     (Claude Haiku : fiche courte)
    dico -p <mot>         + explication APPROFONDIE   (Claude Opus : fiche d'étude)
    dico -s  <mot>        sauvegarde aussi le mot dans vocabulaire.md
    dico -mda <mot>       tout en même temps
    dico                  mode interactif (tape des mots en boucle)

Détecte la langue source (russe si cyrillique, sinon anglais). La traduction
rapide et le Wiktionnaire vont vers le français ; Multitran fait ru→fr (mot
cyrillique) ou fr→ru (mot latin).

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
    return {"pos": pos, "ipa": ipa, "gender": gender, "defs": defs}


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


def wiktionary(word):
    """Fiche française d'un mot. Essaie d'abord le mot tel quel, puis une
    recherche tolérante aux accents — en gardant la fiche la PLUS riche (évite
    « étre » au lieu de « être »)."""
    tried = set()
    for cand in dict.fromkeys(
            [word, word.lower(),
             word.split()[0].lower() if word.split() else word]):
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
    else:
        print(f"  {DIM}📖 (pas de fiche Wiktionnaire pour « {lookup_word} »){RESET}")


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
SAVE_HEADER = "## Ajouts du dico"
SAVE_SEP = "|-----|------|---------|"


def save_to_vocab(translation, original):
    """Ajoute une ligne au tableau « Ajouts du dico » de vocabulaire.md."""
    row = f"| {translation} | {original} |  |"
    try:
        with open(VOCAB, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = "# 📒 Vocabulaire\n"
    if f"| {translation} |" in content:
        return "déjà présent"
    if SAVE_HEADER not in content:
        block = (f"\n{SAVE_HEADER}\n*Mots ajoutés automatiquement avec "
                 f"`dico --save`.*\n\n| Mot | Sens | Exemple |\n{SAVE_SEP}\n{row}\n")
        content = content.rstrip() + "\n" + block
    else:
        sidx = content.find(SAVE_SEP, content.index(SAVE_HEADER))
        if sidx == -1:
            content = content.rstrip() + "\n" + row + "\n"
        else:
            at = sidx + len(SAVE_SEP)
            content = content[:at] + "\n" + row + content[at:]
    with open(VOCAB, "w", encoding="utf-8") as f:
        f.write(content)
    return "ajouté"


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
    Renvoie (lignes, sens, erreur)."""
    direction = "rufr" if detect_lang(word) == "ru" else "frru"
    if not os.path.exists(MULTI_DB):
        return None, direction, "base absente (lance build_multitran.py)"
    try:
        con = sqlite3.connect(f"file:{MULTI_DB}?mode=ro", uri=True)
        row = con.execute(
            "SELECT body FROM entries WHERE key=? AND dir=? LIMIT 1",
            (word.strip().lower(), direction),
        ).fetchone()
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


def conjugate_lookup(word):
    """Trouve l'infinitif français puis ses conjugaisons. Cherche d'abord tel
    quel (hors-ligne) ; sinon traduit le mot vers le français, puis réessaie.
    Renvoie (infinitif, temps, erreur)."""
    real, data, err = _conj_query(word.strip().lower())
    if data:
        return real, data, None
    if err:                                   # base absente / erreur SQLite
        return None, None, err
    try:                                      # pas trouvé → tenter une traduction
        translation, _, _ = translate(word)
    except Exception:
        return None, None, None
    parts = (translation or "").strip().lower().split()
    if parts:
        real, data, _ = _conj_query(parts[0])
        if data:
            return real, data, None
    return None, None, None


# --------------------------------------------------------------------------- #
#  Affichage                                                                  #
# --------------------------------------------------------------------------- #
def show(word, want_dict=False, want_ai=False, want_save=False,
         want_multi=False, want_conj=False, want_deep=False, want_fr=False):
    src_guess = detect_lang(word)
    offline_ok = want_multi or want_conj      # sections qui marchent hors-ligne

    # Si le mot est déjà français (verbe connu, ou mode -f « Wiktionnaire
    # français »), inutile et trompeur de le faire traduire par Google
    # (« manger » est aussi un mot anglais → « crèche »).
    conj_inf = conj_tenses = conj_err = None
    if want_conj:
        conj_inf, conj_tenses, conj_err = conjugate_lookup(word)
    direct_fr_verb = bool(conj_inf) and _deaccent(conj_inf) == _deaccent(word)
    input_is_french = want_fr or direct_fr_verb

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
        if conj_tenses:
            print(f"  {CYAN}🔄 {conj_inf}{RESET}  {DIM}(conjugaison){RESET}")
            width = max((len(lbl) for lbl in conj_tenses), default=0)
            sep = "  " + DIM + "·" + RESET + "  "
            for label, forms in conj_tenses.items():
                print(f"     {DIM}{label.ljust(width)}{RESET}  {sep.join(forms)}")
        elif conj_err:
            print(f"  {DIM}🔄 conjugaison : {conj_err}{RESET}")
        else:
            print(f"  {DIM}🔄 (verbe introuvable : « {word} »){RESET}")

    if want_fr:                               # Wiktionnaire du mot tel quel
        _show_wikt(word)

    if want_dict and translation:             # Wiktionnaire de la traduction
        _show_wikt(translation)

    if want_ai:
        _show_ai(word, deep=False)
    if want_deep:
        _show_ai(word, deep=True)

    if want_save and translation:
        try:
            status = save_to_vocab(translation, word)
            print(f"  {GREEN}💾 « {translation} » → {status} dans vocabulaire.md{RESET}")
        except Exception as e:
            print(f"  {YELLOW}💾 échec de la sauvegarde :{RESET} {e}")


# --------------------------------------------------------------------------- #
#  Mode interactif                                                            #
# --------------------------------------------------------------------------- #
def _parse_inline(line, base_d, base_a, base_s, base_m, base_c, base_p, base_f):
    """Préfixe : '!f' (Wikt. français) '!d' '!m' '!c' '!a' '!p' '!s'…"""
    m = re.match(r"^!([damscpf]+)\s+(.*)$", line)
    if m:
        flags = m.group(1)
        return (m.group(2).strip(), "d" in flags, "a" in flags, "s" in flags,
                "m" in flags, "c" in flags, "p" in flags, "f" in flags)
    return line, base_d, base_a, base_s, base_m, base_c, base_p, base_f


def interactive(base_d=False, base_a=False, base_s=False, base_m=False,
                base_c=False, base_p=False, base_f=False):
    print(f"{BOLD}📖 dico{RESET} — russe/anglais → français")
    print(f"{DIM}Tape un mot puis Entrée.  Astuce : « !f » Wikt. français · "
          f"« !d » Wikt.+trad · « !m » Multitran · « !c » conjugaison · « !a » IA · "
          f"« !p » IA profonde · « !s » sauver.{RESET}")
    print(f"{DIM}« q » ou Ctrl-D pour quitter.{RESET}\n")
    while True:
        try:
            line = input(f"{BLUE}»{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}À bientôt ! 👋{RESET}")
            return
        if not line:
            continue
        if line.lower() in ("q", "quit", "exit", "quitter"):
            print(f"{DIM}À bientôt ! 👋{RESET}")
            return
        word, d, a, s, m, c, pf, f = _parse_inline(
            line, base_d, base_a, base_s, base_m, base_c, base_p, base_f)
        if word:
            show(word, d, a, s, m, c, pf, f)


def main():
    p = argparse.ArgumentParser(
        prog="dico", add_help=True,
        description="Dictionnaire de poche : russe/anglais → français.")
    p.add_argument("mots", nargs="*", help="le(s) mot(s) à traduire")
    p.add_argument("-m", "--multitran", action="store_true",
                   help="ajoute l'entrée Multitran hors-ligne (riche, ru↔fr)")
    p.add_argument("-c", "--conj", action="store_true",
                   help="ajoute la conjugaison hors-ligne (présent, passé composé, futur…)")
    p.add_argument("-f", "--francais", action="store_true",
                   help="Wiktionnaire du mot tel quel (déjà français, sans traduction)")
    p.add_argument("-d", "--dico", action="store_true",
                   help="Wiktionnaire après traduction (RU/EN → français)")
    p.add_argument("-a", "--ai", action="store_true",
                   help="ajoute une explication rapide de Claude (Haiku)")
    p.add_argument("-p", "--profond", action="store_true",
                   help="ajoute une explication APPROFONDIE (Opus : fiche d'étude)")
    p.add_argument("-s", "--save", action="store_true",
                   help="sauvegarde le mot dans vocabulaire.md")
    args = p.parse_args()
    if args.mots:
        show(" ".join(args.mots), args.dico, args.ai, args.save,
             args.multitran, args.conj, args.profond, args.francais)
    else:
        interactive(args.dico, args.ai, args.save, args.multitran,
                    args.conj, args.profond, args.francais)


if __name__ == "__main__":
    main()
