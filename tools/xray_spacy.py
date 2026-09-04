# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "spacy>=3.8,<3.9",
#   "fr-core-news-md @ https://github.com/explosion/spacy-models/releases/download/fr_core_news_md-3.8.0/fr_core_news_md-3.8.0-py3-none-any.whl",
# ]
# ///
"""Sidecar spaCy : analyse morpho-syntaxique d'une phrase française → JSON.
Lancé par dico via `uv run` (dépendances mises en cache après le 1er appel)."""
import json, sys
import spacy

nlp = spacy.load("fr_core_news_md")
doc = nlp(" ".join(sys.argv[1:]) or sys.stdin.read())
out = [{"text": t.text, "lemma": t.lemma_, "pos": t.pos_,
        "morph": t.morph.to_dict(), "dep": t.dep_, "head": t.head.i, "i": t.i}
       for t in doc if not t.is_space]
print(json.dumps(out, ensure_ascii=False))
