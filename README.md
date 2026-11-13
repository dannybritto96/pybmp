# pybmp

[![CI](https://github.com/dannybritto96/pybmp/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/dannybritto96/pybmp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pybmp2.svg)](https://pypi.org/project/pybmp2/)
[![Python](https://img.shields.io/pypi/pyversions/pybmp2.svg)](https://pypi.org/project/pybmp2/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A fast, dependency-free Python library and command-line tool for reading and
writing Windows BMP (DIB) images.

pybmp parses every BMP header version, decodes pixels to plain RGB/RGBA
bytes (or palette indices), and encodes images back to BMP. The hot paths use
C-level bulk operations (`bytes.translate`, extended slice assignment,
`memoryview`, big-integer bit operations) instead of per-pixel Python loops,
so it is fast without any dependencies. numpy is optional: if it is installed,
`to_numpy()` is available and unusual bit-field layouts decode faster.

The distribution is called **`pybmp2`** on PyPI. The import name is `pybmp`.

## Features

- Reads every DIB header version: `BITMAPCOREHEADER` (12 bytes), OS/2
  `OS22XBITMAPHEADER` (16 and 64 bytes), `BITMAPINFOHEADER` (40),
  `BITMAPV2INFOHEADER` (52), `BITMAPV3INFOHEADER` (56), `BITMAPV4HEADER` (108)
  and `BITMAPV5HEADER` (124).
- Decodes 1, 2, 4, 8, 16, 24 and 32 bits per pixel.
- Decodes `BI_RGB`, `BI_RLE8`, `BI_RLE4`, `BI_BITFIELDS` and `BI_ALPHABITFIELDS`,
  including arbitrary channel masks such as RGB565, ARGB4444 and A2R10G10B10.
- Handles bottom-up and top-down (negative height) images, row padding for any
  width, palettes of any size, and the pixel-data offset from the file header.
- Encodes 1/2/4/8-bit indexed, 16-bit (X1R5G5B5), 24-bit and 32-bit RGB, and
  32-bit RGBA, with a core, info, V4 or V5 header, top-down or bottom-up.
- Gives typed header access (`BMPHeader` dataclass), specific exceptions, a
  `pybmp` command-line tool, and full type hints (`py.typed`).
- Stays backwards compatible with the pybmp 1.x attributes (`SHAPE`,
  `PIXELARRAY`, `RAWIMGSIZE` and the rest).

### Unsupported

These raise `UnsupportedFormatError` when you decode pixels. Headers still parse.

- `BI_JPEG` and `BI_PNG` embedded images. `pixel_array` returns the embedded
  stream, so you can hand it to a JPEG or PNG decoder.
- `BI_CMYK`, `BI_CMYKRLE8` and `BI_CMYKRLE4` (Windows Metafile only).
- OS/2 Huffman 1D and RLE24 compression.
- ICC colour profiles and gamma in V4/V5 headers are parsed but not applied.
- Multi-image OS/2 bitmap arrays (`BA`) are read as a single image.
- Writing RLE-compressed files, and converting true-colour images to an
  indexed palette (quantisation).

## Install

```shell
pip install pybmp2            # pure Python, no dependencies
pip install "pybmp2[numpy]"   # adds the optional numpy fast path and to_numpy()
```

From source:

```shell
git clone https://github.com/dannybritto96/pybmp.git
cd pybmp
pip install .                 # or: pip install -e ".[dev]" for development
```

pybmp needs Python 3.10 or newer.

## Quick start

```python
import pybmp

# Write a 3x2 RGB image (rows top-down, 3 bytes per pixel)...
pixels = bytes([
    255, 0, 0,   0, 255, 0,   0, 0, 255,
    255, 255, 0, 0, 255, 255, 255, 255, 255,
])
pybmp.write("example.bmp", 3, 2, pixels)

# ...and read it back.
img = pybmp.open("example.bmp")
print(img)                    # <BMP 3x2 24-bit BI_RGB BITMAPINFOHEADER>
print(img.size, img.mode)     # (3, 2) RGB
assert img.to_rgb() == pixels
print(img.get_pixel(2, 0))    # (0, 0, 255)
```

## Usage

### Reading

```python
import io
from pathlib import Path

from pybmp import BMP

data = Path("example.bmp").read_bytes()

img = BMP("example.bmp")                  # path (str or Path)
img = BMP.open(io.BytesIO(data))          # binary file object
img = BMP.from_bytes(data)                # bytes already in memory

h = img.header                            # frozen BMPHeader dataclass
print(h.header_name, h.bits_per_pixel, h.compression_name, h.pixel_offset)
print(img.width, img.height, img.top_down, img.palette)

rgb = img.to_rgb()        # bytes, 3 per pixel, rows top-down
rgba = img.to_rgba()      # bytes, 4 per pixel (alpha = 255 if none stored)
raw = img.pixel_array     # stored bytes exactly as on disk, from the pixel offset
print(img.info())         # JSON-serialisable summary of every header field
```

With numpy installed:

```python
from pybmp import BMP

arr = BMP("example.bmp").to_numpy()       # shape (height, width, 3), dtype uint8
print(arr.shape)                          # (2, 3, 3)
```

### Indexed (palette) images

```python
import pybmp

palette = [(0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 0, 255)]
indices = bytes([0, 1, 2, 3, 3, 2, 1, 0])  # one palette index per pixel
data = pybmp.encode(4, 2, indices, mode="P", bits=2, palette=palette)

img = pybmp.BMP(data=data)
assert img.to_indices() == indices
print(img.bits_per_pixel, len(img.palette))   # 2 4
```

### Writing

```python
import pybmp

rgba = bytes([255, 0, 0, 128] * 4)                     # 2x2, half-transparent red
pybmp.write("alpha.bmp", 2, 2, rgba, mode="RGBA")      # 32-bit BITMAPV4HEADER

rgb = bytes(range(18))
small = pybmp.encode(3, 2, rgb, bits=16)               # 16-bit X1R5G5B5
top = pybmp.encode(3, 2, rgb, top_down=True, header="v5")

img = pybmp.BMP.from_pixels(3, 2, rgb)                 # build a BMP object directly
img.convert(bits=32, top_down=True).save("converted.bmp")
```

### Errors

All errors derive from `pybmp.BMPError`, which subclasses `ValueError`:

| Exception | Raised when |
|---|---|
| `InvalidBMPError` | the data is not a well-formed BMP (bad signature, width, offset, hex) |
| `TruncatedFileError` | the file ends inside a header, palette or the pixel array |
| `HeaderNotSupported` | the DIB header size is unknown |
| `UnsupportedFormatError` | the file is valid but uses an unsupported feature |

```python
import pybmp

try:
    pybmp.BMP(data=b"definitely not a bitmap")
except pybmp.InvalidBMPError as exc:
    print("not a BMP:", exc)
```

### pybmp 1.x compatibility

The 1.x constructor and upper-case attributes still work:

```python
import binascii
from pybmp import BMP

with open("example.bmp", "rb") as f:
    hexdata = binascii.hexlify(f.read())

img = BMP(hexdata=hexdata)          # or BMP(filename="example.bmp")
print(img.SHAPE, img.RAWIMGSIZE, len(img.PIXELARRAY))   # (3, 2) 24 24
```

## Command line

```shell
$ pybmp info example.bmp
example.bmp: 3x2 24-bit BI_RGB BITMAPINFOHEADER (bottom-up, RGB, palette=0, offset=54)

$ pybmp info --json example.bmp          # every header field as JSON
$ pybmp convert in.bmp out.bmp --bits 32 --top-down --header v5
$ python -m pybmp --version
```

`convert` accepts `--bits {1,2,4,8,16,24,32}`, `--top-down` or `--bottom-up`,
and `--header {core,info,v4,v5}`. Indexed targets need an indexed source.

## Benchmarks

Measured with `python benchmarks/bench.py` on Python 3.13.5, Linux x86_64
(best of 5 runs, milliseconds). "1.x parse" is the pybmp 1.x code on `master`
(after PR #1), which hexlifies the whole file. "2.x parse" builds a `BMP` and
reads `PIXELARRAY`. "naive loop" is a reference per-pixel Python decoder, not
part of either version. Your numbers will vary by machine.

| Image (24-bit) | File MB | 1.x parse | 2.x parse | Speed-up | 2.x `to_rgb` | Pillow `open+tobytes` | naive loop decode |
|---|---|---|---|---|---|---|---|
| 64x64 | 0.01 | 0.03 | 0.017 | 2x | 0.03 | 0.03 | 0.7 |
| 512x512 | 0.79 | 2.21 | 0.103 | 21x | 0.55 | 0.43 | 43.1 |
| 1024x1024 | 3.15 | 7.33 | 0.500 | 15x | 2.38 | 1.64 | 179.5 |
| 2048x2048 | 12.58 | 32.83 | 1.626 | 20x | 9.16 | 6.35 | - |
| 4096x4096 | 50.33 | 87.87 | 42.668 | 2x | 144.09 | 91.92 | - |

Decode and encode at 2048x2048 (4.2 megapixels), milliseconds:

| Format | 2.x decode to RGB(A) | Pillow decode | 2.x encode |
|---|---|---|---|
| 1-bit indexed | 15.9 | 4.9 | 36.6 |
| 4-bit indexed | 15.9 | 5.0 | 34.1 |
| 8-bit indexed | 12.4 | 4.3 | 24.4 |
| 16-bit RGB555 | 21.5 | 12.3 | 30.0 |
| 24-bit RGB | 8.1 | 6.7 | 10.2 |
| 32-bit RGBA (V4) | 13.7 | 5.4 | 13.7 |

pybmp 1.x could not decode pixels at all, so there is no 1.x column for
decoding. Pure-Python 2.x decoding is 20-80x faster than a per-pixel loop and
within 1.2-3.5x of Pillow's C decoder.

## Development

```shell
pip install -e ".[dev]"
pytest --cov                 # tests, with coverage (CI requires >= 90%)
ruff check . && ruff format --check .
mypy                         # strict type checking of src/ and tests/
python benchmarks/bench.py   # benchmarks against the 1.x code on master
python -m build && twine check dist/*
```

The test suite covers every module: header parsing, decoding of every bit
depth and compression, round trips across depths, header versions,
orientations and padded widths, malformed and truncated files, the CLI, the
1.x compatibility layer, cross-checks against Pillow, and the code examples
in this README.

## Contributing

Bug reports and pull requests are welcome.

1. Fork the repository and create a branch from `master`.
2. Install the dev extras: `pip install -e ".[dev]"`.
3. Add tests for your change. For decoder fixes, a small hand-built file in
   `tests/helpers.py` style is ideal.
4. Make sure `pytest --cov`, `ruff check .`, `ruff format --check .` and `mypy`
   all pass. CI runs them on Python 3.10 to 3.13.
5. Open a pull request describing the change.

## What changed in 2.0

2.0 is a full rewrite. The [CHANGELOG](CHANGELOG.md) has the details.

- **Correct pixel data.** 1.x sliced the hexlified file with byte counts, so
  `PIXELARRAY` held only half the image. This was reported and first fixed by
  [@buthanoid](https://github.com/buthanoid) in
  [PR #1](https://github.com/dannybritto96/pybmp/pull/1). Thank you! 2.0
  completes that fix. Pixels are read from the header's pixel-data offset with
  real byte lengths for every header version, and the misaligned header fields
  (`RAWIMGSIZE`, resolution, colour counts, V4 colour space and gamma) are read
  from the right positions.
- Pixel decoding (`to_rgb`, `to_rgba`, `to_indices`, `to_numpy`), encoding
  (`encode`, `write`, `save`, `convert`) and a CLI are new.
- More header versions, RLE, bit fields, palettes and top-down images are supported.
- `src/` layout, `pyproject.toml` packaging, type hints, a pytest suite, and
  CI with ruff, mypy and coverage.

Reference: <https://en.wikipedia.org/wiki/BMP_file_format>

## License

MIT. See [LICENSE](LICENSE).
