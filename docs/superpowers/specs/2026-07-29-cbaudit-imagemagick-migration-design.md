# Design: Migrate cbaudit.py from jpeginfo to ImageMagick

**Date:** 2026-07-29  
**Status:** Approved  
**Related:** cbaudit.py, 2026-07-29-cbaudit-design.md (original spec)  
**Replaces:** jpeginfo dependency with imagemagick

---

## Overview

Migrate `cbaudit.py` from using `jpeginfo` to using `imagemagick`'s `identify` command for both JPEG quality extraction and corruption detection. This change addresses the fundamental limitation that `jpeginfo` does not return quality information, and reduces the tool dependency count by consolidating both checks into a single tool.

---

## Problem Statement

The current `cbaudit.py` implementation has the following issues:

1. **jpeginfo does not support quality information**: Despite the original design assuming `jpeginfo -v -c` would return quality data, the tool does not actually provide this information in its output.
2. **Unreliable parsing**: The current code attempts to parse quality from jpeginfo output using regex patterns that don't match actual jpeginfo behavior.
3. **Redundant dependencies**: Using a separate tool (jpeginfo) for JPEG-specific checks when ImageMagick can handle both quality and corruption detection.

---

## Requirements

### Functional Requirements

1. **Quality Extraction**: Extract numeric quality value (1-100) from JPEG files using `identify -format "%Q"`
2. **Corruption Detection**: Use strict definition — file is corrupted if:
   - `identify` returns non-zero exit code, OR
   - stderr contains "error", "corrupt", or "insufficient image data" keywords
3. **Scan Workflow**:
   - **Quick scan (default)**: Extract 5 evenly spaced JPEG images, check both integrity and quality on all 5
   - **Full scan (`--full-scan`)**: Extract ALL JPEG images, check both integrity and quality on ALL
4. **Dependency Update**: Replace `jpeginfo` with `imagemagick` (which provides `identify`)

### Non-Functional Requirements

- Maintain existing CLI interface (no breaking changes)
- Maintain existing output format and status classifications
- Preserve all existing error handling behavior for archive operations
- Minimal code changes to reduce risk

---

## CLI Interface

**No changes to CLI.** Existing interface remains:

```
cbaudit.py [OPTIONS] <input>

Arguments:
  input    Comic archive file or directory containing archives

Options:
  --full-scan        Scan all images in each archive (default: sample 5)
  -t, --threshold N  Quality threshold for LOW QUALITY classification (default: 70)
  -r, --recursive    Process directories recursively
  -v, --verbose      Print detailed output for all archives
  --dry-run          Show what would be scanned without running
```

**Updated help description:**
```
Audit comic archives (CBZ, ZIP, CBR, RAR, CB7, 7Z) for JPEG image quality and corruption using ImageMagick.
```

---

## Architecture

### Component Changes

| Aspect | Current | New |
|--------|---------|-----|
| Quality tool | `jpeginfo -v -c` | `identify -format "%Q"` |
| Corruption tool | `jpeginfo` exit code + output | `identify` exit code + stderr |
| Dependencies | jpeginfo, unzip | identify (imagemagick), unzip |
| Quick scan | Sample 5 images | Sample 5 images, check both integrity+quality |
| Full scan | Sample 5 for quality, all for integrity | All images, check both integrity+quality |

### Key Insight

One `identify -format "%Q"` subprocess call provides:
- **stdout**: Numeric quality value (e.g., "85") or empty string
- **stderr**: Error/warning messages if file is corrupted
- **returncode**: Non-zero for fatal errors, zero for decodable files (even with warnings)

For strict corruption detection, we check: `returncode != 0 OR stderr contains error keywords`

---

## Detailed Design

### Archive Processing Flow

#### Quick Scan Flow:
```
1. Parse arguments
2. check_dependencies() - verify identify, unzip available
3. find_archive_files(input_path, recursive)
4. For each archive:
   a. with temp_dir(archive_path) as temp_path:
      - extract_archive(archive, temp_path, fmt_config)
      - find all .jpg/.jpeg files (exclude AppleDouble)
      - sort by name/path for deterministic sampling
      - select 5 evenly spaced images
      - for each selected image:
        * run: identify -format "%Q" <image_path>
        * capture: stdout (quality), stderr, returncode
        * is_corrupted = returncode != 0 or stderr contains error keywords
        * quality = int(stdout) if stdout not empty else None
      - aggregate: corrupted_count, quality_scores
      - calculate: avg_quality, determine status
      - print_report(archive, results, verbose)
5. Print summary
```

