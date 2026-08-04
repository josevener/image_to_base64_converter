"""QR service placeholder; kept separate for future optional dependencies."""

from __future__ import annotations


def decode_qr(_: bytes) -> str:
    """Reserved service contract for QR decoding."""
    raise NotImplementedError("QR decoding is not implemented yet.")
