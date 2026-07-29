# Design: cbaudit.py - Comic Archive Quality Audit Script

**Date:** 2026-07-29  
**Status:** Approved  
**Related:** cbztojxl.py (reference for structure and patterns)

---

## Overview

Create a new script `cbaudit.py` that audits comic archive files (CBZ, CBR, CB7) for image quality. The script will use `jpeginfo` to detect corruption and estimate JPEG encoding quality, reporting archives with low quality or corrupted images.

**Note for future enhancement:** BRISQUE (via OpenCV) could be added later for more accurate perceptual quality assessment.

---

## Requirements

### Functional Requirements

1. **Archive Support:** Support same formats as cbztojxl (CBZ/ZIP, CBR/RAR, CB7/7Z)
2. **Two Scan Modes:**
   - **Default scan:** Sample 5 evenly spaced JPEG images from each archive
   - **Full scan (`--full-scan`):** Check all JPEG images in each archive
3. **Quality Assessment:**
   - Use `jpeginfo -v -c` to check each image
   - Corruption: binary pass/fail
   - Quality: numeric estimate (1-100, from encoding settings)
4. **Quality Threshold:**
   - Default: 70
   - Overrideable via `-t/--threshold N` CLI argument
5. **Status Classification:**
   - **UNREADABLE:** Archive contains at least one corrupted image
   - **LOW QUALITY:** Average quality of sampled/scanned images is below threshold
   - **OK:** No corruption, average quality >= threshold
6. **Reporting:**
   - **Non-verbose (default):** Only print archives with issues
   - **Verbose (`-v`):** Print all archives with details
   - Text output to stdout (no file output)
   - Verbose mode lists all corrupted image filenames

### Non-Functional Requirements

- Follow same structure and patterns as `cbztojxl.py`
- Reuse temp directory cleanup pattern
- Progress bars: file-level for quick scan, image-level for full scan
- Handle errors gracefully, continue processing other archives

---

## CLI Interface

```
cbaudit.py [OPTIONS] <input>

Arguments:
  input    Comic archive file or directory containing archives
            (supports: .cbz, .zip, .cbr, .rar, .cb7, .7z)

Options:
  --full-scan        Scan all images in each archive (default: sample 5)
  -t, --threshold N  Quality threshold for LOW QUALITY classification (default: 70)
  -r, --recursive    Process directories recursively
  -v, --verbose      Print detailed output for all archives
  --dry-run          Show what would be scanned without running
```

**No output directory argument** — results print to stdout only.

---

## Architecture

### Script Structure

Single file: `cbaudit.py` in repository root, mirroring `cbztojxl.py` structure.

### Key Components

1. **Argument Parsing** (`parse_args()`): Handle CLI options
2. **Dependency Check** (`check_dependencies()`): Verify `jpeginfo`, `unzip`, and optional archive tools
3. **Archive Discovery** (`find_archive_files()`): Reuse from cbztojxl or duplicate logic
4. **Temp Directory Management** (`temp_dir()` context manager): Same as cbztojxl
5. **Archive Processing** (`process_archive()`): Extract, scan, report
6. **Image Scanning** (`scan_images()`): Run jpeginfo on selected images
7. **Reporting** (`print_report()`): Format and output results

---

## Detailed Design

### Archive Processing Flow

```
1. Parse arguments
2. check_dependencies()
   - Verify jpeginfo is available
   - Verify unzip is available
   - Check optional: unrar, 7z
3. find_archive_files(input_path, recursive)
4. For each archive:
   a. with temp_dir(archive_path) as temp_path:
      - extract_archive(archive, temp_path, fmt_config)
      - find all .jpg/.jpeg files (exclude AppleDouble)
      - sort by name/path for deterministic sampling
      - if --full-scan: select all images
      - else: select 5 evenly spaced images
      - for each selected image:
          * run: jpeginfo -v -c <image_path>
          * parse: corruption status, quality estimate
      - aggregate results
      - determine status
      - print_report(archive, results, verbose)
5. Print summary
```

