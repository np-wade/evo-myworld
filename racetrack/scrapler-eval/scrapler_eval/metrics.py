"""Scrapler Eval Harness — per-axis 0..1 scorers, IR primitives, item blend.

Pure stdlib. No third-party imports (no numpy/torch/faiss). Runs on the host
3.14 and the spider-den 3.12 venv alike.

Metric primitives ported faithfully from the roboflow/supervision metrics
package (donor), reimplemented in plain Python floats/lists:

  - Precision  = TP / (TP + FP)
      src/supervision/metrics/precision.py::Precision._compute_precision
  - Recall     = TP / (TP + FN)
      src/supervision/metrics/recall.py::Recall._compute_recall
  - F1         = 2 * P * R / (P + R)
      src/supervision/metrics/f1_score.py::F1Score  (harmonic mean)
  - set-overlap (IoU-style) = |A ∩ B| / |A ∪ B|
      the Jaccard/IoU idea behind box_iou_batch + the greedy one-to-one match
      in src/supervision/metrics/utils/matching.py::_greedy_match, collapsed to
      set membership for field/string matching (no geometry, no numpy).

Per-task 0..1 scoring shape (count correct / total, normalized string compare)
follows EverMind-AI/EverMemBench eval/src/core/evaluator.py::Evaluator
(accuracy = correct / total; compare via .strip()/.upper() normalization).

Everything below returns a float in [0.0, 1.0] (or a dict of such for score()).
"""

from __future__ import annotations

import math
from typing import Any

from .interface import AxisScores, ExtractResult, FetchResult, Task, WeightClass

__all__ = [
    # scraping axis scorers
    "retrieval_score",
    "completeness_score",
    "evasion_score",
    "latency_norm",
    "cost_norm",
    "robustness_score",
    "field_accuracy",
    # search / IR primitives
    "precision_at_k",
    "recall",
    "average_precision",
    "mrr",
    "ndcg_at_k",
    # helpers exposed for reuse / tests
    "precision",
    "f1",
    "set_overlap",
    "norm_str",
    # blends
    "score",
    "item_quality",
]


