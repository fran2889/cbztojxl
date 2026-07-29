#!/usr/bin/env python3
"""Convert CBZ archives containing JPEG images to JXL format."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TypedDict

# Exit code constants
EXIT_DEPENDENCY_ERROR = 1
EXIT_CONVERSION_ERROR = 2
EXIT_NO_FILES = 3


class ConversionError(Exception):
    """Raised when archive processing fails."""
    pass


class DependencyError(Exception):
    """Raised when required dependencies are missing."""
    pass


class ArchiveFormatConfig(TypedDict):
    """Type definition for archive format configuration."""
    extensions: list[str]
    extract_cmd: list[str]
    list_cmd: list[str]
    requires: list[str]


# Archive format configurations
ALL_FORMATS: dict[str, ArchiveFormatConfig] = {
    'zip': {
        'extensions': ['.cbz', '.zip'],
        'extract_cmd': ['unzip', '-q', '{archive}', '-d', '{output}'],
        'list_cmd': ['unzip', '-l', '{archive}'],
        'requires': ['unzip'],
    },
    'rar': {
        'extensions': ['.cbr', '.rar'],
        'extract_cmd': ['unrar', 'x', '-o+', '{archive}', '{output}'],
        'list_cmd': ['unrar', 'l', '{archive}'],
        'requires': ['unrar'],
    },
    '7z': {
        'extensions': ['.cb7', '.7z'],
        'extract_cmd': ['7z', 'x', '{archive}', '-o', '{output}', '-y'],
        'list_cmd': ['7z', 'l', '{archive}'],
        'requires': ['7z'],
    },
}

# Will be populated at runtime based on available tools
ARCHIVE_FORMATS: dict[str, ArchiveFormatConfig] = {}


def parse_args() -> argparse.Namespace:
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
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs="?",
        default=None,
        help="Output directory. If not provided, output files are placed next to source files with _jxl suffix",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        default=False,
        help="Process directories recursively",
    )
    parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing output files",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Print detailed logging",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would happen without making changes",
    )
    return parser.parse_args()


def is_tool_available(tool_name: str) -> bool:
    """Check if a command-line tool is available in PATH."""
    try:
        subprocess.run(
            [tool_name, '--help'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def check_dependencies() -> None:
    """Verify required tools are available in PATH.
    
    Mandatory tools (cjxl, zip, unzip) cause script to exit if missing.
    Optional tools (unrar, 7z) generate warnings, matching formats excluded from ARCHIVE_FORMATS.
    """
    global ARCHIVE_FORMATS
    
    MANDATORY_TOOLS = ['cjxl', 'zip', 'unzip']
    OPTIONAL_TOOLS = {
        'unrar': ['unrar', 'rar'],
        '7z': ['7z'],
    }
    
    # Check mandatory tools first
    missing_mandatory = []
    for cmd in MANDATORY_TOOLS:
        if not is_tool_available(cmd):
            missing_mandatory.append(cmd)
    
    if missing_mandatory:
        print(f"Error: Missing required dependencies: {', '.join(missing_mandatory)}", file=sys.stderr)
        print("Install cjxl from libjxl: https://github.com/libjxl/libjxl", file=sys.stderr)
        print("Install zip/unzip from your package manager", file=sys.stderr)
        sys.exit(EXIT_DEPENDENCY_ERROR)
    
    # Check optional tools
    available_optional = {}
    for tool_name, variants in OPTIONAL_TOOLS.items():
        available = any(is_tool_available(v) for v in variants)
        available_optional[tool_name] = available
    
    # Print warnings for missing optional tools
    if not available_optional.get('unrar'):
        print("Warning: unrar not found, CBR/RAR files will be skipped", file=sys.stderr)
    if not available_optional.get('7z'):
        print("Warning: 7z not found, CB7/7Z files will be skipped", file=sys.stderr)
    # Empty line after tool warnings
    if not available_optional.get('unrar') or not available_optional.get('7z'):
        print(file=sys.stderr)
    
    # Build ARCHIVE_FORMATS from available tools
    ARCHIVE_FORMATS = {k: v for k, v in ALL_FORMATS.items()
                       if all(is_tool_available(t) for t in v['requires'])}


def find_archive_files(input_path: Path, recursive: bool) -> list[Path]:
    """Find all supported archive files in input_path (file or directory)."""
    input_path = input_path.resolve()
    
    # Get all supported extensions from available formats
    supported_extensions = []
    for fmt in ARCHIVE_FORMATS.values():
        supported_extensions.extend(fmt['extensions'])
    
    # If no formats available (shouldn't happen with mandatory zip), handle gracefully
    if not supported_extensions:
        print("Error: No archive formats available (zip/unzip required)", file=sys.stderr)
        sys.exit(EXIT_DEPENDENCY_ERROR)
    
    # Single file with supported extension
    if input_path.is_file():
        if input_path.suffix.lower() in supported_extensions:
            return [input_path]
        print(f"Error: {input_path} is not a valid archive file", file=sys.stderr)
        print(f"Supported formats: {', '.join(sorted(set(supported_extensions)))}", file=sys.stderr)
        sys.exit(EXIT_DEPENDENCY_ERROR)
    
    # Directory - find all files with supported extensions
    if input_path.is_dir():
        pattern = "**/*" if recursive else "*"
        all_files = list(input_path.glob(pattern))
        return [f for f in all_files 
                if f.is_file() and f.suffix.lower() in supported_extensions]
    
    # Invalid input
    print(f"Error: {input_path} is not a valid file or directory", file=sys.stderr)
    sys.exit(EXIT_DEPENDENCY_ERROR)


def get_format_config(file_path: Path) -> ArchiveFormatConfig | None:
    """Get format config for a file based on its extension.
    
    Returns None if extension not in available formats.
    """
    ext = file_path.suffix.lower()
    for fmt_name, fmt_config in ARCHIVE_FORMATS.items():
        if ext in fmt_config['extensions']:
            return fmt_config
    return None


def is_jpeg_file(path: Path) -> bool:
    """Check if a file path is a JPEG image file."""
    return path.suffix.lower() in (".jpg", ".jpeg") and not is_appledouble_path(str(path))


def format_size_reduction(input_size: int, output_size: int) -> str:
    """Format input and output sizes with reduction percentage."""
    reduction_pct = ((input_size - output_size) / input_size * 100) if input_size > 0 else 0.0
    return f"{format_file_size(input_size)} -> {format_file_size(output_size)} ({reduction_pct:.1f}%)"


def is_appledouble_path(path: str) -> bool:
    """Check if a file path is an AppleDouble metadata file.
    
    AppleDouble files start with '._' or are inside '__MACOSX' directories.
    """
    # Use os.path for cross-platform path handling
    path_lower = path.lower()
    # Check for __MACOSX in any path component
    if any(part == '__macosx' for part in path_lower.split(os.sep)):
        return True
    # Check for ._ prefix in the filename
    basename = os.path.basename(path_lower)
    if basename.startswith('._'):
        return True
    return False


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes == 0:
        return "0 B"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    size = float(size_bytes)
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    # Format with appropriate precision
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    elif size < 10:
        return f"{size:.2f} {units[unit_index]}"
    else:
        return f"{size:.1f} {units[unit_index]}"


def count_jpegs_in_archive(archive_path: Path, fmt_config: ArchiveFormatConfig) -> int:
    """Count JPEG files in archive using list command.
    
    Returns the count of .jpg/.jpeg files, or 0 on error.
    """
    cmd = [c.format(archive=str(archive_path)) for c in fmt_config['list_cmd']]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        count = 0
        for line in result.stdout.splitlines():
            lower_line = line.lower()
            if (lower_line.endswith('.jpg') or lower_line.endswith('.jpeg')) \
               and not is_appledouble_path(lower_line):
                count += 1
        return count
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0



def extract_archive(archive_path: Path, output_dir: Path, fmt_config: ArchiveFormatConfig) -> None:
    """Extract archive using format-specific command.
    
    Raises:
        DependencyError: If extraction fails.
    """
    # Build command by formatting placeholders
    cmd = [c.format(archive=str(archive_path), output=str(output_dir)) 
           for c in fmt_config['extract_cmd']]
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        raise DependencyError(f"Failed to extract {archive_path}: command returned {e.returncode}")


@contextmanager
def temp_dir(source_path: Path) -> Iterator[Path]:
    """Context manager for temp directory in same filesystem as source."""
    source_dir = source_path.parent if source_path.is_file() else source_path
    source_dir = source_dir.resolve()

    temp_path = Path(tempfile.mkdtemp(prefix=".cbztojxl_tmp_", dir=source_dir))
    try:
        yield temp_path
    finally:
        # Clean up temp directory
        shutil.rmtree(temp_path, ignore_errors=True)



def convert_jpegs_to_jxl(temp_dir: Path, on_progress=None, verbose: bool = False) -> list[tuple[Path, Exception]]:
    """Convert all .jpg/.jpeg files in temp_dir to .jxl, delete originals (recursively).
    
    Returns:
        List of (filepath, error) tuples for any failures.
    """
    failures = []
    
    # Find all JPEG files recursively, excluding AppleDouble metadata files
    jpeg_files = [f for f in temp_dir.rglob("*") 
                  if f.is_file() and is_jpeg_file(f)]
    
    for i, filepath in enumerate(jpeg_files):
        jxl_path = filepath.with_suffix(".jxl")

        if verbose:
            print(f"  Converting image {i+1}/{len(jpeg_files)}: {filepath.name}")

        try:
            # Use -q 100 (mathematically lossless for cjxl v0.11+)
            subprocess.run(
                ["cjxl", "-q", "100", str(filepath), str(jxl_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            # Delete original on success
            filepath.unlink()
            
            # Call progress callback after successful conversion
            if on_progress:
                on_progress(i + 1)
        except subprocess.CalledProcessError as e:
            failures.append((filepath, e))

    return failures


def create_cbz(output_path: Path, source_dir: Path) -> None:
    """Create a CBZ (ZIP) archive from files in source_dir.
    
    Raises:
        DependencyError: If zip creation fails.
    """
    output_path = output_path.resolve()

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Check if output directory is writable
    if not os.access(output_path.parent, os.W_OK):
        raise DependencyError(f"Output directory is not writable: {output_path.parent}")

    # Remove existing file to avoid zip updating it instead of replacing
    if output_path.exists():
        output_path.unlink()

    try:
        subprocess.run(
            ["zip", "-q", "-r", str(output_path), "."],
            cwd=str(source_dir),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        raise DependencyError(f"Failed to create {output_path}: zip returned {e.returncode}")


def compute_output_path(
    input_path: Path,
    base_input: Path,
    output_dir: Path | None,
    overwrite: bool,
) -> Path:
    """Compute the output path for a converted archive file.
    
    Always uses .cbz extension for output, regardless of input format.
    """
    input_path = input_path.resolve()
    base_input = base_input.resolve()
    
    if output_dir is None:
        # Default: add _jxl suffix next to source, with .cbz extension
        return input_path.with_stem(input_path.stem + "_jxl").with_suffix('.cbz')
    
    output_dir = output_dir.resolve()
    
    # In-place replacement: output_dir equals source directory AND overwrite
    if output_dir == input_path.parent and overwrite:
        return input_path.with_suffix('.cbz')
    
    # Mirror structure: compute relative path from base_input to input_path
    try:
        rel_path = input_path.relative_to(base_input)
        if rel_path == Path("."):
            rel_path = Path(input_path.name)
    except ValueError:
        rel_path = Path(input_path.name)
    
    result = output_dir / rel_path
    # Force .cbz extension
    return result.with_suffix('.cbz')


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
) -> tuple[int, int, str]:
    """Process a single archive file: extract, convert JPEGs to JXL, repack as CBZ.
    
    Returns:
        tuple: (input_size, output_size, status_message)
        where status_message can be:
        - 'processed' - successfully converted
        - 'skipped_no_jpeg' - no JPEG files in archive
        - 'skipped_exists' - output already exists and overwrite=False
        - 'skipped_format' - archive format not available
        - 'error_extract' - extraction failed
        - 'error_convert' - JXL conversion failed
        - 'error_create' - CBZ creation failed
    """
    input_path = input_path.resolve()
    input_size = input_path.stat().st_size
    
    # Get format config - skip silently if not available
    fmt_config = get_format_config(input_path)
    if fmt_config is None:
        # Extension not in available formats (tool missing) - skip silently
        # Print summary line for non-verbose mode if indexing is provided
        if file_index is not None and total_files is not None:
            size_info = f"{format_file_size(input_size)}"
            print(f"Processing: {input_path.name} - Skipped (archiver not available, {size_info})")
        return input_size, 0, "skipped_format"
    
    if verbose:
        print(f"Processing: {input_path}")
    
    # Count JPEG images in archive
    image_count = count_jpegs_in_archive(input_path, fmt_config)
    
    # Check if archive contains JPEG files before extracting
    if image_count == 0:
        if verbose:
            print(f"  Skipping {input_path}: no JPEG files found")
        # Print summary line for non-verbose mode
        if file_index is not None and total_files is not None:
            size_info = f"{format_file_size(input_size)}"
            print(f"Processing: {input_path.name} - Skipped (no JPEG files, {size_info})")
        return input_size, 0, "skipped_no_jpeg"

    # Compute output path early for dry run
    output_path = compute_output_path(input_path, base_input, output_dir, overwrite)
    
    if dry_run:
        print(f"  Would create: {output_path}")
        # Print summary for dry run if file indexing is provided
        if file_index is not None and total_files is not None:
            # For dry run, estimate output size as roughly same as input (we can't know actual size)
            estimated_output_size = input_size  # This is an estimate for dry run
            size_info = format_size_reduction(input_size, estimated_output_size)
            print(f"Processing: {input_path.name} - Done! ({image_count} images, {size_info})")
        return input_size, input_size, "processed"

    # Check if output exists and overwrite is False
    if output_path.exists() and not overwrite:
        if verbose:
            print(f"  Skipping {input_path}: {output_path} already exists")
        # Get existing output file size for reporting
        existing_output_size = output_path.stat().st_size
        # Print summary line for non-verbose mode
        if file_index is not None and total_files is not None:
            size_info = format_size_reduction(input_size, existing_output_size)
            print(f"Processing: {input_path.name} - Skipped (output exists, {size_info})")
        return input_size, 0, "skipped_exists"

    # Track max line length for progress bar clearing
    max_line_len = 0
    
    # Create temp directory in same filesystem as input
    with temp_dir(input_path) as temp_path:
        try:
            # Extract archive
            if verbose:
                print(f"  Extracting to: {temp_path}")
            extract_archive(input_path, temp_path, fmt_config)
        except DependencyError as e:
            print(f"Error: {e}", file=sys.stderr)
            return input_size, 0, "error_extract"
        
        # Count images for progress tracking (recursively)
        jpeg_files = [f for f in temp_path.rglob("*") 
                      if f.is_file() and is_jpeg_file(f)]
        jpeg_count = len(jpeg_files)
        
        # Set up progress callback if progress bar should be shown
        if show_progress_bar and file_index is not None and total_files is not None:
            progress_cb, max_line_len = create_progress_callback(
                input_path.name, file_index, total_files, jpeg_count
            )
        else:
            progress_cb = None
        
        # Convert JPEGs to JXL
        if verbose:
            print(f"  Converting JPEGs to JXL")
        failures = convert_jpegs_to_jxl(temp_path, on_progress=progress_cb, verbose=verbose)
        
        if failures:
            for filepath, error in failures:
                print(f"Error: Failed to convert {filepath}: {error}", file=sys.stderr)
            return input_size, 0, "error_convert"

        # Create output CBZ
        if verbose:
            print(f"  Creating: {output_path}")
        try:
            create_cbz(output_path, temp_path)
        except DependencyError as e:
            print(f"Error: {e}", file=sys.stderr)
            return input_size, 0, "error_create"

        # Get actual output file size
        output_size = output_path.stat().st_size
        
        # Print summary when done (when file indexing is provided)
        if file_index is not None and total_files is not None and not verbose:
            size_info = format_size_reduction(input_size, output_size)
            # Replace progress bar with Done message using carriage return
            # Pad to max line length to clear any remaining characters
            done_msg = f"Processing: {input_path.name} - Done! ({jpeg_count} images, {size_info})"
            if max_line_len > 0:
                padded_msg = done_msg.ljust(max_line_len)
                print(f"\r{padded_msg}")
            else:
                print(done_msg)

        # Temp dir auto-cleaned by context manager
    
    return input_size, output_size, "processed"


def create_progress_callback(file_name: str, file_index: int, total_files: int, total_images: int) -> tuple[Callable[[int], None], int]:
    """Returns a tuple of (callback, max_line_length) for progress display."""
    # Store the maximum line length for clearing later
    max_line_len = len(f"Processing: {file_name} [{file_index}/{total_files}] |{'=' * 20}| {total_images}/{total_images}")
    
    def callback(current_image: int):
        if total_images <= 0:
            filled = 0
        else:
            filled = int(20 * current_image / total_images)
        bar = '=' * filled + ' ' * (20 - filled)
        line = f"Processing: {file_name} [{file_index}/{total_files}] |{bar}| {current_image}/{total_images}"
        # Pad to max length and use carriage return
        padded_line = line.ljust(max_line_len)
        print(f"\r{padded_line}", end="")
    return callback, max_line_len


def main() -> None:
    args = parse_args()
    check_dependencies()

    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve() if args.output_dir else None

    # Find all archive files to process
    archive_files = find_archive_files(input_path, args.recursive)

    if not archive_files:
        print("No archive files found to process.", file=sys.stderr)
        sys.exit(EXIT_NO_FILES)

    if args.verbose:
        print(f"Found {len(archive_files)} archive file(s) to process")

    failures = []
    
    # Track total sizes for final summary
    total_input_size = 0
    total_output_size = 0
    processed_count = 0
    
    # Show progress bar only in normal mode (no verbose, no dry run)
    # But show summary line in normal and dry run modes
    show_progress_bar = not args.verbose and not args.dry_run
    show_summary = not args.verbose  # Show summary in normal and dry run, but not verbose
    
    for i, archive_file in enumerate(archive_files, 1):
        input_size, output_size, status = process_archive(
            input_path=archive_file,
            base_input=input_path,
            output_dir=output_dir,
            overwrite=args.overwrite,
            verbose=args.verbose,
            dry_run=args.dry_run,
            file_index=i if show_summary else None,
            total_files=len(archive_files) if show_summary else None,
            show_progress_bar=show_progress_bar,
        )
        # Accumulate sizes for total summary
        if status == "processed":
            total_input_size += input_size
            total_output_size += output_size
            processed_count += 1
        elif status == "skipped_no_jpeg" or status == "skipped_format" or status == "skipped_exists":
            # For skipped files, don't include in total calculation as no processing occurred
            processed_count += 1
        elif status.startswith("error_"):
            # Track processing errors
            failures.append(archive_file)

    # Print total summary after all files are processed
    if show_summary and total_input_size > 0:
        total_size_info = format_size_reduction(total_input_size, total_output_size)
        print(f"\nTotal: {total_size_info}")

    # Report results
    if failures:
        print(f"\nFailed to process {len(failures)} file(s):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(EXIT_CONVERSION_ERROR)

    if args.verbose:
        print(f"\nSuccessfully processed {len(archive_files)} file(s)")

    sys.exit(0)


if __name__ == "__main__":
    main()

