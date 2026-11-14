# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [2.1.0] - unreleased

### Added
- Lazy and memory-mapped reading: `pybmp.open_lazy()` and `pybmp.LazyBMP`
  read only the headers and palette when opened, then decode rows on demand
  with `read_rows(start, stop)`, `row(y)`, `iter_rows()`, `get_pixel()` and
  `to_numpy(start, stop)`, in `"RGB"`, `"RGBA"` or `"P"` (indices) mode. Paths
  are memory-mapped (`use_mmap=False` for plain reads); file objects and
  `bytes`/`bytearray`/`memoryview` work too. It is a context manager, and
  `load()` returns an eager `BMP`. RLE files decode fully on the first row
  access and are cached (`random_access` is `False`).
- RLE encoding: `rle=True` on `encode()`, `write()`, `BMP.from_pixels()` and
  `BMP.convert()` writes `BI_RLE8` (8-bit) or `BI_RLE4` (4-bit) indexed
  images, with end-of-line and end-of-bitmap escapes and word-aligned absolute
  runs. RLE4 absolute runs are always even-length so Pillow before 13.0
  decodes them correctly. The CLI gains `pybmp convert --rle`.
- Embedded PNG/JPEG (`BI_PNG` / `BI_JPEG`): `BMP.embedded_format`,
  `BMP.embedded_image` (the raw stream), `BMP.open_embedded()` (decodes it with
  Pillow, an optional dependency) and `BMPHeader.embedded_format`, also on
  `LazyBMP`. `pybmp.encode_embedded()` and `BMP.from_embedded()` write such
  files, reading the size from the PNG `IHDR` or JPEG start-of-frame.
- Benchmarks for lazy reading and RLE.

### Changed
- `BI_PNG` / `BI_JPEG` files with `biBitCount` 0 (as the spec requires) now
  parse. They used to raise `InvalidBMPError`.
- `to_rgb()` and friends on an embedded PNG/JPEG file still raise
  `UnsupportedFormatError`, now with a message pointing at `embedded_image`
  and `open_embedded()`.

### Fixed
- `benchmarks/bench.py` loads the 1.x code from the PR #1 merge commit, since
  `master` no longer has it.

## [2.0.0] - 2026-11-13

A full rewrite of the library.

### Fixed
- `PIXELARRAY` now holds the whole stored pixel array. 1.x sliced the
  hexlified file using byte counts, so it returned only half the image. Thanks
  to [@buthanoid](https://github.com/buthanoid) for reporting and first fixing
  this in [PR #1](https://github.com/dannybritto96/pybmp/pull/1). 2.0 also reads
  the pixel array from the header's pixel-data offset (`bfOffBits`), not a
  hard-coded position, so files with palettes or bit-field masks work, and
  fixes the same problem for the core and V4 headers.
- `RAWIMGSIZE` was read from 3 bytes, which shifted `HORIZONTALRES`,
  `VERTICALRES`, `NCOLORS` and `NIMPCOLORS`. The V4 colour-space endpoints
  were read as 41 bytes instead of 36, which shifted the gamma fields.
- Integers are always decoded as little-endian (1.x used the host byte
  order). Width and height are signed, so top-down images report a negative
  `HEIGHT` instead of a huge unsigned number.
- The library no longer sets the `pybmp2` logger to `DEBUG` at import time and
  no longer logs at `INFO` for every file.

### Added
- Pixel decoding: `to_rgb()`, `to_rgba()`, `to_indices()`, `to_numpy()` and
  `get_pixel()` for 1/2/4/8/16/24/32-bit images with `BI_RGB`, `BI_RLE8`,
  `BI_RLE4`, `BI_BITFIELDS` and `BI_ALPHABITFIELDS`.
- Header versions 16, 52, 56, 64 (OS/2) and 124 (V5), in addition to 12, 40
  and 108.
- Encoding: `pybmp.encode()`, `pybmp.write()`, `BMP.from_pixels()`,
  `BMP.save()` and `BMP.convert()`.
- `pybmp.open()`, `BMP.open()`, `BMP.from_bytes()` and `BMP(data=...)`.
- A typed `BMPHeader` dataclass (`BMP.header`), the `Compression` enum and
  `parse_header()`.
- An exception hierarchy: `BMPError`, `InvalidBMPError`, `TruncatedFileError`,
  `HeaderNotSupported` and `UnsupportedFormatError`, all `ValueError`s.
- The `pybmp` command-line tool (`info`, `convert`) and `python -m pybmp`.
- Type hints (`py.typed`), a pytest suite with coverage, ruff, mypy, and
  GitHub Actions CI and release workflows.

### Changed
- Packaging moved to `pyproject.toml` (hatchling) with a `src/` layout.
  Python 3.10+ is required.
- `HEIGHT` and `SHAPE[1]` keep the on-disk sign (negative means top-down).
  Use `BMP.height` or `BMP.size` for positive values.
- `REDMASK`, `GREENMASK`, `BLUEMASK` and `ALPHAMASK` are the 4 little-endian
  bytes as stored, as before. Integer values are on `BMP.header`.
- Passing more than one of `filename`, `hexdata` and `data` raises
  `ValueError`. 1.x silently used the first.
- Malformed input raises `InvalidBMPError` or `TruncatedFileError`, not a
  `UnicodeDecodeError`, `binascii.Error` or silently wrong values.
- `compression_method()` returns the name and logs at `DEBUG`.

### Deprecated
- `BMP.unhexlify()` and `BMP.bytes2int()`. They emit `DeprecationWarning`.

### Removed
- `setup.py` and the committed `dist/` and `pybmp2.egg-info/` build artifacts.

## [1.0] - 2019

- First release: parses BMP file and DIB headers (12, 40 and 108 bytes) from a
  file or a hexlified string.
