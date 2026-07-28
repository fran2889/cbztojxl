# Multi-Format Archive Support Design

**Date:** 2026-07-28  
**Status:** Approved  
**Author:** Mistral Vibe (with user input)  
**Related:** Extends 2026-07-28-cbztojxl-design.md

## Overview

Extend `cbztojxl.py` to support additional comic and archive formats beyond CBZ (ZIP). The script will accept CBR (RAR), CB7/7z archives as input, but always output ZIP-based CBZ archives with JXL-encoded images.

This makes the script a **universal comic archive to CBZ-JXL converter**.

## Requirements

### Functional

1. **Input Format Support:**
   - Comic formats: `.cbz`, `.cbr`, `.cb7`
   - Archive formats: `.zip`, `.rar`, `.7z`
   - All formats processed identically: extract → convert JPEGs to JXL → repack

2. **Output:**
   - Always ZIP-based archive with `.cbz` extension
   - Input `comic.cbr` → output `comic_jxl.cbz` (default naming)
   - Input `archive.7z` → output `backup/archive.cbz` (with output directory)

3. **Dependency Handling:**
   - **Mandatory:** `cjxl`, `zip`, `unzip` — script fails if missing (exit 1)
   - **Optional:** `unrar` (for RAR/CBR), `7z` (for 7z/CB7) — warn if missing, skip applicable files

4. **File Discovery:**
   - Find files matching any supported extension
   - Works with single file or directory input
   - Respects recursive flag

5. **Error Handling:**
   - Missing optional tool + encountering that format: skip file silently, continue
   - Extraction failure: log error, clean up, continue (directory mode) or exit (single file)
   - Repack failure: same as extraction

6. **Exit Codes:**
   - 0: All conversions successful
   - 1: CLI or mandatory dependency error
   - 2: One or more conversion failures

### Non-Functional

- Maintain backward compatibility with existing CBZ-only behavior
- No new CLI arguments required (only help text updates)
- Preserve existing performance characteristics
- Cross-platform (Linux, macOS, Windows via WSL)

## Archive Format Registry

Central registry mapping archive types to their configurations:

```python
ARCHIVE_FORMATS = {
    'zip': {
        'extensions': ['.cbz', '.zip'],
        'extract_cmd': ['unzip', '-q', '{archive}', '-d', '{output}'],
        'requires': ['unzip'],
    },
    'rar': {
        'extensions': ['.cbr', '.rar'],
        'extract_cmd': ['unrar', 'x', '-o+', '{archive}', '{output}'],
        'requires': ['unrar'],
    },
    '7z': {
        'extensions': ['.cb7', '.7z'],
        'extract_cmd': ['7z', 'x', '{archive}', '-o{output}', '-y'],
        'requires': ['7z'],
    },
}
```

**Runtime Behavior:**
- At startup, after dependency check, filter out formats whose required tools are not available
- `find_archive_files()` only searches for extensions from available formats
- Extraction uses the command template from the matched format
- Repackaging always uses `zip` command (ZIP format)

## Dependency Checking

### Updated `check_dependencies()` Function

```python
MANDATORY_TOOLS = ['cjxl', 'zip', 'unzip']
OPTIONAL_TOOLS = {
    'unrar': ['unrar', 'rar'],  # Accept either binary name
    '7z': ['7z'],
}

def check_dependencies():
    # Check mandatory tools
    for cmd in MANDATORY_TOOLS:
        if not is_tool_available(cmd):
            print_error_and_exit(f"Missing required dependency: {cmd}")
    
    # Check optional tools, warn if missing
    available_optional = {}
    for tool_name, variants in OPTIONAL_TOOLS.items():
        available = any(is_tool_available(v) for v in variants)
        available_optional[tool_name] = available
        if not available:
            warnings.append(f"{tool_name} not found")
    
    # Print warnings
    if not available_optional.get('unrar'):
        print("Warning: unrar not found, CBR/RAR files will be skipped", file=sys.stderr)
    if not available_optional.get('7z'):
        print("Warning: 7z not found, CB7/7Z files will be skipped", file=sys.stderr)
    
    # Build available formats registry
    global ARCHIVE_FORMATS
    ARCHIVE_FORMATS = {k: v for k, v in ALL_FORMATS.items()
                       if all(is_tool_available(t) for t in v['requires'])}
```

