# cbztojxl

Convert CBZ archives containing JPEG images to JXL format using lossless compression.

## Installation

Requires:
- Python 3.6+
- [cjxl from libjxl](https://github.com/libjxl/libjxl)
- zip and unzip utilities (usually pre-installed on Linux/macOS)

```bash
# On Ubuntu/Debian
sudo apt-get install zip unzip
# Then install libjxl (follow instructions at https://github.com/libjxl/libjxl)
```

## Usage

```bash
# Single file - output with _jxl suffix
python cbztojxl.py comic.cbz

# Directory - process all .cbz files in directory
python cbztojxl.py /path/to/comics/

# Directory recursive - process all .cbz files recursively
python cbztojxl.py /path/to/comics/ -r

# Output to different directory - mirror structure, no suffix
python cbztojxl.py /path/to/comics/ /backup/ -r

# In-place conversion - replace original files
python cbztojxl.py /comics/ /comics/ -r -o

# Verbose mode
python cbztojxl.py comic.cbz -v

# Dry run - see what would happen
python cbztojxl.py /comics/ /backup/ -r --dry-run
```

## Options

| Option | Description |
|--------|-------------|
| `-r, --recursive` | Process directories recursively |
| `-o, --overwrite` | Overwrite existing output files |
| `-v, --verbose` | Print detailed logging |
| `--dry-run` | Show what would happen without making changes |
| `-h, --help` | Show help message |

## Output Behavior

- **No output directory specified:** Creates files next to source with `_jxl` suffix (e.g., `comic.cbz` → `comic_jxl.cbz`)
- **Output directory specified:** Creates files in output directory without suffix, preserving relative directory structure
- **Output directory = source directory + `--overwrite`:** Replaces original files in place

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | CLI or dependency error |
| 2 | One or more conversion failures |
