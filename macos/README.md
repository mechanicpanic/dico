# Dico — popup macOS 📖

Un petit panneau flottant, natif macOS, posé par-dessus le dictionnaire
[`dico`](../README.md). Il vit dans la barre de menus (aucune icône dans le Dock)
et s'ouvre **partout** avec **⌥D**.

![modes](https://img.shields.io/badge/modes-5-4c6ef5)

## Ce que ça fait

Un champ, cinq modes. Entrée lance la requête.

| Mode | Chip | Ce qu'on y voit |
|---|---|---|
| **Mot** | 📖 | Traduction, acceptions groupées par nature, en puces numérotées. Genre coloré (m bleu, f rose), fréquence en ★. **Cliquer une puce sauve le terme** dans le vocabulaire (ou **⌘1…⌘9**). Exemple + rétro-traductions. |
| **Conjuguer** | 🔁 | Grille je/tu/il/nous/vous/ils × 7 temps, pronoms retirés, colonne du présent surlignée. |
| **Grammaire** | ✅ | La phrase avec les fautes surlignées (rouge = grammaire, orange = orthographe), les messages numérotés, les suggestions en puces vertes, la phrase corrigée + **Copier**. |
| **Rayons X** | 🔬 | Tableau compact : mot · lemme · nature · temps · rôle · sens. |
| **Demander ?** | 💬 | Le tuteur (LLM local) répond en markdown léger. Le dernier mot consulté lui est passé en `--context`. |

**Préfixes** : taper `-c `, `-g `, `-x ` ou `?` en tête du champ bascule le mode
et retire le préfixe.

## Raccourcis

| | |
|---|---|
| `⌥D` | ouvrir / fermer le panneau (global, depuis n'importe quelle app) |
| `Échap` | fermer |
| `⌘K` | vider le champ |
| `⌘1`…`⌘9` | sauver la n-ième acception |
| clic à l'extérieur | fermer |

Le raccourci global passe par Carbon `RegisterEventHotKey` : **aucune
autorisation d'Accessibilité n'est demandée**.

## Construire

```bash
./build.sh                                   # → build/Dico.app
./build/Dico.app/Contents/MacOS/Dico --selftest   # éprouve la chaîne CLI→Swift
open build/Dico.app                          # puis ⌥D
./install.sh                                 # → /Applications/Dico.app
```

Pas de projet Xcode : `xcrun swiftc` suffit (Xcode Command Line Tools,
Swift 5.9+, macOS 14+, Apple Silicon).

## Prérequis

L'app ne fait que piloter la CLI `dico` — il faut donc `dico` et Python 3 :

```bash
uv tool install git+https://github.com/mechanicpanic/dico
dico --setup
```

L'app cherche, dans l'ordre : `$DICO_BIN`, puis `dico` dans
`/opt/homebrew/bin`, `~/.local/bin`, `/usr/local/bin`, `/usr/bin`, `/bin` ;
à défaut elle exécute `python3 $DICO_SCRIPT` ou
`python3 ~/Projects/vibes/dico/dico.py`. Le mode **Demander ?** a en plus
besoin du LLM local (LM Studio sur `http://localhost:1234`).

## Fichiers

```
Sources/DicoClient.swift   lance la CLI, décode le dernier objet JSON
Sources/DicoModel.swift    modes, état, requêtes, sauvegarde, toasts
Sources/PanelView.swift    palette, matériau, champ, puces de mode, pied de page
Sources/ResultViews.swift  les cinq vues de résultat
Sources/DicoApp.swift      @main, barre de menus, panneau, ⌥D, --selftest
```
