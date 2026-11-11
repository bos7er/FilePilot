"""Filesystem scanning and duplicate detection.

No file is modified by these functions. All traversal stays on the selected
filesystem tree and does not follow symbolic links or Windows junctions.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import threading
import time
from typing import Callable


class ScanCancelled(Exception):
    """Raised when the user cancels a running scan."""


Progress = Callable[[int, int], None]


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    modified_ns: int
    device: int = 0
    inode: int = 0


@dataclass(frozen=True)
class FolderRecord:
    path: str
    size: int
    files: int


@dataclass(frozen=True)
class ScanResult:
    root: str
    files: tuple[FileRecord, ...]
    folders: tuple[FolderRecord, ...]
    skipped: int
    elapsed: float

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)


@dataclass(frozen=True)
class DuplicateGroup:
    size: int
    digest: str
    files: tuple[FileRecord, ...]

    @property
    def potential_savings(self) -> int:
        return (len(self.files) - 1) * self.size


def format_bytes(size: int) -> str:
    size_f = float(max(size, 0))
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size_f < 1024 or unit == "PB":
            return f"{size_f:,.0f} B" if unit == "B" else f"{size_f:,.2f} {unit}"
        size_f /= 1024
    raise AssertionError("unreachable")


def _is_link_or_junction(entry: os.DirEntry[str] | Path) -> bool:
    try:
        if entry.is_symlink():
            return True
        isjunction = getattr(os.path, "isjunction", None)
        return bool(isjunction and isjunction(os.fspath(entry)))
    except OSError:
        return True


def scan_directory(
    root: str,
    cancel: threading.Event | None = None,
    progress: Progress | None = None,
) -> ScanResult:
    """Scan files under root, without following links. Reports unreadable entries.

    The scan records file metadata only; it does not read file contents.
    """
    cancel = cancel or threading.Event()
    target = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(target) or _is_link_or_junction(Path(target)):
        raise ValueError("Choose an existing, non-linked folder.")
    files: list[FileRecord] = []
    folder_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    stack = [target]
    skipped = 0
    total_size = 0
    start = time.monotonic()
    last_progress = start

    while stack:
        if cancel.is_set():
            raise ScanCancelled()
        current = stack.pop()
        folder_totals[current]  # Include empty folders in the folder count.
        try:
            with os.scandir(current) as iterator:
                entries = list(iterator)
        except (OSError, PermissionError):
            skipped += 1
            continue
        for entry in entries:
            if cancel.is_set():
                raise ScanCancelled()
            try:
                if _is_link_or_junction(entry):
                    skipped += 1
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    info = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        continue
                    files.append(FileRecord(
                        entry.path, info.st_size, info.st_mtime_ns,
                        info.st_dev, info.st_ino,
                    ))
                    total_size += info.st_size
                    parent = current
                    while True:
                        counts = folder_totals[parent]
                        counts[0] += info.st_size
                        counts[1] += 1
                        if parent == target:
                            break
                        next_parent = os.path.dirname(parent)
                        if next_parent == parent:
                            break
                        parent = next_parent
                else:
                    skipped += 1
            except (OSError, PermissionError):
                skipped += 1
            now = time.monotonic()
            if progress and now - last_progress >= .22:
                progress(len(files), total_size)
                last_progress = now

    if progress:
        progress(len(files), total_size)
    folders = tuple(
        FolderRecord(path, sizes[0], sizes[1])
        for path, sizes in folder_totals.items() if path != target
    )
    return ScanResult(target, tuple(files), folders, skipped, time.monotonic() - start)


def _hash_file(rec: FileRecord, cancel: threading.Event) -> str | None:
    if cancel.is_set():
        raise ScanCancelled()
    try:
        if _is_link_or_junction(Path(rec.path)):
            return None
        before = os.stat(rec.path, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_size != rec.size
                or before.st_mtime_ns != rec.modified_ns):
            return None
        hasher = hashlib.sha256()
        with open(rec.path, "rb") as stream:
            while block := stream.read(1024 * 1024):
                if cancel.is_set():
                    raise ScanCancelled()
                hasher.update(block)
        after = os.stat(rec.path, follow_symlinks=False)
        if (after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns):
            return None
        return hasher.hexdigest()
    except (PermissionError, OSError):
        return None


def find_duplicates(
    files: tuple[FileRecord, ...] | list[FileRecord],
    cancel: threading.Event | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[DuplicateGroup, ...]:
    """Return verified full-SHA256 duplicates, never trusting filenames.

    Files of unique size are not read. Multiple paths to the same inode are
    collapsed, as hard links do not consume a second copy of the same bytes.
    """
    cancel = cancel or threading.Event()
    by_size: dict[int, list[FileRecord]] = defaultdict(list)
    for rec in files:
        by_size[rec.size].append(rec)
    candidate_sizes = [(size, members) for size, members in by_size.items() if len(members) > 1]
    to_hash = sum(len(members) for _, members in candidate_sizes)
    checked = 0
    result: list[DuplicateGroup] = []
    for size, members in candidate_sizes:
        hashes: dict[str, list[FileRecord]] = defaultdict(list)
        for rec in members:
            if cancel.is_set():
                raise ScanCancelled()
            digest = _hash_file(rec, cancel)
            if digest is not None:
                hashes[digest].append(rec)
            checked += 1
            if progress and (checked % 8 == 0 or checked == to_hash):
                progress(checked, to_hash)
        for digest, matches in hashes.items():
            unique: list[FileRecord] = []
            seen_inodes: set[tuple[int, int]] = set()
            for rec in sorted(matches, key=lambda f: f.path.casefold()):
                # On Windows, os.DirEntry.stat() can return st_ino=0.
                # os.stat(path) retrieves the real file identity, so hard links
                # are not incorrectly listed as separate duplicate copies.
                identity = (rec.device, rec.inode) if rec.inode else None
                if identity is None:
                    try:
                        current = os.stat(rec.path, follow_symlinks=False)
                        if (current.st_ino and current.st_size == rec.size
                                and current.st_mtime_ns == rec.modified_ns):
                            identity = (current.st_dev, current.st_ino)
                    except OSError:
                        pass
                if identity is not None and identity in seen_inodes:
                    continue
                if identity is not None:
                    seen_inodes.add(identity)
                unique.append(rec)
            if len(unique) > 1:
                result.append(DuplicateGroup(size, digest, tuple(unique)))
    result.sort(key=lambda group: group.potential_savings, reverse=True)
    if progress:
        progress(to_hash, to_hash)
    return tuple(result)


def is_under_directory(path: str, root: str) -> bool:
    """Containment check with symlinks resolved; excludes selected root itself."""
    try:
        resolved_path = os.path.normcase(os.path.realpath(path))
        resolved_root = os.path.normcase(os.path.realpath(root))
        return (resolved_path != resolved_root
                and os.path.commonpath([resolved_path, resolved_root]) == resolved_root)
    except (ValueError, OSError):
        return False


def is_protected_windows_path(path: str) -> bool:
    """Block recycle actions inside Windows, application and profile-data trees."""
    if os.name != "nt":
        return False
    candidates = (
        os.environ.get("WINDIR"), os.environ.get("SystemRoot"),
        os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramData"), os.environ.get("APPDATA"),
        os.environ.get("LOCALAPPDATA"),
    )
    for protected in filter(None, candidates):
        try:
            normalized_path = os.path.normcase(os.path.realpath(path))
            normalized_protected = os.path.normcase(os.path.realpath(protected))
            if os.path.commonpath([normalized_path, normalized_protected]) == normalized_protected:
                return True
        except (ValueError, OSError):
            pass
    return False


def recycle_file(path: str, root: str) -> None:
    """Move one explicitly chosen ordinary file to the OS Recycle Bin.

    This intentionally does not permanently delete files and blocks core
    Windows and application directories. The UI must confirm with the user.
    """
    if not is_under_directory(path, root):
        raise ValueError("This file is outside the selected scan folder.")
    if _is_link_or_junction(Path(path)) or not os.path.isfile(path):
        raise ValueError("The selected item is missing or is not a regular file.")
    if is_protected_windows_path(path):
        raise ValueError("System and application folders are protected.")
    from send2trash import send2trash
    send2trash(path)
