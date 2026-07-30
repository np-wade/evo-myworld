"""Graph family — Stage 5 candidates.

- networkx-cooc: co-occurrence edges via networkx (section-window baseline).
- jaccard-graph: pure-python name+evidence jaccard >= 0.18 edges — mirrors the
  incumbent's secondary edge rule, to test whether that rule helps or hurts
  against the gold co-occurrence truth.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate, provision_venv  # noqa: E402


def _tokens(text: str) -> set[str]:
    import re
    return {t for t in re.findall(r"[a-z0-9][a-z0-9-]{2,}", text.lower())}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class NetworkxCooc(Candidate):
    name = "networkx-cooc"
    stages = {"graph"}

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        self._python, reason = provision_venv("networkx", ["networkx"])
        return (self._python is not None), reason

    def graph(self, concepts: list[dict]) -> dict:
        import json
        import subprocess
        script = (
            "import sys, json\n"
            "import networkx as nx\n"
            "concepts = json.load(sys.stdin)\n"
            "g = nx.Graph()\n"
            "for c in concepts:\n"
            "    g.add_node(c['name'])\n"
            "for i, a in enumerate(concepts):\n"
            "    for b in concepts[i+1:]:\n"
            "        shared = set(a.get('sectionIds', [])) & set(b.get('sectionIds', []))\n"
            "        if shared:\n"
            "            g.add_edge(a['name'], b['name'], weight=len(shared))\n"
            "print(json.dumps({'nodes': list(g.nodes), 'edges': list(g.edges)}))\n"
        )
        proc = subprocess.run([str(self._python), "-c", script],
                              input=json.dumps(concepts).encode(),
                              capture_output=True, timeout=90)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-300:])
        return json.loads(proc.stdout.decode())


class JaccardGraph(Candidate):
    """No deps: edges where jaccard(name + evidence) >= 0.18, even without a
    shared section. Tests the incumbent's secondary edge rule directly."""
    name = "jaccard-graph"
    stages = {"graph"}

    def available(self):
        return True, ""

    def graph(self, concepts: list[dict]) -> dict:
        edges = []
        for i, a in enumerate(concepts):
            for b in concepts[i + 1:]:
                shared = set(a.get("sectionIds", [])) & set(b.get("sectionIds", []))
                sim = _jaccard(
                    _tokens(f"{a['name']} {a.get('evidence', '')}"),
                    _tokens(f"{b['name']} {b.get('evidence', '')}"),
                )
                if shared or sim >= 0.18:
                    edges.append((a["name"], b["name"]))
        return {"nodes": [c["name"] for c in concepts], "edges": edges}


CANDIDATES = [NetworkxCooc, JaccardGraph]
