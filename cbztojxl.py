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

# Archive format configurations
ALL_FORMATS = {
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

# Will be populated at runtime based on available tools
ARCHIVE_FORMATS = {}


def parse_args():
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


def check_dependencies():
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
        sys.exit(1)
    
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
        sys.exit(1)
    
    # Single file with supported extension
    if input_path.is_file():
        if input_path.suffix.lower() in supported_extensions:
            return [input_path]
        print(f"Error: {input_path} is not a valid archive file", file=sys.stderr)
        print(f"Supported formats: {', '.join(sorted(set(supported_extensions)))}", file=sys.stderr)
        sys.exit(1)
    
    # Directory - find all files with supported extensions
    if input_path.is_dir():
        pattern = "**/*" if recursive else "*"
        all_files = list(input_path.glob(pattern))
        return [f for f in all_files 
                if f.is_file() and f.suffix.lower() in supported_extensions]
    
    # Invalid input
    print(f"Error: {input_path} is not a valid file or directory", file=sys.stderr)
    sys.exit(1)


def get_format_config(file_path: Path) -> dict | None:
    """Get format config for a file based on its extension.
    
    Returns None if extension not in available formats.
    """
    ext = file_path.suffix.lower()
    for fmt_name, fmt_config in ARCHIVE_FORMATS.items():
        if ext in fmt_config['extensions']:
            return fmt_config
    return None


def extract_archive(archive_path: Path, output_dir: Path, fmt_config: dict):
    """Extract archive using format-specific command."""
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
        print(f"Error: Failed to extract {archive_path}", file=sys.stderr)
        print(f"  Command returned: {e.returncode}", file=sys.stderr)
        sys.exit(1)


@contextmanager
def temp_dir(source_path: Path):
    """Context manager for temp directory in same filesystem as source."""
    source_dir = source_path.parent if source_path.is_file() else source_path
    source_dir = source_dir.resolve()

    temp_path = Path(tempfile.mkdtemp(prefix=".cbztojxl_tmp_", dir=source_dir))
    try:
        yield temp_path
    finally:
        # Clean up temp directory
        shutil.rmtree(temp_path, ignore_errors=True)


def extract_cbz(cbz_path: Path, output_dir: Path):
    """Extract CBZ (ZIP) archive to output directory."""
    try:
        subprocess.run(
            ["unzip", "-q", str(cbz_path), "-d", str(output_dir)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to extract {cbz_path}", file=sys.stderr)
        print(f"  unzip returned: {e.returncode}", file=sys.stderr)
        sys.exit(1)


def convert_jpegs_to_jxl(temp_dir: Path, on_progress=None):
    """Convert all .jpg/.jpeg files in temp_dir to .jxl, delete originals (recursively)."""
    failures = []
    
    # Find all JPEG files recursively
    jpeg_files = [f for f in temp_dir.rglob("*") 
                  if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg")]
    
    for i, filepath in enumerate(jpeg_files):
        jxl_path = filepath.with_suffix(".jxl")

        try:
            # Try -q 100 first (mathematically lossless for cjxl v0.11+)
            # If that fails, try --lossless (older versions)
            try:
                subprocess.run(
                    ["cjxl", "-q", "100", str(filepath), str(jxl_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except subprocess.CalledProcessError:
                # Try --lossless for older versions
                subprocess.run(
                    ["cjxl", "--lossless", str(filepath), str(jxl_path)],
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

    if failures:
        for filepath, error in failures:
            print(f"Error: Failed to convert {filepath}: {error}", file=sys.stderr)
        sys.exit(2)


def create_cbz(output_path: Path, source_dir: Path):
    """Create a CBZ (ZIP) archive from files in source_dir."""
    output_path = output_path.resolve()

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

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
        print(f"Error: Failed to create {output_path}", file=sys.stderr)
        print(f"  zip returned: {e.returncode}", file=sys.stderr)
        sys.exit(1)


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
) -> bool:
    """Process a single archive file: extract, convert JPEGs to JXL, repack as CBZ."""
    input_path = input_path.resolve()
    
    # Get format config - skip silently if not available
    fmt_config = get_format_config(input_path)
    if fmt_config is None:
        # Extension not in available formats (tool missing) - skip silently
        return True  # Not a failure, just skip
    
    if verbose:
        print(f"Processing: {input_path}")

    # Compute output path early for dry run
    output_path = compute_output_path(input_path, base_input, output_dir, overwrite)
    
    if dry_run:
        print(f"  Would create: {output_path}")
        # Print summary for dry run if file indexing is provided
        if file_index is not None and total_files is not None:
            # For dry run, we need to count images to show in summary
            # Count images without extracting (using unzip -l)
            try:
                result = subprocess.run(
                    ["unzip", "-l", str(input_path)],
                    capture_output=True, text=True, check=True
                )
                image_count = sum(1 for line in result.stdout.splitlines()
                                  if line.lower().endswith(".jpg") or line.lower().endswith(".jpeg"))
            except (subprocess.CalledProcessError, FileNotFoundError):
                image_count = 0
            print(f"Processing: {input_path.name} - Done! ({image_count} images)")
        return True

    # Check if output exists and overwrite is False
    if output_path.exists() and not overwrite:
        if verbose:
            print(f"  Skipping {input_path}: {output_path} already exists")
        return True

    # Create temp directory in same filesystem as input
    with temp_dir(input_path) as temp_path:
        # Extract archive
        if verbose:
            print(f"  Extracting to: {temp_path}")
        extract_archive(input_path, temp_path, fmt_config)
        
        # Count images for progress tracking (recursively)
        jpeg_files = [f for f in temp_path.rglob("*") 
                      if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg")]
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

        # Temp dir auto-cleaned by context manager
    
    # Print summary when done (when file indexing is provided)
    if file_index is not None and total_files is not None:
        print()  # Newline after progress line
        print(f"Processing: {input_path.name} - Done! ({jpeg_count} images)")
    
    return True


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


def main():
    args = parse_args()
    check_dependencies()

    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve() if args.output_dir else None

    # Find all archive files to process
    archive_files = find_archive_files(input_path, args.recursive)

    if not archive_files:
        print("No archive files found to process.", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Found {len(archive_files)} archive file(s) to process")

    failures = []
    
    # Show progress bar only in normal mode (no verbose, no dry run)
    # But show summary line in normal and dry run modes
    show_progress_bar = not args.verbose and not args.dry_run
    show_summary = not args.verbose  # Show summary in normal and dry run, but not verbose
    
    for i, archive_file in enumerate(archive_files, 1):
        try:
            success = process_archive(
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
            if not success:
                failures.append(archive_file)
        except SystemExit as e:
            # process_archive may call sys.exit on some errors
            # In directory mode, we want to continue
            if e.code != 0:
                failures.append(archive_file)
            continue

    # Report results
    if failures:
        print(f"\nFailed to process {len(failures)} file(s):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(2)

    if args.verbose:
        print(f"\nSuccessfully processed {len(archive_files)} file(s)")

    sys.exit(0)


if __name__ == "__main__":
    main()

