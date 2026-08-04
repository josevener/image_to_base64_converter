# UI Technology Rule

All desktop user-interface work in this project must use **PySide6 (Qt for Python)**.

- Do not add or reintroduce Tkinter, CustomTkinter, wxPython, or other GUI toolkits.
- Use Qt layouts, widgets, signals/slots, and `QPropertyAnimation` for UI behavior.
- Keep visual widgets in `ui/` and `pages/`; keep application logic in `services/`.
- Preserve the MVC separation: `app.py` coordinates views and services, pages are views,
  and services own non-visual data and image operations.
