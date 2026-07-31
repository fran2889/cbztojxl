# Additive Verbose Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `cbztojxl.py` print compact, path-aware archive results in every mode while verbose mode adds details and extraction occurs under the output tree.

**Architecture:** Introduce small display and subprocess-diagnostic helpers, then make `process_archive()` the single owner of per-archive output. Keep `main()` responsible only for aggregation and the final `[total]` line. Preserve existing status return values and exit codes.

**Tech Stack:** Python standard library, `unittest`, `unittest.mock`, external archive tools mocked in unit tests.

## Global Constraints

- Use ASCII statuses, `=>` arrows, and `|` major-field separators.
- Use `page`/`pages`, never `image`/`images`, in user-visible conversion output.
- Show archive paths relative to their input/output roots and page paths relative to the archive root.
- Create and display temporary extraction directories relative to the output root.
- Verbose output is additive except that per-page messages replace the transient progress bar.
- Error details are identical in regular and verbose modes; never print executed command lines.
- Print no blank lines between archive results and exactly one blank line before `[total]`.
- Do not modify the unrelated working-tree change in `pdftocbz.py`.

---

### Task 1: Path-aware output and output-root temporary directories

**Files:**
- Modify: `cbztojxl.py:329-469`
- Test: `tests/test_cbztojxl.py`

**Interfaces:**
- Produces: `display_input_path(input_path: Path, base_input: Path) -> str`
- Produces: `display_output_path(output_path: Path, output_root: Path) -> str`
- Changes: `temp_dir(parent_dir: Path) -> Iterator[Path]`
- Changes: `report_processed(source_display: str, target_display: str, input_size: int, output_size: int, page_count: int, max_line_len: int = 0) -> None`

- [ ] **Step 1: Add failing path, temporary-directory, result, and progress tests**

```python
def test_display_paths_preserve_nested_relative_paths(self):
    self.assertEqual(
        cbztojxl.display_input_path(Path("/in/series/volume.cbz"), Path("/in")),
        "series/volume.cbz",
    )
    self.assertEqual(
        cbztojxl.display_output_path(Path("/out/series/volume.cbz"), Path("/out")),
        "series/volume.cbz",
    )

def test_temp_dir_is_created_under_requested_output_parent(self):
    with tempfile.TemporaryDirectory() as directory:
        parent = Path(directory) / "series"
        with cbztojxl.temp_dir(parent) as temporary:
            self.assertEqual(temporary.parent, parent.resolve())
            self.assertTrue(temporary.exists())
        self.assertFalse(temporary.exists())

def test_report_processed_uses_compact_ascii_format(self):
    with patch("sys.stdout", new_callable=io.StringIO) as stdout:
        cbztojxl.report_processed("series/in.cbz", "series/out.cbz", 100, 75, 24)
    self.assertEqual(
        stdout.getvalue().strip(),
        "[done]  series/in.cbz => series/out.cbz | 24 pages | 100 B => 75 B (25.0% smaller)",
    )

def test_progress_uses_relative_path_without_processing_prefix(self):
    callback, _ = cbztojxl.create_progress_callback("series/in.cbz", 1, 2, 4)
    with patch("sys.stdout", new_callable=io.StringIO) as stdout:
        callback(2)
    self.assertIn("series/in.cbz [1/2]", stdout.getvalue())
    self.assertNotIn("Processing:", stdout.getvalue())
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python3 -m unittest tests.test_cbztojxl -v`

Expected: failures for missing display helpers, the old `temp_dir()` parent choice, legacy `Processing:`/`images` wording, and the old `report_processed()` signature.

- [ ] **Step 3: Implement the display helpers and compact success/progress formatting**

```python
def display_input_path(input_path: Path, base_input: Path) -> str:
    base = base_input.parent if base_input.is_file() else base_input
    try:
        return str(input_path.resolve().relative_to(base.resolve()))
    except ValueError:
        return input_path.name


def display_output_path(output_path: Path, output_root: Path) -> str:
    try:
        return str(output_path.resolve().relative_to(output_root.resolve()))
    except ValueError:
        return output_path.name


@contextmanager
def temp_dir(parent_dir: Path) -> Iterator[Path]:
    parent_dir = parent_dir.resolve()
    parent_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".cbztojxl_tmp_", dir=parent_dir))
    try:
        yield temporary
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def report_processed(source_display, target_display, input_size, output_size,
                     page_count, max_line_len=0):
    page_label = "page" if page_count == 1 else "pages"
    message = (
        f"[done]  {source_display} => {target_display} | "
        f"{page_count} {page_label} | "
        f"{format_size_reduction(input_size, output_size).replace(' -> ', ' => ')}"
    ).replace(")", " smaller)")
    print(f"\r{message.ljust(max_line_len)}" if max_line_len else message)
```

