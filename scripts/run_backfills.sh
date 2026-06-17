#!/bin/bash
# Restart all incomplete forecast backfills with BOUNDED concurrency.
#
# Background: the previous attempt ran 10 parallel sessions and they died
# (bandwidth/disk/Herbie-cache contention; disk-full once even crashed
# Postgres). This caps concurrency at 3 and runs every job over the full
# window — the gaps are scattered, so a full-range pass (idempotent at the DB
# insert) is the only reliable way to fill them.
#
# Run in tmux:  tmux new-session -d -s backfills 'bash scripts/run_backfills.sh'
set -u
cd /home/tdunn/weather-project
LOG=/tmp/backfill
mkdir -p "$LOG"
START=2025-06-26
END=2026-06-16
MAXJOBS=3

run_job() {
  local script=$1 station=$2 model=$3
  echo "[$(date -u +%H:%M:%S)] START  $model $station"
  /home/tdunn/.local/bin/uv run python "scripts/$script" \
      --run-hour 0 --start "$START" --end "$END" --station "$station" \
      > "$LOG/${model}_${station}.log" 2>&1
  echo "[$(date -u +%H:%M:%S)] FINISH $model $station (exit $?)"
}

# KMDW GEFS first — it gates the Midway/Polymarket model work.
JOBS=(
  "backfill_gefs_runs.py  KMDW gefs"
  "backfill_gefs_runs.py  KPHX gefs"
  "backfill_gefs_runs.py  KLAS gefs"
  "backfill_ecmwf_runs.py KLAS ifs"
  "backfill_ecmwf_runs.py KSEA ifs"
  "backfill_gefs_runs.py  KSEA gefs"
  "backfill_ecmwf_runs.py KDFW ifs"
  "backfill_gefs_runs.py  KDFW gefs"
  "backfill_ecmwf_runs.py KMSY ifs"
  "backfill_gefs_runs.py  KMSY gefs"
)

echo "=== backfill orchestrator start $(date -u) — ${#JOBS[@]} jobs, max ${MAXJOBS} parallel ==="
for job in "${JOBS[@]}"; do
  # throttle: wait until a slot frees up
  while [ "$(jobs -rp | wc -l)" -ge "$MAXJOBS" ]; do sleep 15; done
  # shellcheck disable=SC2086
  run_job $job &
  sleep 2
done
wait
echo "=== ALL BACKFILLS COMPLETE $(date -u) ==="
