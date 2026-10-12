#!/usr/bin/env bash
# Launch a job in a tmux session (servers without a scheduler).
#
#   scripts/launch/tmux.sh scripts/experiment.py +experiment=012-lora
#
# The session is named after the run ID and closes when the job ends.
# Run with --help for all options.

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

parse_arguments "$@"
prepare
make_job_script tmux

echo "submit: tmux new-session -d -s $RUN_ID bash $JOB_SCRIPT"
[ "$DRY_RUN" = 1 ] && { echo "dry run: nothing submitted"; exit 0; }

tmux new-session -d -s "$RUN_ID" "bash $(printf '%q' "$JOB_SCRIPT")"
echo "started tmux session $RUN_ID"
echo "  watch:  tmux attach -t $RUN_ID     (or: tail -f $RUN_DIR/stdout.log)"
echo "  cancel: tmux kill-session -t $RUN_ID"
