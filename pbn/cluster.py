"""Image colours: weighted k-means in CIELAB, the colours a user maps onto an inventory.

Pixels are first binned to 5 bits per channel (exact Lab means per bin), so k-means runs on a
few thousand points instead of every pixel. Bins are weighted by sqrt(pixel count) while
clustering, so small accents (stars, highlights) keep a cluster of their own; the reported
centres and shares use the real pixel counts.
"""
from __future__ import annotations

import numpy as np

from .palette import lab_to_srgb, srgb_to_lab


def _kmeans(pts: np.ndarray, w: np.ndarray, n: int, seed: int, iters: int) -> np.ndarray:
    """Weighted k-means++ / Lloyd; returns the cluster index per point."""
    rng = np.random.default_rng(seed)
    centres = [pts[np.argmax(w)]]
    d2 = ((pts - centres[0]) ** 2).sum(1)
    for _ in range(n - 1):
        p = w * d2
        if p.sum() <= 0:
            break
        centres.append(pts[rng.choice(len(pts), p=p / p.sum())])
        d2 = np.minimum(d2, ((pts - centres[-1]) ** 2).sum(1))
    c = np.array(centres)
    idx = None
    for _ in range(iters):
        new = ((pts[:, None] - c[None]) ** 2).sum(-1).argmin(1)
        if idx is not None and (new == idx).all():
            break
        idx = new
        ws = np.bincount(idx, w, len(c))
        keep = ws > 0
        c = np.stack([np.bincount(idx, w * pts[:, j], len(c)) for j in range(3)], 1)[keep] / ws[keep, None]
    return ((pts[:, None] - c[None]) ** 2).sum(-1).argmin(1)


def cluster(img_rgb: np.ndarray, n: int, seed: int = 0, iters: int = 40) -> dict:
    """img_rgb H×W×3 uint8 -> dict(labels H×W uint8, lab n×3, rgb n×3, share n), sorted by share."""
    assert 1 <= n <= 255
    h, w = img_rgb.shape[:2]
    px = img_rgb.reshape(-1, 3)
    lab = srgb_to_lab(px)
    q = (px >> 3).astype(np.int32)
    _, inv, cnt = np.unique((q[:, 0] << 10) | (q[:, 1] << 5) | q[:, 2], return_inverse=True, return_counts=True)
    inv = inv.ravel()
    pts = np.stack([np.bincount(inv, lab[:, j], len(cnt)) for j in range(3)], 1) / cnt[:, None]

    bin_label = np.arange(len(cnt)) if len(cnt) <= n else _kmeans(pts, np.sqrt(cnt), n, seed, iters)
    k = int(bin_label.max()) + 1
    counts = np.bincount(bin_label, cnt, k)
    centres = np.stack([np.bincount(bin_label, cnt * pts[:, j], k) for j in range(3)], 1)
    used = counts > 0
    order = np.argsort(-counts[used], kind="stable")
    remap = np.full(k, -1)
    remap[np.flatnonzero(used)[order]] = np.arange(used.sum())
    centres = (centres[used] / counts[used, None])[order]
    return dict(labels=remap[bin_label][inv].reshape(h, w).astype(np.uint8),
                lab=centres, rgb=lab_to_srgb(centres), share=counts[used][order] / (h * w))


if __name__ == "__main__":
    img = np.zeros((20, 30, 3), np.uint8)
    img[:, :10] = (255, 229, 91)
    img[:, 10:] = (31, 116, 182)
    img[0, 0] = (255, 0, 0)
    r = cluster(img, 3)
    assert r["labels"].max() == 2 and abs(r["share"][0] - 400 / 600) < 1e-9
    assert (r["rgb"][0] == (31, 116, 182)).all() and r["labels"][0, 0] == 2
    print("ok")
