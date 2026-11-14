"""Benchmark pybmp 2.x against the last pybmp 1.x code (``master`` after PR #1).

Usage::

    python benchmarks/bench.py            # loads 1.x with `git show <OLD_REF>:...`
    python benchmarks/bench.py --old path/to/old/__init__.py

Every figure is the best of ``--repeat`` runs (milliseconds).
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pybmp

#: Merge commit of PR #1: the last 1.x code before the 2.0 rewrite.
OLD_REF = "1ba6a007747ba315b1fa6d72c1446125489c2a42"

SIZES = [(64, 64), (512, 512), (1024, 1024), (2048, 2048), (4096, 4096)]


def load_old(path: str | None) -> ModuleType:
    if path is None:
        src = subprocess.run(
            ["git", "show", f"{OLD_REF}:pybmp/__init__.py"],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        ).stdout
        tmp = Path(tempfile.mkdtemp()) / "pybmp_old.py"
        tmp.write_text(src)
        path = str(tmp)
    spec = importlib.util.spec_from_file_location("pybmp_old", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def best(fn: Callable[[], object], repeat: int) -> float:
    times = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t)
    return min(times) * 1000


def naive_decode_24(data: bytes, w: int, h: int) -> bytes:
    """Reference per-pixel loop (what a straightforward decoder would do)."""
    off = int.from_bytes(data[10:14], "little")
    stride = (w * 3 + 3) & ~3
    out = bytearray()
    for y in range(h - 1, -1, -1):
        row = off + y * stride
        for x in range(w):
            b, g, r = data[row + 3 * x : row + 3 * x + 3]
            out += bytes((r, g, b))
    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--naive-max", type=int, default=1024)
    args = ap.parse_args()
    old = load_old(args.old)
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        Image = None  # noqa: N806

    print(
        f"Python {platform.python_version()} on {platform.machine()} "
        f"({platform.system()}), best of {args.repeat}, times in ms\n"
    )
    print(
        "| Image (24-bit) | File MB | 1.x parse (file) | 2.x parse (file) | Speed-up "
        "| 2.x to_rgb | Pillow open+tobytes | naive loop decode |"
    )
    print("|---|---|---|---|---|---|---|---|")
    tmpdir = Path(tempfile.mkdtemp())
    for w, h in SIZES:
        rgb = bytes(range(256)) * (w * h * 3 // 256 + 1)
        data = pybmp.encode(w, h, rgb[: w * h * 3])
        path = tmpdir / f"{w}x{h}.bmp"
        path.write_bytes(data)
        t_old = best(lambda: old.BMP(filename=str(path)).PIXELARRAY, args.repeat)
        t_new = best(lambda: pybmp.BMP(path).PIXELARRAY, args.repeat)
        t_rgb = best(lambda: pybmp.BMP(path).to_rgb(), args.repeat)
        t_pil = (
            best(lambda: Image.open(path).tobytes(), args.repeat)
            if Image
            else float("nan")
        )
        naive = (
            f"{best(lambda: naive_decode_24(data, w, h), 1):.1f}"
            if w <= args.naive_max
            else "-"
        )
        print(
            f"| {w}x{h} | {len(data) / 1e6:.2f} | {t_old:.2f} | {t_new:.3f} | "
            f"{t_old / t_new:.0f}x | {t_rgb:.2f} | {t_pil:.2f} | {naive} |"
        )

    print("\n2.x decode/encode throughput at 2048x2048 (ms):\n")
    print("| Format | decode to RGB | Pillow decode | encode |")
    print("|---|---|---|---|")
    w = h = 2048
    rgb = (bytes(range(256)) * (w * h * 3 // 256 + 1))[: w * h * 3]
    idx = (bytes(range(256)) * (w * h // 256 + 1))[: w * h]
    pal = [(i, 255 - i, i // 2) for i in range(256)]
    rgba = (bytes(range(256)) * (w * h * 4 // 256 + 1))[: w * h * 4]
    cases: list[tuple[str, dict[str, object], bytes]] = [
        (
            "1-bit indexed",
            {"mode": "P", "bits": 1, "palette": pal[:2]},
            bytes(b & 1 for b in idx),
        ),
        (
            "4-bit indexed",
            {"mode": "P", "bits": 4, "palette": pal[:16]},
            bytes(b & 15 for b in idx),
        ),
        ("8-bit indexed", {"mode": "P", "bits": 8, "palette": pal}, idx),
        ("16-bit RGB555", {"bits": 16}, rgb),
        ("24-bit RGB", {"bits": 24}, rgb),
        ("32-bit RGBA (V4)", {"mode": "RGBA"}, rgba),
    ]
    for name, kw, px in cases:
        t_enc = best(lambda: pybmp.encode(w, h, px, **kw), args.repeat)  # type: ignore[arg-type]
        data = pybmp.encode(w, h, px, **kw)  # type: ignore[arg-type]
        img = pybmp.BMP(data=data)
        dec = img.to_rgba if img.mode == "RGBA" else img.to_rgb
        t_dec = best(dec, args.repeat)
        pil_mode = "RGBA" if img.mode == "RGBA" else "RGB"
        t_pil = (
            best(
                lambda: Image.open(io.BytesIO(data)).convert(pil_mode).tobytes(),
                args.repeat,
            )
            if Image
            else float("nan")
        )
        print(f"| {name} | {t_dec:.1f} | {t_pil:.1f} | {t_enc:.1f} |")

    bench_lazy(tmpdir, args.repeat)
    bench_rle(args.repeat, Image)


def bench_lazy(tmpdir: Path, repeat: int) -> None:
    w = h = 4096
    rgb = (bytes(range(256)) * (w * h * 3 // 256 + 1))[: w * h * 3]
    path = tmpdir / "lazy.bmp"
    path.write_bytes(pybmp.encode(w, h, rgb))
    print(f"\nLazy reading of a {w}x{h} 24-bit file (50 MB), ms:\n")
    print("| Operation | eager `BMP` | `open_lazy` (mmap) |")
    print("|---|---|---|")

    def lazy_row() -> bytes:
        with pybmp.open_lazy(path) as img:
            return img.row(h // 2)

    def lazy_header() -> object:
        with pybmp.open_lazy(path) as img:
            return img.header

    def lazy_all() -> int:
        with pybmp.open_lazy(path) as img:
            return sum(len(r) for r in img.iter_rows())

    rows = [
        ("open + read headers", lambda: pybmp.BMP(path).header, lazy_header),
        ("open + decode one row", lambda: pybmp.BMP(path).to_rgb(), lazy_row),
        ("open + decode every row", lambda: pybmp.BMP(path).to_rgb(), lazy_all),
    ]
    for name, eager, lazy in rows:
        t_e, t_l = best(eager, repeat), best(lazy, repeat)
        print(f"| {name} | {t_e:.2f} | {t_l:.3f} |")


def bench_rle(repeat: int, Image: object) -> None:  # noqa: N803
    w = h = 2048
    pal = [(i, 255 - i, i // 2) for i in range(256)]
    # Horizontal bands of flat colour with a noisy stripe: typical RLE content.
    row_flat = b"".join(bytes([c]) * 64 for c in range(32))
    row_noisy = (bytes(range(7, 256, 7)) * 60)[:w]
    rows = [row_noisy if y % 16 == 0 else row_flat for y in range(h)]
    idx = b"".join(rows)
    print(f"\nRLE on a {w}x{h} banded 8-bit / 4-bit image:\n")
    print("| Format | size (KB) | encode ms | decode ms | Pillow decode ms |")
    print("|---|---|---|---|---|")
    for bits, rle in [(8, False), (8, True), (4, False), (4, True)]:
        px = idx if bits == 8 else bytes(v & 15 for v in idx)
        kw: dict[str, object] = {
            "mode": "P",
            "bits": bits,
            "palette": pal[: 1 << bits],
            "rle": rle,
        }
        t_enc = best(lambda: pybmp.encode(w, h, px, **kw), repeat)  # type: ignore[arg-type]
        data = pybmp.encode(w, h, px, **kw)  # type: ignore[arg-type]
        img = pybmp.BMP(data=data)
        t_dec = best(img.to_rgb, repeat)
        t_pil = (
            best(
                lambda: Image.open(io.BytesIO(data)).convert("RGB").tobytes(),  # type: ignore[attr-defined]
                repeat,
            )
            if Image
            else float("nan")
        )
        name = f"{bits}-bit {'RLE' if rle else 'raw'}"
        print(
            f"| {name} | {len(data) / 1024:.0f} | {t_enc:.1f} | {t_dec:.1f} "
            f"| {t_pil:.1f} |"
        )


if __name__ == "__main__":
    sys.exit(main())
