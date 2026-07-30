"""Concepts-stage plugin pack 03: ontocast, opennlp, nemo-gliner, wittgenstein.

- `ontocast-concepts` (corpus growgraph_ontocast): OntoCast's extraction path
  is LLM+SPARQL driven — tool/chunk/chunker.py feeds chunks to an LLM triple
  extractor and tool/agg/entity_aligner.py aligns the resulting RDF graphs
  with a sentence-transformer embedding model. No LLM endpoint and no
  model-weight downloads on this box -> honest unavailable (FastTextConcepts
  idiom), never a regex stand-in.
- `opennlp-ner` (corpus apache_opennlp): Java/Maven project; java-gated
  honest refusal, no maven builds attempted.
- `nemo-gliner` (corpus NVIDIA-NeMo_Guardrails): NeMo's library/gliner
  (actions.py/request.py) posts to a GLiNER HTTP server endpoint; the honest
  local adaptation is the standalone `gliner` pip package (same model family,
  nvidia/gliner-pii) run in a minimal venv — NOT the full nemoguardrails
  stack. Weights download from HF at first use; if that fails the venv is
  purged and the candidate reports unavailable with the true reason.
- `wittgenstein-rules` (corpus imoscovitz_wittgenstein): RIPPER
  (ripper.py / abstract_ruleset_classifier.py) is a supervised rule
  classifier needing labeled training data; the concepts stage supplies
  unlabeled sections, so no honest concept-extraction adaptation exists.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate, _run, provision_venv  # noqa: E402

GLINER_VENV = "gliner"
GLINER_MODEL = "nvidia/gliner-pii"
HEAVY_TIMEOUT_S = 300
WEIGHTS_TIMEOUT_S = 900

# Ontology labels from the pack D-rows (S3.01/S3.07): entity/concept recall
# and method/dataset/metric/tool/theory/person/org/material/location typing.
GLINER_LABELS = [
    "person", "organization", "location", "method", "dataset", "model",
    "metric", "tool", "theory", "material", "variable", "process",
]

_LLM_ENDPOINT_ENVS = (
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY", "ONTOCAST_LLM_MODEL", "LLM_MODEL",
)


def _sections_text(sections: list[dict]) -> list[str]:
    return [
        (f"{s.get('title', '')}\n{s.get('content', '')}").strip()
        for s in sections
    ]


class OntoCastConcepts(Candidate):
    """growgraph_ontocast — LLM/SPARQL-driven ontology extraction.

    OntoCast (code/ontocast/tool/chunk/chunker.py -> LLM triple extraction ->
    tool/agg/entity_aligner.py RDF alignment) cannot extract concepts without
    an LLM endpoint and embedding-model weights, neither of which is
    provisionable on this box. Honest unavailable; no regex substitute.
    """
    name = "ontocast-concepts"
    stages = {"concepts"}

    def available(self) -> tuple[bool, str]:
        try:
            endpoint = next(
                (e for e in _LLM_ENDPOINT_ENVS if os.environ.get(e)), None
            )
            if endpoint:
                return False, (
                    f"LLM endpoint env {endpoint} is set, but OntoCast's "
                    "extraction path (tool/chunk/chunker.py -> LLM triple "
                    "extraction -> tool/agg/entity_aligner.py embedding-based "
                    "RDF alignment) also needs sentence-transformer weights "
                    "and outbound LLM calls; network/model-weight downloads "
                    "are not permitted in this lane, so no deterministic "
                    "local run is possible"
                )
            return False, (
                "ontocast concept extraction is LLM+SPARQL driven "
                "(tool/chunk/chunker.py feeds an LLM triple extractor; "
                "tool/agg/entity_aligner.py aligns RDF graphs with an "
                "embedding model); no LLM endpoint configured on this box "
                "and model-weight downloads are disallowed"
            )
        except Exception as exc:  # available() must never raise
            return False, f"available() check failed: {exc}"


class OpenNlpNer(Candidate):
    """apache_opennlp — Java/Maven NER (opennlp-runtime namefind).

    Java-gated honest refusal: maven builds are not attempted in this lane,
    so without a JDK on PATH (and with no prebuilt jars) there is no way to
    run OpenNLP's name finder here.
    """
    name = "opennlp-ner"
    stages = {"concepts"}

    def available(self) -> tuple[bool, str]:
        try:
            if shutil.which("java") is None:
                return False, (
                    "java not on PATH; apache_opennlp is a Java/Maven "
                    "project and maven builds are not attempted in this lane"
                )
            return False, (
                "java is present but OpenNLP jars are not built; maven "
                "builds are not attempted in this lane, so the namefind "
                "models cannot run"
            )
        except Exception as exc:  # available() must never raise
            return False, f"available() check failed: {exc}"


class NeMoGliner(Candidate):
    """NVIDIA-NeMo_Guardrails GLiNER — via the standalone `gliner` package.

    NeMo's library/gliner/{actions,request}.py call a GLiNER HTTP server;
    the honest local adaptation is the same model (nvidia/gliner-pii) loaded
    through the `gliner` pip package in a minimal venv. Predicted entity
    labels are reported as concept types as-is.
    """
    name = "nemo-gliner"
    stages = {"concepts"}

    def __init__(self):
        self._python: Path | None = None

    def available(self) -> tuple[bool, str]:
        try:
            python, reason = provision_venv(GLINER_VENV, ["gliner"])
            if python is None:
                return False, f"gliner install failed (purged): {reason}"
            # Fast path: weights already in the local HF cache load offline
            # (avoids HF hub metadata calls entirely on re-races).
            try:
                cached = _run(
                    [str(python), "-c",
                     f"from gliner import GLiNER; GLiNER.from_pretrained({GLINER_MODEL!r})"],
                    timeout=120, env={"HF_HUB_OFFLINE": "1"},
                )
                if cached.returncode == 0:
                    self._python = python
                    return True, ""
            except Exception:
                pass  # fall through to the online download probe
            # GLiNER weights download from HF at first use; probe honestly.
            # A TimeoutExpired here must NEVER escape available() (it crashed
            # the race in run5): report unavailable with the true reason.
            try:
                probe = _run(
                    [str(python), "-c",
                     f"from gliner import GLiNER; GLiNER.from_pretrained({GLINER_MODEL!r})"],
                    timeout=WEIGHTS_TIMEOUT_S,
                )
            except Exception as exc:
                return False, (
                    f"gliner weights ({GLINER_MODEL}) probe timed out/failed: {exc}"
                )
            if probe.returncode != 0:
                # The venv itself is fine (torch/gliner import OK) — only the
                # weights fetch failed, so keep the venv; re-installing torch
                # on every race would be far costlier than the disk it holds.
                return False, (
                    f"gliner weights ({GLINER_MODEL}) download/load failed "
                    f"(venv kept): {probe.stderr.decode()[-300:]}"
                )
            self._python = python
            return True, ""
        except Exception as exc:  # available() must never raise
            return False, f"gliner provisioning raised: {exc}"

    def concepts(self, sections: list[dict]) -> list[dict]:
        # HF_HUB_OFFLINE is set before importing gliner: available() has
        # already cached the weights, and online metadata calls against a
        # stalling HF hub were what timed this stage out (run5 crash).
        script = (
            "import os\n"
            "os.environ['HF_HUB_OFFLINE'] = '1'\n"
            "import sys, json\n"
            "from gliner import GLiNER\n"
            "texts = json.load(sys.stdin)\n"
            f"model = GLiNER.from_pretrained({GLINER_MODEL!r})\n"
            f"labels = {GLINER_LABELS!r}\n"
            "found = {}\n"
            "for text in texts:\n"
            "    if not text:\n"
            "        continue\n"
            # gliner truncates very long inputs; chunk on whitespace.
            "    words = text.split()\n"
            "    chunks, cur, size = [], [], 0\n"
            "    for w in words:\n"
            "        cur.append(w); size += len(w) + 1\n"
            "        if size >= 1500:\n"
            "            chunks.append(' '.join(cur)); cur, size = [], 0\n"
            "    if cur:\n"
            "        chunks.append(' '.join(cur))\n"
            "    for chunk in chunks:\n"
            "        for ent in model.predict_entities(chunk, labels, threshold=0.5):\n"
            "            name = ent['text'].strip()\n"
            "            if not name:\n"
            "                continue\n"
            "            key = (name, ent['label'])\n"
            "            found[key] = found.get(key, 0) + 1\n"
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


class WittgensteinRules(Candidate):
    """imoscovitz_wittgenstein — RIPPER supervised rule classifier.

    RIPPER (code/wittgenstein/ripper.py, abstract_ruleset_classifier.py)
    learns classification rules from labeled training data. The concepts
    stage supplies unlabeled sections, so there is no honest adaptation from
    rule classification to concept extraction — report unavailable with
    exactly that reason (FastTextConcepts idiom). The wittgenstein venv
    install is not attempted: the outcome is unavailable regardless and disk
    is tight.
    """
    name = "wittgenstein-rules"
    stages = {"concepts"}

    def available(self) -> tuple[bool, str]:
        try:
            return False, (
                "wittgenstein RIPPER is a supervised rule classifier "
                "requiring labeled training data; the concepts stage "
                "provides unlabeled sections, so no honest "
                "concept-extraction adaptation exists"
            )
        except Exception as exc:  # available() must never raise
            return False, f"available() check failed: {exc}"


CANDIDATES = [OntoCastConcepts, OpenNlpNer, NeMoGliner, WittgensteinRules]
