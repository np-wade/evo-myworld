#!/usr/bin/env bash
# Run one race request through the evo harness. Usage: run-race.sh <request.md>
set -uo pipefail
REQ="${1:?usage: run-race.sh <request.md>}"
REPO="$HOME/coding/docker-envs/projects/evo-myworld"
SLUG=$(basename "$REQ" .md)
RACEDIR="$HOME/coding/docker-envs/projects/evo-races/$SLUG"
RESULT="$REPO/racetrack/results/$SLUG.md"
mkdir -p "$REPO/racetrack/results" "$REPO/racetrack/requests/done" "$(dirname "$RACEDIR")"

[ -f "$RESULT" ] && { echo "race $SLUG already has a result, skipping"; exit 0; }

mkdir -p "$RACEDIR" && cd "$RACEDIR"
git init -q 2>/dev/null; git config user.name np-wade; git config user.email np.wade@pm.me

timeout 3000 claude --dangerously-skip-permissions -p "You are the race steward on a memory-limited WSL box (max 2 parallel experiments, small benchmarks only).
Race request (verbatim):
---
$(cat "$REQ")
---
Library corpus on host: ~/coding/docker-envs/filing-cabinet/library-base/repos
In THIS empty repo ($RACEDIR):
1. Read each candidate's cited source for real. Build a minimal fair arena: a baseline module, bench.py printing a single scored line per the request's metric, and the stated gate as an executable check.
2. Use /evo:discover (seed it fully so it asks nothing) then /evo:optimize — but instead of free exploration, implement EACH candidate from the request as its own experiment (one branch per candidate, faithful to the cited approach). One round, then stop.
3. Write $RESULT in markdown: table of candidate|source|score|gate-status, the winner, WHY it won (1 paragraph), and full citations. If a candidate can't be implemented faithfully, record it as 'scratched' with the reason.
4. Do not touch anything outside $RACEDIR except writing $RESULT." >"$RACEDIR/steward.log" 2>&1
RC=$?

if [ -f "$RESULT" ]; then
  mv "$REQ" "$REPO/racetrack/requests/done/$(basename "$REQ")"
  echo "race $SLUG complete → $RESULT"
else
  echo "race $SLUG FAILED (rc=$RC) — request left in place, log: $RACEDIR/steward.log"
  exit 1
fi
