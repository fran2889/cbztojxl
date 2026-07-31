# PDF-to-CBZ Page Method Counts

## Goal

After successfully converting each PDF comic, report how many pages were copied losslessly from embedded JPEGs and how many were re-rendered.

## Output

The completion line will use this format, including zero-valued counts:

```text
Created: comic.cbz (12 pages: 9 lossless, 3 re-rendered)
```

Skipped files, dry runs, errors, and verbose per-page messages retain their current output.

## Design

`build_page_images()` will count the two existing page-processing branches while it creates page images. It will return an immutable result containing the total page count, lossless count, and re-rendered count. `process_pdf()` will use that result to construct the completion line after the CBZ is created.

This keeps classification at the point where the extraction/render decision is made and avoids mutable output parameters or attempting to infer the method from generated files.

## Testing

A regression test will exercise a conversion with both processing branches and assert the returned counts. A completion-line test will assert the exact requested text. The full existing test suite will then be run.
