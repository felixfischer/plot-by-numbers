"""Step 2 – map every pixel to the nearest palette colour (or paper white).

- distance in Lab: dL² + chroma_weight·(da² + db²)
- optional dark boost for photos: near-black, near-neutral pixels get more chroma and
  lightness spread, so dark brush strokes get their own colours instead of one black blob
- edge-aware smoothing (filter_mm > 0): cost-volume filtering – the cost of every palette
  colour is smoothed with a guided filter whose guide is the picture itself (Lab), then each
  pixel takes the cheapest colour. Texture and noise average out, real edges stay sharp, so
  regions follow the picture's edges instead of pixel noise.
- filter_mm = 0: the old noise removal, 3×3 majority filter (2×) + opening per class
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


def features(lab: np.ndarray, q: dict, boost: bool = True) -> np.ndarray:
    """Lab -> space where the Euclidean distance is the quantize distance. The dark boost
    applies to picture pixels only (boost=False for palette colours)."""
    f = boost_dark(lab, q) if boost else np.array(lab, np.float64)
    f[..., 1:] *= np.sqrt(q["chroma_weight"])
    return f


class GuidedFilter:
    """Guided filter (He et al. 2010) with a colour guide; the guide's statistics are computed
    once, then any number of single-channel inputs can be filtered against it."""

    def __init__(self, guide: np.ndarray, r: int, eps: float):
        self.I, self.r = guide.astype(np.float32), r
        self.mI = self.box(self.I)
        cov = self.box(self.I[..., :, None] * self.I[..., None, :]) - self.mI[..., :, None] * self.mI[..., None, :]
        self.inv = np.linalg.inv(cov + eps * np.eye(3, dtype=np.float32))

    def box(self, a: np.ndarray) -> np.ndarray:
        size = (2 * self.r + 1,) * 2 + (1,) * (a.ndim - 2)
        return ndimage.uniform_filter(a, size, mode="nearest")

    def __call__(self, p: np.ndarray) -> np.ndarray:
        p = p.astype(np.float32)
        mp = self.box(p)
        a = np.einsum("...ij,...j->...i", self.inv, self.box(self.I * p[..., None]) - self.mI * mp[..., None])
        b = mp - (a * self.mI).sum(-1)
        return (self.box(a) * self.I).sum(-1) + self.box(b)


def assign(lab: np.ndarray, palette: list[dict], q: dict, mm_per_px: float) -> np.ndarray:
    """Lab image + palette (from palette_from_entries) -> palette index per pixel, denoised."""
    f = features(lab, q)
    pal_f = features(np.array([e["lab"] for e in palette]), q, boost=False)
    cost = np.empty((*lab.shape[:2], len(palette)), np.float32)
    banned = np.zeros(cost.shape, bool)
    for j, e in enumerate(palette):
        cost[..., j] = np.sqrt(((f - pal_f[j]) ** 2).sum(-1))  # ΔE-like: keeps small accents (squared -> mean colour)
        if e["code"] in q["dark_only"]:
            banned[..., j] = lab[..., 0] >= q["dark_l"]
    r = round(q["filter_mm"] / mm_per_px)
    if r < 1:
        cost[banned] = np.inf
        return morph_open(majority_filter(cost.argmin(axis=-1)), len(palette))
    cost[banned] = 200.0  # finite while filtering, so the ban doesn't bleed into allowed pixels
    gf = GuidedFilter(f / 100.0, r, q["filter_eps"])
    for j in range(len(palette)):
        cost[..., j] = gf(cost[..., j])
    cost[banned] = np.inf
    return cost.argmin(axis=-1)


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
    mm_per_px = p.geometry(img.shape[1], img.shape[0])["mm_per_px"]
    mm2_per_px = mm_per_px ** 2
    lab = srgb_to_lab(img)
    palette = load_palette(p.palette_path)
    idx = assign(lab, palette, p.q, mm_per_px)

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
