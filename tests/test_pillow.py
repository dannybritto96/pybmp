"""Cross-check decoded pixels against Pillow (test-only dependency)."""

from __future__ import annotations

import io

import pytest

from helpers import build_bmp, random_bytes
from pybmp import BMP, HeaderVersion, encode

Image = pytest.importorskip("PIL.Image")


def _pillow_bytes(img: object, mode: str) -> bytes:
    return bytes(img.convert(mode).tobytes())  # type: ignore[attr-defined]


def _pillow_open(data: bytes) -> object:
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


@pytest.mark.parametrize("width", [1, 3, 5, 8, 31])
@pytest.mark.parametrize("mode", ["1", "L", "P", "RGB"])
def test_pillow_written_files(mode: str, width: int) -> None:
    height = 4
    if mode == "RGB":
        im = Image.frombytes("RGB", (width, height), random_bytes(width * height * 3))
    else:
        im = Image.frombytes("L", (width, height), random_bytes(width * height, seed=1))
        if mode == "P":
            im = im.quantize(16)
        elif mode == "1":
            im = im.convert("1")
    buf = io.BytesIO()
    im.save(buf, "BMP")
    ours = BMP(data=buf.getvalue())
    assert ours.to_rgb() == _pillow_bytes(_pillow_open(buf.getvalue()), "RGB")


@pytest.mark.parametrize("header", ["info", "v4", "v5"])
@pytest.mark.parametrize("top_down", [False, True])
@pytest.mark.parametrize(
    ("mode", "bits"),
    [("RGB", 16), ("RGB", 24), ("RGB", 32), ("RGBA", 32), ("P", 1), ("P", 4), ("P", 8)],
)
def test_pillow_reads_our_files(
    mode: str, bits: int, top_down: bool, header: HeaderVersion
) -> None:
    if mode == "RGBA" and header == "info":
        pytest.skip("RGBA needs a V4/V5 header")
    width, height = 7, 5
    pal = None
    if mode == "P":
        pal = [(i * 13 % 256, i * 29 % 256, i * 53 % 256) for i in range(1 << bits)]
        px = random_bytes(width * height, limit=1 << bits)
    else:
        px = random_bytes(width * height * len(mode), seed=bits)
    data = encode(
        width,
        height,
        px,
        mode=mode,  # type: ignore[arg-type]
        bits=bits,
        palette=pal,
        top_down=top_down,
        header=header,
    )
    ours = BMP(data=data)
    theirs = _pillow_open(data)
    assert theirs.size == (width, height)  # type: ignore[attr-defined]
    out_mode = "RGBA" if mode == "RGBA" else "RGB"
    ours_px = ours.to_rgba() if out_mode == "RGBA" else ours.to_rgb()
    assert ours_px == _pillow_bytes(theirs, out_mode)


RLE8_STREAM = bytes([3, 7, 0, 3, 1, 2, 3, 0, 0, 0, 0, 2, 2, 0, 2, 9, 0, 0, 8, 4, 0, 1])
RLE4_STREAM = bytes([4, 0x12, 0, 4, 0x34, 0x56, 0, 0, 4, 0xAB, 0, 0, 8, 0x5A, 0, 1])


@pytest.mark.parametrize(
    ("bpp", "compression", "stream"), [(8, 1, RLE8_STREAM), (4, 2, RLE4_STREAM)]
)
def test_pillow_rle(bpp: int, compression: int, stream: bytes) -> None:
    pal = [(i * 16 % 256, 255 - i, i) for i in range(1 << bpp)]
    data = build_bmp(
        width=8,
        height=3,
        bpp=bpp,
        compression=compression,
        palette=pal,
        pixel_data=stream,
    )
    assert BMP(data=data).to_rgb() == _pillow_bytes(_pillow_open(data), "RGB")


@pytest.mark.parametrize("masks", [(0xF800, 0x07E0, 0x001F), (0x7C00, 0x03E0, 0x001F)])
def test_pillow_16bit_bitfields(masks: tuple[int, int, int]) -> None:
    raw = random_bytes(4 * 2 * 2, seed=3)
    data = build_bmp(
        width=4, height=2, bpp=16, compression=3, masks=masks, pixel_data=raw
    )
    assert BMP(data=data).to_rgb() == _pillow_bytes(_pillow_open(data), "RGB")
