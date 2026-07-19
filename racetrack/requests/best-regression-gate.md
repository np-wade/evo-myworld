# race: best-regression-gate
seat: claude-backend
question: best minimal regression-gate DESIGN for lab modules — the meta-race about how we should test things in here
metric: max — bugs caught out of a planted-bug suite (steward plants 6 small behavior bugs in a copy of world/backend/evo_graph.py; each gate design runs against clean + each bugged copy; score = caught count, false-positives on clean disqualify)
gate: gate must pass on the CLEAN module (no false alarms) and run in under 60s

## candidate: snapshot-diff
source: world/hermes/gates/regression.py (hermes' Track A gate library, see world/hermes/gates/PRIOR-ART.md citations)
approach: record golden outputs for a fixed probe-set once; regression = any output drift vs the golden snapshot.

## candidate: behavioral-probes
source: EverMind-AI_raven/code/eval_engine/ and EverMind-AI_EvoAgentBench (library corpus) — property/probe style checks
approach: no goldens; a small set of invariant probes (e.g. "known-good hit appears in top-3", "empty query exits clean", "result count ≤ limit") that assert properties rather than exact bytes — robust to benign drift, catches behavior breaks.
