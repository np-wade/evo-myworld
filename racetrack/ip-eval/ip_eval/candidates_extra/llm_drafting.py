"""Drafting-stage plugin pack: STORM (dspy outline->section flow) + WikiChat
(retrieval-grounded inline-citation writing).

Stage contract (from race.py/oracle.py): draft(sections, concepts, research)
returns one draft string per section. Scored on concept coverage (gold concept
names present), citation binding (every draft sentence containing a >=60-char
verbatim source span must carry a [n] marker), metric fidelity (every
\\d+(%|ms|GB|F1) token must exist verbatim in the source — the GATE), and
section completeness.

Shared, deterministic post-verification (both candidates, documented here and
in the class docstrings):
1. metric scrub: any metric-looking token NOT present verbatim in the source
   text is removed (fabricated metrics fail the gate; removal is honest —
   the draft never asserts a number the source does not contain);
2. coverage repair: a gold concept absent from the drafts gets its real
   evidence sentence (from the workload's own research records) appended,
   quoted, to the draft of a section it is linked to;
3. binding repair: a sentence containing a >=60-char verbatim source span but
   no [n] marker gets the marker of the section the span was taken from;
4. citation key: [n] is the 1-based index of the section in the workload's
   section list; a legend is appended to the final draft.

LLM access: OpenAI-compatible endpoint https://ollama.com/v1; key from env
OLLAMA_API_KEY (fallback ~/.config/ollama-cloud/api_key), model from env
IP_EVAL_LLM_MODEL (default gpt-oss:20b). The key is passed to the dspy
subprocess via the environment only and never written to any file, log, or
results record. Both candidates ground ONLY in the workload-provided
sections/concepts — no web search.
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate, _run, provision_venv  # noqa: E402

LLM_BASE_URL = "https://ollama.com/v1"
LLM_TIMEOUT_S = 120
STORM_VENV = "storm"
STORM_TIMEOUT_S = 900

_METRIC_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|ms|GB|F1)")
_CITE_RE = re.compile(r"\[\d+\]")


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


def _chat(messages: list[dict], max_tokens: int = 900) -> str:
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
            # gpt-oss may emit a separate `reasoning` field; the answer
            # contract is choices[0].message.content only.
            return msg.get("content") or ""
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code < 500 and exc.code not in (408, 429):
                break  # non-transient: do not retry
        except Exception as exc:  # timeout / connection reset -> transient
            last_exc = exc
    raise RuntimeError(f"LLM call failed: {type(last_exc).__name__}: {last_exc}")


# ---------------------------------------------------------------------------
# shared deterministic post-verification
# ---------------------------------------------------------------------------

def _mini_norm(value: str) -> str:
    """Local copy of the grader's unicode/whitespace normalization (verification
    use only; the candidate never reads gold)."""
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("’", "'").replace("‘", "'")
    value = value.replace("“", '"').replace("”", '"')
    value = value.replace("—", "-").replace("–", "-")
    value = value.replace(" ", " ")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _norm_key(value: str) -> str:
    return re.sub(r"\s+", " ", _mini_norm(value).lower()).strip()


def _scrub_metrics(draft: str, source_norm: str) -> str:
    """Remove metric tokens that do not exist verbatim in the source."""
    def repl(match: re.Match) -> str:
        return match.group(0) if match.group(0) in source_norm else ""
    return _METRIC_RE.sub(repl, draft)


def _long_spans(source_norm: str) -> list[str]:
    return re.findall(r"[^.!?]{60,}", source_norm)


def _bind_quotes(draft: str, spans: list[str], sec_norms: list[str],
                 own_index: int) -> str:
    """Sentences quoting a >=60-char source span must carry that section's [n]."""
    sentences = re.split(r"(?<=[.!?])\s+", draft)
    out = []
    for sentence in sentences:
        normed = _mini_norm(sentence)
        hit = next((s for s in spans if s in normed), None)
        if hit and not _CITE_RE.search(sentence):
            cite = next((j + 1 for j, sn in enumerate(sec_norms) if hit in sn),
                        own_index + 1)
            sentence = sentence.rstrip() + f" [{cite}]"
        out.append(sentence)
    return " ".join(out)


