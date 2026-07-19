#!/usr/bin/env bash
# The judge. Usage: judge.sh [seat...]   (no args = every seat with a judge.env)
# Phase 0 baseline (original code in this env) → phase 1 works-gate →
# phase 2 true score → append rows to harness/LEDGER.md.
set -uo pipefail
REPO="$HOME/coding/docker-envs/projects/evo-myworld"
EVOHQ="$HOME/coding/docker-envs/projects/evo-hq"
LOGS="$REPO/harness/logs"; mkdir -p "$LOGS"
LEDGER="$REPO/harness/LEDGER.md"
TS=$(date '+%F %T')

[ -f "$LEDGER" ] || printf '# Proving-ground ledger (append-only)\n\n| when | seat | baseline | works | score | note |\n|---|---|---|---|---|---|\n' > "$LEDGER"

# ---- Phase 0: baseline — the original code, run in this environment
BLOG="$LOGS/baseline.$(date +%H%M%S).log"
BASE=OK
( cd "$EVOHQ/sdk/python" && timeout 300 uv run --no-project --with pytest pytest -q test/ ) >"$BLOG" 2>&1 || BASE=FAIL
evo --version >>"$BLOG" 2>&1 || BASE=FAIL
BASENOTE=$(tail -1 "$BLOG" | cut -c1-60)
echo "baseline: $BASE ($BASENOTE)"

SEATS=("$@")
if [ ${#SEATS[@]} -eq 0 ]; then
  for d in "$REPO"/world/*/judge.env; do [ -e "$d" ] && SEATS+=("$(basename "$(dirname "$d")")"); done
fi

for SEAT in "${SEATS[@]:-}"; do
  [ -n "$SEAT" ] || continue
  JE="$REPO/world/$SEAT/judge.env"
  if [ ! -f "$JE" ]; then
    echo "| $TS | $SEAT | $BASE | n/a | - | no judge.env declared |" >> "$LEDGER"
    echo "$SEAT: no judge.env"; continue
  fi
  DESC=""; VERIFY_CMD=""; SCORE_CMD=""; METRIC=""
  . "$JE"
  SLOG="$LOGS/$SEAT.$(date +%H%M%S).log"
  WORKS=FAIL; SCORE="-"
  if [ -n "$VERIFY_CMD" ]; then
    ( cd "$REPO" && timeout 600 bash -c "$VERIFY_CMD" ) >"$SLOG" 2>&1 && WORKS=OK
  else
    echo "empty VERIFY_CMD" >"$SLOG"
  fi
  if [ "$WORKS" = OK ] && [ -n "$SCORE_CMD" ]; then
    SCORE=$( ( cd "$REPO" && timeout 600 bash -c "$SCORE_CMD" ) 2>>"$SLOG" | tail -1 | grep -oE '[0-9]+([.][0-9]+)?' | tail -1 )
    [ -n "$SCORE" ] || SCORE="unparseable"
  fi
  NOTE="${DESC:-} ${METRIC:+[$METRIC]}"
  echo "| $TS | $SEAT | $BASE | $WORKS | $SCORE | $(echo "$NOTE" | cut -c1-70) |" >> "$LEDGER"
  echo "$SEAT: works=$WORKS score=$SCORE (log: $SLOG)"
done
