"""Step 4 – region boundaries -> smooth polylines, plus one number position per region.

- boundaries on the pixel-corner grid: each edge between two regions exactly once
  (shared borders are drawn once). The picture edge is the frame (layout step).
- trace chains between junctions (degree ≠ 2) and closed loops
- smoothing: one smoothing spline over the whole boundary network – minimise
  Σ |p − pixel boundary|² + λ Σ |second difference|², a sparse linear system. Wiggles shorter
  than curve_mm are removed, longer shapes stay. Junctions are shared points and move with
  their chains (no kinks); chain ends on the picture edge only slide along it.
- Douglas–Peucker (0.3 px) to drop redundant points
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
JOIN_MM = 0.6  # junctions closer than this (along their chain) become one crossing


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


def join_close_junctions(chains: list[tuple[list, bool]], size: tuple[int, int], min_px: float):
    """Chains shorter than min_px between two inner junctions are dropped and their ends joined,
    so four regions that almost meet in a point get one clean crossing instead of a tiny bridge.
    -> remaining chains, junction point -> representative point"""
    W, H = size
    parent: dict[tuple, tuple] = {}

    def find(p):
        while parent.get(p, p) != p:
            p = parent[p]
        return p

    inner = lambda p: 0 < p[0] < W and 0 < p[1] < H
    keep = []
    for pts, closed in chains:
        a, b = pts[0], pts[-1]
        if not closed and len(pts) - 1 < min_px and a != b and inner(a) and inner(b):
            parent[find(a)] = find(b)
        else:
            keep.append((pts, closed))
    return keep, {p: find(p) for p in parent} | {find(p): find(p) for p in parent}


def smooth_network(chains: list[tuple[list, bool]], size: tuple[int, int], wavelength_px: float,
                   join: dict | None = None) -> list[np.ndarray]:
    """Smoothing spline over all chains at once. Points are on a 1 px grid, so λ follows from
    the cut-off wavelength L: the filter response 1 / (1 + λ (ωh)⁴) is ½ at ω = 2π / L.
    join: junction point -> representative (joined junctions share one variable)."""
    from scipy import sparse
    from scipy.sparse.linalg import factorized

    W, H = size
    join = join or {}
    lam = (wavelength_px / (2 * np.pi)) ** 4
    var: dict[tuple, int] = {}  # junction / chain-end point -> variable, shared between chains
    idx, rows = [], []          # per chain: variable indices; second-difference triples
    n = 0
    for pts, closed in chains:
        if closed:
            ii = list(range(n, n + len(pts) - 1))
            n += len(ii)
            rows += [(ii[k - 1], ii[k], ii[(k + 1) % len(ii)]) for k in range(len(ii))]
            ii.append(ii[0])
        else:
            ii = []
            for k, p in enumerate(pts):
                if k in (0, len(pts) - 1):
                    p = join.get(p, p)
                    if p not in var:
                        var[p], n = n, n + 1
                    ii.append(var[p])
                else:
                    ii.append(n)
                    n += 1
            rows += [(ii[k - 1], ii[k], ii[k + 1]) for k in range(1, len(ii) - 1)]
        idx.append(ii)
    orig, cnt = np.zeros((n, 2)), np.zeros(n)
    for (pts, _), ii in zip(chains, idx):
        np.add.at(orig, ii, pts)  # a joined junction is fitted to the mean of its points
        np.add.at(cnt, ii, 1)
    orig /= cnt[:, None]

    r = np.repeat(np.arange(len(rows)), 3)
    D = sparse.csr_matrix((np.tile([1.0, -2.0, 1.0], len(rows)), (r, np.ravel(rows))), shape=(len(rows), n))
    out = np.empty_like(orig)
    for c, edge in ((0, W), (1, H)):
        fixed = (orig[:, c] == 0) | (orig[:, c] == edge)  # on the picture edge: keep this coordinate
        w = np.where(fixed, 1e8, 1.0)
        solve = factorized((sparse.diags(w) + lam * (D.T @ D)).tocsc())
        out[:, c] = solve(w * orig[:, c])
    return [out[ii] for ii in idx]


def number_radius_mm(nr: int, h: float) -> float:
    """Smallest inscribed-circle radius that fits the number at digit height h."""
    return float(np.hypot(text_width(str(nr), h) / 2, h / 2) + CLEARANCE_MM)


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
        if number_radius_mm(int(s), h) <= r_mm:
            placed.append(pos | dict(h_mm=h))
        else:
            omitted.append(pos | dict(r_mm=round(float(r_mm), 2)))
    return placed, omitted


def run(p) -> None:
    z = np.load(p.out / "regions.npz")
    lab, nr_of = z["labels"], z["nr"]
    H, W = lab.shape
    mm_per_px = p.geometry(W, H)["mm_per_px"]

    chains, join = join_close_junctions(trace(edge_graph(lab)), (W, H), JOIN_MM / mm_per_px)
    smooth = smooth_network(chains, (W, H), p.cfg["vectorize"]["curve_mm"] / mm_per_px, join)
    lines = [np.round(dp(pl, 0.3), 2).tolist() for pl in smooth]
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
