"""Lazy / memory-mapped reading with LazyBMP and open_lazy."""

from __future__ import annotations

import array
import gc
import io
from pathlib import Path
from typing import Any

import pytest

from helpers import build_bmp, pad_rows, random_bytes
from pybmp import (
    BMP,
    BMPError,
    HeaderNotSupported,
    LazyBMP,
    TruncatedFileError,
    UnsupportedFormatError,
    encode,
    open_lazy,
)

FORMATS: list[dict[str, Any]] = [
    {"mode": "P", "bits": 1},
    {"mode": "P", "bits": 2},
    {"mode": "P", "bits": 4},
    {"mode": "P", "bits": 8},
    {"mode": "RGB", "bits": 16},
    {"mode": "RGB", "bits": 24},
    {"mode": "RGB", "bits": 32},
    {"mode": "RGBA", "bits": 32},
    {"mode": "P", "bits": 4, "rle": True},
    {"mode": "P", "bits": 8, "rle": True},
]


def _make(fmt: dict[str, Any], width: int, height: int, top_down: bool) -> bytes:
    kw = dict(fmt)
    mode = kw["mode"]
    if mode == "P":
        bits = kw["bits"]
        kw["palette"] = [(i, 255 - i, (i * 7) % 256) for i in range(1 << bits)]
        px = random_bytes(width * height, seed=bits, limit=1 << bits)
        if kw.get("rle"):
            px = bytes(v if i % 5 else 0 for i, v in enumerate(px))
            top_down = False
    else:
        px = random_bytes(width * height * len(mode), seed=width)
    return encode(width, height, px, top_down=top_down, **kw)


def _sources(data: bytes, tmp_path: Path) -> list[tuple[str, Any]]:
    path = tmp_path / "img.bmp"
    path.write_bytes(data)
    prefixed = io.BytesIO(b"junk" + data)
    prefixed.seek(4)
    return [
        ("bytes", data),
        ("bytearray", bytearray(data)),
        ("memoryview", memoryview(data)),
        ("path-mmap", path),
        ("str-path-nommap", str(path)),
        ("fileobj", io.BytesIO(data)),
        ("fileobj-offset", prefixed),
    ]


@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: "-".join(map(str, f.values())))
@pytest.mark.parametrize("top_down", [False, True])
@pytest.mark.parametrize("width", [1, 5, 33])
def test_rows_match_eager(
    fmt: dict[str, Any], top_down: bool, width: int, tmp_path: Path
) -> None:
    height = 7
    data = _make(fmt, width, height, top_down)
    eager = BMP(data=data)
    rgb, rgba = eager.to_rgb(), eager.to_rgba()
    indices = eager.to_indices() if eager.bits_per_pixel <= 8 else None
    for name, src in _sources(data, tmp_path):
        with open_lazy(src, use_mmap=name != "str-path-nommap") as img:
            assert img.header == eager.header, name
            assert img.size == eager.size
            assert img.mode == eager.mode
            assert img.random_access is not fmt.get("rle", False)
            assert img.read_rows(mode="RGB") == rgb
            assert img.read_rows(mode="RGBA") == rgba
            assert img.read_rows() == (rgba if img.mode == "RGBA" else rgb)
            for lo, hi in [(0, 1), (2, 5), (6, 7), (-3, None), (3, 100)]:
                n = slice(lo, hi).indices(height)
                assert (
                    img.read_rows(lo, hi, mode="RGB")
                    == rgb[n[0] * width * 3 : n[1] * width * 3]
                )
            assert b"".join(img.iter_rows(mode="RGB", chunk_rows=3)) == rgb
            assert list(img.iter_rows(2, 4, mode="RGB")) == [
                rgb[y * width * 3 : (y + 1) * width * 3] for y in (2, 3)
            ]
            if indices is not None:
                assert img.read_rows(mode="P") == indices
                assert img.row(-1, mode="P") == indices[-width:]
            assert img.get_pixel(width - 1, 3) == eager.get_pixel(width - 1, 3)
            assert img.load() == eager


