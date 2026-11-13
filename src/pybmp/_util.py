"""Small byte-level helpers shared by the decoder and encoder."""

from __future__ import annotations

__all__ = ["or_bytes"]


def or_bytes(a: bytes, b: bytes) -> bytes:
    """Bitwise OR of two equal-length byte strings via big-integer arithmetic.

    CPython performs big-int ``|`` in C, so this is far faster than a
    per-byte Python loop.
    """
    return (int.from_bytes(a, "little") | int.from_bytes(b, "little")).to_bytes(
        len(a), "little"
    )
