# AGENTS.md

This file is for AI agents. For usage and installation instructions, see
[README.md](./README.md).

## Purpose and Precedence

This document gives repository-specific guidance for cbztojxl. General working
instructions adapted from the shared FlixMonkey guidance take precedence over
local conventions unless they conflict with Python best practice, the task
request, or established behavior in this repository.

## Project Overview

cbztojxl is a set of Python command-line utilities for converting and auditing
comic archives:

- `cbztojxl.py` converts JPEG pages from CBZ, ZIP, CBR, RAR, CB7, and 7Z input
  archives into lossless JXL pages in a CBZ output archive.
- `pdftocbz.py` creates conventional CBZ archives from PDF comics, preserving a
  directly extractable JPEG only when the page has no text and exactly one JPEG.
  Other pages are rendered to JPEG.
- `cbaudit.py` samples or scans JPEG pages in comic archives for corruption,
  inferred JPEG quality, and optional page-size issues.
- `zip_support.py` provides the shared safe, deterministic ZIP/CBZ extraction,
  counting, and writing helpers. It is a support module, not a standalone CLI.

The supported runtime is Python 3.10+. `cbztojxl.py` requires `cjxl` from
libjxl. CBR/RAR support requires `unrar` or `rar`, and CB7/7Z support requires
`7z`. `pdftocbz.py` requires the Poppler commands `pdfinfo`, `pdftotext`,
`pdfimages`, and `pdftocairo`. `cbaudit.py` requires ImageMagick's `identify`;
its RAR and 7Z support has the same optional archiver dependencies.

## Setup and Verification

Install Python 3.10+ and the external commands required by the utility being
worked on. The project has no package-manager setup step for its standard test
suite.

Run the full automated test suite with:

```bash
python3 -m unittest discover -v
```

For documentation-only changes, run the focused formatting and encoding checks
specified by the task. For behavior changes, run the full test suite and add or
update `unittest` coverage for the changed behavior.

## Architecture and Safety

Keep each CLI's argument parsing, dependency checks, discovery, processing, and
reporting behavior consistent with its existing module. Preserve documented exit
codes, result lines, diagnostics, deterministic lexical ordering, and output
path behavior.

Archive safety is mandatory. ZIP/CBZ extraction must continue to reject unsafe
member paths, including empty names, NUL bytes, backslashes, absolute paths,
drive-qualified paths, path traversal, and symbolic-link members. Extracted
paths must remain within the intended workspace. Do not replace the standard
library `zipfile` handling for ZIP/CBZ archives with external archiver commands.

Preserve stable POSIX-relative member ordering when writing archives. Create
outputs through a temporary file or workspace where the existing code does so,
and clean temporary directories before reporting success. Do not weaken output
path validation, overwrite protection, or in-place replacement safeguards.

`--dry-run` must report the planned action without modifying source archives,
creating outputs, extracting workspaces, converting pages, or writing archives.
Keep dry-run output and dependency behavior aligned with the individual CLI's
existing contract.

## Testing

Tests live in `tests/` and use the standard-library `unittest` framework. Test
files mirror the command-line modules: `test_cbztojxl.py`, `test_pdftocbz.py`,
and `test_cbaudit.py`.

Add focused tests for changed command-line behavior, archive safety, path
handling, cleanup, ordering, result reporting, and dry-run behavior as relevant.
Mock external commands and filesystem effects in unit tests rather than relying
on locally installed tools or real comic archives. Run the full `unittest`
command before reporting a behavior change as complete.

## General Working Conventions

- Update `README.md` when a change affects user-facing commands, options,
  dependencies, output, supported formats, or documented behavior.
- Use Conventional Commit messages in the form `type(scope)?: description`, in
  imperative mood. Common types are `feat`, `fix`, `docs`, `refactor`, `test`,
  `build`, `ci`, and `chore`.
- At task handoff, report the files changed, validation performed and its
  outcome, any remaining concerns, and a suggested Conventional Commit message.
- Use ASCII-only prose unless non-ASCII content is specifically required for a
  test case or user-facing content. Replace typographic punctuation and symbols
  with ASCII equivalents.
- Do not use em dashes. Use a colon, a semicolon, or separate sentences.
- Use the Oxford comma in prose.

## Python Conventions

- Target Python 3.10+ and use standard-library facilities unless a task calls
  for a dependency.
- Follow existing module style: `pathlib.Path` for paths, type annotations for
  public and nontrivial internal interfaces, `argparse` for CLIs, and focused
  docstrings for functions and classes.
- Keep command invocation explicit with argument lists. Preserve current error
  handling, stderr diagnostics, and exit-code behavior.
- Prefer small, testable helpers. Avoid unrelated refactoring and do not modify
  application code or tests for documentation-only tasks.
