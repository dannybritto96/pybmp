"""Tests for the ``pybmp`` command-line interface."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from pybmp import BMP, __version__, encode
from pybmp.cli import main


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    path = tmp_path / "in.bmp"
    path.write_bytes(encode(3, 2, bytes(range(18))))
    return path


def test_info_text(sample: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info", str(sample)]) == 0
    out = capsys.readouterr().out
    assert "3x2 24-bit BI_RGB BITMAPINFOHEADER" in out
    assert "bottom-up" in out


def test_info_json_single_and_multiple(
    sample: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["info", "--json", str(sample)]) == 0
    one = json.loads(capsys.readouterr().out)
    assert one["width"] == 3
    assert one["file"] == str(sample)
    assert main(["info", "--json", str(sample), str(sample)]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 2


def test_info_errors(
    tmp_path: Path, sample: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.bmp"
    bad.write_bytes(b"nope")
    assert main(["info", str(sample), str(bad), str(tmp_path / "missing.bmp")]) == 1
    captured = capsys.readouterr()
    assert "bad.bmp" in captured.err
    assert "missing.bmp" in captured.err
    assert "3x2" in captured.out
    assert main(["info", "--json", str(bad)]) == 1
    assert json.loads(capsys.readouterr().out) == {}


@pytest.mark.parametrize(
    ("args", "bits", "top_down", "header_size"),
    [
        ([], 24, False, 40),
        (["--bits", "32", "--top-down"], 32, True, 40),
        (["--bits", "16", "--header", "v5"], 16, False, 124),
        (["--bottom-up", "--header", "core"], 24, False, 12),
    ],
)
def test_convert(
    sample: Path,
    tmp_path: Path,
    args: list[str],
    bits: int,
    top_down: bool,
    header_size: int,
) -> None:
    out = tmp_path / "out.bmp"
    assert main(["convert", str(sample), str(out), *args]) == 0
    img = BMP(out)
    assert (img.bits_per_pixel, img.top_down, img.header.header_size) == (
        bits,
        top_down,
        header_size,
    )


def test_convert_error(
    sample: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["convert", str(sample), str(tmp_path / "o.bmp"), "--bits", "8"]) == 1
    assert "indexed" in capsys.readouterr().err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_python_dash_m(
    sample: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["pybmp", "info", str(sample)])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("pybmp", run_name="__main__")
    assert exc.value.code == 0
    assert "3x2" in capsys.readouterr().out
