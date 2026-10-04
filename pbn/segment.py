"""Step 3 – colour classes -> paintable regions.

- connected components per colour (4-connectivity: with 8, two colours could cross
  diagonally and the boundary would be ambiguous)
- merge, smallest "effective size" first, until both max_regions and min_area_mm2 hold:
  - effective size = area × salience boost: a region whose mean picture colour stands out
    from all its neighbours' counts up to (1 + MAX_BOOST)× larger, so small accents (a star,
    a highlight) survive while smaller specks always go
  - the target is the neighbour whose mean picture colour is closest (Ward: least growth of
    the squared colour error), with a bonus for a long shared boundary
  - the union takes the palette colour closest to its mean picture colour, so a textured
    area ends up in its average colour, not in the colour of whichever speck grew first;
    touching same-colour regions fuse
  - regions above max_area_mm2 only take in specks that have no other neighbour
- smoothing: Gaussian blur per region, pixel -> region with the highest value
- necks: per-region opening with a disc of neck_mm; cut-off spikes and bridges go to the
  nearest other region
- width: regions whose inscribed circle is narrower than min_width_mm (default: too small for
  their number) are merged away
Output: out/regions.npz (labels, nr per region), out/regions.png (preview)
"""
from __future__ import annotations

import heapq
import json

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from .palette import load_palette, srgb_to_lab
from .quantize import features
from .vectorize import number_radius_mm

MAX_BOOST = 1.0     # salience boost: effective size up to (1 + MAX_BOOST) × area
BOUNDARY_DE = 10.0  # target choice: ΔE a neighbour may be further away if it holds the whole boundary


