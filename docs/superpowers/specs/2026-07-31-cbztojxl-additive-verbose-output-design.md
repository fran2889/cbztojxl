# Additive Verbose Output Design

## Goal

Make `--verbose` additive: it preserves the durable regular output and adds operation details. The only regular-mode element omitted in verbose mode is the transient progress bar, because per-page verbose messages replace it.

## Paths

- Display archive input paths relative to the input file or directory.
- Display output archive paths relative to the output directory.
- Create each temporary extraction directory beside its destination archive,
  within the output directory tree.
- Display temporary extraction paths relative to the output root.
- Display converted page paths relative to the extracted archive root, including every parent directory for nested pages.

## Regular Output

Print one compact line per archive without blank lines between archives:

```text
[done]  series/volume01.cbz => series/volume01.cbz | 24 pages | 48.0 MB => 34.2 MB (28.8% smaller)
[error] series/volume02.cbz | convert page 7/22: chapter02/page007.jpg failed
        cjxl exited with status 1: could not decode JPEG input
[skip]  series/volume03.cbz => series/volume03.cbz | output already exists

[total] 3 archives | 1 done, 1 skipped, 1 failed | 48.0 MB => 34.2 MB (28.8% smaller)
```

- Status comes first in ASCII brackets.
- Use `=>` for input-to-output and size transitions.
- Use `|` only to separate major fields.
- Do not prefix progress or outcomes with `Processing:`.
- Use `page`/`pages`, never `image`/`images`.
- Do not include page counts in the total line.
- Insert one blank line before `[total]`, but none between archive results.

The live regular-mode progress display uses the relative input path:

```text
series/volume01.cbz [1/3] |=============       | 16/24
```

## Verbose Output

Verbose mode adds details while retaining the same final archive result and total lines:

```text
series/volume01.cbz
  Extracting to: series/.cbztojxl_tmp_abcd1234
  Converting page 1/24: chapter01/page001.jpg
  Converting page 2/24: chapter01/page002.jpg
  Creating: series/volume01.cbz
[done]  series/volume01.cbz => series/volume01.cbz | 24 pages | 48.0 MB => 34.2 MB (28.8% smaller)
```

Remove the redundant `Converting JPEGs to JXL` message. Do not print the live progress bar in verbose mode.

When no explicit output directory is supplied, use the source archive's parent
as the effective output root. Temporary-directory cleanup remains automatic on
success and failure.

## Errors

Error detail is identical in regular and verbose modes and is always printed. Do not print executed command lines.

```text
[error] series/volume02.cbz | extract archive failed
        unzip exited with status 9: end-of-central-directory signature not found

[error] series/volume02.cbz | convert page 7/22: chapter02/page007.jpg failed
        cjxl exited with status 1: could not decode JPEG input

[error] series/volume02.cbz => series/volume02.cbz | create archive failed
        zip exited with status 15: could not create output file
```

Capture and surface concise subprocess diagnostics for extraction, conversion, and archive creation. Do not repeat a separate filename-only failure list after processing; the `[total]` line supplies aggregate counts. Processing errors retain the existing nonzero exit status.

## Testing

Automated tests cover regular and verbose success output, relative nested paths,
temporary extraction beside the destination archive, progress labels, skip
output, all three error stages and their subprocess details, total output
without page counts, removal of legacy wording, cleanup, and unchanged exit
behavior.
