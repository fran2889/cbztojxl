import importlib.util
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch


MODULE_PATH = Path(__file__).parents[1] / "pdftocbz.py"
SPEC = importlib.util.spec_from_file_location("pdftocbz", MODULE_PATH)
pdftocbz = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pdftocbz)


class PdfToCbzUnitTests(unittest.TestCase):
    def test_create_cbz_uses_native_zip_and_orders_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pages = root / "pages"
            pages.mkdir()
            (pages / "0002.jpg").write_bytes(b"second")
            (pages / "0001.jpg").write_bytes(b"first")
            output = root / "comic.cbz"

            with patch.object(pdftocbz.subprocess, "run", side_effect=AssertionError):
                pdftocbz.create_cbz(output, pages)

            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), ["0001.jpg", "0002.jpg"])

    def test_build_page_images_counts_lossless_and_rerendered_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            direct = root / "direct.jpg"
            direct.write_bytes(b"original")
            work_dir = root / "work"
            work_dir.mkdir()

            def render_page(_pdf_path, _page, _dpi, destination):
                destination.write_bytes(b"rendered")

            command_result = MagicMock(stdout="")
            with (
                patch.object(pdftocbz, "get_page_count", return_value=2),
                patch.object(pdftocbz, "run_command", return_value=command_result),
                patch.object(pdftocbz.subprocess, "run"),
                patch.object(pdftocbz, "page_has_text", return_value=False),
                patch.object(pdftocbz, "select_direct_image", side_effect=[direct, None]),
                patch.object(pdftocbz, "render_page", side_effect=render_page),
            ):
                result = pdftocbz.build_page_images(Path("comic.pdf"), work_dir, 300, False)

        self.assertEqual(
            result,
            pdftocbz.PageBuildResult(total=2, lossless=1, rerendered=1),
        )

    def test_process_pdf_prints_page_method_counts(self):
        temporary = MagicMock()
        temporary.__enter__.return_value = Path("work")
        result = pdftocbz.PageBuildResult(total=12, lossless=9, rerendered=3)

        with (
            patch.object(pdftocbz, "compute_output_path", return_value=Path("comic.cbz")),
            patch.object(pdftocbz, "temp_dir", return_value=temporary),
            patch.object(pdftocbz, "build_page_images", return_value=result),
            patch.object(pdftocbz, "create_cbz"),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            status = pdftocbz.process_pdf(
                Path("comic.pdf"), Path("."), None, False, False, False, 300
            )

        self.assertEqual(status, "processed")
        self.assertEqual(
            stdout.getvalue().strip(),
            "Created: comic.cbz (12 pages: 9 lossless, 3 re-rendered)",
        )

    def test_render_page_uses_single_page_jpeg_command(self):
        with patch("pdftocbz.subprocess.run") as run:
            pdftocbz.render_page(Path("comic.pdf"), 2, 300, Path("0002.jpg"))

        self.assertEqual(
            run.call_args.args[0],
            ["pdftocairo", "-f", "2", "-l", "2", "-singlefile", "-jpeg",
             "-jpegopt", "quality=95", "-r", "300", "comic.pdf", "0002"],
        )
    def test_find_pdf_files_is_case_insensitive_and_recursive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "first.PDF").touch()
            nested = root / "nested"
            nested.mkdir()
            (nested / "second.pdf").touch()

            self.assertEqual(pdftocbz.find_pdf_files(root, False), [root / "first.PDF"])
            self.assertEqual(
                pdftocbz.find_pdf_files(root, True),
                [root / "first.PDF", nested / "second.pdf"],
            )

    def test_parse_pdfimages_list_keeps_jpeg_records_and_ppi(self):
        listing = "1 0 image 1200 1800 rgb 3 8 jpeg no 8 0 300 300 120K 1.9%\n"

        images = pdftocbz.parse_pdfimages_list(listing)

        self.assertEqual(images[0].page, 1)
        self.assertEqual(images[0].encoding, "jpeg")
        self.assertEqual(images[0].x_ppi, 300.0)

    def test_compute_output_path_uses_cbz_without_default_suffix(self):
        source = Path("/library/Series/Issue.pdf")

        self.assertEqual(
            pdftocbz.compute_output_path(source, source, None),
            Path("/library/Series/Issue.cbz"),
        )
        self.assertEqual(
            pdftocbz.compute_output_path(source, Path("/library"), Path("/target")),
            Path("/target/Series/Issue.cbz"),
        )

    def test_direct_image_requires_one_existing_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jpeg = pdftocbz.EmbeddedImage(1, 0, "jpeg", 1200, 1800, 300, 300)
            (root / "image-000.jpg").write_bytes(b"original")
            self.assertEqual(pdftocbz.select_direct_image([jpeg], 1, root), root / "image-000.jpg")
            self.assertIsNone(pdftocbz.select_direct_image([jpeg, jpeg], 1, root))

    def test_render_dpi_uses_largest_jpeg_or_fallback(self):
        small = pdftocbz.EmbeddedImage(2, 1, "jpeg", 300, 300, 144, 144)
        large = pdftocbz.EmbeddedImage(2, 2, "jpeg", 1200, 1800, 299, 301)
        self.assertEqual(pdftocbz.select_render_dpi([small, large], 2, 300), 300)
        self.assertEqual(pdftocbz.select_render_dpi([], 3, 300), 300)
