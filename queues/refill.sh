#!/usr/bin/env bash
# Refill seat queues with library-exploration items when a seat has no
# unchecked work. Topics come from graphify TOPICS.md; each refill hands the
# seat a rotating batch of repos from its assigned topics.
set -uo pipefail
REPO="$HOME/coding/docker-envs/projects/evo-myworld"
TOPICS="$HOME/coding/docker-envs/projects/graphify-app/data/graphs/TOPICS.md"
STATE="$REPO/queues/.refill-state"; mkdir -p "$STATE"

# seat → its topics (from TOPICS.md section names), matched to seat strengths
declare -A SEAT_TOPICS=(
  [kimi]="web-frontend graphics-media"
  [codex]="llm-agents cli-tooling"
  [cursor]="editors-ide web-frontend"
  [gemini]="machine-learning observability"
  [hermes]="web-backend database-storage"
  [poe]="parsing-compilers serialization"
  [feather]="caching text-search"
  [claude-backend]="database-storage networking"
)

repos_for_topic() { # extract "- **owner__repo**" lines under "## <topic> ("
  awk -v t="## $1 (" 'index($0,t)==1{f=1;next} /^## /{f=0} f&&/^- \*\*/{gsub(/^- \*\*|\*\*.*$/,"");print}' "$TOPICS"
}

for SEAT in "${!SEAT_TOPICS[@]}"; do
  Q="$REPO/queues/$SEAT.md"
  [ -f "$Q" ] || continue
  grep -q '^[0-9]*\. \[ \]' "$Q" && continue   # still has open work
  CURSOR_F="$STATE/$SEAT.idx"; IDX=$(cat "$CURSOR_F" 2>/dev/null || echo 0)
  BATCH=$(for t in ${SEAT_TOPICS[$SEAT]}; do repos_for_topic "$t"; done | sort -u | awk -v s="$IDX" 'NR>s && NR<=s+3')
  [ -z "$BATCH" ] && { echo 0 >"$CURSOR_F"; continue; }  # wrap around
  echo $((IDX+3)) >"$CURSOR_F"
  N=$(grep -cE '^[0-9]+\. \[' "$Q" || echo 0)
  {
    echo "$((N+1)). [ ] LIBRARY EXPLORATION (auto-refill $(date +%F)): explore these"
    echo "   corpus repos (at /library/repos/<name> in lanes, ~/coding/docker-envs/filing-cabinet/library-base/repos on host):"
    echo "$BATCH" | sed 's/^/   - /'
    echo "   Find ONE capability done notably well (or notably differently) across"
    echo "   ≥2 of them (or 1 of them + 1 graph-library slice). Then FILE A RACE:"
    echo "   write racetrack/requests/<slug>.md per racetrack/RACETRACK.md, with"
    echo "   real citations. Also append 2-3 findings to FIELD-NOTES.md (signed)."
    echo "   Small benchmarks only. If the repos are unsuitable, say why in"
    echo "   FIELD-NOTES and tick this item anyway."
  } >> "$Q"
  echo "refilled $SEAT (repos idx $IDX..$((IDX+3)))"
done
