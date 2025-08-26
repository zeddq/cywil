#!/usr/bin/env bash
set -euo pipefail

# Config
REPO_DIR="/workspace"
VENV_BIN="/workspace/.venv/bin"
PYRIGHT_SCRIPT="/workspace/scripts/pyright_report_by_rule.py"
REPORT_DIR="/workspace/pyright_reports"
MONITOR_LOG="/workspace/reports/pyright_monitor_latest.md"
SLEEP_SECS=1800 # 30 minutes

mkdir -p "$(dirname "$MONITOR_LOG")"
mkdir -p "$REPORT_DIR"

cd "$REPO_DIR"

last_head=""

note() {
  echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$MONITOR_LOG"
}

get_head() {
  git rev-parse HEAD 2>/dev/null || echo "unknown"
}

get_branch() {
  git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "detached"
}

run_report() {
  PATH="$VENV_BIN:$PATH" "$VENV_BIN/python" "$PYRIGHT_SCRIPT" | sed 's/^/    /' | tee -a "$MONITOR_LOG"
}

baseline_csv=""

summarize_counts() {
  awk -F, 'NR>1{c[$1]+=1} END{for (r in c) printf "%s,%d\n", r, c[r]}' "$1" | sort
}

compare_csvs() {
  local old_csv="$1" new_csv="$2"
  if [[ -z "$old_csv" || ! -s "$old_csv" ]]; then
    echo "first_run"
    return 0
  fi
  local old_sum new_sum
  old_sum=$(summarize_counts "$old_csv")
  new_sum=$(summarize_counts "$new_csv")
  echo "--- previous" && echo "$old_sum"
  echo "--- current" && echo "$new_sum"
}

note "Starting pyright monitor on branch $(get_branch)"

while true; do
  current_head=$(get_head)
  if [[ "$current_head" != "$last_head" ]]; then
    note "Detected new commit: ${current_head:0:12} (prev: ${last_head:0:12})"
    # Preserve previous CSV to compare
    prev_csv="${REPORT_DIR}/all_violations.prev.csv"
    if [[ -f "${REPORT_DIR}/all_violations.csv" ]]; then
      cp -f "${REPORT_DIR}/all_violations.csv" "$prev_csv" || true
    fi

    run_report || note "Report run failed"

    if [[ -f "$prev_csv" && -f "${REPORT_DIR}/all_violations.csv" ]]; then
      note "Diff of rule counts (rule,count)"
      compare_csvs "$prev_csv" "${REPORT_DIR}/all_violations.csv" | sed 's/^/    /' | tee -a "$MONITOR_LOG"

      # Detect net reduction
      old_total=$(wc -l < "$prev_csv")
      new_total=$(wc -l < "${REPORT_DIR}/all_violations.csv")
      # subtract header line
      old_total=$((old_total-1))
      new_total=$((new_total-1))
      if (( new_total < old_total )); then
        note "✅ Linter violations reduced: ${old_total} -> ${new_total} (-$((old_total-new_total)))"
      else
        note "ℹ️ No reduction detected: ${old_total} -> ${new_total}"
      fi
    else
      note "No previous CSV to compare; initial baseline established."
    fi

    last_head="$current_head"
  else
    note "No new commits on $(get_branch). Skipping run."
  fi

  sleep "$SLEEP_SECS"

done