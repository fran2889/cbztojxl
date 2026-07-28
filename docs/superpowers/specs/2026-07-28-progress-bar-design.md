# Progress Bar Feature Design

**Date:** 2026-07-28  
**Feature:** Add ASCII progress bar tracking image and file progress  
**Status:** Approved for implementation  

---

## Overview

Add a visual ASCII progress bar to cbztojxl that shows:
1. **File-level progress**: Which CBZ file is being processed out of total files (e.g., `[3/10]`)
2. **Image-level progress**: Which image within the current CBZ is being converted (e.g., `|====    | 5/12`)

The progress bar updates in place on a single line using carriage return (`\r`).

---

## Requirements

### Display Format

**During processing:**
```
Processing: comic01.cbz [1/10] |====      | 5/12
```

- `Processing: {filename}` - The CBZ file being processed
- `[{file_index}/{total_files}]` - File position in the queue
- `|{bar}|` - 20-character ASCII bar using `=` for filled, ` ` (space) for empty
- `{current}/{total}` - Image count within the current CBZ file

**On completion:**
```
Processing: comic01.cbz [1/10] |==========| 12/12
Processing: comic01.cbz - Done! (12 images)

Processing: comic02.cbz [2/10] |=====     | 3/15
```

- Progress line completes (bar full, count at total)
- Summary line confirms completion with image count
- Blank line separates files for readability

### Behavior by Mode

| Mode | Progress Bar | Summary Line |
|------|--------------|--------------|
| Normal | ✅ Shown | ✅ Shown |
| Verbose (`-v`) | ❌ Suppressed | ❌ Suppressed |
| Dry run (`--dry-run`) | ❌ Suppressed | ✅ Shown |

**Note on modes:** Progress bar is only shown in normal mode. Verbose mode suppresses both progress bar and summary. Dry run mode suppresses the progress bar but still shows the summary line to list all files that will be processed.

---

## Implementation Approach

**Approach:** Callback pattern (Approach C)

A callback function is passed to `convert_jpegs_to_jxl()` and invoked after each image conversion. This keeps the conversion logic clean and decoupled from the display logic.

### Components

#### 1. Progress Callback Creator

New helper function that creates closure over progress display state:

```python
def create_progress_callback(file_name: str, file_index: int, total_files: int, total_images: int):
    """Returns a callback that updates progress display."""
    def callback(current_image: int):
        if total_images <= 0:
            filled = 0
        else:
            filled = int(20 * current_image / total_images)
        bar = '=' * filled + ' ' * (20 - filled)
        print(f"\rProcessing: {file_name} [{file_index}/{total_files}] |{bar}| {current_image}/{total_images}", end="")
    return callback
```

- Called after each successful image conversion
- Updates the same line using `\r` (carriage return)
- Bar width: 20 characters
- Uses `end=""` to prevent newline

#### 2. Modified `convert_jpegs_to_jxl()`

Add optional `on_progress` parameter:

```python
def convert_jpegs_to_jxl(temp_dir: Path, on_progress=None):
    failures = []
    
    # Find all JPEG files first to get total
    jpeg_files = [f for f in temp_dir.iterdir() 
                  if f.suffix.lower() in (".jpg", ".jpeg")]
    
    for i, filepath in enumerate(jpeg_files):
        jxl_path = filepath.with_suffix(".jxl")
        
        try:
            # ... existing conversion code ...
            
            # Call progress callback after successful conversion
            if on_progress:
                on_progress(i + 1)
                
        except subprocess.CalledProcessError as e:
            failures.append((filepath, e))
    
    # ... rest of function ...
```

- Counts JPEG files before the loop to know total
- Calls `on_progress(i + 1)` after each successful conversion
- If `on_progress` is None, behaves exactly as before

#### 3. Modified `process_cbz()`

Add parameters for file indexing and progress control:

