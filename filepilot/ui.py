"""English-language Windows desktop interface for FilePilot."""
from __future__ import annotations

import csv
from datetime import datetime
import os
from pathlib import Path
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from .core import (
    DuplicateGroup, FileRecord, ScanCancelled, ScanResult,
    find_duplicates, format_bytes, recycle_file, scan_directory,
)
from . import __version__

BG = "#0A101B"
CARD = "#131F2E"
CARD_2 = "#18283A"
EDGE = "#25394F"
TEXT = "#ECF3FA"
MUTED = "#9DAFBE"
ACCENT = "#28DBB5"
ACCENT_DARK = "#0D6D5C"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class FilePilotApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"FilePilot {__version__} | Smart Storage Explorer")
        self.geometry("1160x800")
        self.minsize(950, 660)
        self.configure(fg_color=BG)
        self.scan_data: ScanResult | None = None
        self.duplicate_groups: tuple[DuplicateGroup, ...] = ()
        self._file_rows: dict[str, FileRecord] = {}
        self._duplicate_rows: dict[str, FileRecord] = {}
        self._events: queue.Queue[tuple] = queue.Queue()
        self._cancel = threading.Event()
        self._task: str | None = None
        default_path = Path.home() / "Downloads"
        self.selected_path = str(default_path if default_path.is_dir() else Path.home())

        self._style_tree()
        self._create_header()
        self._create_toolbar()
        self._create_tabs()
        self._create_status()
        self._reset_display()
        self.after(100, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _style_tree(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "FilePilot.Treeview", background=CARD, fieldbackground=CARD,
            foreground=TEXT, borderwidth=0, rowheight=29,
            font=("Segoe UI", 10),
        )
        style.configure(
            "FilePilot.Treeview.Heading", background=CARD_2, foreground=TEXT,
            borderwidth=0, padding=(9, 9), font=("Segoe UI Semibold", 10),
        )
        style.map("FilePilot.Treeview", background=[("selected", ACCENT_DARK)],
                  foreground=[("selected", "#FFFFFF")])
        style.map("FilePilot.Treeview.Heading", background=[("active", EDGE)])

    def _create_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        header.pack(fill="x", padx=26, pady=(22, 12))
        ctk.CTkLabel(header, text="◈  FilePilot", font=("Segoe UI", 29, "bold"),
                     text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(header, text="SMART STORAGE EXPLORER", font=("Segoe UI", 11, "bold"),
                     text_color=MUTED).pack(side="left", padx=22, pady=(10, 0))
        ctk.CTkLabel(header, text=f"v{__version__}  •  Offline & private",
                     font=("Segoe UI", 11), text_color=MUTED).pack(side="right")

    def _create_toolbar(self) -> None:
        outer = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12, border_width=1,
                             border_color=EDGE)
        outer.pack(fill="x", padx=26, pady=(0, 14))
        title_row = ctk.CTkFrame(outer, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(13, 4))
        ctk.CTkLabel(title_row, text="Folder to analyze", font=("Segoe UI", 12, "bold"),
                     text_color=MUTED).pack(side="left")
        path_row = ctk.CTkFrame(outer, fg_color="transparent")
        path_row.pack(fill="x", padx=16, pady=(0, 14))
        self.path_label = ctk.CTkLabel(path_row, text=self.selected_path,
                                       font=("Segoe UI", 11), text_color=TEXT,
                                       fg_color=BG, corner_radius=8, anchor="w", height=40)
        self.path_label.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.choose_button = self._button(path_row, "Browse folder", self._choose_folder,
                                           primary=False, width=120)
        self.choose_button.pack(side="left", padx=(0, 9))
        self.scan_button = self._button(path_row, "Scan folder", self._start_scan, width=120)
        self.scan_button.pack(side="left", padx=(0, 9))
        self.cancel_button = self._button(path_row, "Cancel", self._cancel_task,
                                           primary=False, width=80)
        self.cancel_button.pack(side="left")
        self.cancel_button.configure(state="disabled")

    def _button(self, parent, title: str, command, *, primary: bool = True, width: int = 150):
        return ctk.CTkButton(
            parent, text=title, command=command, width=width, height=40,
            corner_radius=8, font=("Segoe UI", 12, "bold"),
            fg_color=ACCENT if primary else CARD_2,
            hover_color="#1DBE9E" if primary else EDGE,
            text_color=BG if primary else TEXT,
        )

    def _create_tabs(self) -> None:
        self.tabs = ctk.CTkTabview(
            self, fg_color=CARD, segmented_button_fg_color=CARD_2,
            segmented_button_selected_color=ACCENT_DARK,
            segmented_button_selected_hover_color="#118B76",
            segmented_button_unselected_color=CARD_2,
            segmented_button_unselected_hover_color=EDGE,
            text_color=TEXT, corner_radius=12,
        )
        self.tabs.pack(fill="both", expand=True, padx=26, pady=(0, 14))
        self.tabs.add("Overview")
        self.tabs.add("Largest Files")
        self.tabs.add("Duplicates")
        self._create_overview(self.tabs.tab("Overview"))
        self._create_largest(self.tabs.tab("Largest Files"))
        self._create_duplicates(self.tabs.tab("Duplicates"))

    def _make_tree(self, parent, columns, widths: dict[str, int], *, height: int = 13):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=12, pady=(3, 12))
        tree = ttk.Treeview(frame, columns=columns, show="headings",
                            style="FilePilot.Treeview", selectmode="browse", height=height)
        for col in columns:
            tree.heading(col, text=col, anchor="w")
            tree.column(col, width=widths.get(col, 140), minwidth=75,
                        anchor="w", stretch=col in ("Path", "Folder", "Name"))
        scroll_y = ctk.CTkScrollbar(frame, command=tree.yview)
        tree.configure(yscrollcommand=scroll_y.set)
        scroll_y.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def _create_overview(self, tab) -> None:
        stats = ctk.CTkFrame(tab, fg_color="transparent")
        stats.pack(fill="x", padx=12, pady=(14, 10))
        self._stat_values: dict[str, ctk.CTkLabel] = {}
        for idx, (key, title) in enumerate([
            ("files", "FILES FOUND"), ("size", "TOTAL FILE SIZE"),
            ("folders", "FOLDERS"), ("time", "SCAN TIME"),
        ]):
            stats.grid_columnconfigure(idx, weight=1, uniform="stats")
            card = ctk.CTkFrame(stats, fg_color=CARD_2, corner_radius=11)
            card.grid(row=0, column=idx, padx=5, sticky="ew")
            ctk.CTkLabel(card, text=title, text_color=MUTED,
                         font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=17, pady=(13, 5))
            v = ctk.CTkLabel(card, text="—", text_color=TEXT,
                             font=("Segoe UI", 23, "bold"))
            v.pack(anchor="w", padx=17, pady=(0, 12))
            self._stat_values[key] = v
        ctk.CTkLabel(tab, text="Folders using the most space",
                     text_color=TEXT, font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=19, pady=(9, 1))
        ctk.CTkLabel(tab, text="Includes files inside subfolders. Unreadable and linked entries are skipped.",
                     text_color=MUTED, font=("Segoe UI", 11)).pack(anchor="w", padx=19, pady=(0, 6))
        self.folder_tree = self._make_tree(tab, ("Folder", "Size", "Files"),
                                           {"Folder": 650, "Size": 140, "Files": 120})

    def _action_row(self, tab):
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=(13, 9))
        return row

    def _create_largest(self, tab) -> None:
        row = self._action_row(tab)
        ctk.CTkLabel(row, text="Largest files", text_color=TEXT,
                     font=("Segoe UI", 17, "bold")).pack(side="left", padx=(0, 16))
        self.export_files_button = self._button(row, "Export CSV", self._export_files,
                                                  primary=False, width=113)
        self.export_files_button.pack(side="right", padx=(8, 0))
        self.recycle_files_button = self._button(row, "Move to Recycle Bin",
                                                   lambda: self._recycle_selected("files"),
                                                   primary=False, width=171)
        self.recycle_files_button.pack(side="right", padx=(8, 0))
        self.open_files_button = self._button(row, "Show in Explorer",
                                                lambda: self._open_selected("files"),
                                                primary=False, width=148)
        self.open_files_button.pack(side="right", padx=(8, 0))
        ctk.CTkLabel(tab, text="Choose an item below. Nothing is removed unless you explicitly confirm.",
                     text_color=MUTED, font=("Segoe UI", 11)).pack(anchor="w", padx=18)
        self.files_tree = self._make_tree(tab, ("Name", "Size", "Modified", "Path"),
                                          {"Name": 205, "Size": 120, "Modified": 145, "Path": 570})

    def _create_duplicates(self, tab) -> None:
        row = self._action_row(tab)
        ctk.CTkLabel(row, text="Duplicate finder", text_color=TEXT,
                     font=("Segoe UI", 17, "bold")).pack(side="left", padx=(0, 15))
        self.dupe_button = self._button(row, "Find duplicates", self._start_duplicates, width=148)
        self.dupe_button.pack(side="left", padx=(0, 10))
        self.export_dupes_button = self._button(row, "Export CSV", self._export_duplicates,
                                                  primary=False, width=115)
        self.export_dupes_button.pack(side="right", padx=(8, 0))
        self.recycle_dupe_button = self._button(row, "Move to Recycle Bin",
                                                  lambda: self._recycle_selected("dupes"),
                                                  primary=False, width=172)
        self.recycle_dupe_button.pack(side="right", padx=(8, 0))
        self.open_dupe_button = self._button(row, "Show in Explorer",
                                               lambda: self._open_selected("dupes"),
                                               primary=False, width=143)
        self.open_dupe_button.pack(side="right", padx=(8, 0))
        self.duplicate_summary = ctk.CTkLabel(
            tab, text="Scan a folder first, then use Find duplicates. SHA-256 checks file contents.",
            text_color=MUTED, font=("Segoe UI", 11), anchor="w")
        self.duplicate_summary.pack(fill="x", padx=18, pady=(0, 3))
        self.duplicate_tree = self._make_tree(tab, ("Group", "Size", "Name", "Path"),
                                              {"Group": 75, "Size": 120, "Name": 230, "Path": 635})

    def _create_status(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=29, pady=(0, 16))
        self.status = ctk.CTkLabel(bar, text="Ready. Select a folder and run a scan.",
                                   text_color=MUTED, anchor="w", font=("Segoe UI", 11))
        self.status.pack(side="left", fill="x", expand=True)
        self.progressbar = ctk.CTkProgressBar(bar, width=180, height=8,
                                             progress_color=ACCENT, fg_color=EDGE)
        self.progressbar.pack(side="right", padx=(14, 0))
        self.progressbar.set(0)

    def _reset_display(self) -> None:
        for t in (self.folder_tree, self.files_tree, self.duplicate_tree):
            for item in t.get_children():
                t.delete(item)
        self._file_rows.clear()
        self._duplicate_rows.clear()
        for key in self._stat_values:
            self._stat_values[key].configure(text="—")
        self.duplicate_summary.configure(
            text="Scan a folder first, then use Find duplicates. SHA-256 checks file contents.")

    def _choose_folder(self) -> None:
        if self._task:
            return
        path = filedialog.askdirectory(initialdir=self.selected_path, title="Choose a folder to analyze")
        if path:
            self.selected_path = path
            self.path_label.configure(text=f"  {path}")
            self.scan_data = None
            self.duplicate_groups = ()
            self._reset_display()
            self.status.configure(text="Folder selected. Click Scan folder to begin.")

    def _set_busy(self, task: str | None) -> None:
        self._task = task
        busy = task is not None
        self.scan_button.configure(state="disabled" if busy else "normal")
        self.choose_button.configure(state="disabled" if busy else "normal")
        self.dupe_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.progressbar.configure(mode="indeterminate")
            self.progressbar.start()
        else:
            self.progressbar.stop()
            self.progressbar.configure(mode="determinate")
            self.progressbar.set(0)

    def _start_scan(self) -> None:
        if self._task:
            return
        self.scan_data = None
        self.duplicate_groups = ()
        self._reset_display()
        self._cancel = threading.Event()
        self._set_busy("scan")
        self.status.configure(text="Scanning files… This can take longer on large drives.")
        root = self.selected_path

        def worker():
            try:
                result = scan_directory(
                    root, self._cancel,
                    lambda count, _bytes: self._events.put(("scan_progress", count)),
                )
                self._events.put(("scan_done", result))
            except ScanCancelled:
                self._events.put(("cancelled",))
            except Exception as exc:
                self._events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _start_duplicates(self) -> None:
        if self._task:
            return
        if not self.scan_data:
            messagebox.showinfo("Scan required", "Please scan a folder before finding duplicates.")
            return
        self._cancel = threading.Event()
        self._set_busy("duplicates")
        self.status.configure(text="Checking file contents for duplicates…")
        self.duplicate_summary.configure(text="Calculating SHA-256 checksums for same-size files…")
        files = self.scan_data.files

        def worker():
            try:
                groups = find_duplicates(
                    files, self._cancel,
                    lambda done, total: self._events.put(("dupe_progress", done, total)),
                )
                self._events.put(("dupe_done", groups))
            except ScanCancelled:
                self._events.put(("cancelled",))
            except Exception as exc:
                self._events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _cancel_task(self) -> None:
        if self._task:
            self._cancel.set()
            self.status.configure(text="Cancel requested. Finishing the current operation…")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self._events.get_nowait()
                name = event[0]
                if name == "scan_progress":
                    if self._task == "scan":
                        self.status.configure(text=f"Scanning… {event[1]:,} files found")
                elif name == "scan_done":
                    self._set_busy(None)
                    self.scan_data = event[1]
                    self._display_scan(event[1])
                elif name == "dupe_progress":
                    if self._task == "duplicates":
                        self.status.configure(text=f"Hashing files… {event[1]:,} / {event[2]:,}")
                elif name == "dupe_done":
                    self._set_busy(None)
                    self.duplicate_groups = event[1]
                    self._display_duplicates(event[1])
                    self.tabs.set("Duplicates")
                elif name == "cancelled":
                    self._set_busy(None)
                    self.status.configure(text="Operation cancelled. No files were changed.")
                    self.duplicate_summary.configure(text="Operation cancelled. Try again when ready.")
                elif name == "error":
                    self._set_busy(None)
                    self.status.configure(text=f"Error: {event[1]}")
                    messagebox.showerror("FilePilot", event[1])
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(110, self._poll_events)

    def _display_scan(self, result: ScanResult) -> None:
        self._stat_values["files"].configure(text=f"{len(result.files):,}")
        self._stat_values["size"].configure(text=format_bytes(result.total_size))
        self._stat_values["folders"].configure(text=f"{len(result.folders):,}")
        self._stat_values["time"].configure(text=f"{result.elapsed:.1f}s")
        for index, folder in enumerate(sorted(result.folders, key=lambda f: f.size, reverse=True)[:350]):
            display_name = os.path.relpath(folder.path, result.root)
            self.folder_tree.insert("", "end", iid=f"folder{index}", values=(
                display_name, format_bytes(folder.size), f"{folder.files:,}",
            ))
        for index, rec in enumerate(sorted(result.files, key=lambda f: f.size, reverse=True)[:1500]):
            iid = f"file{index}"
            self._file_rows[iid] = rec
            try:
                modified = datetime.fromtimestamp(rec.modified_ns / 1_000_000_000).strftime("%Y-%m-%d %H:%M")
            except (OverflowError, OSError, ValueError):
                modified = "Unknown"
            self.files_tree.insert("", "end", iid=iid, values=(
                os.path.basename(rec.path), format_bytes(rec.size), modified, rec.path,
            ))
        self.status.configure(text=(
            f"Scan complete: {len(result.files):,} files • {result.skipped:,} unreadable or linked entries skipped. "
            "Largest Files shows the top 1,500 files."
        ))

    def _display_duplicates(self, groups: tuple[DuplicateGroup, ...]) -> None:
        for item in self.duplicate_tree.get_children():
            self.duplicate_tree.delete(item)
        self._duplicate_rows.clear()
        row_count = 0
        for g_index, group in enumerate(groups, 1):
            for rec in group.files:
                if row_count >= 2000:
                    break
                iid = f"dupe{row_count}"
                self._duplicate_rows[iid] = rec
                self.duplicate_tree.insert("", "end", iid=iid, values=(
                    f"#{g_index}", format_bytes(rec.size), os.path.basename(rec.path), rec.path,
                ))
                row_count += 1
            if row_count >= 2000:
                break
        savings = sum(group.potential_savings for group in groups)
        summary = (f"{len(groups):,} duplicate groups • Potential savings: {format_bytes(savings)} "
                   "(estimate; keep at least one copy of each group).")
        self.duplicate_summary.configure(text=summary)
        self.status.configure(text=f"Duplicate scan complete. Showing {row_count:,} matching files.")

    def _current_record(self, source: str) -> FileRecord | None:
        tree = self.files_tree if source == "files" else self.duplicate_tree
        rows = self._file_rows if source == "files" else self._duplicate_rows
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Select a file", "Please select a file in the list first.")
            return None
        return rows.get(selected[0])

    def _open_selected(self, source: str) -> None:
        rec = self._current_record(source)
        if not rec:
            return
        if not os.path.exists(rec.path):
            messagebox.showwarning("File not found", "This file has moved. Run a new scan.")
            return
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer.exe", "/select,", rec.path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(rec.path)])
        except OSError as exc:
            messagebox.showerror("Cannot open location", str(exc))

    def _recycle_selected(self, source: str) -> None:
        if self._task:
            return
        rec = self._current_record(source)
        if not rec or not self.scan_data:
            return
        if not messagebox.askyesno(
            "Move file to Recycle Bin",
            "Move this file to the Windows Recycle Bin?\n\n"
            f"{rec.path}\n\nSize: {format_bytes(rec.size)}\n\n"
            "This does not permanently delete the file. Review the path carefully.",
            icon="warning",
        ):
            return
        try:
            recycle_file(rec.path, self.scan_data.root)
        except (ValueError, OSError, PermissionError) as exc:
            messagebox.showerror("Cannot recycle file", str(exc))
            return
        tree = self.files_tree if source == "files" else self.duplicate_tree
        tree.delete(tree.selection()[0])
        self.status.configure(text="File moved to Recycle Bin. Re-scan to update storage totals.")
        messagebox.showinfo("File moved", "The selected file was moved to the Recycle Bin. Re-scan to refresh results.")

    def _export_files(self) -> None:
        if not self.scan_data:
            messagebox.showinfo("Scan required", "Scan a folder before exporting a report.")
            return
        path = filedialog.asksaveasfilename(title="Export file report", defaultextension=".csv",
                                            initialfile="filepilot-files.csv",
                                            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["File Path", "Size (bytes)", "Last Modified (UTC timestamp)"])
                for f in sorted(self.scan_data.files, key=lambda r: r.size, reverse=True):
                    writer.writerow([f.path, f.size, f.modified_ns])
        except OSError as exc:
            messagebox.showerror("Export error", str(exc))
            return
        self.status.configure(text=f"Report exported to {path}")

    def _export_duplicates(self) -> None:
        if not self.duplicate_groups:
            messagebox.showinfo("No duplicate results", "Run Find duplicates before exporting.")
            return
        path = filedialog.asksaveasfilename(title="Export duplicate report", defaultextension=".csv",
                                            initialfile="filepilot-duplicates.csv",
                                            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Group", "SHA-256", "File Path", "Size (bytes)"])
                for number, group in enumerate(self.duplicate_groups, 1):
                    for rec in group.files:
                        writer.writerow([number, group.digest, rec.path, rec.size])
        except OSError as exc:
            messagebox.showerror("Export error", str(exc))
            return
        self.status.configure(text=f"Report exported to {path}")

    def _on_close(self) -> None:
        self._cancel.set()
        self.destroy()


def run() -> None:
    FilePilotApp().mainloop()
