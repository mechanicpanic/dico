#!/usr/bin/env python3
"""Golden `--json` outputs for the session refactor (docs/session-refactor.md).

    python3 tests/check_goldens.py            # re-run every query, diff against tests/golden/
    python3 tests/check_goldens.py --record   # (re)write the goldens; runs each query twice
                                              # and reports any field that drifted between runs
    python3 tests/check_goldens.py -k save_term,card   # only these queries (exact names)

Each query is run twice: with --json (golden/<name>.json) and as the terminal
would print it (golden/<name>.txt, ANSI stripped), each mode on its own temporary
store, so the printer refactor is proven output-identical too.

Every query runs with HOME, DICO_STORE and DICO_VOCAB pointing into a scratch
directory, so neither the real card store nor ~/.dico_config.json is touched
(and the goldens do not depend on the user's settings: autosave off, no LLM). Network answers are
served from data/translate_cache.json; keep the cache warm. Fields listed in
VOLATILE (timestamps, machine paths) are scrubbed before comparison.
"""
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DICO = os.path.join(REPO, "dico.py")
GOLDEN = os.path.join(HERE, "golden")

# (name, argv) — every one gets --json. Order matters: save-term first, so that
# --card / --grade / --due find the card.
QUERIES = [
    ("cook",         ["cook"]),                          # EN noun/verb → FR card
    ("maison",       ["maison"]),                        # FR word typed directly
    ("koshka",       ["кошка"]),                         # RU word
    ("dire",         ["dire"]),                          # FR verb
    ("phrase",       ["i have to go"]),                  # EN phrase
    # The card-direction rule (decide_direction): homographs and cognates.
    ("manger",       ["manger"]),                        # FR verb Google mistakes for English
    ("car",          ["car"]),                           # EN noun, also a FR conjunction
    ("table",        ["table"]),                         # FR/EN cognate
    ("chat",         ["chat"]),                          # FR noun / EN verb
    ("conj_dire",    ["-c", "dire"]),                    # conjugation grid
    ("fr_chat",      ["-f", "chat"]),                    # Wiktionary definition
    ("multi_chat",   ["-m", "chat"]),                    # Multitran fr→ru
    ("examples",     ["--examples", "chat"]),            # Tatoeba examples
    ("grammar",      ["-g", "elle est parti"]),          # Grammalecte
    ("xray",         ["-x", "le chat dort"]),            # x-ray (spaCy sidecar if present)
    ("paths",        ["--paths"]),
    ("save_term",    ["--save-term", "chat", "--sens", "cat"]),
    ("card",         ["--card", "chat"]),
    ("grade",        ["--grade", "chat", "--ease", "3"]),
    ("due",          ["--due"]),
    ("card_missing", ["--card", "nope"]),                # error case
]

# name → JSON paths scrubbed before comparison ("*" matches any key / index).
# Timestamps depend on the clock; the SRS schedule is relative to "now".
VOLATILE = {
    "card":  ["card.due"],
    "grade": ["card.due"],
    "due":   ["cards.*.due"],
}


# Same idea for the terminal text: regexes whose matches are blanked.
VOLATILE_TXT = {
    "card":  [r'"due": "[^"]*"'],
    "grade": [r'"due": "[^"]*"'],
    "due":   [r'"due": "[^"]*"'],
}
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# Queries that change the store: running them twice gives a different (correct)
# answer, so the --record drift probe skips them.
STATEFUL = {"save_term", "grade"}


def _scrub(obj, path):
    """Drop the field at `path` (list of keys, "*" = wildcard) in place."""
    if not path:
        return
    head, rest = path[0], path[1:]
    if isinstance(obj, dict):
        keys = list(obj) if head == "*" else ([head] if head in obj else [])
        for k in keys:
            if rest:
                _scrub(obj[k], rest)
            else:
                obj[k] = "<volatile>"
    elif isinstance(obj, list):
        idx = range(len(obj)) if head == "*" else ([int(head)] if head.isdigit() and int(head) < len(obj) else [])
        for i in idx:
            if rest:
                _scrub(obj[i], rest)
            else:
                obj[i] = "<volatile>"


def _normalise(text, name, tmp):
    text = text.replace(tmp, "<TMP>").replace(os.path.expanduser("~"), "<HOME>")
    try:
        data = json.loads(text)
    except ValueError:
        return {"_raw": text}
    for p in VOLATILE.get(name, []):
        _scrub(data, p.split("."))
    return data


def _normalise_txt(text, name, tmp):
    text = _ANSI.sub("", text).replace(tmp, "<TMP>").replace(os.path.expanduser("~"), "<HOME>")
    for rx in VOLATILE_TXT.get(name, []):
        text = re.sub(rx, "<volatile>", text)
    return text


def scratch_env(tmp):
    """HOME → the scratch dir: ~/.dico_config.json is not read (autosave off,
    no LLM), ~/.dico is scratch too. uv keeps its real caches (spaCy sidecar)."""
    home = os.path.expanduser("~")
    return dict(os.environ, HOME=tmp,
                UV_CACHE_DIR=os.environ.get("UV_CACHE_DIR") or os.path.join(home, ".cache", "uv"),
                UV_PYTHON_INSTALL_DIR=os.environ.get("UV_PYTHON_INSTALL_DIR")
                or os.path.join(home, ".local", "share", "uv", "python"),
                DICO_STORE=os.path.join(tmp, "dico_vocab.json"),
                DICO_VOCAB=os.path.join(tmp, "vocabulaire.md"),
                NO_COLOR="1", PYTHONIOENCODING="utf-8")


def run(argv, tmp, as_json=True):
    env = scratch_env(tmp)
    r = subprocess.run([sys.executable, DICO, *(["--json"] if as_json else []), *argv],
                       capture_output=True, text=True, env=env, timeout=300, cwd=REPO)
    if r.returncode:
        err = {"_exit": r.returncode, "_stdout": r.stdout, "_stderr": r.stderr[-2000:]}
        return err if as_json else json.dumps(err, ensure_ascii=False, indent=2)
    return r.stdout


def _dump(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _diff(a, b, name, ext="json"):
    ta = _dump(a) if ext == "json" else a
    tb = _dump(b) if ext == "json" else b
    return "".join(difflib.unified_diff(ta.splitlines(True), tb.splitlines(True),
                                        f"golden/{name}.{ext}", f"{name} (now)"))


def main():
    record = "--record" in sys.argv
    only = None
    if "-k" in sys.argv:
        only = sys.argv[sys.argv.index("-k") + 1].split(",")   # exact names
    os.makedirs(GOLDEN, exist_ok=True)
    tmp = {"json": tempfile.mkdtemp(prefix="dico-golden-"), "txt": tempfile.mkdtemp(prefix="dico-golden-txt-")}
    failed = []
    try:
        for name, argv in QUERIES:
            if only and name not in only:
                continue
            for ext in ("json", "txt"):
                as_json = ext == "json"
                out = run(argv, tmp[ext], as_json)
                if as_json:
                    now = _normalise(out, name, tmp[ext]) if isinstance(out, str) else out
                else:
                    now = _normalise_txt(out, name, tmp[ext])
                label = f"{name}.{ext}"
                path = os.path.join(GOLDEN, label)
                if record:
                    if name in STATEFUL:       # a second run would change the store → no drift probe
                        again = now
                    else:
                        out2 = run(argv, tmp[ext], as_json)
                        if as_json:
                            again = _normalise(out2, name, tmp[ext]) if isinstance(out2, str) else out2
                        else:
                            again = _normalise_txt(out2, name, tmp[ext])
                    if again != now:
                        print(f"~ {label}: differs between two runs — mark the field volatile:\n"
                              + _diff(now, again, name, ext))
                        failed.append(label)
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(_dump(now) if as_json else now)
                    print(f"= {label}: recorded")
                    continue
                if not os.path.exists(path):
                    print(f"? {label}: no golden (run with --record)")
                    failed.append(label)
                    continue
                with open(path, encoding="utf-8") as f:
                    want = json.load(f) if as_json else f.read()
                if want == now:
                    print(f"ok {label}")
                else:
                    print(f"FAIL {label}\n" + _diff(want, now, name, ext))
                    failed.append(label)
    finally:
        for d in tmp.values():
            shutil.rmtree(d, ignore_errors=True)
    if failed:
        print(f"\n{len(failed)} failed: {', '.join(failed)}")
        return 1
    print("\nall goldens match" if not record else "\ngoldens recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
