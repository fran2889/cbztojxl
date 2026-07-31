# `cbaudit` Page-Size Metric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `--page-size [KB]` check that flags comic archives whose sampled JPEG pages average below a configurable size threshold.

**Architecture:** Keep the existing single-file application structure. Parse the optional threshold into `int | None`, gather raw byte sizes from the already selected extracted JPEGs, and extend report classification with an independent `SMALL PAGES` state. Unit tests load `cbaudit.py` directly and isolate CLI, reporting, and archive-processing behavior with standard-library mocks and temporary files.

**Tech Stack:** Python 3, `argparse`, `pathlib`, `unittest`, `unittest.mock`

## Global Constraints

- The page-size metric is disabled when `--page-size` is omitted.
- Bare `--page-size` uses exactly 100 KB; an explicit value must be a positive integer.
- One KB means exactly 1,024 bytes.
- Use the same selected JPEGs as the quality scan: five evenly spaced by default and all JPEGs under `--full-scan`.
- Compare the unrounded arithmetic mean in bytes; a mean strictly below the threshold fails and equality passes.
- Display averages rounded to the nearest whole KB.
- Corrupt selected files remain in the size calculation.
- Status order is `UNREADABLE + LOW QUALITY + SMALL PAGES`.
- Existing behavior and output remain unchanged when the option is omitted.
- Do not add third-party dependencies or inspect non-JPEG images.

---

## File Structure

- Modify `cbaudit.py`: add CLI validation, page-size collection, classification, reporting, and main-loop wiring.
- Create `tests/test_cbaudit.py`: cover argument parsing, report boundaries/output, selected-page reuse, full scans, metadata failures, and main exit behavior.

No new production module is warranted: this feature is a small extension of the existing archive-processing and reporting pipeline.

### Task 1: Parse the Optional Page-Size Threshold

**Files:**
- Modify: `cbaudit.py:183-229`
- Create: `tests/test_cbaudit.py`

**Interfaces:**
- Consumes: `argparse.ArgumentTypeError`, the existing `parse_args()` function, and `sys.argv`.
- Produces: `positive_int(value: str) -> int`; `parse_args()` returns `args.page_size: int | None`, where `None` disables the check, `100` is the bare-option default, and an explicit positive integer is preserved.

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cbaudit.py` with:

```python
import importlib.util
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "cbaudit.py"
SPEC = importlib.util.spec_from_file_location("cbaudit", MODULE_PATH)
cbaudit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cbaudit)


class CbAuditArgumentTests(unittest.TestCase):
    def parse(self, *arguments):
        with patch("sys.argv", ["cbaudit.py", *arguments]):
            return cbaudit.parse_args()

    def test_page_size_is_disabled_when_omitted(self):
        self.assertIsNone(self.parse("comic.cbz").page_size)

    def test_bare_page_size_uses_100_kb_default(self):
        self.assertEqual(self.parse("comic.cbz", "--page-size").page_size, 100)

    def test_page_size_accepts_custom_positive_threshold(self):
        self.assertEqual(self.parse("comic.cbz", "--page-size", "150").page_size, 150)

    def test_page_size_rejects_zero_negative_and_non_numeric_values(self):
        for value in ("0", "-1", "abc"):
            with self.subTest(value=value), self.assertRaises(SystemExit) as raised:
                with redirect_stderr(StringIO()):
                    self.parse("comic.cbz", "--page-size", value)
            self.assertEqual(raised.exception.code, 2)
```

- [ ] **Step 2: Run the CLI tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_cbaudit.CbAuditArgumentTests -v
```

Expected: failures/errors because `Namespace` has no `page_size` and `--page-size` is unrecognized.

- [ ] **Step 3: Add positive-integer validation and the optional-value argument**

Add immediately before `parse_args()` in `cbaudit.py`:

```python
def positive_int(value: str) -> int:
    """Parse a strictly positive command-line integer."""
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed
```

Add after the existing `--threshold` argument:

```python
    parser.add_argument(
        "--page-size",
        nargs="?",
        type=positive_int,
        const=100,
        default=None,
        metavar="KB",
        help="Flag archives averaging below KB per page (default when enabled: 100)",
    )
```

- [ ] **Step 4: Run the CLI tests and the existing suite**

Run:

```bash
python3 -m unittest tests.test_cbaudit.CbAuditArgumentTests -v
python3 -m unittest discover -s tests -v
```

Expected: all argument tests pass; the complete existing suite passes.

- [ ] **Step 5: Commit the CLI slice**

```bash
git add cbaudit.py tests/test_cbaudit.py
git commit -m "feat: add cbaudit page-size option"
```

