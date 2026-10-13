---
name: audit
description: High-level review of the whole repository with fresh eyes - design, stale code, duplication, docs that no longer match. Reports, changes nothing.
argument-hint: "[optional focus, e.g. the data pipeline]"
disable-model-invocation: true
context: fork
model: opus
effort: high
---

# Audit the repository

Focus given by the user (empty means the whole project): $ARGUMENTS

You start without any history of this project, on purpose: judge what is in the repository,
as a stranger would who has to work with it tomorrow. Change no file. Submit no job, push
nothing, upload nothing.

## What to read

Everything tracked by git (`git ls-files`), starting with `README.md`, `CLAUDE.md` and
`CONTRIBUTING.md`: they state what the project wants to be, and you measure the code
against that. `git log --stat` shows which parts grew fast and which were not touched in a
long time.

`src/expkit/` and `scripts/launch/` are the bookkeeping that came with the template. Read
them to understand the project, but report on them only what is broken. The audit is about
the code of the project itself.

## What to look for

1. **Design.** Modules that do several jobs, or one job spread over several modules. Logic
   in `scripts/` that belongs in `src/`. Functions that pass a growing bag of arguments or
   an untyped dict. Constants in the code that should be in `conf/`. Two ways of doing the
   same thing that grew side by side.
2. **Stale code.** Functions, config keys, experiment files, tests and dependencies that
   nothing uses any more. Confirm with a search before you claim it.
3. **Mismatch.** README, docstrings and comments that describe an earlier state. Tests whose
   name promises something the body does not check.
4. **Risk to results.** Anything that could make a number in the paper wrong without an
   error: data leaking between splits, a seed that is not applied, a metric computed
   differently in two places, evaluation that depends on the batch size or on file order.
   This kind weighs more than all the others.
5. **Housekeeping.** Files that should be in `.gitignore`, large files in git, a place where
   a secret could reach a file or a log.

Do not report what `make check` already enforces (formatting, missing type hints, docstring
form), and do not report matters of taste.

## How to report

Reviewers always find something, and a refactoring always costs time and can break results
that were already obtained. So be selective:

- First, one paragraph: is the structure still sound for the size of the project, or has it
  outgrown its design? "It is fine, leave it" is a valid answer, and often the right one.
- Then at most ten findings, most important first. For each: file and line, what is wrong,
  what it costs to leave it, how large the change is (an hour, a day, a week), and whether
  the change could alter results.
- Mark each finding as confirmed (you ran or searched something) or suspected.
- If you recommend a larger redesign, sketch the target layout in a few lines, say which
  tests must exist first to prove that results stay the same, and in which order to do it
  so that every step leaves a working project.
- End with what you did not look at.
