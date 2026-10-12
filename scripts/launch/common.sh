# Shared steps of the launchers. Sourced by tmux.sh and slurm.sh, not run directly.
#
# A launch has three steps:
#   prepare   check the git tree, tag the experiment, create the run folder
#   submit    hand the job script to tmux or Slurm (done in tmux.sh / slurm.sh)
#   wrap      job_wrapper.sh runs the command and records its state

set -euo pipefail

LAUNCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$LAUNCH_DIR" rev-parse --show-toplevel)"

fail() { echo "error: $*" >&2; exit 1; }
warn() { echo "warning: $*" >&2; }

usage() {
    cat <<USAGE
usage: $(basename "$0") [options] <command...>

  <command...>         what to run, e.g. scripts/experiment.py +experiment=012-lora
                       A command that starts with a .py file is run with "uv run python".
options:
  --profile NAME       settings file scripts/launch/servers/NAME.sh
                       (default: LAUNCH_PROFILE from .env)
  --allow-dirty        launch even with uncommitted changes (recorded in run.json)
  --sbatch "FLAGS"     extra sbatch flags for this launch, e.g. "--time=12:00:00" (Slurm only)
  --dry-run            show what would be done, change nothing
  -h, --help           this text
USAGE
}

# setting NAME: the environment variable NAME, or else its line in .env, or else empty.
setting() {
    local name="$1"
    if [ -n "${!name:-}" ]; then
        echo "${!name}"
    elif [ -f "$REPO/.env" ]; then
        { grep -m1 "^$name=" "$REPO/.env" || true; } | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
    fi
}

parse_arguments() {
    PROFILE="$(setting LAUNCH_PROFILE)"
    ALLOW_DIRTY=0
    DRY_RUN=0
    SBATCH_FLAGS=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --profile) PROFILE="$2"; shift 2 ;;
            --allow-dirty) ALLOW_DIRTY=1; shift ;;
            --sbatch) SBATCH_FLAGS="$2"; shift 2 ;;
            --dry-run) DRY_RUN=1; shift ;;
            -h|--help) usage; exit 0 ;;
            --) shift; break ;;
            -*) usage >&2; fail "unknown option $1" ;;
            *) break ;;
        esac
    done
    [ "$#" -gt 0 ] || { usage >&2; fail "no command given"; }
    COMMAND=("$@")
    # Shorthand: "scripts/train.py ..." means "uv run python scripts/train.py ...".
    case "${COMMAND[0]}" in *.py) COMMAND=(uv run python "${COMMAND[@]}") ;; esac

    # The experiment is named by the Hydra argument +experiment=NAME. Without it, the run is
    # a debugging run ("scratch"): no tag and no clean-tree check.
    EXPERIMENT_CHOICE=""
    local argument
    for argument in "${COMMAND[@]}"; do
        case "$argument" in +experiment=*|experiment=*) EXPERIMENT_CHOICE="${argument#*=}" ;; esac
    done
    # conf/experiment/vision/012-lora.yaml is chosen as vision/012-lora and has the ID 012-lora.
    EXPERIMENT_ID="${EXPERIMENT_CHOICE##*/}"

    PROFILE_FILE=""
    if [ -n "$PROFILE" ]; then
        PROFILE_FILE="$LAUNCH_DIR/servers/$PROFILE.sh"
        [ -f "$PROFILE_FILE" ] || fail "no settings file $PROFILE_FILE"
    fi
}