### Task 2: Classify and Report Small Average Pages

**Files:**
- Modify: `cbaudit.py:342-395`
- Modify: `tests/test_cbaudit.py`

**Interfaces:**
- Consumes: `page_sizes: list[int] | None` containing selected files' raw byte sizes and `page_size_threshold: int | None` in KB.
- Produces: `print_archive_report(..., threshold: int, verbose: bool, page_sizes: list[int] | None = None, page_size_threshold: int | None = None) -> bool`; returns `True` for a page-size-only failure and prints the new state only when enabled.

- [ ] **Step 1: Write failing reporting tests**

Append to `tests/test_cbaudit.py`:

```python
class CbAuditReportTests(unittest.TestCase):
    def report(self, *, page_sizes=None, page_size_threshold=None, verbose=False,
               corrupted_count=0, qualities=None):
        output = StringIO()
        with redirect_stdout(output):
            has_issues = cbaudit.print_archive_report(
                "comic.cbz",
                total_images=5,
                sampled_count=5,
                corrupted_count=corrupted_count,
                qualities=[80] * 5 if qualities is None else qualities,
                corrupted_paths=[Path("broken.jpg")] if corrupted_count else [],
                threshold=70,
                verbose=verbose,
                page_sizes=page_sizes,
                page_size_threshold=page_size_threshold,
            )
        return has_issues, output.getvalue()

    def test_disabled_page_size_preserves_compact_ok_output(self):
        has_issues, output = self.report()
        self.assertFalse(has_issues)
        self.assertEqual(output, "")

    def test_average_below_threshold_reports_small_pages(self):
        has_issues, output = self.report(
            page_sizes=[80 * 1024] * 5,
            page_size_threshold=100,
        )
        self.assertTrue(has_issues)
        self.assertEqual(output, "comic.cbz: SMALL PAGES (avg page=80 KB)\n")

    def test_average_equal_to_threshold_passes(self):
        has_issues, output = self.report(
            page_sizes=[100 * 1024] * 5,
            page_size_threshold=100,
        )
        self.assertFalse(has_issues)
        self.assertEqual(output, "")

    def test_unrounded_bytes_control_classification(self):
        has_issues, output = self.report(
            page_sizes=[100 * 1024 - 1],
            page_size_threshold=100,
        )
        self.assertTrue(has_issues)
        self.assertIn("avg page=100 KB", output)

    def test_verbose_output_shows_enabled_metric_even_when_it_passes(self):
        has_issues, output = self.report(
            page_sizes=[184 * 1024] * 5,
            page_size_threshold=100,
            verbose=True,
        )
        self.assertFalse(has_issues)
        self.assertIn("Average page size: 184 KB (threshold: 100 KB)", output)

    def test_statuses_and_details_have_fixed_order(self):
        has_issues, output = self.report(
            page_sizes=[82 * 1024] * 5,
            page_size_threshold=100,
            corrupted_count=1,
            qualities=[65] * 5,
        )
        self.assertTrue(has_issues)
        self.assertEqual(
            output,
            "comic.cbz: UNREADABLE + LOW QUALITY + SMALL PAGES "
            "(1 corrupted, avg=65, avg page=82 KB)\n",
        )
```