def test_properties_and_repr(tmp_path: Path) -> None:
    pal = [(1, 2, 3), (4, 5, 6)]
    data = encode(3, 2, bytes([0, 1, 1, 1, 0, 0]), mode="P", bits=1, palette=pal)
    img = LazyBMP(data)
    assert img.width == 3
    assert img.height == 2
    assert img.bits_per_pixel == 1
    assert not img.top_down
    assert img.palette == tuple(pal)
    assert img.file_size == len(data)
    assert img.embedded_format is None
    assert img.embedded_image is None
    assert repr(img) == "<LazyBMP 3x2 1-bit BI_RGB BITMAPINFOHEADER>"
    assert not img.closed
    img.close()
    assert img.closed
    assert repr(img).endswith("closed>")
    img.close()  # idempotent


def test_closed_image_raises(tmp_path: Path) -> None:
    path = tmp_path / "a.bmp"
    path.write_bytes(encode(2, 2, bytes(12)))
    with open_lazy(path) as img:
        assert img.row(0) == bytes(6)
    assert img.closed
    with pytest.raises(ValueError, match="closed"):
        img.read_rows()
    with pytest.raises(ValueError, match="closed"):
        img.read_rows(1, 1)
    with pytest.raises(ValueError, match="closed"):
        img.load()


def test_file_object_left_open() -> None:
    f = io.BytesIO(encode(2, 2, bytes(12)))
    with open_lazy(f) as img:
        img.read_rows()
    assert not f.closed


def test_path_file_closed(tmp_path: Path) -> None:
    path = tmp_path / "a.bmp"
    path.write_bytes(encode(2, 2, bytes(12)))
    img = LazyBMP(path, use_mmap=False)
    f = img._file
    assert f is not None
    img.close()
    assert f.closed


def test_finaliser_closes_file(tmp_path: Path) -> None:
    path = tmp_path / "a.bmp"
    path.write_bytes(encode(2, 2, bytes(12)))
    img = LazyBMP(path, use_mmap=False)
    f = img._file
    assert f is not None
    del img
    gc.collect()
    assert f.closed


def test_header_only_is_read(tmp_path: Path) -> None:
    """Opening must not read the pixel array."""
    data = encode(64, 64, bytes(64 * 64 * 3))

    class Counting(io.BytesIO):
        read_bytes = 0

        def read(self, n: int | None = -1) -> bytes:
            out = super().read(n)
            Counting.read_bytes += len(out)
            return out

    f = Counting(data)
    img = LazyBMP(f)
    assert Counting.read_bytes < 100
    img.row(10)
    assert Counting.read_bytes < 100 + img.header.stride
    img.close()


def test_errors_close_the_file(tmp_path: Path) -> None:
    path = tmp_path / "bad.bmp"
    path.write_bytes(b"XX" + bytes(60))
    with pytest.raises(BMPError):
        LazyBMP(path)
    path.write_bytes(b"")
    with pytest.raises(TruncatedFileError):
        LazyBMP(path)
    with pytest.raises(TruncatedFileError):
        LazyBMP(b"BM")


def test_unknown_header_size() -> None:
    data = bytearray(encode(2, 2, bytes(12)))
    data[14:18] = (999).to_bytes(4, "little")
    with pytest.raises(HeaderNotSupported):
        LazyBMP(bytes(data))


def test_bad_arguments() -> None:
    img = LazyBMP(encode(2, 2, bytes(12)))
    with pytest.raises(BMPError, match="unknown mode"):
        img.read_rows(mode="L")  # type: ignore[arg-type]
    with pytest.raises(BMPError, match="unknown mode"):
        list(img.iter_rows(mode="L"))  # type: ignore[arg-type]
    with pytest.raises(UnsupportedFormatError, match="no palette indices"):
        img.read_rows(mode="P")
    with pytest.raises(ValueError, match="chunk_rows"):
        list(img.iter_rows(chunk_rows=0))
    with pytest.raises(IndexError):
        img.row(2)
    with pytest.raises(IndexError):
        img.row(-3)
    with pytest.raises(IndexError):
        img.get_pixel(2, 0)
    with pytest.raises(IndexError):
        img.get_pixel(0, -1)
    assert img.read_rows(1, 1) == b""
    assert img.read_rows(2, 0) == b""
    assert list(img.iter_rows(1, 1)) == []


