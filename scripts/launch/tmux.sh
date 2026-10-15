#!/usr/bin/env bash
# Launch a job in a tmux session (servers without a scheduler).
#
#   scripts/launch/tmux.sh scripts/experiment.py +experiment=012-lora
#   CUDA_VISIBLE_DEVICES=1 scripts/launch/tmux.sh scripts/experiment.py +experiment=012-lora
#
# Each job gets a tmux server of its own, named after the run ID, which closes when the job
# ends. A session on an already running tmux server would get that server's environment,
# not this shell's, and lose variables such as CUDA_VISIBLE_DEVICES. Run with --help for all
# options.

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

parse_arguments "$@"
prepare
make_job_script tmux

echo "submit: tmux -L $RUN_ID new-session -d -s $RUN_ID bash $JOB_SCRIPT"
[ "$DRY_RUN" = 1 ] && { echo "dry run: nothing submitted"; exit 0; }

tmux -L "$RUN_ID" new-session -d -s "$RUN_ID" "bash $(printf '%q' "$JOB_SCRIPT")" \
    || submit_failed "tmux could not start the session (its message is above)"
push_tag
echo "started tmux session $RUN_ID"
echo "  watch:  tmux -L $RUN_ID attach     (or: tail -f $RUN_DIR/output.log)"
echo "  cancel: tmux -L $RUN_ID kill-session"
