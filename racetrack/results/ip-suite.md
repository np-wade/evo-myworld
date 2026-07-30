# result: ip-suite (T6)
seat: kimi + subagent lanes (extraction / retrieval / concepts / export / graph / drafting)
question: for each Information Processer stage, is the incumbent the best
implementation in the corpus — and where exactly does it lose?
metric: max — stage score (gate first, then quality metric; see each race mode)
gate: per-stage correctness gate (see `results-*-run*.json` "mode" fields)
oracle: self-authored fixtures + gold (WE own the truth) — 100% offline,
seeded (20260727), fixture version 2 (hardened 2026-07-28 after v1 saturated)
package: ip-eval/  •  run: `python3 -m ip_eval.cli race <stage>` / `race-all` / `pipeline`

Fixtures v2: 2 synthetic academic docs x 5 formats + adversarial pack
(zero-byte, corrupt PDF, misleading extension, unicode torture, page furniture,
**dedup v2 with forbidden merges**, **split torture with setext/numbered
headings + false-heading trap**) + authored hard cases: **retrieval acronym/
paraphrase/distractor queries**, **graph false-edge traps**, **BibTeX
unicode/braces/missing-year refs**.

## Pipeline scorecard (pipeline-run2.json) — incumbent full chain, wall 0.58s
HARD: s1 1.000 • s2 1.000 • s3 concept F1 0.571 / type-acc 1.000 •
s4 recall@5 0.292 • s7 unique-preserved 1.000 • s8 docx+bibtex 1.000.
ADVISORY: draft readability / section mapping (judgment, not hard-scored).

## Stage races (fixtures v2) — every board now separates

### S1 extraction (run3) — 🏆 pandoc-pypandoc 0.799, ip 0.738
IP has no DOCX reader (f1_docx 0.037); adopt docx2python/pandoc for DOCX
ingest. PDF: IP 0.666, pandoc refuses. mineru needs torch+model weights
(magic-pdf 0.6.1/py3.12) — unraced honestly.

### S2 splitting (run2) — 🏆 ip 0.778, naive 0.628, haystack FAIL
v1 was ip 1.000 — the torture doc (setext, numbered subsections, a
"Results are discussed later…" false-heading trap) costs the incumbent
22 points. Next evo frontier: setext + numbered-heading support.

### S3 concepts (run4) — 🏆 ip 0.705 (type_acc 1.000)
naive 0.379, spacy-nounchunks 0.180, presidio 0.040. Weak spots: recall
(f1 0.571) and metric capture (0.13).

### S4 retrieval (run4) — base tie 0.3564; hard queries separate
| candidate | r@5 (base) | hard r@5 | p50 |
|---|---|---|---|
| haystack/rank-bm25/tantivy | 0.3564 | **1.000** | 146–562ms |
| ⚔️ ip-incumbent | 0.3564 | 0.833 | **53ms** |
| faiss-hashdense | 0.3450 | 0.667 | 199ms |

On acronym/paraphrase/distractor queries the BM25 libraries beat the
incumbent's coverage gate. IP remains 3–10x faster.

### S5 graph (run3) — 🏆 naive/networkx-cooc 0.983, ip 0.971, jaccard 0.956
False-edge traps (similar names, zero co-occurrence) cost the incumbent:
its secondary jaccard≥0.18 edge rule adds false positives. **Build signal:
raise the similarity threshold or require a shared window.**

### S6 drafting (run4) — 🏆 ip 0.908
sumy-textrank-citepost 0.833, naive 0.700, sumy-lsa 0.700 (and
nondeterministic, det=0). Gate = zero fabricated metrics; all survivors pass.

### S7 dedup (run5) — 🏆 naive 0.667 … **real bug found**
| candidate | gate | score | what happened |
|---|---|---|---|
| naive-baseline | PASS | 0.667 | keeps swaps, misses punct-variant merge |
| ⚔️ ip-incumbent | **FAIL** | 0.0 | **false-merges "ranks 12 sentences" vs "ranks 47 sentences"** |
| last30days-dedupe | **FAIL** | 0.0 | same false-merge (0.7 threshold too loose) |
| graphify-dedup | FAIL | 0.0 | entity-label tool, can't merge prose |

**Root cause:** IP's jaccard tokenizer drops 2-char tokens, so a number swap
(12→47) is invisible and the "duplicate" scores 1.0 — evidence destruction.
Priority fix in `server/pipeline.mjs` (`tokenize`/`jaccard`/`combineDrafts`).

### S8 export (run3/run4) — 🏆 ip 1.000 both
DOCX v2 weighted: ip 1.000 > pandoc 0.994 > python-docx 0.846 > docxtpl 0.844.
BibTeX v2 (unicode/braces/missing-year refs): ip 1.000, unopposed.

## App-level races (tranche 3 — P10/A10/S10/F11)

### P10 persistence (run5) — discriminating
| candidate | gate | score | torn reads | lost updates | corrupt file | write p50 |
|---|---|---|---|---|---|---|
| ip-incumbent | PASS | 0.850 | 0 | 0 | throws (no recovery) | 0.93ms |
| sqlite-store | PASS | 0.850 | 0 | 0 | throws (no recovery) | 0.06ms |
| pouchdb-store | PASS | 0.775 | 0 | 0 | **opens but LOSES data** | 0.57ms |
| naive-json | FAIL | 0.0 | 208 | 19 | throws | 0.02ms |

**Build signal:** tmp+rename + update-queue is solid (0 torn / 0 lost). Gap:
corrupt `workspace.json` has no recovery path — IP throws `SyntaxError`.
PouchDB's silent-open-but-data-lost is the worst outcome class; IP at least
fails loudly.

### A10 API (run1) — live probes against running servers
| candidate | gate | score | fails |
|---|---|---|---|
| ip-incumbent | PASS | 0.625 | unknown API route returns SPA (no 404); `{"content": 12345}` → 500; 60MB body not 413 |
| fastapi-naive | FAIL | 0.0 | **malformed JSON → 500** (framework default); no body-size limit |

### S10 security (run1) — IP gate PASS (1.000)
Path-traversal names confined (7 nasties sanitized); planted prompt injection
never surfaces its token. Advisories: the injection line *is* promoted to a
concept (`SYSTEM INSTRUCTION` — concept-matrix pollution); `npm audit`:
0 critical, 1 high.

### F11 frontend (run1) — IP 5/5 (1.000)
Playwright/chromium probes: 9/9 routes render, zero console errors, keyboard
focus visible, no horizontal overflow at 320px/1440px, deep-link refresh
stable. No defects found.

## Deferred contenders (next frontier)
- OCR lane (PaddleOCR/olmOCR/tesseract) — needs image fixtures
- MinerU with model-weight budget; server retrieval via docker lane
- Remaining matrix rows: Stage 4 hybrid fusion, R10 SLO/fault-injection,
  backup/restore, schema migration races — acceptance-gate harnesses exist
  now (persistence/api/security stages are the pattern)

## Files
Package `ip-eval/ip_eval/*.py` + `candidates_extra/` plugins; results
`ip-eval/results-*-run*.json` + `pipeline-run2.json`; fixtures
`ip-eval/fixtures/` (grader-only `fixtures/gold.json`, version 2); incumbent
driver `ip-eval/drivers/ip_driver.mjs`; handoff `ip-eval/HANDOFF.md`.
Cleanup: candidate venvs + uv cache purged after results landed.
