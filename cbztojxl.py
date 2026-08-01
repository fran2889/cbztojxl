#!/usr/bin/env python3
"""Convert CBZ archives containing JPEG images to JXL format.

Requires cjxl v0.11+ for -q 100 (mathematically lossless) conversion.
"""

__version__ = "1.0.0"

import argparse
import locale
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TypedDict

from zip_support import (
    ZipArchiveError,
    count_zip_jpegs,
    extract_zip_archive,
    write_zip_archive,
)

# Exit code constants
EXIT_DEPENDENCY_ERROR = 1
EXIT_CONVERSION_ERROR = 2
EXIT_NO_FILES = 3

# UI constants
PROGRESS_BAR_WIDTH = 20

# Conversion constants
CJXL_QUALITY = 100


class ConversionError(Exception):
    """Raised when archive processing fails."""
    pass


class DependencyError(Exception):
    """Raised when required dependencies are missing."""
    pass


class WorkspaceCleanupError(Exception):
    """Raised when an extraction workspace cannot be removed."""

    def __init__(self, error: OSError):
        super().__init__(str(error))
        self.error = error


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

# Will be populated at runtime based on available tools
ARCHIVE_FORMATS: dict[str, ArchiveFormatConfig] = {}


ANSI_ESCAPE_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)?)"
)
POSIX_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.])/(?:[^\s/:]+/)*[^\s/:]+")
WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?<![\w.])(?:[a-z]:[\\/]|\\\\)[^\s:]+"
)


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
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
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
    
    Mandatory tools (cjxl) cause script to exit if missing.
    Optional tools (unrar, 7z) generate warnings, matching formats excluded from ARCHIVE_FORMATS.
    """
    global ARCHIVE_FORMATS
    
    MANDATORY_TOOLS = ['cjxl']
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
    input_path = lexical_absolute(input_path)
    
    # Discover every recognized format. Availability is reported per archive.
    supported_extensions = []
    for fmt in ALL_FORMATS.values():
        supported_extensions.extend(fmt['extensions'])
    
    # ZIP support is built in, so at least one archive format is always available.
    if not supported_extensions:
        print("Error: No archive formats available", file=sys.stderr)
        sys.exit(EXIT_DEPENDENCY_ERROR)
    
    # Single file with supported extension
    if input_path.is_file():
        if input_path.suffix.lower() in supported_extensions:
            return [input_path]
        input_display = sanitize_fragment(input_path.name)
        print(f"Error: {input_display} is not a valid archive file", file=sys.stderr)
        print(f"Supported formats: {', '.join(sorted(set(supported_extensions)))}", file=sys.stderr)
        sys.exit(EXIT_DEPENDENCY_ERROR)
    
    # Directory - find all files with supported extensions
    if input_path.is_dir():
        pattern = "**/*" if recursive else "*"
        all_files = list(input_path.glob(pattern))
        return sorted(
            (f for f in all_files if f.is_file()
             and f.suffix.lower() in supported_extensions),
            key=lambda path: path.relative_to(input_path).as_posix(),
        )
    
    # Invalid input
    input_display = sanitize_fragment(input_path.name)
    print(f"Error: {input_display} is not a valid file or directory", file=sys.stderr)
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
    return (
        f"{format_file_size(input_size)} => {format_file_size(output_size)} "
        f"({reduction_pct:.1f}% smaller)"
    )


def format_total(
    archive_count: int,
    successful_count: int,
    skipped_count: int,
    failed_count: int,
    input_size: int,
    output_size: int,
) -> str:
    """Format aggregate archive counts and converted sizes."""
    counts = (
        f"{successful_count} done, {skipped_count} skipped, "
        f"{failed_count} failed"
    )
    total = f"[total] {archive_count} archives | {counts}"
    if input_size:
        total += f" | {format_size_reduction(input_size, output_size)}"
    return total


def is_appledouble_path(path: str | os.PathLike) -> bool:
    """Check if a file path is an AppleDouble metadata file.
    
    AppleDouble files start with '._' or are inside '__MACOSX' directories.
    Accepts both str and PathLike objects.
    """
    # Standardize path to str to handle both str and PathLike inputs
    path = str(path)
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
    
    Raises DependencyError when the archive cannot be listed.
    """
    if fmt_config is ALL_FORMATS['zip']:
        try:
            return count_zip_jpegs(archive_path, is_jpeg_file)
        except ZipArchiveError as error:
            raise DependencyError(str(error)) from error

    cmd = [c.format(archive=str(archive_path)) for c in fmt_config['list_cmd']]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        count = 0
        stdout = _decode_subprocess_output(result.stdout)
        for line in stdout.splitlines():
            lower_line = line.lower()
            if (lower_line.endswith('.jpg') or lower_line.endswith('.jpeg')) \
               and not is_appledouble_path(lower_line):
                count += 1
        return count
    except (subprocess.CalledProcessError, OSError) as error:
        raise DependencyError(command_diagnostic(cmd[0], error)) from error