### Sampling Algorithm

For N total images, sample 5 evenly spaced:

```python
def get_sample_indices(total: int, count: int = 5) -> list[int]:
    """Return count evenly spaced indices for total images."""
    if total <= count:
        return list(range(total))
    step = total / count
    return [int(i * step) for i in range(count)]

# Example: 20 images -> [0, 4, 8, 12, 16]
# Example:  8 images -> [0, 1, 3, 4, 6]
```

### jpeginfo Parsing

Example `jpeginfo -v -c` output:
```
[OK] myimage.jpg: 85% quality, RGB, 1920x1080
```

Parse to extract:
- Status: OK or CORRUPT
- Quality: integer percentage

**Implementation:** Use subprocess with `capture_output=True`, parse stdout.

### Status Determination

```python
is_unreadable = corrupted_count > 0
is_low_quality = average_quality < threshold

if is_unreadable and is_low_quality:
    status = "UNREADABLE + LOW QUALITY"
elif is_unreadable:
    status = "UNREADABLE"
elif is_low_quality:
    status = "LOW QUALITY"
else:
    status = "OK"
```

### Reporting Format

**Non-verbose mode (default):** Only archives with issues
```
mycomic.cbz: LOW QUALITY (avg=65, threshold=70)
badcomic.cbz: UNREADABLE (1 corrupted image)
bothissues.cbz: UNREADABLE + LOW QUALITY (1 corrupted, avg=60)
```

**Verbose mode:** All archives
```
Scanning 10 archives...

archive1.cbz [OK]
  Sampled 5/20 images, avg quality: 85

archive2.cbz [LOW QUALITY]
  Sampled 5/15 images, avg quality: 65
  Low quality: 3/5 images below threshold 70

archive3.cbz [UNREADABLE]
  Sampled 5/12 images
  Corrupted images:
    - page_001.jpg
    - page_007.jpg

archive4.cbz [OK]
  Sampled 5/8 images, avg quality: 92

Done. 2 archives with issues.
```

### Progress Bars

- **File-level progress:** `Scanning [3/10]` — shown during archive enumeration
- **Full scan image progress:** `Processing: archive.cbz [image 15/200] |=====     |` — same style as cbztojxl
- **Default scan:** Only file-level progress (5 images is fast)

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `jpeginfo` missing | Print error with install instructions, exit 1 |
| Archive extraction fails | Log error, skip archive, continue with others |
| `jpeginfo` fails on image | Count as corrupted, log to stderr if verbose, continue |
| No JPEG files in archive | Skip with note in verbose mode, continue |
| Input not found | Print error, exit 1 |

---

## Dependencies

### Mandatory CLI Tools
- `jpeginfo` — JPEG quality and corruption checking
- `unzip` — CBZ/ZIP extraction

### Optional CLI Tools
- `unrar` — CBR/RAR extraction
- `7z` — CB7/7Z extraction

### Python Dependencies
- Standard library only (same as cbztojxl)

---

## Future Enhancements

1. **BRISQUE Support:** Add `--brisque` flag to use OpenCV's BRISQUE for perceptual quality scoring
2. **JSON Output:** Add `--json` flag for programmatic consumption
3. **Report Files:** Add `--output-file` to save reports to disk
4. **Batch Mode:** Process multiple directories with aggregated reports
5. **Quality Histogram:** Show distribution of quality scores

---

## Implementation Notes

- Reuse `ARCHIVE_FORMATS` and `get_format_config()` from cbztojxl or duplicate
- Reuse `temp_dir()` context manager exactly
- Reuse `is_appledouble_path()` for filtering
- Follow same coding style and conventions

---

## File Location

- Script: `/cbaudit.py` (repo root)
- Spec: `/docs/superpowers/specs/2026-07-29-cbaudit-design.md`

---

## Approval

All design sections approved by user on 2026-07-29.
