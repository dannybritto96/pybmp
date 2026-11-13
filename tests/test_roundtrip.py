"""Round-trip encode -> decode across depths, headers, orientations and widths."""

from __future__ import annotations

import pytest

from helpers import random_bytes
from pybmp import BMP, HeaderVersion, encode

WIDTHS = [1, 2, 3, 5, 7, 13, 31, 33]
HEADERS: list[HeaderVersion] = ["info", "v4", "v5"]


def _quantise555(rgb: bytes) -> bytes:
    return bytes((v >> 3) * 255 // 31 for v in rgb)


@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("top_down", [False, True])
@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("bits", [16, 24, 32])
def test_rgb_roundtrip(
    bits: int, width: int, top_down: bool, header: HeaderVersion
) -> None:
    height = 4
    rgb = random_bytes(width * height * 3, seed=width * bits)
    img = BMP(
        data=encode(width, height, rgb, bits=bits, top_down=top_down, header=header)
    )
    assert img.size == (width, height)
    assert img.top_down is top_down
    assert img.bits_per_pixel == bits
    expected = _quantise555(rgb) if bits == 16 else rgb
    assert img.to_rgb() == expected
    # Re-encoding the decoded pixels is lossless and byte-identical.
    again = encode(
        width, height, img.to_rgb(), bits=bits, top_down=top_down, header=header
    )
    assert again == img.data


@pytest.mark.parametrize("header", ["v4", "v5"])
@pytest.mark.parametrize("top_down", [False, True])
@pytest.mark.parametrize("width", WIDTHS)
def test_rgba_roundtrip(width: int, top_down: bool, header: HeaderVersion) -> None:
    rgba = random_bytes(width * 3 * 4, seed=width)
    img = BMP(
        data=encode(width, 3, rgba, mode="RGBA", top_down=top_down, header=header)
    )
    assert img.mode == "RGBA"
    assert img.to_rgba() == rgba
    rgb = bytearray(width * 3 * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = rgba[0::4], rgba[1::4], rgba[2::4]
    assert img.to_rgb() == rgb


@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("top_down", [False, True])
@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("bits", [1, 2, 4, 8])
def test_indexed_roundtrip(
    bits: int, width: int, top_down: bool, header: HeaderVersion
) -> None:
    height = 3
    pal = [(i, (i * 7) % 256, 255 - i) for i in range(1 << bits)]
    idx = random_bytes(width * height, seed=bits + width, limit=1 << bits)
    img = BMP(
        data=encode(
            width,
            height,
            idx,
            mode="P",
            bits=bits,
            palette=pal,
            top_down=top_down,
            header=header,
        )
    )
    assert img.to_indices() == idx
    assert img.palette == tuple(pal)
    assert img.to_rgb() == b"".join(bytes(pal[i]) for i in idx)


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("bits", [1, 4, 8, 24])
def test_core_header_roundtrip(bits: int, width: int) -> None:
    height = 2
    if bits == 24:
        px = random_bytes(width * height * 3, seed=width)
        img = BMP(data=encode(width, height, px, header="core"))
        assert img.to_rgb() == px
    else:
        pal = [(i, i, i) for i in range(1 << bits)]
        px = random_bytes(width * height, seed=width, limit=1 << bits)
        img = BMP(
            data=encode(
                width, height, px, mode="P", bits=bits, palette=pal, header="core"
            )
        )
        assert img.to_indices() == px
    assert img.header.header_size == 12


def test_short_palette() -> None:
    pal = [(9, 8, 7), (1, 2, 3)]
    img = BMP(data=encode(4, 1, bytes([0, 1, 1, 0]), mode="P", bits=8, palette=pal))
    assert img.header.colors_used == 2
    assert img.to_rgb() == bytes((9, 8, 7, 1, 2, 3, 1, 2, 3, 9, 8, 7))


@pytest.mark.parametrize(
    ("bits", "top_down", "header"),
    [(None, None, None), (24, True, "v5"), (32, False, "info"), (16, None, None)],
)
def test_convert_true_colour(
    bits: int | None, top_down: bool | None, header: HeaderVersion | None
) -> None:
    rgb = random_bytes(5 * 3 * 3)
    src = BMP.from_pixels(5, 3, rgb)
    out = src.convert(bits=bits, top_down=top_down, header=header)
    assert out.bits_per_pixel == (bits or 24)
    if top_down is not None:
        assert out.top_down is top_down
    expected = _quantise555(rgb) if bits == 16 else rgb
    assert out.to_rgb() == expected


def test_convert_indexed_and_alpha() -> None:
    pal = [(0, 0, 0), (255, 255, 255)]
    src = BMP.from_pixels(3, 1, b"\x00\x01\x00", mode="P", bits=8, palette=pal)
    assert src.convert().bits_per_pixel == 8
    one = src.convert(bits=1)
    assert one.bits_per_pixel == 1
    assert one.to_indices() == b"\x00\x01\x00"
    assert src.convert(bits=24).to_rgb() == src.to_rgb()
    rgba = BMP.from_pixels(1, 1, b"\x01\x02\x03\x04", mode="RGBA")
    assert rgba.convert(top_down=True).to_rgba() == b"\x01\x02\x03\x04"
    assert rgba.convert(bits=24).to_rgb() == b"\x01\x02\x03"
