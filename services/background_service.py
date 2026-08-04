"""Local, dependency-free removal of connected uniform image backgrounds."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError


@dataclass(frozen=True)
class BackgroundRemovalResult:
    source: Path
    output: Path
    dimensions: tuple[int, int]


def remove_uniform_background(source: str | Path, output: str | Path, tolerance: int) -> BackgroundRemovalResult:
    """Make edge-connected pixels close to their corner color transparent.

    This deliberately treats only connected edge regions as background, preserving
    foreground objects that share a similar color elsewhere in the image.
    """
    source_path, output_path = Path(source), Path(output)
    try:
        with Image.open(source_path) as original:
            image = original.convert("RGBA")
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Invalid image file.") from error
    width, height = image.size
    pixels = image.load()
    corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    threshold = max(1, tolerance) ** 2 * 3
    visited: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int, tuple[int, int, int]]] = deque()
    for x, y in corners:
        color = pixels[x, y][:3]
        queue.append((x, y, color))

    while queue:
        x, y, reference = queue.popleft()
        if (x, y) in visited:
            continue
        red, green, blue, alpha = pixels[x, y]
        distance = (red - reference[0]) ** 2 + (green - reference[1]) ** 2 + (blue - reference[2]) ** 2
        if distance > threshold:
            continue
        visited.add((x, y))
        pixels[x, y] = (red, green, blue, 0)
        for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= next_x < width and 0 <= next_y < height and (next_x, next_y) not in visited:
                queue.append((next_x, next_y, reference))
    image.save(output_path, "PNG")
    return BackgroundRemovalResult(source_path, output_path, (width, height))
