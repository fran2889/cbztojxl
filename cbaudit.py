#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Fran
# SPDX-License-Identifier: GPL-3.0-only

"""Audit comic archives (CBZ, CBR, CB7) for JPEG image quality and corruption using ImageMagick."""

__version__ = "1.0.0"

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, TypedDict

from zip_support import ZipArchiveError, extract_zip_archive


class ArchiveFormatConfig(TypedDict):
    """Type definition for archive format configuration."""
    extensions: list[str]
    extract_cmd: list[str]
    list_cmd: list[str]
    requires: list[str]


# Archive format configurations - duplicated from cbztojxl
ALL_FORMATS: dict[str, ArchiveFormatConfig] = {
    'zip': {
        'extensions': ['.cbz', '.zip'],
        'extract_cmd': [],
        'list_cmd': [],
        'requires': [],
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

ARCHIVE_FORMATS: dict[str, ArchiveFormatConfig] = {}


class ArchiveExtractionError(Exception):
    """Raised when archive extraction fails."""
    pass


class DependencyError(Exception):
    """Raised when required dependencies are missing."""
    pass


def is_tool_available(tool_name: str) -> bool:
    """Check if a command-line tool is available in PATH."""
    # identify doesn't support --help (tries to decode file), use -help instead
    help_flag = '-help' if tool_name == 'identify' else '--help'
    try:
        subprocess.run(
            [tool_name, help_flag],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def is_appledouble_path(path: str) -> bool:
    """Check if a file path is an AppleDouble metadata file.
    
    AppleDouble files start with '._' or are inside '__MACOSX' directories.
    """
    path_lower = path.lower()
    if any(part == '__macosx' for part in path_lower.split(os.sep)):
        return True
    basename = path_lower.rsplit(os.sep, 1)[-1]
    if basename.startswith('._'):
        return True
    return False


@contextmanager
def temp_dir(source_path: Path):
    """Context manager for temp directory in same filesystem as source."""
    source_dir = source_path.parent if source_path.is_file() else source_path
    source_dir = source_dir.resolve()

    temp_path = Path(tempfile.mkdtemp(prefix=".cbaudit_tmp_", dir=source_dir))
    try:
        yield temp_path
    finally:
        shutil.rmtree(temp_path, ignore_errors=True)


def get_format_config(file_path: Path) -> ArchiveFormatConfig | None:
    """Get format config for a file based on its extension."""
    ext = file_path.suffix.lower()
    for fmt_name, fmt_config in ARCHIVE_FORMATS.items():
        if ext in fmt_config['extensions']:
            return fmt_config
    return None


def find_archive_files(input_path: Path, recursive: bool) -> list[Path]:
    """Find all supported archive files in input_path (file or directory)."""
    input_path = input_path.resolve()

    supported_extensions = []
    for fmt in ARCHIVE_FORMATS.values():
        supported_extensions.extend(fmt['extensions'])

    if not supported_extensions:
        print("Error: No archive formats available. Install ImageMagick.", file=sys.stderr)
        sys.exit(1)

    if input_path.is_file():
        if input_path.suffix.lower() in supported_extensions:
            return [input_path]
        print(f"Error: {input_path} is not a valid archive file. Supported formats: {', '.join(sorted(set(supported_extensions)))}.", file=sys.stderr)
        sys.exit(1)

    if input_path.is_dir():
        pattern = "**/*" if recursive else "*"
        all_files = list(input_path.glob(pattern))
        return sorted(
            (f for f in all_files if f.is_file()
             and f.suffix.lower() in supported_extensions),
            key=lambda path: path.relative_to(input_path).as_posix(),
        )

    print(f"Error: {input_path} is not a valid file or directory.", file=sys.stderr)
    sys.exit(1)


def check_dependencies(skip_errors: bool = False):
    """Verify required tools are available in PATH.
    
    Args:
        skip_errors: If True, don't exit on missing tools (for dry-run)
    
    Returns: True if all mandatory tools available, False otherwise
    """
    global ARCHIVE_FORMATS
    
    MANDATORY_TOOLS = ['identify']
    OPTIONAL_TOOLS = {
        'unrar': ['unrar'],
        '7z': ['7z'],
    }
    
    missing_mandatory = []
    for cmd in MANDATORY_TOOLS:
        if not is_tool_available(cmd):
            missing_mandatory.append(cmd)
    
    available_optional = {}
    for tool_name, variants in OPTIONAL_TOOLS.items():
        available = any(is_tool_available(v) for v in variants)
        available_optional[tool_name] = available
    
    # Always populate ARCHIVE_FORMATS
    ARCHIVE_FORMATS = {k: v for k, v in ALL_FORMATS.items()
                       if all(is_tool_available(t) for t in v['requires'])}
    
    if not skip_errors and missing_mandatory:
        print(f"Error: Missing required dependencies: {', '.join(missing_mandatory)}. Install ImageMagick from your package manager.", file=sys.stderr)
        sys.exit(1)
    
    if not skip_errors:
        if not available_optional.get('unrar'):
            print("Warning: unrar not found. CBR/RAR files will be skipped.", file=sys.stderr)
        if not available_optional.get('7z'):
            print("Warning: 7z not found. CB7/7Z files will be skipped.", file=sys.stderr)
    
    return len(missing_mandatory) == 0


def positive_int(value: str) -> int:
    """Parse a strictly positive command-line integer."""
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args():
    parser = argparse.ArgumentParser(
        description="Audit comic archives (CBZ, ZIP, CBR, RAR, CB7, 7Z) "
                    "for JPEG image quality and corruption using ImageMagick."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Comic archive file or directory containing comic archives "
             "(supports: .cbz, .zip, .cbr, .rar, .cb7, .7z)",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        default=False,
        help="Scan all images in each archive (default: sample 5)",
    )
    parser.add_argument(
        "-t", "--threshold",
        type=int,
        default=70,
        help="Quality threshold for LOW QUALITY classification (default: 70)",
    )
    parser.add_argument(
        "--page-size",
        nargs="?",
        type=positive_int,
        const=100,
        default=None,
        metavar="KB",
        help="Flag archives averaging below KB per page (default when enabled: 100)",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        default=False,
        help="Process directories recursively",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Print detailed output for all archives",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be scanned without running",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args()


def extract_archive(archive_path: Path, output_dir: Path, fmt_config: ArchiveFormatConfig) -> None:
    """Extract archive using format-specific command.
    
    Raises:
        ArchiveExtractionError: If extraction fails.
    """
    if fmt_config is ALL_FORMATS['zip']:
        try:
            extract_zip_archive(archive_path, output_dir)
        except ZipArchiveError as error:
            raise ArchiveExtractionError(str(error)) from error
        return

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
        raise ArchiveExtractionError(f"Failed to extract {archive_path}: command returned {e.returncode}")


def get_sample_indices(total: int, count: int = 5) -> list[int]:
    """Return count evenly spaced indices for total images."""
    if total <= count:
        return list(range(total))
    step = total / count
    return [int(i * step) for i in range(count)]


def scan_image(image_path: Path) -> tuple[bool, int | None]:
    """Run identify on a single image. Returns (is_ok, quality).
    
    is_ok: True if image is not corrupted
    quality: integer quality estimate (1-100), or None if unparseable
    """
    CORRUPTION_PATTERNS = ['error', 'corrupt', 'insufficient image data']
    
    try:
        result = subprocess.run(
            ['identify', '-format', '%Q', str(image_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        quality_str = result.stdout.strip()
        stderr = result.stderr.lower()
        
        # Strict corruption check
        is_corrupted = (
            result.returncode != 0
            or any(pattern in stderr for pattern in CORRUPTION_PATTERNS)
        )
        
        # Extract quality if available
        quality = None
        if quality_str:
            try:
                quality = int(quality_str)
            except ValueError:
                pass
        
        return (not is_corrupted, quality)
        
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return (False, None)


def scan_images(image_paths: list[Path], on_progress: Callable[[int], None] | None = None) -> tuple[list[bool], list[int | None], list[Path]]:
    """Scan multiple images. Returns (corrupted_flags, quality_scores, corrupted_paths).
    
    Args:
        image_paths: List of image paths to scan
        on_progress: Optional callback(current_index) for progress updates
    """
    corrupted = []
    qualities = []
    corrupted_paths = []
    for i, path in enumerate(image_paths):
        is_ok, quality = scan_image(path)
        corrupted.append(not is_ok)
        qualities.append(quality)
        if not is_ok:
            corrupted_paths.append(path)
        if on_progress:
            on_progress(i + 1)
    return (corrupted, qualities, corrupted_paths)


def get_file_sizes(image_paths: list[Path]) -> list[int]:
    """Return raw sizes in bytes for the selected image files."""
    return [path.stat().st_size for path in image_paths]


def create_file_progress_callback(total: int):
    """Create callback for file-level progress."""
    def callback(current: int):
        print(f"\rScanning [{current}/{total}]", end="", flush=True)
    return callback


def create_image_progress_callback(file_name: str, total_images: int):
    """Create callback for image-level progress."""
    max_len = len(f"Processing: {file_name} [{total_images}/{total_images}] |{'=' * 20}|")
    
    def callback(current: int):
        if total_images <= 0:
            filled = 0
        else:
            filled = int(20 * current / total_images)
        bar = '=' * filled + ' ' * (20 - filled)
        line = f"Processing: {file_name} [{current}/{total_images}] |{bar}|"
        padded = line.ljust(max_len)
        print(f"\r{padded}", end="", flush=True)
    
    return callback, max_len


def print_archive_report(
    archive_name: str,
    total_images: int,
    sampled_count: int,
    corrupted_count: int,
    qualities: list[int | None],
    corrupted_paths: list[Path],
    threshold: int,
    verbose: bool,
    page_sizes: list[int] | None = None,
    page_size_threshold: int | None = None,
) -> bool:
    """Print report for a single archive. Returns True if it has issues."""
    valid_qualities = [q for q in qualities if q is not None]
    avg_quality = sum(valid_qualities) / len(valid_qualities) if valid_qualities else 0
    avg_page_bytes = (
        sum(page_sizes) / len(page_sizes)
        if page_size_threshold is not None and page_sizes
        else None
    )

    is_unreadable = corrupted_count > 0
    is_low_quality = avg_quality < threshold if valid_qualities else False
    is_small_pages = (
        avg_page_bytes < page_size_threshold * 1024
        if avg_page_bytes is not None and page_size_threshold is not None
        else False
    )

    statuses = []
    if is_unreadable:
        statuses.append("UNREADABLE")
    if is_low_quality:
        statuses.append("LOW QUALITY")
    if is_small_pages:
        statuses.append("SMALL PAGES")
    status = " + ".join(statuses) if statuses else "OK"
    has_issues = bool(statuses)

    if not verbose and not has_issues:
        return False

    if verbose:
        print(f"\n{archive_name} [{status}]")
        print(f"  Sampled {sampled_count}/{total_images} images, avg quality: {avg_quality:.0f}")
        if avg_page_bytes is not None and page_size_threshold is not None:
            print(
                f"  Average page size: {avg_page_bytes / 1024:.0f} KB "
                f"(threshold: {page_size_threshold} KB)"
            )
        if is_low_quality:
            low_q = sum(1 for q in valid_qualities if q < threshold)
            print(f"  Low quality: {low_q}/{sampled_count} images below threshold {threshold}")
        if is_unreadable:
            print("  Corrupted images:")
            for corrupted_path in corrupted_paths:
                print(f"    {corrupted_path.name}")
    else:
        parts = []
        if is_unreadable:
            parts.append(f"{corrupted_count} corrupted")
        if is_low_quality:
            parts.append(f"avg={avg_quality:.0f}")
        if is_small_pages and avg_page_bytes is not None:
            parts.append(f"avg page={avg_page_bytes / 1024:.0f} KB")
        print(f"{archive_name}: {status} ({', '.join(parts)})")

    return has_issues


def process_archive(
    input_path: Path,
    full_scan: bool,
    threshold: int,
    verbose: bool,
    dry_run: bool,
    file_index: int | None = None,
    total_files: int | None = None,
    page_size_threshold: int | None = None,
) -> tuple[bool, int, int]:
    """Process a single archive: extract, scan images, report.
    
    Returns: (has_issues, total_jpeg_count, scanned_count)
    """
    input_path = input_path.resolve()
    
    fmt_config = get_format_config(input_path)
    if fmt_config is None:
        return (False, 0, 0)
    
    if dry_run:
        if file_index is not None and total_files is not None:
            print(f"Would scan: {input_path.name}")
        return (False, 0, 0)
    
    with temp_dir(input_path) as temp_path:
        try:
            extract_archive(input_path, temp_path, fmt_config)
        except ArchiveExtractionError as e:
            print(f"Error: {e}", file=sys.stderr)
            # Extraction failed - treat as having issues
            return (True, 0, 0)
        
        jpeg_files = [f for f in temp_path.rglob("*") 
                      if f.is_file() 
                      and f.suffix.lower() in (".jpg", ".jpeg")
                      and not is_appledouble_path(str(f))]
        
        total_jpegs = len(jpeg_files)
        
        if total_jpegs == 0:
            if verbose:
                print(f"\n{input_path.name}: No JPEG images found.")
            return (False, total_jpegs, 0)
        
        # Sort for deterministic sampling
        jpeg_files.sort()
        
        if full_scan:
            selected = jpeg_files
        else:
            indices = get_sample_indices(total_jpegs, 5)
            selected = [jpeg_files[i] for i in indices]
        
        scanned_count = len(selected)
        
        # Create progress callback for full scan (only in non-verbose mode)
        if full_scan and scanned_count > 1 and not verbose:
            progress_cb, max_line_len = create_image_progress_callback(input_path.name, scanned_count)
        else:
            progress_cb = None
            max_line_len = 0
        
        # Clear progress bar line if we printed one
        if progress_cb and not verbose:
            # For non-verbose, we'll clear the progress bar after
            pass
        
        corrupted, qualities, corrupted_paths = scan_images(selected, on_progress=progress_cb)
        corrupted_count = sum(corrupted)

        page_sizes = None
        if page_size_threshold is not None:
            try:
                page_sizes = get_file_sizes(selected)
            except OSError as error:
                print(
                    f"Error: Could not read page sizes for {input_path.name}: {error}",
                    file=sys.stderr,
                )
                return (True, total_jpegs, scanned_count)
        
        # Clear progress bar before reporting
        if progress_cb and not verbose:
            # Pad to clear the line
            clear_line = " " * max_line_len
            print(f"\r{clear_line}\r", end="")
        
        # Report
        has_issues = print_archive_report(
            input_path.name,
            total_jpegs,
            scanned_count,
            corrupted_count,
            qualities,
            corrupted_paths,
            threshold,
            verbose,
            page_sizes=page_sizes,
            page_size_threshold=page_size_threshold,
        )
        
        return (has_issues, total_jpegs, scanned_count)


def main():
    args = parse_args()
    check_dependencies(skip_errors=args.dry_run)
    
    input_path = args.input.resolve()
    
    archive_files = find_archive_files(input_path, args.recursive)
    
    if not archive_files:
        print("Error: No archive files found to process.", file=sys.stderr)
        sys.exit(1)
    
    total_files = len(archive_files)
    issues_found = 0
    
    # File-level progress callback
    if not args.verbose and not args.dry_run and not args.full_scan:
        file_cb = create_file_progress_callback(total_files)
    else:
        file_cb = None
    
    for i, archive_file in enumerate(archive_files, 1):
        has_issues, total_jpegs, scanned = process_archive(
            input_path=archive_file,
            full_scan=args.full_scan,
            threshold=args.threshold,
            verbose=args.verbose,
            dry_run=args.dry_run,
            file_index=i if not args.verbose else None,
            total_files=total_files if not args.verbose else None,
            page_size_threshold=args.page_size,
        )
        if has_issues:
            issues_found += 1
        
        if file_cb:
            file_cb(i)
    
    if file_cb:
        print()  # Newline after progress
    
    if args.dry_run:
        print(f"\nDry run: would scan {total_files} archive(s).")
        sys.exit(0)
    
    if issues_found > 0:
        print(f"\nFound {issues_found} archive(s) with issues.")
    elif args.verbose:
        print(f"\nAll {total_files} archive(s) OK.")
    
    sys.exit(0 if issues_found == 0 else 1)


if __name__ == "__main__":
    main()