def test_truncated_pixel_array_reads_available_rows() -> None:
    width, height = 4, 6
    data = encode(width, height, random_bytes(width * height * 3), top_down=True)
    stride = 12
    cut = data[: len(data) - 2 * stride]
    img = LazyBMP(cut)
    full = BMP(data=data).to_rgb()
    assert img.read_rows(0, 4, mode="RGB") == full[: 4 * width * 3]
    with pytest.raises(TruncatedFileError, match=r"rows 3\.\.4"):
        img.read_rows(3, 5)
    with pytest.raises(TruncatedFileError):
        BMP(data=cut).to_rgb()


def test_rle_stream_truncated() -> None:
    pal = [(0, 0, 0)] * 256
    data = encode(4, 4, bytes(range(16)), mode="P", palette=pal, rle=True)
    with pytest.raises(TruncatedFileError, match="truncated"):
        LazyBMP(data[:-4]).read_rows()
    hdr = BMP(data=data).header
    with pytest.raises(TruncatedFileError, match="past end"):
        LazyBMP(data[: hdr.pixel_offset - 1]).read_rows()


def test_rle_decodes_once() -> None:
    pal = [(i, i, i) for i in range(256)]
    px = bytes(range(64))
    data = encode(8, 8, px, mode="P", palette=pal, rle=True)
    img = LazyBMP(data)
    assert img.row(0, mode="P") == px[:8]
    cached = img._indices
    assert cached == px
    assert img.row(7, mode="P") == px[56:]
    assert img._indices is cached


def test_bitfield_rows() -> None:
    width, height = 3, 4
    rows = [random_bytes(width * 2, seed=y) for y in range(height)]
    data = build_bmp(
        width=width,
        height=height,
        bpp=16,
        compression=3,
        masks=(0xF800, 0x07E0, 0x001F),
        pixel_data=pad_rows(rows),
    )
    eager = BMP(data=data)
    with open_lazy(data) as img:
        assert img.read_rows() == eager.to_rgb()
        assert img.read_rows(1, 3) == eager.to_rgb()[width * 3 : 3 * width * 3]


def test_unsupported_compression_rows() -> None:
    data = build_bmp(width=1, height=1, bpp=24, compression=11, pixel_data=bytes(4))
    img = LazyBMP(data)
    with pytest.raises(UnsupportedFormatError, match="BI_CMYK"):
        img.read_rows()


def test_non_byte_memoryview() -> None:
    data = encode(2, 2, bytes(range(12)))
    data += bytes(-len(data) % 2)
    words = memoryview(array.array("H", data))
    with open_lazy(words) as img:
        assert img.read_rows() == bytes(range(12))


def test_bytearray_released_on_close() -> None:
    buf = bytearray(encode(2, 2, bytes(12)))
    img = open_lazy(buf)
    with pytest.raises(BufferError):
        buf.extend(b"x")
    img.close()
    buf.extend(b"x")


def test_to_numpy() -> None:
    np = pytest.importorskip("numpy")
    width, height = 5, 4
    rgba = random_bytes(width * height * 4)
    data = encode(width, height, rgba, mode="RGBA")
    with open_lazy(data) as img:
        arr = img.to_numpy(1, 3)
        assert arr.shape == (2, width, 4)
        assert arr.tobytes() == rgba[width * 4 : 3 * width * 4]
        assert img.to_numpy(mode="RGB").shape == (height, width, 3)
    pal = [(i, i, i) for i in range(16)]
    idx = random_bytes(width * height, limit=16)
    with open_lazy(encode(width, height, idx, mode="P", bits=4, palette=pal)) as img:
        arr = img.to_numpy(mode="P")
        assert arr.shape == (height, width)
        assert arr.dtype == np.uint8
        assert arr.tobytes() == idx


def test_large_image_single_row(tmp_path: Path) -> None:
    width, height = 3000, 2000
    row = bytes(range(256)) * (width * 3 // 256 + 1)
    data = encode(width, height, row[: width * 3] * height)
    path = tmp_path / "big.bmp"
    path.write_bytes(data)
    with open_lazy(path) as img:
        assert img.row(1234) == row[: width * 3]
        assert img.get_pixel(2999, 1999) == tuple(row[2999 * 3 : 3000 * 3])
        assert sum(1 for _ in img.iter_rows()) == height
