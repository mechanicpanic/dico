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
| `dico -a house` | **Tuteur IA** — fiche rapide (modèle local via LM Studio, ou Claude) | non* |
| `dico -a "tu ou vous ?"` | **Question libre** au tuteur (plusieurs mots = question) | non* |
| `dico -p …` | idem, réponse détaillée | non* |
| `dico -s house` | enregistre ce mot (store de vocabulaire) | oui |
| `dico --mots-outils` | **noyau grammatical** (Lexique) : articles, prépositions, pronoms… | **non** 🔌 |
| `dico -g "Elle est parti"` | **Grammaire** — corrige une phrase, nomme la règle (Grammalecte) | **non** 🔌 |
| `dico -x "j'habitais à Lyon"` | **Rayons X** — chaque mot : lemme, temps, genre, rôle, sens | non* 🔌 |

Cumulables : `dico -mc хотеть`, `dico -fc manger`, `dico -mcdap mot`…
Mode interactif : tape `dico`, puis `!m` `!c` `!f` `!d` `!a` `!p` `!s` devant un mot.

### La carte de dictionnaire (par défaut)

Une recherche affiche une **vraie entrée** : les sens **groupés par nature** et
**numérotés**, l'article/genre de chaque nom (Lexique), la fréquence (★), les
rétro-traductions du sens principal, et une phrase d'exemple réelle (Tatoeba) :

```
» cook
     verbe      1 cuisiner ★★  2 cuire ★  3 faire la cuisine   ← bake
     nom        4 un cuisinier ★  5 une cuisine ★★             ← chef
     « Il aime cuisiner le week-end. » — He likes to cook on weekends.
» !s 4                      ← sauve « un cuisinier » (le nom, pas le verbe)
```

Le sens 1 est celui que l'auto-save garde ; **`!s N`** sauve le sens N — fini de
se battre avec les drapeaux quand Google a choisi la mauvaise nature. Un mot
**déjà français** (`maison`, `doit`) donne sa carte : nature · genre · article ·
fréquence, puis ses sens anglais. `:examples off` coupe les phrases Tatoeba.

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

### Tuteur IA : `?` dans le REPL, modèle local d'abord

Le tuteur n'est plus un « tier » qu'on active : c'est une **question qu'on pose**.
En mode interactif, `? ta question` (ou `?? …` pour une réponse détaillée) — le
tuteur connaît **le dernier mot cherché / la dernière phrase analysée** :

```
» cuisiner
» ? et cuire, c'est pareil ?
» -x j'en veux deux
» ? explique « en » ici
```

Backend, dans l'ordre : **1)** un endpoint **compatible OpenAI** (LM Studio sur
`http://localhost:1234/v1` par défaut — ou un DGX Spark / Ollama / Mistral / Groq via
`DICO_LLM_URL`, `DICO_LLM_MODEL`, `DICO_LLM_KEY`, ou `:llm <url> [modèle]` dans le REPL) ;
**2)** l'API Anthropic (`ANTHROPIC_API_KEY`) ; **3)** la commande `claude`.
Modèle recommandé (bake-off sur 5 questions de grammaire, M4 Pro) :
**Gemma 4 12B it — MLX 4-bit** (`lmstudio-community/gemma-4-12B-it-MLX-4bit`,
≈ 2 s par réponse, 5/5 réponses justes). Ministral 3 8B est plus rapide (≈ 1,5 s)
mais s'est trompé sur la règle *de/des*. Toujours préférer les poids **MLX** aux
GGUF sur Apple Silicon (≈ 2× plus rapide). Sur le DGX Spark : Mistral Small 4.
`*` local = sans internet.

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

En mode interactif : `:save on|off` · `:forget <mot>` · `:render` · `:spacy on|off` · `:llm` · `:examples on|off`.
Chaque sauvegarde enrichit le mot avec le **genre** (→ *un/une*), le lemme accentué,
la nature et la langue source ; les répétitions incrémentent un compteur `×N`.

## Installation

```sh
# outil autonome (recommandé) — commande « dico » dans le PATH
uv tool install git+https://github.com/mechanicpanic/dico
dico --setup            # télécharge / construit les bases hors-ligne (≈ 2 min)

# ou, depuis un clone (développement) :
git clone https://github.com/mechanicpanic/dico && cd dico && ./setup.sh
alias dico="python3 $PWD/dico.py"
```

Besoins : **Python 3.10+** et [`uv`](https://docs.astral.sh/uv/) (pour les
conjugaisons, spaCy et l'installation). Le cœur n'a **aucune dépendance**.
Données et réglages : `~/.dico/` (ou le dossier du clone) ; `DICO_HOME`,
`DICO_DATA`, `DICO_VOCAB`, `DICO_STORE` pour les déplacer.

```sh
# (option) tuteur IA : LM Studio sur localhost:1234 marche sans rien configurer ;
# sinon un endpoint compatible OpenAI, ou l'API Anthropic :
export DICO_LLM_URL="http://spark.local:8000/v1"  DICO_LLM_MODEL="…"
export ANTHROPIC_API_KEY="sk-ant-..."
# (option) où vivent tes cartes (un coffre Obsidian, par ex.)
export DICO_VOCAB="$HOME/notes/francais/mots-cherches.md"
```

### Sources & licences

- Code : **MIT**. Tout le reste est téléchargé chez son auteur par `dico --setup`, jamais redistribué ici.
- **Lexique 3.83** (New, Pallier et al.) — CC BY-SA · **Tatoeba** — CC BY 2.0 fr ·
  **Grammalecte** (Olivier R.) — GPL 3 · **verbecc** — conjugaisons · **spaCy** `fr_core_news_md` — MIT/CC BY-SA ·
  **Wiktionnaire** — CC BY-SA · **Multitran** : dictionnaires Apple propriétaires, *à fournir soi-même* (option `-m`).
- La traduction rapide passe par un endpoint Google non officiel (limité en débit) avec repli MyMemory.

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
