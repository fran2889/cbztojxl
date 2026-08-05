# Replace-source conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit `--replace-source` mode that replaces source archives only after a successful CBZ conversion.

**Architecture:** Thread a `replace_source` boolean from parsing through output-path calculation, collision detection, and archive processing. In replacement mode, select the unsuffixed sibling CBZ destination and treat overwrite as enabled. Delete a non-CBZ source only after the staged CBZ creation and output stat succeed.

**Tech Stack:** Python 3.10+, standard-library `argparse`, `pathlib`, and `unittest`.

## Global Constraints

- Preserve Python 3.10+ compatibility and use only the standard library.
- `--replace-source` must reject an explicit output directory.
- `--replace-source` must imply overwrite, while `--overwrite` remains accepted.
- Do not delete a non-CBZ source until the staged output has been created and statted.
- Preserve existing ZIP safety checks, lexical path handling, collision skipping, dry-run non-mutation, and result-line conventions.
- Keep README and CLI help ASCII-only and do not use em dashes.

---

### Task 1: Define and propagate replacement-mode paths

**Files:**
- Modify: `cbztojxl.py:100-155`
- Modify: `cbztojxl.py:673-733`
- Modify: `cbztojxl.py:1025-1115`
- Test: `tests/test_cbztojxl.py:317-740`

**Interfaces:**
- Produces: `compute_output_path(input_path: Path, base_input: Path, output_dir: Path | None, overwrite: bool, replace_source: bool = False) -> Path`.
- Produces: `find_output_path_collisions(archive_files: list[Path], base_input: Path, output_dir: Path | None, overwrite: bool, replace_source: bool = False) -> set[Path]`.
- Consumes: `argparse.Namespace.replace_source: bool` in `main()`.

- [ ] **Step 1: Write failing parser and path tests**

Add these tests to `tests/test_cbztojxl.py` near the path-safety tests. Patch `sys.argv` for parser behavior and use `assertRaises(SystemExit)` for `ArgumentParser.error()`:

```python
def test_parse_args_rejects_replace_source_with_output_directory(self):
    with patch("sys.argv", ["cbztojxl.py", "book.cbr", "out", "--replace-source"]):
        with self.assertRaises(SystemExit) as raised:
            cbztojxl.parse_args()

    self.assertEqual(raised.exception.code, 2)

def test_replace_source_uses_unsuffixed_sibling_cbz_path(self):
    source = Path("/library/Issue.cbr")

    output = cbztojxl.compute_output_path(
        source, source, None, overwrite=False, replace_source=True
    )

    self.assertEqual(output, Path("/library/Issue.cbz"))

def test_replace_source_paths_collide_for_cbz_and_cbr_with_same_stem(self):
    first = Path("/library/Issue.cbz")
    second = Path("/library/Issue.cbr")

    collisions = cbztojxl.find_output_path_collisions(
        [first, second], Path("/library"), None,
        overwrite=False, replace_source=True,
    )

    self.assertEqual(collisions, {first, second})

def test_main_skips_replace_source_output_collision_before_processing(self):
    args = Namespace(
        input=Path("library"), output_dir=None, recursive=True,
        overwrite=False, verbose=False, dry_run=False, replace_source=True,
    )
    with (
        patch.object(cbztojxl, "parse_args", return_value=args),
        patch.object(cbztojxl, "check_dependencies"),
        patch.object(
            cbztojxl,
            "find_archive_files",
            return_value=[Path("library/book.cbz"), Path("library/book.cbr")],
        ),
        patch.object(cbztojxl, "process_archive") as process,
        patch("sys.stdout", new_callable=io.StringIO) as stdout,
        self.assertRaises(SystemExit),
    ):
        cbztojxl.main()

    self.assertEqual(process.call_count, 0)
    self.assertIn(
        "[skip]  book.cbr => book.cbz | output path collides with another input",
        stdout.getvalue(),
    )
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
python3 -m unittest tests.test_cbztojxl.CbzToJxlDiscoveryAndPathSafetyTests -v
```

Expected: FAIL because `--replace-source` is unrecognized and the new keyword argument is not accepted.

- [ ] **Step 3: Implement parsing, path selection, and collision propagation**

Add the argument:

```python
parser.add_argument(
    "--replace-source",
    action="store_true",
    default=False,
    help="Replace each source archive after successful conversion",
)
args = parser.parse_args()
if args.replace_source and args.output_dir is not None:
    parser.error("--replace-source cannot be used with output_dir")
return args
```

Extend `compute_output_path()` and place this branch immediately after lexical normalization, before the existing `output_dir is None` branch:

```python
if replace_source:
    return input_path.with_suffix(".cbz")
```

Extend `find_output_path_collisions()` with `replace_source: bool = False` and pass it through each `compute_output_path()` call. In `main()`, bind `replace_source = getattr(args, "replace_source", False)` after parsing so existing unit-test `Namespace` values remain compatible. Pass `replace_source` to collision detection and collision-display path calculation. Pass `replace_source=replace_source` to `process_archive()` in preparation for Task 2.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run:

```bash
python3 -m unittest tests.test_cbztojxl.CbzToJxlDiscoveryAndPathSafetyTests -v
```

Expected: PASS, including the new parser, unsuffixed-path, and collision tests.

- [ ] **Step 5: Commit the path contract**

```bash
git add cbztojxl.py tests/test_cbztojxl.py
git commit -m "feat(cbztojxl): add replace-source path mode"
```

### Task 2: Delete non-CBZ sources only after completed output creation

