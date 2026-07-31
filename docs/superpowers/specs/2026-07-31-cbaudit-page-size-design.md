# Design: Optional Page-Size Quality Metric for `cbaudit.py`

**Date:** 2026-07-31

## Goal

Complement `cbaudit.py`'s JPEG quality estimate with an optional, easy-to-understand size-per-page metric. The metric identifies archives whose sampled JPEG pages have an unusually small average file size, which can indicate low resolution or aggressive compression.

The page-size check is opt-in. Existing behavior and output remain unchanged unless the user supplies `--page-size`.

## Command-Line Interface

Add an optional-value argument:

```text
--page-size [KB]
```

Examples:

```bash
# Enable the metric with its default threshold of 100 KB
python3 cbaudit.py comic.cbz --page-size

# Enable it with a custom threshold of 150 KB
python3 cbaudit.py comic.cbz --page-size 150
```

The argument accepts only positive integers. Zero, negative, and non-numeric values are command-line errors. When omitted, the page-size metric is disabled.

## Metric Definition

The metric uses the raw extracted size of each selected JPEG, independent of the archive container's compression.

It operates on the exact same selected JPEG files as the existing ImageMagick quality scan:

- Default scan: five evenly spaced JPEG pages, or every page if the archive contains five or fewer.
- `--full-scan`: every JPEG page.

For the selected pages:

1. Read each file's size in bytes.
2. Compute the arithmetic mean in bytes.
3. Compare that unrounded mean with `threshold_kb * 1024`.

An archive has small pages when its average is strictly below the threshold. Equality passes. Corrupt selected files remain in the size calculation because their on-disk sizes are measurable.

The default threshold is **100 KB per page**, where one KB is 1,024 bytes. This deliberately conservative default aims to identify unusually small comic pages without treating ordinary manga, monochrome pages, or simple artwork as inherently defective.

Archives with no JPEG images are not classified as having small pages, consistent with the current no-JPEG behavior.

## Classification and Reporting

The new independent issue classification is `SMALL PAGES`. It composes with the existing classifications in this fixed order:

```text
UNREADABLE + LOW QUALITY + SMALL PAGES
```

When page-size checking is enabled, verbose output includes the rounded average and configured threshold:

```text
Average page size: 184 KB (threshold: 100 KB)
```

If the metric fails, compact output includes the rounded average:

```text
comic.cbz: SMALL PAGES (avg page=82 KB)
```

Combined example:

```text
comic.cbz: LOW QUALITY + SMALL PAGES (avg=65, avg page=82 KB)
```

Display values are rounded to the nearest whole KB. Classification always uses the unrounded byte average, so display rounding cannot change pass/fail behavior.

`SMALL PAGES` contributes to the existing per-archive issue result, overall issue count, summary, and exit status in the same manner as corruption and low quality.

When `--page-size` is absent, no size calculation needs to be reported and all current output remains byte-for-byte unchanged for equivalent inputs.

## Implementation Boundaries

Keep the feature within the existing single-file architecture:

- Argument parsing enables the metric and supplies either the default or custom threshold.
- Archive processing obtains sizes from the already extracted and selected JPEG paths; it performs no additional extraction or image decoding.
- Reporting receives the optional threshold and page-size values, derives the `SMALL PAGES` state, and composes it with existing states.

The feature does not measure archive-compressed size, normalize by image dimensions, inspect non-JPEG pages, or replace the existing JPEG quality estimate.

## Error Handling

- Reject invalid `--page-size` values through `argparse` with its standard usage error and exit code.
- If a selected file disappears or its metadata cannot be read after extraction, treat processing of that archive as failed rather than silently calculating an average from a different sample.
- Preserve current extraction, corruption, missing-dependency, and no-JPEG handling.

## Testing

Automated tests should verify:

- Omitting `--page-size` preserves existing behavior.
- Bare `--page-size` selects the 100 KB default.
- `--page-size 150` selects a 150 KB custom threshold.
- Zero, negative, and non-numeric thresholds are rejected.
- A mean below the threshold produces `SMALL PAGES`.
- A mean exactly equal to the threshold passes.
- The unrounded byte mean controls classification while output is rounded to whole KB.
- Default sampling uses the same five selected files for quality and page size.
- `--full-scan` includes every JPEG in both metrics.
- Corrupt selected files are included in the size mean.
- No-JPEG archives are not marked `SMALL PAGES`.
- Verbose and compact reports show the new values only when enabled.
- `SMALL PAGES` combines in the specified order with `UNREADABLE` and `LOW QUALITY`.
- A page-size-only failure affects issue totals and the existing nonzero issue exit status.
- A metadata-read failure causes archive processing to fail visibly.

