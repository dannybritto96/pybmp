"""Tests for the BMP class, pybmp 1.x compatibility and the PR #1 regression."""

from __future__ import annotations

import binascii
import io
import logging
from pathlib import Path

import pytest

import pybmp
from helpers import build_bmp, pad_rows, random_bytes
from pybmp import BMP, BMPError, HeaderNotSupported, InvalidBMPError, encode


def _sample(width: int = 5, height: int = 3) -> tuple[bytes, bytes]:
    rgb = random_bytes(width * height * 3, seed=7)
    return rgb, encode(width, height, rgb)


# ---------------------------------------------------------------- PR #1 regression
@pytest.mark.parametrize("header_size", [12, 16, 40, 52, 56, 64, 108, 124])
@pytest.mark.parametrize("source", ["data", "hexdata", "filename"])
def test_pr1_pixelarray_is_whole_image_from_offset(
    header_size: int, source: str, tmp_path: Path
) -> None:
    """Regression for PR #1: PIXELARRAY used to hold only half the image.

    pybmp 1.x sliced the *hexlified* file with byte counts (so it read half the
    bytes), started at a hard-coded position instead of ``bfOffBits`` and
    mis-sized several header fields. Every header variant must now return the
    full ``stride * height`` bytes that start at the pixel-data offset.
    """
    width, height = 5, 4  # odd width -> 1 byte of padding per 24-bit row
    stride = 16
    pixel_data = random_bytes(stride * height, seed=header_size)
    data = build_bmp(
        header_size=header_size,
        width=width,
        height=height,
        bpp=24,
        pixel_data=pixel_data,
    )
    if source == "data":
        img = BMP(data=data)
    elif source == "hexdata":
        img = BMP(hexdata=binascii.hexlify(data))
    else:
        path = tmp_path / "x.bmp"
        path.write_bytes(data)
        img = BMP(filename=str(path))
    offset = int.from_bytes(data[10:14], "little")
    assert offset == img.OFFSET
    assert len(img.PIXELARRAY) == stride * height == img.PIXELARRAYSIZE
    assert img.PIXELARRAY == data[offset:] == pixel_data


def test_pr1_with_palette_offset() -> None:
    """The pixel array must start after the palette, not at a fixed position."""
    idx_rows = [bytes([1, 2, 3]), bytes([3, 2, 1])]
    pal = [(i, i, i) for i in range(4)]
    data = build_bmp(
        width=3, height=2, bpp=8, palette=pal, pixel_data=pad_rows(idx_rows)
    )
    img = BMP(data=data)
    assert img.OFFSET == 14 + 40 + 16
    assert pad_rows(idx_rows) == img.PIXELARRAY


def test_pr1_header_fields_are_correct() -> None:
    """pybmp 1.x read RAWIMGSIZE from 3 bytes and shifted later fields."""
    data = encode(3, 2, bytes(18), pixels_per_meter=3780)
    img = BMP(data=data)
    assert img.RAWIMGSIZE == 24
    assert (img.HORIZONTALRES, img.VERTICALRES) == (3780, 3780)
    assert (img.NCOLORS, img.NIMPCOLORS) == (0, 0)


# ------------------------------------------------------------ legacy attributes
def test_legacy_attributes_info_header() -> None:
    _, data = _sample()
    img = BMP(hexdata=binascii.hexlify(data))
    assert img.ID == "BM"
    assert len(data) == img.SIZE
    assert img.RESERVED == 0
    assert img.DIBHEADER == 40
    assert (img.WIDTH, img.HEIGHT, img.SHAPE) == (5, 3, (5, 3))
    assert img.NCOLORPANES == 1
    assert img.NBITSPERPIXEL == 24
    assert img.COMPRESSION == 0
    with pytest.raises(AttributeError, match="REDMASK"):
        img.REDMASK  # noqa: B018


def test_legacy_attributes_v4() -> None:
    img = BMP(data=encode(1, 1, bytes(4), mode="RGBA"))
    assert (0xFF0000).to_bytes(4, "little") == img.REDMASK
    assert (0xFF00).to_bytes(4, "little") == img.GREENMASK
    assert (0xFF).to_bytes(4, "little") == img.BLUEMASK
    assert (0xFF000000).to_bytes(4, "little") == img.ALPHAMASK
    assert img.CSTYPE == 0x73524742
    assert len(img.COLORSPACEENDPOINTS) == 36
    assert (img.GAMMARED, img.GAMMAGREEN, img.GAMMABLUE) == (0, 0, 0)


def test_legacy_core_header_has_no_compression() -> None:
    img = BMP(data=encode(1, 1, bytes(3), header="core"))
    with pytest.raises(AttributeError):
        img.COMPRESSION  # noqa: B018
    assert img.SHAPE == (1, 1)


