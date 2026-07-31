# PDF-to-CBZ Page Method Counts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Print each successfully created comic's total, lossless, and re-rendered page counts.

**Architecture:** Count each page-processing branch inside `build_page_images()`, where the method is already selected. Return an immutable `PageBuildResult` to `process_pdf()`, which formats the requested completion line.

**Tech Stack:** Python standard library, `dataclasses`, `unittest`, `unittest.mock`

## Global Constraints

- The completion line must be `Created: comic.cbz (12 pages: 9 lossless, 3 re-rendered)`.
- Include zero-valued method counts.
- Do not alter skipped-file, dry-run, error, or verbose per-page output.

---

### Task 1: Count Page Processing Methods and Report Them

**Files:**
- Modify: `pdftocbz.py`
- Modify: `tests/test_pdftocbz.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the existing direct-copy versus render decision in `build_page_images(pdf_path, work_dir, fallback_dpi, verbose)`
- Produces: `PageBuildResult(total: int, lossless: int, rerendered: int)` returned by `build_page_images()`

- [ ] **Step 1: Write failing tests for branch counts and completion output**

Add a `PageBuildResult` assertion around a two-page `build_page_images()` call. Patch PDF inspection and rendering dependencies so page 1 selects an extracted JPEG and page 2 renders, then assert:

```python
self.assertEqual(
    result,
    pdftocbz.PageBuildResult(total=2, lossless=1, rerendered=1),
)
```

Add a `process_pdf()` test that patches `temp_dir`, `build_page_images`, and `create_cbz`, captures stdout, and asserts:

```python
self.assertEqual(
    stdout.getvalue().strip(),
    "Created: comic.cbz (12 pages: 9 lossless, 3 re-rendered)",
)
```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run:

```bash
python3 -m unittest tests.test_pdftocbz.PdfToCbzUnitTests.test_build_page_images_counts_lossless_and_rerendered_pages tests.test_pdftocbz.PdfToCbzUnitTests.test_process_pdf_prints_page_method_counts -v
```

Expected: FAIL because `PageBuildResult` and the new completion output do not exist.

- [ ] **Step 3: Implement the immutable result and increment both branch counts**

Add:

```python
@dataclass(frozen=True)
class PageBuildResult:
    total: int
    lossless: int
    rerendered: int
```

Initialize `lossless = 0` and `rerendered = 0` before the page loop. Increment `lossless` after copying a direct JPEG, increment `rerendered` after rendering, and return:

```python
return PageBuildResult(page_count, lossless, rerendered)
```

In `process_pdf()`, store this result and print:

```python
print(
    f"Created: {output_path} ({result.total} pages: "
    f"{result.lossless} lossless, {result.rerendered} re-rendered)"
)
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run the Step 2 command again.

Expected: both tests PASS.

- [ ] **Step 5: Document the completion summary**

In README's PDF-to-CBZ section, add this example after the commands:

```text
Created: comic.cbz (12 pages: 9 lossless, 3 re-rendered)
```

Explain in one sentence that the summary distinguishes unchanged embedded JPEG extraction from rendered pages.

- [ ] **Step 6: Run full verification**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests PASS with no failures or errors.

Run:

```bash
python3 -m py_compile pdftocbz.py
git diff --check
```

Expected: both commands exit 0 with no output.

- [ ] **Step 7: Commit the implementation**

```bash
git add pdftocbz.py tests/test_pdftocbz.py README.md
git commit -m "feat: report pdftocbz page processing counts"
```
