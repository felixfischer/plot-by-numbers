"""Step 4 – region boundaries -> smooth polylines, plus one number position per region.

- boundaries on the pixel-corner grid: each edge between two regions exactly once
  (shared borders are drawn once). The picture edge is the frame (layout step).
- trace chains between junctions (degree ≠ 2) and closed loops
- smoothing: Douglas–Peucker (1 px) -> 3× Chaikin -> Douglas–Peucker (0.3 px); chain ends
  stay fixed so boundaries meet exactly at junctions
- number at the maximum of the distance transform; if it does not fit the inscribed
  circle at digit_height_mm it is listed as omitted (add it by hand)
Output: out/vectors.json (px), out/regions.svg
"""
from __future__ import annotations

import json

import numpy as np
from scipy import ndimage

from .font import text_width

CLEARANCE_MM = 0.3


def edge_graph(lab: np.ndarray) -> dict[tuple[int, int], list[tuple[int, int]]]:
    """Corner (x, y) -> neighbouring corners along region boundaries."""
    g: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def add(a, b):
        g.setdefault(a, []).append(b)
        g.setdefault(b, []).append(a)

    for y, x in zip(*np.nonzero(lab[:, 1:] != lab[:, :-1])):  # vertical edges
        add((x + 1, y), (x + 1, y + 1))
    for y, x in zip(*np.nonzero(lab[1:, :] != lab[:-1, :])):  # horizontal edges
        add((x, y + 1), (x + 1, y + 1))
    return g


def trace(g) -> list[tuple[list, bool]]:
    """-> [(points, closed)]"""
    seen: set[frozenset] = set()
    chains = []

    def walk(a, b):
        pts = [a, b]
        seen.add(frozenset((a, b)))
        while len(g[b]) == 2:
            free = [n for n in g[b] if frozenset((b, n)) not in seen]
            if not free:
                break  # loop closed
            nxt = free[0]
            seen.add(frozenset((b, nxt)))
            pts.append(nxt)
            b = nxt
        return pts

    for a in [n for n in g if len(g[n]) != 2]:
        for b in g[a]:
            if frozenset((a, b)) not in seen:
                chains.append((walk(a, b), False))
    for a in g:  # remaining: loops without junctions
        for b in g[a]:
            if frozenset((a, b)) not in seen:
                chains.append((walk(a, b), True))
    return chains


def dp(pts: np.ndarray, eps: float) -> np.ndarray:
    """Douglas–Peucker, iterative; end points stay."""
    keep = np.zeros(len(pts), bool)
    keep[[0, -1]] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        seg = pts[i + 1:j] - a
        d = b - a
        n = np.hypot(*d)
        dist = np.abs(seg[:, 0] * d[1] - seg[:, 1] * d[0]) / n if n > 0 else np.hypot(seg[:, 0], seg[:, 1])
        k = int(dist.argmax())
        if dist[k] > eps:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return pts[keep]


def chaikin(pts: np.ndarray, closed: bool, iters: int = 3) -> np.ndarray:
    for _ in range(iters):
        p = pts[:-1] if closed else pts
        q = np.roll(p, -1, axis=0) if closed else p[1:]
        p = p if closed else p[:-1]
        mid = np.empty((2 * len(p), 2))
        mid[0::2] = 0.75 * p + 0.25 * q
        mid[1::2] = 0.25 * p + 0.75 * q
        pts = np.vstack([mid, mid[:1]]) if closed else np.vstack([pts[:1], mid, pts[-1:]])
    return pts


def digits(lab: np.ndarray, nr_of: np.ndarray, mm_per_px: float, h: float):
    placed, omitted = [], []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        m = np.pad(lab[sl] == i, 1)  # crop border = boundary
        d = ndimage.distance_transform_edt(m)
        y, x = np.unravel_index(d.argmax(), d.shape)
        r_mm = d[y, x] * mm_per_px
        s = str(nr_of[i - 1])
        pos = dict(region=i, nr=int(nr_of[i - 1]), x=float(sl[1].start + x - 1 + 0.5), y=float(sl[0].start + y - 1 + 0.5),
                   area_mm2=round(float((lab[sl] == i).sum() * mm_per_px**2), 1))
        if np.hypot(text_width(s, h) / 2, h / 2) + CLEARANCE_MM <= r_mm:
            placed.append(pos | dict(h_mm=h))
        else:
            omitted.append(pos | dict(r_mm=round(float(r_mm), 2)))
    return placed, omitted


def run(p) -> None:
    z = np.load(p.out / "regions.npz")
    lab, nr_of = z["labels"], z["nr"]
    H, W = lab.shape
    mm_per_px = p.geometry(W, H)["mm_per_px"]

    lines = []
    for pts, closed in trace(edge_graph(lab)):
        pl = dp(chaikin(dp(np.array(pts, float), 1.0), closed), 0.3)
        lines.append(np.round(pl, 2).tolist())
    placed, omitted = digits(lab, nr_of, mm_per_px, p.lay["digit_height_mm"])
    (p.out / "vectors.json").write_text(json.dumps(dict(size=[W, H], lines=lines, digits=placed, omitted=omitted)))

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
           f'<rect width="{W}" height="{H}" fill="white" stroke="black"/>']
    svg += [f'<polyline fill="none" stroke="black" points="{" ".join(f"{x},{y}" for x, y in l)}"/>' for l in lines]
    svg += [f'<text x="{d["x"]}" y="{d["y"]}" font-size="{d["h_mm"] / mm_per_px * 1.3:.0f}" text-anchor="middle" '
            f'dominant-baseline="central" font-family="sans-serif">{d["nr"]}</text>' for d in placed]
    svg += [f'<circle cx="{d["x"]}" cy="{d["y"]}" r="8" fill="red"/>' for d in omitted]
    (p.out / "regions.svg").write_text("\n".join(svg + ["</svg>"]))

    print(f"  {len(lines)} boundary lines, {sum(map(len, lines))} points, {len(placed)} numbers, {len(omitted)} omitted")
    for d in omitted:
        print(f"  omitted: region {d['region']} (nr {d['nr']}, {d['area_mm2']} mm², inscribed r {d['r_mm']} mm) – add by hand")
    print(f"  -> {p.out / 'vectors.json'}, {p.out / 'regions.svg'}")