- [ ] **Step 2: Run the reporting tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_cbaudit.CbAuditReportTests -v
```

Expected: errors stating that `print_archive_report()` does not accept `page_sizes`.

- [ ] **Step 3: Extend report calculation and status composition**

Replace `print_archive_report()` in `cbaudit.py` with:

```python
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
```

- [ ] **Step 4: Run reporting tests and the complete suite**

Run:

```bash
python3 -m unittest tests.test_cbaudit.CbAuditReportTests -v
python3 -m unittest discover -s tests -v
```

Expected: all reporting tests and the complete suite pass.

- [ ] **Step 5: Commit the reporting slice**

```bash
git add cbaudit.py tests/test_cbaudit.py
git commit -m "feat: report small average comic pages"
```

### Task 3: Wire Selected File Sizes Through Archive Processing

**Files:**
- Modify: `cbaudit.py:398-503`
- Modify: `tests/test_cbaudit.py`

**Interfaces:**
- Consumes: selected `list[Path]`, `args.page_size: int | None`, and Task 2's extended `print_archive_report()`.
- Produces: `get_file_sizes(image_paths: list[Path]) -> list[int]`; `process_archive(..., page_size_threshold: int | None = None) -> tuple[bool, int, int]`. `get_file_sizes()` deliberately propagates `OSError` so `process_archive()` can report a visible archive failure.

- [ ] **Step 1: Write failing selection, full-scan, no-JPEG, and metadata-error tests**

Append to `tests/test_cbaudit.py`:

```python
class CbAuditProcessingTests(unittest.TestCase):
    def setUp(self):
        self.format_config = cbaudit.ALL_FORMATS["zip"]

    def run_archive(self, page_count, *, full_scan=False, page_size_threshold=100):
        observed = {}

        def fake_extract(_archive, output_dir, _config):
            for index in range(page_count):
                (output_dir / f"{index:02}.jpg").write_bytes(bytes([index]) * (index + 1))

        def fake_scan(paths, on_progress=None):
            observed["scanned"] = [path.name for path in paths]
            return [False] * len(paths), [80] * len(paths), []

        def fake_sizes(paths):
            observed["sized"] = [path.name for path in paths]
            return [path.stat().st_size for path in paths]

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "comic.cbz"
            archive.touch()
            with (
                patch("cbaudit.get_format_config", return_value=self.format_config),
                patch("cbaudit.extract_archive", side_effect=fake_extract),
                patch("cbaudit.scan_images", side_effect=fake_scan),
                patch("cbaudit.get_file_sizes", side_effect=fake_sizes),
                patch("cbaudit.print_archive_report", return_value=False) as report,
            ):
                result = cbaudit.process_archive(
                    archive,
                    full_scan=full_scan,
                    threshold=70,
                    verbose=True,
                    dry_run=False,
                    page_size_threshold=page_size_threshold,
                )
        return result, observed, report

    def test_default_scan_sizes_the_same_five_pages_that_it_scans(self):
        result, observed, report = self.run_archive(10)
        self.assertEqual(observed["scanned"], ["00.jpg", "02.jpg", "04.jpg", "06.jpg", "08.jpg"])
        self.assertEqual(observed["sized"], observed["scanned"])
        self.assertEqual(report.call_args.kwargs["page_sizes"], [1, 3, 5, 7, 9])
        self.assertEqual(result, (False, 10, 5))

    def test_full_scan_sizes_every_jpeg(self):
        _, observed, report = self.run_archive(6, full_scan=True)
        self.assertEqual(observed["sized"], [f"{index:02}.jpg" for index in range(6)])
        self.assertEqual(report.call_args.kwargs["page_size_threshold"], 100)

    def test_disabled_metric_does_not_read_file_sizes(self):
        _, _, report = self.run_archive(3, page_size_threshold=None)
        self.assertEqual(report.call_args.kwargs["page_sizes"], None)

    def test_no_jpeg_archive_is_not_an_issue(self):
        result, _, report = self.run_archive(0)
        self.assertEqual(result, (False, 0, 0))
        report.assert_not_called()

    def test_metadata_read_failure_is_reported_as_archive_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "comic.cbz"
            archive.touch()

            def fake_extract(_archive, output_dir, _config):
                (output_dir / "page.jpg").touch()

            stderr = StringIO()
            with (
                patch("cbaudit.get_format_config", return_value=self.format_config),
                patch("cbaudit.extract_archive", side_effect=fake_extract),
                patch("cbaudit.scan_images", return_value=([False], [80], [])),
                patch("cbaudit.get_file_sizes", side_effect=OSError("metadata unavailable")),
                redirect_stderr(stderr),
            ):
                result = cbaudit.process_archive(
                    archive, False, 70, True, False, page_size_threshold=100
                )

        self.assertEqual(result, (True, 1, 1))
        self.assertIn("Could not read page sizes for comic.cbz", stderr.getvalue())
```

- [ ] **Step 2: Run processing tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_cbaudit.CbAuditProcessingTests -v
```

Expected: errors because `get_file_sizes()` and `page_size_threshold` do not exist.

- [ ] **Step 3: Add size collection and processing integration**

Add after `scan_images()` in `cbaudit.py`:

```python
def get_file_sizes(image_paths: list[Path]) -> list[int]:
    """Return raw sizes in bytes for the selected image files."""
    return [path.stat().st_size for path in image_paths]
```

Add the following final parameter to `process_archive()`:

```python
    page_size_threshold: int | None = None,
```

Immediately after `corrupted_count = sum(corrupted)`, add:

```python
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
```

Change the `print_archive_report()` call to use keywords for the new inputs while preserving all existing values:

```python
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
```

- [ ] **Step 4: Run processing tests and the complete suite**

Run:

```bash
python3 -m unittest tests.test_cbaudit.CbAuditProcessingTests -v
python3 -m unittest discover -s tests -v
```

Expected: all processing tests and the complete suite pass.

