# CBZ to JXL Conversion Script Design

**Date:** 2026-07-28  
**Status:** Draft  
**Author:** Mistral Vibe (with user input)

## Overview

A Python script that converts CBZ archive files containing JPEG images to JXL format. The script extracts the CBZ, converts each JPEG to JXL using lossless compression, preserves non-JPEG files, and repackages into a new CBZ with a `_jxl` suffix.

## Requirements

### Functional

1. **Input:** Accept a single CBZ file path (matching `.cbz` extension case-insensitively) or a directory containing CBZ files
2. **Recursive processing:** Optionally process directories recursively (`-r/--recursive`)
3. **File processing:** 
   - Extract CBZ to a temporary directory in the same filesystem as the source
   - Convert each `.jpg` and `.jpeg` file (case-insensitive) to JXL using `cjxl --lossless`
   - Delete the original JPEG after successful conversion
   - Preserve all non-JPEG files unchanged in the output
4. **Output:** 
   - If OUTPUT_DIR not provided: Create a new CBZ file next to source with `_jxl` inserted before the extension (e.g., `comic.cbz` → `comic_jxl.cbz`)
   - If OUTPUT_DIR provided: Create output CBZ in that directory, mirroring source directory structure, without `_jxl` suffix (e.g., `/source/dir/comic.cbz` → `/output/dir/comic.cbz`)
   - If OUTPUT_DIR equals source directory AND `--overwrite` is enabled: Replace original files in place
5. **Overwrite protection:** Skip existing output files unless `-o/--overwrite` is specified
6. **Error handling:**
   - Single file mode: Exit on any conversion failure
   - Directory mode: Log per-file errors, continue processing remaining files
7. **Cleanup:** Always remove temporary directories, even on error

### Non-Functional

- **Cross-platform:** Works on Linux, macOS, Windows (Python-based)
- **Dependencies:** Requires Python 3.6+, `cjxl` (libjxl), `zip`/`unzip` utilities
- **Performance:** Temp directory on same filesystem as source to avoid cross-partition copying

## CLI Interface

### Usage

```bash
python cbztojxl.py [OPTIONS] INPUT [OUTPUT_DIR]
```

### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `INPUT` | path | Yes | CBZ file or directory containing CBZ files |
| `OUTPUT_DIR` | path | No | Output directory. If not provided, output files are placed next to source files with `_jxl` suffix |

### Options

| Flag | Long | Default | Description |
|------|------|---------|-------------|
| `-r` | `--recursive` | false | Process directories recursively |
| `-o` | `--overwrite` | false | Overwrite existing output files |
| `-v` | `--verbose` | false | Print detailed logging |
| | `--dry-run` | false | Show what would happen without making changes |
| `-h` | `--help` | N/A | Show help message |

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All conversions successful |
| `1` | CLI or dependency error (bad arguments, missing `cjxl`) |
| `2` | One or more conversion failures |

## File Processing Pipeline

### Single File Mode

```
input.cbz
    ↓
Validate input exists and has .cbz extension (case-insensitive)
    ↓
Check cjxl is available in PATH
    ↓
If --dry-run: log what would happen, exit 0 (skip all actual processing)
    ↓
Create temp dir in same directory as input (.cbztojxl_tmp_XXXXXX)
    ↓
Extract input.cbz to temp dir
    ↓
For each file in temp dir:
    - If extension is .jpg or .jpeg (case-insensitive):
        - Run: cjxl --lossless input.jpg output.jxl
        - If success: delete input.jpg
        - If fail: log error, clean up temp, exit 2
    - Else: keep as-is
    ↓
Determine output path:
    - If OUTPUT_DIR not provided: output = input.parent / (input.stem + "_jxl" + input.suffix)
    - If OUTPUT_DIR provided:
        - If OUTPUT_DIR == input.parent AND --overwrite: output = input (replace original)
        - Else: output = OUTPUT_DIR / input.name (mirror structure if applicable)
    ↓
If --dry-run: skip writing output
    ↓
Create output archive from temp dir contents
    ↓
If output exists and NOT --overwrite: skip, log, exit 0
    ↓
Write output archive
    ↓
Delete temp dir
    ↓
Done (exit 0)
```

### Directory Mode

```
Find all files with .cbz extension (case-insensitive) in INPUT directory:
    - If -r/--recursive: walk all subdirectories
    - Else: only top-level directory
    ↓
If OUTPUT_DIR provided:
    - OUTPUT_DIR is the base for all output files
    - Relative paths from INPUT directory are preserved in OUTPUT_DIR
    ↓
For each .cbz file found:
    - If --dry-run: log what would happen for this file, continue to next
    - Else: Apply single file pipeline to each CBZ
        - Output path computed as: OUTPUT_DIR / relative_path_from_input / filename
        - If OUTPUT_DIR equals INPUT dir AND --overwrite: replace original in place
    ↓
    Track failures per file
    ↓
If any failures: log summary, exit 2
Else: exit 0
```

## Temp Directory Management

