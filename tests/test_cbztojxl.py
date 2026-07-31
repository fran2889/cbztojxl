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
