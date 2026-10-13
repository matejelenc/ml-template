# Ways of working

How code is written in this project. It applies to everyone who changes it: you, a
collaborator, a coding agent. `README.md` says how to use the project; this file says how to
change it.

The aim is code that a stranger can read, trust and reuse a year from now. It is still
research code: it has to be clear and correct, not bullet-proof.

## Before every commit

```
make format    # format the code, apply the safe automatic fixes
make check     # formatting, lint rules, type hints, tests
```

A commit goes in only when `make check` passes. Everything a tool can check is checked
there (settings in `pyproject.toml`), so the rest of this file is short: it covers what
tools cannot check. If a rule gets in the way, change the rule here and in `pyproject.toml`
in a commit of its own. Do not silence it line by line.

## Principles

1. **Write for the reader.** Plain names, short functions, no clever tricks. Code is read
   far more often than it is written.
2. **One source for each piece of logic.** If two places need the same thing, they call the
   same function. A bug then has one possible home.
3. **Delete what is unused.** No commented-out code, no "might need it later". Git remembers.
4. **Few dependencies.** Each new package is something that can break on the next server.
   Add one with `uv add` only when writing it yourself would be clearly worse, and say in a
   comment in `pyproject.toml` what it is for.
5. **Fail early, with a message that says what to do.** Check inputs at the start of a job,
   not after six hours of training. Never catch an error just to continue silently.
6. **Results come from committed code.** No number in a paper comes from a notebook or from
   uncommitted changes. Notebooks are for looking at data; code that matters moves to `src/`.

## Layout

- `src/<package>/`: everything that is imported. Small modules, one topic each.
- `scripts/`: entry points only. A script reads the config, calls functions from `src/` and
  writes results. Logic that deserves a test belongs in `src/`.
- `conf/`: settings. A value that changes between experiments is in the config, never a
  constant buried in the code.
- A name that starts with an underscore (`_helper`) is internal to its module. Anything
  another module or a user calls has no underscore, and a docstring.

## Type hints

Every function has a type on each argument and on the return value. `make check` enforces it.

- Use the built-in forms: `list[str]`, `dict[str, float]`, `Path | None`. Nothing from
  `typing` is needed for them.
- Use `Path` for paths, not `str`.
- Be specific: `dict[str, float]`, not `dict`. Use `Any` only where a library gives nothing
  better, such as a W&B run.
- A value with a fixed structure that travels through several functions gets a `dataclass`,
  not a dict with keys the reader has to guess.
- Types cannot say what an array holds. For arrays and tensors, write the shape and the
  meaning in the docstring (see the example below).
- `# type: ignore` needs the error code and a reason: `# type: ignore[attr-defined]  # why`.

## Docstrings

Google style. `make check` checks the form, `make docs` turns the docstrings into pages.

- Every module, and every class and function without an underscore, has one.
- The first line is one sentence that says what the thing does, and fits on the line.
- Then, only if needed: why it exists, what is surprising, a short example.
- `Args:`, `Returns:` and `Raises:` are written when they say more than the names and types
  already do. Do not repeat the types: they are in the signature.
- A docstring that only repeats the function name is noise. Say something the reader cannot
  see in the signature, or keep it to the one line.
- Placeholders such as `<run_id>` go in backticks, otherwise the docs page swallows them.

```python
def top_k_accuracy(logits: torch.Tensor, labels: torch.Tensor, k: int = 5) -> float:
    """Share of samples whose true class is among the k highest scores.

    Args:
        logits: Unnormalized scores, shape (batch, classes).
        labels: Index of the true class of each sample, shape (batch,).
        k: How many of the highest scores count as a hit.

    Returns:
        A number between 0 and 1.

    Raises:
        ValueError: If k is larger than the number of classes.
    """
```

## Comments

A comment says why, not what. `# The tag counts only if it sits on the commit that is
running` helps; `# get the tag` does not. If a block needs a comment to say what it does,
give it a name by making it a function.

## Tests

- Tests mirror the code: `src/<package>/<module>.py` is tested in
  `tests/<package>/test_<module>.py`, `scripts/<name>.py` in `tests/scripts/test_<name>.py`,
  and the config in `tests/conf/`. Each test file starts with a docstring.
- The name of a test says what must hold: `test_a_crashed_run_keeps_its_run_json`.
- Test what a function promises, not how it does it. A few tests that would catch a real
  mistake are worth more than many that restate the code.
- A bug that cost you time gets a test before the fix.
- When behaviour changes, change or delete the tests of the old behaviour in the same commit.
- For research code, the most useful tests are small and concrete: shapes, a metric on an
  example worked out by hand, a training step that lowers the loss on four samples, no
  overlap between the train and test split.

## Git

- One commit is one change that can be described in one line, written as an instruction:
  `Add top-k accuracy`, not `changes` or `fixed stuff`.
- Formatting-only changes go in a commit of their own.
- An experiment runs from a commit, and its tag `exp/NNN-slug` is never moved (see
  `README.md`).
- Never commit secrets, data, run folders or weights. `.gitignore` covers them.

## Documentation

Three kinds, each with one job:

| Where | What it answers | Written |
|---|---|---|
| `README.md` | How do I install and use this? | by hand, updated in the commit that changes the behaviour |
| docstrings | What does this function do and expect? | by hand, next to the code |
| `docs/api/` | The docstrings and signatures as web pages | by `make docs`, never by hand, not committed |

`make docs` builds the pages for every package in `src/`; open `docs/api/index.html`.
`make docs SERVE=1` shows them in the browser and reloads while you edit. The pages are only
as good as the docstrings, and they do not replace the README: a new user needs the README
first.

## Rules of the template code

These concern `src/expkit` and `scripts/launch`, the bookkeeping that came with the template.

- Python 3.12 and Hydra 1.3: one version of each, named in `.python-version` and
  `pyproject.toml`, and locked in `uv.lock`. Every server runs the same.
- One reader per language: Python reads `.env` with `expkit.config.load_env` and folders
  with `expkit.config.env_path` / `runs_dir`; bash uses `setting` in
  `scripts/launch/common.sh`. Do not parse `.env` anywhere else.
- The config is printed, saved and uploaded only through `expkit.redact.redact_config`.
- `scripts/launch/job_wrapper.sh` must stay independent of Python and `expkit`.
- The journal export and W&B must never make a job fail.
- LaTeX: `src/expkit/templates/macros.sty` defines which macros exist, the files in
  `templates/styles/` define how they look (every style defines the same commands, listed
  at the end of `macros.sty`). Generated entries contain macro calls, not formatting.