# prepare: check the git tree and make sure the tag exp/<id> sits on the current commit.
prepare() {
    if [ -z "$EXPERIMENT_ID" ]; then
        echo "no +experiment=... given: scratch run, no tag"
        return
    fi
    local experiment_file="$REPO/conf/experiment/$EXPERIMENT_CHOICE.yaml"
    [ -f "$experiment_file" ] || fail "no experiment file $experiment_file"

    if [ -n "$(git -C "$REPO" status --porcelain)" ]; then
        if [ "$ALLOW_DIRTY" = 1 ]; then
            warn "uncommitted changes: the tag will not match the code that runs"
        else
            git -C "$REPO" status --short >&2
            fail "uncommitted changes. Commit them, or pass --allow-dirty"
        fi
    fi

    local tag="exp/$EXPERIMENT_ID" head has_remote=0
    head="$(git -C "$REPO" rev-parse HEAD)"
    git -C "$REPO" remote get-url origin >/dev/null 2>&1 && has_remote=1

    if [ "$DRY_RUN" = 1 ]; then
        echo "would create or reuse tag $tag on $head"
        return
    fi
    # Another server may have used this experiment number already.
    if [ "$has_remote" = 1 ]; then
        git -C "$REPO" fetch --quiet --tags origin || warn "could not fetch tags from origin"
    fi

    if git -C "$REPO" rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
        local tagged
        tagged="$(git -C "$REPO" rev-parse "$tag^{commit}")"
        [ "$tagged" = "$head" ] || fail "tag $tag already exists on another commit (${tagged:0:10}).
One tag means one commit. Create a new experiment file with the next number instead."
        echo "tag $tag already on this commit, reusing it"
    else
        # The tag message is the "# Purpose: ..." line of the experiment file.
        local purpose
        purpose="$(sed -n 's/^# *Purpose: *//p' "$experiment_file" | head -n 1)"
        git -C "$REPO" tag -a "$tag" -m "${purpose:-Experiment $EXPERIMENT_ID}"
        echo "created tag $tag: ${purpose:-Experiment $EXPERIMENT_ID}"
    fi
    if [ "$has_remote" = 1 ]; then
        git -C "$REPO" push --quiet origin "$tag" \
            || warn "could not push tag $tag. Push it later with: git push origin $tag"
    fi
}

# make_job_script SCHEDULER: choose the run ID and folder, write <run_dir>/job.sh.
make_job_script() {
    local scheduler="$1" runs_dir
    RUN_ID="$(date +%Y%m%d-%H%M%S)-$(od -An -N2 -tx1 /dev/urandom | tr -d ' \n')"
    runs_dir="$(setting RUNS_DIR)"
    runs_dir="${runs_dir:-runs}"
    # A relative RUNS_DIR is relative to the repository.
    case "$runs_dir" in /*) ;; *) runs_dir="$REPO/$runs_dir" ;; esac
    RUN_DIR="$runs_dir/${EXPERIMENT_ID:-scratch}/$RUN_ID"

    JOB_SCRIPT_TEXT="$(
        echo "#!/usr/bin/env bash"
        if [ -n "$PROFILE_FILE" ]; then
            echo "# --- from scripts/launch/servers/$PROFILE.sh ---"
            cat "$PROFILE_FILE"
            echo "# --- end of server settings ---"
        fi
        printf 'cd %q\n' "$REPO"
        # The run ID and folder are fixed here, so the launcher and the job agree on them.
        printf 'export RUN_ID=%q RUNS_DIR=%q LAUNCH_SCHEDULER=%q ALLOW_DIRTY=%q\n' \
            "$RUN_ID" "$runs_dir" "$scheduler" "$ALLOW_DIRTY"
        printf 'exec bash scripts/launch/job_wrapper.sh %q' "$RUN_DIR"
        printf ' %q' "${COMMAND[@]}"
        echo
    )"

    echo
    echo "run folder: $RUN_DIR"
    echo "job script:"
    echo "$JOB_SCRIPT_TEXT" | sed 's/^/    /'
    echo

    JOB_SCRIPT="$RUN_DIR/job.sh"
    if [ "$DRY_RUN" = 0 ]; then
        bash "$LAUNCH_DIR/job_wrapper.sh" --queued "$RUN_DIR"
        echo "$JOB_SCRIPT_TEXT" > "$JOB_SCRIPT"
    fi
}
