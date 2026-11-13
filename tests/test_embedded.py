"""BI_JPEG / BI_PNG embedded images."""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import pytest

from helpers import build_bmp, random_bytes
from pybmp import (
    BMP,
    BMPError,
    InvalidBMPError,
    UnsupportedFormatError,
    encode,
    encode_embedded,
    open_lazy,
)
from pybmp._encode import embedded_kind
from pybmp.cli import main

Image = pytest.importorskip("PIL.Image")


def _png(width: int = 9, height: int = 7) -> bytes:
    im = Image.frombytes("RGB", (width, height), random_bytes(width * height * 3))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _jpeg(width: int = 16, height: int = 8, **kw: object) -> bytes:
    im = Image.new("RGB", (width, height), (200, 30, 90))
    buf = io.BytesIO()
    im.save(buf, "JPEG", **kw)
    return buf.getvalue()


@pytest.mark.parametrize("header", ["info", "v4", "v5"])
@pytest.mark.parametrize("kind", ["png", "jpeg"])
def test_round_trip(header: str, kind: str, tmp_path: Path) -> None:
    stream = _png() if kind == "png" else _jpeg()
    data = encode_embedded(stream, header=header)  # type: ignore[arg-type]
    img = BMP(data=data)
    assert img.embedded_format == kind
    assert img.embedded_image == stream
    assert img.header.bits_per_pixel == 0
    assert img.header.compression_name == ("BI_PNG" if kind == "png" else "BI_JPEG")
    assert img.header.image_size == len(stream)
    assert img.size == ((9, 7) if kind == "png" else (16, 8))
    assert img.palette == ()
    assert img.mode == "RGB"
    decoded = img.open_embedded()
    direct = Image.open(io.BytesIO(stream))
    assert decoded.size == img.size
    assert decoded.tobytes() == direct.convert(decoded.mode).tobytes()
    path = tmp_path / "e.bmp"
    path.write_bytes(data)
    with open_lazy(path) as lazy:
        assert lazy.embedded_format == kind
        assert lazy.embedded_image == stream
        assert lazy.open_embedded().size == img.size
        with pytest.raises(UnsupportedFormatError, match="embedded_image"):
            lazy.read_rows()


def test_pixels_raise_with_hint() -> None:
    img = BMP.from_embedded(_png())
    with pytest.raises(UnsupportedFormatError, match="embedded PNG"):
        img.to_rgb()
    with pytest.raises(UnsupportedFormatError, match="open_embedded"):
        img.to_indices()


def test_explicit_size_and_resolution() -> None:
    img = BMP.from_embedded(_png(), width=3, height=4, pixels_per_meter=100)
    assert img.size == (3, 4)
    assert img.header.x_pixels_per_meter == 100
    img = BMP.from_embedded(_png(), width=3)
    assert img.size == (3, 7)


def test_hand_built_files_with_nonzero_bpp() -> None:
    """Some writers store biBitCount 24 with BI_PNG; still exposed."""
    stream = _png()
    for bpp in (0, 24):
        data = build_bmp(
            header_size=40, width=9, height=7, bpp=bpp, compression=5, pixel_data=stream
        )
        img = BMP(data=data)
        assert img.embedded_image == stream
    # Stream without biSizeImage: read to end of file.
    data = build_bmp(
        header_size=124,
        width=9,
        height=7,
        bpp=0,
        compression=5,
        pixel_data=stream,
        image_size=0,
    )
    assert BMP(data=data).embedded_image == stream
    # A palette that is present is still parsed.
    data = build_bmp(
        width=9,
        height=7,
        bpp=0,
        compression=4,
        pixel_data=_jpeg(),
        palette=[(1, 2, 3)],
    )
    assert BMP(data=data).palette == ((1, 2, 3),)


def test_bpp_zero_rejected_elsewhere() -> None:
    with pytest.raises(InvalidBMPError, match="bits per pixel: 0"):
        BMP(data=build_bmp(width=1, height=1, bpp=0, pixel_data=bytes(4)))
    # OS/2 compression 4 means RLE24, not JPEG.
    with pytest.raises(InvalidBMPError, match="bits per pixel: 0"):
        BMP(
            data=build_bmp(
                header_size=64, width=1, height=1, bpp=0, compression=4, pixel_data=b""
            )
        )
    os2 = BMP(
        data=build_bmp(
            header_size=64, width=1, height=1, bpp=24, compression=4, pixel_data=b""
        )
    )
    assert os2.embedded_format is None


def test_ordinary_bitmap_has_no_embedded_image() -> None:
    img = BMP(data=encode(1, 1, bytes(3)))
    assert img.embedded_format is None
    assert img.embedded_image is None
    with pytest.raises(UnsupportedFormatError, match="no embedded"):
        img.open_embedded()


def test_encode_embedded_errors() -> None:
    with pytest.raises(BMPError, match="PNG or JPEG"):
        encode_embedded(b"GIF89a")
    with pytest.raises(UnsupportedFormatError, match="CORE"):
        encode_embedded(_png(), header="core")
    with pytest.raises(BMPError, match="unknown header"):
        encode_embedded(_png(), header="v9")  # type: ignore[arg-type]
    with pytest.raises(BMPError, match="positive"):
        encode_embedded(_png(), width=0, height=1)
    with pytest.raises(BMPError, match="IHDR"):
        encode_embedded(b"\x89PNG\r\n\x1a\n" + bytes(4))


def test_embedded_kind() -> None:
    assert embedded_kind(_png()) == "png"
    assert embedded_kind(_jpeg()) == "jpeg"
    assert embedded_kind(b"BM") is None


def _jpeg_with(*segments: bytes) -> bytes:
    return b"\xff\xd8" + b"".join(segments)


def _sof(width: int, height: int, marker: int = 0xC0) -> bytes:
    body = struct.pack(">BHHB", 8, height, width, 1) + b"\x01\x11\x00"
    return bytes((0xFF, marker)) + struct.pack(">H", len(body) + 2) + body


def test_jpeg_size_parser() -> None:
    app0 = b"\xff\xe0" + struct.pack(">H", 4) + b"ab"
    dht = b"\xff\xc4" + struct.pack(">H", 3) + b"x"
    progressive = _jpeg_with(b"\xff", app0, b"\xff\xd0", dht, _sof(33, 21, 0xC2))
    assert BMP.from_embedded(progressive).size == (33, 21)
    assert BMP.from_embedded(_jpeg(40, 24, progressive=True)).size == (40, 24)
    with pytest.raises(BMPError, match="no start-of-frame"):
        encode_embedded(_jpeg_with(app0, b"\xff\xd9"))
    with pytest.raises(BMPError, match="no start-of-frame"):
        encode_embedded(_jpeg_with(b"\xff\xc0\x00\x11\x08"))
    with pytest.raises(BMPError, match="expected a marker"):
        encode_embedded(_jpeg_with(b"\xffl" + bytes(3), b"\x00\x00\x00\x00"))


def test_cli_info(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "e.bmp"
    path.write_bytes(encode_embedded(_png()))
    assert main(["info", "--json", str(path)]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["compression"] == "BI_PNG"
    assert info["bits_per_pixel"] == 0
