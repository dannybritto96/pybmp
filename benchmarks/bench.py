"""Benchmark pybmp 2.x against the pybmp 1.x code on ``master``.

Usage::

    python benchmarks/bench.py            # loads 1.x from `git show master:...`
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

SIZES = [(64, 64), (512, 512), (1024, 1024), (2048, 2048), (4096, 4096)]


def load_old(path: str | None) -> ModuleType:
    if path is None:
        src = subprocess.run(
            ["git", "show", "master:pybmp/__init__.py"],
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


if __name__ == "__main__":
    sys.exit(main())
