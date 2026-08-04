# Developer Toolbox

A scalable Windows desktop image-utilities application built with **PySide6 (Qt)**.
Its first production-ready tool, **Image to Base64**, encodes image files to Base64 or
Data URI text. The collapsible Qt sidebar animates smoothly and completely hides to
give the active tool the full window width.

Developed by [Zentrix Solutions](https://zentrix-solutions.vercel.app).

## Architecture

The code follows MVC boundaries:

- `app.py` is the controller and coordinates navigation.
- `ui/` contains the reusable Qt shell: header, sidebar, status bar, and window.
- `pages/` contains individual tool views.
- `services/` owns image and Base64 operations, without visual-widget dependencies.

Future contributors must follow the Qt UI rule in [AGENTS.md](AGENTS.md).

## Persistent data

The application uses Python's built-in SQLite support; no separate database server or
package is required. Persistent data is stored locally in
`%LOCALAPPDATA%\DeveloperToolbox\developer_toolbox.db`, including theme settings, recent
files, and API history. Existing Image Toolkit Pro data is copied there automatically
on the next launch, while the original remains as a backup.

## Requirements

- Python 3.12
- Windows (for native file opening and drag/drop)

## Run

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Use **Browse Image** or drop a supported file anywhere in the window. The app accepts JPG, PNG, BMP, GIF, and WebP files up to 50 MB. Conversion occurs on a background thread.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+O | Browse image |
| Ctrl+C | Copy raw Base64 |
| Ctrl+S | Save output |
| Ctrl+L | Clear |
| Ctrl+V | Load an image from the clipboard |

## Package

The project includes a minimal `assets/icon.ico`; replace it with your own branding if desired.

### Create the application bundle

Install PyInstaller, then build using the included spec file:

```powershell
pip install pyinstaller
pyinstaller app.spec
```

This creates `dist\DeveloperToolbox\DeveloperToolbox.exe` and its required Qt files.

### Create the Windows installer

Open `installer.iss` in Inno Setup Compiler and select **Build → Compile**. The
installer is written to `installer_output\DeveloperToolbox-Setup-1.0.0.exe`.
