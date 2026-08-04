#!/bin/bash
# heartbeat.sh — shared "is this job actually alive" progress reporting for
# RETICLE SLURM job scripts.
#
# A silent job and a stuck one look identical in a SLURM log otherwise (see:
# reticle-context.sh hanging with pg_stat_activity showing no active OR
# blocked connection at all — the python process was stuck on a dead TCP
# socket, indistinguishable from "just slow" without something else proving
# the process tree is still alive).
#
# Usage: source this file, then wrap the real (long-running) command instead
# of calling it directly:
#   source "$RETICLE_DIR/slurm/heartbeat.sh"
#   run_with_heartbeat "compute_contextual.py" python3 compute_contextual.py --version "$VERSION" ...
#   EXIT_CODE=$?
#
# Prints one line every $HEARTBEAT_INTERVAL seconds (default 300s = 5 min)
# while the wrapped command runs, and preserves its real exit code in $?.
#
# Reading it: if heartbeat lines stop appearing entirely, the job's process
# tree (or its node) actually died — that's different from "no new app-level
# log line yet." If heartbeats keep coming but the app's own log has gone
# quiet, the process is alive but stuck (e.g. blocked on a dead DB socket) —
# check pg_stat_activity / squeue+top on that PID next.

HEARTBEAT_INTERVAL="${HEARTBEAT_INTERVAL:-300}"

run_with_heartbeat() {
    local desc="$1"; shift
    local start_ts
    start_ts=$(date +%s)

    "$@" &
    local cmd_pid=$!

    (
        while kill -0 "$cmd_pid" 2>/dev/null; do
            sleep "$HEARTBEAT_INTERVAL"
            kill -0 "$cmd_pid" 2>/dev/null || break
            now=$(date +%s)
            elapsed=$(( (now - start_ts) / 60 ))
            echo "[heartbeat] $(date -u +%Y-%m-%dT%H:%M:%SZ)  ${desc}  still running (PID $cmd_pid, ${elapsed}m elapsed)"
        done
    ) &
    local hb_pid=$!

    wait "$cmd_pid"
    local exit_code=$?

    kill "$hb_pid" 2>/dev/null
    wait "$hb_pid" 2>/dev/null

    return $exit_code
}
