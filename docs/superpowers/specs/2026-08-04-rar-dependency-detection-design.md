# RAR Dependency Detection Design

## Goal

Make `unrar` the only supported executable for CBR and RAR archive support, so
dependency detection matches the commands that the utilities execute.

## Scope

The change applies to `cbztojxl.py`, `cbaudit.py`, their focused unit tests,
and the user-facing dependency wording in `README.md`.

## Design

Both utilities will define the optional RAR dependency as the single command
`unrar`. Their existing RAR format configurations already invoke `unrar` for
listing and extraction, so those commands remain unchanged. If `unrar` is not
available, the existing warning and RAR-format filtering behavior remains in
place, including when a program named `rar` is available.

The README will identify `unrar` as the optional dependency for CBR and RAR
support. It will no longer imply that `rar` is supported.

## Testing

Focused tests will mock tool availability and verify that `rar` alone does not
enable RAR formats, while `unrar` does. The full standard-library unittest
suite will then be run.

## Constraints

- Target Python 3.10+ and use only the standard library.
- Preserve current archive commands, warnings, format filtering, exit codes,
  and dry-run behavior.
- Keep user-facing prose ASCII-only.
