@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements-build.txt || exit /b 1
python -m unittest discover -s tests -v || exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed --name FilePilot --icon assets/filepilot.ico --collect-all customtkinter main.py || exit /b 1
echo.
echo FilePilot.exe is available in the dist folder.
pause