```python
def process_cbz(
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
    input_path = input_path.resolve()
    
    # Compute output path
    output_path = compute_output_path(input_path, base_input, output_dir, overwrite)
    
    if dry_run:
        if verbose:
            print(f"Processing: {input_path}")
        print(f"  Would create: {output_path}")
        return True
    
    if verbose:
        print(f"Processing: {input_path}")
    
    # Check if output exists and overwrite is False
    if output_path.exists() and not overwrite:
        if verbose:
            print(f"  Skipping {input_path}: {output_path} already exists")
        return True
    
    # Create temp directory in same filesystem as input
    with temp_dir(input_path) as temp_path:
        # Extract CBZ
        if verbose:
            print(f"  Extracting to: {temp_path}")
        extract_cbz(input_path, temp_path)
        
        # Count images for progress tracking
        jpeg_files = [f for f in temp_path.iterdir() 
                      if f.suffix.lower() in (".jpg", ".jpeg")]
        jpeg_count = len(jpeg_files)
        
        # Set up progress callback if progress bar should be shown
        if show_progress_bar and file_index is not None and total_files is not None:
            progress_cb = create_progress_callback(
                input_path.name, file_index, total_files, jpeg_count
            )
        else:
            progress_cb = None
        
        # Convert JPEGs to JXL
        if verbose:
            print(f"  Converting JPEGs to JXL")
        convert_jpegs_to_jxl(temp_path, on_progress=progress_cb)
        
        # Create output CBZ
        if verbose:
            print(f"  Creating: {output_path}")
        create_cbz(output_path, temp_path)
    
    # Print summary when done (only if we had progress tracking)
    if file_index is not None and total_files is not None:
        print()  # Newline after progress line
        print(f"Processing: {input_path.name} - Done! ({jpeg_count} images)")
    
    return True
```

- Counts images before conversion to pass to callback creator
- Creates callback only when `show_progress_bar` is True and file indexing is provided
- Prints summary with image count when `file_index` and `total_files` are provided

#### 4. Modified `main()`

Pass file index and total to `process_cbz()`, control progress display:

```python
def main():
    args = parse_args()
    check_dependencies()
    
    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve() if args.output_dir else None
    
    # Find all CBZ files to process
    cbz_files = find_cbz_files(input_path, args.recursive)
    
    if not cbz_files:
        print("No CBZ files found to process.", file=sys.stderr)
        sys.exit(1)
    
    if args.verbose:
        print(f"Found {len(cbz_files)} CBZ file(s) to process")
    
    failures = []
    
    # Show progress bar only in normal mode (no verbose, no dry run)
    # But show summary line in normal and dry run modes
    show_progress_bar = not args.verbose and not args.dry_run
    show_summary = not args.verbose  # Show summary in normal and dry run, but not verbose
    
    for i, cbz_file in enumerate(cbz_files, 1):
        try:
            success = process_cbz(
                input_path=cbz_file,
                base_input=input_path,
                output_dir=output_dir,
                overwrite=args.overwrite,
                verbose=args.verbose,
                dry_run=args.dry_run,
                file_index=i if show_summary else None,
                total_files=len(cbz_files) if show_summary else None,
                show_progress_bar=show_progress_bar,
            )
            if not success:
                failures.append(cbz_file)
        except SystemExit as e:
            if e.code != 0:
                failures.append(cbz_file)
            continue
    
    # Report results
    if failures:
        print(f"\nFailed to process {len(failures)} file(s):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(2)
    
    if args.verbose:
        print(f"\nSuccessfully processed {len(cbz_files)} file(s)")
    
    sys.exit(0)
```

- `show_progress_bar = not args.verbose and not args.dry_run` controls the updating progress bar
- `show_summary = not args.verbose` controls whether summary line is shown (normal + dry run, but not verbose)
- Passes `file_index` and `total_files` when summary should be shown
- Passes `show_progress_bar` separately to control the updating bar
- When both are suppressed (verbose mode), `process_cbz()` behaves as before

---

## File Changes Summary

| File | Changes |
|------|---------|
| `cbztojxl.py` | Add `create_progress_callback()` function |
| `cbztojxl.py` | Modify `convert_jpegs_to_jxl()` signature and loop |
| `cbztojxl.py` | Modify `process_cbz()` signature, add `show_progress_bar` param and progress logic |
| `cbztojxl.py` | Modify `main()` to pass indexing info

---

## Edge Cases

1. **No images in CBZ**: `total_images` is 0, callback handles division by zero gracefully (filled = 0, bar is all spaces)
2. **CBZ with non-JPEG files**: Only `.jpg`/`.jpeg` files (case insensitive) are counted and converted
3. **Single CBZ file**: Works correctly with `[1/1]` display
4. **Very long filenames**: Display wraps naturally, no truncation needed
5. **Terminal width**: Bar is fixed at 20 chars, should fit most terminals
6. **Dry run mode**: Progress bar suppressed, but summary line shown to list files
7. **Zero-width bar**: When total_images is 0, bar displays as 20 spaces

---

## Testing Considerations

- Test with single CBZ file
- Test with multiple CBZ files
- Test with CBZ containing various numbers of images
- Test verbose mode (progress bar and summary should not appear)
- Test dry run mode (progress bar should not appear, but summary line should)
- Test with very long filenames
- Test with CBZ files containing no JPEG images
- Test with CBZ files containing mixed file types

---

## Approval

**User Approved:** Yes  
**Date:** 2026-07-28