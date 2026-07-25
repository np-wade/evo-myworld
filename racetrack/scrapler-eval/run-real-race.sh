#!/bin/bash
# Run a REAL scrapler race for one weight class: make a venv, install just that
# class's tool deps, then race its bracket. ONE class at a time on purpose —
# browsers/engines are heavy and this box is RAM-capped (the harness itself is
# pure stdlib; only the tools need installing). Niced + idle-io so it yields.
#
#   ./run-real-race.sh class1      # fetchers: curl_cffi, scrapling
#   ./run-real-race.sh class2      # browsers: playwright (+ browser binaries), camoufox, ...
#   ./run-real-race.sh class3      # engines:  crawl4ai, scrapegraphai (+ HEADLESSX_URL/BROWSERLESS_URL)
#   ./run-real-race.sh class4      # extractors: trafilatura, bs4  (light)
set -euo pipefail
cd "$(dirname "$0")"
CLASS="${1:?usage: run-real-race.sh class1|class2|class3|class4}"
VENV=".venv-race"
[ -d "$VENV" ] || python3 -m venv "$VENV"
PY="$VENV/bin/python"; PIP="$VENV/bin/pip"

case "$CLASS" in
  class1) DEPS="curl_cffi scrapling"; BRACKET="class1-fetchers" ;;
  class2) DEPS="playwright camoufox scrapling"; BRACKET="class2-browsers"
          EXTRA_POST="$VENV/bin/playwright install chromium firefox" ;;
  class3) DEPS="crawl4ai scrapegraphai"; BRACKET="class3-engines" ;;
  class4) DEPS="trafilatura beautifulsoup4 lxml"; BRACKET="class4-extractors" ;;
  *) echo "unknown class $CLASS"; exit 1 ;;
esac

echo ">> installing $CLASS deps ($DEPS) into $VENV (niced)…"
nice -n 19 ionice -c 3 "$PIP" install -q $DEPS || {
  echo "!! some deps failed to install — the harness will still skip them cleanly"; }
[ -n "${EXTRA_POST:-}" ] && { echo ">> $EXTRA_POST"; nice -n 19 $EXTRA_POST || true; }

echo ">> racing $BRACKET with real tools…"
nice -n 19 ionice -c 3 "$PY" -m scrapler_eval race \
  --bracket "brackets/$BRACKET.json" --out "result-$BRACKET-real.md"
echo ">> result -> result-$BRACKET-real.md"
