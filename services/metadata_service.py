"""Image metadata service placeholder."""

from __future__ import annotations

from pathlib import Path


def read_metadata(source: Path) -> dict[str, str]:
    """Reserved service contract for metadata extraction."""
    raise NotImplementedError("Metadata reading is not implemented yet.")
