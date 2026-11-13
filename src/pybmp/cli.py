"""Command-line interface: ``pybmp info`` and ``pybmp convert``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING

from . import __version__
from ._bmp import BMP
from ._errors import BMPError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pybmp", description="Inspect and convert BMP images."
    )
    parser.add_argument("--version", action="version", version=f"pybmp {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="print the headers of one or more BMP files")
    info.add_argument("files", nargs="+", metavar="FILE")
    info.add_argument("--json", action="store_true", help="print JSON")

    conv = sub.add_parser("convert", help="re-encode a BMP with a different format")
    conv.add_argument("source", metavar="SRC")
    conv.add_argument("dest", metavar="DST")
    conv.add_argument("--bits", type=int, choices=(1, 2, 4, 8, 16, 24, 32))
    order = conv.add_mutually_exclusive_group()
    order.add_argument("--top-down", dest="top_down", action="store_true", default=None)
    order.add_argument("--bottom-up", dest="top_down", action="store_false")
    conv.add_argument("--header", choices=("core", "info", "v4", "v5"))
    return parser


def _info(files: Sequence[str], as_json: bool) -> int:
    results = []
    status = 0
    for path in files:
        try:
            results.append({"file": path, **BMP(path).info()})
        except (OSError, BMPError) as exc:
            print(f"pybmp: {path}: {exc}", file=sys.stderr)
            status = 1
    if as_json:
        payload: object = results if len(files) > 1 else (results or [{}])[0]
        print(json.dumps(payload, indent=2))
    else:
        for r in results:
            print(
                f"{r['file']}: {r['width']}x{r['height']} {r['bits_per_pixel']}-bit "
                f"{r['compression']} {r['header']} "
                f"({'top-down' if r['top_down'] else 'bottom-up'}, {r['mode']}, "
                f"palette={r['palette_size']}, offset={r['pixel_offset']})"
            )
    return status


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    args = _build_parser().parse_args(argv)
    if args.command == "info":
        return _info(args.files, args.json)
    try:
        BMP(args.source).convert(
            bits=args.bits, top_down=args.top_down, header=args.header
        ).save(args.dest)
    except (OSError, BMPError) as exc:
        print(f"pybmp: {exc}", file=sys.stderr)
        return 1
    return 0