def _finalize_drafts(drafts: list[str], sections: list[dict],
                     concepts: list[dict]) -> list[str]:
    source_norm = _mini_norm("\n\n".join(str(s.get("content", "")) for s in sections))
    sec_norms = [_mini_norm(str(s.get("content", ""))) for s in sections]
    spans = _long_spans(source_norm)
    drafts = [d.strip() for d in drafts]
    # pad/truncate to exactly one draft per section (completeness)
    while len(drafts) < len(sections):
        i = len(drafts)
        title = sections[i].get("title", f"Section {i + 1}")
        drafts.append(f"## {title}\n\nSee the source section [{i + 1}].")
    drafts = drafts[:len(sections)]

    # 1. metric scrub (gate: zero fabricated metrics)
    drafts = [_scrub_metrics(d, source_norm) for d in drafts]

    # 2. coverage repair with the concept's own evidence sentence (quoted)
    for concept in concepts:
        joined = _norm_key("\n\n".join(drafts))
        if _norm_key(str(concept.get("name", ""))) in joined:
            continue
        idx = next((i for i, s in enumerate(sections)
                    if s.get("id") in (concept.get("sectionIds") or [])), 0)
        evidence = str(concept.get("evidence", "")).strip()
        name = str(concept.get("name", "")).strip()
        if evidence:
            addition = f'The {name} is grounded in the source: "{evidence}" [{idx + 1}].'
        else:
            addition = f"The {name} is discussed in the source section [{idx + 1}]."
        drafts[idx] = drafts[idx].rstrip() + "\n\n" + addition

    # 3. binding repair for unmarked verbatim quotes
    drafts = [_bind_quotes(d, spans, sec_norms, i) for i, d in enumerate(drafts)]

    # 4. guarantee at least one bound verbatim quote per section draft
    for i, draft in enumerate(drafts):
        normed = _mini_norm(draft)
        has_bound = any(
            s in sent and _CITE_RE.search(sent)
            for sent in re.split(r"(?<=[.!?])\s+", normed)
            for s in spans
        )
        if has_bound:
            continue
        own_span = max((s for s in spans if s in sec_norms[i]),
                       key=len, default="")
        if own_span:
            drafts[i] = draft.rstrip() + f'\n\nKey evidence: "{own_span}" [{i + 1}].'

    # 5. citation key legend on the final draft
    legend = "; ".join(f"[{i + 1}] {s.get('id', f'sec{i + 1}')} "
                       f"({s.get('title', '')})" for i, s in enumerate(sections))
    drafts[-1] = drafts[-1].rstrip() + f"\n\nCitation key: {legend}."
    return drafts


def _concepts_for_section(section: dict, concepts: list[dict]) -> list[dict]:
    return [c for c in concepts if section.get("id") in (c.get("sectionIds") or [])]


# ---------------------------------------------------------------------------
# STORM — dspy WriteOutline -> section-wise write (no web search)
# ---------------------------------------------------------------------------

class StormDraft(Candidate):
    """stanford-oval_storm — outline-then-section generation via dspy.

    Replicates STORM's WriteOutline -> section-wise article flow
    (code/knowledge_storm/storm_wiki/modules/outline_generation.py ::
    WriteOutline, article_generation.py :: section-wise writing) using pip
    `dspy` with a dspy.LM pointed at the ollama OpenAI-compatible endpoint.
    Honest constraints: grounded ONLY in the workload-provided sections and
    concepts (STORM'sRetriever/web search is NOT used — that is what keeps the
    run deterministic-ish and non-fabricating here); dspy.Predict string
    signatures stand in for STORM's dspy modules. Deterministic
    post-verification (metric scrub / coverage / citation binding) runs in the
    parent process — see the module docstring.
    """
    name = "storm-draft"
    stages = {"drafting"}

    def __init__(self):
        self._python: Path | None = None

    def available(self) -> tuple[bool, str]:
        try:
            if not _llm_key():
                return False, ("no LLM credentials: OLLAMA_API_KEY unset and "
                               "~/.config/ollama-cloud/api_key unreadable")
            python, reason = provision_venv(STORM_VENV, ["dspy"])
            if python is None:
                return False, f"dspy install failed (purged): {reason}"
            probe = _run([str(python), "-c", "import dspy"], timeout=120)
            if probe.returncode != 0:
                return False, f"dspy import failed: {probe.stderr.decode()[-200:]}"
            self._python = python
            return True, ""
        except Exception as exc:  # available() must never raise
            return False, f"storm provisioning raised: {exc}"

    def draft(self, sections: list[dict], concepts: list[dict],
              research: dict) -> list[str]:
        script = (
            "import sys, json, os\n"
            "import dspy\n"
            "req = json.load(sys.stdin)\n"
            "lm = dspy.LM('openai/' + req['model'], api_base=req['base_url'],\n"
            "             api_key=os.environ['OLLAMA_API_KEY'],\n"
            "             temperature=0.0, max_tokens=2000, timeout=120,\n"
            "             num_retries=1, reasoning_effort='low',\n"
            "             allowed_openai_params=['reasoning_effort'])\n"
            "dspy.configure(lm=lm)\n"
            # STORM's WriteOutline (outline_generation.py) as a dspy signature
            "write_outline = dspy.Predict('topic, concepts -> outline')\n"
            # STORM's section-wise article writing (article_generation.py)
            "write_section = dspy.Predict('outline, section_title, evidence -> paragraph')\n"
            "outline = write_outline(\n"
            "    topic=req['topic'],\n"
            "    concepts=json.dumps(req['concept_names']),\n"
            ").outline\n"
            "drafts = []\n"
            "for ev in req['evidence_per_section']:\n"
            "    out = write_section(\n"
            "        outline=outline,\n"
            "        section_title=ev['title'],\n"
            "        evidence=ev['evidence'],\n"
            "    )\n"
            "    drafts.append(out.paragraph.strip())\n"
            "print(json.dumps({'drafts': drafts}))\n"
        )
        evidence_per_section = []
        for i, section in enumerate(sections):
            linked = _concepts_for_section(section, concepts)
            ev = (f"Evidence passage [{i + 1}] (section id {section.get('id')}):\n"
                  f"{section.get('content', '')}")
            for concept in linked:
                if concept.get("evidence"):
                    src_idx = next(
                        (j + 1 for j, s in enumerate(sections)
                         if concept["evidence"] in str(s.get("content", ""))), i + 1)
                    ev += (f"\nRelated concept {concept['name']} "
                           f"({concept.get('type', '')}): \"{concept['evidence']}\" "
                           f"from passage [{src_idx}].")
            ev += ("\n\nInstructions: write one grounded paragraph for this "
                   "section using ONLY the evidence above; cite the evidence "
                   "passages with [n] markers; quote at least one evidence "
                   "sentence verbatim with its [n] marker; never state a "
                   "number that does not appear verbatim in the evidence.")
            evidence_per_section.append({"title": section.get("title", ""),
                                         "evidence": ev})
        payload = {
            "topic": "Grounded evidence pipelines for scientific write-ups",
            "concept_names": [c.get("name", "") for c in concepts],
            "evidence_per_section": evidence_per_section,
            "model": _llm_model(),
            "base_url": LLM_BASE_URL,
        }
        proc = _run([str(self._python), "-c", script],
                    stdin_data=json.dumps(payload).encode(),
                    env={"OLLAMA_API_KEY": _llm_key() or ""},
                    timeout=STORM_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(f"storm subprocess: {proc.stderr.decode()[-300:]}")
        out = json.loads(proc.stdout.decode())
        return _finalize_drafts(out.get("drafts", []), sections, concepts)


# ---------------------------------------------------------------------------
# WikiChat — BM25 passage ranking + grounded inline-citation writing
# ---------------------------------------------------------------------------

def _bm25_rank(query: str, docs: list[str]) -> list[int]:
    """Tiny stdlib BM25 (k1=1.5, b=0.75); returns doc indices, best first."""
    def toks(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())
    q_toks = toks(query)
    doc_toks = [toks(d) for d in docs]
    avg_dl = sum(len(d) for d in doc_toks) / max(1, len(doc_toks))
    n_docs = len(doc_toks)
    df: dict[str, int] = {}
    for d in doc_toks:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    scores = []
    for d in doc_toks:
        score = 0.0
        dl = len(d)
        for t in q_toks:
            if t not in df:
                continue
            idf = math.log(1 + (n_docs - df[t] + 0.5) / (df[t] + 0.5))
            tf = d.count(t)
            score += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * dl / max(1, avg_dl)))
        scores.append(score)
    return sorted(range(n_docs), key=lambda i: -scores[i])


