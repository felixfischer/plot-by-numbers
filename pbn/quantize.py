"""Step 2 – map every pixel to the nearest palette colour (or paper white).

- distance in Lab: dL² + chroma_weight·(da² + db²)
- optional dark boost for photos: near-black, near-neutral pixels get more chroma and
  lightness spread, so dark brush strokes get their own colours instead of one black blob
- noise removal: 3×3 majority filter (2×) + morphological opening per class
Output: out/labels.png (pixel = palette nr), out/palette.json, out/quantized_compare.png
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from scipy import ndimage

from .config import dump_json
from .palette import lab_to_srgb, load_palette, srgb_to_lab


def boost_dark(lab: np.ndarray, q: dict) -> np.ndarray:
    """Full effect below L* = dark_l − dark_span, faded out at dark_l; only for chroma < dark_c."""
    w = np.clip((q["dark_l"] - lab[..., 0]) / q["dark_span"], 0.0, 1.0)
    w *= np.clip((q["dark_c"] - np.hypot(lab[..., 1], lab[..., 2])) / 10.0, 0.0, 1.0)
    k = 1.0 + (q["dark_boost"] - 1.0) * w
    out = lab.copy()
    out[..., 0] = 4.0 + (lab[..., 0] - 4.0) * (1.0 + (k - 1.0) / 2)
    out[..., 1:] *= k[..., None]
    return out


def majority_filter(idx: np.ndarray, iters: int = 2) -> np.ndarray:
    onehot = (idx[..., None] == np.arange(int(idx.max()) + 1)).astype(np.float32)
    for _ in range(iters):
        onehot = ndimage.convolve(onehot, np.ones((3, 3, 1), np.float32), mode="nearest")
        idx = onehot.argmax(axis=-1).astype(np.int64)
    return idx


def morph_open(idx: np.ndarray, n: int) -> np.ndarray:
    """Opening (3×3) per class; pixels no opened class covers keep their label."""
    s = np.ones((3, 3), bool)
    out, filled = idx.copy(), np.zeros(idx.shape, bool)
    for i in range(n):
        take = ndimage.binary_dilation(ndimage.binary_erosion(idx == i, structure=s), structure=s) & ~filled
        out[take] = i
        filled |= take
    return out


def assign(lab: np.ndarray, palette: list[dict], q: dict) -> np.ndarray:
    """Lab image + palette (from palette_from_entries) -> palette index per pixel, denoised."""
    lab_q = boost_dark(lab, q)
    pal_lab = np.array([e["lab"] for e in palette])
    dist = np.empty((*lab.shape[:2], len(palette)))
    for j, e in enumerate(palette):
        dL, da, db = (lab_q[..., c] - pal_lab[j, c] for c in range(3))
        dist[..., j] = dL * dL + q["chroma_weight"] * (da * da + db * db)
        if e["code"] in q["dark_only"]:
            dist[..., j][lab[..., 0] >= q["dark_l"]] = np.inf
    return morph_open(majority_filter(dist.argmin(axis=-1)), len(palette))


def stats(lab: np.ndarray, idx: np.ndarray, palette: list[dict], mm2_per_px: float) -> list[dict]:
    """Per palette colour: share, area and the mean colour of its pixels; sorted by nr."""
    out = []
    for i, e in enumerate(palette):
        mask = idx == i
        mean = lab[mask].mean(axis=0) if mask.any() else e["lab"]
        out.append(dict(nr=e["nr"], code=e["code"], name=e["name"], hex=e["hex"],
                        hex_mean="#%02x%02x%02x" % tuple(lab_to_srgb(mean)) if mask.any() else "",
                        share_pct=round(float(mask.mean() * 100), 2),
                        area_mm2=round(float(mask.sum() * mm2_per_px))))
    return sorted(out, key=lambda s: s["nr"])


def run(p) -> None:
    img = np.asarray(Image.open(p.out / "source.png").convert("RGB"))
    mm2_per_px = p.geometry(img.shape[1], img.shape[0])["mm_per_px"] ** 2
    lab = srgb_to_lab(img)
    palette = load_palette(p.palette_path)
    idx = assign(lab, palette, p.q)

    nr_of = np.array([e["nr"] for e in palette], np.uint8)
    Image.fromarray(nr_of[idx]).save(p.out / "labels.png")

    rgb_out = np.array([lab_to_srgb(e["lab"]) for e in palette])[idx]
    st = stats(lab, idx, palette, mm2_per_px)

    h, w = idx.shape
    cmp = Image.new("RGB", (w * 2 + 12, h), (30, 30, 30))
    cmp.paste(Image.fromarray(img), (0, 0))
    cmp.paste(Image.fromarray(rgb_out), (w + 12, 0))
    cmp.resize((cmp.width * 2 // 3, cmp.height * 2 // 3), Image.LANCZOS).save(p.out / "quantized_compare.png")
    print(f"  -> {p.out / 'quantized_compare.png'}")
    dump_json(p.out / "palette.json", dict(
        palette=st, note="nr = painting order (1 = lightest, 0 = paper white); "
                         "hex_mean = average colour of the pixels mapped to it"))
    for s in st:
        print(f"  {s['nr']:>2}. {s['code']:<5} {s['name']:<26} {s['hex']}  {s['share_pct']:5.2f} %  ({s['area_mm2']:6.0f} mm²)")