def sanitize_fragment(value: object) -> str:
    """Escape terminal control characters in a user-visible text fragment."""
    result = []
    for character in str(value):
        codepoint = ord(character)
        if character == "\n":
            result.append("\\n")
        elif character == "\r":
            result.append("\\r")
        elif character == "\t":
            result.append("\\t")
        elif unicodedata.category(character).startswith("C"):
            if codepoint <= 255:
                result.append(f"\\x{codepoint:02x}")
            elif codepoint <= 0xFFFF:
                result.append(f"\\u{codepoint:04x}")
            else:
                result.append(f"\\U{codepoint:08x}")
        else:
            result.append(character)
    return "".join(result)


def sanitize_path_fragment(value: object) -> str:
    """Sanitize a path without allowing it to forge transcript separators."""
    return (
        sanitize_fragment(value)
        .replace("=>", "%3D%3E")
        .replace("|", "%7C")
    )


def _decode_subprocess_output(output: bytes | str | None) -> str:
    if isinstance(output, bytes):
        return output.decode(locale.getpreferredencoding(False), errors="replace")
    return output or ""


def _redact_diagnostic(text: str, arguments: list[str] | None = None) -> str:
    """Remove command arguments, absolute paths, and terminal controls."""
    for argument in sorted(arguments or [], key=len, reverse=True):
        if argument and argument != ".":
            text = text.replace(argument, "<arg>")
    text = ANSI_ESCAPE_RE.sub("", text)
    text = WINDOWS_ABSOLUTE_PATH_RE.sub("<path>", text)
    text = POSIX_ABSOLUTE_PATH_RE.sub("<path>", text)
    text = "".join(
        " "
        if unicodedata.category(character).startswith("C")
        else character
        for character in text
    )
    return " ".join(text.split())


def filesystem_diagnostic(error: OSError) -> str:
    """Return an OSError diagnostic without including filesystem paths."""
    detail = error.strerror or "operation failed"
    return f"filesystem error: {_redact_diagnostic(detail)}"


def command_diagnostic(
    tool: str, error: subprocess.CalledProcessError | OSError
) -> str:
    """Return a concise subprocess failure without exposing command arguments."""
    if isinstance(error, OSError):
        detail = _redact_diagnostic(error.strerror or "operation failed")
        return f"{sanitize_fragment(Path(tool).name)} failed: {detail}"
    command = error.cmd if isinstance(error.cmd, (list, tuple)) else []
    arguments = [str(argument) for argument in command[1:]]
    lines = _decode_subprocess_output(error.stderr).strip().splitlines()
    detail = _redact_diagnostic(lines[-1], arguments) if lines else ""
    suffix = f": {detail}" if detail else ""
    return (
        f"{sanitize_fragment(Path(tool).name)} exited with status "
        f"{error.returncode}{suffix}"
    )



def extract_archive(archive_path: Path, output_dir: Path, fmt_config: ArchiveFormatConfig) -> None:
    """Extract archive using format-specific command.
    
    Raises:
        DependencyError: If extraction fails.
    """
    if fmt_config is ALL_FORMATS['zip']:
        try:
            extract_zip_archive(archive_path, output_dir)
        except ZipArchiveError as error:
            raise DependencyError(str(error)) from error
        return

    # Build command by formatting placeholders
    cmd = [c.format(archive=str(archive_path), output=str(output_dir)) 
           for c in fmt_config['extract_cmd']]
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except (subprocess.CalledProcessError, OSError) as error:
        raise DependencyError(command_diagnostic(cmd[0], error)) from error


