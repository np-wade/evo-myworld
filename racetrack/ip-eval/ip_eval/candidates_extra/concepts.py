"""Concepts-stage plugin: presidio NER, spacy noun chunks, fasttext.

- `presidio` and `spacy-nounchunks` share one venv (.venv-candidates/concepts)
  with presidio-analyzer + spacy + en_core_web_sm; both run as venv
  subprocesses with JSON in/out.
- `fasttext` is a text classifier, not an extractor: we try the install
  (fasttext-wheel) but record the candidate unavailable — there is no honest
  concept-extraction adapter for it.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..candidates import VENVS, Candidate, _run, provision_venv

CONCEPTS_VENV = "concepts"
FASTTEXT_VENV = "fasttext"
HEAVY_TIMEOUT_S = 300


def _concepts_python() -> tuple[Path | None, str]:
    """Provision the shared spacy/presidio venv incl. en_core_web_sm."""
    python, reason = provision_venv(CONCEPTS_VENV, ["presidio-analyzer", "spacy"])
    if python is None:
        return None, reason
    probe = _run([str(python), "-c", "import en_core_web_sm"], timeout=60)
    if probe.returncode == 0:
        return python, ""
    # spacy delegates to `uv pip install` when uv is present; uv needs
    # VIRTUAL_ENV pointed at our venv or it refuses with "no venv found".
    download = _run(
        [str(python), "-m", "spacy", "download", "en_core_web_sm"],
        timeout=900,
        env={"VIRTUAL_ENV": str(python.parent.parent)},
    )
    if download.returncode != 0:
        shutil.rmtree(VENVS / CONCEPTS_VENV, ignore_errors=True)  # disk is tight
        return None, f"en_core_web_sm download failed (purged): {download.stderr.decode()[-300:]}"
    return python, ""


def _sections_text(sections: list[dict]) -> list[str]:
    return [
        (f"{s.get('title', '')}\n{s.get('content', '')}").strip()
        for s in sections
    ]


class PresidioConcepts(Candidate):
    """presidio-analyzer NER entities as concepts.

    Presidio finds PII-style entities (PERSON, ORGANIZATION, LOCATION, ...),
    not scientific concepts; entity types are reported as-is, so a type
    mismatch against the gold ontology is an expected, legitimate outcome.
    """
    name = "presidio"
    stages = {"concepts"}

    def __init__(self):
        self._python: Path | None = None

    def available(self) -> tuple[bool, str]:
        self._python, reason = _concepts_python()
        return (self._python is not None), reason

    def concepts(self, sections: list[dict]) -> list[dict]:
        script = (
            "import sys, json\n"
            "from presidio_analyzer import AnalyzerEngine\n"
            "from presidio_analyzer.nlp_engine import NlpEngineProvider\n"
            "texts = json.load(sys.stdin)\n"
            # presidio's default engine wants en_core_web_lg (~500MB); pin the
            # already-installed en_core_web_sm instead.
            "provider = NlpEngineProvider(nlp_configuration={\n"
            "    'nlp_engine_name': 'spacy',\n"
            "    'models': [{'lang_code': 'en', 'model_name': 'en_core_web_sm'}],\n"
            "})\n"
            "analyzer = AnalyzerEngine(nlp_engine=provider.create_engine())\n"
            "found = {}\n"
            "for text in texts:\n"
            "    if not text:\n"
            "        continue\n"
            "    for ent in analyzer.analyze(text=text, language='en'):\n"
            "        name = text[ent.start:ent.end].strip()\n"
            "        if not name:\n"
            "            continue\n"
            "        key = (name, ent.entity_type)\n"
            "        found[key] = found.get(key, 0) + 1\n"
            "print(json.dumps([\n"
            "    {'name': name, 'type': etype, 'mentions': n}\n"
            "    for (name, etype), n in sorted(found.items())\n"
            "]))\n"
        )
        proc = _run([str(self._python), "-c", script],
                    stdin_data=json.dumps(_sections_text(sections)).encode(),
                    timeout=HEAVY_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-300:])
        return json.loads(proc.stdout.decode())


class SpacyNounChunks(Candidate):
    """en_core_web_sm noun_chunks as a statistical phrase extractor.

    Each noun-chunk span (leading determiners stripped) becomes a concept of
    type 'Concept', deduped with a mention count.
    """
    name = "spacy-nounchunks"
    stages = {"concepts"}

    def __init__(self):
        self._python: Path | None = None

    def available(self) -> tuple[bool, str]:
        self._python, reason = _concepts_python()
        return (self._python is not None), reason

    def concepts(self, sections: list[dict]) -> list[dict]:
        script = (
            "import sys, json\n"
            "import spacy\n"
            "texts = json.load(sys.stdin)\n"
            "nlp = spacy.load('en_core_web_sm')\n"
            "found = {}\n"
            "for text in texts:\n"
            "    if not text:\n"
            "        continue\n"
            "    for chunk in nlp(text).noun_chunks:\n"
            "        name = chunk.text.strip()\n"
            "        for det in ('The ', 'the ', 'A ', 'a ', 'An ', 'an '):\n"
            "            if name.startswith(det):\n"
            "                name = name[len(det):].strip()\n"
            "                break\n"
            "        if len(name) < 3 or not any(c.isalpha() for c in name):\n"
            "            continue\n"
            "        found[name] = found.get(name, 0) + 1\n"
            "print(json.dumps([\n"
            "    {'name': name, 'type': 'Concept', 'mentions': n}\n"
            "    for name, n in sorted(found.items())\n"
            "]))\n"
        )
        proc = _run([str(self._python), "-c", script],
                    stdin_data=json.dumps(_sections_text(sections)).encode(),
                    timeout=HEAVY_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-300:])
        return json.loads(proc.stdout.decode())


class FastTextConcepts(Candidate):
    """fastText — a text classifier, not a concept extractor.

    We attempt the install (fasttext-wheel) but there is no honest way to
    adapt a supervised classifier / embedding trainer into concept
    extraction, so this candidate always reports unavailable with the real
    reason rather than faking an extraction stage.
    """
    name = "fasttext"
    stages = {"concepts"}

    def available(self) -> tuple[bool, str]:
        python, reason = provision_venv(FASTTEXT_VENV, ["fasttext-wheel"])
        if python is None:
            return False, f"fasttext-wheel install failed (purged): {reason}"
        return False, (
            "fasttext-wheel installs fine, but fastText is a supervised text "
            "classifier / embedding trainer with no extraction capability; no "
            "honest concept-extraction adapter exists"
        )


CANDIDATES = [PresidioConcepts, SpacyNounChunks, FastTextConcepts]
