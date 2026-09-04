# ⚙️ Installer la commande `dico`

Pour pouvoir taper **`dico mot`** depuis n'importe où dans le terminal.

## Option 1 — un alias (le plus simple)

Ajoute cette ligne à la fin de ton fichier `~/.zshrc` :

```sh
uv tool install git+https://github.com/mechanicpanic/dico && dico --setup   # ou : alias dico="python3 $HOME/Projects/vibes/dico/dico.py"
```

Puis recharge le terminal :

```sh
source ~/.zshrc
```

Et voilà ! Essaie :

```sh
dico maison        # (mot anglais ou russe → français)
dico спасибо
dico
```

> 💡 Tu peux aussi me demander (à Claude) : « ajoute l'alias dico à mon zshrc »
> et je le fais pour toi.

## Option 2 — sans installer

Depuis le dossier `francais/`, lance directement :

```sh
python3 dico.py house
./dico.py house          # (le fichier est déjà exécutable)
```

## (Option) IA plus rapide : une clé API

L'option `dico -a` (explication par Claude) marche déjà via la commande
`claude`, mais c'est lent (~10 s) car ça démarre tout Claude Code. Avec une
**clé API Anthropic**, `dico` appelle l'API directement (~1-2 s) :

```sh
# Ajoute à ~/.zshrc — garde la clé PRIVÉE (jamais dans le code) !
export ANTHROPIC_API_KEY="sk-ant-..."
```

Puis `source ~/.zshrc`. C'est tout : `dico -a` détecte la clé et prend le
chemin rapide tout seul. Sans clé, il revient à la commande `claude`.

> Le modèle est réglé en haut de `dico.py` (`AI_MODEL`, par défaut Haiku —
> rapide et économique). Mets `claude-opus-4-8` ou `claude-sonnet-4-6` pour
> des explications plus poussées (plus lent / plus cher).

## Besoins
- **Python 3** (déjà présent sur ton Mac).
- **Internet** (le dico interroge un service de traduction gratuit).
- **Aucune** bibliothèque à installer — que la bibliothèque standard.
