"""Exception hierarchy for :mod:`pybmp`.

Every error raised for bad or unsupported input derives from :class:`BMPError`,
which itself subclasses :class:`ValueError` so ``except ValueError`` keeps
working for callers of the original 1.x API.
"""

from __future__ import annotations

__all__ = [
    "BMPError",
    "HeaderNotSupported",
    "InvalidBMPError",
    "TruncatedFileError",
    "UnsupportedFormatError",
]


class BMPError(ValueError):
    """Base class for every error raised by pybmp."""


class InvalidBMPError(BMPError):
    """The data is not a well-formed BMP file."""


class TruncatedFileError(InvalidBMPError):
    """The data ends before a header, palette or pixel array is complete."""


class HeaderNotSupported(BMPError):  # noqa: N818 - name kept from pybmp 1.x
    """The DIB header size does not match any known BMP header version."""


class UnsupportedFormatError(BMPError):
    """The file is valid but uses a feature pybmp cannot decode or encode."""