# --------------------------------------------------------------------------- #
# tiny pure-math helpers                                                       #
# --------------------------------------------------------------------------- #
def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp x into the inclusive [lo, hi] range."""
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def norm_str(value: Any) -> str:
    """Normalize any value to a comparable string (EverMemBench style).

    Lower-cased, stripped, internal whitespace collapsed — so "Foo  Bar " and
    "foo bar" compare equal in field/string matching.
    """
    return " ".join(str(value).strip().lower().split())


def precision(tp: float, fp: float) -> float:
    """Precision = TP / (TP + FP); 0.0 when there are no predictions.

    Ported from supervision Precision._compute_precision (numpy divide with a
    zero-fill where the denominator is 0).
    """
    denom = tp + fp
    if denom <= 0:
        return 0.0
    return tp / denom


def _recall_tp_fn(tp: float, fn: float) -> float:
    """Recall = TP / (TP + FN); 0.0 when there is no ground truth.

    Ported from supervision Recall._compute_recall.
    """
    denom = tp + fn
    if denom <= 0:
        return 0.0
    return tp / denom


def f1(p: float, r: float) -> float:
    """F1 = harmonic mean of precision and recall; 0.0 when both are 0.

    Ported from supervision F1Score (2 * P * R / (P + R)).
    """
    denom = p + r
    if denom <= 0:
        return 0.0
    return 2.0 * p * r / denom


def set_overlap(a: Any, b: Any) -> float:
    """IoU-style set overlap (Jaccard): |A ∩ B| / |A ∪ B|.

    Collapses the supervision box-IoU idea to plain set membership so it works
    on tokenized strings or arbitrary hashable collections. Two empty sets are
    defined as a perfect overlap (1.0); one empty and one not is 0.0.
    """
    sa = a if isinstance(a, (set, frozenset)) else set(_tokenize(a))
    sb = b if isinstance(b, (set, frozenset)) else set(_tokenize(b))
    if not sa and not sb:
        return 1.0
    union = sa | sb
    if not union:
        return 1.0
    inter = sa & sb
    return len(inter) / len(union)


def _tokenize(value: Any) -> list[str]:
    """Split a value into normalized whitespace tokens for set overlap."""
    if isinstance(value, (list, tuple)):
        return [norm_str(v) for v in value]
    return norm_str(value).split()


# --------------------------------------------------------------------------- #
# 1. scraping axis scorers                                                     #
# --------------------------------------------------------------------------- #
def retrieval_score(fetch: FetchResult, threshold: int = 200) -> float:
    """Did we get real content back? 1.0 for a clean, non-empty fetch.

    0.0 if blocked, not ok, or empty. Between empty and `threshold` chars the
    score grades linearly (len/threshold); at/above `threshold` it is 1.0.
    """
    if fetch is None or not fetch.ok or fetch.blocked:
        return 0.0
    n = len(fetch.text or "")
    if n <= 0:
        return 0.0
    if threshold <= 0:
        return 1.0
    if n >= threshold:
        return 1.0
    return _clamp(n / threshold)


def completeness_score(fetch: FetchResult, task: Task) -> float:
    """Captured content ÷ expected, capped at 1.0.

    Precedence of the answer key:
      1. ``expected_chars``  -> len(text) / expected_chars
      2. ``expected_blocks`` -> captured_blocks / expected_blocks
      3. ``must_contain``    -> fraction of required substrings present
    With no usable key we cannot judge completeness, so 0.0.
    """
    key = task.answer_key if task and task.answer_key else {}
    text = fetch.text or "" if fetch else ""

    if "expected_chars" in key:
        expected = key["expected_chars"]
        if not expected or expected <= 0:
            return 1.0
        return _clamp(len(text) / expected)

    if "expected_blocks" in key:
        expected = key["expected_blocks"]
        if not expected or expected <= 0:
            return 1.0
        captured = _count_blocks(fetch)
        return _clamp(captured / expected)

    if "must_contain" in key:
        subs = key["must_contain"] or []
        if not subs:
            return 1.0
        hay = text
        hits = sum(1 for s in subs if str(s) in hay)
        return _clamp(hits / len(subs))

    return 0.0


def _count_blocks(fetch: FetchResult) -> int:
    """Count captured content blocks.

    Prefers an explicit ``artifacts['blocks']`` list; otherwise falls back to
    counting blank-line-separated non-empty paragraphs in the extracted text.
    """
    if fetch is None:
        return 0
    blocks = fetch.artifacts.get("blocks") if fetch.artifacts else None
    if isinstance(blocks, (list, tuple)):
        return len(blocks)
    if isinstance(blocks, int):
        return blocks
    text = fetch.text or ""
    paras = [p for p in text.split("\n\n") if p.strip()]
    return len(paras)


def evasion_score(fetch: FetchResult) -> float:
    """Bot-detector pass fraction.

    Uses ``artifacts['detector_pass']`` when present — a float fraction, or a
    list of pass/fail booleans (averaged). With no detector signal: 0.0 if
    blocked, 1.0 for a clean live fetch, else 0.0.
    """
    if fetch is None:
        return 0.0
    if fetch.artifacts and "detector_pass" in fetch.artifacts:
        dp = fetch.artifacts["detector_pass"]
        if isinstance(dp, bool):
            return 1.0 if dp else 0.0
        if isinstance(dp, (int, float)):
            return _clamp(float(dp))
        if isinstance(dp, (list, tuple)) and dp:
            passed = sum(1 for x in dp if x)
            return _clamp(passed / len(dp))
        return 0.0
    if fetch.blocked:
        return 0.0
    return 1.0 if fetch.ok else 0.0


def latency_norm(
    latency_ms: float, field_min_ms: float, field_max_ms: float
) -> float:
    """Inverted min-max normalization of latency (faster = higher).

    score = (max - latency) / (max - min), clamped to [0, 1]. When the field
    has no spread (max == min) every candidate ties at 1.0 (divide-by-zero
    guard).
    """
    span = field_max_ms - field_min_ms
    if span <= 0:
        return 1.0
    return _clamp((field_max_ms - latency_ms) / span)


def cost_norm(fetch: FetchResult, field_max_cost: float) -> float:
    """Inverted footprint cost (cheaper = higher).

    footprint = bytes_down + llm_tokens*4 + peak_rss_mb*1e6
    score = 1 - footprint / field_max_cost, clamped to [0, 1]. A non-positive
    field_max_cost means no measurable cost spread -> 1.0 (divide-by-zero
    guard).
    """
    if fetch is None:
        return 1.0
    footprint = (
        float(fetch.bytes_down)
        + float(fetch.llm_tokens) * 4.0
        + float(fetch.peak_rss_mb) * 1e6
    )
    if field_max_cost <= 0:
        return 1.0
    return _clamp(1.0 - footprint / field_max_cost)


def robustness_score(qualities: list[float]) -> float:
    """1 - population stddev of repeated-run qualities, clamped to [0, 1].

    Fewer than two samples means no observable variance, so 1.0 (perfectly
    consistent / divide-by-zero guard).
    """
    if not qualities or len(qualities) < 2:
        return 1.0
    n = len(qualities)
    mean = sum(qualities) / n
    variance = sum((q - mean) ** 2 for q in qualities) / n  # population
    stddev = math.sqrt(variance)
    return _clamp(1.0 - stddev)


def field_accuracy(extract: ExtractResult, task: Task) -> float:
    """Fraction of expected fields present and matching in the extraction.

    Expected fields live in ``task.answer_key['fields']`` (a name -> value
    map). Each field is compared with a normalized string compare; if the
    expected value is a collection, an IoU-style set overlap of 1.0 counts as a
    match. No expected fields -> 0.0 (nothing to demonstrate; divide-by-zero
    guard).
    """
    key = task.answer_key if task and task.answer_key else {}
    fields = key.get("fields") or {}
    if not fields:
        return 0.0
    got = extract.fields if extract and extract.fields else {}
    hits = 0
    for name, expected in fields.items():
        if name not in got:
            continue
        actual = got[name]
        if isinstance(expected, (list, tuple, set, frozenset)):
            if set_overlap(expected, actual) >= 1.0:
                hits += 1
        elif norm_str(actual) == norm_str(expected):
            hits += 1
    return _clamp(hits / len(fields))


# --------------------------------------------------------------------------- #
# 2. search / IR primitives (ported from supervision math)                    #
# --------------------------------------------------------------------------- #
def precision_at_k(returned: list, relevant, k: int) -> float:
    """Precision@k = (# relevant in top-k) / k.

    `returned` is a ranked list of ids; `relevant` is the set/collection of
    known-good ids. k <= 0 or empty input -> 0.0 (guard).
    """
    if k <= 0 or not returned:
        return 0.0
    rel = set(relevant)
    topk = returned[:k]
    hits = sum(1 for item in topk if item in rel)
    return hits / k


def recall(returned: list, relevant) -> float:
    """Recall = (# relevant retrieved) / (# relevant total).

    Mirrors supervision Recall = TP / (TP + FN). No relevant items -> 0.0.
    """
    rel = set(relevant)
    if not rel:
        return 0.0
    ret = set(returned or [])
    tp = len(ret & rel)
    fn = len(rel - ret)
    return _recall_tp_fn(tp, fn)


def average_precision(returned: list, relevant) -> float:
    """Average Precision: mean of Precision@i at each relevant hit position.

    AP = (1/R) * Σ_i [ rel(i) * Precision@i ], R = # relevant. This is the
    ranked-retrieval reduction of the supervision AP (precision averaged over
    recall points). No relevant items or empty ranking -> 0.0.
    """
    rel = set(relevant)
    if not rel or not returned:
        return 0.0
    hits = 0
    running = 0.0
    for i, item in enumerate(returned, start=1):
        if item in rel:
            hits += 1
            running += hits / i  # precision@i at this relevant hit
    return running / len(rel)


def mrr(ranked: list, relevant) -> float:
    """Mean/Reciprocal Rank: 1 / rank of the first relevant item, else 0.0."""
    rel = set(relevant)
    if not rel or not ranked:
        return 0.0
    for i, item in enumerate(ranked, start=1):
        if item in rel:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list, relevance_map: dict, k: int) -> float:
    """Normalized Discounted Cumulative Gain at k (graded relevance).

    DCG = Σ_{i=1..k} rel_i / log2(i + 1); IDCG is the DCG of the ideal ordering
    (relevances sorted descending). nDCG = DCG / IDCG, in [0, 1]. k <= 0, empty
    ranking, or all-zero relevance -> 0.0 (divide-by-zero guard).
    """
    if k <= 0 or not ranked:
        return 0.0
    rmap = relevance_map or {}

    def dcg(rels: list[float]) -> float:
        total = 0.0
        for i, rel in enumerate(rels[:k], start=1):
            if rel:
                total += rel / math.log2(i + 1)
        return total

    gains = [float(rmap.get(item, 0.0)) for item in ranked]
    ideal = sorted((float(v) for v in rmap.values()), reverse=True)
    idcg = dcg(ideal)
    if idcg <= 0:
        return 0.0
    return _clamp(dcg(gains) / idcg)


# --------------------------------------------------------------------------- #
# 3. compose all axes                                                         #
# --------------------------------------------------------------------------- #
def score(
    fetch: FetchResult,
    extract: ExtractResult | None,
    task: Task,
    field_stats: dict[str, Any] | None = None,
) -> AxisScores:
    """Fill an AxisScores by running every applicable axis scorer.

    `field_stats` carries per-field normalization context:
      - latency_min_ms / latency_max_ms  (for latency_norm)
      - cost_max                         (for cost_norm)
      - qualities: list[float]           (repeated-run qualities for robustness)
    Search axes (relevance/recall/freshness/selfhost) are filled only when the
    task exposes search ground truth (answer_key['relevant']); everything else
    stays at its 0.0 default, per the interface contract.
    """
    fs = field_stats or {}
    axes = AxisScores()

    axes.retrieval = retrieval_score(fetch)
    axes.completeness = completeness_score(fetch, task)
    axes.evasion = evasion_score(fetch)
    axes.latency_norm = latency_norm(
        fetch.latency_ms if fetch else 0.0,
        float(fs.get("latency_min_ms", 0.0)),
        float(fs.get("latency_max_ms", 0.0)),
    )
    axes.cost_norm = cost_norm(fetch, float(fs.get("cost_max", 0.0)))
    axes.robustness = robustness_score(list(fs.get("qualities", [])))
    axes.field_accuracy = field_accuracy(extract, task) if extract else 0.0

    # --- search axes: only when the task carries retrieval ground truth ----
    key = task.answer_key if task and task.answer_key else {}
    if "relevant" in key:
        relevant = key["relevant"]
        ranked = []
        if fetch and fetch.artifacts:
            ranked = fetch.artifacts.get("ranked") or fetch.artifacts.get(
                "results", []
            )
        k = int(key.get("k", len(ranked) or 1))
        axes.relevance = precision_at_k(ranked, relevant, k)
        axes.recall = recall(ranked, relevant)
        if fetch and fetch.artifacts:
            axes.freshness = _clamp(float(fetch.artifacts.get("freshness", 0.0)))
            axes.selfhost = _clamp(float(fetch.artifacts.get("selfhost", 0.0)))

    return axes


# --------------------------------------------------------------------------- #
# 4. per-item quality blend                                                   #
# --------------------------------------------------------------------------- #
def item_quality(axes: AxisScores, weight_class: int) -> float:
    """Blend axis scores into a single per-item quality in [0, 1].

    Weights by weight class (see CONTRACT.md item->leaderboard flow):
      class 1-3 (fetchers/browsers/engines):
          retrieval*0.4 + completeness*0.3 + evasion*0.2 + robustness*0.1
      class 4 (extractor):
          field_accuracy*0.7 + completeness*0.3
      class 5 (search):
          relevance*0.5 + recall*0.3 + freshness*0.1 + selfhost*0.1
    """
    wc = int(weight_class)
    if wc == int(WeightClass.EXTRACTOR):  # 4
        q = axes.field_accuracy * 0.7 + axes.completeness * 0.3
    elif wc == int(WeightClass.SEARCH):  # 5
        q = (
            axes.relevance * 0.5
            + axes.recall * 0.3
            + axes.freshness * 0.1
            + axes.selfhost * 0.1
        )
    else:  # 1, 2, 3 (and any unknown class defaults to the scraping blend)
        q = (
            axes.retrieval * 0.4
            + axes.completeness * 0.3
            + axes.evasion * 0.2
            + axes.robustness * 0.1
        )
    return _clamp(q)
