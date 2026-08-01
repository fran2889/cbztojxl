# AGENTS.md Design

## Goal

Create a repository-root `AGENTS.md` that gives AI agents accurate guidance for
the cbztojxl Python command-line utilities.

## Content

The document will contain:

- A precedence rule: the general instructions adapted from FlixMonkey override
  local conventions unless they conflict with Python best practice.
- Project-specific context for `cbztojxl.py`, `pdftocbz.py`, `cbaudit.py`, and
  `zip_support.py`.
- The supported Python version, external command dependencies, and test command.
- Guidance for archive handling, deterministic member ordering, temporary-file
  cleanup, exit codes, CLI output, and dry-run behavior.
- Testing expectations using the standard-library `unittest` suite.
- General working rules adapted from FlixMonkey: update README documentation
  when user-facing behavior changes, propose a Conventional Commit message at
  task completion, use ASCII-only prose, avoid em dashes, and use the Oxford
  comma.

## Exclusions

Do not copy FlixMonkey details that apply only to its JavaScript browser
extension, its build tooling, or Netflix-specific test architecture.

## Verification

Review `AGENTS.md` for completeness and ASCII-only text. No executable code is
changed, so the test suite is not required for this documentation-only change.
