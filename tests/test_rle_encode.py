"""BI_RLE8 / BI_RLE4 encoding."""

from __future__ import annotations

import io
import random
from pathlib import Path

import pytest

from helpers import random_bytes
from pybmp import (
    BMP,
    Compression,
    HeaderVersion,
    UnsupportedFormatError,
    encode,
    write,
)
from pybmp._encode import rle_encode
from pybmp.cli import main

WIDTHS = [1, 2, 3, 4, 5, 7, 254, 255, 256, 257, 600]


def _pattern(kind: str, width: int, height: int, levels: int) -> bytes:
    n = width * height
    rng = random.Random(f"{kind}{width}{levels}")
    if kind == "constant":
        return bytes([levels - 1]) * n
    if kind == "random":
        return bytes(rng.randrange(levels) for _ in range(n))
    if kind == "alternating":
        return bytes(i % 2 for i in range(n))
    # "mixed": runs of random lengths interleaved with noise
    out = bytearray()
    while len(out) < n:
        if rng.random() < 0.5:
            out += bytes([rng.randrange(levels)]) * rng.randrange(1, 300)
        else:
            out += bytes(rng.randrange(levels) for _ in range(rng.randrange(1, 9)))
    return bytes(out[:n])


def _strict_decode(stream: bytes, width: int, height: int, four: bool) -> bytes:
    """Spec-checking RLE decoder: validates structure while decoding."""
    rows: list[bytes] = []
    row = bytearray()
    i = 0
    ended = False
    while i < len(stream):
        count, value = stream[i], stream[i + 1]
        i += 2
        if count:
            if four:
                hi, lo = value >> 4, value & 15
                row += bytes((hi, lo) * (count // 2) + ((hi,) if count & 1 else ()))
            else:
                row += bytes([value]) * count
        elif value == 0:
            assert len(row) == width, "EOL before row is complete"
            rows.append(bytes(row))
            row.clear()
        elif value == 1:
            assert len(row) == width, "EOB before last row is complete"
            rows.append(bytes(row))
            ended = True
            assert i == len(stream), "data after end-of-bitmap"
            break
        else:
            assert value != 2, "delta escapes are never emitted"
            nbytes = (value + 1) // 2 if four else value
            chunk = stream[i : i + nbytes]
            assert len(chunk) == nbytes
            if four:
                pix = bytearray()
                for b in chunk:
                    pix += bytes((b >> 4, b & 15))
                row += pix[:value]
            else:
                row += chunk
            i += nbytes + (nbytes & 1)
            assert i % 2 == 0, "absolute runs must end on a word boundary"
        assert len(row) <= width, "run crosses the end of a row"
    assert ended, "missing end-of-bitmap"
    assert len(rows) == height
    return b"".join(reversed(rows))  # stored bottom-up


@pytest.mark.parametrize("bits", [4, 8])
@pytest.mark.parametrize("kind", ["constant", "random", "alternating", "mixed"])
@pytest.mark.parametrize("width", WIDTHS)
def test_round_trip_and_structure(bits: int, kind: str, width: int) -> None:
    height = 3
    px = _pattern(kind, width, height, 1 << bits)
    stream = rle_encode(px, width, height, bits)
    assert _strict_decode(stream, width, height, bits == 4) == px
    pal = [(i, (i * 3) % 256, 255 - i) for i in range(1 << bits)]
    data = encode(width, height, px, mode="P", bits=bits, palette=pal, rle=True)
    img = BMP(data=data)
    expected = Compression.BI_RLE8 if bits == 8 else Compression.BI_RLE4
    assert img.header.compression == expected
    assert img.header.image_size == len(stream)
    assert img.pixel_array == stream
    assert img.to_indices() == px
    assert (
        img.to_rgb()
        == BMP(
            data=encode(width, height, px, mode="P", bits=bits, palette=pal)
        ).to_rgb()
    )


@pytest.mark.parametrize("header", ["info", "v4", "v5"])
@pytest.mark.parametrize("bits", [4, 8])
@pytest.mark.parametrize("width", [1, 3, 17, 300])
def test_pillow_decodes_our_rle(header: HeaderVersion, bits: int, width: int) -> None:
    Image = pytest.importorskip("PIL.Image")
    height = 5
    px = _pattern("mixed", width, height, 1 << bits)
    pal = [(i * 13 % 256, i * 29 % 256, i * 53 % 256) for i in range(1 << bits)]
    data = encode(
        width, height, px, mode="P", bits=bits, palette=pal, header=header, rle=True
    )
    im = Image.open(io.BytesIO(data))
    im.load()
    assert im.size == (width, height)
    assert im.convert("RGB").tobytes() == BMP(data=data).to_rgb()


def test_compresses_flat_images() -> None:
    width, height = 640, 480
    px = bytes([3]) * (width * height)
    pal = [(0, 0, 0)] * 16
    raw = encode(width, height, px, mode="P", palette=pal)
    rle8 = encode(width, height, px, mode="P", palette=pal, rle=True)
    rle4 = encode(width, height, px, mode="P", bits=4, palette=pal, rle=True)
    assert len(rle8) < len(raw) // 50
    assert len(rle4) < len(raw) // 50


def test_literal_boundaries() -> None:
    # Literal of exactly 1, 2 and 3 pixels between long runs.
    px = bytes([1, 1, 1, 2, 3, 3, 3, 4, 5, 6, 6, 6, 7, 8, 9])
    stream = rle_encode(px, len(px), 1, 8)
    assert stream == bytes([3, 1, 1, 2, 3, 3, 1, 4, 1, 5, 3, 6, 0, 3, 7, 8, 9, 0, 0, 1])
    stream4 = rle_encode(px, len(px), 1, 4)
    assert stream4 == bytes(
        [3, 0x11, 1, 0x20, 3, 0x33, 2, 0x45, 3, 0x66, 2, 0x78, 1, 0x90, 0, 1]
    )
    # 4- and 5-pixel literals: an even absolute run, then a 1-pixel run.
    px = bytes([1, 2, 3, 4, 5, 5, 5, 1, 2, 3, 4, 5])
    assert rle_encode(px, len(px), 1, 4) == bytes(
        [0, 4, 0x12, 0x34, 3, 0x55, 0, 4, 0x12, 0x34, 1, 0x50, 0, 1]
    )


def _absolute_counts(stream: bytes, four: bool) -> list[int]:
    counts, i = [], 0
    while i < len(stream):
        count, value = stream[i], stream[i + 1]
        i += 2
        if count == 0 and value >= 3:
            counts.append(value)
            nbytes = (value + 1) // 2 if four else value
            i += nbytes + (nbytes & 1)
    return counts


def test_rle4_absolute_runs_are_even() -> None:
    px = _pattern("random", 999, 2, 16)
    counts = _absolute_counts(rle_encode(px, 999, 2, 4), four=True)
    assert counts
    assert all(c % 2 == 0 and c <= 254 for c in counts)
    counts8 = _absolute_counts(rle_encode(px, 999, 2, 8), four=False)
    assert 255 in counts8
    assert any(c % 2 for c in counts8)


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"mode": "RGB"}, "mode 'P'"),
        ({"mode": "P", "bits": 1}, "4 or 8 bits"),
        ({"mode": "P", "bits": 8, "header": "core"}, "CORE"),
        ({"mode": "P", "bits": 8, "top_down": True}, "bottom-up"),
    ],
)
def test_rle_rejected(kw: dict[str, object], match: str) -> None:
    pal = [(0, 0, 0), (1, 1, 1)]
    px = bytes(4) if kw["mode"] == "P" else bytes(12)
    with pytest.raises(UnsupportedFormatError, match=match):
        encode(2, 2, px, palette=pal, rle=True, **kw)  # type: ignore[arg-type]