def components(cls: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """4-connected components per class -> (label map, class per label; label 0 unused)."""
    lab = np.zeros(cls.shape, np.int32)
    cls_of = [0]
    for c in np.unique(cls):
        l, n = ndimage.label(cls == c)
        lab[l > 0] = l[l > 0] + len(cls_of) - 1
        cls_of += [int(c)] * n
    return lab, np.array(cls_of)


def adjacency(lab: np.ndarray) -> dict[int, dict[int, int]]:
    """Shared boundary length (pixel edges) per region pair."""
    a = np.concatenate([lab[:, :-1].ravel(), lab[:-1, :].ravel()]).astype(np.int64)
    b = np.concatenate([lab[:, 1:].ravel(), lab[1:, :].ravel()]).astype(np.int64)
    m = a != b
    a, b = np.minimum(a[m], b[m]), np.maximum(a[m], b[m])
    base = int(lab.max()) + 1
    keys, counts = np.unique(a * base + b, return_counts=True)
    adj: dict[int, dict[int, int]] = {}
    for k, n in zip(keys.tolist(), counts.tolist()):
        i, j = divmod(k, base)
        adj.setdefault(i, {})[j] = n
        adj.setdefault(j, {})[i] = n
    return adj


def merge_regions(lab, cls_of, max_regions, min_px, cap_px, feat, recolor, contrast_de=np.inf, force=()):
    """feat: per-pixel features (H×W×C; the first 3 span the quantize distance).
    recolor(mean feature) -> class of a merged region. force: labels merged away regardless of size."""
    area = np.bincount(lab.ravel()).astype(np.int64)
    fsum = np.stack([np.bincount(lab.ravel(), feat[..., c].ravel(), len(area)) for c in range(feat.shape[-1])], -1)
    cls_of = cls_of.copy()
    adj = adjacency(lab)
    parent = np.arange(len(area))
    alive = set(range(1, len(area)))
    force = set(force)

    def mean(r: int) -> np.ndarray:
        return fsum[r, :3] / area[r]

    def key(r: int) -> float:
        if r in force:
            return -1.0
        if area[r] * (1 + MAX_BOOST) < min_px or not adj.get(r) or area[r] >= cap_px:
            return float(area[r])
        nb = list(adj[r])
        s = np.sqrt(((fsum[nb, :3] / area[nb, None] - mean(r)) ** 2).sum(-1)).min()  # to the most similar neighbour
        return float(area[r] * (1 + min((s / contrast_de) ** 2, MAX_BOOST)))

    def absorb(r: int, t: int) -> None:
        parent[r] = t
        area[t] += area[r]
        fsum[t] += fsum[r]
        alive.discard(r)
        for n, l in adj.pop(r).items():
            del adj[n][r]
            if n != t:
                adj[t][n] = adj[t].get(n, 0) + l
                adj[n][t] = adj[n].get(t, 0) + l

    def fuse_same_color(t: int) -> None:
        stack = [t]
        while stack:
            t = stack.pop()
            if t not in alive:
                continue
            same = [n for n in adj[t] if cls_of[n] == cls_of[t]]
            for n in same:
                absorb(n, t)
            if same:
                cls_of[t] = recolor(fsum[t] / area[t])
                stack.append(t)

    heap = [(key(r), r) for r in alive]
    heapq.heapify(heap)
    # ponytail: Python loop over ~10⁵ regions, a few seconds; fine.
    while heap:
        k, r = heapq.heappop(heap)
        if r not in alive:
            continue
        if (now := key(r)) != k:
            heapq.heappush(heap, (now, r))  # stale entry
            continue
        if len(alive) <= max_regions and k >= min_px:
            break
        if not adj.get(r):
            continue  # the only region in the picture
        cand = {n: l for n, l in adj[r].items() if area[n] < cap_px} or adj[r]
        nb, total = list(cand), sum(cand.values())
        # Ward: growth of the squared colour error, as ΔE of r's pixels; bonus for a long shared boundary
        de = np.sqrt(area[nb] / (area[nb] + area[r]) * ((fsum[nb, :3] / area[nb, None] - mean(r)) ** 2).sum(-1))
        t = nb[int(np.argmin(de + BOUNDARY_DE * (1 - np.array([cand[n] for n in nb]) / total)))]
        touched = set(adj[r]) - {t}
        absorb(r, t)
        cls_of[t] = recolor(fsum[t] / area[t])  # the union takes the colour closest to its mean
        fuse_same_color(t)
        for n in touched | {t}:  # their neighbourhood changed
            if n in alive:
                heapq.heappush(heap, (key(n), n))

    roots = parent.copy()
    while not np.array_equal(nxt := roots[roots], roots):
        roots = nxt
    final = sorted(alive)
    remap = np.zeros(len(parent), np.int32)
    remap[final] = np.arange(1, len(final) + 1)
    return remap[roots[lab]], cls_of[final]


def inscribed_radius(lab: np.ndarray) -> np.ndarray:
    """Radius (px) of the largest inscribed circle per region; index 0 = label 1."""
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        out.append(ndimage.distance_transform_edt(np.pad(lab[sl] == i, 1)).max())
    return np.array(out)


def cut_necks(lab: np.ndarray, r: int) -> np.ndarray:
    """Opening per region with a disc of radius r; removed pixels go to the nearest other region.
    Regions the opening would erase completely are left alone (min_width handles them)."""
    disc = np.hypot(*np.mgrid[-r:r + 1, -r:r + 1]) <= r
    out, pad = lab.copy(), r + 2
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        ys = slice(max(sl[0].start - pad, 0), sl[0].stop + pad)
        xs = slice(max(sl[1].start - pad, 0), sl[1].stop + pad)
        sub = lab[ys, xs]
        m = sub == i
        cut = m & ~ndimage.binary_opening(m, disc)
        others = ~m
        if not cut.any() or cut.sum() == m.sum() or not others.any():
            continue
        _, (iy, ix) = ndimage.distance_transform_edt(m, return_indices=True)
        o = out[ys, xs]  # view
        o[cut] = sub[iy[cut], ix[cut]]
    return out


def smooth_regions(lab: np.ndarray, sigma: float) -> np.ndarray:
    best = np.full(lab.shape, -1.0, np.float32)
    out = lab.copy()
    pad = int(3 * sigma) + 1
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        ys = slice(max(sl[0].start - pad, 0), sl[0].stop + pad)
        xs = slice(max(sl[1].start - pad, 0), sl[1].stop + pad)
        g = ndimage.gaussian_filter((lab[ys, xs] == i).astype(np.float32), sigma)
        b, o = best[ys, xs], out[ys, xs]  # views
        m = g > b
        b[m] = g[m]
        o[m] = i
    return out


def preview(lab, nr_of, palette, path):
    """Regions in palette colours, black boundaries, number at the innermost point."""
    color = {e["nr"]: e["hex"] for e in palette}
    lut = np.array([[255, 255, 255]] + [[int(color[n][i:i + 2], 16) for i in (1, 3, 5)] for n in nr_of], np.uint8)
    rgb = lut[lab]
    edge = np.zeros(lab.shape, bool)
    edge[:, 1:] |= lab[:, 1:] != lab[:, :-1]
    edge[1:, :] |= lab[1:, :] != lab[:-1, :]
    rgb[edge] = 0
    dist = ndimage.distance_transform_edt(np.pad(~edge, 1))[1:-1, 1:-1]  # picture edge counts as boundary
    pos = ndimage.maximum_position(dist, lab, np.arange(1, lab.max() + 1))
    im = Image.fromarray(rgb)
    draw = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=22)
    for (y, x), n in zip(pos, nr_of):
        draw.text((x, y), str(n), fill=(0, 0, 0), font=font, anchor="mm", stroke_width=2, stroke_fill=(255, 255, 255))
    im.save(path)


