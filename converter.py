"""Image encoding helpers used by the GUI."""

from __future__ import annotations

import base64
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
MIME_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".bmp": "image/bmp", ".gif": "image/gif", ".webp": "image/webp",
}


@dataclass(frozen=True)
class ConversionResult:
    path: Path
    raw_base64: str
    mime_type: str
    size_bytes: int
    dimensions: tuple[int, int]
    elapsed_ms: float

    def text(self, include_data_uri: bool) -> str:
        if include_data_uri:
            return f"data:{self.mime_type};base64,{self.raw_base64}"
        return self.raw_base64


def is_supported_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def convert_image(path: str | Path) -> ConversionResult:
    """Validate and encode an image without transforming its original bytes."""
    image_path = Path(path)
    if not image_path.is_file() or not is_supported_image(image_path):
        raise ValueError("Invalid image file.")
    if image_path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Image must be 50 MB or smaller.")

    started = time.perf_counter()
    try:
        with Image.open(image_path) as image:
            image.verify()
        with Image.open(image_path) as image:
            dimensions = image.size
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        raise ValueError("Invalid image file.") from error

    with image_path.open("rb") as source:
        raw_base64 = base64.b64encode(source.read()).decode("ascii")
    suffix = image_path.suffix.lower()
    mime_type = MIME_TYPES.get(suffix, mimetypes.guess_type(image_path.name)[0] or "image/*")
    return ConversionResult(
        path=image_path,
        raw_base64=raw_base64,
        mime_type=mime_type,
        size_bytes=os.path.getsize(image_path),
        dimensions=dimensions,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )
