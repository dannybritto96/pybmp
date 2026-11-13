"""Lazy, memory-mapped BMP reading: :class:`LazyBMP` and :func:`open_lazy`."""

from __future__ import annotations

import contextlib
import mmap
import os
from dataclasses import replace
from typing import IO, TYPE_CHECKING, Any

from ._bmp import BMP, open_embedded
from ._constants import FILE_HEADER_SIZE, V5_HEADER_SIZE
from ._decode import (
    check_decodable,
    decode_indices,
    decode_rgb,
    has_alpha,
    indices_to_rgb,
    is_rle,
)
from ._errors import BMPError, TruncatedFileError, UnsupportedFormatError
from ._header import BMPHeader, parse_header

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

    import numpy as np
    from PIL import Image as PILImage

    from ._encode import Mode

__all__ = ["LazyBMP", "open_lazy"]

StrPath = str | os.PathLike[str]
Source = StrPath | IO[bytes] | bytes | bytearray | memoryview

#: Longest possible header block: file header, V5 header, 4 masks and the
#: largest palette parse_header will read (65536 RGBQUADs).
_HEADER_CAP = FILE_HEADER_SIZE + V5_HEADER_SIZE + 16 + 4 * (1 << 16)
#: Stored bytes decoded per chunk by :meth:`LazyBMP.iter_rows`.
_CHUNK_BYTES = 1 << 20


