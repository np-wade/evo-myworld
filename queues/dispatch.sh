#!/usr/bin/env bash
# Sequential AI-queue dispatcher for evo-myworld.
# Usage: dispatch.sh <ai> [<ai>...]   ai = poe|feather|hermes|gemini|gemini2|codex|cursor|kimi
# Runs ONE agent at a time (WSL RAM rule). Docker ask-lanes see the repo at
# /workspace/evo-myworld; kimi at /projects/evo-myworld; codex runs on host.
set -uo pipefail

ENVROOT="$HOME/coding/docker-envs"
REPO_HOST="$ENVROOT/projects/evo-myworld"
LOGDIR="$REPO_HOST/queues/logs"; mkdir -p "$LOGDIR"

prompt_for() { # $1=seat name  $2=queue file stem  $3=repo path as agent sees it
  cat <<EOF
You are the "$1" seat of the evo-myworld lab. Work directory: $3
Read, in order: $3/CHARTER.md, $3/FIELD-NOTES.md, $3/queues/$2.md.
Then DO the top unchecked item in that queue file. Rules:
- Write outputs ONLY inside $3/world/$2/ (create it), except: append your
  learnings to $3/FIELD-NOTES.md (dated, signed $1) and tick the finished
  queue item in $3/queues/$2.md by changing "[ ]" to "[x]".
- Do not run long/heavy commands; this is a reading+writing task.
- Cite files you read by path. Be concrete, not generic.
EOF
}

for AI in "$@"; do
  LOG="$LOGDIR/$AI.$(date +%H%M%S).log"
  echo "=== dispatching $AI → $LOG"
  Q="$AI"; [ "$AI" = gemini2 ] && Q=gemini
  case "$AI" in
    poe|hermes|gemini|gemini2)
      (cd "$ENVROOT" && timeout 1500 ./scripts/launch.sh ask "$AI" "$(prompt_for "$AI" "$Q" /workspace/evo-myworld)") >"$LOG" 2>&1 ;;
    feather)
      (cd "$ENVROOT" && timeout 1500 ./scripts/launch.sh ask opencode "$(prompt_for feather feather /workspace/evo-myworld)") >"$LOG" 2>&1 ;;
    cursor)
      (cd "$ENVROOT" && timeout 1500 ./scripts/launch.sh ask cursor "$(prompt_for cursor cursor /workspace/evo-myworld)") >"$LOG" 2>&1 ;;
    codex)
      # host codex has no auth (401) — the docker codex lane holds the login
      (cd "$ENVROOT" && timeout 1500 ./scripts/launch.sh ask codex "$(prompt_for codex codex /workspace/evo-myworld)") >"$LOG" 2>&1 ;;
    kimi)
      timeout 1500 docker exec kimi-cli kimi --print -p "$(prompt_for kimi kimi /projects/evo-myworld)" >"$LOG" 2>&1 ;;
    *) echo "unknown ai: $AI" | tee "$LOG"; continue ;;
  esac
  echo "--- $AI exit=$? (log: $LOG)"
done
