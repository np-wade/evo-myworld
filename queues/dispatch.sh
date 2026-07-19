#!/usr/bin/env bash
# Sequential AI-queue dispatcher for evo-myworld. v2 — call-shape aware.
# Usage: dispatch.sh <ai> [<ai>...]   ai = poe|feather|hermes|gemini|gemini2|codex|cursor|kimi
#
# v2 changes (2026-07-19, "think about the way it's getting called"):
# - Per-seat prompt shapes: small-context seats (feather, poe) get a LIGHT
#   call — only their queue item + the tail of FIELD-NOTES, not the whole
#   doc stack. FIELD-NOTES grows every cycle; full reads will eventually
#   choke every seat, so everyone reads only the last ~150 lines.
# - Verification: a call only counts if the seat actually ticked a queue
#   item. Exit 0 with no tick = soft-fail.
# - Attempts + escalation: 2 consecutive fails on the same item → item is
#   marked ESCALATED (ticked so the loop stops hammering it), logged to
#   queues/escalations.md for a stronger seat/orchestrator.
# - Poe model fallback chain: qwen3.7-max → minimax-m3-el (server errors
#   are model-side some days; -t variants are text-only, never agent).
set -uo pipefail

ENVROOT="$HOME/coding/docker-envs"
REPO_HOST="$ENVROOT/projects/evo-myworld"
LOGDIR="$REPO_HOST/queues/logs"; ATT="$REPO_HOST/queues/.attempts"
mkdir -p "$LOGDIR" "$ATT"

open_count() { awk 'BEGIN{c=0}/\[ \]/{c++}END{print c}' "$1" 2>/dev/null || echo 0; }

full_prompt() { # $1=seat $2=queue-stem $3=repo path as agent sees it
  cat <<EOF
You are the "$1" seat of the evo-myworld lab. Work directory: $3
Context (read in this order, nothing more):
1. $3/CHARTER.md
2. the LAST 150 lines only of $3/FIELD-NOTES.md (it is long; do not read it all)
3. $3/queues/$2.md — your queue
Then DO the top unchecked "[ ]" item. Rules:
- Write outputs ONLY inside $3/world/$2/ (create it) or, for race filings,
  $3/racetrack/requests/ per $3/racetrack/RACETRACK.md.
- Append learnings to $3/FIELD-NOTES.md (dated, signed $1).
- REQUIRED: tick the finished item in $3/queues/$2.md ("[ ]" -> "[x]").
  If you cannot finish it, write one line explaining why under the item
  and leave it unticked.
- No long/heavy commands. Cite files you read by path. Be concrete.
EOF
}

light_prompt() { # $1=seat $2=queue-stem $3=repo path — for small-context seats
  local ITEM
  ITEM=$(awk '/\[ \]/{f=1} f{print} f&&/^[0-9]+\. \[/&&++c==2{exit}' "$REPO_HOST/queues/$2.md" | head -20)
  cat <<EOF
You are the "$1" seat of the evo-myworld lab. Work directory: $3
Your single task (from $3/queues/$2.md):
$ITEM
Do exactly this task. Output files go in $3/world/$2/ (create it); race
filings go in $3/racetrack/requests/ (format: $3/racetrack/RACETRACK.md).
For lab context read ONLY the last 60 lines of $3/FIELD-NOTES.md.
When done: append 1-2 learnings to FIELD-NOTES.md (dated, signed $1) and
tick the item in $3/queues/$2.md ("[ ]" -> "[x]"). Keep every file you
read small — you have a small context window.
EOF
}

run_seat() { # $1=AI  → returns lane exit code
  local AI=$1 Q=$2 LOG=$3
  case "$AI" in
    hermes|gemini|gemini2|cursor)
      (cd "$ENVROOT" && AGY_PRINT_TIMEOUT=20m timeout 1500 ./scripts/launch.sh ask "$AI" "$(full_prompt "$AI" "$Q" /workspace/evo-myworld)") >"$LOG" 2>&1 ;;
    codex)
      (cd "$ENVROOT" && timeout 1500 ./scripts/launch.sh ask codex "$(full_prompt codex "$Q" /workspace/evo-myworld)") >"$LOG" 2>&1 ;;
    kimi)
      timeout 1500 docker exec kimi-cli kimi --print -p "$(full_prompt kimi "$Q" /projects/evo-myworld)" >"$LOG" 2>&1 ;;
    feather)
      (cd "$ENVROOT" && timeout 1500 ./scripts/launch.sh ask opencode "$(light_prompt feather "$Q" /workspace/evo-myworld)") >"$LOG" 2>&1 ;;
    poe)
      (cd "$ENVROOT" && timeout 1200 ./scripts/launch.sh ask poe "$(light_prompt poe "$Q" /workspace/evo-myworld)") >"$LOG" 2>&1
      local rc=$?
      if [ $rc -ne 0 ] || grep -q 'Internal server error' "$LOG"; then
        echo "--- poe primary failed, falling back to minimax-m3-el" >>"$LOG"
        (cd "$ENVROOT" && POE_MODEL=empiriolabs-ai/minimax-m3-el timeout 1200 ./scripts/launch.sh ask poe "$(light_prompt poe "$Q" /workspace/evo-myworld)") >>"$LOG" 2>&1
      fi ;;
    *) echo "unknown ai: $AI" >"$LOG"; return 2 ;;
  esac
}

for AI in "$@"; do
  Q="$AI"; [ "$AI" = gemini2 ] && Q=gemini
  QF="$REPO_HOST/queues/$Q.md"
  BEFORE=$(open_count "$QF")
  [ "$BEFORE" -eq 0 ] && { echo "=== $AI: queue empty, skipping"; continue; }
  LOG="$LOGDIR/$AI.$(date +%H%M%S).log"
  echo "=== dispatching $AI → $LOG"
  run_seat "$AI" "$Q" "$LOG"; RC=$?
  AFTER=$(open_count "$QF")
  if [ "$AFTER" -lt "$BEFORE" ]; then
    echo 0 >"$ATT/$Q"
    echo "--- $AI OK (ticked an item, rc=$RC)"
  else
    N=$(( $(cat "$ATT/$Q" 2>/dev/null || echo 0) + 1 )); echo "$N" >"$ATT/$Q"
    echo "--- $AI SOFT-FAIL (no item ticked, rc=$RC, attempt $N)"
    if [ "$N" -ge 2 ]; then
      ITEM_LINE=$(grep -n '\[ \]' "$QF" | head -1 | cut -d: -f1)
      [ -n "$ITEM_LINE" ] && sed -i "${ITEM_LINE}s/\[ \]/[x] ESCALATED/" "$QF"
      { echo "- $(date +%F' '%T) seat=$AI queue=$Q: item escalated after $N failed attempts (last log: $LOG)"; } >> "$REPO_HOST/queues/escalations.md"
      echo 0 >"$ATT/$Q"
      echo "--- $AI item ESCALATED to queues/escalations.md"
    fi
  fi
done
