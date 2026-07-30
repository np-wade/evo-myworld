"""Drafting family — Stage 6 candidates.

- sumy-textrank-citepost: declared composition — sumy TextRank extractive
  summary per section, then a citation post-processor that appends [n] markers
  (from the fixed research input) to sentences containing evidence excerpts.
- sumy-lsa-citepost: same composition with the LSA summarizer.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate, provision_venv  # noqa: E402

_SCRIPT = r"""
import json, re, sys

method = sys.argv[1]
req = json.load(sys.stdin)

from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
if method == "textrank":
    from sumy.summarizers.text_rank import TextRankSummarizer as Summarizer
else:
    from sumy.summarizers.lsa import LsaSummarizer as Summarizer

drafts = []
for section in req["sections"]:
    content = section.get("content", "")
    parser = PlaintextParser.from_string(content, Tokenizer("english"))
    summarizer = Summarizer()
    picked = summarizer(parser.document, 3)
    body = " ".join(str(s) for s in picked) or content[:400]

    # citation post-processor: bind [n] to sentences quoting research evidence
    n = 0
    key_by_concept = {}
    for concept in req["concepts"]:
        rec = req["research"].get(concept["id"], {})
        sources = rec.get("sources", [])
        evidence = rec.get("evidence", [])
        if sources and evidence:
            n += 1
            key_by_concept[concept["name"]] = (n, evidence[0].get("excerpt", ""))
    sentences = re.split(r"(?<=[.!?])\s+", body)
    out_sentences = []
    for sentence in sentences:
        for name, (num, excerpt) in key_by_concept.items():
            if excerpt and excerpt[:60] in sentence and f"[{num}]" not in sentence:
                sentence = sentence.rstrip() + f" [{num}]"
        out_sentences.append(sentence)
    drafts.append(f"## {section.get('title', 'Section')}\n\n" + " ".join(out_sentences))

print(json.dumps(drafts))
"""


class _SumyDraft(Candidate):
    method = ""
    stages = {"drafting"}

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        self._python, reason = provision_venv("sumy", ["sumy", "nltk", "numpy"])
        if self._python is None:
            return False, reason
        # sumy needs the nltk punkt tokenizer data
        probe = subprocess.run(
            [str(self._python), "-c",
             "import nltk; nltk.download('punkt', quiet=True); "
             "nltk.download('punkt_tab', quiet=True)"],
            capture_output=True, timeout=300)
        if probe.returncode != 0:
            return False, f"nltk data download failed: {probe.stderr.decode()[-200:]}"
        return True, ""

    def draft(self, sections, concepts, research) -> list[str]:
        payload = {"sections": sections, "concepts": concepts, "research": research}
        proc = subprocess.run(
            [str(self._python), "-c", _SCRIPT, self.method],
            input=json.dumps(payload).encode(), capture_output=True, timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-300:])
        return json.loads(proc.stdout.decode())


class SumyTextRank(_SumyDraft):
    name = "sumy-textrank-citepost"
    method = "textrank"


class SumyLsa(_SumyDraft):
    name = "sumy-lsa-citepost"
    method = "lsa"


CANDIDATES = [SumyTextRank, SumyLsa]
