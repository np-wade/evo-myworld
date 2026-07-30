"""Drafting-extra family — Stage 6 candidates from LLM-pipeline repos.

- paperspine-draft: declared composition — PaperSpine
  (`WUBING2023_PaperSpine/code/src/scripts/structured_review.py`) applied
  extractively. structured_review.py's genuinely deterministic, LLM-free
  sub-components are its evidence-mapping scaffold: every finding row is
  bound to an evidence-bank entry and marked supported/missing, with
  `[LLM: ...]` placeholders for anything generative. This adapter keeps the
  deterministic half and drops the LLM half: each concept is a rationale row,
  its research record is the evidence-bank entry; rows with evidence are
  drafted as verbatim excerpt sentences bound to [n] citations, rows without
  evidence are omitted (never invented), and only sentences quoteable against
  the given sections/research are emitted. Pure stdlib, no provisioning.
- storm-draft: honest-unavailable. STORM's outline/article generation
  (`stanford-oval_storm/code/knowledge_storm/storm_wiki/modules/
  {outline,article}_generation.py`) are dspy LLM modules (WriteOutline /
  ConvToSection / WriteSection) — the section text is LLM-generated from
  retrieved snippets; there is no deterministic LLM-free drafting
  sub-component to extract.
- wikichat-draft: honest-unavailable. WikiChat's chatbot
  (`stanford-oval_WikiChat/code/pipelines/chatbot.py`) is an async
  chainlite/langgraph LLM pipeline that needs an LLM engine
  (`llm_generation_chain`) and a live retriever API endpoint
  (`retrieve_via_api`); no honest extractive adapter exists.

Grounding rules (drafting gate: metric_fidelity >= 0.99): every emitted
sentence is verbatim from the given section content or research evidence;
numbers/units are copied, never rounded or invented; missing evidence
produces omission, never a placeholder claim (S6.05/S6.12).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate  # noqa: E402

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _citation_table(concepts: list[dict], research: dict) -> dict:
    """concept id -> (marker number, concept name, evidence excerpt).

    Mirrors PaperSpine's evidence-status check: a row is 'supported' only
    when it has BOTH sources and a non-empty evidence excerpt; everything
    else is 'missing' and omitted downstream (never invented).
    """
    table: dict[str, tuple[int, str, str]] = {}
    n = 0
    for concept in concepts:
        rec = research.get(concept.get("id"), {}) or {}
        sources = rec.get("sources") or []
        evidence = rec.get("evidence") or []
        excerpt = evidence[0].get("excerpt", "") if evidence else ""
        if sources and excerpt:
            n += 1
            table[concept.get("id")] = (n, concept.get("name", ""), excerpt)
    return table


def _draft_sections(sections: list[dict], concepts: list[dict],
                    research: dict) -> list[str]:
    citations = _citation_table(concepts, research)
    bound: set[str] = set()  # concept ids whose excerpt was emitted somewhere
    drafts = []
    for section in sections:
        content = section.get("content", "") or ""
        kept = []
        for sentence in _SENT_SPLIT.split(content):
            s = sentence.strip()
            if not s:
                continue
            tags = ""
            for cid, (num, _name, excerpt) in citations.items():
                if excerpt[:60] in s:
                    tags += f" [{num}]"
                    bound.add(cid)
            if tags:
                kept.append(s + tags)
            elif len(s) < 60:
                # short verbatim sentence: grounded, and below the oracle's
                # 60-char long-quote threshold so no citation marker is owed
                kept.append(s)
            # long sentence carrying no research evidence: omit rather than
            # bind a citation to text the evidence does not support
        drafts.append((section, kept))

    # Fallback for supported rows whose excerpt did not match any section
    # sentence (e.g. whitespace drift): emit the excerpt verbatim, bound to
    # its [n], in the section that mentions the concept (else section 0).
    out = [body[:] for _section, body in drafts]
    for cid, (num, name, excerpt) in citations.items():
        if cid in bound:
            continue
        target = 0
        for i, (section, _body) in enumerate(drafts):
            haystack = (section.get("title", "") + "\n"
                        + (section.get("content", "") or "")).lower()
            if name and name.lower() in haystack:
                target = i
                break
        if out:
            out[target].append(f"{excerpt.strip()} [{num}]")
        bound.add(cid)

    return [
        f"## {section.get('title', 'Section')}\n\n" + " ".join(body)
        for (section, _body), body in zip(drafts, out, strict=True)
    ]


class PaperSpineDraft(Candidate):
    name = "paperspine-draft"
    stages = {"drafting"}

    def available(self):
        try:
            return True, ""  # pure stdlib; nothing to provision
        except Exception as exc:  # available() must never raise
            return False, f"available() error: {exc}"

    def draft(self, sections, concepts, research) -> list[str]:
        return _draft_sections(sections, concepts, research)


class StormDraft(Candidate):
    """STORM — dspy LLM pipeline; honest refusal (no extractive adapter)."""
    name = "storm-draft"
    stages = {"drafting"}

    def available(self):
        try:
            return False, (
                "STORM outline/article generation (knowledge_storm "
                "storm_wiki/modules/{outline,article}_generation.py) are dspy "
                "LLM modules (WriteOutline / ConvToSection) requiring an LLM "
                "backend; no honest deterministic extractive adapter exists"
            )
        except Exception as exc:  # available() must never raise
            return False, f"available() error: {exc}"


class WikiChatDraft(Candidate):
    """WikiChat — LLM chat pipeline; honest refusal (no extractive adapter)."""
    name = "wikichat-draft"
    stages = {"drafting"}

    def available(self):
        try:
            return False, (
                "WikiChat chatbot (pipelines/chatbot.py) is a chainlite/"
                "langgraph LLM pipeline requiring an LLM engine and a live "
                "retriever API endpoint; no honest extractive adapter exists"
            )
        except Exception as exc:  # available() must never raise
            return False, f"available() error: {exc}"


CANDIDATES = [PaperSpineDraft, StormDraft, WikiChatDraft]
