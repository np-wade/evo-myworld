#!/usr/bin/env bash
# selfdev/cycle-review.sh — ONE bounded self-refinement per lab cycle.
# Ported from raven's evolver funnel (see selfdev/SELFDEV.md for the map):
#   gather last cycle's evidence (= failing trajectories, raven diagnose ①)
#   -> no-op if nothing new (= zero-hit preflight ③, production.py)
#   -> one bounded claude -p call picks ONE small refinement (= design ②, n=1)
#   -> edits allowed ONLY in queues/*.md, selfdev/**, FIELD-NOTES.md;
#      anything else is reverted (= applier/path_guard.py whitelist + revert)
#   -> everything logged append-only to selfdev/CHANGELOG.md (= node ledger).
# The measurement surface (lab-loop.sh, dispatch.sh, refill.sh, bench/,
# racetrack/ scripts, race results) is the immutable kernel — never edited
# here. Out-of-whitelist ideas become selfdev/proposals/*.md for the
# orchestrator. Safe to run any time: flock'd, timeout'd, no-ops honored.
set -uo pipefail
REPO="$HOME/coding/docker-envs/projects/evo-myworld"
SD="$REPO/selfdev"
STATE="$SD/.state"; LOGS="$SD/logs"
mkdir -p "$STATE" "$LOGS" "$SD/proposals"
exec 9>"$STATE/.lock"; flock -n 9 || { echo "cycle-review already running"; exit 0; }
cd "$REPO" || exit 1
[ -f STOPLAB ] && { echo "STOPLAB present — skipping selfdev review"; exit 0; }

TIMEOUT="${SELFDEV_TIMEOUT:-600}"
MODEL_ARGS=(); [ -n "${SELFDEV_MODEL:-}" ] && MODEL_ARGS=(--model "$SELFDEV_MODEL")
STAMP=$(date '+%Y%m%d-%H%M%S'); TS=$(date '+%F %T')
LOG="$LOGS/cycle-review-$STAMP.log"
CHANGELOG="$SD/CHANGELOG.md"
[ -f "$CHANGELOG" ] || printf '# selfdev CHANGELOG (append-only ledger)\n' > "$CHANGELOG"

