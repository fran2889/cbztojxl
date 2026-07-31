# CBZ to JXL Dry-Run Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `cbztojxl.py --dry-run` follow normal processing decisions and final reporting while performing no writes and using the input size as the output size.

**Architecture:** Keep the shared archive inspection, output-path calculation, and existing-output decision in `process_archive`. Place one dry-run return immediately before temporary-directory creation, using a small reporting helper shared with the normal success path so final output cannot drift.

**Tech Stack:** Python standard library, `unittest`, `unittest.mock`

## Global Constraints

- Dry-run performs no filesystem writes, extraction, conversion, deletion, or archive creation.
- Dry-run applies the same existing-output and overwrite decisions as a normal run.
- Dry-run uses the input byte count as its output byte count and reports a 0.0% reduction.
- Dry-run final success details and skip messages match normal output; it emits no live per-image conversion progress.
- Preserve the unrelated existing modification to `pdftocbz.py`.

---

## File Structure

- Create `tests/test_cbztojxl.py`: focused regression tests for dry-run decisions, output, and mutation suppression.
- Modify `cbztojxl.py`: reorder the existing-output check, replace the compression estimate, and share final success reporting between dry and normal processing.

### Task 1: Share Success Reporting and Gate Mutations

**Files:**
- Create: `tests/test_cbztojxl.py`
- Modify: `cbztojxl.py:450-598`

**Interfaces:**
- Consumes: `process_archive(input_path: Path, base_input: Path, output_dir: Path | None, overwrite: bool, verbose: bool, dry_run: bool, file_index: int | None = None, total_files: int | None = None, show_progress_bar: bool = False) -> tuple[int, int, str]`
- Produces: `report_processed(input_path: Path, output_path: Path, input_size: int, output_size: int, jpeg_count: int, verbose: bool, file_index: int | None, total_files: int | None, target_display: str, max_line_len: int = 0) -> None`

- [ ] **Step 1: Write failing dry-run regression tests**

Create `tests/test_cbztojxl.py` with tests that load the script consistently with the existing suite, create a real source archive placeholder, and patch read-only inspection:

```python
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "cbztojxl.py"
SPEC = importlib.util.spec_from_file_location("cbztojxl", MODULE_PATH)
cbztojxl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cbztojxl)


class CbzToJxlDryRunTests(unittest.TestCase):
    def setUp(self):
        self.format_config = cbztojxl.ALL_FORMATS["zip"]

    def run_dry(self, root, *, overwrite=False, verbose=False):
        source = root / "comic.cbz"
        source.write_bytes(b"archive-data")
        output = root / "comic_jxl.cbz"

        with (
            patch.object(cbztojxl, "get_format_config", return_value=self.format_config),
            patch.object(cbztojxl, "count_jpegs_in_archive", return_value=3),
            patch.object(cbztojxl, "temp_dir") as temporary,
            patch.object(cbztojxl, "extract_archive") as extract,
            patch.object(cbztojxl, "convert_jpegs_to_jxl") as convert,
            patch.object(cbztojxl, "create_cbz") as create,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            result = cbztojxl.process_archive(
                source, source, None, overwrite, verbose, True,
                file_index=None if verbose else 1,
                total_files=None if verbose else 1,
            )

        return source, output, result, stdout.getvalue(), temporary, extract, convert, create

    def test_dry_run_uses_input_size_and_never_enters_mutation_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output, result, stdout, temporary, extract, convert, create = \
                self.run_dry(Path(directory))

        self.assertEqual(result, (len(b"archive-data"), len(b"archive-data"), "processed"))
        self.assertEqual(
            stdout.strip(),
            "Processing: comic.cbz => comic_jxl.cbz - Done! "
            "(3 images, 12 B -> 12 B (0.0%))",
        )
        self.assertFalse(output.exists())
        temporary.assert_not_called()
        extract.assert_not_called()
        convert.assert_not_called()
        create.assert_not_called()

    def test_dry_run_skips_existing_output_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "comic_jxl.cbz").write_bytes(b"existing")
            _, _, result, stdout, temporary, _, _, _ = self.run_dry(root)

        self.assertEqual(result, (len(b"archive-data"), 0, "skipped_exists"))
        self.assertEqual(stdout.strip(), "Processing: comic.cbz - Skipped (output exists)")
        temporary.assert_not_called()

    def test_dry_run_verbose_success_matches_normal_success_details(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, result, stdout, _, _, _, _ = self.run_dry(
                Path(directory), overwrite=True, verbose=True
            )

        self.assertEqual(result[2], "processed")
        self.assertIn("Processing:", stdout)
        self.assertIn("Done! 3 images, 12 B -> 12 B (0.0%)", stdout)
        self.assertNotIn("Would create", stdout)
```

- [ ] **Step 2: Run the tests and verify the intended failures**

Run:

```bash
python3 -m unittest tests.test_cbztojxl -v
```

Expected: the existing-output test reports `processed` instead of `skipped_exists`, the size test returns an estimated size instead of 12 bytes, and verbose output contains `Would create` rather than the normal success details.

- [ ] **Step 3: Implement shared final reporting and move the dry-run gate**

Add this helper before `process_archive`:

```python
def report_processed(
    input_path: Path,
    output_path: Path,
    input_size: int,
    output_size: int,
    jpeg_count: int,
    verbose: bool,
    file_index: int | None,
    total_files: int | None,
    target_display: str,
    max_line_len: int = 0,
) -> None:
    size_info = format_size_reduction(input_size, output_size)
    if verbose:
        print(f"  Done! {jpeg_count} images, {size_info}")
    elif file_index is not None and total_files is not None:
        done_msg = (
            f"Processing: {input_path.name} => {target_display} - Done! "
            f"({jpeg_count} images, {size_info})"
        )
        print(f"\r{done_msg.ljust(max_line_len)}" if max_line_len > 0 else done_msg)
```

In `process_archive`, move the existing-output block above the dry-run block. Replace the dry-run estimate and special output with:

```python
    if dry_run:
        output_size = input_size
        report_processed(
            input_path, output_path, input_size, output_size, image_count,
            verbose, file_index, total_files, target_display,
        )
        return input_size, output_size, "processed"
```

After normal archive creation and `output_path.stat()`, replace the duplicated verbose/non-verbose success output with:

```python
        report_processed(
            input_path, output_path, input_size, output_size, jpeg_count,
            verbose, file_index, total_files, target_display, max_line_len,
        )
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_cbztojxl -v
```

Expected: all three tests pass.

- [ ] **Step 5: Run the full regression suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass without errors or failures.

- [ ] **Step 6: Check syntax and the final diff**

Run:

```bash
python3 -m py_compile cbztojxl.py tests/test_cbztojxl.py
git diff --check
git diff -- cbztojxl.py tests/test_cbztojxl.py README.md
```

Expected: compilation succeeds, `git diff --check` emits no output, and the diff contains only the scoped dry-run behavior and tests. No README change is required because the documented dry-run promise remains accurate.

- [ ] **Step 7: Commit the implementation**

```bash
git add cbztojxl.py tests/test_cbztojxl.py
git commit -m "refactor: simplify cbztojxl dry-run"
```