**Files:**
- Modify: `cbztojxl.py:772-1015`
- Modify: `cbztojxl.py:1025-1115`
- Test: `tests/test_cbztojxl.py:854-1015`

**Interfaces:**
- Consumes: `process_archive(..., replace_source: bool = False)` from `main()`.
- Produces: status string `error_remove_source` when a completed output cannot be followed by source deletion.
- Depends on: Task 1's `replace_source` output-path behavior.

- [ ] **Step 1: Write failing source-removal tests**

Add a helper that mocks extraction, conversion, and archive creation while writing a real destination file. Then add these tests:

```python
def test_replace_source_deletes_non_cbz_after_output_is_created(self):
    source = self.make_replace_source_archive("volume.cbr")

    result = self.run_replace_source(source)

    self.assertEqual(result[2], "processed")
    self.assertFalse(source.exists())
    self.assertTrue(source.with_suffix(".cbz").exists())

def test_replace_source_keeps_non_cbz_when_creation_fails(self):
    source = self.make_replace_source_archive("volume.cbr")

    result = self.run_replace_source(
        source, create_error=cbztojxl.DependencyError("create failed")
    )

    self.assertEqual(result[2], "error_create")
    self.assertTrue(source.exists())

def test_replace_source_keeps_source_when_deletion_fails(self):
    source = self.make_replace_source_archive("volume.cbr")

    with patch.object(Path, "unlink", side_effect=PermissionError(13, "Permission denied")):
        result = self.run_replace_source(source)

    self.assertEqual(result[2], "error_remove_source")
    self.assertTrue(source.exists())
    self.assertTrue(source.with_suffix(".cbz").exists())

def test_replace_source_dry_run_does_not_write_or_delete(self):
    source = self.make_replace_source_archive("volume.cbr")

    result = self.run_replace_source(source, dry_run=True)

    self.assertEqual(result[2], "processed")
    self.assertTrue(source.exists())
    self.assertFalse(source.with_suffix(".cbz").exists())
```

Also add a test invoking `process_archive(..., overwrite=False, replace_source=True)` when a destination CBZ already exists. Assert that it returns `processed`, proving replacement mode implies overwrite.

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
python3 -m unittest tests.test_cbztojxl.CbzToJxlStageOutputTests -v
```

Expected: FAIL because `process_archive()` does not accept `replace_source`, sources are never unlinked, and replacement mode does not yet imply overwrite.

- [ ] **Step 3: Implement guarded removal and implicit overwrite**

Extend the `process_archive()` signature with `replace_source: bool = False`. Compute the effective overwrite value before output-existence handling:

```python
effective_overwrite = overwrite or replace_source
```

Pass `replace_source` to `compute_output_path()` and use `effective_overwrite` for the existing-output skip check. After `output_path.stat()` succeeds and before `report_processed()`, remove only a distinct non-CBZ source:

```python
if replace_source and input_path.suffix.lower() != ".cbz":
    try:
        input_path.unlink()
    except OSError as error:
        report_error(
            f"{source_display} => {target_display} | remove source failed",
            filesystem_diagnostic(error),
        )
        return input_size, output_size, "error_remove_source"
```

Keep the stat before this block. Do not attempt source deletion in dry-run or any earlier failure path. In `main()`, pass `args.overwrite or replace_source` to collision detection and process calls so all planning and processing paths use implied overwrite consistently.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run:

```bash
python3 -m unittest tests.test_cbztojxl.CbzToJxlStageOutputTests -v
```

Expected: PASS, including creation failure preservation, dry-run non-mutation, deletion failure reporting, and implicit overwrite coverage.

- [ ] **Step 5: Commit the safe source-removal behavior**

```bash
git add cbztojxl.py tests/test_cbztojxl.py
git commit -m "feat(cbztojxl): remove replaced source archives"
```

### Task 3: Document the explicit replacement mode and verify the suite

**Files:**
- Modify: `README.md:35-75`

**Interfaces:**
- Consumes: final `--replace-source` behavior from Tasks 1 and 2.
- Produces: user-facing usage and output-behavior documentation.

- [ ] **Step 1: Update README text and examples**

Replace the inaccurate in-place example with:

```markdown
# Replace source archives after successful conversion
python cbztojxl.py /comics/ -r --replace-source
```

Add the option table row:

```markdown
| `--replace-source` | Replace each source archive after a successful conversion; cannot be used with an output directory, and implies `--overwrite` |
```

Replace the in-place output bullet with two bullets:

```markdown
- **No output directory specified:** Creates files next to source with `_jxl` suffix (for example, `comic.cbz` to `comic_jxl.cbz`)
- **`--replace-source`:** Creates an unsuffixed sibling CBZ, then removes a non-CBZ source only after successful conversion. It cannot be combined with an output directory and implies `--overwrite`.
```

Keep the existing output-directory and collision bullets, adjusting only punctuation needed for consistency.

- [ ] **Step 2: Run focused replacement-mode tests to confirm documentation examples match behavior**

Run:

```bash
python3 -m unittest tests.test_cbztojxl.CbzToJxlDiscoveryAndPathSafetyTests tests.test_cbztojxl.CbzToJxlStageOutputTests -v
```

Expected: PASS, including replacement-mode path, collision, replacement, and dry-run behavior.

- [ ] **Step 3: Run the full automated test suite**

Run:

```bash
python3 -m unittest discover -v
```

Expected: PASS with no failures or errors.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md
git commit -m "docs: explain replace-source conversions"
```
