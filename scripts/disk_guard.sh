#!/bin/bash
# Protect Postgres from a disk-full crash during backfills. If free space on
# the data volume drops below THRESH_GB, stop the backfills. The kill pattern
# lives in this file (not in this process's argv), so pgrep -f never matches
# the guard itself; the $$ check is belt-and-suspenders.
THRESH_GB=6
echo "disk-guard started $(date -u) — threshold ${THRESH_GB}GB"
while true; do
  if ! tmux has-session -t backfills 2>/dev/null; then
    echo "[$(date -u +%H:%M)] backfills session gone — guard exiting"; break
  fi
  avail=$(df -BG --output=avail /home/tdunn | tail -1 | tr -dc '0-9')
  echo "[$(date -u +%H:%M)] free=${avail}GB"
  if [ "${avail:-99}" -lt "$THRESH_GB" ]; then
    echo "[$(date -u +%H:%M)] DISK LOW (${avail}GB < ${THRESH_GB}GB) — stopping backfills"
    tmux kill-session -t backfills 2>/dev/null
    for pid in $(pgrep -f "backfill_(gefs|ecmwf)_runs"); do
      [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null
    done
    break
  fi
  sleep 120
done