def test_legacy_top_down_height_is_signed() -> None:
    img = BMP(data=encode(2, 3, bytes(18), top_down=True))
    assert img.HEIGHT == -3
    assert img.SHAPE == (2, -3)
    assert img.size == (2, 3)
    assert img.PIXELARRAYSIZE == 24


def test_legacy_helpers(caplog: pytest.LogCaptureFixture) -> None:
    _, data = _sample()
    img = BMP(data=data)
    assert BMP.PixelArraySize(24, 5, -3) == 48
    assert img.PixelArraySize(1, 9, 2) == 8
    with caplog.at_level(logging.DEBUG, logger="pybmp2"):
        assert img.compression_method(3) == "BI_BITFIELDS"
    assert "BI_BITFIELDS" in caplog.text
    assert img.compression_method(99) is None
    assert BMP.COMPRESSION_DICT["BI_RLE8"] == 1
    with pytest.deprecated_call():
        assert img.unhexlify(b"4142") == b"AB"
    with pytest.deprecated_call():
        assert img.bytes2int(b"0100") == 1
    assert isinstance(BMP.__dict__["ID"], object)
    assert pybmp.name == "pybmp2"


def test_class_access_to_legacy_descriptor() -> None:
    assert BMP.WIDTH is BMP.__dict__["WIDTH"]


# ------------------------------------------------------------------- class API
def test_constructors(tmp_path: Path) -> None:
    rgb, data = _sample()
    path = tmp_path / "s.bmp"
    path.write_bytes(data)
    variants = [
        BMP(str(path)),
        BMP(path),
        BMP.open(path),
        BMP.open(io.BytesIO(data)),
        pybmp.open(path),
        BMP.from_bytes(bytearray(data)),
        BMP(data=memoryview(data)),
        BMP(hexdata=binascii.hexlify(data).decode()),
    ]
    for img in variants:
        assert img == variants[0]
        assert img.to_rgb() == rgb
    assert len({hash(v) for v in variants}) == 1
    assert BMP(data=data) != BMP(data=encode(1, 1, bytes(3)))
    assert BMP(data=data).__eq__(object()) is NotImplemented


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"filename": "a", "data": b"x"}, {"hexdata": "00", "data": b"x"}],
)
def test_exactly_one_source(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        BMP(**kwargs)  # type: ignore[arg-type]


def test_bad_hexdata() -> None:
    with pytest.raises(InvalidBMPError, match="hex"):
        BMP(hexdata="zz")
    with pytest.raises(InvalidBMPError, match="hex"):
        BMP(hexdata="abc")


def test_errors_are_value_errors() -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - 1.x compatibility
        BMP(data=b"not a bmp at all, definitely")
    assert issubclass(HeaderNotSupported, BMPError)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        BMP(tmp_path / "nope.bmp")


def test_properties_and_repr() -> None:
    img = BMP(data=encode(3, 2, bytes(6), mode="P", bits=4, palette=[(1, 2, 3)]))
    assert img.width == 3
    assert img.height == 2
    assert img.bits_per_pixel == 4
    assert not img.top_down
    assert img.mode == "RGB"
    assert img.palette == ((1, 2, 3),)
    assert repr(img) == "<BMP 3x2 4-bit BI_RGB BITMAPINFOHEADER>"
    info = img.info()
    assert info["palette_size"] == 1
    assert info["header"] == "BITMAPINFOHEADER"
    assert img.to_bytes() == img.data


def test_save(tmp_path: Path) -> None:
    _, data = _sample()
    img = BMP(data=data)
    img.save(tmp_path / "o.bmp")
    buf = io.BytesIO()
    img.save(buf)
    assert (tmp_path / "o.bmp").read_bytes() == buf.getvalue() == data


def test_get_pixel() -> None:
    rgb, data = _sample()
    img = BMP(data=data)
    assert img.get_pixel(0, 0) == tuple(rgb[:3])
    assert img.get_pixel(4, 2) == tuple(rgb[-3:])
    rgba = BMP(data=encode(1, 1, b"\x01\x02\x03\x04", mode="RGBA"))
    assert rgba.get_pixel(0, 0) == (1, 2, 3, 4)
    with pytest.raises(IndexError):
        img.get_pixel(5, 0)
    with pytest.raises(IndexError):
        img.get_pixel(0, -1)


def test_to_numpy() -> None:
    np = pytest.importorskip("numpy")
    rgb, data = _sample()
    img = BMP(data=data)
    arr = img.to_numpy()
    assert arr.shape == (3, 5, 3)
    assert arr.dtype == np.uint8
    assert arr.tobytes() == rgb
    assert img.to_numpy("RGBA").shape == (3, 5, 4)
    with pytest.raises(BMPError):
        img.to_numpy("CMYK")


def test_convert_true_colour_to_indexed_is_rejected() -> None:
    _, data = _sample()
    with pytest.raises(pybmp.UnsupportedFormatError):
        BMP(data=data).convert(bits=8)
