"""Safe, deterministic helpers for ZIP-based comic archives."""

from __future__ import annotations

import os
import re
import shutil
import stat
import time
import zipfile
from pathlib import Path, PurePosixPath


class ZipArchiveError(Exception):
    """Raised when a ZIP archive cannot be safely read or written."""


def relative_path_key(path: Path, root: Path) -> str:
    """Return a stable archive-relative sort key using POSIX separators."""
    return path.relative_to(root).as_posix()


def sorted_archive_entries(root: Path) -> list[Path]:
    """Return every source entry in stable archive-member order."""
    return sorted(root.rglob("*"), key=lambda path: relative_path_key(path, root))


def _validated_member_path(info: zipfile.ZipInfo, output_dir: Path) -> Path:
    """Return a safe output path for one ZIP member or raise ZipArchiveError."""
    name = info.filename
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:", name)
    ):
        raise ZipArchiveError("ZIP archive contains an unsafe member path")
    parts = PurePosixPath(name).parts
    if not parts or any(part == ".." for part in parts):
        raise ZipArchiveError("ZIP archive contains an unsafe member path")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise ZipArchiveError("ZIP archive contains a symbolic-link member")
    destination = output_dir.joinpath(*parts)
    try:
        destination.resolve(strict=False).relative_to(output_dir.resolve())
    except (OSError, RuntimeError, ValueError) as error:
        raise ZipArchiveError("ZIP archive contains an unsafe member path") from error
    return destination


def _restore_member_mtime(path: Path, info: zipfile.ZipInfo) -> None:
    """Restore a ZIP member's modification time on an extracted path."""
    timestamp = time.mktime((*info.date_time, 0, 0, -1))
    os.utime(path, (timestamp, timestamp))


def extract_zip_archive(archive_path: Path, output_dir: Path) -> None:
    """Safely extract a ZIP archive without invoking external utilities."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            destinations = [
                (member, _validated_member_path(member, output_dir))
                for member in members
            ]
            directory_members = []
            for member, destination in destinations:
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    directory_members.append((member, destination))
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                _restore_member_mtime(destination, member)
            for member, destination in sorted(
                directory_members,
                key=lambda item: len(item[1].parts),
                reverse=True,
            ):
                _restore_member_mtime(destination, member)
    except ZipArchiveError:
        raise
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as error:
        raise ZipArchiveError("ZIP archive is invalid or uses unsupported features") from error


def count_zip_jpegs(archive_path: Path, is_jpeg) -> int:
    """Count JPEG file members in a ZIP archive."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            return sum(
                not member.is_dir() and is_jpeg(Path(member.filename))
                for member in archive.infolist()
            )
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as error:
        raise ZipArchiveError("ZIP archive is invalid or uses unsupported features") from error


def write_zip_archive(output_path: Path, source_dir: Path) -> None:
    """Write source entries to a CBZ/ZIP in stable order with normal metadata."""
    try:
        with zipfile.ZipFile(
            output_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for entry in sorted_archive_entries(source_dir):
                archive.write(entry, relative_path_key(entry, source_dir))
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as error:
        raise ZipArchiveError("could not create ZIP archive") from error
