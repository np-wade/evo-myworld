# HANDOFF — ip-eval final round (2026-07-28, LLM-unblocked + convert stage)

Supersedes the pause point (`PAUSE-2026-07-28.md`) for the candidate-expansion
tranche. Suite root: `~/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval`.
Selftest green at handoff. No stray processes or docker containers. Nothing committed.

## What this round did

1. **Validated the 4 paused defects** — annoy (0.3564, retrieval tie), turso-store
   (0.5, 20 lost updates exposed), opendal-store (0.85, ties top), hayhooks-api
   (0.5714, gate PASS), nemo-gliner (0.4896 solo, gate PASS — see caveats).
2. **Unblocked the LLM-bound candidates** via Ollama Cloud
   (OpenAI-compatible `https://ollama.com/v1`, model `gpt-oss:20b`, key in
   `~/.config/ollama-cloud/api_key` — chmod 600, never in the repo; override model
   with env `IP_EVAL_LLM_MODEL`). New files:
   - `ip_eval/candidates_extra/llm_retrieval.py` — hypermem, wikichat, suql,
     local-deep-researcher (suql spins `postgres:16-alpine` in docker, atexit teardown)
   - `ip_eval/candidates_extra/llm_graph.py` — hypermem-graph, ontocast-graph
   - `ip_eval/candidates_extra/llm_concepts.py` — fasttext-classify, ontocast-concepts
   - `ip_eval/candidates_extra/llm_drafting.py` — storm-draft, wikichat-draft
   All LLM clients: stdlib urllib, key from env else the file above, 120s timeout.
3. **Added the `convert` stage** (S9: ingress 2 docs × 5 formats → canonical, token
   F1; egress canonical → docx/html/pdf, validity + fidelity; score = 0.6·ingress +
   0.4·egress; gate ingress F1 ≥ 0.3). Wiring: surgical additions to `race.py`,
   `oracle.py`, `cli.py`; candidates in `ip_eval/candidates_extra/convert.py`
   (ip-incumbent, pandoc-convert via pypandoc-binary, docx2python, mineru,
   stirling-pdf via docker, olmocr honest-unavailable/no-GPU).
   `oracle.py` also gained a stdlib ObjStm-aware PDF text extractor.
4. **Charts**: `make_charts.py` renders 16 per-stage leaderboard PNGs (8 rotating
   styles + champions board) to the Windows desktop
   (`/mnt/c/Users/npwad/OneDrive/Desktop/ip-eval-charts`). Re-run: `python3 make_charts.py`.
5. Earlier deliverable: `make_infographic.py` → `ip-eval-results-2026-07-28.html/.pdf`
   (PDF also on the desktop). NOTE: predates this round — regenerate to include
   convert + LLM candidates.

## Final leaderboards (latest run per stage, on disk)

| Stage | Champion | Score | IP-incumbent |
|---|---|---|---|
| convert (run2) | pandoc-convert | 0.8319 | 0.5761 |
| extract (run3) | pandoc-pypandoc | 0.7899 | 0.7783 |
| split (run4) | **ip-incumbent** | 0.7778 | 👑 |
| concepts (run8) | **ip-incumbent** | 0.7053 | 👑 |
| tabilify (run2) | **ip-incumbent** | 0.6141 | 👑 |
| retrieval (run7) | 9-way tie: IP, librer, ragbits-rrf, rank-bm25, tantivy-py, annoy, haystack-bm25, suql, local-deep-researcher | 0.3564 | tied 👑 |
| graph (run5) | graphify-graph / naive / networkx | 0.9833 | 0.9714 |
| drafting (run6) | wikichat-draft ⚠ det=0 | 1.0 | 0.9077 |
| dedup (run6) | **ip-incumbent** | 1.0 | 👑 |
| export_docx (run4) | **ip-incumbent** | 1.0 | 👑 |
| export_bibtex (run5) | **ip-incumbent** | 1.0 | 👑 |
| persistence (run7) | IP = sqlite = opendal | 0.85 | tied 👑 |
| api (run3) | **ip-incumbent** | 0.625 | 👑 |
| security (run2) | **ip-incumbent** | PASS | 👑 |
| frontend (run1) | ip-frontend-playwright | 5/5 | 👑 |

