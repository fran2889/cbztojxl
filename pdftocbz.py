#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Fran
# SPDX-License-Identifier: GPL-3.0-only

"""Convert PDF comic files into conventional CBZ archives."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


__version__ = "1.0.0"

EXIT_DEPENDENCY_ERROR = 1
EXIT_CONVERSION_ERROR = 2
EXIT_NO_FILES = 3

REQUIRED_TOOLS = ("pdfinfo", "pdftotext", "pdfimages", "pdftocairo")


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Convert PDF comics to conventional CBZ archives.")
    parser.add_argument("input", type=Path, help="PDF file or directory containing PDFs")
    parser.add_argument("output_dir", nargs="?", type=Path, default=None)
    parser.add_argument("-r", "--recursive", action="store_true")
    parser.add_argument("-o", "--overwrite", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--replace-source",
        action="store_true",
        help="Replace each source PDF after successful conversion",
    )
    parser.add_argument("--fallback-dpi", type=int, default=300)
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    args = parser.parse_args()
    if args.replace_source and args.output_dir is not None:
        parser.error("--replace-source cannot be used with output_dir")
    return args


def check_dependencies() -> None:
    """Exit with a clear error if a required command is unavailable."""
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        print("Error: Missing required dependencies: " + ", ".join(missing), file=sys.stderr)
        raise SystemExit(EXIT_DEPENDENCY_ERROR)


def find_pdf_files(input_path: Path, recursive: bool) -> list[Path]:
    """Find PDF files at input_path, optionally including subdirectories."""
    input_path = input_path.absolute()
    if input_path.is_file():
        if input_path.suffix.lower() == ".pdf":
            return [input_path]
        raise ValueError("Input file is not a PDF: " + str(input_path))
    if input_path.is_dir():
        iterator = input_path.rglob("*") if recursive else input_path.glob("*")
        return sorted(path for path in iterator if path.is_file() and path.suffix.lower() == ".pdf")
    raise ValueError("Input path does not exist: " + str(input_path))


@dataclass(frozen=True)
class EmbeddedImage:
    """Metadata for an image object reported by pdfimages."""

    page: int
    number: int
    encoding: str
    width: int
    height: int
    x_ppi: float
    y_ppi: float


@dataclass(frozen=True)
class PageBuildResult:
    """Counts of the methods used to build a comic's page images."""

    total: int
    lossless: int
    rerendered: int


def parse_pdfimages_list(output: str) -> list[EmbeddedImage]:
    """Parse image records from ``pdfimages -list`` output."""
    images = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 15 or not fields[0].isdigit() or not fields[1].isdigit():
            continue
        try:
            images.append(
                EmbeddedImage(
                    page=int(fields[0]),
                    number=int(fields[1]),
                    encoding=fields[8].lower(),
                    width=int(fields[3]),
                    height=int(fields[4]),
                    x_ppi=float(fields[12]),
                    y_ppi=float(fields[13]),
                )
            )
        except ValueError:
            continue
    return images


def compute_output_path(
    input_path: Path,
    base_input: Path,
    output_dir: Path | None,
    replace_source: bool = False,
) -> Path:
    """Return the conventional CBZ output path for an input PDF."""
    if replace_source:
        return input_path.absolute().with_suffix(".cbz")
    input_path = input_path.resolve()
    if output_dir is None:
        return input_path.with_suffix(".cbz")
    try:
        relative_path = input_path.relative_to(base_input.resolve())
    except ValueError:
        relative_path = Path(input_path.name)
    return (output_dir.resolve() / relative_path).with_suffix(".cbz")


def find_output_path_collisions(
    pdf_files: list[Path],
    base_input: Path,
    output_dir: Path | None,
    replace_source: bool = False,
) -> set[Path]:
    """Return inputs whose computed output path is shared by another input."""
    destinations: dict[Path | str, list[Path]] = {}
    for pdf_file in pdf_files:
        output_path = compute_output_path(
            pdf_file, base_input, output_dir, replace_source
        )
        destination_key: Path | str = output_path
        if replace_source:
            destination_key = str(output_path).casefold()
        destinations.setdefault(destination_key, []).append(pdf_file)
    return {
        pdf_file
        for matching_inputs in destinations.values()
        if len(matching_inputs) > 1
        for pdf_file in matching_inputs
    }


def run_command(command: list[str]) -> subprocess.CompletedProcess:
    """Run a text-producing external command."""
    return subprocess.run(command, check=True, capture_output=True, text=True)


def get_page_count(pdf_path: Path) -> int:
    """Read the PDF page count from pdfinfo."""
    for line in run_command(["pdfinfo", str(pdf_path)]).stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise ValueError("pdfinfo did not report a page count for " + str(pdf_path))


def page_has_text(pdf_path: Path, page: int) -> bool:
    """Return whether a page has non-whitespace extractable text."""
    result = run_command(["pdftotext", "-f", str(page), "-l", str(page), str(pdf_path), "-"])
    return bool(result.stdout.strip())


def select_direct_image(images: list[EmbeddedImage], page: int, extracted_dir: Path) -> Path | None:
    """Return an extracted JPEG only when its page has exactly one JPEG object."""
    candidates = [image for image in images if image.page == page and image.encoding == "jpeg"]
    if len(candidates) != 1:
        return None
    candidate = extracted_dir / ("image-" + str(candidates[0].number).zfill(3) + ".jpg")
    return candidate if candidate.is_file() else None


