# Short names for common commands. Each one also works typed out by hand.
.PHONY: test journal

test:
	uv run pytest -q

# make journal EXP=012-lora            push the newest finished run of the experiment
# make journal EXP=012-lora OUT=dir    write to a folder instead (manual upload)
journal:
	uv run python scripts/export_journal.py $(EXP) $(if $(RUN),--run $(RUN)) $(if $(OUT),--out $(OUT))
