#!/usr/bin/env bash
# The standing lab loop: refill queues → dispatch every seat with open work
# (sequentially) → run pending races → commit/push → sleep → repeat.
# Stop: touch STOPLAB in repo root (honored between steps).
# Status: one-line heartbeat every minute in racetrack/STATUS + lab-loop.log.
# Tunables live-reload each cycle from lab-tunables.env.
set -uo pipefail
REPO="$HOME/coding/docker-envs/projects/evo-myworld"
cd "$REPO"
LOCK="$REPO/queues/.lab-loop.lock"
exec 9>"$LOCK"; flock -n 9 || { echo "lab-loop already running"; exit 1; }
LOG="$REPO/lab-loop.log"
SEATS_DEFAULT="feather hermes gemini gemini2 cursor codex poe kimi"

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
status(){ echo "[$(date '+%F %T')] $*" > "$REPO/racetrack/STATUS"; }

# heartbeat: one line per minute (Nicholas's standing preference)
( while sleep 60; do
    m=$(awk '/MemAvailable/{printf "%.1fG",$2/1048576}' /proc/meminfo)
    s=$(awk '/SwapFree/{printf "%.1fG",$2/1048576}' /proc/meminfo)
    echo "[$(date '+%F %T')] heartbeat: $(cat "$REPO/racetrack/STATUS" 2>/dev/null | cut -c1-120) | MemAvail=$m SwapFree=$s" >> "$LOG"
  done ) & HB=$!
trap 'kill $HB 2>/dev/null' EXIT

CYCLE=0
while :; do
  CYCLE=$((CYCLE+1))
  [ -f STOPLAB ] && { log "STOPLAB present — stopping."; break; }
  CYCLE_SLEEP=900; MAX_RACES=2; SEATS="$SEATS_DEFAULT"
  [ -f lab-tunables.env ] && . ./lab-tunables.env
  log "=== cycle $CYCLE start (seats: $SEATS, max races: $MAX_RACES)"

  status "cycle $CYCLE: refilling queues"
  ./queues/refill.sh >>"$LOG" 2>&1

  for SEAT in $SEATS; do
    [ -f STOPLAB ] && break
    Q="queues/$SEAT.md"; [ "$SEAT" = gemini2 ] && Q="queues/gemini.md"
    grep -q '\[ \]' "$Q" 2>/dev/null || continue
    status "cycle $CYCLE: seat $SEAT working"
    ./queues/dispatch.sh "$SEAT" >>"$LOG" 2>&1
  done

  RACES=0
  for REQ in racetrack/requests/*.md; do
    [ -e "$REQ" ] || break
    [ -f STOPLAB ] && break
    [ "$RACES" -ge "$MAX_RACES" ] && break
    status "cycle $CYCLE: racing $(basename "$REQ" .md)"
    ./racetrack/run-race.sh "$REQ" >>"$LOG" 2>&1 && RACES=$((RACES+1))
  done

  status "cycle $CYCLE: committing"
  git add -A >>"$LOG" 2>&1
  git commit -qm "lab-loop cycle $CYCLE: seat outputs, race results" >>"$LOG" 2>&1 && git push -q origin main >>"$LOG" 2>&1
  log "=== cycle $CYCLE done ($RACES races). Sleeping ${CYCLE_SLEEP}s."
  status "sleeping until next cycle ($(date -d "+${CYCLE_SLEEP} seconds" '+%T' 2>/dev/null))"
  for _ in $(seq $((CYCLE_SLEEP/30))); do [ -f STOPLAB ] && break; sleep 30; done
done
status "lab loop stopped"
