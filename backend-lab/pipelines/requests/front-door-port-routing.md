# race: front-door-port-routing
seat: backend-lab
question: how do we resolve the 8787 (information-processer vs witt-link-server) and 8080 (evo dashboard vs localai sidecar) collisions — hardcoded ports, a reverse proxy front door, or a programmable proxy?
metric: min — added p95 ms per hop at 200 req/s against two stub backends behind the candidate router
gate: 0 misroutes — every /api/* request reaches the information-processer backend and every dashboard request reaches evo (distinguishing response tokens), and contract tests A11/A12 pass (each port has exactly one owner)

## candidate: hardcoded-ports-incumbent
source: projects/witt-link-server/config.toml (port = 8787 at line 6, sidecars :8788-:8793, :8080 at line 50) + projects/information-processer/vite.config.js:10 + projects/evo-desktop/launch-dashboard.sh:12
approach: incumbent — keep per-app hardcoded defaults, resolve collisions by renumbering one claimant. Zero added latency, zero new moving parts; cost is every consumer editing config when ports move.

## candidate: nginx-front-door
source: nginx_nginx/code (library repo, verified)
approach: one nginx reverse proxy owns :8787 and :8080; path-prefix routing dispatches /api/* to information-processer and the rest to the dashboard/witt backends. Config-only, system package, no builds.

## candidate: mitmproxy-programmable
source: mitmproxy_mitmproxy (library repo, verified)
approach: a small mitmproxy addon script does programmatic dispatch (and doubles as the passive hop observer for the B3 trace-stitching ground truth). More flexible routing logic, higher per-hop cost than nginx.
