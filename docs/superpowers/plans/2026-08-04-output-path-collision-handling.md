# Output-path collision handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip every input that maps to a shared output path before archive processing, and prevent recursive discovery from entering a nested output tree.

**Architecture:** Extend discovery with an optional lexical output-tree exclusion. Add a small preflight helper that groups `compute_output_path()` results, then have `main()` report and count collision-group members as skips while passing only unique destinations to the unchanged archive-processing pipeline.

**Tech Stack:** Python 3.10+, standard library `pathlib`, `unittest`, and `unittest.mock`.

## Global Constraints

- Preserve lexical POSIX-relative archive ordering.
- Do not modify source archives or create outputs for collision-group inputs, including under `--dry-run` and `--overwrite`.
- Retain existing exit codes, result-line format, and total-line accounting.
- Keep output-path validation and in-place replacement safeguards unchanged.
- Use ASCII-only documentation prose.

---

### Task 1: Exclude a nested output tree during recursive discovery

**Files:**

- Modify: `cbztojxl.py:214-250`
- Test: `tests/test_cbztojxl.py:388-404`

**Interfaces:**

- Consumes: `find_archive_files(input_path: Path, recursive: bool)` and optional `output_dir: Path | None`.
- Produces: `find_archive_files(input_path: Path, recursive: bool, output_dir: Path | None = None) -> list[Path]`, with output-tree descendants omitted only for recursive directory discovery.

- [ ] **Step 1: Write the failing test**

```python
def test_recursive_discovery_excludes_nested_output_tree(self):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "source.cbz").touch()
        output = root / "output"
        output.mkdir()
        (output / "previous.cbz").touch()

        discovered = cbztojxl.find_archive_files(root, recursive=True, output_dir=output)

    self.assertEqual(discovered, [root / "source.cbz"])
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python3 -m unittest tests.test_cbztojxl.CbzToJxlDiscoveryAndPathSafetyTests.test_recursive_discovery_excludes_nested_output_tree -v`

Expected: FAIL because `find_archive_files()` does not accept `output_dir`.

- [ ] **Step 3: Write the minimal implementation**

```python
def find_archive_files(
    input_path: Path, recursive: bool, output_dir: Path | None = None
) -> list[Path]:
    # Existing input validation remains unchanged.
    excluded_output = lexical_absolute(output_dir) if output_dir else None
    # While filtering recursive directory candidates, retain a file unless it
    # is inside excluded_output, which is itself inside input_path.
```

Use `Path.relative_to()` to determine lexical containment. Keep the existing
relative-POSIX sort key.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `python3 -m unittest tests.test_cbztojxl.CbzToJxlDiscoveryAndPathSafetyTests.test_recursive_discovery_excludes_nested_output_tree -v`

Expected: PASS.

### Task 2: Preflight and skip output-path collision groups

**Files:**

- Modify: `cbztojxl.py:650-695,1010-1065`
- Test: `tests/test_cbztojxl.py:1570-1650`

**Interfaces:**

- Consumes: `archive_files: list[Path]`, `base_input: Path`, `output_dir: Path | None`, and `overwrite: bool`.
- Produces: `find_output_path_collisions(...) -> set[Path]`, containing all inputs whose computed output destination is shared by multiple inputs.

- [ ] **Step 1: Write the failing test**

```python
def test_main_skips_every_output_path_collision_before_processing(self):
    first = Path("library/book.cbz")
    second = Path("library/book.cbr")
    distinct = Path("library/other.cbz")
    args = Namespace(
        input=Path("library"), output_dir=Path("out"), recursive=True,
        overwrite=True, verbose=False, dry_run=False,
    )
    with (
        patch.object(cbztojxl, "parse_args", return_value=args),
        patch.object(cbztojxl, "check_dependencies"),
        patch.object(cbztojxl, "find_archive_files", return_value=[first, second, distinct]),
        patch.object(cbztojxl, "process_archive", return_value=(10, 5, "processed")) as process,
        patch("sys.stdout", new_callable=io.StringIO) as stdout,
        self.assertRaises(SystemExit) as raised,
    ):
        cbztojxl.main()

    self.assertEqual(raised.exception.code, 0)
    self.assertEqual(process.call_args_list[0].kwargs["input_path"], distinct)
    self.assertEqual(process.call_count, 1)
    self.assertIn("[skip]  book.cbz => book.cbz | output path collides with another input", stdout.getvalue())
    self.assertIn("[skip]  book.cbr => book.cbz | output path collides with another input", stdout.getvalue())
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python3 -m unittest tests.test_cbztojxl.CbzToJxlMainOutputTests.test_main_skips_every_output_path_collision_before_processing -v`

Expected: FAIL because both colliding inputs currently reach `process_archive()`.

- [ ] **Step 3: Write the minimal implementation**

```python
def find_output_path_collisions(
    archive_files: list[Path],
    base_input: Path,
    output_dir: Path | None,
    overwrite: bool,
) -> set[Path]:
    destinations: dict[Path, list[Path]] = {}
    for archive_file in archive_files:
        output_path = compute_output_path(
            archive_file, base_input, output_dir, overwrite
        )
        destinations.setdefault(output_path, []).append(archive_file)
    return {
        archive_file
        for matching_inputs in destinations.values()
        if len(matching_inputs) > 1
        for archive_file in matching_inputs
    }
```

In `main()`, pass `output_dir` to discovery, calculate collisions immediately
after discovery, and, during the ordered loop, print each collision skip using
the normal source and destination displays. Increment `skipped_count` and do
not call `process_archive()` for that input.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `python3 -m unittest tests.test_cbztojxl.CbzToJxlMainOutputTests.test_main_skips_every_output_path_collision_before_processing -v`

Expected: PASS.

### Task 3: Document the grouped-skip behavior and run regression checks

**Files:**

- Modify: `README.md:68-73`
- Test: `tests/test_cbztojxl.py`

**Interfaces:**

- Consumes: the completed preflight behavior.
- Produces: README output behavior wording that states inputs targeting the same destination are all skipped.

- [ ] **Step 1: Write the documentation assertion as a focused test extension**

Extend the Task 2 test to assert that collision members add to the final
`[total]` skipped count and that the distinct input remains processed.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python3 -m unittest tests.test_cbztojxl.CbzToJxlMainOutputTests.test_main_skips_every_output_path_collision_before_processing -v`

Expected: FAIL until the collision path is included in normal total accounting.

- [ ] **Step 3: Update README output behavior**

Add this bullet under `## Output Behavior`:

```markdown
- **Output-path collisions:** If multiple inputs map to the same output CBZ path, every input in that collision group is skipped before processing.
```

- [ ] **Step 4: Run focused and full verification**

Run: `python3 -m unittest tests.test_cbztojxl -v && python3 -m unittest discover -v`

Expected: both commands exit 0 with all tests passing.
