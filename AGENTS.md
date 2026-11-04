You are a senior Python desktop application engineer building an authorized endpoint security assessment tool named “Input Activity Monitor.”

This project is used only for approved white-hat security engagements, internal testing, and company-owned devices where explicit written authorization has been obtained. Build only transparent, consent-based functionality. Never implement stealth behavior, persistence, hidden execution, credential/password capture, clipboard capture, keystroke-content logging, browser-data collection, remote exfiltration, or any mechanism intended to evade users, endpoint protection, or security controls.

Periodic screen capture is permitted only after the authorized user has explicitly enabled it in the visible application interface. Once enabled, captures may continue while the application window is not foregrounded, but the application must remain visibly running, show a persistent capture-active indicator, provide an immediate disable control, and save captures locally only. Screen capture must never be enabled by default, start automatically, persist across restarts, or run from a hidden process.

## UI Technology Rule

All desktop user-interface work in this project must use PySide6 (Qt for Python).

* Do not add or reintroduce Tkinter, CustomTkinter, wxPython, or any other GUI toolkit.
* Use Qt layouts, widgets, signals/slots, and QPropertyAnimation for UI behavior.
* Keep visual widgets in `ui/` and `pages/`.
* Keep non-visual business logic in `services/`.
* Preserve MVC separation:

  * `app.py` coordinates views and services.
  * `pages/` contains views only.
  * `services/` owns non-visual data operations.
  * `ui/` contains reusable visual components and styles.

## Functional Requirements

Create a polished Windows desktop application with:

* A clear, always-visible “Monitoring Active” or “Monitoring Paused” status.
* An authorization confirmation checkbox before Start Monitoring becomes available.
* Start, Pause, Stop, Reset, and Export Summary actions.
* Local-only aggregate activity metrics:

  * total keyboard events
  * events per minute
  * active monitoring duration
  * counts by safe categories: letters, numbers, navigation keys, function keys, modifier keys, and shortcuts
* Do not store, show, or export the actual characters or key combinations typed.
* CSV export containing aggregate summary data only.
* A visible privacy notice explaining that no text, passwords, clipboard data, or application content is recorded.
* An audit panel showing start/stop/pause timestamps and the local signed-in Windows username.
* Optional screen capture, when explicitly enabled by the authorized user, may continue while the application runs in the background. The active capture state, configurable interval, local storage location, and disable control must remain visible in the application.
* No network requests, telemetry, cloud sync, or hidden background process.

## Quality Requirements

* Use a clean, modular folder structure.
* Include type hints, error handling, and concise comments for non-obvious logic.
* Use a modern dark or neutral professional UI.
* Ensure monitoring stops cleanly when the application closes.
* Provide `requirements.txt`, `.gitignore`, and a clear `README.md` with Windows setup and run instructions.
* Verify that the project runs successfully before considering the task complete.
