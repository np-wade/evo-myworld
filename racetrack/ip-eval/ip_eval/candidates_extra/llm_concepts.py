"""Concepts-stage plugin pack: fastText unsupervised typing + OntoCast LLM extraction.

- `fasttext-classify` (corpus facebookresearch_fastText, code/python): fastText
  is a supervised text classifier / unsupervised embedding trainer; this stage
  has no labels, so the honest adaptation is the unsupervised path
  (`train_unsupervised(model='skipgram')`, cf. code/python/fasttext_module).
  A small skipgram model is trained ON THE PROVIDED SECTION TEXTS with fixed
  hyperparameters (dim=50, epoch=25, minCount=1, thread=1 -> deterministic;
  fasttext-wheel exposes no `seed` kwarg, verified empirically). Capitalized
  multiword terms are embedded (mean word vector) and typed by nearest-centroid
  cosine against embedded concept-type label phrases. High-salience terms
  (frequency >= 1, deduped, nested-suppressed) become the concept strings.
- `ontocast-concepts` (corpus growgraph_ontocast): minimal honest adaptation of
  ontocast's pipeline (code/ontocast tool/chunk/chunker.py -> LLM triple
  extraction -> tool/agg/entity_aligner.py): one batched LLM call per document
  extracts typed entities/triples in ontocast extractor style; entity alignment
  is done with normalized-string matching (substring/case folding) instead of
  sentence-transformers — documented simplification, no SPARQL store. Entities
  that do not literally appear in the source text are dropped (grounding).
  LLM: OpenAI-compatible endpoint https://ollama.com/v1, key from env
  OLLAMA_API_KEY (fallback ~/.config/ollama-cloud/api_key), model from env
  IP_EVAL_LLM_MODEL (default gpt-oss:20b). The key is never written to any
  file, log, or results record.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate, _run, provision_venv  # noqa: E402

LLM_BASE_URL = "https://ollama.com/v1"
LLM_TIMEOUT_S = 120
FASTTEXT_VENV = "fasttext"
FASTTEXT_TIMEOUT_S = 300

# Type vocabulary for this stage (mirrors the pack D-row typing: method /
# dataset / architecture / system component / metric / tool / theory ...).
CONCEPT_TYPES = [
    "Architecture", "System Component", "Method", "Dataset",
    "Metric", "Tool", "Theory",
]


# ---------------------------------------------------------------------------
# LLM helper (stdlib only; key never leaves memory)
# ---------------------------------------------------------------------------

def _llm_key() -> str | None:
    key = os.environ.get("OLLAMA_API_KEY")
    if key:
        return key.strip()
    try:
        return (Path.home() / ".config/ollama-cloud/api_key").read_text().strip()
    except Exception:
        return None


def _llm_model() -> str:
    return os.environ.get("IP_EVAL_LLM_MODEL", "gpt-oss:20b")


def _chat(messages: list[dict], max_tokens: int = 1200) -> str:
    """One chat call, one retry on transient failure. Returns content."""
    key = _llm_key()
    if not key:
        raise RuntimeError("no LLM key (OLLAMA_API_KEY unset, key file unreadable)")
    body = json.dumps({
        "model": _llm_model(),
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        # gpt-oss otherwise spends the entire completion budget on the
        # `reasoning` field and returns empty content (finish_reason=length)
        "reasoning_effort": "low",
    }).encode()
    last_exc: Exception | None = None
    for _attempt in range(2):  # one retry on transient failure
        req = urllib.request.Request(
            LLM_BASE_URL + "/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as resp:
                data = json.loads(resp.read())
            msg = data["choices"][0]["message"]
            # gpt-oss may also emit a separate `reasoning` field; the answer
            # contract is choices[0].message.content only.
            return msg.get("content") or ""
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code < 500 and exc.code not in (408, 429):
                break  # non-transient: do not retry
        except Exception as exc:  # timeout / connection reset -> transient
            last_exc = exc
    raise RuntimeError(f"LLM call failed: {type(last_exc).__name__}: {last_exc}")


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


_METRIC_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|ms|GB|MB|F1)\b")


def _metrics_near(name: str, text: str, limit: int = 4) -> str:
    """Metric tokens from sentences that mention the concept (verbatim only)."""
    found: list[str] = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if _norm(name) in _norm(sent):
            for m in _METRIC_RE.finditer(sent):
                if m.group(0) not in found:
                    found.append(m.group(0))
    return ", ".join(found[:limit])


def _sections_text(sections: list[dict]) -> list[str]:
    return [(f"{s.get('title', '')}\n{s.get('content', '')}").strip()
            for s in sections]


# ---------------------------------------------------------------------------
# fastText — unsupervised skipgram typing (no labels exist in this stage)
# ---------------------------------------------------------------------------

class FastTextClassify(Candidate):
    """facebookresearch_fastText — unsupervised skipgram + centroid typing.

    fastText's classification mode needs labels this stage does not provide,
    so the honest adaptation is `train_unsupervised` skipgram (see
    code/python/fasttext_module/FastText.py) trained on the race-provided
    section texts with fixed dim/epoch/thread=1 for determinism
    (fasttext-wheel has no `seed` kwarg — verified; documented deviation).
    Concept strings are high-salience capitalized terms; types are assigned
    by nearest-centroid cosine between the term embedding (mean word vector)
    and embeddings of the stage's concept-type label phrases.
    """
    name = "fasttext-classify"
    stages = {"concepts"}

    def __init__(self):
        self._python: Path | None = None

    def available(self) -> tuple[bool, str]:
        try:
            python, reason = provision_venv(FASTTEXT_VENV, ["fasttext-wheel"])
            if python is None:
                return False, f"fasttext-wheel install failed (purged): {reason}"
            probe = _run([str(python), "-c", "import fasttext"], timeout=60)
            if probe.returncode != 0:
                return False, f"fasttext import failed: {probe.stderr.decode()[-200:]}"
            self._python = python
            return True, ""
        except Exception as exc:  # available() must never raise
            return False, f"fasttext provisioning raised: {exc}"

    def concepts(self, sections: list[dict]) -> list[dict]:
        script = (
            "import sys, json, re, math, tempfile, os\n"
            "import fasttext\n"
            "texts = json.load(sys.stdin)\n"
            f"types = {CONCEPT_TYPES!r}\n"
            "corpus = '\\n'.join(t for t in texts if t)\n"
            "tmp = tempfile.mktemp(prefix='ft-corpus-')\n"
            "open(tmp, 'w').write(corpus.lower())\n"
            # fixed hyperparameters; thread=1 makes training deterministic
            "model = fasttext.train_unsupervised(input=tmp, model='skipgram',"
            " dim=50, epoch=25, minCount=1, thread=1, verbose=0)\n"
            "os.unlink(tmp)\n"
            "def vec(phrase):\n"
            "    ws = [w for w in re.findall(r\"[a-z0-9]+\", phrase.lower())]\n"
            "    vs = [model.get_word_vector(w) for w in ws if w in model.words]\n"
            "    if not vs:\n"
            "        return None\n"
            "    return [sum(v[i] for v in vs) / len(vs) for i in range(len(vs[0]))]\n"
            "def cos(a, b):\n"
            "    na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(x*x for x in b))\n"
            "    return sum(x*y for x, y in zip(a, b)) / (na * nb + 1e-9)\n"
            "centroids = {t: vec(t) for t in types}\n"
            # candidate terms: capitalized multiword phrases (sentence-initial
            # determiners stripped); salience = mention count in the corpus
            "phrase_re = re.compile(r\"\\b[A-Z][A-Za-z0-9]+(?:\\s+[A-Z][A-Za-z0-9]+){1,3}\\b\")\n"
            "found = {}\n"
            "for text in texts:\n"
            # per line: titles (single capitalized word) never match the
            # multiword regex, and phrases cannot span the title/body boundary
            "    for line in text.splitlines():\n"
            "        for m in phrase_re.finditer(line):\n"
            "            name = m.group(0)\n"
            "            for lead in ('The ', 'A ', 'An ', 'Its '):\n"
            "                if name.startswith(lead) and len(name) > len(lead) + 3:\n"
            "                    name = name[len(lead):]\n"
            "                    break\n"
            "            if len(name) < 4:\n"
            "                continue\n"
            "            found[name] = found.get(name, 0) + 1\n"
            # nested suppression: drop a term that is a strict sub-phrase of
            # another extracted term (keep the longest form)
            "names = sorted(found)\n"
            "kept = [n for n in names if not any(\n"
            "    n != m and re.search(r'\\b' + re.escape(n) + r'\\b', m) for m in names)]\n"
            "out = []\n"
            "for name in kept:\n"
            "    v = vec(name)\n"
            "    if v is None:\n"
            "        continue\n"
            "    best = max(types, key=lambda t: cos(v, centroids[t]) if centroids[t] else -1)\n"
            "    out.append({'name': name, 'type': best, 'mentions': found[name]})\n"
            "print(json.dumps(out))\n"
        )
        proc = _run([str(self._python), "-c", script],
                    stdin_data=json.dumps(_sections_text(sections)).encode(),
                    timeout=FASTTEXT_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(f"fasttext subprocess: {proc.stderr.decode()[-300:]}")
        concepts = json.loads(proc.stdout.decode())
        full_text = "\n".join(_sections_text(sections))
        for concept in concepts:
            metric = _metrics_near(concept["name"], full_text)
            if metric:
                concept["metric"] = metric
        return concepts


# ---------------------------------------------------------------------------
# OntoCast — LLM typed-entity/triple extraction + string-match alignment
# ---------------------------------------------------------------------------

class OntoCastLLMConcepts(Candidate):
    """growgraph_ontocast — chunk -> LLM triple extraction -> entity alignment.

    Follows ontocast's extractor approach (code/ontocast: chunker feeds chunks
    to an LLM triple extractor; tool/agg/entity_aligner.py then aligns
    entities across chunks). Simplifications, documented: all fixture sections
    are batched into ONE LLM call per document (fixtures are tiny); entity
    alignment uses normalized-string matching (case-fold + substring merge,
    longest form wins) instead of sentence-transformers; no SPARQL store.
    Entities not literally present in the source text are dropped (grounding).
    """
    name = "ontocast-concepts"
    stages = {"concepts"}

    def available(self) -> tuple[bool, str]:
        try:
            if not _llm_key():
                return False, ("no LLM credentials: OLLAMA_API_KEY unset and "
                               "~/.config/ollama-cloud/api_key unreadable")
            probe = _chat([{"role": "user", "content": "ping"}], max_tokens=8)
            if probe is None:  # empty content is fine; HTTP 200 authenticated
                return True, ""
            return True, ""
        except Exception as exc:  # available() must never raise
            return False, f"LLM endpoint probe failed: {exc}"

    def concepts(self, sections: list[dict]) -> list[dict]:
        texts = _sections_text(sections)
        full_text = "\n\n".join(texts)
        numbered = "\n\n".join(f"[S{i + 1}] {t}" for i, t in enumerate(texts))
        prompt = (
            "You are an ontology extraction engine in the style of OntoCast: "
            "read the numbered sections and extract the named entities and the "
            "triples that relate them.\n"
            f"Allowed entity types: {', '.join(CONCEPT_TYPES)}.\n"
            "Rules: use the exact surface form from the text for names; only "
            "extract salient multiword named entities (methods, systems, "
            "datasets, architectures, metrics); do not invent entities.\n"
            "Answer ONLY with JSON of the shape:\n"
            '{"entities": [{"name": ..., "type": ...}], '
            '"triples": [{"subject": ..., "predicate": ..., "object": ...}]}\n\n'
            f"SECTIONS:\n{numbered}"
        )
        raw = _chat([{"role": "user", "content": prompt}], max_tokens=4000)
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise RuntimeError(f"ontocast LLM returned non-JSON: {raw[:160]!r}")
        payload = json.loads(match.group(0))
        entities = payload.get("entities", [])

        # --- entity alignment: normalized-string matching ------------------
        # canonical = longest surface form per case-folded cluster; then
        # substring merge (nested suppression): "Evidence Graph" folds into
        # "Evidence Graph Transformer".
        by_key: dict[str, dict] = {}
        for ent in entities:
            name = str(ent.get("name", "")).strip()
            etype = str(ent.get("type", "")).strip()
            if not name:
                continue
            key = _norm(name)
            if key not in by_key or len(name) > len(by_key[key]["name"]):
                by_key[key] = {"name": name, "type": etype}
        aligned = list(by_key.values())
        kept = [a for a in aligned if not any(
            b is not a and re.search(r"\b" + re.escape(_norm(a["name"])) + r"\b",
                                     _norm(b["name"]))
            for b in aligned)]
        # --- grounding + mentions + verbatim metrics -----------------------
        source_norm = _norm(full_text)
        out = []
        for ent in kept:
            if _norm(ent["name"]) not in source_norm:
                continue  # hallucinated entity: drop, never emit
            mentions = len(re.findall(re.escape(_norm(ent["name"])), source_norm))
            record = {"name": ent["name"],
                      "type": ent["type"] if ent["type"] in CONCEPT_TYPES
                               else "Concept",
                      "mentions": mentions}
            metric = _metrics_near(ent["name"], full_text)
            if metric:
                record["metric"] = metric
            out.append(record)
        return out


CANDIDATES = [FastTextClassify, OntoCastLLMConcepts]