def display_input_path(input_path: Path, base_input: Path) -> str:
    """Return an input path relative to the supplied input root when possible."""
    if lexical_absolute(input_path) == lexical_absolute(base_input):
        return sanitize_path_fragment(Path(input_path.name))
    base = base_input.parent if base_input.is_file() else base_input
    try:
        display = lexical_absolute(input_path).relative_to(lexical_absolute(base))
    except ValueError:
        display = Path(input_path.name)
    return sanitize_path_fragment(display)


def display_output_path(output_path: Path, output_root: Path) -> str:
    """Return an output path relative to the supplied output root when possible."""
    try:
        display = (
            lexical_absolute(output_path).relative_to(lexical_absolute(output_root))
        )
    except ValueError:
        display = Path(output_path.name)
    return sanitize_path_fragment(display)


def lexical_absolute(path: Path) -> Path:
    """Return an absolute normalized path without resolving symbolic links."""
    return Path(os.path.abspath(os.fspath(path)))


def validate_output_path(output_path: Path, output_root: Path) -> None:
    """Reject destinations that escape the output root or use a symlink leaf."""
    output_path = lexical_absolute(output_path)
    output_root = lexical_absolute(output_root)
    if output_path.is_symlink():
        raise DependencyError(
            "filesystem error: output path is a symbolic link"
        )
    try:
        relative_parent = output_path.parent.relative_to(output_root)
        candidate = output_root
        for component in relative_parent.parts:
            candidate /= component
            if candidate.is_symlink():
                candidate.stat()
        if output_root.is_symlink():
            output_root.stat()
        output_path.parent.resolve(strict=False).relative_to(
            output_root.resolve(strict=False)
        )
    except (OSError, RuntimeError) as error:
        raise DependencyError(
            "filesystem error: output path cannot be resolved safely"
        ) from error
    except ValueError as error:
        raise DependencyError(
            "filesystem error: output path escapes output root"
        ) from error


@contextmanager
def temp_dir(parent_dir: Path) -> Iterator[Path]:
    """Create a temporary directory beneath the requested output parent."""
    parent_dir = lexical_absolute(parent_dir)
    parent_dir.mkdir(parents=True, exist_ok=True)
    temp_path = Path(tempfile.mkdtemp(prefix=".cbztojxl_tmp_", dir=parent_dir))
    try:
        yield temp_path
    finally:
        try:
            shutil.rmtree(temp_path)
        except OSError as error:
            raise WorkspaceCleanupError(error) from error