#### Full Scan Flow:
```
1-4. Same as quick scan through extraction
5. For each archive:
   a. with temp_dir(archive_path) as temp_path:
      - extract_archive(archive, temp_path, fmt_config)
      - find all .jpg/.jpeg files (exclude AppleDouble)
      - sort by name/path for deterministic order
      - for EACH image (not sampled):
        * run: identify -format "%Q" <image_path>
        * capture: stdout (quality), stderr, returncode
        * is_corrupted = returncode != 0 or stderr contains error keywords
        * quality = int(stdout) if stdout not empty else None
      - aggregate across ALL images
      - calculate: avg_quality, determine status
      - print_report(archive, results, verbose)
6. Print summary
```

### Corruption Detection Logic

```python
STRICT_CORRUPTION_PATTERNS = ['error', 'corrupt', 'insufficient image data']

def is_corrupted(returncode: int, stderr: str) -> bool:
    stderr_lower = stderr.lower()
    return (
        returncode != 0
        or any(pattern in stderr_lower for pattern in STRICT_CORRUPTION_PATTERNS)
    )
```

**Strict mode rationale:** If ImageMagick detects any corruption (even if the file is partially decodable), we treat it as corrupted. This is appropriate for an audit tool where data integrity is paramount.

### Quality Extraction Logic

```python
def extract_quality(stdout: str) -> int | None:
    quality_str = stdout.strip()
    if not quality_str:
        return None
    try:
        return int(quality_str)
    except ValueError:
        return None
```

**Note:** `identify -format "%Q"` returns an empty string for non-JPEG files or completely corrupted files. We return `None` in these cases.

### Status Classification (unchanged)

```python
is_unreadable = corrupted_count > 0
is_low_quality = avg_quality < threshold

if is_unreadable and is_low_quality:
    status = "UNREADABLE + LOW QUALITY"
elif is_unreadable:
    status = "UNREADABLE"
elif is_low_quality:
    status = "LOW QUALITY"
else:
    status = "OK"
```

---

## Error Handling

### Identify Command Scenarios

| Scenario | identify behavior | cbaudit handling |
|----------|------------------|------------------|
| File doesn't exist | Exit 1, error on stderr | Mark as corrupted, log stderr if verbose |
| Not a valid image | Exit 1, error on stderr | Mark as corrupted, log stderr if verbose |
| Valid but partially corrupted (warnings) | Exit 0, warnings on stderr | **Mark as corrupted** (strict mode) |
| Valid JPEG, no issues | Exit 0, quality on stdout | Mark as OK, use quality value |
| identify command not found | FileNotFoundError | Exit with dependency error in check_dependencies() |

### Archive Processing Errors (unchanged)

| Scenario | Behavior |
|----------|----------|
| Archive extraction fails | Log error, skip archive, continue with others |
| No JPEG files in archive | Skip with note in verbose mode, continue |
| Input not found | Print error, exit 1 |

---

## Dependencies

### Mandatory CLI Tools
- `identify` — From ImageMagick suite, for quality extraction and corruption checking
- `unzip` — CBZ/ZIP extraction (unchanged)

### Optional CLI Tools (unchanged)
- `unrar` — CBR/RAR extraction
- `7z` — CB7/7Z extraction

### Python Dependencies
- Standard library only (unchanged)

---

## Testing

### Test Strategy

1. **Unit tests for `scan_image()`**:
   - Valid JPEG with known quality → returns (True, quality_value)
   - Corrupted file → returns (False, None)
   - Non-JPEG file → returns (False, None)
   - File with partial corruption (warnings only) → returns (False, quality_value)

2. **Integration tests**:
   - Quick scan on archive with 20 images → extracts 5, checks all 5
   - Full scan on archive with 20 images → extracts all 20, checks all 20
   - Mixed archive (some corrupted, some low quality) → correct classification
   - Empty archive (no JPEGs) → skip with verbose note

3. **Test file generation**:
   ```bash
   # Valid quality 85
   convert -size 100x100 xc:white -quality 85 test_85.jpg
   
   # Valid quality 60 (below default threshold)
   convert -size 100x100 xc:white -quality 60 test_60.jpg
   
   # Corrupted (completely invalid)
   echo "not an image" > test_corrupt.jpg
   
   # Corrupted (truncated)
   head -c 100 test_85.jpg > test_truncated.jpg
   ```

### Test File Locations

- Add test images to a new `tests/fixtures/` directory
- Or generate on-the-fly during test execution (requires ImageMagick)

---

## File Location

- **Script**: `cbaudit.py` (repo root) — modified in place
- **Spec**: `docs/superpowers/specs/2026-07-29-cbaudit-imagemagick-migration-design.md`
- **Plan**: `docs/superpowers/plans/2026-07-29-cbaudit-imagemagick-migration.md`

---

## Approval

All design sections approved by user on 2026-07-29.
