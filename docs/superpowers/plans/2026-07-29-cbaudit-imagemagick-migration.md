# Implementation Plan: Migrate cbaudit.py from jpeginfo to ImageMagick

**Date:** 2026-07-29  
**Status:** Ready for Implementation  
**Related Spec:** docs/superpowers/specs/2026-07-29-cbaudit-imagemagick-migration-design.md  
**Target Script:** cbaudit.py

---

## Overview

This plan details the step-by-step implementation to migrate `cbaudit.py` from using `jpeginfo` to using `imagemagick`'s `identify` command for both quality extraction and corruption detection.

---

## Prerequisites

- ImageMagick installed and `identify` command available in PATH
- Existing `cbaudit.py` working (current state with jpeginfo)
- Git working directory clean or on a feature branch

---

## Implementation Steps

### Phase 1: Preparation (Setup)

**Goal:** Ensure environment is ready for changes.

| # | Task | Command/Action | Verification |
|---|------|----------------|--------------|
| 1 | Create feature branch | `git checkout -b feat/migrate-cbaudit-to-imagemagick` | `git branch` shows new branch |
| 2 | Verify ImageMagick available | `which identify && identify --version` | identify command found, version displayed |
| 3 | Backup current cbaudit.py | `cp cbaudit.py cbaudit.py.backup` | backup file exists |

---

### Phase 2: Core Function Updates

**Goal:** Update the image scanning functions to use imagemagick.

#### Task 1: Update MANDATORY_TOOLS

**File:** `cbaudit.py`

**Change:**
```python
# Line 128: Change MANDATORY_TOOLS
MANDATORY_TOOLS = ['identify', 'unzip']  # was: ['jpeginfo', 'unzip']
```

**Dependencies:** None

---

#### Task 2: Update check_dependencies() messages

**File:** `cbaudit.py`

**Changes:**
```python
# Line 150: Update error message
print("Install imagemagick from your package manager", file=sys.stderr)  
# was: print("Install jpeginfo from your package manager or https://github.com/tjko/jpeginfo", file=sys.stderr)
```

**Dependencies:** None

---

#### Task 3: Update description in parse_args()

**File:** `cbaudit.py`

**Change:**
```python
# Lines 166-168: Update description
parser = argparse.ArgumentParser(
    description="Audit comic archives (CBZ, ZIP, CBR, RAR, CB7, 7Z) "
                "for JPEG image quality and corruption using ImageMagick.",
)  # was: "for JPEG image quality and corruption."
```

**Dependencies:** None

---

#### Task 4: Replace scan_image() function

**File:** `cbaudit.py` (lines 234-267)

**Current function (to be replaced):**
```python
def scan_image(image_path: Path) -> tuple[bool, int | None]:
    """Run jpeginfo on a single image. Returns (is_ok, quality).
    
    is_ok: True if image is not corrupted
    quality: integer quality estimate (1-100), or None if unparseable
    """
    try:
        result = subprocess.run(
            ['jpeginfo', '-v', '-c', str(image_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout.strip()
        
        # Parse: [OK] filename.jpg: 85% quality, RGB, 1920x1080
        # or: [OK] filename.jpg: 85%  RGB  1920x1080
        match = re.match(r'\[([^\]]+)\]\s+[^:]+:\s*(\d+)%?\s*quality', output, re.IGNORECASE)
        if match:
            status = match.group(1).upper()
            quality = int(match.group(2))
            is_ok = status == 'OK'
            return (is_ok, quality)
        
        # Check for CORRUPT status
        if '[CORRUPT]' in output.upper():
            return (False, None)
        
        # Fallback: check exit code
        is_ok = result.returncode == 0
        return (is_ok, None)
        
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return (False, None)
```

**New function:**
```python
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
```

**Dependencies:** None

**Note:** We can also remove the `import re` at the top since we no longer need regex parsing.

---

#### Task 5: Update process_archive() for full scan workflow

**File:** `cbaudit.py` (lines 365-447)

**Current behavior:** Full scan samples 5 images for quality, checks all for integrity (but integrity check also uses jpeginfo)

**New behavior:** Full scan checks ALL images for both integrity and quality.

**Change:** Remove the sampling logic for full scan quality checking. The current code at lines 407-411:

```python
if full_scan:
    selected = jpeg_files
else:
    indices = get_sample_indices(total_jpegs, 5)
    selected = [jpeg_files[i] for i in indices]
```

This is already correct for our new workflow! With full_scan, `selected = jpeg_files` (all files), and we check both integrity and quality on all of them via `scan_images(selected)`.

**No changes needed** for the sampling logic — it already does what we want:
- Quick scan: samples 5, checks both on all 5
- Full scan: uses all, checks both on all

**Verification:** The `scan_images()` function calls `scan_image()` on each path, which now returns both integrity and quality info.

**Dependencies:** Task 4 (scan_image updated)

---

### Phase 3: Validation and Cleanup

**Goal:** Verify the changes work correctly and clean up.

