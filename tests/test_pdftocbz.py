import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "pdftocbz.py"
SPEC = importlib.util.spec_from_file_location("pdftocbz", MODULE_PATH)
pdftocbz = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pdftocbz)


class PdfToCbzUnitTests(unittest.TestCase):
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