def select_render_dpi(images: list[EmbeddedImage], page: int, fallback_dpi: int) -> int:
    """Choose the largest JPEG's averaged PPI or the configured fallback."""
    candidates = [image for image in images if image.page == page and image.encoding == "jpeg" and image.x_ppi > 0 and image.y_ppi > 0]
    if not candidates:
        return fallback_dpi
    primary = max(candidates, key=lambda image: image.width * image.height)
    return round((primary.x_ppi + primary.y_ppi) / 2)


@contextmanager
def temp_dir(source_path: Path):
    path = Path(tempfile.mkdtemp(prefix=".pdftocbz_tmp_", dir=source_path.parent.resolve()))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def render_page(pdf_path: Path, page: int, dpi: int, destination: Path) -> None:
    """Render one PDF page as a high-quality JPEG."""
    subprocess.run(
        ["pdftocairo", "-f", str(page), "-l", str(page), "-singlefile", "-jpeg",
         "-jpegopt", "quality=95", "-r", str(dpi), str(pdf_path), str(destination.with_suffix(""))],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )


def build_page_images(
    pdf_path: Path, work_dir: Path, fallback_dpi: int, verbose: bool
) -> PageBuildResult:
    """Create one JPEG under work_dir/pages for every PDF page."""
    page_count = get_page_count(pdf_path)
    lossless = 0
    rerendered = 0
    images = parse_pdfimages_list(run_command(["pdfimages", "-list", str(pdf_path)]).stdout)
    extracted_dir = work_dir / "extracted"
    pages_dir = work_dir / "pages"
    extracted_dir.mkdir()
    pages_dir.mkdir()
    subprocess.run(["pdfimages", "-j", str(pdf_path), str(extracted_dir / "image")], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for page in range(1, page_count + 1):
        destination = pages_dir / (str(page).zfill(4) + ".jpg")
        direct = None if page_has_text(pdf_path, page) else select_direct_image(images, page, extracted_dir)
        if direct is not None:
            shutil.copyfile(direct, destination)
            lossless += 1
            if verbose:
                print(f"  Page {page}: preserved embedded JPEG")
        else:
            dpi = select_render_dpi(images, page, fallback_dpi)
            render_page(pdf_path, page, dpi, destination)
            rerendered += 1
            if verbose:
                print(f"  Page {page}: rendered at {dpi} DPI")
        if not destination.is_file():
            raise RuntimeError(f"No JPEG created for page {page}")
    return PageBuildResult(page_count, lossless, rerendered)


def create_cbz(output_path: Path, pages_dir: Path) -> None:
    """Create the CBZ in a temporary sibling and atomically replace output."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name("." + output_path.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in sorted(pages_dir.rglob("*"), key=lambda path: path.relative_to(pages_dir).as_posix()):
            archive.write(entry, entry.relative_to(pages_dir).as_posix())
    os.replace(temporary, output_path)


def process_pdf(input_path: Path, base_input: Path, output_dir: Path | None, overwrite: bool,
                verbose: bool, dry_run: bool, fallback_dpi: int,
                replace_source: bool = False) -> str:
    output_path = compute_output_path(
        input_path, base_input, output_dir, replace_source
    )
    effective_overwrite = overwrite or replace_source
    if output_path.exists() and not effective_overwrite:
        print(f"Skipping: {input_path} (output exists: {output_path})")
        return "skipped_exists"
    if dry_run:
        print(f"Would create: {output_path}")
        return "processed"
    try:
        with temp_dir(input_path) as work_dir:
            result = build_page_images(input_path, work_dir, fallback_dpi, verbose)
            create_cbz(output_path, work_dir / "pages")
        if replace_source:
            try:
                input_path.unlink()
            except OSError as error:
                print(
                    f"Error: {input_path}: remove source failed: {error}; "
                    "converted output was kept; source was retained",
                    file=sys.stderr,
                )
                return "error_remove_source"
        print(
            f"Created: {output_path} ({result.total} pages: "
            f"{result.lossless} lossless, {result.rerendered} re-rendered)"
        )
        return "processed"
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Error: {input_path}: {error}", file=sys.stderr)
        return "error"


def main() -> int:
    args = parse_args()
    if args.fallback_dpi <= 0:
        print("Error: --fallback-dpi must be greater than zero", file=sys.stderr)
        return EXIT_DEPENDENCY_ERROR
    check_dependencies()
    try:
        pdf_files = find_pdf_files(args.input, args.recursive)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_DEPENDENCY_ERROR
    if not pdf_files:
        print("No PDF files found.", file=sys.stderr)
        return EXIT_NO_FILES
    base_input = args.input if args.input.is_dir() else args.input.parent
    replace_source = getattr(args, "replace_source", False)
    effective_overwrite = args.overwrite or replace_source
    collisions = (
        find_output_path_collisions(
            pdf_files, base_input, args.output_dir, replace_source
        )
        if replace_source
        else set()
    )
    failed = False
    for pdf in pdf_files:
        if pdf in collisions:
            print(f"Skipping: {pdf} (output path collides with another input)")
            continue
        status = process_pdf(
            pdf,
            base_input,
            args.output_dir,
            effective_overwrite,
            args.verbose,
            args.dry_run,
            args.fallback_dpi,
            replace_source,
        )
        if status in {"error", "error_remove_source"}:
            failed = True
    return EXIT_CONVERSION_ERROR if failed else 0


if __name__ == "__main__":
    sys.exit(main())
