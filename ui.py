"""CustomTkinter user interface for Image to Base64 Converter."""

from __future__ import annotations

import os
import threading
import tempfile
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk
import pyperclip
from PIL import Image, ImageGrab, ImageOps

from converter import ConversionResult, SUPPORTED_EXTENSIONS, convert_image, is_supported_image
from theme import add_recent, load_settings, save_settings

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    DND_FILES = "DND_Files"
    TkinterDnD = object  # type: ignore[assignment,misc]


class AppRoot(TkinterDnD.Tk if DND_AVAILABLE else ctk.CTk):
    """A Tk root that gains native drag/drop support when tkinterdnd2 is installed."""


class ImageBase64App:
    def __init__(self) -> None:
        self.settings = load_settings()
        ctk.set_appearance_mode(self.settings["theme"])
        ctk.set_default_color_theme("blue")
        self.root = AppRoot()
        self.root.title("Image to Base64 Converter")
        self.root.geometry("1080x760")
        self.root.minsize(850, 650)
        self.result: ConversionResult | None = None
        self.preview_image: ctk.CTkImage | None = None
        self.status_after_id: str | None = None
        self.last_output_folder = self.settings.get("last_folder", "")
        self._build_ui()
        self._bind_shortcuts()
        self._configure_drag_drop()

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self.root, corner_radius=0, height=70)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="▣", font=ctk.CTkFont(size=30, weight="bold"), text_color="#2F80ED").grid(row=0, column=0, padx=(28, 12), pady=16)
        ctk.CTkLabel(header, text="Image to Base64 Converter", font=ctk.CTkFont(size=22, weight="bold")).grid(row=0, column=1, sticky="w")
        self.theme_button = ctk.CTkButton(header, text="☀ Light" if self.settings["theme"] == "Dark" else "☾ Dark", width=100, command=self.toggle_theme)
        self.theme_button.grid(row=0, column=2, padx=24)
        self.recent_menu = ctk.CTkOptionMenu(
            header, values=self._recent_values(), command=self.open_recent,
            width=150,
        )
        self.recent_menu.grid(row=0, column=3, padx=(0, 12))

        body = ctk.CTkFrame(self.root, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=24, pady=20)
        body.grid_columnconfigure((0, 1), weight=1, uniform="columns")
        body.grid_rowconfigure(1, weight=1)

        left = ctk.CTkFrame(body)
        left.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 10))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(left, text="IMAGE", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 4))
        self.drop_area = ctk.CTkFrame(left, border_width=2, border_color=("#B8C2CC", "#45515F"), fg_color="transparent")
        self.drop_area.grid(row=1, column=0, sticky="nsew", padx=20, pady=12)
        self.drop_area.grid_columnconfigure(0, weight=1)
        self.drop_area.grid_rowconfigure(0, weight=1)
        self.preview_label = ctk.CTkLabel(self.drop_area, text="Drop an image here\nor use Browse Image", font=ctk.CTkFont(size=16), justify="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        ctk.CTkButton(left, text="Browse Image", command=self.browse_image, height=40).grid(row=2, column=0, sticky="ew", padx=20, pady=(4, 10))
        self.open_button = ctk.CTkButton(left, text="Open Image", command=self.open_image, state="disabled", fg_color="transparent", border_width=1)
        self.open_button.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))

        right = ctk.CTkFrame(body)
        right.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        right.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(right, text="IMAGE DETAILS", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(18, 10))
        self.stat_vars = {name: ctk.StringVar(value="—") for name in ("Image Size", "Dimensions", "File Type", "Base64 Length", "Encoding Time")}
        for row, (name, variable) in enumerate(self.stat_vars.items(), start=1):
            ctk.CTkLabel(right, text=name, text_color=("#5E6B78", "#AAB4C0")).grid(row=row, column=0, sticky="w", padx=20, pady=5)
            ctk.CTkLabel(right, textvariable=variable, anchor="e").grid(row=row, column=1, sticky="ew", padx=20, pady=5)
        self.uri_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(right, text="Include Data URI Prefix", variable=self.uri_var, command=self.refresh_output).grid(row=6, column=0, columnspan=2, sticky="w", padx=20, pady=(12, 18))

        output = ctk.CTkFrame(body)
        output.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=(20, 0))
        output.grid_columnconfigure(0, weight=1)
        output.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(output, text="BASE64 OUTPUT", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 8))
        self.output_box = ctk.CTkTextbox(output, wrap="none", font=("Cascadia Mono", 12))
        self.output_box.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 14))
        actions = ctk.CTkFrame(output, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 18))
        actions.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)
        self.copy_button = ctk.CTkButton(actions, text="Copy Base64", command=lambda: self.copy_output(False), state="disabled")
        self.copy_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.copy_uri_button = ctk.CTkButton(actions, text="Copy Data URI", command=lambda: self.copy_output(True), state="disabled")
        self.copy_uri_button.grid(row=0, column=1, padx=6, sticky="ew")
        self.save_button = ctk.CTkButton(actions, text="Save Base64", command=self.save_output, state="disabled")
        self.save_button.grid(row=0, column=2, padx=6, sticky="ew")
        self.output_folder_button = ctk.CTkButton(actions, text="Open Output Folder", command=self.open_output_folder, state="disabled", fg_color="transparent", border_width=1)
        self.output_folder_button.grid(row=0, column=3, padx=6, sticky="ew")
        ctk.CTkButton(actions, text="Clear", command=self.clear, fg_color="#9E3A3A", hover_color="#7C2D2D").grid(row=0, column=4, padx=(6, 0), sticky="ew")

        self.status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(self.root, textvariable=self.status_var, anchor="w", height=30, text_color=("#536170", "#AEB9C5")).grid(row=2, column=0, sticky="ew", padx=28)

    def _bind_shortcuts(self) -> None:
        for sequence, callback in (("<Control-o>", self.browse_image), ("<Control-c>", lambda: self.copy_output(False)), ("<Control-s>", self.save_output), ("<Control-l>", self.clear), ("<Control-v>", self.paste_image)):
            self.root.bind(sequence, lambda event, action=callback: (action(), "break")[1])

    def _configure_drag_drop(self) -> None:
        if DND_AVAILABLE:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event: object) -> None:
        data = getattr(event, "data", "")
        paths = self.root.tk.splitlist(data)
        if paths:
            self.load_image(paths[0])

    def browse_image(self) -> None:
        patterns = " ".join(f"*{item}" for item in SUPPORTED_EXTENSIONS)
        path = filedialog.askopenfilename(initialdir=self.settings.get("last_folder") or None, title="Select an image", filetypes=[("Image files", patterns), ("All files", "*.*")])
        if path:
            self.load_image(path)

    def paste_image(self) -> None:
        try:
            clipboard_image = ImageGrab.grabclipboard()
        except Exception:
            clipboard_image = None
        if isinstance(clipboard_image, Image.Image):
            temp_path = Path(tempfile.gettempdir()) / "image_base64_clipboard.png"
            clipboard_image.save(temp_path, "PNG")
            self.load_image(str(temp_path))
            return
        if isinstance(clipboard_image, list) and clipboard_image:
            self.load_image(clipboard_image[0])
            return
        self.set_status("Clipboard does not contain an image.")

    def load_image(self, path: str) -> None:
        if not is_supported_image(path):
            messagebox.showerror("Invalid image", "Invalid image file.")
            return
        self.set_status("Converting image…")
        self._set_busy(True)
        threading.Thread(target=self._convert_worker, args=(path,), daemon=True).start()

    def _convert_worker(self, path: str) -> None:
        try:
            result = convert_image(path)
            self.root.after(0, lambda: self._conversion_done(result))
        except ValueError as error:
            self.root.after(0, lambda: self._conversion_error(str(error)))

    def _conversion_done(self, result: ConversionResult) -> None:
        self.result = result
        self.settings["last_folder"] = str(result.path.parent)
        add_recent(self.settings, str(result.path))
        save_settings(self.settings)
        self.recent_menu.configure(values=self._recent_values())
        self._show_preview(result.path)
        self.stat_vars["Image Size"].set(self._format_size(result.size_bytes))
        self.stat_vars["Dimensions"].set(f"{result.dimensions[0]} × {result.dimensions[1]} px")
        self.stat_vars["File Type"].set(result.mime_type)
        self.stat_vars["Base64 Length"].set(f"{len(result.raw_base64):,} characters")
        self.stat_vars["Encoding Time"].set(f"{result.elapsed_ms:.1f} ms")
        self.refresh_output()
        self._set_busy(False)
        self.open_button.configure(state="normal")
        self.set_status(f"Converted {result.path.name}")

    def _conversion_error(self, text: str) -> None:
        self._set_busy(False)
        messagebox.showerror("Conversion error", text)
        self.set_status(text)

    def _show_preview(self, path: Path) -> None:
        with Image.open(path) as image:
            image.thumbnail((410, 310))
            preview = ImageOps.exif_transpose(image.copy()).convert("RGBA")
        self.preview_image = ctk.CTkImage(light_image=preview, dark_image=preview, size=preview.size)
        self.preview_label.configure(image=self.preview_image, text="")

    def refresh_output(self) -> None:
        self.output_box.delete("1.0", "end")
        if self.result:
            self.output_box.insert("1.0", self.result.text(self.uri_var.get()))

    def copy_output(self, data_uri: bool) -> None:
        if not self.result:
            return
        pyperclip.copy(self.result.text(data_uri))
        self.set_status("Copied!")
        if self.status_after_id:
            self.root.after_cancel(self.status_after_id)
        self.status_after_id = self.root.after(2000, lambda: self.set_status("Ready"))

    def save_output(self) -> None:
        if not self.result:
            return
        path = filedialog.asksaveasfilename(initialdir=self.settings.get("last_folder") or None, defaultextension=".txt", filetypes=[("Text files", "*.txt")], initialfile=f"{self.result.path.stem}-base64.txt")
        if path:
            Path(path).write_text(self.result.text(self.uri_var.get()), encoding="utf-8")
            self.last_output_folder = str(Path(path).parent)
            self.output_folder_button.configure(state="normal")
            self.set_status(f"Saved to {Path(path).name}")

    def open_image(self) -> None:
        if self.result:
            os.startfile(self.result.path)  # type: ignore[attr-defined]

    def clear(self) -> None:
        self.result = None
        self.preview_image = None
        self.preview_label.configure(image=None, text="Drop an image here\nor use Browse Image")
        self.output_box.delete("1.0", "end")
        for variable in self.stat_vars.values():
            variable.set("—")
        for button in (self.copy_button, self.copy_uri_button, self.save_button, self.open_button, self.output_folder_button):
            button.configure(state="disabled")
        self.set_status("Ready")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else ("normal" if self.result else "disabled")
        for button in (self.copy_button, self.copy_uri_button, self.save_button):
            button.configure(state=state)

    def open_output_folder(self) -> None:
        folder = self.last_output_folder or self.settings.get("last_folder")
        if folder and Path(folder).is_dir():
            os.startfile(folder)  # type: ignore[attr-defined]

    def open_recent(self, selection: str) -> None:
        if selection != "Recent Files" and Path(selection).is_file():
            self.load_image(selection)
        self.recent_menu.set("Recent Files")

    def _recent_values(self) -> list[str]:
        recent = [path for path in self.settings.get("recent_files", []) if Path(path).is_file()]
        return ["Recent Files", *recent] or ["Recent Files"]

    def toggle_theme(self) -> None:
        new_theme = "Light" if ctk.get_appearance_mode() == "Dark" else "Dark"
        ctk.set_appearance_mode(new_theme)
        self.settings["theme"] = new_theme
        save_settings(self.settings)
        self.theme_button.configure(text="☀ Light" if new_theme == "Dark" else "☾ Dark")

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ("B", "KB", "MB"):
            if size < 1024 or unit == "MB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
            size /= 1024
        return f"{size:.1f} GB"

    def run(self) -> None:
        self.root.mainloop()
