# Output-path collision handling design

## Scope

`cbztojxl.py` will identify output destinations for all discovered archives
before processing any archive. This prevents source formats that share a stem,
such as `book.cbz` and `book.cbr`, from writing the same `book.cbz`
destination when an output directory is supplied.

## Discovery and preflight

`find_archive_files()` will keep its existing POSIX-relative lexical ordering.
For a recursive directory input, it will accept the output directory as an
optional exclusion and omit that directory and every descendant when the output
tree is lexically inside the input tree. This prevents files created in a
previous run from being discovered as source archives.

After discovery, `main()` will calculate `compute_output_path()` for every
archive. Destinations with more than one input form a collision group.

## Collision behavior

Every archive in a collision group will be skipped. A clear, deterministic
skip result will identify the source and destination and state that the output
path collides with another input. No member of a collision group will call
`process_archive()`, so it cannot inspect, extract, convert, create, or
overwrite an output. Non-colliding archives will continue through the existing
processing flow.

Collision skips contribute to the final skipped count and preserve the existing
successful exit status when no unrelated conversion fails.

## Tests and documentation

Focused unit tests will verify that colliding paths are skipped as a group,
processing is never invoked for those inputs, the output tree is excluded from
recursive discovery, and non-colliding inputs retain lexical ordering. README
output behavior documentation will explain that inputs mapping to the same
destination are skipped.