# ---- ① gather evidence (last cycle's "failing trajectories") ----------------
EV="$STATE/evidence.txt"; SEEN="$STATE/seen-results.txt"; touch "$SEEN"
NEWSEEN="$STATE/seen-results.new"; : > "$NEWSEEN"
{
  echo "== lab-loop.log tail (heartbeats stripped) =="
  grep -v ' heartbeat: ' lab-loop.log 2>/dev/null | tail -n 60
  echo; echo "== bench/trail.md tail =="
  tail -n 20 bench/trail.md 2>/dev/null || echo "(no trail yet)"
  echo; echo "== NEW racetrack results (unseen by selfdev) =="
  for f in racetrack/results/*.md; do
    [ -e "$f" ] || { echo "(none yet)"; break; }
    grep -qxF "$f" "$SEEN" && continue
    echo "--- $f"; head -c 3000 "$f"; echo; echo "$f" >> "$NEWSEEN"
  done
  echo; echo "== queues/escalations.md tail =="
  tail -n 30 queues/escalations.md 2>/dev/null || echo "(no escalations yet)"
} > "$EV" 2>/dev/null

# ---- ③ preflight: unchanged evidence = inert candidate = free no-op ---------
FP=$(sha256sum "$EV" | cut -c1-16)
if [ "$FP" = "$(cat "$STATE/last-fingerprint" 2>/dev/null)" ]; then
  echo "[$TS] cycle-review: no new evidence (fp $FP) — no-op, no LLM call" | tee -a "$LOG"
  rm -f "$NEWSEEN"; exit 0
fi

# ---- snapshot dirty paths for the path guard --------------------------------
BEFORE="$STATE/dirty-before.txt"
git status --porcelain=v1 2>/dev/null | awk '{print $NF}' | sort > "$BEFORE"

# ---- ② one bounded driver call: pick + apply ONE small refinement -----------
PROMPT=$(cat <<EOF
You are the selfdev reviewer of the evo-myworld lab (repo: $REPO).
Read selfdev/SELFDEV.md sections 2-3 for the rules, then, from ONLY the
evidence below, pick THE SINGLE highest-leverage refinement and act:

A) If it is a small edit INSIDE the whitelist — queues/*.md (fix/rewrite/
   re-route a queue item or escalated item, or fix a racetrack request
   filing referenced by a queue item... but queue .md files only),
   selfdev/proposals/, or FIELD-NOTES.md (consolidate noise; never delete
   standing rules/gotchas) — apply it as ONE small edit.
B) If the right fix lives OUTSIDE the whitelist (dispatch.sh prompts,
   lab-loop.sh, gate code, bench/racetrack scripts): do NOT edit it.
   Instead write selfdev/proposals/$STAMP-<slug>.md containing: the problem,
   the evidence lines, and the exact proposed diff for the orchestrator.
C) If the evidence shows nothing actionable, make no edit.

Then in ALL cases append one entry to selfdev/CHANGELOG.md, exactly:
## $TS — <one-line what (or "no change adopted")>
- why: <one line>
- evidence: <the specific log/result lines that justified it>
- check: <how the next cycle's evidence will show whether it worked>

Hard rules: at most ONE refinement. Only edit files under queues/*.md,
selfdev/, FIELD-NOTES.md. Never run heavy commands. Never mark your own
change "adopted" — adoption is judged by next cycle's evidence.

=== EVIDENCE (this cycle) ===
$(head -c 12000 "$EV")
EOF
)

echo "[$TS] cycle-review: new evidence (fp $FP) — running bounded claude call (timeout ${TIMEOUT}s)" | tee -a "$LOG"
CL_BEFORE=$(wc -c < "$CHANGELOG")
timeout "$TIMEOUT" claude -p "$PROMPT" \
  --allowedTools "Read,Edit,Write,Glob,Grep" \
  --permission-mode acceptEdits \
  --max-turns 30 "${MODEL_ARGS[@]}" >> "$LOG" 2>&1
RC=$?

# ---- path guard: revert anything touched outside the whitelist --------------
REVERTED=""
while IFS= read -r P; do
  [ -n "$P" ] || continue
  grep -qxF "$P" "$BEFORE" && continue                # was already dirty — not ours
  case "$P" in
    queues/*.md|selfdev/*|FIELD-NOTES.md) ;;          # whitelisted
    *)
      if git ls-files --error-unmatch "$P" >/dev/null 2>&1; then
        git checkout -- "$P" 2>/dev/null
      else
        rm -f "$P" 2>/dev/null
      fi
      REVERTED="$REVERTED $P"
      ;;
  esac
done < <(git status --porcelain=v1 2>/dev/null | awk '{print $NF}' | sort)
[ -n "$REVERTED" ] && echo "[$TS] path-guard REVERTED out-of-whitelist edits:$REVERTED" | tee -a "$LOG"

# ---- ledger fallback: every run leaves a record -----------------------------
if [ "$(wc -c < "$CHANGELOG")" -le "$CL_BEFORE" ]; then
  { echo; echo "## $TS — no change adopted (driver rc=$RC, no CHANGELOG entry written)"
    echo "- why: call failed/timed out or found nothing actionable"
    echo "- evidence: fp $FP; see selfdev/logs/cycle-review-$STAMP.log"
    echo "- check: same evidence next cycle triggers a retry with fresh eyes"
  } >> "$CHANGELOG"
fi
[ -n "$REVERTED" ] && { echo "- path-guard: reverted$REVERTED"; } >> "$CHANGELOG"

# ---- commit state: this evidence is now consumed ----------------------------
echo "$FP" > "$STATE/last-fingerprint"
cat "$NEWSEEN" >> "$SEEN"; rm -f "$NEWSEEN"
echo "[$TS] cycle-review done (rc=$RC). Log: $LOG" | tee -a "$LOG"
exit 0
