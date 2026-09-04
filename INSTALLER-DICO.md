# ⚙️ Installing the `dico` command

So you can type **`dico word`** from anywhere in your terminal.

## Option 1 — an alias (the simplest)

Add this line at the end of your `~/.zshrc`:

```sh
uv tool install git+https://github.com/mechanicpanic/dico && dico --setup   # or: alias dico="python3 $HOME/Projects/vibes/dico/dico.py"
```

Then reload the terminal:

```sh
source ~/.zshrc
```

Done! Try it:

```sh
dico maison        # (an English or Russian word → French)
dico спасибо
dico
```

> 💡 You can also just ask me (Claude): "add the dico alias to my zshrc" and
> I will do it for you.

## Option 2 — without installing

From the `francais/` directory, run it directly:

```sh
python3 dico.py house
./dico.py house          # (the file is already executable)
```

## (Optional) Faster AI: an API key

The `dico -a` option (an explanation from Claude) already works through the
`claude` command, but it is slow (~10 s) because it boots all of Claude Code.
With an **Anthropic API key**, `dico` calls the API directly (~1-2 s):

```sh
# Add to ~/.zshrc — keep the key PRIVATE (never in the code)!
export ANTHROPIC_API_KEY="sk-ant-..."
```

Then `source ~/.zshrc`. That is all: `dico -a` detects the key and takes the
fast path by itself. Without a key it falls back to the `claude` command.

> The model is set at the top of `dico.py` (`AI_MODEL`, Haiku by default —
> fast and cheap). Use `claude-opus-4-8` or `claude-sonnet-4-6` for deeper
> explanations (slower / more expensive).

## Requirements
- **Python 3** (already on your Mac).
- **Internet** (the dictionary queries a free translation service).
- **No** library to install — the standard library only.
