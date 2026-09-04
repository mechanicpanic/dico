# dico 🇫🇷

Un dictionnaire de poche en ligne de commande : **russe / anglais → français**,
pensé pour un apprenant russophone/anglophone. Cœur **zéro dépendance**
(bibliothèque standard de Python 3) ; plusieurs niveaux, dont deux **hors-ligne**.

## Niveaux (cumulables)

| Commande | Source | Internet ? |
|---|---|---|
| `dico кошка` | Google (rapide) | oui |
| `dico -m кошка` | **Multitran** (riche, ru↔fr) | **non** 🔌 |
| `dico -c manger` | **Conjugaison** (~7000 verbes, 7 temps) | **non** 🔌 |
| `dico -c doit` | **Forme conjuguée** → infinitif (*doit → devoir*) | **non** 🔌 |
| `dico -f manger` | **Wiktionnaire** — mot déjà français | oui |
| `dico -d house` | **Wiktionnaire** — après traduction | oui |
| `dico -a house` | **Claude Haiku** — fiche rapide | oui |
| `dico -p house` | **Claude Opus** — fiche d'étude | oui |
| `dico -s house` | enregistre ce mot (store de vocabulaire) | oui |
| `dico --mots-outils` | **noyau grammatical** (Lexique) : articles, prépositions, pronoms… | **non** 🔌 |
| `dico -g "Elle est parti"` | **Grammaire** — corrige une phrase, nomme la règle (Grammalecte) | **non** 🔌 |
| `dico -x "j'habitais à Lyon"` | **Rayons X** — chaque mot : lemme, temps, genre, rôle, sens | non* 🔌 |

Cumulables : `dico -mc хотеть`, `dico -fc manger`, `dico -mcdap mot`…
Mode interactif : tape `dico`, puis `!m` `!c` `!f` `!d` `!a` `!p` `!s` devant un mot.

**Pas besoin de taper les accents** : `etre` trouve *être*, `creche` trouve *crèche*.
**Préfixes tolérants** (mode interactif) : `!c manger`, `! c manger`, `manger !c`, `-c manger`,
`--conj manger`, `!cf mot`, `!C MANGER` — tous équivalents. Préfixe inconnu → message clair.

### Phrases : `-g` (grammaire) et `-x` (rayons X)

- **`dico -g "<phrase>"`** — correcteur **Grammalecte** (GPL, pur Python, installé par
  `build_grammalecte.py` dans `data/grammalecte/`) : phrase avec les fautes surlignées,
  puis chaque faute *(quoi · pourquoi · → suggestion)*, puis la **version corrigée**.
  Idéal pour écrire tes propres phrases et apprendre la règle qui te manque.
- **`dico -x "<phrase>"`** — analyse mot à mot : lemme, nature, **temps + personne**
  (via la base de conjugaison — plus fiable que spaCy pour l'imparfait), genre, fréquence,
  **rôle** (sujet / COD / verbe principal…) et sens. Les rôles viennent de **spaCy**
  (`tools/xray_spacy.py`, lancé par `uv run` — modèle téléchargé au 1ᵉʳ appel, ≈ 3 s
  ensuite). Sans spaCy ou avec `:spacy off`, tout le reste marche instantanément,
  hors-ligne. *La ligne de traduction anglaise de la phrase demande internet.*

### Lexique 3.83 — savoir, hors-ligne (badge sur chaque recherche)

Chaque mot français affiche un **badge** `📊 fréquence · nature · genre`
(*très courant → rare*, via [Lexique](http://www.lexique.org)), pour savoir s'il
vaut la peine d'être mémorisé. Lexique sert aussi à : enrichir l'auto-save
(lemme + genre **sans réseau**), et **détecter les cognats/faux-amis** — `table`
(EN) reste `table` (FR), mais `pain` (EN→*douleur*) est signalé *« aussi français :
un pain »*. Et `dico --mots-outils` sort l'échafaudage grammatical qui ne se
devine pas (le, de, à, que, être, avoir…) **avec leur sens anglais** ; ajoute
`-s` pour en faire des cartes Anki (`dico --mots-outils -s`).

## Vocabulaire : auto-save + store JSON

Tout ce que tu cherches peut être **enregistré automatiquement**. La **source de
vérité** est `dico_vocab.json` (à côté du markdown) ; le `.md` n'en est qu'une
**vue régénérée** — tu n'édites plus jamais le markdown à la main, et `push_anki.py`
lit le store directement. La curation est **soustractive** : on sauve tout, tu
*retires* le déchet.

| Commande | Effet |
|---|---|
| `dico --autosave on` / `off` | active/désactive l'enregistrement auto (persistant) |
| `dico -s mot` | enregistre ce mot maintenant (même si l'auto-save est off) |
| `dico --forget mot` | retire un mot (curation soustractive) |
| `dico --render` | régénère le markdown depuis le store JSON |

En mode interactif : `:save on|off` · `:forget <mot>` · `:render` · `:spacy on|off`.
Chaque sauvegarde enrichit le mot avec le **genre** (→ *un/une*), le lemme accentué,
la nature et la langue source ; les répétitions incrémentent un compteur `×N`.

## Installation

```sh
# alias (zsh)
alias dico="python3 /Users/aleph/Projects/vibes/dico/dico.py"

# (option) explication IA rapide via l'API — sinon repli sur la commande `claude`
export ANTHROPIC_API_KEY="sk-ant-..."

# (option) où --save écrit le vocabulaire (sinon : vocabulaire.md local)
export DICO_VOCAB="/Users/aleph/Projects/vibes/francais/vocabulaire.md"
```

Besoins : **Python 3** (intégré au Mac). Aucune bibliothèque à installer pour le
cœur. `-a`/`-p` utilisent l'API Anthropic (clé `ANTHROPIC_API_KEY`) ou la
commande `claude`. Le modèle est réglable en haut de `dico.py` (`AI_MODEL`,
`AI_MODEL_DEEP`).

## Données hors-ligne (`data/`)

Les bases SQLite ne sont **pas** versionnées (≈ 600 Mo). On les reconstruit :

```sh
./setup.sh
```

- **Conjugaisons** → `build_conjugations.py` (via `verbecc` + `uv`). Autonome.
- **Multitran** → nécessite les dictionnaires Apple
  `~/Library/Dictionaries/multitran_{rufr,frru}.dictionary` (issus des `.zip`
  Multitran). `setup.sh` les convertit avec `pyglossary`, puis
  `build_multitran.py`.

Sans ces bases, `dico` marche quand même — seuls `-m` et `-c` sont désactivés.

## Fichiers

| Fichier | Rôle |
|---|---|
| `dico.py` | l'outil (zéro dépendance) |
| `build_conjugations.py` | construit `data/conjugations.db` |
| `build_multitran.py` | construit `data/multitran.db` (depuis les `.txt` convertis) |
| `setup.sh` | reconstruit toutes les bases |
| `data/` | bases SQLite **(non versionnées)** |