## File Discovery

### Updated `find_archive_files()` Function

```python
def find_archive_files(input_path: Path, recursive: bool) -> list[Path]:
    """Find all supported archive files in input_path."""
    input_path = input_path.resolve()
    
    # Get all supported extensions from available formats
    supported_extensions = []
    for fmt in ARCHIVE_FORMATS.values():
        supported_extensions.extend(fmt['extensions'])
    
    # Single file with supported extension
    if input_path.is_file():
        if input_path.suffix.lower() in supported_extensions:
            return [input_path]
        print(f"Error: {input_path} is not a supported archive format", file=sys.stderr)
        print(f"Supported formats: {', '.join(sorted(supported_extensions))}", file=sys.stderr)
        sys.exit(1)
    
    # Directory - find all files with supported extensions
    if input_path.is_dir():
        pattern = "**/*" if recursive else "*"
        all_files = list(input_path.glob(pattern))
        return [f for f in all_files 
                if f.is_file() and f.suffix.lower() in supported_extensions]
    
    print(f"Error: {input_path} is not a valid file or directory", file=sys.stderr)
    sys.exit(1)
```

## Processing Pipeline

### New/Modified Functions

```python
def get_format_config(file_path: Path) -> dict | None:
    """Get format config for a file based on its extension."""
    ext = file_path.suffix.lower()
    for fmt_name, fmt_config in ARCHIVE_FORMATS.items():
        if ext in fmt_config['extensions']:
            return fmt_config
    return None

def extract_archive(archive_path: Path, output_dir: Path, fmt_config: dict):
    """Extract archive using format-specific command."""
    cmd = fmt_config['extract_cmd']
    # Expand placeholders
    cmd = [c.format(archive=str(archive_path), output=str(output_dir)) 
           for c in cmd]
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to extract {archive_path}", file=sys.stderr)
        print(f"  Command returned: {e.returncode}", file=sys.stderr)
        sys.exit(1)

def create_cbz(output_path: Path, source_dir: Path):
    """Create ZIP-based CBZ archive. Unchanged from original."""
    # Always uses zip command
    # output_path already has .cbz extension
    ...
```

### Modified `process_archive()` Function

```python
def process_archive(
    input_path: Path,
    base_input: Path,
    output_dir: Path | None,
    overwrite: bool,
    verbose: bool,
    dry_run: bool,
    file_index: int = None,
    total_files: int = None,
    show_progress_bar: bool = False,
) -> bool:
    """Process a single archive file: extract, convert, repack as CBZ."""
    input_path = input_path.resolve()
    
    # Get format config
    fmt_config = get_format_config(input_path)
    if fmt_config is None:
        # Extension not in available formats (tool missing) - skip silently
        return True  # Skip, not a failure
    
    if verbose:
        print(f"Processing: {input_path}")
    
    # Compute output path - always .cbz extension
    output_path = compute_output_path(input_path, base_input, output_dir, overwrite)
    # Force .cbz extension
    output_path = output_path.with_suffix('.cbz')
    
    # ... rest of processing: dry run, temp dir, extract, convert, repack ...
    
    # Extract using format-specific command
    with temp_dir(input_path) as temp_path:
        extract_archive(input_path, temp_path, fmt_config)
        # Convert JPEGs to JXL (unchanged)
        # Repack using zip (unchanged, output_path has .cbz)
```

## Output Path Computation

### Modified `compute_output_path()` Function

```python
def compute_output_path(
    input_path: Path,
    base_input: Path,
    output_dir: Path | None,
    overwrite: bool,
) -> Path:
    """Compute output path, always with .cbz extension."""
    input_path = input_path.resolve()
    base_input = base_input.resolve()
    
    if output_dir is None:
        # Default: add _jxl suffix, change extension to .cbz
        return input_path.with_stem(input_path.stem + "_jxl").with_suffix('.cbz')
    
    output_dir = output_dir.resolve()
    
    # In-place replacement
    if output_dir == input_path.parent and overwrite:
        return input_path.with_suffix('.cbz')
    
    # Mirror structure
    try:
        rel_path = input_path.relative_to(base_input)
        if rel_path == Path("."):
            rel_path = Path(input_path.name)
    except ValueError:
        rel_path = Path(input_path.name)
    
    result = output_dir / rel_path
    # Force .cbz extension
    return result.with_suffix('.cbz')
```