| # | Task | Command/Action | Verification |
|---|------|----------------|--------------|
| 1 | Run syntax check | `python3 -m py_compile cbaudit.py` | No syntax errors |
| 2 | Test with valid archive | `python3 cbaudit.py --verbose test.cbz` | Correct quality values, OK status |
| 3 | Test with known low quality | `python3 cbaudit.py -t 80 test_low.cbz` | LOW QUALITY status |
| 4 | Test full scan | `python3 cbaudit.py --full-scan --verbose test.cbz` | All images scanned |
| 5 | Test dependency check | `python3 cbaudit.py` (with no identify) | Proper error message |
| 6 | Remove backup | `rm cbaudit.py.backup` | Backup removed |
| 7 | Remove unused import | Remove `import re` if no longer used | Code still works |

---

### Phase 4: Documentation Updates

**Goal:** Update documentation to reflect the changes.

| # | Task | File | Change |
|---|------|------|--------|
| 1 | Update README.md | README.md | Update dependencies section to mention ImageMagick instead of jpeginfo |
| 2 | Update original spec | docs/superpowers/specs/2026-07-29-cbaudit-design.md | Add note: "Updated to use ImageMagick identify instead of jpeginfo (see migration spec)" |

---

## Checkpoints

### Checkpoint 1: Core Functionality
After completing Phase 2, Task 4:
- [ ] `scan_image()` works with identify
- [ ] Returns correct (is_ok, quality) tuples
- [ ] Handles corrupted files correctly
- [ ] Handles valid files correctly

**Verification command:**
```bash
python3 -c "
from pathlib import Path
from cbaudit import scan_image
print(scan_image(Path('test_85.jpg')))  # Should be (True, 85)
print(scan_image(Path('test_corrupt.jpg')))  # Should be (False, None)
"
```

### Checkpoint 2: Integration
After completing Phase 2, Task 5:
- [ ] Quick scan extracts 5, checks both on all 5
- [ ] Full scan extracts all, checks both on all
- [ ] Status classification works correctly

**Verification command:**
```bash
python3 cbaudit.py --verbose test_archive.cbz
python3 cbaudit.py --full-scan --verbose test_archive.cbz
```

### Checkpoint 3: Error Handling
After completing Phase 3:
- [ ] Missing identify → proper error
- [ ] Corrupted images → detected correctly
- [ ] Partial corruption → detected correctly (strict mode)

**Verification command:**
```bash
# Test missing dependency
mv $(which identify) /tmp/identify_backup 2>/dev/null
python3 cbaudit.py test.cbz 2>&1 | grep -i "imagemagick"
mv /tmp/identify_backup $(which identify) 2>/dev/null
```

---

## Rollback Plan

If issues are discovered after implementation:

```bash
# Restore from backup (if still available)
cp cbaudit.py.backup cbaudit.py

# Or revert from git
git checkout main -- cbaudit.py
```

---

## Git Commits

### Commit 1: Update dependencies and help text
```bash
git add cbaudit.py
git commit -m "feat: replace jpeginfo with imagemagick identify for quality/corruption checks

- Update MANDATORY_TOOLS from jpeginfo to identify
- Update dependency error messages
- Update help description to mention ImageMagick

Generated by Mistral Vibe.
Co-Authored-By: Mistral Vibe <vibe@mistral.ai>"
```

### Commit 2: Migrate scan_image function
```bash
git add cbaudit.py
git commit -m "feat: implement identify-based image scanning

- Replace jpeginfo with identify -format '%Q' in scan_image()
- Add strict corruption detection (exit code + stderr patterns)
- Parse numeric quality from identify output
- Remove unused regex import

Generated by Mistral Vibe.
Co-Authored-By: Mistral Vibe <vibe@mistral.ai>"
```

### Commit 3: Documentation updates (optional)
```bash
git add README.md docs/
git commit -m "docs: update documentation for imagemagick migration

- Update README.md dependencies
- Add migration spec and plan
- Update original spec with migration note

Generated by Mistral Vibe.
Co-Authored-By: Mistral Vibe <vibe@mistral.ai>"
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| identify not installed on user systems | Medium | High | Clear error message guides installation |
| identify output format varies by version | Low | Medium | Use well-tested -format "%Q" which is stable |
| Performance regression (identify slower than jpeginfo) | Low | Low | identify reads full file but is generally fast |
| Partial corruption false positives | Medium | Low | Strict mode is intentional for audit tool |

---

## Success Criteria

- [ ] All existing functionality preserved (no breaking changes)
- [ ] Quality values correctly extracted from JPEG files
- [ ] Corruption detection works with strict criteria
- [ ] Quick scan: 5 sampled images, both checks on all 5
- [ ] Full scan: all images extracted and checked
- [ ] Dependency error messages are clear and helpful
- [ ] Code passes syntax check
- [ ] Manual testing with sample archives passes

---

## Next Steps

After completing this implementation:

1. Run full test suite (if available)
2. Test with real comic archives
3. Consider adding test fixtures for automated testing
4. Update any CI/CD configuration if needed

---

## Approval

Implementation plan approved by user on 2026-07-29. Ready to begin implementation.
