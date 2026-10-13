#!/usr/bin/env bash
# Claude Code hook: run `make check` when Claude finishes a turn in which it changed code.
#
#   check.sh mark    after each file edit: remember that code was changed
#   check.sh         when Claude finishes: run the check if something was remembered
#
# A failed check is handed back to Claude once (exit code 2 does that). If it still fails
# after Claude's attempt to fix it, the user gets a warning instead, so there is no endless
# loop. Claude Code passes the details of the event as JSON on standard input.
# Both calls are set up in .claude/settings.json.

cd "${CLAUDE_PROJECT_DIR:-$(dirname "${BASH_SOURCE[0]}")/../..}" || exit 0
git_dir="$(git rev-parse --absolute-git-dir 2>/dev/null)" || exit 0
# Kept inside .git, so it is never committed and needs no line in .gitignore.
marker="$git_dir/claude-changed-code"
event="$(cat)"

if [ "${1:-}" = mark ]; then
    # Only files that `make check` looks at. Editing the README costs no test run.
    code='/(src|scripts|tests|conf)/[^"]*|/pyproject\.toml|/Makefile'
    grep -Eq "\"file_path\": *\"[^\"]*($code)\"" <<<"$event" && touch "$marker"
    exit 0
fi

[ -e "$marker" ] || exit 0
if output="$(make check 2>&1)"; then
    rm -f "$marker"
    exit 0
fi

if grep -Eq '"stop_hook_active": *true' <<<"$event"; then
    rm -f "$marker"
    echo '{"systemMessage": "make check still fails after an attempt to fix it. Run it to see why."}'
    exit 0
fi

echo "make check failed. Fix the cause, or tell the user why you cannot. The end of its output:" >&2
tail -n 40 <<<"$output" >&2
exit 2
