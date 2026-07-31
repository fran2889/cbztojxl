# PDF-to-CBZ Converter Design

**Date:** 2026-07-31  
**Status:** Approved design — pending written-spec review  
**Related:** `cbztojxl.py`

## Overview

Add a standalone `pdftocbz.py` command-line script that converts PDF comic files to conventional ZIP-based CBZ archives. The archive contains exactly one JPEG image per input PDF page, in page order.

The script preserves an embedded JPEG unchanged when the corresponding page has no extractable text and contains exactly one usable embedded JPEG. Pages containing text, pages with zero or multiple embedded JPEGs, and pages whose only image is not JPEG are rendered as full pages to JPEG. This preserves original artwork where it is unambiguous while keeping text and complex layouts intact.

The implementation uses only Python's standard library plus external command-line tools. It adds no Python package dependencies.

## User Interface

`pdftocbz.py` mirrors the interface and behavior of `cbztojxl.py`:

```text
python pdftocbz.py INPUT [OUTPUT_DIR] [-r] [-o] [-v] [--dry-run]
```

Arguments and options:

| Option | Behavior |
| --- | --- |
| `input` | A single PDF file or a directory containing PDFs. |
| `output_dir` | Optional destination directory. When given, retain the input-relative directory layout. |
| `-r`, `--recursive` | Search input directories recursively. |
| `-o`, `--overwrite` | Replace an existing CBZ output. |
| `-v`, `--verbose` | Print detailed per-file and per-page decisions. |
| `--dry-run` | Report intended actions without creating output. |
| `--fallback-dpi DPI` | DPI for rendered pages without a usable primary-image DPI; default: 300. |
| `--version` | Print the script version. |

Output naming:

- With no `output_dir`, `/comics/story.pdf` becomes `/comics/story.cbz`.
- With `output_dir`, `/source/series/story.pdf` and `/target` become `/target/series/story.cbz`.
- A same-named PDF and CBZ never collide as source files; an existing output CBZ is skipped unless `--overwrite` is supplied.
- PDF discovery accepts `.pdf` case-insensitively and ignores existing CBZ files.

## Dependencies

The script requires Poppler command-line utilities and ZIP:

- `pdfinfo` for page count and PDF metadata.
- `pdftotext` for text detection.
- `pdfimages` for embedded-image metadata and direct JPEG extraction.
- `pdftocairo` for full-page JPEG rendering.
- `zip` for writing the CBZ archive.

Missing dependencies are reported before processing and cause exit code 1. The README will document package installation as Poppler utilities plus ZIP, using the platform package manager.

## Processing Pipeline

For each PDF, create a temporary working directory and build one numbered JPEG per page.

1. Determine the page count with `pdfinfo`.
2. Obtain embedded-image metadata with `pdfimages -list` and associate records with PDF pages.
3. For every page, run `pdftotext` for that page and treat non-whitespace output as text content.
4. Classify the page:
   - **Direct extraction:** no text and exactly one usable embedded JPEG record. Extract the PDF images with `pdfimages -j` and copy the matching JPEG unchanged into the page sequence.
   - **Rendering:** any text; zero or multiple JPEGs; no JPEG; or ambiguous/failed extraction. Render the page with `pdftocairo -jpeg`.
5. Choose rendering DPI:
   - Prefer the primary image record's reported X/Y PPI for that page when usable. The primary record is the page's JPEG with the largest pixel area; use a single DPI derived from its X/Y PPI.
   - Otherwise use `--fallback-dpi`, default 300.
6. Rendered pages use JPEG quality 95.
7. Place every final page image under zero-padded sequential names such as `0001.jpg`, then create a ZIP archive with `.cbz` extension.
8. Write the archive atomically: create it in temporary output and rename it only after ZIP succeeds. Always remove temporary working files.

The direct-extraction condition is deliberately conservative. A PDF page can contain decoration, masks, panels, or multiple artwork objects; rendering prevents the converter from producing an incomplete comic page in those cases.

## Error Handling and Exit Codes

| Code | Meaning |
| --- | --- |
| 0 | All requested PDFs were converted successfully, or dry-run completed successfully. |
| 1 | Invalid CLI use, invalid input path, or missing required dependency. |
| 2 | One or more PDF conversions failed. |
| 3 | A directory input contained no PDFs. |

For a single PDF, processing errors are printed with the PDF path and command failure context, then exit 2. For a directory, failures are recorded per PDF, processing continues, and the final result is 2 if any conversion failed. If a page's direct extraction fails or is ambiguous, the script falls back to rendering that page; a rendering failure fails that PDF.

`--dry-run` checks inputs and dependencies, computes every output path, and reports intended per-file action, but performs no conversion, extraction, rendering, archive writing, or overwrite.

## Testing and Verification

Verification will cover:

- An image-only, single-JPEG-per-page PDF: confirm each CBZ image is byte-identical to the embedded JPEG.
- Pages with text over scanned art: confirm a full rendered page is used, with text visible.
- No-text pages with zero, multiple, or non-JPEG image objects: confirm rendering fallback and one output image per page.
- DPI selection from a primary embedded image and 300-DPI fallback.
- Single-file output naming, output-directory mirroring, existing-output skip/overwrite, directory and recursive discovery, and dry-run behavior.
- Missing tools, corrupt PDFs, page rendering failures, and archive failures with the documented exit codes.

## Out of Scope

- Converting page images to JXL or other formats.
- Supporting non-PDF inputs.
- OCR; text detection relies only on extractable PDF text.
- Preserving PDF annotations, forms, bookmarks, or metadata in the CBZ.
