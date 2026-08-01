import importlib.util
import tempfile
import unittest
import zipfile
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


class CbAuditProcessingTests(unittest.TestCase):
    def setUp(self):
        self.format_config = cbaudit.ALL_FORMATS["zip"]

    def test_zip_extraction_uses_native_library_without_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "comic.cbz"
            extracted = root / "extracted"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("pages/0001.jpg", b"jpeg")

            with patch.object(cbaudit.subprocess, "run", side_effect=AssertionError):
                cbaudit.extract_archive(archive, extracted, self.format_config)

            self.assertEqual((extracted / "pages" / "0001.jpg").read_bytes(), b"jpeg")

    def test_discovery_orders_archives_by_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "z.cbz").touch()
            nested = root / "series"
            nested.mkdir()
            (nested / "a.cbz").touch()
            (root / "A.cbz").touch()
            with patch.object(cbaudit, "ARCHIVE_FORMATS", cbaudit.ALL_FORMATS):
                discovered = cbaudit.find_archive_files(root, recursive=True)

        self.assertEqual(
            [path.relative_to(root).as_posix() for path in discovered],
            ["A.cbz", "series/a.cbz", "z.cbz"],
        )

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
                patch.object(cbaudit, "get_format_config", return_value=self.format_config),
                patch.object(cbaudit, "extract_archive", side_effect=fake_extract),
                patch.object(cbaudit, "scan_images", side_effect=fake_scan),
                patch.object(cbaudit, "get_file_sizes", side_effect=fake_sizes),
                patch.object(cbaudit, "print_archive_report", return_value=False) as report,
                redirect_stdout(StringIO()),
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
                patch.object(cbaudit, "get_format_config", return_value=self.format_config),
                patch.object(cbaudit, "extract_archive", side_effect=fake_extract),
                patch.object(cbaudit, "scan_images", return_value=([False], [80], [])),
                patch.object(cbaudit, "get_file_sizes", side_effect=OSError("metadata unavailable")),
                redirect_stderr(stderr),
            ):
                result = cbaudit.process_archive(
                    archive, False, 70, True, False, page_size_threshold=100
                )

        self.assertEqual(result, (True, 1, 1))
        self.assertIn("Could not read page sizes for comic.cbz", stderr.getvalue())


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
            patch.object(cbaudit, "parse_args", return_value=arguments),
            patch.object(cbaudit, "check_dependencies"),
            patch.object(cbaudit, "find_archive_files", return_value=[archive]),
            patch.object(cbaudit, "process_archive", return_value=(True, 5, 5)) as process,
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
            patch.object(cbaudit, "parse_args", return_value=arguments),
            patch.object(cbaudit, "check_dependencies"),
            patch.object(cbaudit, "find_archive_files", return_value=[Path("comic.cbz")]),
            patch.object(cbaudit, "process_archive", return_value=(False, 5, 5)) as process,
            redirect_stdout(StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            cbaudit.main()

        self.assertEqual(raised.exception.code, 0)
        self.assertIsNone(process.call_args.kwargs["page_size_threshold"])
