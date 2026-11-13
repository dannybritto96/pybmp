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
- Writes `BI_RLE8` and `BI_RLE4` run-length compressed files (`rle=True`).
- Opens huge files lazily (`open_lazy`): only the headers are read up front,
  and rows are decoded on demand from a memory map, a file object or bytes.
- Exposes the PNG or JPEG stream embedded in `BI_PNG` / `BI_JPEG` files,
  decodes it with Pillow if installed, and can write such files.
- Gives typed header access (`BMPHeader` dataclass), specific exceptions, a
  `pybmp` command-line tool, and full type hints (`py.typed`).
- Stays backwards compatible with the pybmp 1.x attributes (`SHAPE`,
  `PIXELARRAY`, `RAWIMGSIZE` and the rest).

### Unsupported

These raise `UnsupportedFormatError` when you decode pixels. Headers still parse.

- Decoding `BI_JPEG` and `BI_PNG` pixels with `to_rgb()` and friends. Use
  `embedded_image` (the raw stream) or `open_embedded()` (needs Pillow) instead.
- `BI_CMYK`, `BI_CMYKRLE8` and `BI_CMYKRLE4` (Windows Metafile only).
- OS/2 Huffman 1D and RLE24 compression.
- ICC colour profiles and gamma in V4/V5 headers are parsed but not applied.
- Multi-image OS/2 bitmap arrays (`BA`) are read as a single image.
- Converting true-colour images to an indexed palette (quantisation), and
  writing RLE delta escapes (the encoder never needs them).

## Install

```shell
pip install pybmp2            # pure Python, no dependencies
pip install "pybmp2[numpy]"   # adds the optional numpy fast path and to_numpy()
pip install "pybmp2[pillow]"  # adds Pillow for open_embedded() (PNG/JPEG in BMP)
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

### Lazy and memory-mapped reading

`open_lazy()` (or `LazyBMP(...)`) reads only the headers and palette. Rows are
read and decoded when you ask for them, so a multi-gigabyte bitmap can be
inspected or streamed in constant memory. Paths are memory-mapped (pass
`use_mmap=False` to use plain reads); binary file objects and
`bytes`/`bytearray`/`memoryview` work too, without a copy.

```python
import pybmp

with pybmp.open_lazy("example.bmp") as img:   # headers only; file stays mapped
    print(img.size, img.mode, img.random_access)   # (3, 2) RGB True
    top = img.read_rows(0, 1)                 # rows 0..0, RGB bytes, top-down
    last = img.row(-1)                        # negative rows count from the bottom
    print(img.get_pixel(0, 1))                # (255, 255, 0), reads one row only
    for row in img.iter_rows(mode="RGBA"):    # one row at a time, ~1 MiB per read
        assert len(row) == img.width * 4
    eager = img.load()                        # the whole file as a normal BMP
```

`read_rows(start, stop)` takes slice-style bounds and `mode="RGB"`, `"RGBA"`
or `"P"` (palette indices). `to_numpy(start, stop)` returns just those rows.
Uncompressed and bit-field files are read row by row. RLE rows can't be found
without decoding everything before them, so for `BI_RLE8` / `BI_RLE4` files
(`random_access` is `False`) the first row access decodes the whole image once
and caches the indices. Closing the `LazyBMP` releases the map and closes a
file it opened; file objects you pass in stay open.

### RLE compression

`rle=True` on `encode()`, `write()`, `BMP.from_pixels()` and `BMP.convert()`
writes `BI_RLE8` (8-bit) or `BI_RLE4` (4-bit) data for indexed images. RLE
files are always bottom-up and need an info, V4 or V5 header.

```python
import pybmp

palette = [(0, 0, 0), (255, 255, 255)]
indices = bytes([1] * 100 + [0] * 100) * 50          # 200x50, two flat halves
rle = pybmp.encode(200, 50, indices, mode="P", palette=palette, rle=True)
raw = pybmp.encode(200, 50, indices, mode="P", palette=palette)
print(len(rle), len(raw))                            # 362 10062
assert pybmp.BMP(data=rle).to_indices() == indices

small = pybmp.BMP(data=raw).convert(bits=4, rle=True)
print(small)                     # <BMP 200x50 4-bit BI_RLE4 BITMAPINFOHEADER>
```

The encoder writes encoded runs for three or more equal pixels, word-aligned
absolute runs for everything else, an end-of-line escape after each row and
end-of-bitmap after the last. RLE4 absolute runs always have an even length,
because Pillow before 13.0 drops the last pixel of an odd one.

### Embedded PNG and JPEG

A `BI_PNG` or `BI_JPEG` file wraps a whole PNG or JPEG stream (mostly seen
from printer drivers). pybmp parses the headers, gives you the stream as is,
and decodes it with Pillow when Pillow is installed. Pillow is never required
otherwise.

```python
import io

import pybmp
from PIL import Image                        # only for making a PNG to embed

buf = io.BytesIO()
Image.new("RGB", (4, 3), (255, 0, 0)).save(buf, "PNG")

data = pybmp.encode_embedded(buf.getvalue())  # size read from the PNG header
img = pybmp.BMP(data=data)
print(img.embedded_format, img.size)          # png (4, 3)
assert img.embedded_image == buf.getvalue()   # the raw stream, no Pillow needed
print(img.open_embedded().getpixel((0, 0)))   # (255, 0, 0), decoded by Pillow
```

`embedded_image` is `None` for ordinary bitmaps, and `LazyBMP` has the same
properties. `to_rgb()` on an embedded file raises `UnsupportedFormatError`
pointing at these instead. `encode_embedded()` (or `BMP.from_embedded()`)
detects PNG or JPEG from the magic bytes and defaults to a V5 header.

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
$ pybmp convert in.bmp out.bmp --bits 8 --rle  # BI_RLE8 (indexed sources only)
$ python -m pybmp --version
```

