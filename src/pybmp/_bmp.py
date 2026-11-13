"""The :class:`BMP` image class."""

from __future__ import annotations

import binascii
import logging
import os
import warnings
from typing import IO, TYPE_CHECKING, Any, ClassVar

from ._constants import Compression
from ._decode import decode_indices, decode_rgb, has_alpha, pixel_array
from ._encode import DEFAULT_PPM, HeaderVersion, Mode, encode
from ._errors import BMPError, InvalidBMPError, UnsupportedFormatError
from ._header import BMPHeader, parse_header, row_stride

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import numpy as np

__all__ = ["BMP"]

logger = logging.getLogger("pybmp2")

StrPath = str | os.PathLike[str]


class _Legacy:
    """Read-only alias exposing a pybmp 1.x upper-case attribute."""

    __slots__ = ("_getter", "_name", "_present")

    def __init__(
        self,
        getter: Callable[[BMP], Any],
        present: Callable[[BMPHeader], bool] | None = None,
    ) -> None:
        self._getter = getter
        self._present = present
        self._name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name

    def __get__(self, obj: BMP | None, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        if self._present is not None and not self._present(obj.header):
            raise AttributeError(
                f"{self._name} is not defined for {obj.header.header_name}"
            )
        return self._getter(obj)


def _has_info(h: BMPHeader) -> bool:
    return h.header_size >= 40


def _has_v4(h: BMPHeader) -> bool:
    return h.header_size >= 108


def _mask_bytes(value: int) -> bytes:
    return value.to_bytes(4, "little")


class BMP:
    """A parsed BMP image.

    Construct it from exactly one source::

        BMP("image.bmp")                 # path (str or os.PathLike)
        BMP(data=raw_bytes)              # the file's bytes
        BMP(hexdata=binascii.hexlify(raw_bytes))  # pybmp 1.x hex input

    or with :meth:`open` / :meth:`from_bytes`. Headers are parsed eagerly;
    pixels are decoded on demand by :meth:`to_rgb`, :meth:`to_rgba`,
    :meth:`to_indices` and :meth:`to_numpy`.
    """

    COMPRESSION_DICT: ClassVar[dict[str, int]] = {c.name: c.value for c in Compression}

    __slots__ = ("_data", "header")

    def __init__(
        self,
        filename: StrPath | None = None,
        hexdata: bytes | str | None = None,
        *,
        data: bytes | bytearray | memoryview | None = None,
    ) -> None:
        """Parse a BMP from a path, raw bytes or a hex string.

        Raises:
            ValueError: if not exactly one source is given.
            BMPError: (a ``ValueError`` subclass) if the data is not a valid BMP.
        """
        sources = sum(x is not None for x in (filename, hexdata, data))
        if sources != 1:
            raise ValueError("pass exactly one of filename, hexdata or data")
        if filename is not None:
            with open(filename, "rb") as f:
                raw = f.read()
        elif hexdata is not None:
            try:
                raw = binascii.unhexlify(hexdata)
            except (binascii.Error, ValueError) as exc:
                raise InvalidBMPError(f"hexdata is not valid hex: {exc}") from exc
        else:
            assert data is not None
            raw = bytes(data)
        self._data: bytes = raw
        self.header: BMPHeader = parse_header(raw)
        logger.debug(
            "Header Type: %s, Compression Method: %s",
            self.header.header_name,
            self.header.compression_name,
        )

    # ------------------------------------------------------------------ factories
    @classmethod
    def open(cls, path: StrPath | IO[bytes]) -> BMP:
        """Read a BMP from a path or a binary file object."""
        if isinstance(path, (str, os.PathLike)):
            return cls(path)
        return cls(data=path.read())

    @classmethod
    def from_bytes(cls, data: bytes | bytearray | memoryview) -> BMP:
        """Parse a BMP held in memory."""
        return cls(data=data)

    @classmethod
    def from_pixels(
        cls,
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
    ) -> BMP:
        """Build a BMP from raw pixels; see :func:`pybmp.encode` for arguments."""
        return cls(
            data=encode(
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
        )

    # ---------------------------------------------------------------- properties
    @property
    def width(self) -> int:
        """Width in pixels."""
        return self.header.width

    @property
    def height(self) -> int:
        """Height in pixels (always positive; see :attr:`top_down`)."""
        return abs(self.header.height)

    @property
    def size(self) -> tuple[int, int]:
        """``(width, height)`` in pixels, both positive."""
        return (self.width, self.height)

    @property
    def bits_per_pixel(self) -> int:
        """Stored bits per pixel."""
        return self.header.bits_per_pixel

    @property
    def top_down(self) -> bool:
        """``True`` if rows are stored top-down (negative height on disk)."""
        return self.header.top_down

    @property
    def palette(self) -> tuple[tuple[int, int, int], ...]:
        """Colour table as ``(r, g, b)`` tuples (empty for most true-colour files)."""
        return self.header.palette

    @property
    def mode(self) -> str:
        """``"RGBA"`` if the pixel format has an alpha channel, else ``"RGB"``."""
        return "RGBA" if has_alpha(self.header) else "RGB"

    @property
    def data(self) -> bytes:
        """The complete file contents."""
        return self._data

    @property
    def pixel_array(self) -> bytes:
        """Raw stored pixel bytes, read from the header's pixel-data offset."""
        return pixel_array(self._data, self.header)

    # ------------------------------------------------------------------ decoding
    def to_rgb(self) -> bytes:
        """Decode to packed RGB bytes, 3 per pixel, rows top-down."""
        return decode_rgb(self._data, self.header)

    def to_rgba(self) -> bytes:
        """Decode to packed RGBA bytes, 4 per pixel, rows top-down.

        Formats without alpha get an opaque (255) alpha channel.
        """
        return decode_rgb(self._data, self.header, alpha=True)

    def to_indices(self) -> bytes:
        """Return one palette index per pixel (rows top-down) for <= 8-bit images."""
        return decode_indices(self._data, self.header)

    def to_numpy(self, mode: str | None = None) -> np.ndarray[Any, Any]:
        """Return a ``(height, width, channels)`` ``uint8`` array (needs numpy).

        Args:
            mode: ``"RGB"`` or ``"RGBA"``; defaults to :attr:`mode`.
        """
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - numpy is a test dep
            raise ImportError("to_numpy() requires numpy: pip install numpy") from exc
        mode = mode or self.mode
        if mode == "RGB":
            buf, ch = self.to_rgb(), 3
        elif mode == "RGBA":
            buf, ch = self.to_rgba(), 4
        else:
            raise BMPError(f"unknown mode {mode!r}")
        return np.frombuffer(buf, dtype=np.uint8).reshape(self.height, self.width, ch)

    def get_pixel(self, x: int, y: int) -> tuple[int, ...]:
        """Return the RGB (or RGBA) value at column ``x``, row ``y`` (0 = top).

        This decodes the whole image; use :meth:`to_rgb` for bulk access.
        """
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError(f"pixel ({x}, {y}) outside {self.width}x{self.height}")
        ch = 4 if self.mode == "RGBA" else 3
        buf = self.to_rgba() if ch == 4 else self.to_rgb()
        i = (y * self.width + x) * ch
        return tuple(buf[i : i + ch])

    # ------------------------------------------------------------------ encoding
    def to_bytes(self) -> bytes:
        """Return the file contents (identical to :attr:`data`)."""
        return self._data

    def save(self, path: StrPath | IO[bytes]) -> None:
        """Write the file to a path or binary file object."""
        if isinstance(path, (str, os.PathLike)):
            with open(path, "wb") as f:
                f.write(self._data)
        else:
            path.write(self._data)

    def convert(
        self,
        *,
        bits: int | None = None,
        top_down: bool | None = None,
        header: HeaderVersion | None = None,
    ) -> BMP:
        """Re-encode this image with a different storage format.

        Indexed targets (``bits <= 8``) keep the palette and need an indexed
        source; true-colour targets keep alpha when the source has it.
        """
        top_down = self.top_down if top_down is None else top_down
        if bits is not None and bits <= 8:
            if self.bits_per_pixel > 8:
                raise UnsupportedFormatError(
                    "cannot convert a true-colour image to an indexed format"
                )
            return BMP.from_pixels(
                self.width,
                self.height,
                self.to_indices(),
                mode="P",
                bits=bits,
                palette=self.palette,
                top_down=top_down,
                header=header,
            )
        if bits is None and self.bits_per_pixel <= 8:
            return BMP.from_pixels(
                self.width,
                self.height,
                self.to_indices(),
                mode="P",
                bits=self.bits_per_pixel,
                palette=self.palette,
                top_down=top_down,
                header=header,
            )
        if self.mode == "RGBA" and bits in (None, 32):
            return BMP.from_pixels(
                self.width,
                self.height,
                self.to_rgba(),
                mode="RGBA",
                top_down=top_down,
                header=header,
            )
        return BMP.from_pixels(
            self.width,
            self.height,
            self.to_rgb(),
            mode="RGB",
            bits=bits or (self.bits_per_pixel if self.bits_per_pixel > 8 else 24),
            top_down=top_down,
            header=header,
        )

    def info(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary of the headers."""
        h = self.header
        return {
            "signature": h.signature,
            "file_size": h.file_size,
            "pixel_offset": h.pixel_offset,
            "header": h.header_name,
            "header_size": h.header_size,
            "width": self.width,
            "height": self.height,
            "top_down": self.top_down,
            "bits_per_pixel": h.bits_per_pixel,
            "compression": h.compression_name,
            "image_size": h.image_size,
            "colors_used": h.colors_used,
            "palette_size": len(h.palette),
            "masks": {
                "red": h.red_mask,
                "green": h.green_mask,
                "blue": h.blue_mask,
                "alpha": h.alpha_mask,
            },
            "mode": self.mode,
            "x_pixels_per_meter": h.x_pixels_per_meter,
            "y_pixels_per_meter": h.y_pixels_per_meter,
        }

    def __repr__(self) -> str:
        return (
            f"<BMP {self.width}x{self.height} {self.bits_per_pixel}-bit "
            f"{self.header.compression_name} {self.header.header_name}>"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BMP):
            return NotImplemented
        return self._data == other._data

    def __hash__(self) -> int:
        return hash(self._data)

    # ------------------------------------------------- pybmp 1.x compatibility
    @staticmethod
    def PixelArraySize(BITSPERPIXEL: int, IMAGEWIDTH: int, IMAGEHEIGHT: int) -> int:  # noqa: N802, N803
        """Size of the padded pixel array (pybmp 1.x helper)."""
        return row_stride(BITSPERPIXEL, IMAGEWIDTH) * abs(IMAGEHEIGHT)

    def compression_method(self, compression: int) -> str | None:
        """Return (and log at DEBUG) the name of a compression code."""
        for key, value in self.COMPRESSION_DICT.items():
            if value == compression:
                logger.debug("Compression Method: %s", key)
                return key
        return None

    def unhexlify(self, bytedata: bytes | str) -> bytes:
        """Deprecated: use :func:`binascii.unhexlify`."""
        warnings.warn(
            "BMP.unhexlify is deprecated; use binascii.unhexlify",
            DeprecationWarning,
            stacklevel=2,
        )
        return binascii.unhexlify(bytedata)

    def bytes2int(self, bytedata: bytes | str) -> int:
        """Deprecated: decode little-endian hex digits to an int."""
        warnings.warn(
            "BMP.bytes2int is deprecated; use int.from_bytes(..., 'little')",
            DeprecationWarning,
            stacklevel=2,
        )
        return int.from_bytes(binascii.unhexlify(bytedata), "little")

    ID = _Legacy(lambda s: s.header.signature)
    SIZE = _Legacy(lambda s: s.header.file_size)
    RESERVED = _Legacy(lambda s: s.header.reserved1 | (s.header.reserved2 << 16))
    OFFSET = _Legacy(lambda s: s.header.pixel_offset)
    DIBHEADER = _Legacy(lambda s: s.header.header_size)
    WIDTH = _Legacy(lambda s: s.header.width)
    HEIGHT = _Legacy(lambda s: s.header.height)
    NCOLORPANES = _Legacy(lambda s: s.header.planes)
    NBITSPERPIXEL = _Legacy(lambda s: s.header.bits_per_pixel)
    SHAPE = _Legacy(lambda s: (s.header.width, s.header.height))
    PIXELARRAYSIZE = _Legacy(lambda s: s.header.stride * abs(s.header.height))
    PIXELARRAY = _Legacy(lambda s: s.pixel_array)
    COMPRESSION = _Legacy(lambda s: s.header.compression, _has_info)
    RAWIMGSIZE = _Legacy(lambda s: s.header.image_size, _has_info)
    HORIZONTALRES = _Legacy(lambda s: s.header.x_pixels_per_meter, _has_info)
    VERTICALRES = _Legacy(lambda s: s.header.y_pixels_per_meter, _has_info)
    NCOLORS = _Legacy(lambda s: s.header.colors_used, _has_info)
    NIMPCOLORS = _Legacy(lambda s: s.header.colors_important, _has_info)
    REDMASK = _Legacy(lambda s: _mask_bytes(s.header.red_mask), _has_v4)
    GREENMASK = _Legacy(lambda s: _mask_bytes(s.header.green_mask), _has_v4)
    BLUEMASK = _Legacy(lambda s: _mask_bytes(s.header.blue_mask), _has_v4)
    ALPHAMASK = _Legacy(lambda s: _mask_bytes(s.header.alpha_mask), _has_v4)
    CSTYPE = _Legacy(lambda s: s.header.color_space_type, _has_v4)
    COLORSPACEENDPOINTS = _Legacy(lambda s: s.header.endpoints, _has_v4)
    GAMMARED = _Legacy(lambda s: s.header.gamma_red, _has_v4)
    GAMMAGREEN = _Legacy(lambda s: s.header.gamma_green, _has_v4)
    GAMMABLUE = _Legacy(lambda s: s.header.gamma_blue, _has_v4)
