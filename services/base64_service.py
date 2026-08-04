"""Base64-specific model operations."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError


def decode_data_uri(value: str) -> tuple[str, bytes]:
    """Decode raw Base64 or a Data URI and return its MIME type and bytes."""
    text = value.strip()
    mime_type = "image/png"
    if text.startswith("data:"):
        header, text = text.split(",", 1)
        mime_type = header.split(";", 1)[0][5:] or mime_type
    try:
        return mime_type, base64.b64decode("".join(text.split()), validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid Base64 image data.") from error


def save_as_image(value: str, destination: str | Path, image_format: str) -> tuple[str, bytes]:
    """Decode and validate Base64 image data, then save it in the chosen format."""
    mime_type, data = decode_data_uri(value)
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            if image_format == "JPEG" and image.mode in {"RGBA", "LA", "P"}:
                image = image.convert("RGB")
            image.save(destination, image_format)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValueError("Invalid Base64 image data.") from error
    return mime_type, data
