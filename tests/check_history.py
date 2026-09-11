#!/usr/bin/env python3
"""The tutor's history: what a Session remembers and how ai_ask uses it.
No real model is called — llm_complete is stubbed and its prompts captured.

    python3 tests/check_history.py
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_goldens import DICO, scratch_env  # noqa: E402

tmp = tempfile.mkdtemp(prefix="dico-history-")
os.environ.update({k: v for k, v in scratch_env(tmp).items()
                   if k in ("HOME", "DICO_STORE", "DICO_VOCAB", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR")})
spec = importlib.util.spec_from_file_location("dico", DICO)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

prompts, canned = [], ["**ok**"]


def fake_llm(system, user, max_tokens=400, deep=False):
    prompts.append(user)
    return canned[-1], None


d.llm_complete = fake_llm
failed = []


def ok(name, cond, detail=""):
    print(f"{'ok' if cond else 'FAIL'} {name}" + (f"\n{detail}" if not cond and detail else ""))
    if not cond:
        failed.append(name)


def in_order(text, *needles):
    pos = -1
    for n in needles:
        i = text.find(n, pos + 1)
        if i < 0:
            return f"missing: {n!r}"
        pos = i
    return ""


try:
    s = d.Session()
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet):
        s.handle("cook")
        s.handle("save 2")
        s.handle("conj")                       # the follow-up looks up « cuisiner »
        s.handle("grammar elle est parti")
        s.handle("x le chat dort")
        s.handle("def maison")
        s.handle("? tu ou vous ?")
        s.handle("?? and in the passé composé?")
    kinds = [t["kind"] for t in s.history]
    ok("turns recorded in order", kinds == ["lookup", "lookup", "grammar", "xray", "definition", "question", "question"], kinds)
    t0 = s.history[0]
    ok("lookup keeps the query AND the French word, and the sense saved",
       t0["query"] == "cook" and t0["fr"] == "cuisiner" and t0["direction"] == "to_fr" and t0["saved"] == "cuire", t0)
    t1 = s.history[1]
    ok("conj follow-up: a lookup of the French verb with its section",
       t1["query"] == "cuisiner" and t1["fr"] == "cuisiner" and "conjugation" in t1["sections"], t1)
    ok("grammar turn carries the correction", s.history[2].get("corrected") == "elle est partie", s.history[2])
    p2 = prompts[-1]
    miss = in_order(p2, "Earlier in this session",
                    "Looked up « cook » → « cuisiner »", "saved « cuire »",
                    "Looked up « cuisiner » (a French word) (conjugation shown)",
                    "Grammar check: « elle est parti » → « elle est partie »",
                    "X-ray of « le chat dort »",
                    "Definition of « maison »",
                    "Asked: tu ou vous ?", "Answered: **ok**",
                    "Question: and in the passé composé?")
    ok("the second question's prompt lists the turns, oldest first", miss == "", miss + "\n" + p2)
    ok("no redundant « Last word » line when the history has it", "Last word looked up" not in p2, p2)
    # caps
    canned.append("x" * 1000)
    with contextlib.redirect_stdout(quiet):
        s.handle("? long one")
    a = s.history[-1]["answer"]
    ok(f"answers trimmed to {d.HISTORY_ANSWER_CHARS} chars", len(a) == d.HISTORY_ANSWER_CHARS and a.endswith("…"), len(a))
    with contextlib.redirect_stdout(quiet):
        for i in range(15):
            s.handle(f"grammar je mange {i} pomme")
    ok(f"history capped at {d.HISTORY_TURNS} turns", len(s.history) == d.HISTORY_TURNS
       and all(t["kind"] == "grammar" for t in s.history) and s.history[-1]["sentence"].endswith("14 pomme"), len(s.history))
    # exposure
    r = s.handle("history")
    lines = d.render(r)
    ok("« history » returns the turns and renders them", r["_kind"] == "history" and len(r["history"]) == d.HISTORY_TURNS
       and lines[0].strip().startswith("1.") and "Grammar check" in lines[0], lines[:2])
    r = s.handle(":forget")
    ok(":forget alone clears it", r["setting"] == "forget_history" and s.history == [] and "cleared" in d.render(r)[0], r)
    ok("« history » when empty", "nothing yet" in d.render(s.handle("history"))[0])
    # the one-shot prompt (no history) is what it always was
    s2 = d.Session()
    s2.last["word"] = "cook"
    s2.last["fr"] = "cuisiner"
    d.ai_ask(s2, "why?")
    ok("one-shot prompt unchanged", prompts[-1] == "Context: Last word looked up: « cook » (→ « cuisiner »).\n\nQuestion: why?", prompts[-1])
    # the --json one-shot never carries the history
    class A:
        pass
    a = A(); a.words = ["cook"]; a.json = True
    for k in "ai profond grammaire xray examples francais dico say syn multitran conj save save_main".split():
        setattr(a, k, False)
    j = d._public(s.handle_args(a))
    ok("--json result carries no history key", "history" not in j and not [k for k in j if k.startswith("_")], j.keys())
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failed:
    print(f"\n{len(failed)} failed: {', '.join(failed)}")
    sys.exit(1)
print("\nhistory: ok")
