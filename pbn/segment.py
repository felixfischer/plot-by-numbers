"""Step 3 – colour classes -> paintable regions.

- connected components per colour (4-connectivity: with 8, two colours could cross
  diagonally and the boundary would be ambiguous)
- smallest-first merge: the smallest region joins the neighbour with the longest shared
  boundary until both max_regions and min_area_mm2 hold; touching same-colour regions fuse.
  Regions above max_area_mm2 only take in specks that have no other neighbour.
- smoothing: Gaussian blur per region, pixel -> region with the highest value; then
  components + merge again for the splinters this creates
Output: out/regions.npz (labels, nr per region), out/regions.png (preview)
"""
from __future__ import annotations

import heapq
import json

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage


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


def merge_regions(lab, cls_of, max_regions, min_px, cap_px=np.inf):
    area = np.bincount(lab.ravel()).astype(np.int64)
    adj = adjacency(lab)
    parent = np.arange(len(area))
    alive = set(range(1, len(area)))

    def absorb(r: int, t: int) -> None:
        parent[r] = t
        area[t] += area[r]
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
                stack.append(t)

    heap = [(int(area[r]), r) for r in alive]
    heapq.heapify(heap)
    # ponytail: Python loop over ~10⁵ regions, a few seconds; fine.
    while heap:
        a, r = heapq.heappop(heap)
        if r not in alive or a != area[r]:
            continue  # stale heap entry
        if len(alive) <= max_regions and a >= min_px:
            break
        if not adj.get(r):
            continue  # the only region in the picture
        small = {n: l for n, l in adj[r].items() if area[n] < cap_px}
        cand = small or adj[r]
        t = max(cand, key=cand.get)  # longest shared boundary
        absorb(r, t)
        fuse_same_color(t)
        heapq.heappush(heap, (int(area[t]), t))

    roots = parent.copy()
    while not np.array_equal(nxt := roots[roots], roots):
        roots = nxt
    final = sorted(alive)
    remap = np.zeros(len(parent), np.int32)
    remap[final] = np.arange(1, len(final) + 1)
    return remap[roots[lab]], cls_of[final]


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

    lab, cls_of = components(cls)
    print(f"  {len(cls_of) - 1} components")
    lab, nr_of = merge_regions(lab, cls_of, s["max_regions"], min_px, cap_px)
    if s["smooth_mm"] > 0:
        lab, cls_of = components(np.concatenate([[0], nr_of])[smooth_regions(lab, s["smooth_mm"] / mm_per_px)])
        lab, nr_of = merge_regions(lab, cls_of, s["max_regions"], min_px, cap_px)
    np.savez_compressed(p.out / "regions.npz", labels=lab, nr=nr_of)
    preview(lab, nr_of, palette, p.out / "regions.png")

    area = np.bincount(lab.ravel())[1:] * mm_per_px**2
    print(f"  {len(nr_of)} regions, area mm²: min {area.min():.0f} / median {np.median(area):.0f} / max {area.max():.0f}")
    for e in palette:
        m = nr_of == e["nr"]
        print(f"  {e['nr']:>2}. {e['code']:<5} {m.sum():4d} regions  {area[m].sum() / area.sum() * 100:5.1f} % area")
    print(f"  -> {p.out / 'regions.npz'}, {p.out / 'regions.png'}")
