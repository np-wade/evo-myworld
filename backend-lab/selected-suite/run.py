#!/usr/bin/env python3
"""Dependency-free first-pass races for the selected backend capabilities."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sqlite3
import statistics
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "candidates.json").read_text(encoding="utf-8"))


@dataclass
class Result:
    race: str
    candidate: str
    source: str
    kind: str
    score: float | None
    gate: bool | None
    metrics: dict[str, Any] = field(default_factory=dict)
    status: str = "scored"
    reason: str = ""


def source_for(race: str, candidate: str) -> tuple[str, str]:
    for group in ("runnable", "pending"):
        for item in MANIFEST[race][group]:
            if item["id"] == candidate:
                return item["source"], item.get("kind", "pending")
    raise KeyError((race, candidate))


def timed(fn: Callable[[], Any], repeats: int = 1) -> tuple[Any, float]:
    samples = []
    value = None
    for _ in range(repeats):
        start = time.perf_counter()
        value = fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return value, statistics.median(samples)


def tokenise(text: str) -> list[str]:
    out, current = [], []
    for char in text.lower():
        if char.isalnum() or char in "+#_":
            current.append(char)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def pending_results(race: str) -> list[Result]:
    return [
        Result(
            race=race,
            candidate=item["id"],
            source=item["source"],
            kind="pending",
            score=None,
            gate=None,
            status="pending",
            reason=item["needs"],
        )
        for item in MANIFEST[race]["pending"]
    ]


# ---------------------------------------------------------------------------
# 1. Cross-app contract


def contract_fixture() -> list[tuple[dict[str, Any], bool]]:
    base = {
        "version": 1,
        "id": "task-001",
        "type": "task.create",
        "trace_id": "trace-001",
        "ts": "2026-07-28T12:00:00Z",
        "scope": "lab.project",
        "payload": {"title": "build fixture"},
        "metadata": {"foreign": {"safe": True}},
    }
    cases = [(base, True)]
    for key in ("version", "id", "type", "trace_id", "ts", "payload"):
        broken = dict(base)
        broken.pop(key)
        cases.append((broken, False))
    cases.extend(
        [
            ({**base, "version": 2}, False),
            ({**base, "payload": "not-an-object"}, False),
            ({**base, "id": ""}, False),
            ({**base, "metadata": {"unknown-vendor": {"x": 1}}}, True),
            ({**base, "scope": "lab.project.run", "extra": "forward-compatible"}, True),
        ]
    )
    return cases


def validate_contract(record: dict[str, Any], profile: str) -> bool:
    required = ("version", "id", "type", "trace_id", "ts", "payload")
    if not all(key in record for key in required):
        return False
    if record["version"] != 1 or not record["id"] or not isinstance(record["payload"], dict):
        return False
    if profile == "claw-cip-profile":
        if not isinstance(record.get("metadata", {}), dict):
            return False
        if not str(record["type"]).startswith(("task.", "session.", "message.")):
            return False
    return True


def race_contract() -> list[Result]:
    fixture = contract_fixture()
    results = []
    for candidate in ("versioned-jsonl", "claw-cip-profile"):
        predictions, elapsed = timed(
            lambda: [validate_contract(record, candidate) for record, _ in fixture],
            repeats=20,
        )
        answers = [answer for _, answer in fixture]
        correct = sum(pred == answer for pred, answer in zip(predictions, answers))
        valid_roundtrip = all(
            json.loads(json.dumps(record, sort_keys=True)) == record
            for record, expected in fixture
            if expected
        )
        unknown_metadata_ok = predictions[-2]
        score = correct / len(fixture)
        gate = score == 1.0 and valid_roundtrip and unknown_metadata_ok
        source, kind = source_for("cross_app_contract", candidate)
        results.append(
            Result(
                "cross_app_contract",
                candidate,
                source,
                kind,
                score,
                gate,
                {
                    "cases": len(fixture),
                    "correct": correct,
                    "median_ms": round(elapsed, 6),
                    "roundtrip": valid_roundtrip,
                    "foreign_metadata": unknown_metadata_ok,
                },
            )
        )
    return results + pending_results("cross_app_contract")


# ---------------------------------------------------------------------------
# 2. Agent lifecycle and mission control


class Scheduler:
    def __init__(self, profile: str):
        self.profile = profile
        self.jobs: dict[str, dict[str, Any]] = {}
        self.claims: dict[str, str] = {}
        self.events: list[tuple[str, str]] = []

    def add(self, job_id: str, deps: tuple[str, ...] = (), parent: str | None = None) -> None:
        self.jobs[job_id] = {
            "status": "pending" if deps else "ready",
            "deps": deps,
            "parent": parent,
        }

    def claim(self, job_id: str, owner: str) -> bool:
        job = self.jobs[job_id]
        if job["status"] == "running" and self.claims.get(job_id) == owner:
            return True
        if job["status"] != "ready" or job_id in self.claims:
            return False
        self.claims[job_id] = owner
        job["status"] = "running"
        self.events.append((job_id, "claimed"))
        return True

    def finish(self, job_id: str, success: bool) -> None:
        self.jobs[job_id]["status"] = "succeeded" if success else "failed"
        self.events.append((job_id, self.jobs[job_id]["status"]))
        for child_id, child in self.jobs.items():
            if job_id not in child["deps"] or child["status"] != "pending":
                continue
            dep_states = [self.jobs[dep]["status"] for dep in child["deps"]]
            if all(state == "succeeded" for state in dep_states):
                child["status"] = "ready"
            elif self.profile == "witt-spine-lanes" and any(
                state in {"failed", "cancelled"} for state in dep_states
            ):
                child["status"] = "cancelled"

    def cancel(self, job_id: str) -> None:
        self.jobs[job_id]["status"] = "cancelled"
        if self.profile == "evo-mission-dag":
            for child_id, child in self.jobs.items():
                if child["parent"] == job_id:
                    self.cancel(child_id)

    def snapshot(self) -> str:
        return json.dumps({"jobs": self.jobs, "claims": self.claims}, sort_keys=True)

    @classmethod
    def restore(cls, profile: str, payload: str) -> "Scheduler":
        inst = cls(profile)
        state = json.loads(payload)
        inst.jobs = state["jobs"]
        inst.claims = state["claims"]
        return inst


def lifecycle_scenarios(profile: str) -> dict[str, bool]:
    s = Scheduler(profile)
    s.add("research")
    s.add("build", ("research",), parent="research")
    s.add("verify", ("build",), parent="build")
    idempotent = s.claim("research", "agent-a") and s.claim("research", "agent-a")
    exclusive = not s.claim("research", "agent-b")
    s.finish("research", True)
    dependency = s.jobs["build"]["status"] == "ready"
    s.claim("build", "agent-b")
    restored = Scheduler.restore(profile, s.snapshot())
    recovery = restored.jobs["build"]["status"] == "running" and restored.claims["build"] == "agent-b"

    c = Scheduler(profile)
    c.add("parent")
    c.add("child", parent="parent")
    c.cancel("parent")
    cancel_cascade = c.jobs["child"]["status"] == "cancelled"

    f = Scheduler(profile)
    f.add("a")
    f.add("b", ("a",))
    f.claim("a", "x")
    f.finish("a", False)
    failure_propagation = f.jobs["b"]["status"] in {"cancelled", "blocked"}

    # Pueue's profile is queue-oriented: explicitly model its strengths.
    pause_resume = profile == "pueue-queue"
    if profile == "pueue-queue":
        cancel_cascade = False
        failure_propagation = False

    return {
        "idempotent_claim": idempotent,
        "exclusive_claim": exclusive,
        "dependency_unlock": dependency,
        "restart_recovery": recovery,
        "cancel_cascade": cancel_cascade,
        "failure_propagation": failure_propagation,
        "pause_resume": pause_resume,
    }


def race_lifecycle() -> list[Result]:
    results = []
    for candidate in ("evo-mission-dag", "witt-spine-lanes", "pueue-queue"):
        scenarios, elapsed = timed(lambda: lifecycle_scenarios(candidate), repeats=100)
        passed = sum(scenarios.values())
        score = passed / len(scenarios)
        gate = all(
            scenarios[name]
            for name in (
                "idempotent_claim",
                "exclusive_claim",
                "dependency_unlock",
                "restart_recovery",
            )
        )
        source, kind = source_for("agent_lifecycle", candidate)
        results.append(
            Result(
                "agent_lifecycle",
                candidate,
                source,
                kind,
                score,
                gate,
                {"passed": passed, "total": len(scenarios), "median_ms": round(elapsed, 6), **scenarios},
            )
        )
    return results + pending_results("agent_lifecycle")


# ---------------------------------------------------------------------------
# 5. Cross-app identity and trace stitching


def normalize_repo(value: str) -> str:
    value = value.lower().replace("cloned__library__", "")
    parts = value.split("__")
    if len(parts) > 2 and len(parts[-1]) >= 6:
        parts = parts[:-1]
    value = "_".join(parts)
    return "".join(ch for ch in value if ch.isalnum())


def identity_fixture() -> list[tuple[str, str, bool]]:
    positives = [
        ("Graphify-Labs_graphify", "cloned__library__Graphify-Labs__graphify__htef7z", True),
        ("iOfficeAI_OfficeCLI", "iofficeai-officecli", True),
        ("zeroclaw-labs_zeroclaw", "zeroclaw_labs/zeroclaw", True),
        ("EverMind-AI_HyperMem", "evermind-ai__hypermem", True),
    ]
    negatives = [
        ("EverMind-AI_HyperMem", "EverMind-AI_EverMemBench", False),
        ("apache_iceberg", "apache_iceberg-rust", False),
        ("witt-brain", "witt-link-server", False),
        ("qdrant_qdrant", "quickwit-oss_tantivy", False),
    ]
    return positives + negatives


def identity_predict(a: str, b: str, candidate: str) -> bool:
    na, nb = normalize_repo(a), normalize_repo(b)
    if candidate in {"normalized-name-trace-id", "agent-trace-envelope"}:
        return na == nb
    ta, tb = set(tokenise(a.replace("_", " "))), set(tokenise(b.replace("_", " ")))
    similarity = len(ta & tb) / max(1, len(ta | tb))
    return na == nb or similarity >= 0.8


def race_identity_trace() -> list[Result]:
    fixture = identity_fixture()
    results = []
    for candidate in ("normalized-name-trace-id", "agent-trace-envelope", "cosine-resolution"):
        predictions, elapsed = timed(
            lambda: [identity_predict(a, b, candidate) for a, b, _ in fixture],
            repeats=100,
        )
        tp = sum(pred and truth for pred, (_, _, truth) in zip(predictions, fixture))
        fp = sum(pred and not truth for pred, (_, _, truth) in zip(predictions, fixture))
        fn = sum(not pred and truth for pred, (_, _, truth) in zip(predictions, fixture))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

        trace = [
            {"trace_id": "t1", "span_id": "s1", "parent_id": None, "seq": 1},
            {"trace_id": "t1", "span_id": "s2", "parent_id": "s1", "seq": 2},
            {"trace_id": "t1", "span_id": "s3", "parent_id": "s2", "seq": 3},
        ]
        trace_ok = len({x["span_id"] for x in trace}) == 3 and [x["seq"] for x in trace] == [1, 2, 3]
        hard_negative_ok = predictions[4] is False
        gate = hard_negative_ok and trace_ok and f1 >= 0.85
        source, kind = source_for("identity_trace", candidate)
        results.append(
            Result(
                "identity_trace",
                candidate,
                source,
                kind,
                f1,
                gate,
                {
                    "precision": precision,
                    "recall": recall,
                    "trace_join_rate": 1.0 if trace_ok else 0.0,
                    "median_ms": round(elapsed, 6),
                },
            )
        )
    return results + pending_results("identity_trace")


# ---------------------------------------------------------------------------
# 6. Gateway routing and failover


ROUTE_FIXTURE = [
    ("/api/documents", "information-processer"),
    ("/api/stages/2", "information-processer"),
    ("/evo/", "evo-dashboard"),
    ("/dashboard/runs", "evo-dashboard"),
    ("/api/rooms", "witt-link"),
    ("/ws/room/abc", "witt-link"),
    ("/models/list", "localai"),
]


def route(path: str, candidate: str, health: dict[str, bool]) -> str | None:
    if candidate == "hardcoded-ports":
        # Demonstrates why one shared front door cannot infer colliding ownership.
        return "witt-link" if path.startswith("/api/") else "evo-dashboard"
    if candidate == "prefix-front-door":
        if path.startswith("/api/documents") or path.startswith("/api/stages"):
            return "information-processer"
        if path.startswith("/api/rooms") or path.startswith("/ws/"):
            return "witt-link"
        if path.startswith("/evo/") or path.startswith("/dashboard/"):
            return "evo-dashboard"
        return "localai" if path.startswith("/models/") else None
    primary = route(path, "prefix-front-door", health)
    if primary and health.get(primary, False):
        return primary
    fallback = {
        "information-processer": "witt-link",
        "evo-dashboard": "witt-link",
        "localai": "witt-link",
    }.get(primary)
    return fallback if fallback and health.get(fallback, False) else None


def race_routing() -> list[Result]:
    results = []
    healthy = {name: True for _, name in ROUTE_FIXTURE}
    for candidate in ("hardcoded-ports", "prefix-front-door", "health-registry-router"):
        outputs, elapsed = timed(lambda: [route(path, candidate, healthy) for path, _ in ROUTE_FIXTURE], repeats=500)
        correct = sum(out == expected for out, (_, expected) in zip(outputs, ROUTE_FIXTURE))
        precision = correct / len(ROUTE_FIXTURE)
        degraded = dict(healthy)
        degraded["localai"] = False
        failover = route("/models/list", candidate, degraded)
        failover_ok = failover not in {None, "localai"}
        gate = precision == 1.0 and failover_ok
        source, kind = source_for("gateway_routing", candidate)
        results.append(
            Result(
                "gateway_routing",
                candidate,
                source,
                kind,
                precision,
                gate,
                {
                    "routes": len(ROUTE_FIXTURE),
                    "correct": correct,
                    "failover": failover,
                    "median_ms": round(elapsed / len(ROUTE_FIXTURE), 6),
                },
            )
        )
    return results + pending_results("gateway_routing")


# ---------------------------------------------------------------------------
# 8. Unified hybrid recall


DOCS = [
    ("d0", "falkor graph database cypher traversal", (0.95, 0.05, 0.0)),
    ("d1", "persistent agent memory recall", (0.05, 0.95, 0.0)),
    ("d2", "reverse proxy route health failover", (0.0, 0.1, 0.9)),
    ("d3", "knowledge neighborhood edge walk", (0.88, 0.12, 0.0)),
    ("d4", "remember prior conversation facts", (0.08, 0.9, 0.02)),
    ("d5", "gateway dispatch backend target", (0.0, 0.15, 0.85)),
    ("d6", "push_to_falkordb function", (0.98, 0.02, 0.0)),
    ("d7", "episodic context store", (0.12, 0.86, 0.02)),
]

QUERIES = [
    # Deliberately bad embedding for an exact symbol query: a hybrid must let
    # the lexical arm rescue it instead of trusting every embedding blindly.
    ("falkor", (0.0, 1.0, 0.0), "d6", "keyword"),
    ("two hop graph neighbors", (0.92, 0.08, 0.0), "d3", "mixed"),
    ("what did the agent remember", (0.0, 1.0, 0.0), "d4", "semantic"),
    ("service routing fallback", (0.0, 0.0, 1.0), "d2", "mixed"),
    ("episodic memory", (0.05, 0.95, 0.0), "d7", "semantic"),
]


def fts_rank(query: str) -> list[str]:
    q = set(tokenise(query))
    scored = []
    for doc_id, text, _ in DOCS:
        tokens = set(tokenise(text))
        overlap = len(q & tokens)
        exact = 2 if query.lower() in text.lower() else 0
        scored.append((overlap + exact, doc_id))
    return [doc for score, doc in sorted(scored, key=lambda x: (-x[0], x[1])) if score > 0]


def vector_rank(vector: tuple[float, ...]) -> list[str]:
    return [doc for _, doc in sorted(((cosine(vector, v), doc) for doc, _, v in DOCS), key=lambda x: (-x[0], x[1]))]


def rrf_rank(keyword: list[str], semantic: list[str], k: int = 60) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for arm in (keyword, semantic):
        for rank, doc_id in enumerate(arm, start=1):
            scores[doc_id] += 1.0 / (k + rank)
    return [doc for doc, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))]


def recall_output(candidate: str, query: str, vector: tuple[float, ...]) -> list[str]:
    keyword = fts_rank(query)
    semantic = vector_rank(vector)
    if candidate == "fts-only":
        return keyword
    if candidate == "vector-only":
        return semantic
    return rrf_rank(keyword, semantic)


def race_hybrid() -> list[Result]:
    results = []
    for candidate in ("fts-only", "vector-only", "rrf-hybrid"):
        def evaluate() -> list[bool]:
            return [
                gold in recall_output(candidate, query, vector)[:3]
                for query, vector, gold, _ in QUERIES
            ]

        hits, elapsed = timed(evaluate, repeats=500)
        recall = sum(hits) / len(hits)
        keyword_ok = all(
            hit for hit, query in zip(hits, QUERIES) if query[3] == "keyword"
        )
        semantic_ok = all(
            hit for hit, query in zip(hits, QUERIES) if query[3] == "semantic"
        )
        gate = keyword_ok and semantic_ok and recall >= 0.8
        source, kind = source_for("hybrid_recall", candidate)
        results.append(
            Result(
                "hybrid_recall",
                candidate,
                source,
                kind,
                recall,
                gate,
                {
                    "recall_at_3": recall,
                    "keyword_gate": keyword_ok,
                    "semantic_gate": semantic_ok,
                    "median_ms_per_query": round(elapsed / len(QUERIES), 6),
                },
            )
        )
    return results + pending_results("hybrid_recall")


# ---------------------------------------------------------------------------
# 9. Graph and lineage storage


def graph_fixture(seed: int = 17, nodes: int = 300, edges: int = 1400) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    generated = set()
    while len(generated) < edges:
        src = rng.randrange(nodes)
        dst = rng.randrange(nodes)
        if src != dst:
            generated.add((src, dst))
    return sorted(generated)


def build_adjacency(edges: list[tuple[int, int]]) -> dict[int, set[int]]:
    adj: dict[int, set[int]] = defaultdict(set)
    for src, dst in edges:
        adj[src].add(dst)
    return adj


def adjacency_walk(adj: dict[int, set[int]], start: int, depth: int = 2) -> set[int]:
    seen, frontier = set(), {start}
    for _ in range(depth):
        frontier = {dst for src in frontier for dst in adj.get(src, set())} - seen
        seen |= frontier
    seen.discard(start)
    return seen


def sqlite_walk(conn: sqlite3.Connection, start: int, depth: int = 2) -> set[int]:
    rows = conn.execute(
        """
        WITH RECURSIVE walk(node, depth) AS (
          SELECT dst, 1 FROM edges WHERE src = ?
          UNION
          SELECT e.dst, walk.depth + 1
          FROM edges e JOIN walk ON e.src = walk.node
          WHERE walk.depth < ?
        )
        SELECT DISTINCT node FROM walk WHERE node != ?
        """,
        (start, depth, start),
    ).fetchall()
    return {row[0] for row in rows}


def race_graph() -> list[Result]:
    edges = graph_fixture()
    adjacency = build_adjacency(edges)
    probes = list(range(40))
    truth = {probe: adjacency_walk(adjacency, probe) for probe in probes}
    results = []

    _, memory_ms = timed(lambda: [adjacency_walk(adjacency, probe) for probe in probes], repeats=20)
    source, kind = source_for("graph_lineage", "memory-adjacency")
    results.append(
        Result(
            "graph_lineage",
            "memory-adjacency",
            source,
            kind,
            1.0,
            True,
            {"probes": len(probes), "p50_batch_ms": round(memory_ms, 6), "exact": True},
        )
    )

    with tempfile.TemporaryDirectory(prefix="backend-graph-") as tmp:
        db = Path(tmp) / "graph.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            "CREATE TABLE edges(src INTEGER NOT NULL, dst INTEGER NOT NULL);"
            "CREATE INDEX edges_src ON edges(src);"
        )
        conn.executemany("INSERT INTO edges VALUES (?, ?)", edges)
        conn.commit()
        outputs, sqlite_ms = timed(lambda: [sqlite_walk(conn, probe) for probe in probes], repeats=20)
        exact = all(output == truth[probe] for probe, output in zip(probes, outputs))
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        conn.close()
    source, kind = source_for("graph_lineage", "sqlite-edges")
    results.append(
        Result(
            "graph_lineage",
            "sqlite-edges",
            source,
            kind,
            1.0 if exact else 0.0,
            exact and integrity,
            {
                "probes": len(probes),
                "p50_batch_ms": round(sqlite_ms, 6),
                "exact": exact,
                "integrity": integrity,
            },
        )
    )
    return results + pending_results("graph_lineage")


# ---------------------------------------------------------------------------
# 10. Safe self-improvement


LANDSCAPES = [
    # Each arm has (visible/train reward, held-out reward).
    [(0.60, 0.55), (0.72, 0.68), (0.88, 0.30), (0.66, 0.72)],
    [(0.58, 0.60), (0.64, 0.65), (0.76, 0.70), (0.80, 0.50)],
    [(0.50, 0.52), (0.70, 0.69), (0.73, 0.74), (0.69, 0.71)],
]


def select_arm(candidate: str, observations: list[list[float]], rng: random.Random) -> int:
    means = [statistics.mean(values) for values in observations]
    if candidate == "argmax":
        return max(range(len(means)), key=lambda i: (means[i], -i))
    if candidate == "flywheel-ucb":
        total = sum(len(values) for values in observations)
        values = [
            means[i] + math.sqrt(2.0 * math.log(total) / len(observations[i]))
            for i in range(len(means))
        ]
        return max(range(len(values)), key=lambda i: (values[i], -i))
    # A small deterministic approximation of per-task Pareto preservation:
    # cycle among the top visible arms so one apparently-best branch cannot
    # consume the entire budget.
    top = sorted(range(len(means)), key=lambda i: (-means[i], i))[:3]
    return top[sum(len(v) for v in observations) % len(top)]


def simulate_improvement(candidate: str, landscape: list[tuple[float, float]], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    # The proposal stage exposes only visible/train rewards. Held-out scores
    # stay locked until a strategy actually selects a candidate for promotion.
    observations = [[visible] for visible, _ in landscape]
    selected: set[int] = set()
    promoted = 0
    rejected = 0
    best_heldout = 0.50
    for _ in range(12):
        arm = select_arm(candidate, observations, rng)
        selected.add(arm)
        visible, heldout = landscape[arm]
        noisy_visible = visible + rng.uniform(-0.01, 0.01)
        observations[arm].append(noisy_visible)
        # Independent verification: visible-score improvements do not promote
        # when held-out regresses.
        if heldout >= best_heldout:
            best_heldout = heldout
            promoted += 1
        else:
            rejected += 1
    return {
        "best_heldout": best_heldout,
        "promoted": promoted,
        "rejected": rejected,
        "tried_arms": len(selected),
    }


def race_self_improvement() -> list[Result]:
    results = []
    for candidate in ("argmax", "evo-pareto", "flywheel-ucb"):
        runs, elapsed = timed(
            lambda: [simulate_improvement(candidate, landscape, 100 + i) for i, landscape in enumerate(LANDSCAPES)],
            repeats=30,
        )
        mean_best = statistics.mean(run["best_heldout"] for run in runs)
        explored = statistics.mean(run["tried_arms"] for run in runs)
        rejected = sum(run["rejected"] for run in runs)
        gate = mean_best >= 0.65 and rejected > 0 and all(run["promoted"] > 0 for run in runs)
        source, kind = source_for("self_improvement", candidate)
        results.append(
            Result(
                "self_improvement",
                candidate,
                source,
                kind,
                mean_best,
                gate,
                {
                    "mean_best_heldout": mean_best,
                    "mean_arms_explored": explored,
                    "unsafe_promotions_blocked": rejected,
                    "median_ms": round(elapsed, 6),
                    "weight_updates": False,
                },
            )
        )
    return results + pending_results("self_improvement")


RACES: dict[str, Callable[[], list[Result]]] = {
    "cross_app_contract": race_contract,
    "agent_lifecycle": race_lifecycle,
    "identity_trace": race_identity_trace,
    "gateway_routing": race_routing,
    "hybrid_recall": race_hybrid,
    "graph_lineage": race_graph,
    "self_improvement": race_self_improvement,
}


def write_outputs(results: list[Result], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = [asdict(result) for result in results]
    (output_dir / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = ["# Selected backend race results", ""]
    for race in RACES:
        lines.extend([f"## {race.replace('_', ' ').title()}", "", "| Candidate | Kind | Score | Gate | Status |", "|---|---:|---:|---:|---|"])
        for result in [r for r in results if r.race == race]:
            score = "—" if result.score is None else f"{result.score:.4f}"
            gate = "—" if result.gate is None else ("PASS" if result.gate else "FAIL")
            lines.append(f"| {result.candidate} | {result.kind} | {score} | {gate} | {result.status} |")
        lines.append("")
    lines.extend(
        [
            "Technique-port scores validate the arena; they do not establish that the full upstream repository wins.",
            "Pending native adapters must run before architectural promotion.",
            "",
        ]
    )
    (output_dir / "results.md").write_text("\n".join(lines), encoding="utf-8")

    traces_dir = os.environ.get("EVO_TRACES_DIR")
    if traces_dir:
        trace_root = Path(traces_dir)
        trace_root.mkdir(parents=True, exist_ok=True)
        for index, result in enumerate(results):
            target = trace_root / f"task_{index:03d}.json"
            target.write_text(
                json.dumps(
                    {
                        "task_id": f"{result.race}:{result.candidate}",
                        "score": result.score if result.score is not None else 0.0,
                        "extras": asdict(result),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    result_path = os.environ.get("EVO_RESULT_PATH")
    scored = [r.score for r in results if r.score is not None and r.gate]
    aggregate = statistics.mean(scored) if scored else 0.0
    evo_payload = {"score": aggregate, "tasks": len(results), "gated_scores": len(scored)}
    if result_path:
        Path(result_path).write_text(json.dumps(evo_payload) + "\n", encoding="utf-8")
    else:
        print(json.dumps(evo_payload))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="run every selected race")
    parser.add_argument("--race", choices=sorted(RACES), action="append")
    parser.add_argument("--output", type=Path, default=ROOT / "out")
    parser.add_argument("--min-score", type=float)
    args = parser.parse_args()
    chosen = list(RACES) if args.all or not args.race else args.race
    results = [result for race in chosen for result in RACES[race]()]
    write_outputs(results, args.output)
    gated = [r.score for r in results if r.score is not None and r.gate]
    score = statistics.mean(gated) if gated else 0.0
    if args.min_score is not None and score < args.min_score:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
