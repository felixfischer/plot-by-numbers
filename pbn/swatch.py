"""A4 swatch card (PDF) for an inventory: digital colour next to an empty field for a real
stroke of the pen/paint, so you can check how far the published hex values are off.
--bw: toner-friendly variant without colour fills."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DPI = 300
W, H = 2480, 3508  # A4 @ 300 dpi
MM = DPI / 25.4
COLS = 6


def _font(size: int):
    for name in ("Helvetica.ttc", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def run(src: Path, dst: Path | None = None, bw: bool = False) -> None:
    dst = dst or Path(f"swatch-{src.stem}{'-bw' if bw else ''}.pdf")
    colors = json.loads(src.read_text(encoding="utf-8"))
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    title, small, tiny = _font(80), _font(34), _font(28)

    m = int(12 * MM)
    d.text((m, m), src.stem, font=title, fill="black")
    sub = "fill each field with a real stroke" if bw else "left: digital, right: real stroke"
    d.text((m, m + 100), f"{len(colors)} colours · {sub}", font=small, fill="#666")

    top = m + 190
    rows = -(-len(colors) // COLS)
    cw, ch = (W - 2 * m) // COLS, (H - top - m) // rows
    pad = 14
    for i, c in enumerate(colors):
        x, y = m + (i % COLS) * cw, top + (i // COLS) * ch
        sw, sh = (cw - 2 * pad) // 2, ch - 2 * pad - 90
        if not bw:
            d.rectangle((x + pad, y + pad, x + pad + sw, y + pad + sh), fill=tuple(c["rgb"]))
            d.rectangle((x + pad + sw, y + pad, x + cw - pad, y + pad + sh), outline="#bbb", width=3)
        d.rectangle((x + pad, y + pad, x + cw - pad, y + pad + sh), outline="#bbb", width=3)
        ty = y + pad + sh + 10
        d.text((x + pad, ty), f'{c["code"]}  {c["name"]}', font=small, fill="black")
        d.text((x + pad, ty + 42), c["hex"], font=tiny, fill="#777")

    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, resolution=DPI)
    print(f"  -> {dst}")
