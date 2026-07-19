# evo dashboard: live run notes

Date: 2026-07-19. Signed: codex.

## What actually ran

The container initially had no Python interpreter. I installed the small system
packages `python3`, `python3-flask`, and `python3-portalocker`. The stock entry
point then imported successfully, but its implicit `repo_root()` failed because
the mounted `/workspace/evo-demo` snapshot has no `.git` directory. I used the
dashboard's explicit-root application seam instead:

```text
PYTHONPATH=/workspace/evo-hq/plugins/evo/src python3 -c \
  "from pathlib import Path; from evo.dashboard import create_app; \
   create_app(Path('/workspace/evo-demo')).run(host='127.0.0.1', port=8765)"

 * Serving Flask app 'evo.dashboard'
 * Running on http://127.0.0.1:8765
```

This was the actual Flask dashboard, using the real active run selected by
`/workspace/evo-demo/.evo/meta.json` (`run_0000`). I curled it over TCP, not via
Flask's test client. Werkzeug reported `Werkzeug/2.2.2 Python/3.11.2`.

## Route inventory and real response samples

The inventory below comes from the live app's URL map. Samples are trimmed.
Read routes were called normally. For state-changing routes I used requests
that fail validation, a nonexistent run, or (for runtime) an empty value that
left the already-null settings semantically unchanged.

| Method and route | Observed live response (trimmed) |
|---|---|
| `GET /` | `200 text/html`, 33 KB; `<title>evo : autoresearch</title>` and the top bar's `Best Score` / `Experiments` placeholders. |
| `GET /static/<path:filename>` | `GET /static/app.js` -> `200`, starts `/* evo dashboard */`; `/static/style.css` -> `200`, starts `/* Reset & base */`; `/static/favicon.svg` -> `200 image/svg+xml`, 339 bytes. All had `Cache-Control: no-store, no-cache...`. |
| `GET /api/stats` | `200 {"baseline_score":5.0967,"best_score":0.0067,"committed":3,"frontier":2,"metric":"min","project_name":"Dedup speed demo","total_experiments":3,...}` |
| `GET /api/graph` | `200`; begins `{"next_id":3,"nodes":{"exp_0000":{..."children":["exp_0001","exp_0002"],..."effective_status":"committed"...}}}`. The response enriches the file nodes with `checks`, `effective_status`, lineage fields, and `resolved_backend`. |
| `GET /api/tree` | `200 text/plain`: `root root gates=1` then `exp_0000 committed score=5.0967`, with children `exp_0001 ... 0.0067` and `exp_0002 ... 0.0176`. |
| `GET /api/scatter` | `200 [{"epoch":1,"id":"exp_0000","score":5.0967,"status":"committed"},{..."exp_0001","score":0.0067...},{..."exp_0002","score":0.0176...}]` |
| `GET /api/node/<exp_id>` | `GET .../exp_0001` -> `200`; score `0.0067`, parent `exp_0000`, no children, gate result `true`, five benchmark task scores, hypothesis `replace O(n^2)... with sorted(set(records))`. |
| `POST /api/node/<exp_id>/prune` | `{}` against `exp_0001` -> `400 {"error":"reason is required"}`; graph was not changed. |
| `GET /api/workspace` | `200`; benchmark `python3 {worktree}/bench.py`, backend `worktree`, metric `min`, target `src/dedup.py`, frontier strategy `pareto_per_task`, keyfile present, three node IDs. It also returned provider readiness and environment key *names* (not values). |
| `POST /api/workspace/execution` | `{}` -> `400 {"error":"backend must be one of: worktree, pool, remote"}`. |
| `POST /api/workspace/runtime-env` | Invalid mode -> `400 {"error":"runtime env source mode must be 'all' or 'allow'"}`. |
| `POST /api/workspace/runtime` | JSON `[]` -> `200` workspace summary; because `request.get_json(...) or {}` coerces the empty array to `{}`, it rewrote the existing runtime values as the same `{prepare:null,before_run:null,prefix:null}`. |
| `POST /api/workspace/runtime-variables` | `{"variables":42}` -> `500` HTML Internal Server Error, rather than a JSON validation response. No variables file was written by this failing request. |
| `GET /api/node/<exp_id>/traces` | `exp_0001` -> `200`, five `task_rep_N.json` objects. `rep_2` had `score:0.006728`, `50` calls, `6000` records, and `0.0001345587` seconds/call. |
| `GET /api/node/<exp_id>/traces/<task_id>` | `exp_0001/rep_0` -> `200 {"calls":50,"direction":"min","score":0.010808,"status":"passed",...}`; nonexistent task -> `404` with JSON `null`. |
| `GET /api/node/<exp_id>/log/<path:filename>` | `exp_0001/log/benchmark.log` -> `200`, `seconds: 0.0067`, `X-Log-Size: 16`. `?offset=8` returned the final 8 bytes (` 0.0067\n`); `?tail=2` returned the sole line. |
| `GET /api/node/<exp_id>/logs` | `200 {"attempt":1,"files":[{"name":"benchmark.log","size":16},{"name":"benchmark_err.log","size":0},{"name":"gate_correctness.log","size":24}]}` |
| `GET /api/node/<exp_id>/trackio` | `exp_0001` -> `200 {"url":null}`; this run has no `.trackio_url`. |
| `GET /api/active` | `200 []`; the completed cycle has no active experiments. |
| `GET /api/scratchpad` | `200 text/plain`; status says `metric=min best=0.0067 total=3 3c/0e/0d/0a`; tree marks `exp_0000` and `exp_0001` with the best-path star; frontier contains only `exp_0001`; inherited root correctness gate is shown. |
| `GET /api/annotations` | `200`; nine real annotations, including baseline analysis, pre/post verification JSON, and global findings. One says `sorted(set(records))` achieved about `760x`; another records `dict.fromkeys` as about `2.6x` slower. |
| `GET /api/runs` | `200 [{"active":true,"created":"","id":"run_0000","target":"src/dedup.py"}]` |
| `POST /api/runs/<run_id>/activate` | `no_such_run` -> `404 {"error":"run no_such_run not found"}`. |
| `GET /api/frontier-strategy` | `200`; current/default are `{"kind":"pareto_per_task","params":{"k":5,"task_floor":0.0}}`; registry includes argmax, top-k, epsilon-greedy, softmax, and Pareto-per-task metadata used by the UI. |
| `POST /api/frontier-strategy` | Unknown kind -> `400` naming all five known kinds; config was not changed. |
| `GET /api/frontier` | `200`; `all_ids` contains both leaves but `picks` contains only `exp_0001` rank 1, score `0.0067`; strategy is Pareto-per-task. `?seed=42` echoed seed 42 and produced the same sole pick. |
| `POST /api/direct` | `{}` -> `400 {"error":"text is required"}`; no directive was queued. |

