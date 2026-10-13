#!/usr/bin/env bash
# Runs one job and records its state in <run_dir>/status.json.
#
#   job_wrapper.sh <run_dir> <command...>     run the command
#   job_wrapper.sh --queued <run_dir>         only mark the run as queued (used by launchers)
#   job_wrapper.sh --failed <run_dir>         only mark the run as failed: the scheduler did
#                                             not accept it (used by launchers)
#
# States: queued -> running -> done | failed | cancelled.
# While the job runs, the "heartbeat" time is refreshed every minute. A run that says
# "running" with an old heartbeat was killed without warning: `make status` shows it as lost.
#
# This file depends on nothing but bash, on purpose: jobs must run and be recorded even if
# the Python library is broken. All output of the command goes to <run_dir>/output.log.

set -u
SCHEMA_VERSION=1
HEARTBEAT_SECONDS="${HEARTBEAT_SECONDS:-60}"

# write_status <state> <exit code or null>
write_status() {
    local temporary="$RUN_DIR/status.json.$BASHPID.tmp"
    printf '{\n  "schema_version": %s,\n  "state": "%s",\n  "heartbeat": "%s",\n  "exit_code": %s\n}\n' \
        "$SCHEMA_VERSION" "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$2" > "$temporary"
    # Rename in one step, so a reader never sees a half-written file.
    mv "$temporary" "$RUN_DIR/status.json"
}

if [ "${1:-}" = "--queued" ] || [ "${1:-}" = "--failed" ]; then
    RUN_DIR="$2"
    mkdir -p "$RUN_DIR"
    write_status "${1#--}" null
    exit 0
fi

if [ "$#" -lt 2 ]; then
    echo "usage: job_wrapper.sh <run_dir> <command...>" >&2
    exit 2
fi
RUN_DIR="$1"
shift
mkdir -p "$RUN_DIR"
LOG="$RUN_DIR/output.log"

write_status running null

# Start the job in the background, so this script stays free to react to signals.
"$@" >> "$LOG" 2>&1 &
job=$!

# Heartbeat: refresh the time in status.json while the job runs.
(
    # Stop at once when asked to, without leaving a sleep behind.
    trap 'kill "$!" 2>/dev/null; exit 0' TERM
    while :; do
        sleep "$HEARTBEAT_SECONDS" &
        wait "$!"
        write_status running null
    done
) > /dev/null 2>&1 &
heartbeat=$!

# In a terminal (tmux), show the log live. Under Slurm there is no terminal.
if [ -t 1 ]; then
    tail -n +1 -f "$LOG" --pid="$job" &
fi

# scancel, a Slurm time limit, tmux kill-session and Ctrl-C all arrive as signals.
# Pass the signal on to the job and remember that the run was cancelled.
cancelled=0
trap 'cancelled=1; kill -TERM "$job" 2>/dev/null' TERM INT HUP

# `wait` returns early when a signal arrives, so repeat until the job has really ended.
exit_code=0
while :; do
    wait "$job"
    exit_code=$?
    kill -0 "$job" 2>/dev/null || break
done

kill "$heartbeat" 2>/dev/null
wait "$heartbeat" 2>/dev/null

if [ "$cancelled" = 1 ]; then
    write_status cancelled "$exit_code"
elif [ "$exit_code" = 0 ]; then
    write_status done 0
else
    write_status failed "$exit_code"
fi
exit "$exit_code"
