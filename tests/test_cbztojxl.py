import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
import zipfile
from argparse import Namespace
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "cbztojxl.py"
SPEC = importlib.util.spec_from_file_location("cbztojxl", MODULE_PATH)
cbztojxl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cbztojxl)


class CbzToJxlDependencyTests(unittest.TestCase):
    def test_rar_formats_require_unrar(self):
        original_formats = cbztojxl.ARCHIVE_FORMATS
        self.addCleanup(setattr, cbztojxl, "ARCHIVE_FORMATS", original_formats)

        available = {"cjxl", "7z", "rar"}
        with (
            patch.object(cbztojxl, "is_tool_available", side_effect=available.__contains__),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            cbztojxl.check_dependencies()

        self.assertNotIn("rar", cbztojxl.ARCHIVE_FORMATS)
        self.assertIn("Warning: unrar not found", stderr.getvalue())

        available = {"cjxl", "7z", "unrar"}
        with patch.object(
            cbztojxl, "is_tool_available", side_effect=available.__contains__
        ):
            cbztojxl.check_dependencies()

        self.assertIn("rar", cbztojxl.ARCHIVE_FORMATS)


class RecordingStream(io.StringIO):
    def __init__(self, name, events):
        super().__init__()
        self.name = name
        self.events = events

    def write(self, value):
        self.events.append((self.name, "write", value))
        return super().write(value)

    def flush(self):
        self.events.append((self.name, "flush", ""))
        return super().flush()


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
                "[done]  comic.cbz => comic_jxl.cbz | 3 pages | "
                "12 B => 12 B (0.0% smaller)",
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
        self.assertEqual(
            stdout.strip(),
            "[skip]  comic.cbz => comic_jxl.cbz | output already exists",
        )
        temporary.assert_not_called()

    def test_dry_run_verbose_success_matches_normal_success_details(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, result, stdout, _, _, _, _ = self.run_dry(
                Path(directory), overwrite=True, verbose=True
            )

        self.assertEqual(result[2], "processed")
        self.assertIn("[done]  comic.cbz => comic_jxl.cbz | 3 pages", stdout)
        self.assertIn("12 B => 12 B (0.0% smaller)", stdout)
        self.assertNotIn("Would create", stdout)


class CbzToJxlOutputFormattingTests(unittest.TestCase):
    def test_total_is_mode_independent_and_omits_pages(self):
        expected = (
            "[total] 4 archives | 2 done, 1 skipped, 1 failed | "
            "150 B => 115 B (23.3% smaller)"
        )
        actual = cbztojxl.format_total(4, 2, 1, 1, 150, 115)
        self.assertEqual(actual, expected)
        self.assertNotIn("pages", actual)

    def test_display_paths_preserve_nested_relative_paths(self):
        self.assertEqual(
            cbztojxl.display_input_path(Path("/in/series/volume.cbz"), Path("/in")),
            "series/volume.cbz",
        )
        self.assertEqual(
            cbztojxl.display_output_path(Path("/out/series/volume.cbz"), Path("/out")),
            "series/volume.cbz",
        )

    def test_disappearing_single_input_still_displays_its_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "vanished.cbz"

            self.assertEqual(
                cbztojxl.display_input_path(source, source),
                "vanished.cbz",
            )

    def test_temp_dir_is_created_under_requested_output_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "series"
            with cbztojxl.temp_dir(parent) as temporary:
                self.assertEqual(temporary.parent, parent.resolve())
                self.assertTrue(temporary.exists())
            self.assertFalse(temporary.exists())

    def test_report_processed_uses_compact_ascii_format(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            cbztojxl.report_processed("series/in.cbz", "series/out.cbz", 100, 75, 24)
        self.assertEqual(
            stdout.getvalue().strip(),
            "[done]  series/in.cbz => series/out.cbz | 24 pages | 100 B => 75 B (25.0% smaller)",
        )

    def test_progress_uses_relative_path_without_processing_prefix(self):
        callback, _ = cbztojxl.create_progress_callback("series/in.cbz", 1, 2, 4)
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            callback(2)
        self.assertIn("series/in.cbz [1/2]", stdout.getvalue())
        self.assertNotIn("Processing:", stdout.getvalue())

    def test_verbose_adds_details_but_keeps_done_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extracted = root / "out" / "series" / ".cbztojxl_tmp_test"
            page = extracted / "chapter" / "page001.jpg"
            page.parent.mkdir(parents=True)
            page.write_bytes(b"jpeg")
            with (
                patch("subprocess.run"),
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                failures = cbztojxl.convert_jpegs_to_jxl(extracted, verbose=True)
        self.assertEqual(failures, [])
        self.assertIn("Converting page 1/1: chapter/page001.jpg", stdout.getvalue())
        self.assertNotIn("image", stdout.getvalue())

    def test_conversion_error_prints_full_page_path_and_stderr(self):
        error = subprocess.CalledProcessError(
            1,
            ["cjxl", "--secret-option", "/private/input.jpg"],
            stderr=b"could not decode JPEG input\n",
        )
        detail = cbztojxl.command_diagnostic("cjxl", error)
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            cbztojxl.report_error(
                "series/volume.cbz | convert page 1/1: chapter/page001.jpg failed",
                detail,
            )
        self.assertEqual(
            stderr.getvalue(),
            "[error] series/volume.cbz | convert page 1/1: "
            "chapter/page001.jpg failed\n"
            "        cjxl exited with status 1: could not decode JPEG input\n",
        )
        self.assertNotIn("--secret-option", stderr.getvalue())
        self.assertNotIn("/private/input.jpg", stderr.getvalue())

    def test_command_diagnostic_uses_only_last_stderr_line(self):
        error = subprocess.CalledProcessError(
            9, ["unzip", "/private/archive.cbz"], stderr="context\ncorrupt archive\n"
        )
        self.assertEqual(
            cbztojxl.command_diagnostic("unzip", error),
            "unzip exited with status 9: corrupt archive",
        )

    def test_command_diagnostic_redacts_paths_arguments_and_terminal_controls(self):
        archive = "/private/library/volume.cbz"
        workspace = "/private/output/.cbztojxl_tmp_secret"
        error = subprocess.CalledProcessError(
            9,
            ["unzip", "-l", archive, workspace, "--secret-option"],
            stderr=(
                f"failure \x1b[31m{archive}\x1b[0m {workspace} "
                "/etc/passwd --secret-option \x07\u202e"
            ).encode(),
        )

        actual = cbztojxl.command_diagnostic("unzip", error)

        self.assertEqual(
            actual,
            "unzip exited with status 9: failure <arg> <arg> <path> <arg>",
        )
        for secret in (
            archive,
            workspace,
            "/etc/passwd",
            "--secret-option",
            "\x1b",
            "\x07",
            "\u202e",
        ):
            self.assertNotIn(secret, actual)

    def test_display_paths_escape_terminal_control_characters(self):
        displayed = cbztojxl.display_input_path(
            Path("/in/series/evil\n\x1b[31m\u202e.cbz"), Path("/in")
        )

        self.assertEqual(displayed, "series/evil\\n\\x1b[31m\\u202e.cbz")
        self.assertNotIn("\n", displayed)
        self.assertNotIn("\x1b", displayed)
        self.assertNotIn("\u202e", displayed)

    def test_display_paths_encode_reserved_transcript_delimiters(self):
        displayed = cbztojxl.display_input_path(
            Path("/in/series/a|b=>c.cbz"), Path("/in")
        )

        self.assertEqual(displayed, "series/a%7Cb%3D%3Ec.cbz")
        self.assertNotIn("|", displayed)
        self.assertNotIn("=>", displayed)

    def test_report_error_flushes_stdout_before_writing_stderr(self):
        events = []
        stdout = RecordingStream("stdout", events)
        stderr = RecordingStream("stderr", events)

        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            cbztojxl.report_error(
                "volume.cbz | extract archive failed",
                "unzip exited with status 9: corrupt archive",
            )

        first_error_write = next(
            index
            for index, event in enumerate(events)
            if event[0:2] == ("stderr", "write")
        )
        self.assertIn(("stdout", "flush", ""), events[:first_error_write])

    def test_extract_error_is_detailed_in_regular_mode(self):
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            cbztojxl.report_error(
                "series/volume.cbz | extract archive failed",
                "unzip exited with status 9: corrupt archive",
            )
        self.assertEqual(
            stderr.getvalue(),
            "[error] series/volume.cbz | extract archive failed\n"
            "        unzip exited with status 9: corrupt archive\n",
        )

    def test_create_error_includes_relative_destination(self):
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            cbztojxl.report_error(
                "series/volume.cbz => series/volume.cbz | create archive failed",
                "zip exited with status 15: could not create output file",
            )
        self.assertEqual(
            stderr.getvalue(),
            "[error] series/volume.cbz => series/volume.cbz | create archive failed\n"
            "        zip exited with status 15: could not create output file\n",
        )


class CbzToJxlDiscoveryAndPathSafetyTests(unittest.TestCase):
    def setUp(self):
        self.format_config = cbztojxl.ALL_FORMATS["zip"]

    def test_invalid_zip_listing_is_not_reported_as_zero_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "volume.cbz"
            archive.write_bytes(b"not a zip")
            with self.assertRaisesRegex(
                cbztojxl.DependencyError,
                "^ZIP archive is invalid or uses unsupported features$",
            ):
                cbztojxl.count_jpegs_in_archive(
                    archive, self.format_config
                )

    def test_missing_zip_file_is_an_extraction_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                cbztojxl.DependencyError,
                "^ZIP archive is invalid or uses unsupported features$",
            ):
                cbztojxl.count_jpegs_in_archive(
                    Path(directory) / "missing.cbz", self.format_config
                )

    def test_archive_listing_counts_jpegs_from_zip_members(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "volume.cbz"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("page.jpg", b"jpeg")
                output.writestr("note.txt", b"note")
            count = cbztojxl.count_jpegs_in_archive(
                archive, self.format_config
            )

        self.assertEqual(count, 1)

    def test_listing_failure_is_an_extract_error_in_both_modes(self):
        for verbose in (False, True):
            with self.subTest(verbose=verbose), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "in" / "series" / "volume.cbz"
                source.parent.mkdir(parents=True)
                source.write_bytes(b"archive-data")
                error = cbztojxl.DependencyError(
                    "unzip exited with status 9: corrupt archive"
                )
                with (
                    patch.object(
                        cbztojxl, "get_format_config", return_value=self.format_config
                    ),
                    patch.object(
                        cbztojxl, "count_jpegs_in_archive", side_effect=error
                    ),
                    patch.object(cbztojxl, "temp_dir") as temporary,
                    patch("sys.stdout", new_callable=io.StringIO) as stdout,
                    patch("sys.stderr", new_callable=io.StringIO) as stderr,
                ):
                    result = cbztojxl.process_archive(
                        source,
                        root / "in",
                        root / "out",
                        overwrite=True,
                        verbose=verbose,
                        dry_run=False,
                    )

                self.assertEqual(result, (len(b"archive-data"), 0, "error_extract"))
                self.assertEqual(
                    stderr.getvalue(),
                    "[error] series/volume.cbz | extract archive failed\n"
                    "        unzip exited with status 9: corrupt archive\n",
                )
                self.assertNotIn("no JPEG pages", stdout.getvalue())
                temporary.assert_not_called()

    def test_discovery_includes_formats_whose_optional_archiver_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cbz = root / "available.cbz"
            cbr = root / "unavailable.cbr"
            cbz.write_bytes(b"zip")
            cbr.write_bytes(b"rar")
            with patch.object(
                cbztojxl,
                "ARCHIVE_FORMATS",
                {"zip": cbztojxl.ALL_FORMATS["zip"]},
            ):
                discovered = cbztojxl.find_archive_files(root, recursive=False)

        self.assertEqual(set(discovered), {cbz, cbr})

    def test_discovery_orders_archives_by_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "z.cbz").touch()
            nested = root / "series"
            nested.mkdir()
            (nested / "a.cbz").touch()
            (root / "A.cbz").touch()

            discovered = cbztojxl.find_archive_files(root, recursive=True)

        self.assertEqual(
            [path.relative_to(root).as_posix() for path in discovered],
            ["A.cbz", "series/a.cbz", "z.cbz"],
        )

    def test_recursive_discovery_excludes_nested_output_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.cbz").touch()
            output = root / "output"
            output.mkdir()
            (output / "previous.cbz").touch()

            discovered = cbztojxl.find_archive_files(
                root, recursive=True, output_dir=output
            )

        self.assertEqual(discovered, [root / "source.cbz"])

    def test_recursive_discovery_retains_input_when_output_is_same_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.cbz"
            source.touch()

            discovered = cbztojxl.find_archive_files(
                root, recursive=True, output_dir=root
            )

        self.assertEqual(discovered, [source])

    def test_zip_listing_uses_native_library_without_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "comic.cbz"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("page.jpg", b"jpeg")
                output.writestr("notes.txt", b"notes")
            with patch.object(cbztojxl.subprocess, "run", side_effect=AssertionError):
                count = cbztojxl.count_jpegs_in_archive(
                    archive, cbztojxl.ALL_FORMATS["zip"]
                )

        self.assertEqual(count, 1)

    def test_invalid_input_diagnostic_hides_absolute_path_and_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing\n\x1b[31m"
            with (
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
                self.assertRaises(SystemExit) as raised,
            ):
                cbztojxl.find_archive_files(missing, recursive=False)

        self.assertEqual(raised.exception.code, cbztojxl.EXIT_DEPENDENCY_ERROR)
        self.assertEqual(
            stderr.getvalue(),
            "Error: missing\\n\\x1b[31m is not a valid file or directory\n",
        )
        self.assertNotIn(str(root), stderr.getvalue())
        self.assertNotIn("\n\x1b", stderr.getvalue())

    def test_unavailable_single_input_reaches_skip_result_and_total(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "volume.cbr"
            source.write_bytes(b"rar")
            args = Namespace(
                input=source,
                output_dir=root / "out",
                recursive=False,
                overwrite=False,
                verbose=False,
                dry_run=False,
            )
            with (
                patch.object(cbztojxl, "parse_args", return_value=args),
                patch.object(cbztojxl, "check_dependencies"),
                patch.object(
                    cbztojxl,
                    "ARCHIVE_FORMATS",
                    {"zip": cbztojxl.ALL_FORMATS["zip"]},
                ),
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
                self.assertRaises(SystemExit) as raised,
            ):
                cbztojxl.main()

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            stdout.getvalue(),
            "[skip]  volume.cbr | archiver not available\n\n"
            "[total] 1 archives | 0 done, 1 skipped, 0 failed\n",
        )

    def test_symlink_aliases_keep_lexical_names_and_distinct_output_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "in"
            series = input_root / "series"
            series.mkdir(parents=True)
            first_target = root / "external-a" / "book.cbz"
            second_target = root / "external-b" / "book.cbz"
            first_target.parent.mkdir()
            second_target.parent.mkdir()
            first_target.write_bytes(b"first")
            second_target.write_bytes(b"second")
            first_alias = series / "alpha.cbz"
            second_alias = series / "beta.cbz"
            first_alias.symlink_to(first_target)
            second_alias.symlink_to(second_target)
            output_root = root / "out"

            with patch.object(cbztojxl, "ARCHIVE_FORMATS", cbztojxl.ALL_FORMATS):
                discovered = sorted(
                    cbztojxl.find_archive_files(input_root, recursive=True)
                )
            displays = [
                cbztojxl.display_input_path(path, input_root) for path in discovered
            ]
            outputs = [
                cbztojxl.compute_output_path(
                    path, input_root, output_root, overwrite=False
                )
                for path in discovered
            ]

        self.assertEqual(discovered, [first_alias, second_alias])
        self.assertEqual(displays, ["series/alpha.cbz", "series/beta.cbz"])
        self.assertEqual(
            outputs,
            [output_root / "series" / "alpha.cbz", output_root / "series" / "beta.cbz"],
        )

    def test_in_place_output_directory_symlink_keeps_safe_lexical_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_dir = root / "library"
            source_dir.mkdir()
            source = source_dir / "volume.cbz"
            source.write_bytes(b"archive")
            output_alias = root / "library-alias"
            output_alias.symlink_to(source_dir, target_is_directory=True)

            output = cbztojxl.compute_output_path(
                source,
                source_dir,
                output_alias,
                overwrite=True,
            )

            self.assertEqual(output, output_alias / "volume.cbz")
            cbztojxl.validate_output_path(output, output_alias)

    def test_in_place_detection_defers_resolve_failures_to_output_validation(self):
        source = Path("/in/volume.cbz")
        output_root = Path("/out")

        with patch.object(Path, "resolve", side_effect=RuntimeError("symlink loop")):
            output = cbztojxl.compute_output_path(
                source,
                Path("/in"),
                output_root,
                overwrite=True,
            )

        self.assertEqual(output, output_root / "volume.cbz")

    def run_escaped_output_case(self, *, leaf_symlink):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        input_root = root / "in"
        source = input_root / "series" / "volume.cbz"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"archive-data")
        output_root = root / "out"
        external = root / "external"
        external.mkdir()
        output = output_root / "series" / "volume.cbz"
        if leaf_symlink:
            output.parent.mkdir(parents=True)
            victim = external / "victim.cbz"
            victim.write_bytes(b"do-not-touch")
            output.symlink_to(victim)
        else:
            output_root.mkdir()
            (output_root / "series").symlink_to(external, target_is_directory=True)
            victim = external / "volume.cbz"

        def extract_page(_archive, extracted, _format_config):
            page = extracted / "page.jpg"
            page.write_bytes(b"jpeg")

        def create(unsafe_output, _source_dir):
            unsafe_output.write_bytes(b"escaped")

        with (
            patch.object(cbztojxl, "get_format_config", return_value=self.format_config),
            patch.object(cbztojxl, "count_jpegs_in_archive", return_value=1),
            patch.object(cbztojxl, "extract_archive", side_effect=extract_page),
            patch.object(cbztojxl, "convert_jpegs_to_jxl", return_value=[]),
            patch.object(cbztojxl, "create_cbz", side_effect=create),
            patch("sys.stdout", new_callable=io.StringIO),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            result = cbztojxl.process_archive(
                source,
                input_root,
                output_root,
                overwrite=True,
                verbose=False,
                dry_run=False,
            )
        return temporary, result, stderr.getvalue(), victim

    def test_symlinked_output_parent_cannot_escape_output_root(self):
        temporary, result, stderr, victim = self.run_escaped_output_case(
            leaf_symlink=False
        )
        try:
            self.assertEqual(result[2], "error_create")
            self.assertFalse(victim.exists())
            self.assertIn("| create archive failed\n", stderr)
            self.assertNotIn(str(victim.parent), stderr)
        finally:
            temporary.cleanup()

    def test_output_leaf_symlink_is_rejected_without_touching_target(self):
        temporary, result, stderr, victim = self.run_escaped_output_case(
            leaf_symlink=True
        )
        try:
            self.assertEqual(result[2], "error_create")
            self.assertEqual(victim.read_bytes(), b"do-not-touch")
            self.assertIn("| create archive failed\n", stderr)
            self.assertNotIn(str(victim.parent), stderr)
        finally:
            temporary.cleanup()

    def test_symlink_loop_in_output_parent_is_a_sanitized_create_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "in"
            source = input_root / "series" / "volume.cbz"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"archive-data")
            output_root = root / "out"
            output_root.mkdir()
            (output_root / "series").symlink_to(
                "series", target_is_directory=True
            )
            with (
                patch.object(
                    cbztojxl, "get_format_config", return_value=self.format_config
                ),
                patch.object(cbztojxl, "count_jpegs_in_archive", return_value=1),
                patch.object(cbztojxl, "temp_dir") as temporary,
                patch("sys.stdout", new_callable=io.StringIO),
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                result = cbztojxl.process_archive(
                    source,
                    input_root,
                    output_root,
                    overwrite=True,
                    verbose=False,
                    dry_run=False,
                )

            self.assertEqual(result[2], "error_create")
            self.assertIn("| create archive failed\n", stderr.getvalue())
            self.assertNotIn(str(root), stderr.getvalue())
            temporary.assert_not_called()

    def test_failed_in_place_archive_creation_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "volume.cbz"
            source_dir = root / "extracted"
            source_dir.mkdir()
            (source_dir / "page.jxl").write_bytes(b"jxl")
            output.write_bytes(b"original-archive")
            with patch.object(
                cbztojxl, "write_zip_archive", side_effect=cbztojxl.ZipArchiveError("could not create ZIP archive")
            ):
                with self.assertRaises(cbztojxl.DependencyError):
                    cbztojxl.create_cbz(output, source_dir)

            self.assertEqual(output.read_bytes(), b"original-archive")

    def test_archive_creation_stages_then_atomically_replaces_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "volume.cbz"
            source_dir = root / "extracted"
            source_dir.mkdir()
            (source_dir / "page.jxl").write_bytes(b"jxl")
            output.write_bytes(b"original-archive")

            def create_staged_archive(staged_path, _source_dir):
                self.assertEqual(staged_path.parent.parent, output.parent)
                self.assertTrue(staged_path.parent.name.startswith(".cbztojxl_stage_"))
                self.assertEqual(staged_path.parent.stat().st_mode & 0o077, 0)
                self.assertFalse(staged_path.exists())
                with zipfile.ZipFile(staged_path, "w") as archive:
                    archive.writestr("page.jxl", b"jxl")

            with patch.object(cbztojxl, "write_zip_archive", side_effect=create_staged_archive):
                cbztojxl.create_cbz(output, source_dir)

            self.assertFalse(any(root.glob(".cbztojxl_stage_*")))
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), ["page.jxl"])

    def test_archive_failure_preserves_primary_diagnostic_if_staging_cleanup_fails(self):
        real_mkdtemp = tempfile.mkdtemp
        real_rmtree = cbztojxl.shutil.rmtree
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_dir = root / "extracted"
            source_dir.mkdir()
            created_staging_dirs = []

            def record_mkdtemp(*args, **kwargs):
                path = Path(real_mkdtemp(*args, **kwargs))
                created_staging_dirs.append(path)
                return str(path)

            cleanup_error = PermissionError(
                13, "Permission denied", str(root / "private-stage")
            )
            try:
                with (
                    patch.object(
                        cbztojxl.tempfile,
                        "mkdtemp",
                        side_effect=record_mkdtemp,
                    ),
                    patch.object(cbztojxl, "write_zip_archive", side_effect=cbztojxl.ZipArchiveError("could not create ZIP archive")),
                    patch.object(
                        cbztojxl.shutil,
                        "rmtree",
                        side_effect=cleanup_error,
                    ),
                    self.assertRaisesRegex(
                        cbztojxl.DependencyError,
                        "^could not create ZIP archive; "
                        "staging cleanup also failed: Permission denied$",
                    ),
                ):
                    cbztojxl.create_cbz(root / "volume.cbz", source_dir)

                self.assertEqual(len(created_staging_dirs), 1)
                self.assertTrue(created_staging_dirs[0].exists())
            finally:
                for path in created_staging_dirs:
                    if path.exists():
                        real_rmtree(path)

    def test_leaf_symlink_failure_preserves_primary_diagnostic_if_staging_cleanup_fails(self):
        real_mkdtemp = tempfile.mkdtemp
        real_rmtree = cbztojxl.shutil.rmtree
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "volume.cbz"
            victim = root / "victim.cbz"
            victim.write_bytes(b"do-not-touch")
            source_dir = root / "extracted"
            source_dir.mkdir()
            created_staging_dirs = []

            def record_mkdtemp(*args, **kwargs):
                path = Path(real_mkdtemp(*args, **kwargs))
                created_staging_dirs.append(path)
                return str(path)

            real_write_zip_archive = cbztojxl.write_zip_archive

            def create_staged_archive_and_swap_leaf(staged_path, staged_source_dir):
                real_write_zip_archive(staged_path, staged_source_dir)
                output.symlink_to(victim)

            cleanup_error = PermissionError(
                13, "Permission denied", str(root / "private-stage")
            )
            try:
                with (
                    patch.object(
                        cbztojxl.tempfile,
                        "mkdtemp",
                        side_effect=record_mkdtemp,
                    ),
                    patch.object(cbztojxl, "write_zip_archive", side_effect=create_staged_archive_and_swap_leaf),
                    patch.object(
                        cbztojxl.shutil,
                        "rmtree",
                        side_effect=cleanup_error,
                    ),
                    self.assertRaisesRegex(
                        cbztojxl.DependencyError,
                        "^filesystem error: output path is a symbolic link; "
                        "staging cleanup also failed: Permission denied$",
                    ),
                ):
                    cbztojxl.create_cbz(output, source_dir)

                self.assertEqual(victim.read_bytes(), b"do-not-touch")
                self.assertEqual(len(created_staging_dirs), 1)
                self.assertTrue(created_staging_dirs[0].exists())
            finally:
                for path in created_staging_dirs:
                    if path.exists():
                        real_rmtree(path)

    def test_writable_directory_error_is_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "private-output" / "volume.cbz"
            source_dir = root / "extracted"
            source_dir.mkdir()
            error = PermissionError(13, "Permission denied", str(output.parent))
            with patch.object(Path, "mkdir", autospec=True, side_effect=error):
                with self.assertRaisesRegex(
                    cbztojxl.DependencyError,
                    "^filesystem error: Permission denied$",
                ) as raised:
                    cbztojxl.create_cbz(output, source_dir)

            self.assertNotIn(str(root), str(raised.exception))


class CbzToJxlStageOutputTests(unittest.TestCase):
    def setUp(self):
        self.format_config = cbztojxl.ALL_FORMATS["zip"]

    @staticmethod
    def make_page(extracted):
        page = extracted / "chapter" / "page001.jpg"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_bytes(b"jpeg")

    @classmethod
    def extract_page(cls, _archive, extracted, _format_config):
        cls.make_page(extracted)

    def run_success(self, root, verbose):
        input_root = root / "in"
        source = input_root / "series" / "volume.cbz"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"archive-data")
        output_root = root / "out"

        def create(output_path, _source_dir):
            output_path.write_bytes(b"new-cbz")

        with (
            patch.object(cbztojxl, "get_format_config", return_value=self.format_config),
            patch.object(cbztojxl, "count_jpegs_in_archive", return_value=1),
            patch.object(cbztojxl, "extract_archive", side_effect=self.extract_page),
            patch.object(cbztojxl, "create_cbz", side_effect=create),
            patch("subprocess.run"),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            result = cbztojxl.process_archive(
                source,
                input_root,
                output_root,
                overwrite=True,
                verbose=verbose,
                dry_run=False,
                file_index=1,
                total_files=1,
            )
        return result, stdout.getvalue()

    def test_process_archive_verbose_is_additive(self):
        with tempfile.TemporaryDirectory() as normal_directory:
            normal_result, normal = self.run_success(Path(normal_directory), False)
        with tempfile.TemporaryDirectory() as verbose_directory:
            verbose_result, verbose = self.run_success(Path(verbose_directory), True)

        self.assertEqual(normal_result, (12, 7, "processed"))
        self.assertEqual(verbose_result, normal_result)
        done = (
            "[done]  series/volume.cbz => series/volume.cbz | 1 page | "
            "12 B => 7 B (41.7% smaller)"
        )
        self.assertIn(done, normal)
        self.assertIn(done, verbose)
        for detail in ("Extracting to:", "Converting page", "Creating:"):
            self.assertNotIn(detail, normal)
            self.assertIn(detail, verbose)
        self.assertIn("Converting page 1/1: chapter/page001.jpg", verbose)
        self.assertIn("Creating: series/volume.cbz", verbose)
        self.assertRegex(
            verbose,
            r"  Extracting to: series/\.cbztojxl_tmp_[^\n]+\n",
        )
        self.assertNotIn(str(Path(verbose_directory).resolve()), verbose)
        self.assertNotIn("Converting JPEGs to JXL", verbose)

    def run_progress_failure(self, root, stage):
        input_root = root / "in"
        source = input_root / "series" / "volume.cbz"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"archive-data")
        output_root = root / "out"
        error = subprocess.CalledProcessError(
            1, ["cjxl"], stderr=b"could not decode JPEG input\n"
        )

        def extract_pages(_archive, extracted, _format_config):
            for page_name in ("page001.jpg", "page002.jpg"):
                page = extracted / "chapter" / page_name
                page.parent.mkdir(parents=True, exist_ok=True)
                page.write_bytes(b"jpeg")

        def convert(extracted, on_progress, **_kwargs):
            on_progress(1)
            if stage == "convert":
                return [(2, extracted / "chapter" / "page002.jpg", error)]
            return []

        create_error = cbztojxl.DependencyError(
            "zip exited with status 15: could not create output file"
        )
        events = []
        stdout = RecordingStream("stdout", events)
        stderr = RecordingStream("stderr", events)
        with (
            patch.object(cbztojxl, "get_format_config", return_value=self.format_config),
            patch.object(cbztojxl, "count_jpegs_in_archive", return_value=2),
            patch.object(cbztojxl, "extract_archive", side_effect=extract_pages),
            patch.object(cbztojxl, "convert_jpegs_to_jxl", side_effect=convert),
            patch.object(
                cbztojxl,
                "create_cbz",
                side_effect=create_error if stage == "create" else None,
            ),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            result = cbztojxl.process_archive(
                source,
                input_root,
                output_root,
                overwrite=True,
                verbose=False,
                dry_run=False,
                file_index=1,
                total_files=1,
                show_progress_bar=True,
            )
        return result, stdout, stderr, events

    def assert_progress_is_cleared_before_error(self, stderr, events):
        error_index = next(
            index
            for index, event in enumerate(events)
            if event[0] == "stderr" and "[error]" in event[2]
        )
        prior_events = events[:error_index]
        clear_writes = [
            event
            for event in prior_events
            if event[0:2] == ("stdout", "write")
            and event[2].startswith("\r")
            and event[2].endswith("\r")
        ]
        self.assertTrue(clear_writes)
        self.assertEqual(prior_events[-1], ("stdout", "flush", ""))
        self.assertTrue(stderr.getvalue().startswith("[error]"))
        self.assertIn(("stderr", "flush", ""), events[error_index:])

    def test_conversion_error_clears_live_progress_first(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _stdout, stderr, events = self.run_progress_failure(
                Path(directory), "convert"
            )
        self.assertEqual(result[2], "error_convert")
        self.assert_progress_is_cleared_before_error(stderr, events)

    def test_creation_error_clears_live_progress_first(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _stdout, stderr, events = self.run_progress_failure(
                Path(directory), "create"
            )
        self.assertEqual(result[2], "error_create")
        self.assert_progress_is_cleared_before_error(stderr, events)

    def test_extract_archive_captures_concise_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "volume.cbz"
            archive.write_bytes(b"not a zip")
            with self.assertRaisesRegex(
                cbztojxl.DependencyError,
                "^ZIP archive is invalid or uses unsupported features$",
            ):
                cbztojxl.extract_archive(
                    archive,
                    Path(directory) / "extracted",
                    self.format_config,
                )

    def test_create_cbz_captures_concise_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                cbztojxl, "write_zip_archive", side_effect=cbztojxl.ZipArchiveError("could not create ZIP archive")
            ):
                with self.assertRaisesRegex(
                    cbztojxl.DependencyError,
                    "^could not create ZIP archive$",
                ):
                    cbztojxl.create_cbz(root / "volume.cbz", root)

    def test_conversion_failure_keeps_page_index(self):
        error = subprocess.CalledProcessError(
            1, ["cjxl", "/private/page.jpg"], stderr=b"decode failed\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            extracted = Path(directory)
            self.make_page(extracted)
            page = extracted / "chapter" / "page001.jpg"
            with patch("subprocess.run", side_effect=error):
                failures = cbztojxl.convert_jpegs_to_jxl(extracted)
        self.assertEqual(failures, [(1, page, error)])

    def test_conversion_orders_jpegs_by_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            extracted = Path(directory)
            (extracted / "chapter").mkdir()
            (extracted / "z.jpg").write_bytes(b"jpeg")
            (extracted / "chapter" / "a.jpg").write_bytes(b"jpeg")
            converted = []

            def convert(command, **_kwargs):
                converted.append(Path(command[3]).relative_to(extracted).as_posix())

            with patch.object(cbztojxl.subprocess, "run", side_effect=convert):
                failures = cbztojxl.convert_jpegs_to_jxl(extracted)

        self.assertEqual(failures, [])
        self.assertEqual(converted, ["chapter/a.jpg", "z.jpg"])

    def test_native_cbz_writer_orders_entries_without_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "pages"
            source.mkdir()
            (source / "z.jxl").write_bytes(b"z")
            nested = source / "chapter"
            nested.mkdir()
            (nested / "a.jxl").write_bytes(b"a")
            output = root / "comic.cbz"

            with patch.object(cbztojxl.subprocess, "run", side_effect=AssertionError):
                cbztojxl.create_cbz(output, source)

            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()

        self.assertEqual(names, ["chapter/", "chapter/a.jxl", "z.jxl"])

    def test_process_archive_reports_each_stage_error_without_command_arguments(self):
        cases = (
            (
                "extract",
                cbztojxl.DependencyError("unzip exited with status 9: corrupt archive"),
                "[error] series/volume.cbz | extract archive failed\n"
                "        unzip exited with status 9: corrupt archive\n",
            ),
            (
                "convert",
                subprocess.CalledProcessError(
                    1,
                    ["cjxl", "--secret-option", "/private/chapter/page001.jpg"],
                    stderr=b"could not decode JPEG input\n",
                ),
                "[error] series/volume.cbz | convert page 1/1: "
                "chapter/page001.jpg failed\n"
                "        cjxl exited with status 1: could not decode JPEG input\n",
            ),
            (
                "create",
                cbztojxl.DependencyError(
                    "zip exited with status 15: could not create output file"
                ),
                "[error] series/volume.cbz => series/volume.cbz | create archive failed\n"
                "        zip exited with status 15: could not create output file\n",
            ),
        )
        real_mkdtemp = tempfile.mkdtemp
        for stage, error, expected in cases:
            for verbose in (False, True):
                with (
                    self.subTest(stage=stage, verbose=verbose),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    input_root = root / "in"
                    source = input_root / "series" / "volume.cbz"
                    source.parent.mkdir(parents=True)
                    source.write_bytes(b"archive-data")
                    output_root = root / "out"
                    created_temporaries = []

                    extract_side_effect = (
                        error if stage == "extract" else self.extract_page
                    )

                    def convert(extracted, **_kwargs):
                        if stage == "convert":
                            return [(1, extracted / "chapter" / "page001.jpg", error)]
                        return []

                    def record_mkdtemp(*args, **kwargs):
                        path = Path(real_mkdtemp(*args, **kwargs))
                        created_temporaries.append(path)
                        return str(path)

                    create_side_effect = error if stage == "create" else None
                    with (
                        patch.object(
                            cbztojxl, "get_format_config", return_value=self.format_config
                        ),
                        patch.object(
                            cbztojxl, "count_jpegs_in_archive", return_value=1
                        ),
                        patch.object(
                            cbztojxl,
                            "extract_archive",
                            side_effect=extract_side_effect,
                        ),
                        patch.object(
                            cbztojxl, "convert_jpegs_to_jxl", side_effect=convert
                        ),
                        patch.object(
                            cbztojxl, "create_cbz", side_effect=create_side_effect
                        ),
                        patch.object(
                            cbztojxl.tempfile,
                            "mkdtemp",
                            side_effect=record_mkdtemp,
                        ),
                        patch("sys.stdout", new_callable=io.StringIO),
                        patch("sys.stderr", new_callable=io.StringIO) as stderr,
                    ):
                        result = cbztojxl.process_archive(
                            source, input_root, output_root, True, verbose, False
                        )
                    self.assertEqual(result[2], f"error_{stage}")
                    self.assertEqual(stderr.getvalue(), expected)
                    self.assertNotIn("--secret-option", stderr.getvalue())
                    self.assertNotIn("/private", stderr.getvalue())
                    self.assertTrue(created_temporaries)
                    self.assertTrue(
                        all(not path.exists() for path in created_temporaries)
                    )

    def test_multiple_page_failures_emit_one_archive_outcome(self):
        error = subprocess.CalledProcessError(
            1, ["cjxl"], stderr=b"decode failed\n"
        )
        for verbose in (False, True):
            with self.subTest(verbose=verbose), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                input_root = root / "in"
                source = input_root / "volume.cbz"
                source.parent.mkdir()
                source.write_bytes(b"archive-data")

                def extract_pages(_archive, extracted, _format_config):
                    for name in ("one.jpg", "two.jpg"):
                        (extracted / name).write_bytes(b"jpeg")

                def fail_pages(extracted, **_kwargs):
                    return [
                        (1, extracted / "one.jpg", error),
                        (2, extracted / "two.jpg", error),
                    ]

                with (
                    patch.object(
                        cbztojxl, "get_format_config", return_value=self.format_config
                    ),
                    patch.object(cbztojxl, "count_jpegs_in_archive", return_value=2),
                    patch.object(cbztojxl, "extract_archive", side_effect=extract_pages),
                    patch.object(
                        cbztojxl, "convert_jpegs_to_jxl", side_effect=fail_pages
                    ),
                    patch("sys.stdout", new_callable=io.StringIO),
                    patch("sys.stderr", new_callable=io.StringIO) as stderr,
                ):
                    result = cbztojxl.process_archive(
                        source, input_root, root / "out", True, verbose, False
                    )

                self.assertEqual(result[2], "error_convert")
                self.assertEqual(stderr.getvalue().count("[error]"), 1)
                self.assertIn("convert page 1/2: one.jpg failed", stderr.getvalue())
                self.assertNotIn("two.jpg", stderr.getvalue())

    def test_workspace_creation_oserror_is_an_extract_error_in_both_modes(self):
        for operation in ("mkdir", "mkdtemp"):
            for verbose in (False, True):
                with (
                    self.subTest(operation=operation, verbose=verbose),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    input_root = root / "in"
                    source = input_root / "volume.cbz"
                    source.parent.mkdir()
                    source.write_bytes(b"archive-data")
                    error = PermissionError(
                        13, "Permission denied", str(root / "private-workspace")
                    )
                    setup_failure = (
                        patch.object(
                            Path, "mkdir", autospec=True, side_effect=error
                        )
                        if operation == "mkdir"
                        else patch.object(
                            cbztojxl.tempfile, "mkdtemp", side_effect=error
                        )
                    )
                    with (
                        patch.object(
                            cbztojxl,
                            "get_format_config",
                            return_value=self.format_config,
                        ),
                        patch.object(
                            cbztojxl, "count_jpegs_in_archive", return_value=1
                        ),
                        setup_failure,
                        patch("sys.stdout", new_callable=io.StringIO) as stdout,
                        patch("sys.stderr", new_callable=io.StringIO) as stderr,
                    ):
                        result = cbztojxl.process_archive(
                            source, input_root, root / "out", True, verbose, False
                        )

                    self.assertEqual(result[2], "error_extract")
                    self.assertEqual(
                        stderr.getvalue(),
                        "[error] volume.cbz | extract archive failed\n"
                        "        filesystem error: Permission denied\n",
                    )
                    self.assertNotIn(
                        str(root), stdout.getvalue() + stderr.getvalue()
                    )

    def test_conversion_filesystem_errors_are_normalized_and_cleanup_temp(self):
        real_mkdtemp = tempfile.mkdtemp
        cases = ("create-jxl", "unlink-jpeg")
        for operation in cases:
            for verbose in (False, True):
                with (
                    self.subTest(operation=operation, verbose=verbose),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    input_root = root / "in"
                    source = input_root / "volume.cbz"
                    source.parent.mkdir()
                    source.write_bytes(b"archive-data")
                    created_temporaries = []
                    error = PermissionError(
                        13, "Permission denied", str(root / "private-page.jpg")
                    )

                    def record_mkdtemp(*args, **kwargs):
                        path = Path(real_mkdtemp(*args, **kwargs))
                        created_temporaries.append(path)
                        return str(path)

                    run_effect = error if operation == "create-jxl" else None
                    unlink_effect = error if operation == "unlink-jpeg" else None
                    with (
                        patch.object(
                            cbztojxl, "get_format_config", return_value=self.format_config
                        ),
                        patch.object(
                            cbztojxl, "count_jpegs_in_archive", return_value=1
                        ),
                        patch.object(
                            cbztojxl, "extract_archive", side_effect=self.extract_page
                        ),
                        patch.object(
                            cbztojxl.tempfile,
                            "mkdtemp",
                            side_effect=record_mkdtemp,
                        ),
                        patch("subprocess.run", side_effect=run_effect),
                        patch.object(
                            Path,
                            "unlink",
                            autospec=True,
                            side_effect=unlink_effect,
                        ) if unlink_effect else nullcontext(),
                        patch("sys.stdout", new_callable=io.StringIO),
                        patch("sys.stderr", new_callable=io.StringIO) as stderr,
                    ):
                        result = cbztojxl.process_archive(
                            source, input_root, root / "out", True, verbose, False
                        )

                    self.assertEqual(result[2], "error_convert")
                    self.assertEqual(
                        stderr.getvalue(),
                        "[error] volume.cbz | convert page 1/1: "
                        "chapter/page001.jpg failed\n"
                        "        filesystem error: Permission denied\n",
                    )
                    self.assertTrue(created_temporaries)
                    self.assertTrue(
                        all(not path.exists() for path in created_temporaries)
                    )

    def test_creation_oserrors_are_normalized_and_cleanup_temp(self):
        real_mkdtemp = tempfile.mkdtemp
        for operation in ("write", "stat"):
            for verbose in (False, True):
                with (
                    self.subTest(operation=operation, verbose=verbose),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    input_root = root / "in"
                    source = input_root / "volume.cbz"
                    source.parent.mkdir()
                    source.write_bytes(b"archive-data")
                    created_temporaries = []

                    def record_mkdtemp(*args, **kwargs):
                        path = Path(real_mkdtemp(*args, **kwargs))
                        created_temporaries.append(path)
                        return str(path)

                    create_effect = (
                        PermissionError(
                            13,
                            "Permission denied",
                            str(root / "private-output.cbz"),
                        )
                        if operation == "write"
                        else None
                    )
                    with (
                        patch.object(
                            cbztojxl, "get_format_config", return_value=self.format_config
                        ),
                        patch.object(
                            cbztojxl, "count_jpegs_in_archive", return_value=1
                        ),
                        patch.object(
                            cbztojxl, "extract_archive", side_effect=self.extract_page
                        ),
                        patch.object(cbztojxl, "convert_jpegs_to_jxl", return_value=[]),
                        patch.object(
                            cbztojxl, "create_cbz", side_effect=create_effect
                        ),
                        patch.object(
                            cbztojxl.tempfile,
                            "mkdtemp",
                            side_effect=record_mkdtemp,
                        ),
                        patch("sys.stdout", new_callable=io.StringIO),
                        patch("sys.stderr", new_callable=io.StringIO) as stderr,
                    ):
                        result = cbztojxl.process_archive(
                            source, input_root, root / "out", True, verbose, False
                        )

                    expected_detail = (
                        "Permission denied"
                        if operation == "write"
                        else "No such file or directory"
                    )
                    self.assertEqual(result[2], "error_create")
                    self.assertEqual(
                        stderr.getvalue(),
                        "[error] volume.cbz => volume.cbz | create archive failed\n"
                        f"        filesystem error: {expected_detail}\n",
                    )
                    self.assertTrue(created_temporaries)
                    self.assertTrue(
                        all(not path.exists() for path in created_temporaries)
                    )

    def test_cleanup_failure_is_reported_without_done_result(self):
        real_mkdtemp = tempfile.mkdtemp
        real_rmtree = cbztojxl.shutil.rmtree
        for verbose in (False, True):
            with self.subTest(verbose=verbose), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                input_root = root / "in"
                source = input_root / "volume.cbz"
                source.parent.mkdir()
                source.write_bytes(b"archive-data")
                created_temporaries = []

                def record_mkdtemp(*args, **kwargs):
                    path = Path(real_mkdtemp(*args, **kwargs))
                    created_temporaries.append(path)
                    return str(path)

                def create(output, _source_dir):
                    output.write_bytes(b"new-cbz")

                cleanup_error = PermissionError(
                    13, "Permission denied", str(root / "private-workspace")
                )
                try:
                    with (
                        patch.object(
                            cbztojxl, "get_format_config", return_value=self.format_config
                        ),
                        patch.object(
                            cbztojxl, "count_jpegs_in_archive", return_value=1
                        ),
                        patch.object(
                            cbztojxl, "extract_archive", side_effect=self.extract_page
                        ),
                        patch.object(cbztojxl, "convert_jpegs_to_jxl", return_value=[]),
                        patch.object(cbztojxl, "create_cbz", side_effect=create),
                        patch.object(
                            cbztojxl.tempfile,
                            "mkdtemp",
                            side_effect=record_mkdtemp,
                        ),
                        patch.object(
                            cbztojxl.shutil, "rmtree", side_effect=cleanup_error
                        ),
                        patch("sys.stdout", new_callable=io.StringIO) as stdout,
                        patch("sys.stderr", new_callable=io.StringIO) as stderr,
                    ):
                        result = cbztojxl.process_archive(
                            source, input_root, root / "out", True, verbose, False
                        )

                    self.assertEqual(result[2], "error_cleanup")
                    self.assertNotIn("[done]", stdout.getvalue())
                    self.assertEqual(
                        stderr.getvalue(),
                        "[error] volume.cbz | cleanup workspace failed\n"
                        "        filesystem error: Permission denied\n",
                    )
                    self.assertTrue(created_temporaries[0].exists())
                finally:
                    for path in created_temporaries:
                        if path.exists():
                            real_rmtree(path)

    def test_cleanup_failure_preserves_prior_stage_diagnostic(self):
        real_rmtree = cbztojxl.shutil.rmtree
        conversion_error = subprocess.CalledProcessError(
            1, ["cjxl", "/private/page.jpg"], stderr=b"decode failed\n"
        )
        for verbose in (False, True):
            with self.subTest(verbose=verbose), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                input_root = root / "in"
                source = input_root / "volume.cbz"
                source.parent.mkdir()
                source.write_bytes(b"archive-data")
                created_temporaries = []

                def fail_conversion(extracted, **_kwargs):
                    return [
                        (1, extracted / "chapter" / "page001.jpg", conversion_error)
                    ]

                def record_workspace(_parent):
                    class Workspace:
                        def __enter__(self_inner):
                            path = root / "out" / ".cbztojxl_tmp_test"
                            path.mkdir(parents=True)
                            created_temporaries.append(path)
                            return path

                        def __exit__(self_inner, *_args):
                            raise cbztojxl.WorkspaceCleanupError(
                                PermissionError(
                                    13, "Permission denied", str(created_temporaries[0])
                                )
                            )

                    return Workspace()

                try:
                    with (
                        patch.object(
                            cbztojxl,
                            "get_format_config",
                            return_value=self.format_config,
                        ),
                        patch.object(
                            cbztojxl, "count_jpegs_in_archive", return_value=1
                        ),
                        patch.object(
                            cbztojxl, "extract_archive", side_effect=self.extract_page
                        ),
                        patch.object(
                            cbztojxl,
                            "convert_jpegs_to_jxl",
                            side_effect=fail_conversion,
                        ),
                        patch.object(cbztojxl, "temp_dir", side_effect=record_workspace),
                        patch("sys.stdout", new_callable=io.StringIO),
                        patch("sys.stderr", new_callable=io.StringIO) as stderr,
                    ):
                        result = cbztojxl.process_archive(
                            source, input_root, root / "out", True, verbose, False
                        )

                    self.assertEqual(result[2], "error_convert")
                    self.assertEqual(stderr.getvalue().count("[error]"), 1)
                    self.assertEqual(
                        stderr.getvalue(),
                        "[error] volume.cbz | convert page 1/1: "
                        "chapter/page001.jpg failed\n"
                        "        cjxl exited with status 1: decode failed; "
                        "cleanup also failed: Permission denied\n",
                    )
                finally:
                    for path in created_temporaries:
                        if path.exists():
                            real_rmtree(path)

    def test_cleanup_finishes_before_done_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "in"
            source = input_root / "volume.cbz"
            source.parent.mkdir()
            source.write_bytes(b"archive-data")
            events = []
            real_report = cbztojxl.report_processed
            real_rmtree = cbztojxl.shutil.rmtree

            def create(output, _source_dir):
                output.write_bytes(b"new-cbz")

            def remove(path, *args, **kwargs):
                events.append("cleanup")
                return real_rmtree(path, *args, **kwargs)

            def report(*args, **kwargs):
                events.append("done")
                return real_report(*args, **kwargs)

            with (
                patch.object(cbztojxl, "get_format_config", return_value=self.format_config),
                patch.object(cbztojxl, "count_jpegs_in_archive", return_value=1),
                patch.object(cbztojxl, "extract_archive", side_effect=self.extract_page),
                patch.object(cbztojxl, "convert_jpegs_to_jxl", return_value=[]),
                patch.object(cbztojxl, "create_cbz", side_effect=create),
                patch.object(cbztojxl.shutil, "rmtree", side_effect=remove),
                patch.object(cbztojxl, "report_processed", side_effect=report),
                patch("sys.stdout", new_callable=io.StringIO),
            ):
                result = cbztojxl.process_archive(
                    source, input_root, root / "out", True, False, False
                )

        self.assertEqual(result[2], "processed")
        self.assertEqual(events, ["cleanup", "done"])

    def test_skip_lines_are_compact_in_verbose_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "in"
            source = input_root / "series" / "volume.cbz"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"archive-data")
            output_root = root / "out"

            cases = (
                (None, 1, False, "[skip]  series/volume.cbz | archiver not available"),
                (self.format_config, 0, False, "[skip]  series/volume.cbz | no JPEG pages"),
                (
                    self.format_config,
                    1,
                    True,
                    "[skip]  series/volume.cbz => series/volume.cbz | output already exists",
                ),
            )
            for config, jpeg_count, output_exists, expected in cases:
                with self.subTest(expected=expected):
                    output = output_root / "series" / "volume.cbz"
                    if output_exists:
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(b"existing")
                    elif output.exists():
                        output.unlink()
                    with (
                        patch.object(cbztojxl, "get_format_config", return_value=config),
                        patch.object(
                            cbztojxl, "count_jpegs_in_archive", return_value=jpeg_count
                        ),
                        patch("sys.stdout", new_callable=io.StringIO) as stdout,
                    ):
                        cbztojxl.process_archive(
                            source, input_root, output_root, False, True, False
                        )
                    self.assertEqual(stdout.getvalue().strip(), expected)


class CbzToJxlMainOutputTests(unittest.TestCase):
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
            patch.object(
                cbztojxl,
                "find_archive_files",
                return_value=[first, second, distinct],
            ),
            patch.object(
                cbztojxl, "process_archive", return_value=(10, 5, "processed")
            ) as process,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
            self.assertRaises(SystemExit) as raised,
        ):
            cbztojxl.main()

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(process.call_args_list[0].kwargs["input_path"], distinct)
        self.assertEqual(process.call_count, 1)
        self.assertIn(
            "[skip]  book.cbz => book.cbz | output path collides with another input",
            stdout.getvalue(),
        )
        self.assertIn(
            "[skip]  book.cbr => book.cbz | output path collides with another input",
            stdout.getvalue(),
        )
        self.assertIn(
            "[total] 3 archives | 1 done, 2 skipped, 0 failed | "
            "10 B => 5 B (50.0% smaller)",
            stdout.getvalue(),
        )

    def test_total_and_failure_exit_are_mode_independent(self):
        archive_files = [Path(f"comic-{index}.cbz") for index in range(4)]
        results = [
            (100, 75, "processed"),
            (50, 40, "processed"),
            (20, 0, "skipped_exists"),
            (30, 0, "error_convert"),
        ]
        expected = (
            "[total] 4 archives | 2 done, 1 skipped, 1 failed | "
            "150 B => 115 B (23.3% smaller)"
        )
        outcomes = [
            "[done]  comic-0.cbz => comic-0_jxl.cbz | 1 page | "
            "100 B => 75 B (25.0% smaller)",
            "[done]  comic-1.cbz => comic-1_jxl.cbz | 1 page | "
            "50 B => 40 B (20.0% smaller)",
            "[skip]  comic-2.cbz => comic-2_jxl.cbz | output already exists",
            "[error] comic-3.cbz | extract archive failed\n"
            "        unzip exited with status 9: corrupt archive",
        ]

        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                args = Namespace(
                    input=Path("comics"),
                    output_dir=None,
                    recursive=False,
                    overwrite=False,
                    verbose=verbose,
                    dry_run=False,
                )
                transcript = io.StringIO()

                def process(**kwargs):
                    index = kwargs["file_index"] - 1
                    stream = sys.stderr if index == 3 else sys.stdout
                    print(outcomes[index], file=stream)
                    return results[index]

                with (
                    patch.object(cbztojxl, "parse_args", return_value=args),
                    patch.object(cbztojxl, "check_dependencies"),
                    patch.object(
                        cbztojxl, "find_archive_files", return_value=archive_files
                    ),
                    patch.object(cbztojxl, "process_archive", side_effect=process),
                    patch("sys.stdout", transcript),
                    patch("sys.stderr", transcript),
                    self.assertRaises(SystemExit) as raised,
                ):
                    cbztojxl.main()

                expected_transcript = (
                    ("Found 4 archive file(s) to process\n" if verbose else "")
                    + "\n".join(outcomes)
                    + f"\n\n{expected}\n"
                )
                self.assertEqual(transcript.getvalue(), expected_transcript)
                self.assertNotIn("\n\n[done]", transcript.getvalue())
                self.assertNotIn("\n\n[skip]", transcript.getvalue())
                self.assertNotIn("\n\n[error]", transcript.getvalue())
                self.assertNotIn("Failed to process", transcript.getvalue())
                self.assertEqual(raised.exception.code, cbztojxl.EXIT_CONVERSION_ERROR)

    def test_workspace_failure_still_prints_total_and_exits_conversion_error(self):
        for verbose in (False, True):
            with self.subTest(verbose=verbose), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "volume.cbz"
                source.write_bytes(b"archive-data")
                args = Namespace(
                    input=source,
                    output_dir=root / "out",
                    recursive=False,
                    overwrite=True,
                    verbose=verbose,
                    dry_run=False,
                )
                error = PermissionError(
                    13, "Permission denied", str(root / "private-workspace")
                )
                with (
                    patch.object(cbztojxl, "parse_args", return_value=args),
                    patch.object(cbztojxl, "check_dependencies"),
                    patch.object(
                        cbztojxl, "find_archive_files", return_value=[source]
                    ),
                    patch.object(
                        cbztojxl,
                        "get_format_config",
                        return_value=cbztojxl.ALL_FORMATS["zip"],
                    ),
                    patch.object(cbztojxl, "count_jpegs_in_archive", return_value=1),
                    patch.object(cbztojxl.tempfile, "mkdtemp", side_effect=error),
                    patch("sys.stdout", new_callable=io.StringIO) as stdout,
                    patch("sys.stderr", new_callable=io.StringIO) as stderr,
                    self.assertRaises(SystemExit) as raised,
                ):
                    cbztojxl.main()

                prefix = (
                    "Found 1 archive file(s) to process\nvolume.cbz\n"
                    if verbose
                    else ""
                )
                self.assertEqual(
                    stdout.getvalue(),
                    prefix
                    + "\n[total] 1 archives | 0 done, 0 skipped, 1 failed\n",
                )
                self.assertEqual(
                    stderr.getvalue(),
                    "[error] volume.cbz | extract archive failed\n"
                    "        filesystem error: Permission denied\n",
                )
                self.assertEqual(
                    raised.exception.code, cbztojxl.EXIT_CONVERSION_ERROR
                )
