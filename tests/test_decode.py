"""Unit tests for pybmp._decode using hand-built files."""

from __future__ import annotations

import struct
from dataclasses import replace
from typing import Any

import pytest

import pybmp
from helpers import build_bmp, pad_rows, random_bytes
from pybmp import (
    BMP,
    InvalidBMPError,
    TruncatedFileError,
    UnsupportedFormatError,
    _decode,
)


def _bgr(rgb: bytes) -> bytes:
    out = bytearray(rgb)
    out[0::3], out[2::3] = rgb[2::3], rgb[0::3]
    return bytes(out)


@pytest.mark.parametrize("top_down", [False, True])
@pytest.mark.parametrize("width", [1, 2, 3, 5, 8])
def test_24bit_rows_and_padding(width: int, top_down: bool) -> None:
    height = 3
    rgb = random_bytes(width * height * 3, seed=width)
    rows = [_bgr(rgb[y * width * 3 : (y + 1) * width * 3]) for y in range(height)]
    stored = rows if top_down else rows[::-1]
    data = build_bmp(
        width=width,
        height=-height if top_down else height,
        bpp=24,
        pixel_data=pad_rows(stored),
    )
    assert BMP(data=data).to_rgb() == rgb


@pytest.mark.parametrize("bpp", [1, 2, 4, 8])
@pytest.mark.parametrize("width", [1, 3, 7, 9, 17])
@pytest.mark.parametrize("top_down", [False, True])
def test_indexed_depths(bpp: int, width: int, top_down: bool) -> None:
    height = 2
    ncol = 1 << bpp
    idx = random_bytes(width * height, seed=bpp * 31 + width, limit=ncol)
    per = 8 // bpp
    rows = []
    for y in range(height):
        row = idx[y * width : (y + 1) * width]
        packed = bytearray()
        for i in range(0, width, per):
            b = 0
            for k, v in enumerate(row[i : i + per]):
                b |= v << (8 - bpp * (k + 1))
            packed.append(b)
        rows.append(bytes(packed))
    stored = rows if top_down else rows[::-1]
    pal = [(i, 255 - i, (i * 3) % 256) for i in range(ncol)]
    data = build_bmp(
        width=width,
        height=-height if top_down else height,
        bpp=bpp,
        palette=pal,
        pixel_data=pad_rows(stored),
    )
    img = BMP(data=data)
    assert img.to_indices() == idx
    assert img.to_rgb() == b"".join(bytes(pal[i]) for i in idx)


def test_index_outside_palette_is_black() -> None:
    data = build_bmp(
        width=2, height=1, bpp=8, palette=[(9, 9, 9)], pixel_data=b"\x00\x05\x00\x00"
    )
    assert BMP(data=data).to_rgb() == b"\x09\x09\x09\x00\x00\x00"


def test_core_header_palette() -> None:
    data = build_bmp(
        header_size=12,
        width=2,
        height=1,
        bpp=1,
        palette=[(10, 20, 30), (40, 50, 60)],
        pixel_data=b"\x40\x00\x00\x00",
    )
    assert BMP(data=data).to_rgb() == bytes((10, 20, 30, 40, 50, 60))


