#!/usr/bin/env bash
# Periodic snapshot of the live stack. Appends one dated block to
# monitoring/snapshot.log every POLL_SECONDS seconds until the harvester
# has signalled done AND all three queues have been empty for N
# consecutive polls AND the reporter container has exited this run
# (identified by its StartedAt timestamp being newer than RUN_START).
set -u
LOG=monitoring/snapshot.log
POLL=${POLL_SECONDS:-90}
IDLE_POLLS_REQUIRED=${IDLE_POLLS_REQUIRED:-2}
RUN_START=${RUN_START:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}

idle_streak=0
echo "[$(date +%H:%M:%S)] monitor started (poll=${POLL}s, run_start=${RUN_START})" >> "$LOG"

while :; do
  {
    echo "===== $(date +%Y-%m-%d\ %H:%M:%S) ====="
    MASTERS=$(docker exec hafele-redis redis-cli LLEN hafele:master_urls 2>/dev/null || echo "?")
    SCRAPE=$(docker exec hafele-redis redis-cli LLEN hafele:scrape_queue 2>/dev/null || echo "?")
    DBW=$(docker exec hafele-redis redis-cli LLEN hafele:db_write_queue 2>/dev/null || echo "?")
    HS=$(docker exec hafele-redis redis-cli GET hafele:harvester:status 2>/dev/null || echo "?")
    echo "  master_urls=$MASTERS  scrape_queue=$SCRAPE  db_write_queue=$DBW  harvester=$HS"
    ROWS=$(docker exec hafele-db-writer python -c \
      "import sqlite3;print(sqlite3.connect('/app/data/products.db').execute('SELECT COUNT(*) FROM products').fetchone()[0])" 2>/dev/null || echo "?")
    echo "  db_rows=$ROWS"
    if [ -f data/dinler_fallback.log ]; then
      TOTAL=$(wc -l < data/dinler_fallback.log | tr -d ' ')
      RES=$(grep -c '"outcome": "resolved"' data/dinler_fallback.log 2>/dev/null | head -1 || echo 0)
      MISS=$(grep -c '"outcome": "miss"' data/dinler_fallback.log 2>/dev/null | head -1 || echo 0)
      HTTP=$(grep -c '"outcome": "http_error"' data/dinler_fallback.log 2>/dev/null | head -1 || echo 0)
      TRANS=$(grep -c '"outcome": "transport_error"' data/dinler_fallback.log 2>/dev/null | head -1 || echo 0)
      PARSE=$(grep -c '"outcome": "parse_error"' data/dinler_fallback.log 2>/dev/null | head -1 || echo 0)
      echo "  dinler total=$TOTAL  resolved=$RES  miss=$MISS  http_err=$HTTP  net_err=$TRANS  parse_err=$PARSE"
    else
      echo "  dinler_log=(no file)"
    fi
    SERR=$(docker ps --format '{{.Names}}' | grep -E 'scraper|discovery' | \
      xargs -I{} docker logs --since 2m {} 2>&1 | grep -cE "ERROR|Traceback" | tr -d ' ' || echo 0)
    echo "  scraper_errors_last2m=$SERR"
    # Reporter — only count this run's reporter, not yesterday's.
    REP_STARTED=$(docker inspect hafele-reporter --format '{{.State.StartedAt}}' 2>/dev/null || echo "")
    REP_STATE=$(docker inspect hafele-reporter --format '{{.State.Status}}' 2>/dev/null || echo "n/a")
    REP_EXIT=$(docker inspect hafele-reporter --format '{{.State.ExitCode}}' 2>/dev/null || echo "?")
    echo "  reporter state=$REP_STATE exit=$REP_EXIT started=$REP_STARTED"
  } >> "$LOG"

  # Stop condition: harvester done + all queues zero for IDLE_POLLS_REQUIRED
  # consecutive samples + reporter has exited for this run (StartedAt
  # lexically > RUN_START).
  if [ "$HS" = "done" ] && [ "$MASTERS" = "0" ] && [ "$SCRAPE" = "0" ] && [ "$DBW" = "0" ]; then
    idle_streak=$((idle_streak + 1))
    echo "  (idle_streak=$idle_streak/$IDLE_POLLS_REQUIRED)" >> "$LOG"
    if [ $idle_streak -ge "$IDLE_POLLS_REQUIRED" ] \
        && [ "$REP_STATE" = "exited" ] \
        && [ "$REP_EXIT" = "0" ] \
        && [[ "$REP_STARTED" > "$RUN_START" ]]; then
      echo "[$(date +%H:%M:%S)] stop condition met; monitor exiting" >> "$LOG"
      exit 0
    fi
  else
    idle_streak=0
  fi
  sleep "$POLL"
done