- **Location:** Same directory as the source CBZ file (ensures same filesystem)
- **Naming:** Hidden directory with unique suffix: `.cbztojxl_tmp_XXXXXX`
- **Implementation:** `tempfile.mkdtemp(prefix=".cbztojxl_tmp_", dir=source_dir)`
- **Cleanup:** Always removed via `try/finally` or context manager

## Output Naming

### Default Behavior (no OUTPUT_DIR)
- **Pattern:** Insert `_jxl` before the file extension
- **Examples:**
  - `comic.cbz` → `comic_jxl.cbz`
  - `my_comic.CBZ` → `my_comic_jxl.CBZ`
- **Implementation:** `{stem}_jxl{suffix}` using `pathlib.Path`

### With OUTPUT_DIR
- **Pattern:** Same filename as source, no `_jxl` suffix
- **Location:** OUTPUT_DIR with relative path from INPUT directory preserved
- **Examples:**
  - Source: `/comics/series1/issue.cbz`, Output dir: `/output/` → `/output/series1/issue.cbz`
  - Source: `/comics/issue.cbz`, Output dir: `/comics/` + `--overwrite` → `/comics/issue.cbz` (replaces original)
  - Source: `/comics/issue.cbz`, Output dir: `/backup/` → `/backup/issue.cbz`
- **Implementation:** Compute relative path from INPUT base to source file, apply to OUTPUT_DIR

## Examples

### Scenario 1: Default behavior (no OUTPUT_DIR)
```bash
# Single file
python cbztojxl.py /comics/mycomic.cbz
# Creates: /comics/mycomic_jxl.cbz

# Directory
python cbztojxl.py /comics/ -r
# Creates: /comics/series1/issue1_jxl.cbz, /comics/series1/issue2_jxl.cbz, etc.
```

### Scenario 2: With OUTPUT_DIR
```bash
# Copy to different directory, preserve structure
python cbztojxl.py /comics/ /backup/ -r
# Creates: /backup/series1/issue1.cbz, /backup/series1/issue2.cbz, etc.

# Flat copy (no recursion)
python cbztojxl.py /comics/ /backup/
# Creates: /backup/issue1.cbz (only top-level files)
```

### Scenario 3: In-place conversion
```bash
# Replace originals in place
python cbztojxl.py /comics/ /comics/ -r -o
# Converts each .cbz file in /comics/ to JXL format, replacing originals
```

## Error Handling

### Dependency Check
- At script startup, verify `cjxl` is accessible
- If not found: print error message with installation instructions, exit 1

### Single File Errors
- `unzip` failure: log, clean up temp, exit 1
- `cjxl` failure on JPEG: log filename and error, clean up temp, exit 2
- `zip` failure: log, clean up temp, exit 1
- Output exists and `-o` not set: log, skip file, exit 0

### Directory Mode Errors
- Track list of failed files
- Log each failure with filename and error message
- Continue processing remaining files
- At completion: if failures list non-empty, print summary, exit 2

## Dependencies

### Required
- Python 3.6+
- `cjxl` from libjxl (tested with version 0.8+)
- Standard Unix utilities: `zip`, `unzip`

### Python Modules
- Standard library only: `argparse`, `pathlib`, `subprocess`, `tempfile`, `sys`, `os`

## Testing Strategy

1. **Unit tests:**
   - Output filename generation
   - File extension detection
   - Temp dir naming

2. **Integration tests:**
   - Single CBZ with JPEGs: verify all converted, output exists
   - Single CBZ with mixed files: verify non-JPEGs preserved
   - Directory with multiple CBZ: verify all processed
   - Directory recursive: verify subdir CBZ processed
   - Overwrite protection: verify skip without `-o`
   - Overwrite enabled: verify overwrite with `-o`
   - OUTPUT_DIR specified: verify files placed in output dir without suffix
   - OUTPUT_DIR with structure: verify relative paths preserved
   - OUTPUT_DIR same as source with -o: verify in-place replacement

3. **Error tests:**
   - Missing cjxl: verify error message, exit 1
   - Invalid input path: verify error, exit 1
   - cjxl failure on JPEG: verify error logged, exit 2
   - Read-only output file: verify error handling

4. **Edge cases:**
   - Empty CBZ file
   - CBZ with no JPEGs
   - CBZ with special characters in filename
   - Large files (performance)
   - Cross-partition temp dir (should NOT happen with our design)

## File Structure

```
cbztojxl/
├── cbztojxl.py          # Main script
├── README.md           # Usage documentation
└── tests/
    ├── test_cli.py     # CLI argument parsing tests
    ├── test_convert.py  # Conversion logic tests
    └── test_utils.py    # Utility function tests
```

## Open Questions

1. Should we support CBZ files that are actually RAR or 7z archives (some CBZ use these)? Current: assume ZIP only.
2. Should we validate that the input is actually a valid CBZ/ZIP before processing? Current: let unzip handle this.
3. Should we add a `--quality` option for non-lossless conversion as a future enhancement? Current: lossless only.

## Implementation Notes

- Use `pathlib.Path` for all path operations (cross-platform)
- Use `subprocess.run()` with `check=True` for external commands
- Use `argparse` for CLI argument parsing
- Use `tempfile.mkdtemp()` for temp directory creation
- Use context managers (`with` statements) where possible for cleanup