`convert` accepts `--bits {1,2,4,8,16,24,32}`, `--top-down` or `--bottom-up`,
`--header {core,info,v4,v5}` and `--rle`. Indexed targets need an indexed source.

## Benchmarks

Measured with `python benchmarks/bench.py` on Python 3.13.5, Linux x86_64
(best of 5 runs, milliseconds). "1.x parse" is the last pybmp 1.x code (the
PR #1 merge commit), which hexlifies the whole file. "2.x parse" builds a `BMP` and
reads `PIXELARRAY`. "naive loop" is a reference per-pixel Python decoder, not
part of either version. Your numbers will vary by machine.

| Image (24-bit) | File MB | 1.x parse | 2.x parse | Speed-up | 2.x `to_rgb` | Pillow `open+tobytes` | naive loop decode |
|---|---|---|---|---|---|---|---|
| 64x64 | 0.01 | 0.03 | 0.018 | 2x | 0.03 | 0.04 | 0.7 |
| 512x512 | 0.79 | 1.85 | 0.107 | 17x | 0.54 | 0.43 | 42.1 |
| 1024x1024 | 3.15 | 7.17 | 0.474 | 15x | 2.32 | 1.62 | 167.0 |
| 2048x2048 | 12.58 | 31.61 | 1.589 | 20x | 8.97 | 6.44 | - |
| 4096x4096 | 50.33 | 87.05 | 38.250 | 2x | 138.46 | 85.21 | - |

Decode and encode at 2048x2048 (4.2 megapixels), milliseconds:

| Format | 2.x decode to RGB(A) | Pillow decode | 2.x encode |
|---|---|---|---|
| 1-bit indexed | 15.9 | 4.8 | 35.8 |
| 4-bit indexed | 16.0 | 5.0 | 32.9 |
| 8-bit indexed | 12.5 | 4.2 | 24.1 |
| 16-bit RGB555 | 20.8 | 12.3 | 30.5 |
| 24-bit RGB | 7.9 | 6.6 | 10.1 |
| 32-bit RGBA (V4) | 13.6 | 5.4 | 13.8 |

pybmp 1.x could not decode pixels at all, so there is no 1.x column for
decoding. Pure-Python 2.x decoding is 20-80x faster than a per-pixel loop and
within 1.2-3.5x of Pillow's C decoder.

Lazy reading of a 4096x4096 24-bit file (50 MB), milliseconds. The eager
column always reads and decodes the whole file:

| Operation | eager `BMP` | `open_lazy` (mmap) |
|---|---|---|
| open + read headers | 3.35 | 0.029 |
| open + decode one row | 113.19 | 0.054 |
| open + decode every row (`iter_rows`) | 107.51 | 33.69 |

RLE on a 2048x2048 image of flat colour bands with a noisy row every 16 rows:

| Format | Size (KB) | 2.x encode | 2.x decode to RGB | Pillow decode |
|---|---|---|---|---|
| 8-bit raw | 4097 | 25.4 | 12.3 | 4.4 |
| 8-bit RLE | 384 | 96.2 | 32.2 | 14.2 |
| 4-bit raw | 2048 | 30.7 | 15.9 | 5.0 |
| 4-bit RLE | 255 | 96.3 | 40.9 | 185.2 |

## Development

```shell
pip install -e ".[dev]"
pytest --cov                 # tests, with coverage (CI requires >= 90%)
ruff check . && ruff format --check .
mypy                         # strict type checking of src/ and tests/
python benchmarks/bench.py   # benchmarks against the last 1.x code
python -m build && twine check dist/*
```

The test suite covers every module: header parsing, decoding of every bit
depth and compression, round trips across depths, header versions,
orientations and padded widths, lazy reading from every source type, RLE
encoding checked by a strict spec decoder and by Pillow, embedded PNG/JPEG,
malformed and truncated files, the CLI, the 1.x compatibility layer,
cross-checks against Pillow, and the code examples in this README.

## Contributing

Bug reports and pull requests are welcome.

1. Fork the repository and create a branch from `master`.
2. Install the dev extras: `pip install -e ".[dev]"`.
3. Add tests for your change. For decoder fixes, a small hand-built file in
   `tests/helpers.py` style is ideal.
4. Make sure `pytest --cov`, `ruff check .`, `ruff format --check .` and `mypy`
   all pass. CI runs them on Python 3.10 to 3.13.
5. Open a pull request describing the change.

## What's new in 2.1

- `open_lazy()` / `LazyBMP`: header-only opening and on-demand rows from a
  memory map, file object or bytes, with a context-manager API.
- `rle=True` writes `BI_RLE8` / `BI_RLE4`, also as `pybmp convert --rle`.
- `embedded_image`, `embedded_format` and `open_embedded()` for `BI_PNG` /
  `BI_JPEG` files, plus `encode_embedded()` / `BMP.from_embedded()` to write
  them. Such files with `biBitCount` 0 now parse instead of raising
  `InvalidBMPError`.

All 2.0 code keeps working unchanged. See the [CHANGELOG](CHANGELOG.md).

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