## How `graph.json` drives the UI

`meta.json` chooses `run_0000`; then most experiment views start with that
run's `graph.json`. Its `nodes` dictionary is the canonical topology: `root`
has child `exp_0000`, and `exp_0000.children` contains the two raced siblings.
That exact shape appeared in `/api/tree` and is the input to the JavaScript
timeline layout returned by `/api/graph`.

The same node records supply the visible hypothesis, raw status, score, epoch,
timestamps, parent/children links, gate outcome, benchmark summary, and current
attempt. From these, server helpers compute effective status, best score/spine,
status counts, and raw frontier leaves. Thus the graph's `metric=min` companion
configuration makes `0.0067` the best value, puts the best-spine marker on
`root -> exp_0000 -> exp_0001`, and exposes both leaf nodes as raw frontier
candidates.

`graph.json` is necessary but not sufficient for every panel. `config.json`
adds metric, project/target, backend, and the Pareto strategy. The frontier
endpoint reads each node's latest `attempts/001/outcome.json` for per-task
Pareto ranking, which reduced the two raw leaves to the single pick
`exp_0001`. The node detail endpoint augments graph data with attempt/check
artifacts; trace/log routes read the experiment directories directly; and the
annotation and scratchpad panels also consume `annotations.json` and
`infra_log.json`. The browser therefore receives a public/enriched graph, not
a byte-for-byte echo of `graph.json`.

## What surprised me after running it

- The explicit `create_app(root)` seam works cleanly with a state-only snapshot,
  while the user-facing script cannot start there because `main()` insists on
  discovering a Git root. Serving did work; this was not a loader fallback.
- `/api/graph` performs more filesystem work than its name suggests: the live
  payload added check summaries and resolved backend/effective-lineage fields
  absent from the source JSON.
- `/api/workspace` reports environment variable names and provider readiness.
  It redacted values, but it is a broader operational inventory than an
  experiment-tree dashboard name suggests.
- Runtime-variable normalization assumes `variables` is iterable. A numeric
  value raised a server exception and returned HTML 500, unlike adjacent
  endpoints' deliberate JSON 400 responses.
- Static files and every API response were explicitly non-cacheable. Even the
  completed immutable-looking run is always fetched fresh.
- Pareto-per-task reported two raw frontier IDs but one ranked pick. The UI's
  frontier rail is strategy-authoritative, not simply “all committed leaves.”