## CLI Changes

### Updated Argument Parser

```python
parser = argparse.ArgumentParser(
    description="Convert comic archives (CBZ, ZIP, CBR, RAR, CB7, 7Z) "
                "containing JPEG images to JXL format in CBZ containers."
)
parser.add_argument(
    "input",
    type=Path,
    help="Comic archive file or directory containing comic archives "
         "(supports: .cbz, .zip, .cbr, .rar, .cb7, .7z)",
)
```

No new arguments are added. All existing options (`-r`, `-o`, `-v`, `--dry-run`) work unchanged.

## Error Handling

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All conversions successful |
| 1 | CLI error or mandatory dependency missing |
| 2 | One or more conversion failures |

Files skipped due to missing optional tools do NOT cause exit code 2.

## Examples

### Scenario 1: Single file conversion (CBR to CBZ-JXL)
```bash
python cbztojxl.py comic.cbr
# Creates: comic_jxl.cbz (ZIP-based, with JXL images)
```

### Scenario 2: Directory with mixed formats
```bash
# Input directory has: issue1.cbz, issue2.cbr, issue3.cb7
python cbztojxl.py /comics/ -r
# Creates: issue1_jxl.cbz, issue2_jxl.cbz, issue3_jxl.cbz
```

### Scenario 3: Output to different directory
```bash
python cbztojxl.py /comics/ /backup/ -r
# Creates: /backup/issue1.cbz, /backup/issue2.cbz, /backup/issue3.cbz
# All are ZIP-based CBZ files
```

### Scenario 4: With missing optional tools
```bash
# unrar is not installed
python cbztojxl.py /comics/
# Warning: unrar not found, CBR/RAR files will be skipped
# Processes .cbz and .zip files, skips .cbr files silently
```

## Testing Strategy

### Unit Tests
- Format detection from extensions
- Registry building with different tool availability
- Output path computation with extension change
- Format config lookup

### Integration Tests
- Single file for each format type (CBZ, ZIP, CBR, RAR, CB7, 7Z)
- Mixed format directory
- Output always ZIP-based with .cbz extension
- Files with non-JPEG content preserved

### Error Tests
- Missing mandatory tool (zip/unzip/cjxl) → exit 1
- Missing optional tool + applicable file → skip silently
- Extraction failure for each format type
- Invalid/unsupported file extension

### Edge Cases
- File with recognized extension but wrong format (e.g., .cbz that's actually RAR)
- Empty archive
- Archive with no JPEGs
- Archive with special characters in filename

## File Structure Changes

No new files are added. All changes are to `cbztojxl.py`:

```
cbztojxl/
├── cbztojxl.py          # Modified with multi-format support
├── README.md           # To be updated with new format info
└── docs/
    └── superpowers/
        ├── specs/
        │   ├── 2026-07-28-cbztojxl-design.md          # Original spec
        │   └── 2026-07-28-multi-format-archive-support-design.md  # This spec
        └── plans/
            └── ...
```

## Implementation Notes

1. **Backward Compatibility:** Existing CBZ-only behavior is preserved. All existing tests should pass.

2. **Performance:** No significant performance impact. Extraction commands vary by format but processing is the same.

3. **Tool Variations:**
   - `unrar` binary may be named `rar` or `unrar` on different systems
   - `7z` binary is consistently named `7z`
   - Handle both variations in dependency checking

4. **RAR Extraction Flags:**
   - `-x` extracts with full paths
   - `-o+` overwrites existing files without prompt
   - RAR may need `-y` on some systems to assume yes

5. **7z Extraction Flags:**
   - `x` extracts with full paths
   - `-o{output}` specifies output directory
   - `-y` assumes yes to all prompts

## Open Questions

None. All design decisions have been resolved with user input.

## Approval

All design sections presented and approved by user on 2026-07-28.