New-candidate scores (all real, deterministic unless noted):
suql 0.3564 (LLM SQL over live postgres) · local-deep-researcher 0.3564 ·
wikichat 0.3337 · hypermem 0.2995 · ontocast-graph 0.7867 · hypermem-graph 0.7467 ·
fasttext-classify 0.5442 (unsupervised skipgram on fixture text, nearest-centroid
typing) · wikichat-draft 1.0 ⚠ · pandoc-convert 0.8319.

## Caveats / loose ends (each is a one-race job)

- **wikichat-draft 1.0 UNVERIFIED** — no LLM response caching; failed the
  determinism rep (det=0). Add caching like llm_retrieval.py has, re-run `race drafting`.
- **ontocast-concepts + storm-draft crashed** both races (gate FAIL, no score).
  Never produced a working number.
- **nemo-gliner**: green solo (run6, 0.4896), crashed in run7/run8 under parallel
  CPU load. Evidence points to load-induced timeout, not a code regression — confirm
  with one clean `race concepts`.
- **stirling-pdf**: double bug FOUND AND FIXED (docker `SECURITY_ENABLELOGIN=false`;
  ObjStm font refs in oracle's PDF extractor). Probe-verified egress 0.999, but the
  confirming full race was killed by user request — results-convert-run2.json still
  shows the old zeros. `python3 -m ip_eval.cli race convert` (~7 min, MinerU-bound)
  makes it official.
- LLM graph candidates score below the 0.9833 ceiling by construction: gold edges
  ARE section co-occurrence; LLM semantic edges are sparser (high precision, low
  recall). Honest behavior, not a bug.
- Old same-named honest-unavailable stubs (packs 03/04/06/07) still appear in
  results alongside the new working candidates — cosmetic, kept for comparability.

## Genuine IP-incumbent findings (new this round)

- **IP has no DOCX reader**: `extractDocument` (pipeline.mjs:189) lacks a docx
  branch; .docx falls through to UTF-8 zip decode → F1 0.037 (convert run2,
  extract run3 agree). pandoc-convert now demonstrably out-converts IP overall
  (0.8319 vs 0.5761; IP also has no html/pdf egress writer).
- Drafting crown lost: paperspine-draft 0.9325 (and wikichat-draft pending
  verification) > IP 0.9077. Graph: 0.9833 co-occurrence trio > IP 0.9714.

## Commands

```bash
cd ~/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval
python3 -m ip_eval.cli selftest          # must stay green
python3 -m ip_eval.cli list              # ~100+ candidates
python3 -m ip_eval.cli race <stage>      # now includes: convert
python3 make_charts.py                   # regenerate desktop charts
python3 make_infographic.py              # regenerate HTML report (then re-print PDF)
```

Environment for LLM candidates: key auto-read from `~/.config/ollama-cloud/api_key`;
`IP_EVAL_LLM_MODEL` to switch models (default gpt-oss:20b).

## Not done (deliberately)

- Tranche-4 doc sweep from the pause point: `racetrack/results/ip-suite.md`,
  INDEX.md T6 row, `information-processer/RACETRACK-RESULTS-HANDOFF.md`,
  dated FIELD-NOTES.md entry — still pending, now SHOULD include this round.
- Java lane (opennlp ×2, jabref), Rust lane (ruvector, filecache, zeroclaw —
  corpus repo missing `crates/zeroclaw-runtime/src/firmware`), undoc shim rebuild,
  trivy/nuclei binary installs, olmOCR (needs GPU), PaddleOCR/tesseract image lane.
