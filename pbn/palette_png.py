"""Palette JSON -> PNG strip: one pixel per colour, left to right.

The image is one pixel high and as wide as the palette has colours, so a tool that
reads a palette as "one colour per pixel" can consume it directly. Up to 256 colours
it is written as an indexed PNG (mode P) whose embedded colour table *is* the palette;
above 256 the indexed format cannot hold it, so the strip falls back to RGB.

Accepts either a selection JSON (a bare list of entries, e.g. palettes/copic-sketch.json
or a project's palette.json) or a quantize output (an object with a "palette" key).
The colour is taken from "hex", falling back to "rgb".
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from .palette import hex_rgb


def load(path: Path) -> list[dict]:
    """Palette JSON -> entries. Auto-detects a bare list or a {"palette": [...]} object."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("palette")
    assert isinstance(data, list) and data, f"no palette entries in {path}"
    return data


def _rgb(entry: dict) -> tuple[int, int, int]:
    return hex_rgb(entry["hex"]) if entry.get("hex") else tuple(entry["rgb"])


def run(src: Path, dst: Path | None = None) -> None:
    colors = [_rgb(e) for e in load(src)]
    n = len(colors)
    dst = dst or src.with_suffix(".png")

    im = Image.new("P", (n, 1)) if n <= 256 else Image.new("RGB", (n, 1))
    if im.mode == "P":
        im.putpalette([v for c in colors for v in c] + [0] * (768 - 3 * n))
        im.putdata(range(n))
    else:
        im.putdata(colors)

    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst)
    print(f"  -> {dst}  ({n} colours, {im.mode})")