def convert_jpegs_to_jxl(
    temp_dir: Path,
    on_progress=None,
    verbose: bool = False,
) -> list[tuple[int, Path, subprocess.CalledProcessError | OSError]]:
    """Convert all .jpg/.jpeg files in temp_dir to .jxl, delete originals (recursively).
    
    Returns:
        List of (page index, filepath, error) tuples for any failures.
    """
    failures = []
    
    # Find all JPEG files recursively, excluding AppleDouble metadata files
    jpeg_files = sorted(
        (f for f in temp_dir.rglob("*") if f.is_file() and is_jpeg_file(f)),
        key=lambda path: path.relative_to(temp_dir).as_posix(),
    )
    
    for i, filepath in enumerate(jpeg_files):
        jxl_path = filepath.with_suffix(".jxl")

        if verbose:
            page_display = sanitize_path_fragment(filepath.relative_to(temp_dir))
            print(f"  Converting page {i+1}/{len(jpeg_files)}: {page_display}")

        try:
            # Use -q CJXL_QUALITY (mathematically lossless for cjxl v0.11+)
            subprocess.run(
                ["cjxl", "-q", str(CJXL_QUALITY), str(filepath), str(jxl_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            # Delete original on success
            filepath.unlink()
            
            # Call progress callback after successful conversion
            if on_progress:
                on_progress(i + 1)
        except (subprocess.CalledProcessError, OSError) as error:
            failures.append((i + 1, filepath, error))
            break

    return failures


def create_cbz(output_path: Path, source_dir: Path) -> None:
    """Create a CBZ in private sibling staging and replace the destination."""
    output_path = lexical_absolute(output_path)
    staging_dir: Path | None = None
    failure: DependencyError | None = None
    try:
        if output_path.is_symlink():
            raise DependencyError(
                "filesystem error: output path is a symbolic link"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=".cbztojxl_stage_",
                dir=output_path.parent,
            )
        )
        staged_path = staging_dir / "archive.cbz"
        validate_output_path(staged_path, output_path.parent)
        write_zip_archive(staged_path, source_dir)
        if output_path.is_symlink():
            raise DependencyError(
                "filesystem error: output path is a symbolic link"
            )
        os.replace(staged_path, output_path)
    except DependencyError as error:
        failure = error
    except ZipArchiveError as error:
        failure = DependencyError(str(error))
    except OSError as error:
        failure = DependencyError(filesystem_diagnostic(error))
    finally:
        if staging_dir is not None:
            try:
                shutil.rmtree(staging_dir)
            except OSError as error:
                cleanup_detail = filesystem_diagnostic(error)
                if failure is None:
                    failure = DependencyError(cleanup_detail)
                else:
                    cleanup_reason = cleanup_detail.removeprefix(
                        "filesystem error: "
                    )
                    failure = DependencyError(
                        f"{failure}; staging cleanup also failed: "
                        f"{cleanup_reason}"
                    )

    if failure is not None:
        raise failure


def compute_output_path(
    input_path: Path,
    base_input: Path,
    output_dir: Path | None,
    overwrite: bool,
) -> Path:
    """Compute the output path for a converted archive file.
    
    Always uses .cbz extension for output, regardless of input format.
    """
    input_path = lexical_absolute(input_path)
    base_input = lexical_absolute(base_input)
    
    if output_dir is None:
        # Default: add _jxl suffix next to source, with .cbz extension
        return input_path.with_stem(input_path.stem + "_jxl").with_suffix('.cbz')
    
    output_dir = lexical_absolute(output_dir)
    
    # In-place replacement: output_dir equals source directory AND overwrite
    same_physical_parent = False
    if overwrite:
        try:
            same_physical_parent = (
                output_dir.resolve(strict=False)
                == input_path.parent.resolve(strict=False)
            )
        except (OSError, RuntimeError):
            pass
    if same_physical_parent:
        return (output_dir / input_path.name).with_suffix('.cbz')
    
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


def report_processed(
    source_display: str,
    target_display: str,
    input_size: int,
    output_size: int,
    page_count: int,
    max_line_len: int = 0,
) -> None:
    """Report a completed conversion in the compact output format."""
    source_display = sanitize_path_fragment(source_display)
    target_display = sanitize_path_fragment(target_display)
    page_label = "page" if page_count == 1 else "pages"
    message = (
        f"[done]  {source_display} => {target_display} | "
        f"{page_count} {page_label} | "
        f"{format_size_reduction(input_size, output_size)}"
    )
    print(f"\r{message.ljust(max_line_len)}" if max_line_len else message)


def clear_progress_line(max_line_len: int) -> None:
    """Clear a live progress line and return the terminal cursor to column zero."""
    if max_line_len:
        print(f"\r{' ' * max_line_len}\r", end="", flush=True)


def report_error(primary: str, detail: str) -> None:
    """Report an archive stage failure with an indented diagnostic."""
    sys.stdout.flush()
    print(f"[error] {sanitize_fragment(primary)}", file=sys.stderr)
    print(f"        {_redact_diagnostic(str(detail))}", file=sys.stderr, flush=True)


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
        - 'error_cleanup' - temporary workspace cleanup failed
    """
    input_path = lexical_absolute(input_path)
    source_display = display_input_path(input_path, base_input)
    try:
        input_size = input_path.stat().st_size
    except OSError as error:
        report_error(
            f"{source_display} | extract archive failed",
            filesystem_diagnostic(error),
        )
        return 0, 0, "error_extract"

    try:
        output_path = compute_output_path(
            input_path, base_input, output_dir, overwrite
        )
        output_root = lexical_absolute(output_dir) if output_dir else output_path.parent
        target_display = display_output_path(output_path, output_root)
    except OSError as error:
        report_error(
            f"{source_display} | create archive failed",
            filesystem_diagnostic(error),
        )
        return input_size, 0, "error_create"

    fmt_config = get_format_config(input_path)
    if fmt_config is None:
        print(f"[skip]  {source_display} | archiver not available")
        return input_size, 0, "skipped_format"

    try:
        image_count = count_jpegs_in_archive(input_path, fmt_config)
    except (DependencyError, OSError) as error:
        detail = (
            str(error)
            if isinstance(error, DependencyError)
            else filesystem_diagnostic(error)
        )
        report_error(f"{source_display} | extract archive failed", detail)
        return input_size, 0, "error_extract"

    if image_count == 0:
        print(f"[skip]  {source_display} | no JPEG pages")
        return input_size, 0, "skipped_no_jpeg"

    try:
        validate_output_path(output_path, output_root)
        output_exists = output_path.exists()
    except (DependencyError, OSError) as error:
        detail = (
            str(error)
            if isinstance(error, DependencyError)
            else filesystem_diagnostic(error)
        )
        report_error(
            f"{source_display} => {target_display} | create archive failed",
            detail,
        )
        return input_size, 0, "error_create"

    if output_exists and not overwrite:
        print(
            f"[skip]  {source_display} => {target_display} | "
            "output already exists"
        )
        return input_size, 0, "skipped_exists"

    if dry_run:
        report_processed(
            source_display,
            target_display,
            input_size,
            input_size,
            image_count,
        )
        return input_size, input_size, "processed"

    max_line_len = 0
    jpeg_count = image_count
    failure: tuple[str, str, str] | None = None

    if verbose:
        print(source_display)

    try:
        with temp_dir(output_path.parent) as temp_path:
            try:
                validate_output_path(temp_path, output_root)
                if verbose:
                    temp_display = display_output_path(temp_path, output_root)
                    print(f"  Extracting to: {temp_display}")
                extract_archive(input_path, temp_path, fmt_config)
                jpeg_files = [
                    path
                    for path in temp_path.rglob("*")
                    if path.is_file() and is_jpeg_file(path)
                ]
                jpeg_count = len(jpeg_files)
            except (DependencyError, OSError) as error:
                detail = (
                    str(error)
                    if isinstance(error, DependencyError)
                    else filesystem_diagnostic(error)
                )
                failure = (
                    "error_extract",
                    f"{source_display} | extract archive failed",
                    detail,
                )

            if failure is None:
                if (
                    show_progress_bar
                    and file_index is not None
                    and total_files is not None
                ):
                    progress_cb, max_line_len = create_progress_callback(
                        source_display,
                        file_index,
                        total_files,
                        jpeg_count,
                        target_display,
                    )
                else:
                    progress_cb = None

                try:
                    failures = convert_jpegs_to_jxl(
                        temp_path,
                        on_progress=progress_cb,
                        verbose=verbose,
                    )
                except OSError as error:
                    failure = (
                        "error_convert",
                        f"{source_display} | convert pages failed",
                        filesystem_diagnostic(error),
                    )
                else:
                    if failures:
                        page_index, filepath, error = failures[0]
                        try:
                            page_path = filepath.relative_to(temp_path)
                        except ValueError:
                            page_path = Path(filepath.name)
                        page_display = sanitize_path_fragment(page_path)
                        detail = (
                            command_diagnostic("cjxl", error)
                            if isinstance(error, subprocess.CalledProcessError)
                            else filesystem_diagnostic(error)
                        )
                        failure = (
                            "error_convert",
                            f"{source_display} | convert page "
                            f"{page_index}/{jpeg_count}: {page_display} failed",
                            detail,
                        )

            if failure is not None:
                clear_progress_line(max_line_len)
            else:
                if verbose:
                    print(f"  Creating: {target_display}")
                try:
                    validate_output_path(output_path, output_root)
                    create_cbz(output_path, temp_path)
                except (DependencyError, OSError) as error:
                    detail = (
                        str(error)
                        if isinstance(error, DependencyError)
                        else filesystem_diagnostic(error)
                    )
                    clear_progress_line(max_line_len)
                    failure = (
                        "error_create",
                        f"{source_display} => {target_display} | "
                        "create archive failed",
                        detail,
                    )
    except WorkspaceCleanupError as error:
        clear_progress_line(max_line_len)
        cleanup_detail = filesystem_diagnostic(error.error)
        if failure is None:
            failure = (
                "error_cleanup",
                f"{source_display} | cleanup workspace failed",
                cleanup_detail,
            )
        else:
            status, primary, detail = failure
            cleanup_reason = cleanup_detail.removeprefix("filesystem error: ")
            failure = (
                status,
                primary,
                f"{detail}; cleanup also failed: {cleanup_reason}",
            )
    except OSError as error:
        clear_progress_line(max_line_len)
        failure = (
            "error_extract",
            f"{source_display} | extract archive failed",
            filesystem_diagnostic(error),
        )

    if failure is not None:
        status, primary, detail = failure
        report_error(primary, detail)
        return input_size, 0, status

    try:
        output_size = output_path.stat().st_size
    except OSError as error:
        report_error(
            f"{source_display} => {target_display} | create archive failed",
            filesystem_diagnostic(error),
        )
        return input_size, 0, "error_create"

    report_processed(
        source_display,
        target_display,
        input_size,
        output_size,
        jpeg_count,
        max_line_len,
    )
    return input_size, output_size, "processed"


def create_progress_callback(file_name: str, file_index: int, total_files: int, total_images: int, target_display: str = "") -> tuple[Callable[[int], None], int]:
    """Returns a tuple of (callback, max_line_length) for progress display."""
    file_name = sanitize_path_fragment(file_name)
    target_display = sanitize_path_fragment(target_display)
    # Progress bar line length (when complete)
    progress_line = f"{file_name} [{file_index}/{total_files}] |{'=' * PROGRESS_BAR_WIDTH}| {total_images}/{total_images}"
    
    # Summary line length estimate
    # The actual summary line will be: [done]  {file_name} => {target_display} | {page_count} pages | {size_info}
    # We don't have jpeg_count and size_info here, but we can estimate
    summary_line_estimate = f"[done]  {file_name} => {target_display} | {total_images} pages | "
    # Add a buffer for size_info (roughly 50 chars max)
    summary_line_estimate += "X" * 50
    
    max_line_len = max(len(progress_line), len(summary_line_estimate))
    
    def callback(current_image: int):
        if total_images <= 0:
            filled = 0
        else:
            filled = int(PROGRESS_BAR_WIDTH * current_image / total_images)
        bar = '=' * filled + ' ' * (PROGRESS_BAR_WIDTH - filled)
        line = f"{file_name} [{file_index}/{total_files}] |{bar}| {current_image}/{total_images}"
        # Pad to max length and use carriage return
        padded_line = line.ljust(max_line_len)
        print(f"\r{padded_line}", end="", flush=True)
    return callback, max_line_len


def main() -> None:
    args = parse_args()
    check_dependencies()

    input_path = lexical_absolute(args.input)
    output_dir = lexical_absolute(args.output_dir) if args.output_dir else None

    # Find all archive files to process
    archive_files = find_archive_files(input_path, args.recursive)

    if not archive_files:
        print("No archive files found to process.", file=sys.stderr)
        sys.exit(EXIT_NO_FILES)

    if args.verbose:
        print(f"Found {len(archive_files)} archive file(s) to process")

    # Track total sizes for final summary
    total_input_size = 0
    total_output_size = 0
    successful_count = 0
    skipped_count = 0
    failed_count = 0
    
    # Show progress bar only in normal mode (no verbose, no dry run)
    show_progress_bar = not args.verbose and not args.dry_run
    
    for i, archive_file in enumerate(archive_files, 1):
        input_size, output_size, status = process_archive(
            input_path=archive_file,
            base_input=input_path,
            output_dir=output_dir,
            overwrite=args.overwrite,
            verbose=args.verbose,
            dry_run=args.dry_run,
            file_index=i,
            total_files=len(archive_files),
            show_progress_bar=show_progress_bar,
        )
        # Accumulate sizes for total summary
        if status == "processed":
            total_input_size += input_size
            total_output_size += output_size
            successful_count += 1
        elif status == "skipped_no_jpeg" or status == "skipped_format" or status == "skipped_exists":
            # For skipped files, don't include in total calculation as no processing occurred
            skipped_count += 1
        elif status.startswith("error_"):
            # Track processing errors
            failed_count += 1

    print(
        f"\n{format_total(len(archive_files), successful_count, skipped_count, failed_count, total_input_size, total_output_size)}"
    )

    if failed_count:
        sys.exit(EXIT_CONVERSION_ERROR)

    sys.exit(0)


if __name__ == "__main__":
    main()
