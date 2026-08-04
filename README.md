# Image to Base64 Converter

A Windows desktop tool for encoding image files to Base64 or Data URI text.

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

Use **Browse Image**, drop a supported file onto the window, or paste an image-file path with `Ctrl+V`. The app accepts JPG, PNG, BMP, GIF, and WebP files up to 50 MB. Conversion occurs on a background thread.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+O | Browse image |
| Ctrl+C | Copy raw Base64 |
| Ctrl+S | Save output |
| Ctrl+L | Clear |
| Ctrl+V | Load copied image-file path |

## Package

The project includes a minimal `assets/icon.ico`; replace it with your own branding if desired, then run:

```powershell
pyinstaller --onefile --windowed --icon assets/icon.ico main.py
```

If no icon is needed, omit the `--icon` argument.
