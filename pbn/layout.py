"""Step 5 – sheet layout in mm (origin bottom left) + legend + proofs.

- picture + legend centred as one block on the drawable area, frame around the picture
- legend: one column, per colour "nr [box] code", text at digit_height_mm
- L-shaped corner marks at the corners of the drawable area
Output: out/layout.json (polylines per group), out/preview.svg/.png (line proof 1:1),
        out/preview_color.png, out/color-reference.png/.pdf (not plotted)
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

from . import font
from .palette import hex_rgb, load_palette

MARK, MARK_INSET = 5.0, 1.0
PX_PER_MM = 8  # proof resolution


def rect(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]


def legend_rows(p, g, n):
    """-> box size, [(nr, box x, box y)] for nr 1..n, vertically centred."""
    box = min(p.lay["box_mm"], (g["img_h"] + 6.0) / n - 6.0)
    pitch = box + 6.0
    top = p.plot_h / 2 + (n * pitch - 6.0) / 2
    bx = g["x0"] + g["img_w"] + p.lay["gap_mm"] + 4.0
    return box, [(nr, bx, top - (nr - 1) * pitch - box) for nr in range(1, n + 1)]


def run(p) -> None:
    v = json.loads((p.out / "vectors.json").read_text())
    W, H = v["size"]
    g = p.geometry(W, H)
    s, x0, y0 = g["mm_per_px"], g["x0"], g["y0"]
    dh, pw, ph = p.lay["digit_height_mm"], p.plot_w, p.plot_h

    def to_mm(x, y):  # px (y down) -> mm (y up)
        return (round(x0 + x * s, 3), round(y0 + (H - y) * s, 3))

    groups = {
        "contours": [[to_mm(x, y) for x, y in l] for l in v["lines"]],
        "digits": [st for d in v["digits"] for st in font.text(str(d["nr"]), *to_mm(d["x"], d["y"]), d["h_mm"])],
        "legend": [],
        "frame": [rect(x0, y0, g["img_w"], g["img_h"])],
    }

    pal = sorted((e for e in load_palette(p.palette_path) if e["nr"] > 0), key=lambda e: e["nr"])
    box, rows = legend_rows(p, g, len(pal))
    legend_right = x0 + g["img_w"] + p.lay["gap_mm"] + p.lay["legend_width_mm"]
    for e, (nr, bx, by) in zip(pal, rows):
        cw = font.text_width(e["code"], dh)
        groups["legend"].append(rect(bx, by, box, box))
        groups["legend"] += font.text(str(nr), bx - 2.5, by + box / 2, dh)
        groups["legend"] += font.text(e["code"], bx + box + 1.5 + cw / 2, by + box / 2, dh)
        assert bx + box + 1.5 + cw <= legend_right + 1e-6, f"code {e['code']} wider than legend_width_mm"
    assert legend_right <= pw - p.lay["margin_mm"] + 1e-6, "legend runs off the drawable area"

    for cx, sx in ((MARK_INSET, 1), (pw - MARK_INSET, -1)):
        for cy, sy in ((MARK_INSET, 1), (ph - MARK_INSET, -1)):
            groups["frame"].append([(cx + sx * MARK, cy), (cx, cy), (cx, cy + sy * MARK)])
    (p.out / "layout.json").write_text(json.dumps(dict(size_mm=[pw, ph], groups=groups)))

    # line proofs
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{pw}mm" height="{ph}mm" viewBox="0 0 {pw} {ph}">',
           f'<rect width="{pw}" height="{ph}" fill="white"/>',
           f'<g fill="none" stroke="#555" stroke-width="0.25" stroke-linejoin="round" transform="matrix(1 0 0 -1 0 {ph})">']
    lines_im = Image.new("L", (int(pw * PX_PER_MM), int(ph * PX_PER_MM)), 255)
    dr = ImageDraw.Draw(lines_im)
    for ls in groups.values():
        for l in ls:
            svg.append(f'<polyline points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in l)}"/>')
            dr.line([(x * PX_PER_MM, (ph - y) * PX_PER_MM) for x, y in l], fill=60, width=2, joint="curve")
    (p.out / "preview.svg").write_text("\n".join(svg + ["</g></svg>"]))
    lines_im.save(p.out / "preview.png")

    # colour proof: regions in palette colours under the plot lines
    col = {e["nr"]: hex_rgb(e["hex"]) for e in pal}
    z = np.load(p.out / "regions.npz")
    lut = np.array([(255, 255, 255)] + [col.get(n, (255, 255, 255)) for n in z["nr"]], np.uint8)
    canvas = Image.new("RGB", lines_im.size, "white")
    canvas.paste(Image.fromarray(lut[z["labels"]]).resize((round(g["img_w"] * PX_PER_MM), round(g["img_h"] * PX_PER_MM)),
                                                         Image.NEAREST),
                 (round(x0 * PX_PER_MM), round((ph - y0 - g["img_h"]) * PX_PER_MM)))
    d = ImageDraw.Draw(canvas)
    for nr, bx, by in rows:
        d.rectangle((bx * PX_PER_MM, (ph - by - box) * PX_PER_MM, (bx + box) * PX_PER_MM, (ph - by) * PX_PER_MM), fill=col[nr])
    ImageChops.multiply(canvas, lines_im.convert("RGB")).save(p.out / "preview_color.png")

    # colour reference sheet (not plotted)
    ref = Image.new("RGB", (900, 80 + 70 * len(pal)), "white")
    d = ImageDraw.Draw(ref)
    f = ImageFont.load_default(size=26)
    d.text((20, 20), f"Colour reference – paint light (1) to dark ({len(pal)}), leave paper white blank", fill="black", font=f)
    for i, e in enumerate(pal):
        y = 70 + i * 70
        d.rectangle((20, y, 120, y + 55), fill=e["hex"], outline="black")
        d.text((140, y + 12), f'{e["nr"]:>2}   {e["code"]}  {e["name"]}   {e["hex"]}', fill="black", font=f)
    ref.save(p.out / "color-reference.png")
    ref.save(p.out / "color-reference.pdf")

    print("  " + ", ".join(f"{k}: {len(l)}" for k, l in groups.items()) + " polylines")
    print(f"  -> {p.out}/layout.json, preview.svg/.png, preview_color.png, color-reference.png/.pdf")
