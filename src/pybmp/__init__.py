"""pybmp: a fast, dependency-free reader and writer for Windows BMP images.

Quick start::

    import pybmp

    img = pybmp.BMP("photo.bmp")
    print(img.size, img.bits_per_pixel, img.mode)
    rgb = img.to_rgb()           # packed RGB bytes, rows top-down

    data = pybmp.encode(2, 1, b"\\xff\\x00\\x00\\x00\\xff\\x00")
    pybmp.BMP(data=data).save("out.bmp")
"""

from __future__ import annotations

import builtins
import os
from typing import IO, TYPE_CHECKING

from ._bmp import BMP
from ._constants import Compression
from ._encode import DEFAULT_PPM, HeaderVersion, Mode, encode
from ._errors import (
    BMPError,
    HeaderNotSupported,
    InvalidBMPError,
    TruncatedFileError,
    UnsupportedFormatError,
)
from ._header import BMPHeader, parse_header

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "BMP",
    "BMPError",
    "BMPHeader",
    "Compression",
    "HeaderNotSupported",
    "HeaderVersion",
    "InvalidBMPError",
    "Mode",
    "TruncatedFileError",
    "UnsupportedFormatError",
    "__version__",
    "encode",
    "name",
    "open",
    "parse_header",
    "write",
]

__version__ = "2.0.0"

#: Distribution name on PyPI (kept from pybmp 1.x).
name = "pybmp2"


def open(path: str | os.PathLike[str] | IO[bytes]) -> BMP:  # noqa: A001
    """Read a BMP from a path or a binary file object (like ``PIL.Image.open``)."""
    return BMP.open(path)


def write(
    path: str | os.PathLike[str] | IO[bytes],
    width: int,
    height: int,
    pixels: bytes | bytearray | memoryview,
    *,
    mode: Mode = "RGB",
    bits: int | None = None,
    palette: Sequence[tuple[int, int, int]] | None = None,
    top_down: bool = False,
    header: HeaderVersion | None = None,
    pixels_per_meter: int = DEFAULT_PPM,
) -> None:
    """Encode pixels with :func:`encode` and write them to a path or file object."""
    data = encode(
        width,
        height,
        pixels,
        mode=mode,
        bits=bits,
        palette=palette,
        top_down=top_down,
        header=header,
        pixels_per_meter=pixels_per_meter,
    )
    if isinstance(path, (str, os.PathLike)):
        with builtins.open(path, "wb") as f:
            f.write(data)
    else:
        path.write(data)
