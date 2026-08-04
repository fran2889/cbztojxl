# RAR Dependency Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require `unrar`, rather than accepting `rar`, for CBR and RAR archive support in both command-line utilities.

**Architecture:** Keep each utility's existing RAR commands and format registry unchanged because they already execute `unrar`. Simplify their optional-dependency configuration to probe only `unrar`; the existing availability filtering will then accurately exclude RAR formats whenever that executable is unavailable. Document the same single-executable contract in the README.

**Tech Stack:** Python 3.10+, standard-library `unittest`, `unittest.mock`.

## Global Constraints

- Preserve existing RAR command lists, warning text, archive filtering, exit codes, and dry-run behavior.
- Use only `unrar` as the optional RAR executable.
- Keep user-facing prose ASCII-only.
- Run `python3 -m unittest discover -v` before reporting completion.

---

### Task 1: Test RAR dependency availability

**Files:**
- Modify: `tests/test_cbztojxl.py`
- Modify: `tests/test_cbaudit.py`

**Interfaces:**
- Consumes: `cbztojxl.check_dependencies() -> None` and `cbaudit.check_dependencies(skip_errors: bool = False)`.
- Produces: regression coverage showing RAR formats require `unrar`, even if `rar` is available.

- [x] **Step 1: Write the failing tests**

Add one focused test to each test module. Mock `is_tool_available` so the mandatory tool, `7z`, and `rar` are available, but `unrar` is unavailable. Call the relevant dependency check, suppress stderr, and assert that `ARCHIVE_FORMATS` excludes `"rar"`. Save and restore `ARCHIVE_FORMATS` so the test does not affect later tests.

```python
def test_rar_formats_require_unrar(self):
    original_formats = cbztojxl.ARCHIVE_FORMATS
    self.addCleanup(setattr, cbztojxl, "ARCHIVE_FORMATS", original_formats)
    available = {"cjxl", "7z", "rar"}

    with (
        patch.object(cbztojxl, "is_tool_available", side_effect=available.__contains__),
        patch("sys.stderr", new_callable=io.StringIO),
    ):
        cbztojxl.check_dependencies()

    self.assertNotIn("rar", cbztojxl.ARCHIVE_FORMATS)
```

- [x] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
python3 -m unittest tests.test_cbztojxl tests.test_cbaudit -v
```

Expected: the new assertions fail because the current configuration accepts `rar` as an `unrar` substitute.

- [x] **Step 3: Add the complementary supported-case assertions**

In the same focused tests, mock availability with `unrar` present and `rar` absent, then assert `"rar"` remains in `ARCHIVE_FORMATS`. This proves the tests exercise the intended executable name instead of merely testing that formats can be excluded. Use the same saved-format cleanup as the first assertion.

```python
available = {"cjxl", "7z", "unrar"}
with patch.object(cbztojxl, "is_tool_available", side_effect=available.__contains__):
    cbztojxl.check_dependencies()

self.assertIn("rar", cbztojxl.ARCHIVE_FORMATS)

For `cbaudit`, use `{"identify", "7z", "rar"}` and
`{"identify", "7z", "unrar"}` respectively, call
`cbaudit.check_dependencies(skip_errors=True)`, and patch `sys.stderr` for the
warning assertion path.
```

- [x] **Step 4: Implement the minimal dependency configuration change**

Replace the RAR entries in both optional tool mappings with a single-element list. Do not change the RAR command configuration or filtering comprehension.

```python
OPTIONAL_TOOLS = {
    'unrar': ['unrar'],
    '7z': ['7z'],
}
```

- [x] **Step 5: Update the README dependency wording**

Replace the optional dependency bullet with:

```markdown
- Optional: unrar (for CBR/RAR support)
```

- [x] **Step 6: Run the focused tests to verify they pass**

Run:

```bash
python3 -m unittest tests.test_cbztojxl tests.test_cbaudit -v
```

Expected: all tests pass, including the new `rar`-only and `unrar`-only dependency checks.

- [x] **Step 7: Commit the implementation**

```bash
git add cbztojxl.py cbaudit.py README.md tests/test_cbztojxl.py tests/test_cbaudit.py
git commit -m "fix: require unrar for RAR archive support"
```

### Task 2: Verify the complete repository

**Files:**
- Verify: `cbztojxl.py`
- Verify: `cbaudit.py`
- Verify: `README.md`
- Verify: `tests/test_cbztojxl.py`
- Verify: `tests/test_cbaudit.py`

**Interfaces:**
- Consumes: the dependency detection and regression tests completed in Tasks 1 and 2.
- Produces: fresh evidence that the full test suite passes.

- [ ] **Step 1: Run the required full test suite**

Run:

```bash
python3 -m unittest discover -v
```

Expected: exit code 0 with no test failures or errors.

- [ ] **Step 2: Inspect the final diff and whitespace**

Run:

```bash
git diff --check HEAD~1..HEAD
git status --short
```

Expected: no whitespace errors; the status output contains no unintended tracked changes.