class LazyBMP:
    """A BMP whose pixels are read from the source only when asked for.

    Opening reads just the headers and palette. Rows are then decoded on
    demand, so a 4 GB bitmap can be inspected or streamed in constant memory::

        with pybmp.open_lazy("huge.bmp") as img:
            print(img.size, img.mode)
            top = img.read_rows(0, 16)        # first 16 rows, RGB, top-down
            for row in img.iter_rows():       # one row at a time
                ...

    Sources:

    * a path: memory-mapped (``use_mmap=True``, the default) or read with
      ``seek``/``read``; the file is closed by :meth:`close`;
    * a binary file object: read with ``seek``/``read`` starting at its current
      position; it stays open after :meth:`close` (the caller owns it);
    * ``bytes``, ``bytearray`` or ``memoryview``: used in place, without a copy.

    Uncompressed (``BI_RGB``) and bit-field files are read row by row.
    ``BI_RLE8`` / ``BI_RLE4`` rows can't be located without decoding
    everything before them, so the first row access decodes the whole image
    once and caches the palette indices (see :attr:`random_access`).
    """

    __slots__ = (
        "_base",
        "_buf",
        "_closed",
        "_file",
        "_indices",
        "_mmap",
        "_owns_file",
        "_size",
        "header",
    )

    def __init__(self, source: Source, *, use_mmap: bool = True) -> None:
        """Open ``source`` and parse its headers.

        Raises:
            BMPError: (a ``ValueError`` subclass) if the headers are invalid.
            OSError: if a path can't be opened.
        """
        self._buf: memoryview | None = None
        self._file: IO[bytes] | None = None
        self._mmap: mmap.mmap | None = None
        self._owns_file = False
        self._closed = False
        self._indices: bytes | None = None
        self._base = 0
        if isinstance(source, (bytes, bytearray, memoryview)):
            buf = memoryview(source)
            self._buf = buf if buf.format == "B" and buf.ndim == 1 else buf.cast("B")
            self._size = len(self._buf)
        elif isinstance(source, (str, os.PathLike)):
            self._file = open(source, "rb")  # noqa: SIM115 - closed by close()
            self._owns_file = True
            self._size = os.fstat(self._file.fileno()).st_size
            if use_mmap and self._size:
                try:
                    self._mmap = mmap.mmap(
                        self._file.fileno(), 0, access=mmap.ACCESS_READ
                    )
                except (OSError, ValueError):  # pragma: no cover - platform specific
                    self._mmap = None
        else:
            self._file = source
            self._base = source.tell()
            self._size = source.seek(0, os.SEEK_END) - self._base
        try:
            self.header: BMPHeader = parse_header(self._read_header_block())
        except BaseException:
            self.close()
            raise

    # ------------------------------------------------------------------- source
    def _read(self, offset: int, n: int) -> bytes:
        """Return up to ``n`` bytes starting ``offset`` bytes into the BMP."""
        if self._closed:
            raise ValueError("I/O operation on closed LazyBMP")
        n = max(0, min(n, self._size - offset))
        if n == 0:
            return b""
        if self._mmap is not None:
            return self._mmap[offset : offset + n]
        if self._buf is not None:
            return self._buf[offset : offset + n].tobytes()
        assert self._file is not None
        self._file.seek(self._base + offset)
        return self._file.read(n)

    def _read_header_block(self) -> bytes:
        head = self._read(0, FILE_HEADER_SIZE + 4)
        if len(head) < FILE_HEADER_SIZE + 4:
            return head  # parse_header raises TruncatedFileError
        offset = int.from_bytes(head[10:14], "little")
        header_size = min(int.from_bytes(head[14:18], "little"), V5_HEADER_SIZE)
        need = max(offset, FILE_HEADER_SIZE + header_size + 16)
        return self._read(0, min(need, _HEADER_CAP))

    def close(self) -> None:
        """Release the memory map and close a file opened from a path."""
        if self._closed:
            return
        self._closed = True
        if self._mmap is not None:
            self._mmap.close()
            self._mmap = None
        if self._buf is not None:
            self._buf.release()
            self._buf = None
        if self._file is not None and self._owns_file:
            self._file.close()
        self._file = None
        self._indices = None

    @property
    def closed(self) -> bool:
        """``True`` after :meth:`close`."""
        return self._closed

    def __enter__(self) -> LazyBMP:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __del__(self) -> None:
        # Best effort: close a file we opened. Never raise from a finaliser.
        with contextlib.suppress(Exception):
            self.close()

    # --------------------------------------------------------------- properties
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
        """Colour table as ``(r, g, b)`` tuples."""
        return self.header.palette

    @property
    def mode(self) -> str:
        """``"RGBA"`` if the pixel format has an alpha channel, else ``"RGB"``."""
        return "RGBA" if has_alpha(self.header) else "RGB"

    @property
    def file_size(self) -> int:
        """Size of the BMP data in bytes (the actual length, not the header field)."""
        return self._size

    @property
    def random_access(self) -> bool:
        """``False`` for RLE files, whose first row access decodes everything."""
        return not is_rle(self.header)

    @property
    def embedded_format(self) -> str | None:
        """``"jpeg"`` or ``"png"`` for ``BI_JPEG`` / ``BI_PNG`` files, else ``None``."""
        return self.header.embedded_format

    @property
    def embedded_image(self) -> bytes | None:
        """The embedded JPEG/PNG stream of a ``BI_JPEG`` / ``BI_PNG`` file, or ``None``.

        Only this stream is read from the source.
        """
        if self.header.embedded_format is None:
            return None
        return self._compressed_stream()

    def open_embedded(self) -> PILImage.Image:
        """Decode the embedded JPEG/PNG stream with Pillow (optional dependency)."""
        return open_embedded(self.embedded_image, self.header)

    # ----------------------------------------------------------------- decoding
    def _compressed_stream(self) -> bytes:
        h = self.header
        if h.pixel_offset > self._size:
            raise TruncatedFileError(
                f"pixel data offset {h.pixel_offset} is past end of file"
            )
        length = h.image_size or self._size - h.pixel_offset
        data = self._read(h.pixel_offset, length)
        if len(data) < length:
            raise TruncatedFileError("compressed pixel data is truncated")
        return data

    def _rle_indices(self) -> bytes:
        if self._indices is None:
            stream = self._compressed_stream()
            sub = replace(self.header, pixel_offset=0, image_size=len(stream))
            self._indices = decode_indices(stream, sub)
        return self._indices

    def _span(self, start: int, stop: int | None) -> tuple[int, int]:
        lo, hi, _ = slice(start, stop).indices(self.height)
        return lo, max(lo, hi)

    def _resolve_mode(self, mode: str | None) -> str:
        mode = mode or self.mode
        if mode not in ("RGB", "RGBA", "P"):
            raise BMPError(f"unknown mode {mode!r}; expected 'RGB', 'RGBA' or 'P'")
        return mode

    def _decode(self, lo: int, hi: int, mode: str) -> bytes:
        h = self.header
        check_decodable(h)
        count = hi - lo
        if mode == "P" and h.bits_per_pixel > 8:
            raise UnsupportedFormatError(
                f"{h.bits_per_pixel}-bit images have no palette indices"
            )
        if is_rle(h):
            w = h.width
            idx = self._rle_indices()[lo * w : hi * w]
            if mode == "P":
                return idx
            return indices_to_rgb(idx, h.palette, alpha=mode == "RGBA")
        stride = h.stride
        first = lo if h.top_down else self.height - hi
        need = count * stride
        raw = self._read(h.pixel_offset + first * stride, need)
        if len(raw) < need:
            raise TruncatedFileError(
                f"rows {lo}..{hi - 1} need {need} bytes from offset "
                f"{h.pixel_offset + first * stride}, but only {len(raw)} are present"
            )
        sub = replace(h, height=-count if h.top_down else count, pixel_offset=0)
        if mode == "P":
            return decode_indices(raw, sub)
        return decode_rgb(raw, sub, alpha=mode == "RGBA")

    def read_rows(
        self, start: int = 0, stop: int | None = None, *, mode: Mode | None = None
    ) -> bytes:
        """Decode rows ``start`` to ``stop - 1`` (0 = top), slice-style.

        Args:
            start: First row; negative values count from the bottom.
            stop: One past the last row; ``None`` means the bottom row.
            mode: ``"RGB"`` (3 bytes per pixel), ``"RGBA"`` (4) or ``"P"``
                (one palette index per pixel, <= 8-bit images). Defaults to
                :attr:`mode`.

        Returns:
            Packed pixels, rows top-down, ``width * channels`` bytes per row.
        """
        resolved = self._resolve_mode(mode)
        lo, hi = self._span(start, stop)
        if lo == hi:
            self._read(0, 0)  # still raise on a closed image
            return b""
        return self._decode(lo, hi, resolved)

    def row(self, y: int, *, mode: Mode | None = None) -> bytes:
        """Decode one row (0 = top; negative counts from the bottom)."""
        if not -self.height <= y < self.height:
            raise IndexError(f"row {y} outside 0..{self.height - 1}")
        y %= self.height
        return self.read_rows(y, y + 1, mode=mode)

    def iter_rows(
        self,
        start: int = 0,
        stop: int | None = None,
        *,
        mode: Mode | None = None,
        chunk_rows: int | None = None,
    ) -> Iterator[bytes]:
        """Yield decoded rows top-down, reading ``chunk_rows`` rows at a time.

        ``chunk_rows`` defaults to about 1 MiB of stored pixel data.
        """
        resolved = self._resolve_mode(mode)
        lo, hi = self._span(start, stop)
        if chunk_rows is None:
            chunk_rows = max(1, _CHUNK_BYTES // max(1, self.header.stride))
        if chunk_rows <= 0:
            raise ValueError("chunk_rows must be positive")
        channels = {"RGB": 3, "RGBA": 4, "P": 1}[resolved]
        row_len = self.width * channels
        for y in range(lo, hi, chunk_rows):
            block = self._decode(y, min(hi, y + chunk_rows), resolved)
            mv = memoryview(block)
            for s in range(0, len(block), row_len):
                yield mv[s : s + row_len].tobytes()

    def get_pixel(self, x: int, y: int) -> tuple[int, ...]:
        """Return the RGB (or RGBA) value at column ``x``, row ``y`` (0 = top).

        Only row ``y`` is read and decoded.
        """
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError(f"pixel ({x}, {y}) outside {self.width}x{self.height}")
        ch = 4 if self.mode == "RGBA" else 3
        row = self.read_rows(y, y + 1)
        return tuple(row[x * ch : (x + 1) * ch])

    def to_numpy(
        self, start: int = 0, stop: int | None = None, *, mode: Mode | None = None
    ) -> np.ndarray[Any, Any]:
        """Return rows ``start:stop`` as a ``(rows, width, channels)`` uint8 array.

        Mode ``"P"`` gives a ``(rows, width)`` array of palette indices.
        """
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - numpy is a test dep
            raise ImportError("to_numpy() requires numpy: pip install numpy") from exc
        resolved = self._resolve_mode(mode)
        buf = self.read_rows(start, stop, mode=mode)
        arr = np.frombuffer(buf, dtype=np.uint8)
        if resolved == "P":
            return arr.reshape(-1, self.width)
        return arr.reshape(-1, self.width, 4 if resolved == "RGBA" else 3)

    def load(self) -> BMP:
        """Read the whole file into an eager :class:`BMP`."""
        return BMP(data=self._read(0, self._size))

    def __repr__(self) -> str:
        state = " closed" if self._closed else ""
        return (
            f"<LazyBMP {self.width}x{self.height} {self.bits_per_pixel}-bit "
            f"{self.header.compression_name} {self.header.header_name}{state}>"
        )


def open_lazy(source: Source, *, use_mmap: bool = True) -> LazyBMP:
    """Open a BMP lazily: headers now, pixels on demand. See :class:`LazyBMP`."""
    return LazyBMP(source, use_mmap=use_mmap)
