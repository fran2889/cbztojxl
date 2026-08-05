# Replace-source conversion design

## Purpose

Add an explicit `--replace-source` mode for users who want conversion to leave
only the resulting CBZ archive. The existing behavior remains unchanged unless
the new option is selected.

## Command-line contract

`--replace-source` is mutually exclusive with the optional `output_dir`
positional argument. It always writes the output next to the source archive,
using the source stem and a `.cbz` extension:

- `book.cbz` becomes `book.cbz`.
- `book.cbr` becomes `book.cbz`.

The option implies overwrite behavior. Supplying `--overwrite` remains valid,
but has no additional effect. Ordinary invocations without an output directory
continue to create the `_jxl.cbz` sibling output.

## Processing and safety

The converter must write the destination through the existing staged,
same-directory archive creation mechanism. A CBZ input is therefore replaced
atomically by the final destination commit.

For every non-CBZ input, remove the source only after archive creation succeeds
and the resulting output can be statted. Do not remove a source when conversion,
archive creation, output validation, or output stat fails. The source must also
remain if deletion itself fails; report that case as an error while leaving the
successful output in place.

`--dry-run` must report the planned replacement conversion, but it must not
write an output or delete a source.

## Collisions and reporting

Output-path collision detection applies before any input is processed. For
example, `book.cbz` and `book.cbr` in the same directory both target
`book.cbz` under `--replace-source`, so both are skipped. This avoids
order-dependent replacement or deletion.

Successful non-CBZ replacement reports the source-to-CBZ conversion normally.
Deletion failures use an error status and diagnostic that makes clear the
converted CBZ remains while the source was retained.

## Documentation and tests

Add help text for `--replace-source` and update the README's examples and
output behavior section. Tests cover parser rejection when an output directory
is supplied, unsuffixed replacement paths, implicit overwrite, dry-run
non-mutation, source deletion after success, preservation after failures, and
collision handling.