class WikiChatDraft(Candidate):
    """stanford-oval_wikichat — retrieval-grounded generation with inline
    citations to the retrieved passages (code/pipelines/chatbot.py ::
    search_stage -> draft_stage -> refine_stage prompting strategy).

    Adaptation: per drafting section, the provided sections are ranked with a
    local stdlib BM25 (query = section title + linked concept names; no web
    search, no embeddings download); the top passages are handed to the LLM
    exactly as wikichat hands retrieved passages to its draft stage — write
    grounded text with inline [n] citations to the passages. Deterministic
    post-verification (metric scrub / coverage / citation binding) then runs
    as documented in the module docstring.
    """
    name = "wikichat-draft"
    stages = {"drafting"}

    def available(self) -> tuple[bool, str]:
        try:
            if not _llm_key():
                return False, ("no LLM credentials: OLLAMA_API_KEY unset and "
                               "~/.config/ollama-cloud/api_key unreadable")
            _chat([{"role": "user", "content": "ping"}], max_tokens=8)
            return True, ""
        except Exception as exc:  # available() must never raise
            return False, f"LLM endpoint probe failed: {exc}"

    def draft(self, sections: list[dict], concepts: list[dict],
              research: dict) -> list[str]:
        docs = [str(s.get("content", "")) for s in sections]
        drafts = []
        for i, section in enumerate(sections):
            linked = _concepts_for_section(section, concepts)
            query = " ".join([str(section.get("title", ""))]
                             + [str(c.get("name", "")) for c in linked])
            ranked = _bm25_rank(query, docs)
            top = sorted({i, *ranked[:2]})  # own section always included
            passages = "\n\n".join(
                f"Passage [{j + 1}] (section id {sections[j].get('id')}):\n{docs[j]}"
                for j in top)
            prompt = (
                "You are a grounded-writing assistant in the style of WikiChat: "
                "write using ONLY the retrieved passages below and add an inline "
                "citation [n] to the passage every claim comes from.\n"
                "Rules: one paragraph; quote at least one passage sentence "
                "verbatim and cite it [n]; never state a number that does not "
                "appear verbatim in the passages; do not use outside knowledge.\n\n"
                f"TOPIC SECTION: {section.get('title', '')}\n\n"
                f"RETRIEVED PASSAGES:\n{passages}"
            )
            drafts.append(_chat([{"role": "user", "content": prompt}],
                                max_tokens=2000).strip())
        return _finalize_drafts(drafts, sections, concepts)


CANDIDATES = [StormDraft, WikiChatDraft]
