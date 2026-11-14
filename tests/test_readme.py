"""Execute every ``python`` code block in README.md, in order."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parent.parent / "README.md"
BLOCKS = re.findall(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), re.S)


def test_readme_has_examples() -> None:
    assert len(BLOCKS) >= 5


def test_readme_examples_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    monkeypatch.chdir(tmp_path)
    for i, block in enumerate(BLOCKS):
        exec(
            compile(block, f"README.md[block {i}]", "exec"), {"__name__": "__readme__"}
        )
    out = capsys.readouterr().out
    assert "<BMP 3x2 24-bit BI_RGB BITMAPINFOHEADER>" in out
    assert "(3, 2) RGB" in out
    assert "(0, 0, 255)" in out
    assert "(2, 3, 3)" in out
    assert "2 4" in out
    assert "not a BMP:" in out
    assert "(3, 2) 24 24" in out
    assert "(3, 2) RGB True" in out
    assert "(255, 255, 0)" in out
    assert "362 10062" in out
    assert "<BMP 200x50 4-bit BI_RLE4 BITMAPINFOHEADER>" in out
    assert "png (4, 3)" in out
    assert "(255, 0, 0)" in out


def test_readme_cli_example(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pybmp.cli import main

    monkeypatch.chdir(tmp_path)
    exec(compile(BLOCKS[0], "README.md[0]", "exec"), {})
    capsys.readouterr()
    assert main(["info", "example.bmp"]) == 0
    expected = re.search(
        r"\$ pybmp info example.bmp\n(.*)\n", README.read_text()
    ).group(1)  # type: ignore[union-attr]
    assert capsys.readouterr().out.strip() == expected
