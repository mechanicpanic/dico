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
| `dico -f manger` | **Wiktionnaire** — mot déjà français | oui |
| `dico -d house` | **Wiktionnaire** — après traduction | oui |
| `dico -a house` | **Claude Haiku** — fiche rapide | oui |
| `dico -p house` | **Claude Opus** — fiche d'étude | oui |
| `dico -s house` | sauvegarde → `vocabulaire.md` | oui |

Cumulables : `dico -mc хотеть`, `dico -fc manger`, `dico -mcdap mot`…
Mode interactif : tape `dico`, puis `!m` `!c` `!f` `!d` `!a` `!p` `!s` devant un mot.

**Pas besoin de taper les accents** : `etre` trouve *être*, `creche` trouve *crèche*.

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
