#!/usr/bin/env bash
# The Bench — run two versions of something, look at the difference.
# Usage:
#   experiment.sh "<cmd A>" "<cmd B>"     compare outputs + timing of two commands
#   experiment.sh --funcs <file>          list the functions in one source file
#   experiment.sh --loop <seat>           run a seat's experiment.env, append trail
set -uo pipefail
REPO="$HOME/coding/docker-envs/projects/evo-myworld"

funcs() { # crude but dependency-free: python defs / rust fns
  local f="$1"
  [ -f "$f" ] || { echo "no such file: $f"; return 1; }
  case "$f" in
    *.py) grep -nE '^[[:space:]]*(def|class) ' "$f" || echo "(no defs found)";;
    *.rs) grep -nE '^[[:space:]]*(pub[[:space:]]+)?(async[[:space:]]+)?fn |^[[:space:]]*(pub[[:space:]]+)?(struct|enum|trait) ' "$f" || echo "(no items found)";;
    *) grep -nE '^[[:alpha:]].*[({]' "$f" | head -40;;
  esac
}

run_one() { # $1=label $2=cmd  → echoes to $OUT_$1 file, prints header
  local label="$1" cmd="$2" out="$3"
  local t0 t1
  t0=$(date +%s.%N)
  timeout 300 bash -c "$cmd" >"$out" 2>&1; local rc=$?
  t1=$(date +%s.%N)
  printf '%s: exit=%d  time=%.2fs  (%d lines)\n' "$label" "$rc" "$(echo "$t1-$t0"|bc)" "$(wc -l <"$out")"
}

case "${1:-}" in
  --funcs) shift; funcs "$1"; exit $? ;;
  --loop)
    SEAT="$2"; EE="$REPO/world/$SEAT/experiment.env"
    [ -f "$EE" ] || { echo "no experiment.env for $SEAT"; exit 0; }
    BASE_CMD=""; NEW_CMD=""; NOTE=""; . "$EE"
    A=$(mktemp); B=$(mktemp)
    run_one A "$BASE_CMD" "$A" >/dev/null; run_one B "$NEW_CMD" "$B" >/dev/null
    if diff -q "$A" "$B" >/dev/null; then VERDICT=same; else VERDICT=different; fi
    echo "$(date '+%F %T') · $SEAT · $VERDICT · ${NOTE:-}" >> "$REPO/bench/trail.md"
    rm -f "$A" "$B"; echo "$SEAT: $VERDICT"; exit 0 ;;
  "" ) sed -n '2,20p' "$REPO/bench/BENCH.md"; exit 0 ;;
esac

# two-command compare
A=$(mktemp); B=$(mktemp)
echo "── running A (baseline) ─────────────────────────"
run_one A "$1" "$A"
echo "── running B (your version) ─────────────────────"
run_one B "$2" "$B"
echo "── A output ─────────────────────────────────────"; cat "$A"
echo "── B output ─────────────────────────────────────"; cat "$B"
echo "── diff (A → B) ─────────────────────────────────"
if diff -u "$A" "$B" >/tmp/.bench_diff 2>&1; then echo "(identical output)"; else cat /tmp/.bench_diff; fi
rm -f "$A" "$B" /tmp/.bench_diff
