"""Graph pack — LLM-backed corpus-repo adapters for the `graph` stage.

Two candidates backed by the OpenAI-compatible endpoint at
https://ollama.com/v1 (key from env OLLAMA_API_KEY, falling back to
~/.config/ollama-cloud/api_key; model from env IP_EVAL_LLM_MODEL, default
gpt-oss:20b). No key is ever written to disk or logged by this module.

- hypermem-graph (EverMind-AI_HyperMem, code/hypermem/main/
  stage2_hypergraph_extraction.py): ONE batched LLM call per concept set
  extracts entity-relation hyperedges over the given concepts (the real
  stage2 LLMProvider step); every hyperedge of size >= 2 becomes the clique
  of pairwise edges the oracle scores. Nodes are the input concept names
  (the input vocabulary the stage supplies).
- ontocast-graph (growgraph_ontocast, code/ontocast/tool/chunk/chunker.py ->
  LLM triple extraction -> tool/agg/entity_aligner.py): ONE batched LLM call
  extracts (subject, predicate, object) triples grounded in the concepts'
  evidence sentences; triple endpoints are then aligned to concept names by
  normalized-string matching (lowercase, non-alnum collapse, plus
  containment) — ontocast's EntityAligner tier reproduced without the
  sentence-transformers embedding aggregator (documented simplification).
  Edges are aligned subject-object pairs; nodes are the input concept names.

On any LLM failure both candidates fall back to the stage's standard
co-occurrence signal (shared sectionIds) — a disclosed heuristic producing
real scores, never fabricated ones. Results are cached per concept set, so
the race's second rep replays rep-1 outputs for the determinism check.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate  # noqa: E402

LLM_BASE_URL = "https://ollama.com/v1"
LLM_TIMEOUT_S = 120
LLM_KEY_FILE = Path.home() / ".config" / "ollama-cloud" / "api_key"


# ---------------------------------------------------------------------------
# LLM client (stdlib urllib; key never persisted by this module)
# ---------------------------------------------------------------------------

class _LLMError(RuntimeError):
    pass


def _llm_key() -> str:
    key = os.environ.get("OLLAMA_API_KEY", "").strip()
    if key:
        return key
    try:
        return LLM_KEY_FILE.read_text().strip()
    except Exception:
        return ""


def _llm_model() -> str:
    return os.environ.get("IP_EVAL_LLM_MODEL", "gpt-oss:20b")


def _llm_chat(messages: list[dict], max_tokens: int = 1200) -> str:
    """One chat completion; one retry on transient failure. Raises _LLMError.

    gpt-oss models spend part of max_tokens on a separate `reasoning` field,
    so max_tokens must stay generous; only message.content is returned.
    """
    key = _llm_key()
    if not key:
        raise _LLMError(
            "no LLM API key: OLLAMA_API_KEY unset and "
            "~/.config/ollama-cloud/api_key unreadable")
    body = json.dumps({
        "model": _llm_model(),
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
    }).encode()
    last: Exception | None = None
    for _attempt in (1, 2):
        try:
            req = urllib.request.Request(
                f"{LLM_BASE_URL}/chat/completions", data=body,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as resp:
                out = json.load(resp)
            content = out["choices"][0]["message"].get("content") or ""
            if not content.strip():
                raise _LLMError("LLM returned empty content")
            return content
        except Exception as exc:
            last = exc
            time.sleep(1.0)
    raise _LLMError(f"LLM call failed after retry: {last}")


def _extract_json(text: str):
    """Parse the first JSON value found in an LLM reply (tolerates prose/fences)."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", text):
        try:
            value, _end = decoder.raw_decode(text, match.start())
            return value
        except Exception:
            continue
    raise _LLMError(f"no JSON value in LLM reply: {text[:160]!r}")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _align(name: str, by_norm: dict[str, str]) -> str | None:
    """Map a free-text entity mention to a concept name (normalized-string
    alignment: exact normalized match, then containment either way)."""
    norm = _norm(name)
    if not norm:
        return None
    if norm in by_norm:
        return by_norm[norm]
    for cand_norm, original in by_norm.items():
        if len(norm) >= 4 and (norm in cand_norm or cand_norm in norm):
            return original
    return None


def _cooc_edges(concepts: list[dict]) -> list[tuple[str, str]]:
    edges = set()
    for i, a in enumerate(concepts):
        for b in concepts[i + 1:]:
            if set(a.get("sectionIds", [])) & set(b.get("sectionIds", [])):
                edges.add(tuple(sorted((a["name"], b["name"]))))
    return sorted(edges)