def run(p) -> None:
    s = p.seg
    cls = np.asarray(Image.open(p.out / "labels.png"))
    palette = json.loads((p.out / "palette.json").read_text())["palette"]
    mm_per_px = p.geometry(cls.shape[1], cls.shape[0])["mm_per_px"]
    min_px, cap_px = s["min_area_mm2"] / mm_per_px**2, s["max_area_mm2"] / mm_per_px**2

    lab_src = srgb_to_lab(np.asarray(Image.open(p.out / "source.png").convert("RGB")))
    feat = np.concatenate([features(lab_src, p.q), lab_src[..., :1]], -1)  # + raw L* for dark_only
    pal = load_palette(p.palette_path)
    pal_feat = features(np.array([e["lab"] for e in pal]), p.q, boost=False)
    pal_nr = np.array([e["nr"] for e in pal])
    dark_only = np.array([e["code"] in p.q["dark_only"] for e in pal])

    def recolor(m: np.ndarray) -> int:
        d = ((pal_feat - m[:3]) ** 2).sum(-1)
        d[dark_only & (m[3] >= p.q["dark_l"])] = np.inf
        return int(pal_nr[d.argmin()])

    def merge(lab, cls_of, force=()):
        return merge_regions(lab, cls_of, s["max_regions"], min_px, cap_px, feat, recolor, s["contrast_de"], force)

    def relabel(lab, nr_of):
        return components(np.concatenate([[0], nr_of])[lab])

    lab, cls_of = components(cls)
    print(f"  {len(cls_of) - 1} components")
    lab, nr_of = merge(lab, cls_of)
    if s["smooth_mm"] > 0:
        lab, nr_of = merge(*relabel(smooth_regions(lab, s["smooth_mm"] / mm_per_px), nr_of))
    if (r := round(s["neck_mm"] / 2 / mm_per_px)) >= 1:
        lab, nr_of = merge(*relabel(cut_necks(lab, r), nr_of))
    for _ in range(3):  # merging can create new narrow regions only rarely; a few rounds suffice
        if s["min_width_mm"] is None:  # auto: the region's number must fit (same test as vectorize)
            need = np.array([number_radius_mm(int(n), p.lay["digit_height_mm"]) for n in nr_of]) * 2
        else:
            need = s["min_width_mm"]
        thin = np.nonzero(inscribed_radius(lab) * 2 * mm_per_px < need)[0] + 1
        if not len(thin):
            break
        print(f"  {len(thin)} regions too narrow for {'their number' if s['min_width_mm'] is None else str(need) + ' mm'}: merged")
        lab, nr_of = merge(lab, np.concatenate([[0], nr_of]), thin)
    np.savez_compressed(p.out / "regions.npz", labels=lab, nr=nr_of)
    preview(lab, nr_of, palette, p.out / "regions.png")

    area = np.bincount(lab.ravel())[1:] * mm_per_px**2
    print(f"  {len(nr_of)} regions, area mm²: min {area.min():.0f} / median {np.median(area):.0f} / max {area.max():.0f}")
    for e in palette:
        m = nr_of == e["nr"]
        print(f"  {e['nr']:>2}. {e['code']:<5} {m.sum():4d} regions  {area[m].sum() / area.sum() * 100:5.1f} % area")
    print(f"  -> {p.out / 'regions.npz'}, {p.out / 'regions.png'}")