- [ ] **Step 5: Commit archive-processing integration**

```bash
git add cbaudit.py tests/test_cbaudit.py
git commit -m "feat: measure selected cbaudit page sizes"
```

### Task 4: Propagate the Option Through `main()` and Document It

**Files:**
- Modify: `cbaudit.py:466-525`
- Modify: `README.md`
- Modify: `tests/test_cbaudit.py`

**Interfaces:**
- Consumes: `args.page_size` from Task 1 and `process_archive(..., page_size_threshold=...)` from Task 3.
- Produces: end-to-end CLI propagation, issue counting/exit behavior, and user-facing README documentation.

- [ ] **Step 1: Write failing main-loop tests**

Append to `tests/test_cbaudit.py`:

```python
class CbAuditMainTests(unittest.TestCase):
    def test_main_passes_page_size_threshold_and_exits_one_for_issue(self):
        arguments = type("Arguments", (), {
            "input": Path("comic.cbz"),
            "full_scan": False,
            "threshold": 70,
            "page_size": 125,
            "recursive": False,
            "verbose": False,
            "dry_run": False,
        })()
        archive = Path("comic.cbz")

        with (
            patch("cbaudit.parse_args", return_value=arguments),
            patch("cbaudit.check_dependencies"),
            patch("cbaudit.find_archive_files", return_value=[archive]),
            patch("cbaudit.process_archive", return_value=(True, 5, 5)) as process,
            redirect_stdout(StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            cbaudit.main()

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(process.call_args.kwargs["page_size_threshold"], 125)

    def test_main_keeps_page_size_disabled_when_option_is_omitted(self):
        arguments = type("Arguments", (), {
            "input": Path("comic.cbz"),
            "full_scan": False,
            "threshold": 70,
            "page_size": None,
            "recursive": False,
            "verbose": False,
            "dry_run": False,
        })()

        with (
            patch("cbaudit.parse_args", return_value=arguments),
            patch("cbaudit.check_dependencies"),
            patch("cbaudit.find_archive_files", return_value=[Path("comic.cbz")]),
            patch("cbaudit.process_archive", return_value=(False, 5, 5)) as process,
            redirect_stdout(StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            cbaudit.main()

        self.assertEqual(raised.exception.code, 0)
        self.assertIsNone(process.call_args.kwargs["page_size_threshold"])
```

- [ ] **Step 2: Run main-loop tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_cbaudit.CbAuditMainTests -v
```

Expected: errors because `main()` does not pass `page_size_threshold`.

- [ ] **Step 3: Pass the parsed threshold into archive processing**

Add this keyword argument to the `process_archive()` call in `main()`:

```python
            page_size_threshold=args.page_size,
```

- [ ] **Step 4: Document the new audit option**

Add a `cbaudit` section to `README.md` after the PDF-to-CBZ section:

```markdown
## Comic archive auditing

`cbaudit.py` checks sampled JPEG pages for corruption and inferred JPEG encoding quality. Use `--full-scan` to inspect every JPEG instead of five evenly spaced pages.

An optional page-size metric flags archives whose selected JPEG pages have a small average raw file size:

```bash
# Use the default 100 KB average threshold
python3 cbaudit.py comic.cbz --page-size

# Use a custom 150 KB average threshold
python3 cbaudit.py comic.cbz --page-size 150
```

Page-size checking is disabled unless `--page-size` is supplied. Sizes are measured after extraction, use 1 KB = 1,024 bytes, and complement rather than replace the JPEG-quality check.
```

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
python3 -m unittest tests.test_cbaudit.CbAuditMainTests -v
python3 -m unittest discover -s tests -v
python3 -m py_compile cbaudit.py
python3 cbaudit.py --help
git diff --check
```

Expected: all tests pass; compilation succeeds; help lists `--page-size [KB]`; `git diff --check` prints nothing.

- [ ] **Step 6: Commit the completed feature**

```bash
git add cbaudit.py tests/test_cbaudit.py README.md
git commit -m "docs: explain cbaudit page-size checks"
```

## Final Verification

- [ ] Run the full test suite: `python3 -m unittest discover -s tests -v` — expected: all tests pass.
- [ ] Compile every Python entry point: `python3 -m py_compile cbaudit.py cbztojxl.py pdftocbz.py` — expected: no output and exit code 0.
- [ ] Inspect help: `python3 cbaudit.py --help` — expected: `--page-size [KB]` describes the 100 KB enabled default.
- [ ] Check formatting: `git diff --check HEAD~4..HEAD` — expected: no output.
- [ ] Confirm the worktree: `git status --short` — expected: no uncommitted files from this implementation.

