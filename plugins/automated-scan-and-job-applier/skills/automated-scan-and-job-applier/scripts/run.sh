#!/bin/zsh
# One scheduled run: scan job boards -> filter -> apply (until the budget ends) -> phone notification.
# Schedule it hourly (launchd on macOS, cron on Linux); see references/operations.md.
setopt NULL_GLOB 2>/dev/null
W="${JOB_APPLIER_HOME:-${0:A:h}}"
export JOB_APPLIER_HOME="$W"
export PATH="$HOME/.local/bin:$HOME/.local/node/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
py() { python3 -I "$@"; }
cfg() { py -c "import json,sys; print(json.load(open('$W/config.json')).get(sys.argv[1], sys.argv[2]))" "$1" "$2"; }
LOCK="$W/state/run.lock"; mkdir -p "$W/state" "$W/logs"
TOPIC=$(cfg ntfy_topic ""); NTFY=$(cfg ntfy_server "https://ntfy.sh")
ping() {  # ping TITLE BODY [PRIORITY]
  [ -n "$TOPIC" ] && curl -fsS -H "Title: $1" -H "Priority: ${3:-default}" -d "$2" "$NTFY/$TOPIC" >/dev/null 2>&1
}
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then rmdir "$LOCK"; mkdir "$LOCK" || exit 0
  else echo "$(date) previous run still active, skipping" >> "$W/logs/hourly.log"
       ping "⏳ $(date +%-I:%M%p) previous run still applying" "This hour's scan was skipped. Nothing is wrong." low; exit 0; fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
TS=$(date +%Y%m%d-%H%M); START=$(date +%s)
C="$(cfg career_ops_dir career-ops)"; [[ "$C" != /* ]] && C="$W/$C"
SINCE=$(cfg scan_since_days 2)

# --- scans in parallel (different hosts)
( cd "$C" && node scan-ats-full.mjs --since $SINCE --ats greenhouse,lever,ashby > "$W/logs/scan-$TS.log" 2>&1; echo $? > "$W/logs/.rc-ats" ) &
if [ "$(cfg workday_scan True)" = "True" ]; then
  ( node "$W/sources/workday_scan.mjs" --since $SINCE --budget 420 > "$W/logs/scan-wd-$TS.log" 2> "$W/logs/scan-wd-$TS.err" ) &
fi
if [ "$(cfg indeed False)" = "True" ] && [ $(( $(date +%-H) % 3 )) -eq 0 ]; then
  ( py "$W/sources/indeed_scan.py" --since 4 > "$W/logs/scan-in-$TS.log" 2> "$W/logs/scan-in-$TS.err" ) &
fi
wait
RC=$(cat "$W/logs/.rc-ats" 2>/dev/null || echo 9)
NEW=0
for LOG in "$W/logs/scan-$TS.log" "$W/logs/scan-wd-$TS.log" "$W/logs/scan-in-$TS.log" "$W"/logs/backfill-*.log; do
  [ -f "$LOG" ] || continue
  N=$(py "$W/filter_jobs.py" "$LOG" 2>>"$W/logs/hourly.log" | py -c "import json,sys
try: print(json.load(sys.stdin)['new_queued'])
except Exception: print(0)")
  NEW=$(( NEW + N ))
  [[ "$LOG" == *backfill-* ]] && mv "$LOG" "$LOG.done"
done

# --- apply until minute 55 (the next run starts on the hour)
NOWMIN=$(date +%-M); BUDGET=$(( (55 - NOWMIN) * 60 )); [ $BUDGET -lt 300 ] && BUDGET=300
WRES=$(py "$W/apply_worker.py" --budget $BUDGET 2>>"$W/logs/worker.err" | tail -1)

MIN=$(( ($(date +%s)-START)/60 ))
echo "$(date) rc=$RC new=$NEW worker=$WRES ${MIN}m $(py "$W/stats.py")" >> "$W/logs/hourly.log"
if [ "$RC" = "0" ]; then ping "✅ $(date +%-I:%M%p) run OK" "$(py "$W/stats.py" --pulse "$NEW" "$WRES" "$MIN")"
else ping "⚠️ $(date +%-I:%M%p) run had a problem" "Job-board scan exit code $RC (logs/scan-$TS.log). $(py "$W/stats.py" --pulse "$NEW" "$WRES" "$MIN")" high; fi
find "$W/logs" -name 'scan-*' -mtime +7 -delete
