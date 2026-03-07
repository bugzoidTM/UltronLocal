#!/usr/bin/env bash
set -euo pipefail
LOG=/root/.openclaw/workspace/UltronPro/tools/burnin_runner.log
for i in $(seq 1 576); do
  python3 /root/.openclaw/workspace/UltronPro/tools/burnin_monitor.py >> "$LOG" 2>&1 || true
  python3 /root/.openclaw/workspace/UltronPro/tools/burnin_diversity.py >> "$LOG" 2>&1 || true
  python3 /root/.openclaw/workspace/UltronPro/tools/metacog_metrics.py >> "$LOG" 2>&1 || true
  sleep 300
done
