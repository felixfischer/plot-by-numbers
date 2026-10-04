"""Step 1 – source image -> out/source.png at working size.

- SVG: rendered without antialiasing (ImageMagick), so every pixel is a pure fill colour.
- Raster: optionally `crop_scan` (photo of a canvas on a light background: measure the tilt
  at the right canvas edge, rotate, shave off the background border), then LANCZOS-resized.
- `aspect` forces the width/height ratio (stretching), e.g. to the painting's real size.
"""
from __future__ import annotations

import math
import subprocess

import numpy as np
from PIL import Image


def bg_mask(arr: np.ndarray) -> np.ndarray:
    """Cream or white scan background."""
    r, g, b = (arr[..., i].astype(np.int32) for i in range(3))
    L = 0.299 * r + 0.587 * g + 0.114 * b
    cream = ((r > 140) & (4 <= r - g) & (r - g <= 55) & (10 <= g - b) & (g - b <= 70)
             & (25 <= r - b) & (r - b <= 130) & (L > 140))
    return cream | (np.minimum(np.minimum(r, g), b) > 225)


def first_run(a: np.ndarray, run: int = 4) -> np.ndarray:
    """Per row: first x where `run` consecutive True start (-1 if none)."""
    ok = a.copy()
    for _ in range(run - 1):
        shifted = np.roll(ok, 1, axis=1)
        shifted[:, 0] = False
        ok = a & shifted
    out = np.full(a.shape[0], -1)
    rows = ok.any(axis=1)
    out[rows] = np.argmax(ok, axis=1)[rows]
    return out


def crop_scan(img: Image.Image) -> Image.Image:
    arr = np.asarray(img)
    h, w = arr.shape[:2]
    right = first_run(~bg_mask(arr)[:, ::-1])
    y = np.arange(h)
    m = (y >= h * 0.15) & (y < h * 0.85) & (right >= 0)
    tilt = math.degrees(math.atan(np.polyfit(y[m], w - 1 - right[m], 1)[0]))
    assert abs(tilt) < 3.0, f"implausible tilt {tilt:.2f}°"
    if abs(tilt) > 0.05:
        img = img.rotate(-tilt, expand=True, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    print(f"  tilt {tilt:+.3f}°")

    # shave 2 px at a time while the edge strip is > 12 % background (max 120 px per side)
    bg = bg_mask(np.asarray(img))
    h, w = bg.shape
    rows, cols = slice(int(h * 0.2), int(h * 0.8)), slice(int(w * 0.2), int(w * 0.8))
    x0, x1, y0, y1 = 0, w, 0, h
    while x0 < 120 and bg[rows, x0].mean() > 0.12: x0 += 2
    while w - x1 < 120 and bg[rows, x1 - 1].mean() > 0.12: x1 -= 2
    while y0 < 120 and bg[y0, cols].mean() > 0.12: y0 += 2
    while h - y1 < 120 and bg[y1 - 1, cols].mean() > 0.12: y1 -= 2
    print(f"  shaved L {x0}, R {w - x1}, T {y0}, B {h - y1} px")
    return img.crop((x0, y0, x1, y1))


def render_svg(src, dst, W: int, aspect: float | None = None, density: int | None = None) -> int:
    """Render an SVG at width W without antialiasing (ImageMagick 7); returns the height."""
    nat_w, nat_h = map(int, subprocess.run(["magick", "identify", "-format", "%w %h", str(src)],
                                           check=True, capture_output=True, text=True).stdout.split())
    H = round(W / (aspect or nat_w / nat_h))
    density = density or math.ceil(72 * max(W / nat_w, H / nat_h))
    subprocess.run(["magick", "+antialias", "-density", str(density), str(src), "-background", "white",
                    "-flatten", "-filter", "point", "-resize", f"{W}x{H}!", "-depth", "8", str(dst)], check=True)
    return H


def run(p) -> None:
    cfg = p.cfg
    W = cfg["work_width"]
    p.out.mkdir(parents=True, exist_ok=True)
    dst = p.out / "source.png"
    if p.source.suffix.lower() == ".svg":
        H = render_svg(p.source, dst, W, cfg["aspect"], cfg["svg_density"])
    else:
        img = Image.open(p.source).convert("RGB")
        if cfg["crop_scan"]:
            img = crop_scan(img)
        H = round(W / (cfg["aspect"] or img.width / img.height))
        img.resize((W, H), Image.LANCZOS).save(dst)
    print(f"  -> {dst} ({W}×{H} px)")
