# CBZ to JXL Dry-Run Simplification Design

## Goal

Make `cbztojxl.py --dry-run` follow the same read-only decision path as a normal run while guaranteeing that it performs no filesystem writes, extraction, conversion, deletion, or archive creation.

## Processing Flow

`process_archive` will use one shared path to:

1. Resolve the input archive and read its size.
2. Verify that its archive format is available.
3. Count its JPEG images and skip archives with none.
4. Compute the intended output path.
5. Apply the normal existing-output check, including `--overwrite` behavior.

Only after those decisions will dry-run diverge. A dry-run archive that would otherwise be processed will emit the same final success output as a normal run and return successfully without creating a temporary directory or invoking extraction, JPEG conversion, deletion, or CBZ creation.

## Reporting

Dry-run will not guess a compression ratio. It will use the input byte count as the output byte count, producing a 0.0% size reduction in the existing summary format. Its final per-file output, total summary, verbose success details, and skip messages will otherwise match a normal run. A live per-image progress bar is not emitted because no conversion occurs; this does not change the final output line.

Existing outputs without `--overwrite` will be reported as skipped exactly as in a normal run.

## Implementation Scope

Keep `dry_run` as the flag passed into `process_archive`. Move the existing-output decision before the dry-run return, and keep a single dry-run guard immediately before the mutation phase. Do not add dry-run branches to extraction, conversion, or archive-writing helpers.

## Tests

Add focused tests proving that:

- dry-run skips an existing output when overwrite is disabled;
- dry-run treats an existing output as processable when overwrite is enabled;
- dry-run reports equal input and output sizes;
- dry-run emits the same final success details as a normal run apart from the substituted output size;
- dry-run never enters extraction, conversion, or output archive creation.

Normal conversion behavior remains unchanged.
