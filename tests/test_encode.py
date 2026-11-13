"""Unit tests for pybmp._encode."""

from __future__ import annotations

import io
import struct

import pytest

import pybmp
from pybmp import BMP, BMPError, UnsupportedFormatError, encode


def test_minimal_24bit_layout() -> None:
    data = encode(1, 1, b"\x01\x02\x03")
    sig, size, _, _, offset = struct.unpack_from("<2sIHHI", data)
    assert (sig, size, offset) == (b"BM", len(data), 54)
    assert data[54:] == b"\x03\x02\x01\x00"


def test_bottom_up_by_default_and_top_down_flag() -> None:
    rgb = bytes(range(6))  # 1x2
    bu = encode(1, 2, rgb)
    td = encode(1, 2, rgb, top_down=True)
    assert struct.unpack_from("<i", bu, 22)[0] == 2
    assert struct.unpack_from("<i", td, 22)[0] == -2
    assert bu[54:58] == bytes((5, 4, 3, 0))  # bottom row first
    assert td[54:58] == bytes((2, 1, 0, 0))


@pytest.mark.parametrize(
    ("header", "size"), [("core", 12), ("info", 40), ("v4", 108), ("v5", 124)]
)
def test_header_sizes(header: pybmp.HeaderVersion, size: int) -> None:
    data = encode(2, 2, bytes(12), header=header)
    assert struct.unpack_from("<I", data, 14)[0] == size
    assert BMP(data=data).header.header_size == size


def test_rgba_defaults_to_v4_bitfields() -> None:
    img = BMP(data=encode(1, 1, b"\x01\x02\x03\x04", mode="RGBA"))
    assert img.header.header_size == 108
    assert img.header.compression == pybmp.Compression.BI_BITFIELDS
    assert img.mode == "RGBA"


def test_16bit_packing() -> None:
    data = encode(1, 1, bytes((255, 0, 8)), bits=16)
    (px,) = struct.unpack_from("<H", data, 54)
    assert px == (31 << 10) | (0 << 5) | 1


def test_palette_written_as_rgbquad_and_core_rgbtriple() -> None:
    pal = [(1, 2, 3), (4, 5, 6)]
    info = encode(1, 1, b"\x01", mode="P", bits=1, palette=pal)
    assert info[54:62] == bytes((3, 2, 1, 0, 6, 5, 4, 0))
    core = encode(1, 1, b"\x01", mode="P", bits=1, palette=pal, header="core")
    assert core[26:32] == bytes((3, 2, 1, 6, 5, 4))


def test_resolution() -> None:
    data = encode(1, 1, bytes(3), pixels_per_meter=3780)
    assert struct.unpack_from("<ii", data, 38) == (3780, 3780)


def test_accepts_bytearray_and_memoryview() -> None:
    assert encode(1, 1, bytearray(3)) == encode(1, 1, memoryview(bytes(3)))


def test_write_to_path_and_file(tmp_path: object) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    p = tmp_path / "a.bmp"
    pybmp.write(p, 1, 1, b"\x01\x02\x03")
    buf = io.BytesIO()
    pybmp.write(buf, 1, 1, b"\x01\x02\x03")
    assert p.read_bytes() == buf.getvalue() == encode(1, 1, b"\x01\x02\x03")


@pytest.mark.parametrize(
    ("args", "kwargs", "exc", "match"),
    [
        ((0, 1, b""), {}, BMPError, "positive"),
        ((1, -1, b""), {}, BMPError, "positive"),
        ((1, 1, b"\x00\x00"), {}, BMPError, "expected 3 bytes"),
        ((1, 1, bytes(3)), {"mode": "CMYK"}, BMPError, "unknown mode"),
        ((1, 1, bytes(3)), {"bits": 8}, UnsupportedFormatError, "cannot be stored"),
        (
            (1, 1, bytes(4)),
            {"mode": "RGBA", "bits": 24},
            UnsupportedFormatError,
            "cannot",
        ),
        ((1, 1, bytes(3)), {"header": "v9"}, BMPError, "unknown header"),
        (
            (1, 1, bytes(4)),
            {"mode": "RGBA", "header": "info"},
            UnsupportedFormatError,
            "v4",
        ),
        (
            (1, 1, bytes(3)),
            {"bits": 32, "header": "core"},
            UnsupportedFormatError,
            "CORE",
        ),
        (
            (1, 1, bytes(3)),
            {"header": "core", "top_down": True},
            UnsupportedFormatError,
            "top-down",
        ),
        (
            (70000, 1, bytes(210000)),
            {"header": "core"},
            UnsupportedFormatError,
            "65535",
        ),
        ((1, 1, b"\x00"), {"mode": "P"}, BMPError, "requires a palette"),
        (
            (1, 1, b"\x00"),
            {"mode": "P", "bits": 1, "palette": [(0, 0, 0)] * 3},
            BMPError,
            "allows 2",
        ),
        ((1, 1, b"\x02"), {"mode": "P", "palette": [(0, 0, 0)]}, BMPError, "outside"),
        ((1, 1, b"\x00"), {"mode": "P", "palette": [(0, 0, 256)]}, BMPError, "0..255"),
    ],
)
def test_encode_errors(
    args: tuple[object, ...],
    kwargs: dict[str, object],
    exc: type[Exception],
    match: str,
) -> None:
    with pytest.raises(exc, match=match):
        encode(*args, **kwargs)  # type: ignore[arg-type]
