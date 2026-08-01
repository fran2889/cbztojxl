# cbztojxl

Convert comic archive files (CBZ, CBR, CB7, ZIP, RAR, 7Z) containing JPEG images to JXL format using lossless compression.

## Installation

Requires:
- Python 3.10+
- [cjxl from libjxl](https://github.com/libjxl/libjxl)
- Optional: unrar/rar (for CBR/RAR support)
- Optional: p7zip/7z (for CB7/7Z support)

```bash
# For RAR support:
sudo apt-get install unrar
# For 7z support:
sudo apt-get install p7zip-full
# Then install libjxl (follow instructions at https://github.com/libjxl/libjxl)
```

## Usage

```bash
# Single file - output with _jxl suffix
python cbztojxl.py comic.cbz

# Directory - process all .cbz files in directory
python cbztojxl.py /path/to/comics/

# Directory recursive - process all .cbz files recursively
python cbztojxl.py /path/to/comics/ -r

# Mixed format directory (CBZ, ZIP, CBR, RAR, CB7, 7Z)
python cbztojxl.py /path/to/comics/ -r
# Output is always .cbz (ZIP-based) with JXL images

# Output to different directory - mirror structure, no suffix
python cbztojxl.py /path/to/comics/ /backup/ -r

# In-place conversion - replace original files
python cbztojxl.py /comics/ /comics/ -r -o

# Verbose mode
python cbztojxl.py comic.cbz -v

# Dry run - see what would happen
python cbztojxl.py /comics/ /backup/ -r --dry-run
```

## Options

| Option | Description |
|--------|-------------|
| `-r, --recursive` | Process directories recursively |
| `-o, --overwrite` | Overwrite existing output files |
| `-v, --verbose` | Print detailed logging |
| `--dry-run` | Show what would happen without making changes |
| `-h, --help` | Show help message |

## Output Behavior

- **No output directory specified:** Creates files next to source with `_jxl` suffix (e.g., `comic.cbz` → `comic_jxl.cbz`)
- **Output directory specified:** Creates files in output directory without suffix, preserving relative directory structure
- **Output directory = source directory + `--overwrite`:** Replaces original files in place

Every nonempty run prints a standard result line for each discovered archive,
followed by a total line with archive counts and the combined size reduction for
completed conversions:

```text
[done]  series/in.cbz => series/out.cbz | 24 pages | 100 B => 75 B (25.0% smaller)

[total] 4 archives | 2 done, 1 skipped, 1 failed | 150 B => 115 B (23.3% smaller)
```

Verbose mode retains these standard result and total lines while adding extraction,
per-page conversion, and archive-creation details. Temporary extraction directories
are created beneath the destination tree and removed before success is reported;
cleanup failures are reported as archive errors. Errors always include their detailed
diagnostic in both regular and verbose modes.

Archive paths, converted pages, and generated CBZ members are processed in
case-sensitive lexical order of their relative POSIX paths. ZIP timestamps and
metadata are preserved from source entries, so generated archives are not
promised to be byte-for-byte reproducible.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | CLI or dependency error |
| 2 | One or more conversion failures |
| 3 | No archive files found |

## Supported Formats

| Input Extension | Archive Type | Output Format | Tool Required |
|----------------|--------------|---------------|----------------|
| .cbz | ZIP | .cbz (ZIP) | Python standard library |
| .zip | ZIP | .cbz (ZIP) | Python standard library |
| .cbr | RAR | .cbz (ZIP) | unrar (optional) |
| .rar | RAR | .cbz (ZIP) | unrar (optional) |
| .cb7 | 7z | .cbz (ZIP) | 7z (optional) |
| .7z | 7z | .cbz (ZIP) | 7z (optional) |

**Note:** ZIP/CBZ input and output use Python's standard-library `zipfile`
module. Encrypted or unsupported ZIP variants fail with an archive error. If an
optional tool (unrar or 7z) is not installed, matching files are still discovered
and receive an `[skip] ... | archiver not available` result.

## PDF to CBZ conversion

`pdftocbz.py` creates a conventional CBZ with one JPEG per PDF page. It preserves an embedded JPEG unchanged when a page has no extractable text and exactly one JPEG image; every other page is rendered.

Requires Python 3.6+ and Poppler utilities (`pdfinfo`, `pdftotext`, `pdfimages`, `pdftocairo`).

```bash
# Create comic.cbz next to comic.pdf
python3 pdftocbz.py comic.pdf

# Convert a directory while preserving its structure in /backup
python3 pdftocbz.py /path/to/pdfs/ /backup/ -r

# Use a higher fallback rendering resolution and show per-page decisions
python3 pdftocbz.py comic.pdf --fallback-dpi 400 -v

# Inspect planned outputs without writing files
python3 pdftocbz.py /path/to/pdfs/ --dry-run
```

Each completed comic reports the number of unchanged embedded JPEGs extracted losslessly and the number of pages that were re-rendered:

```text
Created: comic.cbz (12 pages: 9 lossless, 3 re-rendered)
```

## Comic archive auditing

`cbaudit.py` checks sampled JPEG pages for corruption and inferred JPEG encoding quality. Use `--full-scan` to inspect every JPEG instead of five evenly spaced pages.

An optional page-size metric flags archives whose selected JPEG pages have a small average raw file size:

```bash
# Use the default 100 KB average threshold
python3 cbaudit.py comic.cbz --page-size

# Use a custom 150 KB average threshold
python3 cbaudit.py comic.cbz --page-size 150
```

Page-size checking is disabled unless `--page-size` is supplied. Sizes are measured after extraction, use 1 KB = 1,024 bytes, and complement rather than replace the JPEG-quality check.
