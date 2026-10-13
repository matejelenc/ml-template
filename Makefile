# Short names for common commands. Each one also works typed out by hand.
.PHONY: setup test format check docs journal status

# One-time setup on a machine: writes .env and connects the Overleaf project.
setup:
	uv run python scripts/setup.py

test:
	uv run pytest -q

# Format the code and apply the fixes that are safe to apply automatically.
format:
	uv run ruff format src scripts tests
	uv run ruff check --fix src scripts tests

# Run before every commit: formatting, lint rules, type hints, tests. See CONTRIBUTING.md.
check:
	uv run ruff format --check src scripts tests
	uv run ruff check src scripts tests
	uv run mypy
	uv run pytest -q

# Build the reference documentation of every package in src/ from its docstrings.
# Open docs/api/index.html in a browser. `make docs SERVE=1` shows it live while you edit.
PACKAGES = $(patsubst src/%/__init__.py,%,$(wildcard src/*/__init__.py))
docs:
	uv run pdoc --docformat google $(if $(SERVE),,--output-directory docs/api) $(PACKAGES)

# make journal EXP=012-lora            push the newest finished run of the experiment
# make journal EXP=012-lora OUT=dir    write to a folder instead (manual upload)
journal:
	uv run python scripts/export_journal.py $(EXP) $(if $(RUN),--run $(RUN)) $(if $(OUT),--out $(OUT))

# make status                 the newest runs and their state (running, done, failed, lost, ...)
# make status EXP=012-lora    runs of one experiment
status:
	uv run python scripts/status.py $(EXP)
