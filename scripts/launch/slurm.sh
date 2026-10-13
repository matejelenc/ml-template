#!/usr/bin/env bash
# Launch a job with Slurm.
#
#   scripts/launch/slurm.sh --profile hpc-gpu scripts/experiment.py +experiment=012-lora
#   scripts/launch/slurm.sh --sbatch "--time=12:00:00" scripts/experiment.py +experiment=012-lora
#
# The #SBATCH lines come from scripts/launch/servers/<profile>.sh. Flags given with --sbatch
# win over them, as on the sbatch command line. Run with --help for all options.

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

parse_arguments "$@"
[ -n "$PROFILE_FILE" ] || fail "no profile. Pass --profile NAME or set LAUNCH_PROFILE in .env"
prepare
make_job_script slurm

# Slurm's own output (anything printed before the job wrapper starts) goes to slurm.log.
# shellcheck disable=SC2206  # SBATCH_FLAGS is split into words on purpose
submit=(sbatch --parsable --job-name="${EXPERIMENT_ID:-scratch}" --output="$RUN_DIR/slurm.log"
        $SBATCH_FLAGS "$JOB_SCRIPT")
echo "submit: ${submit[*]}"
[ "$DRY_RUN" = 1 ] && { echo "dry run: nothing submitted"; exit 0; }

job_id="$("${submit[@]}")" || submit_failed "sbatch did not accept the job (its message is above)"
push_tag
echo "submitted Slurm job $job_id"
echo "  watch:  tail -f $RUN_DIR/output.log     (or: squeue -j $job_id)"
echo "  cancel: scancel $job_id"
