"""Non-destructive unit tests for the local scanning engine."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from filepilot.core import (
    ScanCancelled, find_duplicates, format_bytes, is_under_directory,
    recycle_file, scan_directory,
)


class FolderScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, relative, data):
        p = self.root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def test_scans_nested_files_and_aggregate_folder_sizes(self):
        self.write("photos/a.jpg", b"123")
        self.write("photos/2026/b.jpg", b"12345")
        self.write("other/c.bin", b"x" * 12)
        result = scan_directory(str(self.root))
        self.assertEqual(len(result.files), 3)
        self.assertEqual(result.total_size, 20)
        lookup = {Path(f.path).relative_to(self.root).as_posix(): f for f in result.folders}
        self.assertEqual(lookup["photos"].size, 8)
        self.assertEqual(lookup["photos"].files, 2)
        self.assertEqual(lookup["photos/2026"].size, 5)
        self.assertEqual(lookup["other"].size, 12)

    def test_skips_symlink_instead_of_following_it(self):
        self.write("a.txt", b"abc")
        target = self.root / "a.txt"
        link = self.root / "alias.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("This machine does not allow symlinks")
        result = scan_directory(str(self.root))
        self.assertEqual(len(result.files), 1)
        self.assertGreaterEqual(result.skipped, 1)

    def test_cancellation_before_scan(self):
        self.write("a", b"x")
        stop = threading.Event()
        stop.set()
        with self.assertRaises(ScanCancelled):
            scan_directory(str(self.root), stop)

    def test_rejects_nonexistent_folder(self):
        with self.assertRaises(ValueError):
            scan_directory(str(self.root / "missing"))

    def test_progress_updates(self):
        self.write("a", b"hello")
        updates = []
        scan_directory(str(self.root), progress=lambda n, b: updates.append(n))
        self.assertEqual(updates[-1], 1)

    def test_nested_folder_symlink_cannot_escape(self):
        outer = tempfile.TemporaryDirectory()
        self.addCleanup(outer.cleanup)
        external = Path(outer.name) / "secret.bin"
        external.write_bytes(b"private")
        try:
            (self.root / "link").symlink_to(outer.name, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("This machine does not allow directory symlinks")
        self.assertEqual(len(scan_directory(str(self.root)).files), 0)


class DuplicateTests(FolderScanTests):
    def test_detects_same_content_across_different_names(self):
        self.write("a.txt", b"matching contents")
        self.write("somewhere/b.log", b"matching contents")
        self.write("c.txt", b"different")
        result = scan_directory(str(self.root))
        duplicates = find_duplicates(result.files)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(len(duplicates[0].files), 2)
        self.assertEqual(duplicates[0].potential_savings, len(b"matching contents"))

    def test_same_size_different_content_not_a_duplicate(self):
        self.write("a", b"abcd")
        self.write("b", b"wxyz")
        duplicates = find_duplicates(scan_directory(str(self.root)).files)
        self.assertFalse(duplicates)

    def test_changed_files_are_ignored(self):
        self.write("a", b"SAME")
        p = self.write("b", b"SAME")
        snapshot = scan_directory(str(self.root))
        p.write_bytes(b"CHANGED")
        duplicates = find_duplicates(snapshot.files)
        self.assertFalse(duplicates)

    def test_duplicate_cancel(self):
        self.write("a", b"SAME")
        self.write("b", b"SAME")
        stop = threading.Event()
        stop.set()
        with self.assertRaises(ScanCancelled):
            find_duplicates(scan_directory(str(self.root)).files, stop)

    def test_empty_files_are_detected(self):
        self.write("a", b"")
        self.write("b", b"")
        groups = find_duplicates(scan_directory(str(self.root)).files)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].size, 0)

    def test_hardlinks_do_not_count_as_extra_copies(self):
        first = self.write("a.txt", b"hardlinked")
        try:
            os.link(first, self.root / "b.txt")
        except OSError:
            self.skipTest("Hard links unsupported")
        groups = find_duplicates(scan_directory(str(self.root)).files)
        self.assertFalse(groups)


class SafetyTests(FolderScanTests):
    def test_only_files_within_root_are_allowed(self):
        target = self.write("sub/file.txt", b"test")
        self.assertTrue(is_under_directory(str(target), str(self.root)))
        self.assertFalse(is_under_directory(str(self.root), str(self.root)))
        self.assertFalse(is_under_directory(str(self.root.parent), str(self.root)))
        self.assertFalse(is_under_directory(str(self.root / ".." / "outside"), str(self.root)))

    def test_recycle_outside_scan_root_is_rejected(self):
        target = self.write("test.txt", b"ok")
        with self.assertRaises(ValueError):
            recycle_file(str(target), str(self.root / "sub"))
        self.assertTrue(target.exists())

    def test_recycle_moves_only_selected_file_via_send2trash(self):
        target = self.write("keep.txt", b"data")
        with patch("send2trash.send2trash") as mock_trash:
            recycle_file(str(target), str(self.root))
        mock_trash.assert_called_once_with(str(target))
        self.assertTrue(target.exists())

    def test_recycle_directory_not_allowed(self):
        (self.root / "sub").mkdir()
        with patch("send2trash.send2trash") as mock_trash:
            with self.assertRaises(ValueError):
                recycle_file(str(self.root / "sub"), str(self.root))
        mock_trash.assert_not_called()

    def test_recycle_symlink_not_allowed(self):
        target = self.write("original", b"data")
        try:
            (self.root / "link").symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unsupported")
        with self.assertRaises(ValueError):
            recycle_file(str(self.root / "link"), str(self.root))

    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1536), "1.50 KB")
        self.assertEqual(format_bytes(1024**3), "1.00 GB")


if __name__ == "__main__":
    unittest.main()