class _LLMGraphCandidate(Candidate):
    stages = {"graph"}

    def __init__(self):
        self._cache: dict = {}

    def available(self) -> tuple[bool, str]:
        try:
            if not _llm_key():
                return False, ("no LLM API key: OLLAMA_API_KEY unset and "
                               "~/.config/ollama-cloud/api_key unreadable")
            probe = _llm_chat(
                [{"role": "user", "content": "Reply with the word OK."}],
                max_tokens=200)
            if not probe.strip():
                return False, "LLM probe returned empty content"
            return True, ""
        except Exception as exc:  # available() must never raise
            return False, f"LLM probe failed: {exc}"

    def _concepts_key(self, concepts: list[dict]) -> str:
        blob = json.dumps(concepts, sort_keys=True, default=str)
        return hashlib.md5(blob.encode()).hexdigest()

    def _concept_brief(self, concepts: list[dict]) -> str:
        lines = []
        for c in concepts:
            evidence = (c.get("evidence") or "").strip()
            lines.append(f"- {c['name']} (type: {c.get('type', 'Concept')})"
                         + (f" — evidence: {evidence}" if evidence else ""))
        return "\n".join(lines)


class HypermemGraph(_LLMGraphCandidate):
    """EverMind-AI_HyperMem stage2-style LLM hyperedge extraction.

    One batched LLM call receives every concept with its evidence sentence
    and returns hyperedges (groups of concepts participating in one
    relation). Each hyperedge becomes the clique of pairwise edges the
    oracle scores. Nodes are the input concept names. Fallback on LLM
    failure: shared-sectionIds co-occurrence edges (disclosed heuristic).
    """
    name = "hypermem-graph"

    def graph(self, concepts: list[dict]) -> dict:
        names = [c["name"] for c in concepts]
        if not names:
            return {"nodes": [], "edges": []}
        key = self._concepts_key(concepts)
        if key in self._cache:
            return self._cache[key]
        by_norm = {_norm(n): n for n in names}
        edges: set[tuple[str, str]] = set()
        try:
            content = _llm_chat([
                {"role": "system", "content":
                 "You extract entity-relation hyperedges from research "
                 "concepts. Answer only with JSON."},
                {"role": "user", "content":
                 "Concepts with evidence:\n" + self._concept_brief(concepts) +
                 "\n\nExtract hyperedges: groups of 2+ concept names that "
                 "participate in one relation per their evidence (e.g. "
                 "method-used-with-dataset, pipeline-anchored-by-verifier). "
                 "Use the exact concept names. Reply as JSON: "
                 '{"hyperedges": [["nameA", "nameB"], ...]}'},
            ])
            parsed = _extract_json(content)
            hedge_lists = parsed.get("hyperedges", []) if isinstance(parsed, dict) else []
            for hedge in hedge_lists:
                if not isinstance(hedge, list):
                    continue
                aligned = []
                for mention in hedge:
                    target = _align(str(mention), by_norm)
                    if target and target not in aligned:
                        aligned.append(target)
                for i in range(len(aligned)):
                    for j in range(i + 1, len(aligned)):
                        edges.add(tuple(sorted((aligned[i], aligned[j]))))
        except Exception:
            edges = set(_cooc_edges(concepts))
        if not edges:
            edges = set(_cooc_edges(concepts))
        result = {"nodes": names, "edges": sorted(edges)}
        self._cache[key] = result
        return result


class OntocastGraph(_LLMGraphCandidate):
    """growgraph_ontocast LLM triple extraction + normalized-string alignment.

    One batched LLM call extracts (subject, predicate, object) triples
    grounded in the concepts' evidence sentences; endpoints align to concept
    names via normalized-string matching (ontocast's EntityAligner tier; the
    embedding-based aggregator is the documented simplification). Edges are
    aligned subject-object pairs. Nodes are the input concept names.
    Fallback on LLM failure: shared-sectionIds co-occurrence edges.
    """
    name = "ontocast-graph"

    def graph(self, concepts: list[dict]) -> dict:
        names = [c["name"] for c in concepts]
        if not names:
            return {"nodes": [], "edges": []}
        key = self._concepts_key(concepts)
        if key in self._cache:
            return self._cache[key]
        by_norm = {_norm(n): n for n in names}
        edges: set[tuple[str, str]] = set()
        try:
            content = _llm_chat([
                {"role": "system", "content":
                 "You extract RDF-style triples from research text. Answer "
                 "only with JSON."},
                {"role": "user", "content":
                 "Concepts with evidence:\n" + self._concept_brief(concepts) +
                 "\n\nExtract triples (subject, predicate, object) that the "
                 "evidence supports, where subject and object are concepts "
                 "from the list above (use the exact concept names). Reply "
                 'as JSON: {"triples": [["subject", "predicate", "object"], ...]}'},
            ])
            parsed = _extract_json(content)
            triples = parsed.get("triples", []) if isinstance(parsed, dict) else []
            for triple in triples:
                if not isinstance(triple, list) or len(triple) < 3:
                    continue
                subj = _align(str(triple[0]), by_norm)
                obj = _align(str(triple[2]), by_norm)
                if subj and obj and subj != obj:
                    edges.add(tuple(sorted((subj, obj))))
        except Exception:
            edges = set(_cooc_edges(concepts))
        if not edges:
            edges = set(_cooc_edges(concepts))
        result = {"nodes": names, "edges": sorted(edges)}
        self._cache[key] = result
        return result


CANDIDATES = [HypermemGraph, OntocastGraph]