def test_rle_encode_rejects_bits() -> None:
    with pytest.raises(UnsupportedFormatError):
        rle_encode(bytes(4), 2, 2, 2)


def test_convert_and_write(tmp_path: Path) -> None:
    pal = [(i, i, i) for i in range(16)]
    px = random_bytes(40 * 10, limit=4)
    img = BMP.from_pixels(40, 10, px, mode="P", palette=pal, top_down=True)
    rle = img.convert(rle=True)
    assert rle.header.compression == Compression.BI_RLE8
    assert not rle.top_down
    assert rle.to_indices() == px
    rle4 = img.convert(bits=4, rle=True)
    assert rle4.header.compression == Compression.BI_RLE4
    assert rle4.to_indices() == px
    assert rle.convert().header.compression == Compression.BI_RGB
    with pytest.raises(UnsupportedFormatError, match="bottom-up"):
        img.convert(rle=True, top_down=True)
    with pytest.raises(UnsupportedFormatError, match="indexed"):
        BMP.from_pixels(2, 1, bytes(6)).convert(rle=True)
    with pytest.raises(UnsupportedFormatError, match="indexed"):
        img.convert(bits=24, rle=True)
    path = tmp_path / "w.bmp"
    write(path, 40, 10, px, mode="P", palette=pal, rle=True)
    assert BMP(path).header.compression == Compression.BI_RLE8
    built = BMP.from_pixels(40, 10, px, mode="P", palette=pal, rle=True)
    assert built == BMP(path)


def test_cli_convert_rle(tmp_path: Path) -> None:
    pal = [(i, i, i) for i in range(16)]
    src = tmp_path / "src.bmp"
    dst = tmp_path / "dst.bmp"
    write(src, 8, 8, bytes(64), mode="P", bits=4, palette=pal)
    assert main(["convert", str(src), str(dst), "--rle"]) == 0
    assert BMP(dst).header.compression == Compression.BI_RLE4
    assert main(["convert", str(src), str(dst), "--rle", "--bits", "24"]) == 1
