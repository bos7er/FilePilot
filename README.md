# FilePilot

**A modern, private disk explorer for Windows 10 and 11.**

FilePilot helps you understand where your storage space went, spot oversized files, and find real duplicates before you decide what to remove.

**[Download latest release](https://github.com/bos7er/FilePilot/releases/latest) · [Project website](https://bos7er.github.io/FilePilot/) · [Build status](https://github.com/bos7er/FilePilot/actions)**

> Releases are available once the repository owner publishes the first Windows executable.

## Features

- **Storage overview:** total file size, file count, scan duration, and folder space usage.
- **Largest files:** browse the 1,500 biggest files in a selected folder (CSV export includes every scanned file).
- **Duplicate finder:** compare full file contents using SHA-256, checking only same-size candidates first. Hard links are not counted twice.
- **Safe cleanup:** move a *single, explicitly selected file* to the Windows Recycle Bin after confirmation. No automated deletion; system and application directories are protected.
- **Open in Explorer:** jump to the selected file's location.
- **Export reports:** CSV reports for scanned files and duplicate groups.
- **Cancel anytime:** stop scans without modifying data.
- **Runs offline:** no accounts, analytics, uploads, or network requests.

**Important:** Folder scanning and hashing can be slow on very large or external drives. Some protected files may be skipped. Counts represent accessible files and do not include filesystem overhead.

## Download and install

1. Open [Releases](https://github.com/bos7er/FilePilot/releases).
2. Download `FilePilot.exe` from the latest release's **Assets** section.
3. Run the executable on Windows 10 or 11. Python is not needed.
4. Click **Browse folder**, choose a directory, then **Scan folder**.

Unsigned community-built Windows programs may show a SmartScreen warning. Verify the release source before running an executable. No administrator rights are required for normal folders.

## Build the Windows EXE with GitHub Actions

The workflow is at `.github/workflows/build-windows.yml`.

1. Upload the project **files and folders** to the repository root, preserving `.github/workflows/`.
2. Go to **Actions → Build FilePilot for Windows**.
3. Select **Run workflow**, or open the automatically started run after a push to `main`.
4. After a green successful run, open the run and download **FilePilot-Windows-EXE** under **Artifacts**.
5. Extract the downloaded artifact to get `FilePilot.exe`.
6. For a public download, create **Releases → Draft a new release**, tag `v1.0.0`, and attach `FilePilot.exe` under **Assets** before publishing.

The Actions artifact is mainly for testing. Public visitors should download the EXE from **Releases**.

## Run from source

Install Python 3.12+ on Windows, then:

```powershell
python -m pip install -r requirements.txt
python main.py
```

Build locally with `build.bat`, or:

```powershell
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
python -m PyInstaller --noconfirm --clean --onefile --windowed --name FilePilot --icon assets/filepilot.ico --collect-all customtkinter main.py
```

The executable appears at `dist/FilePilot.exe`.

## Enable the project website

In **Settings → Pages**, choose **Deploy from a branch**, `main`, `/docs`, and click **Save**. The provided website is fully in English. Its download button leads to the latest GitHub Release.

## Privacy and safety

- All analysis takes place on your device. No file content is sent anywhere.
- File contents are read only when you run duplicate detection.
- Symbolic links and Windows junctions are not followed.
- Deletion is never automatic. The app only sends one selected file to the OS Recycle Bin, after a confirmation dialog.
- Core Windows and application data folders are protected from the cleanup function.
- Review duplicates carefully before moving any files. Two identical files may both be required by your software.

## Technologies

Python 3.12 · CustomTkinter · standard library SHA-256 · Send2Trash · PyInstaller · GitHub Actions

## Contributing

Issues and pull requests are welcome. Do not include personal file paths or private data in bug reports.

## License

MIT — see [LICENSE](LICENSE).
