"""Export the journal entry of an experiment by hand.

    uv run python scripts/export_journal.py 012-lora                  # newest finished run, push
    uv run python scripts/export_journal.py 012-lora --run <run_id>   # a specific run
    uv run python scripts/export_journal.py 012-lora --out upload/    # no push: write a folder
                                                                      # to upload to Overleaf by hand
Exit code 0 on success, 1 on failure.
"""

import argparse
import sys

from expkit import journal
from expkit.config import load_env


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a journal entry to Overleaf.")
    parser.add_argument("experiment", help="experiment ID, e.g. 012-lora")
    parser.add_argument("--run", help="run ID (default: the newest finished run)")
    parser.add_argument("--out", help="write to this folder instead of pushing to Overleaf")
    args = parser.parse_args()

    load_env()
    try:
        run_dir = journal.find_run(args.experiment, args.run)
        print(f"run: {run_dir}")
        print(f"journal export: {journal.export(run_dir, out=args.out)}")
    except (FileNotFoundError, journal.SyncError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