def test_16bit_555_default() -> None:
    px = (31 << 10) | (0 << 5) | 15  # r=31,g=0,b=15
    data = build_bmp(width=1, height=1, bpp=16, pixel_data=struct.pack("<HH", px, 0))
    assert BMP(data=data).to_rgb() == bytes((255, 0, 15 * 255 // 31))


@pytest.mark.parametrize("use_numpy", [True, False])
def test_16bit_565_bitfields(use_numpy: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    if not use_numpy:
        monkeypatch.setattr(_decode, "_np", None)
    px = [(31 << 11) | (63 << 5) | 0, (0 << 11) | (32 << 5) | 31, 0x1234]
    data = build_bmp(
        width=3,
        height=1,
        bpp=16,
        compression=3,
        masks=(0xF800, 0x07E0, 0x001F),
        pixel_data=struct.pack("<3H", *px) + b"\0\0",
    )
    expected = b"".join(
        bytes(
            ((p >> 11) * 255 // 31, ((p >> 5) & 63) * 255 // 63, (p & 31) * 255 // 31)
        )
        for p in px
    )
    assert BMP(data=data).to_rgb() == expected


@pytest.mark.parametrize("use_numpy", [True, False])
def test_16bit_argb4444(use_numpy: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    if not use_numpy:
        monkeypatch.setattr(_decode, "_np", None)
    data = build_bmp(
        header_size=56,
        width=1,
        height=1,
        bpp=16,
        compression=3,
        masks=(0x0F00, 0x00F0, 0x000F, 0xF000),
        pixel_data=struct.pack("<H", 0x8F0A) + b"\0\0",
    )
    img = BMP(data=data)
    assert img.mode == "RGBA"
    assert img.to_rgba() == bytes((255, 0, 10 * 17, 8 * 17))
    assert img.to_rgb() == bytes((255, 0, 170))


def test_32bit_bi_rgb_ignores_fourth_byte() -> None:
    data = build_bmp(
        width=2, height=1, bpp=32, pixel_data=bytes((1, 2, 3, 99, 4, 5, 6, 7))
    )
    img = BMP(data=data)
    assert img.mode == "RGB"
    assert img.to_rgb() == bytes((3, 2, 1, 6, 5, 4))
    assert img.to_rgba() == bytes((3, 2, 1, 255, 6, 5, 4, 255))


@pytest.mark.parametrize("header_size", [40, 56, 108, 124])
def test_32bit_aligned_bitfields_with_alpha(header_size: int) -> None:
    comp = 6 if header_size == 40 else 3
    data = build_bmp(
        header_size=header_size,
        width=1,
        height=1,
        bpp=32,
        compression=comp,
        masks=(0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000),
        pixel_data=bytes((10, 20, 30, 40)),
    )
    img = BMP(data=data)
    assert img.mode == "RGBA"
    assert img.to_rgba() == bytes((10, 20, 30, 40))


@pytest.mark.parametrize("use_numpy", [True, False])
def test_32bit_unaligned_bitfields(
    use_numpy: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not use_numpy:
        monkeypatch.setattr(_decode, "_np", None)
    # A2R10G10B10
    r, g, b, a = 1023, 512, 0, 3
    px = (a << 30) | (r << 20) | (g << 10) | b
    data = build_bmp(
        header_size=108,
        width=1,
        height=1,
        bpp=32,
        compression=3,
        masks=(0x3FF00000, 0x000FFC00, 0x000003FF, 0xC0000000),
        pixel_data=struct.pack("<I", px),
    )
    img = BMP(data=data)
    assert img.to_rgba() == bytes((255, 512 * 255 // 1023, 0, 255))
    data_noalpha = build_bmp(
        header_size=40,
        width=1,
        height=1,
        bpp=32,
        compression=3,
        masks=(0x3FF00000, 0x000FFC00, 0),
        pixel_data=struct.pack("<I", px),
    )
    assert BMP(data=data_noalpha).to_rgb() == bytes((255, 127, 0))


def test_v4_bi_rgb_ignores_masks() -> None:
    data = build_bmp(
        header_size=108,
        width=1,
        height=1,
        bpp=32,
        masks=(0xFF, 0xFF00, 0xFF0000, 0xFF000000),
        pixel_data=bytes((1, 2, 3, 4)),
    )
    img = BMP(data=data)
    assert img.mode == "RGB"
    assert img.to_rgb() == bytes((3, 2, 1))


def _rle(
    header_kw: dict[str, Any], stream: bytes, pal: list[tuple[int, int, int]]
) -> BMP:
    return BMP(data=build_bmp(pixel_data=stream, palette=pal, **header_kw))


def test_rle8_runs_absolute_delta_eol_eof() -> None:
    pal = [(i, i, i) for i in range(256)]
    stream = bytes(
        [
            3,
            7,  # run of three 7s
            0,
            3,
            1,
            2,
            3,
            0,  # absolute run 1,2,3 (padded to word)
            0,
            0,  # end of line
            0,
            2,
            2,
            0,  # delta: +2 x, +0 y
            2,
            9,  # run of two 9s
            0,
            1,  # end of bitmap
        ]
    )
    img = _rle({"width": 6, "height": 2, "bpp": 8, "compression": 1}, stream, pal)
    # row 0 (bottom) = 7 7 7 1 2 3 ; row 1 (top) = 0 0 9 9 0 0
    assert img.to_indices() == bytes([0, 0, 9, 9, 0, 0, 7, 7, 7, 1, 2, 3])
    assert img.to_rgb()[:3] == b"\x00\x00\x00"


def test_rle4() -> None:
    pal = [(i * 16, 0, 0) for i in range(16)]
    stream = bytes(
        [
            5,
            0x12,  # 1 2 1 2 1
            0,
            3,
            0x34,
            0x50,  # absolute 3 4 5
            0,
            0,
            4,
            0xAB,  # A B A B
            0,
            1,
        ]
    )
    img = _rle({"width": 8, "height": 2, "bpp": 4, "compression": 2}, stream, pal)
    assert img.to_indices() == bytes(
        [10, 11, 10, 11, 0, 0, 0, 0, 1, 2, 1, 2, 1, 3, 4, 5]
    )


def test_rle_clips_overlong_runs_and_missing_eof() -> None:
    pal = [(0, 0, 0), (1, 1, 1)]
    stream = bytes([9, 1, 0, 4, 1, 1, 1, 1])  # run too long, absolute past width
    img = _rle({"width": 3, "height": 2, "bpp": 8, "compression": 1}, stream, pal)
    assert img.to_indices() == bytes([0, 0, 0, 1, 1, 1])


def test_rle_top_down() -> None:
    pal = [(0, 0, 0), (1, 1, 1)]
    img = _rle(
        {"width": 2, "height": -2, "bpp": 8, "compression": 1},
        bytes([2, 1, 0, 0, 2, 0, 0, 1]),
        pal,
    )
    assert img.to_indices() == bytes([1, 1, 0, 0])


@pytest.mark.parametrize("stream", [bytes([0, 2, 1]), bytes([0, 5, 1, 2])])
def test_rle_truncated(stream: bytes) -> None:
    pal = [(0, 0, 0)]
    img = _rle({"width": 8, "height": 2, "bpp": 8, "compression": 1}, stream, pal)
    with pytest.raises(TruncatedFileError):
        img.to_indices()


def test_rle_image_size_past_end() -> None:
    data = build_bmp(
        width=2,
        height=1,
        bpp=8,
        compression=1,
        palette=[(0, 0, 0)],
        pixel_data=b"\x00\x01",
        image_size=50,
    )
    with pytest.raises(TruncatedFileError):
        BMP(data=data).pixel_array  # noqa: B018


def test_rle_without_image_size_reads_to_end() -> None:
    data = build_bmp(
        width=2,
        height=1,
        bpp=8,
        compression=1,
        palette=[(0, 0, 0), (5, 5, 5)],
        pixel_data=b"\x02\x01\x00\x01",
        image_size=0,
    )
    img = BMP(data=data)
    assert img.pixel_array == b"\x02\x01\x00\x01"
    assert img.to_rgb() == b"\x05" * 6


def test_offset_past_end_for_compressed() -> None:
    data = build_bmp(
        width=2,
        height=1,
        bpp=8,
        compression=1,
        palette=[(0, 0, 0)],
        pixel_data=b"",
        offset_adjust=0,
    )
    data = data[:-4]  # drop part of the palette region -> offset > len
    with pytest.raises(TruncatedFileError):
        BMP(data=data).pixel_array  # noqa: B018


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"bpp": 24, "compression": 4}, "BI_JPEG"),
        ({"bpp": 24, "compression": 5}, "BI_PNG"),
        ({"bpp": 24, "compression": 1}, "BI_RLE8"),
        ({"bpp": 8, "compression": 2}, "BI_RLE4"),
        ({"bpp": 24, "compression": 3}, "BI_BITFIELDS"),
        ({"bpp": 24, "compression": 42}, "compression 42"),
        ({"bpp": 24, "compression": 11}, "BI_CMYK"),
    ],
)
def test_unsupported_compression(kw: dict[str, Any], match: str) -> None:
    pal = [(0, 0, 0)] * 256 if kw["bpp"] <= 8 else None
    data = build_bmp(
        width=1,
        height=1,
        pixel_data=bytes(16),
        palette=pal,
        masks=(1, 2, 4) if kw["compression"] == 3 else None,
        **kw,
    )
    with pytest.raises(UnsupportedFormatError, match=match):
        BMP(data=data).to_rgb()


@pytest.mark.parametrize("compression", [3, 4])
def test_os2_huffman_rle24_unsupported(compression: int) -> None:
    data = build_bmp(
        header_size=64,
        width=1,
        height=1,
        bpp=24,
        compression=compression,
        pixel_data=bytes(4),
    )
    with pytest.raises(UnsupportedFormatError, match="OS/2"):
        BMP(data=data).to_rgb()


def test_truncated_pixel_array() -> None:
    data = build_bmp(width=4, height=4, bpp=24, pixel_data=bytes(48))
    for cut in (1, 10, 47):
        img = BMP(data=data[:-cut])
        with pytest.raises(TruncatedFileError, match="pixel array"):
            img.to_rgb()


def test_indices_on_true_colour() -> None:
    img = BMP(data=build_bmp(width=1, height=1, bpp=24, pixel_data=bytes(4)))
    with pytest.raises(UnsupportedFormatError):
        img.to_indices()


def test_decode_rgb_requires_palette() -> None:
    img = BMP(
        data=build_bmp(
            width=1, height=1, bpp=8, palette=[(0, 0, 0)], pixel_data=bytes(4)
        )
    )
    header = replace(img.header, palette=())
    with pytest.raises(InvalidBMPError, match="palette"):
        _decode.decode_rgb(img.data, header)


def test_effective_masks_and_alpha() -> None:
    h = pybmp.parse_header(build_bmp(width=1, height=1, bpp=24, pixel_data=bytes(4)))
    assert _decode.effective_masks(h) == (0, 0, 0, 0)
    assert not _decode.has_alpha(h)


def test_rgb_to_rgba() -> None:
    assert _decode.rgb_to_rgba(b"\x01\x02\x03") == b"\x01\x02\x03\xff"


@pytest.mark.parametrize("use_numpy", [True, False])
def test_16bit_wide_channel_uses_lookup_table(
    use_numpy: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not use_numpy:
        monkeypatch.setattr(_decode, "_np", None)
    # 12-bit red channel, 4-bit green, no blue.
    px = [0xFFF0, 0x0805, 0x0000]
    data = build_bmp(
        width=3,
        height=1,
        bpp=16,
        compression=3,
        masks=(0xFFF0, 0x000F, 0),
        pixel_data=struct.pack("<3H", *px) + b"\0\0",
    )
    expected = b"".join(
        bytes(((p >> 4) * 255 // 4095, (p & 15) * 255 // 15, 0)) for p in px
    )
    assert BMP(data=data).to_rgb() == expected


def test_or_bytes() -> None:
    from pybmp._util import or_bytes

    assert or_bytes(b"\x01\x10", b"\x02\x20") == b"\x03\x30"
    assert or_bytes(b"", b"") == b""