Update `format_size_reduction()` directly to emit `=>` and `(N% smaller)` rather than relying on string replacement if that keeps the implementation clearer. Remove `Processing:` from `create_progress_callback()` and size its clearing buffer from the new `[done]` format.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `python3 -m unittest tests.test_cbztojxl -v`

Expected: all `tests.test_cbztojxl` tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add cbztojxl.py tests/test_cbztojxl.py
git commit -m "refactor: add compact path-aware conversion output"
```

### Task 2: Additive verbose output, skips, and detailed stage errors

**Files:**
- Modify: `cbztojxl.py:309-614`
- Test: `tests/test_cbztojxl.py`

**Interfaces:**
- Produces: `command_diagnostic(error: subprocess.CalledProcessError) -> str`
- Produces: `report_error(primary: str, detail: str) -> None`
- Changes: `DependencyError` carries the tool name, return code, and captured stderr text in its message.
- Changes: `convert_jpegs_to_jxl()` reports full archive-relative page paths in verbose mode and returns failures with their page indexes.
- Consumes: display helpers and compact reporters from Task 1.

- [ ] **Step 1: Add failing tests for verbose parity, skips, and all failure stages**

```python
def test_verbose_adds_details_but_keeps_done_line(self):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        extracted = root / "out" / "series" / ".cbztojxl_tmp_test"
        page = extracted / "chapter" / "page001.jpg"
        page.parent.mkdir(parents=True)
        page.write_bytes(b"jpeg")
        with (
            patch("subprocess.run"),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            failures = cbztojxl.convert_jpegs_to_jxl(extracted, verbose=True)
    self.assertEqual(failures, [])
    self.assertIn("Converting page 1/1: chapter/page001.jpg", stdout.getvalue())
    self.assertNotIn("image", stdout.getvalue())

def test_conversion_error_prints_full_page_path_and_stderr(self):
    error = subprocess.CalledProcessError(
        1, ["cjxl"], stderr=b"could not decode JPEG input\n"
    )
    detail = cbztojxl.command_diagnostic("cjxl", error)
    with patch("sys.stderr", new_callable=io.StringIO) as stderr:
        cbztojxl.report_error(
            "series/volume.cbz | convert page 1/1: chapter/page001.jpg failed",
            detail,
        )
    self.assertEqual(
        stderr.getvalue(),
        "[error] series/volume.cbz | convert page 1/1: "
        "chapter/page001.jpg failed\n"
        "        cjxl exited with status 1: could not decode JPEG input\n",
    )

def test_extract_error_is_detailed_in_regular_mode(self):
    with patch("sys.stderr", new_callable=io.StringIO) as stderr:
        cbztojxl.report_error(
            "series/volume.cbz | extract archive failed",
            "unzip exited with status 9: corrupt archive",
        )
    self.assertEqual(
        stderr.getvalue(),
        "[error] series/volume.cbz | extract archive failed\n"
        "        unzip exited with status 9: corrupt archive\n",
    )

def test_create_error_includes_relative_destination(self):
    with patch("sys.stderr", new_callable=io.StringIO) as stderr:
        cbztojxl.report_error(
            "series/volume.cbz => series/volume.cbz | create archive failed",
            "zip exited with status 15: could not create output file",
        )
    self.assertEqual(
        stderr.getvalue(),
        "[error] series/volume.cbz => series/volume.cbz | create archive failed\n"
        "        zip exited with status 15: could not create output file\n",
    )
```

Add a `process_archive()` integration test that mocks extraction, conversion, and
creation successfully and asserts the same `[done]` line appears with
`verbose=False` and `verbose=True`; assert only the verbose capture contains
`Extracting to:`, `Converting page`, and `Creating:`.

- [ ] **Step 2: Run the failure-output tests and verify they fail**

Run: `python3 -m unittest tests.test_cbztojxl -v`

Expected: failures because verbose still replaces normal output, subprocess stderr is suppressed, page paths use basenames, and errors use legacy prose.

- [ ] **Step 3: Capture concise subprocess diagnostics**

```python
def command_diagnostic(tool: str, error: subprocess.CalledProcessError) -> str:
    stderr = error.stderr
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    detail = (stderr or "").strip().splitlines()
    suffix = f": {detail[-1]}" if detail else ""
    return f"{tool} exited with status {error.returncode}{suffix}"
```

Use `stderr=subprocess.PIPE` in extraction and creation. Wrap failures as `DependencyError(command_diagnostic(cmd[0], error))`. Keep commands themselves out of output.

- [ ] **Step 4: Consolidate `process_archive()` output**

Compute these values once before branching:

```python
source_display = display_input_path(input_path, base_input)
output_path = compute_output_path(input_path, base_input, output_dir, overwrite)
output_root = output_dir.resolve() if output_dir else output_path.parent
target_display = display_output_path(output_path, output_root)
```

Always pass file indexes so regular result lines also print in verbose mode. Emit compact skip lines directly:

```python
print(f"[skip]  {source_display} | no JPEG pages")
print(f"[skip]  {source_display} => {target_display} | output already exists")
print(f"[skip]  {source_display} | archiver not available")
```

Create the temporary directory with `temp_dir(output_path.parent)`. Log it via `display_output_path(temp_path, output_root)`. Remove `Converting JPEGs to JXL`. Make per-page verbose messages use `filepath.relative_to(temp_path)`. Format stage failures exactly as the approved spec, with the diagnostic on an eight-space-indented second line. Keep errors on stderr in both modes.

- [ ] **Step 5: Run focused tests and verify they pass**

Run: `python3 -m unittest tests.test_cbztojxl -v`

Expected: all output, skip, error, path, and cleanup tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add cbztojxl.py tests/test_cbztojxl.py
git commit -m "feat: make verbose conversion output additive"
```

### Task 3: Consolidate CLI totals and documentation

**Files:**
- Modify: `cbztojxl.py:644-713`
- Modify: `README.md`
- Test: `tests/test_cbztojxl.py`

**Interfaces:**
- Consumes: existing `(input_size, output_size, status)` process result.
- Produces: one `[total]` line for every nonempty run, including success, skip, and failure counts without page totals.
- Produces: `format_total(archive_count: int, successful_count: int, skipped_count: int, failed_count: int, input_size: int, output_size: int) -> str`

- [ ] **Step 1: Add failing CLI aggregation tests**

```python
def test_total_is_mode_independent_and_omits_pages(self):
    expected = (
        "[total] 4 archives | 2 done, 1 skipped, 1 failed | "
        "150 B => 115 B (23.3% smaller)"
    )
    actual = cbztojxl.format_total(4, 2, 1, 1, 150, 115)
    self.assertEqual(actual, expected)
    self.assertNotIn("pages", actual)
```

Add a `main()` integration test with `process_archive.side_effect` set to
`[(100, 75, "processed"), (50, 40, "processed"),
(20, 0, "skipped_exists"), (30, 0, "error_convert")]`. Invoke it once with
verbose false and once with verbose true. In both captures, assert the expected
line above is present, `Failed to process` is absent, and `SystemExit.code`
equals `EXIT_CONVERSION_ERROR`.

- [ ] **Step 2: Run the aggregation test and verify it fails**

Run: `python3 -m unittest tests.test_cbztojxl -v`

Expected: failure because totals are mode-dependent, lack archive counts, and errors produce a duplicated failure list.

- [ ] **Step 3: Implement the unified total line**

Remove `show_summary`, always provide `file_index` and `total_files`, and retain `show_progress_bar = not args.verbose and not args.dry_run`. Track `failed_count` rather than archive paths. Print:

```python
def format_total(archive_count, successful_count, skipped_count, failed_count,
                 input_size, output_size):
    counts = (
        f"{successful_count} done, {skipped_count} skipped, "
        f"{failed_count} failed"
    )
    total = f"[total] {archive_count} archives | {counts}"
    if input_size:
        total += f" | {format_size_reduction(input_size, output_size)}"
    return total


print(f"\n{format_total(len(archive_files), successful_count, skipped_count, failed_count, total_input_size, total_output_size)}")
```

Delete the filename-only failure report and the verbose-only `Processed ...` footer. Exit with `EXIT_CONVERSION_ERROR` when `failed_count` is nonzero, otherwise exit zero.

- [ ] **Step 4: Update README output documentation**

Document that verbose mode adds extraction, per-page, and creation details while retaining standard result and total lines; temporary extraction occurs under the destination tree; errors are always detailed. Include one `[done]` and one `[total]` example using the approved ASCII format.

- [ ] **Step 5: Run focused and full tests**

Run: `python3 -m unittest tests.test_cbztojxl -v`

Expected: all cbztojxl tests pass.

Run: `python3 -m unittest discover -s tests -v`

Expected: the complete test suite passes.

- [ ] **Step 6: Run static verification**

Run: `python3 -m py_compile cbztojxl.py`

Expected: exit status 0 with no output.

Run: `git diff --check`

Expected: exit status 0 with no output.

- [ ] **Step 7: Commit Task 3**

```bash
git add cbztojxl.py tests/test_cbztojxl.py README.md
git commit -m "docs: describe consolidated conversion output"
```
