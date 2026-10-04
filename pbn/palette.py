"""Colour math (sRGB <-> CIELAB, D65), palette loading and palette picking from an inventory."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_WHITE = np.array([0.95047, 1.0, 1.08883])
_E = 6.0 / 29.0


def srgb_to_lab(rgb) -> np.ndarray:
    """sRGB 0..255 (any shape ...×3) -> Lab float64."""
    v = np.asarray(rgb, dtype=np.float64) / 255.0
    v = np.where(v > 0.04045, ((v + 0.055) / 1.055) ** 2.4, v / 12.92)
    t = (v @ _M.T) / _WHITE
    f = np.where(t > _E**3, np.cbrt(t), t / (3 * _E**2) + 4.0 / 29.0)
    return np.stack([116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]), 200.0 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_srgb(lab) -> np.ndarray:
    """Lab -> sRGB uint8 (clipped)."""
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16.0) / 116.0
    f = np.stack([fy + lab[..., 1] / 500.0, fy, fy - lab[..., 2] / 200.0], axis=-1)
    xyz = np.where(f > _E, f**3, (f - 4.0 / 29.0) * 3 * _E**2) * _WHITE
    v = xyz @ np.linalg.inv(_M).T
    v = np.where(v > 0.0031308, 1.055 * np.abs(v) ** (1.0 / 2.4) - 0.055, 12.92 * v)
    return np.clip(np.round(v * 255.0), 0, 255).astype(np.uint8)


def hex_rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def load_palette(path: Path) -> list[dict]:
    """Selection JSON -> entries with lab, L and nr = painting order by lightness
    (1 = lightest). Paper white is appended as nr 0 (left blank)."""
    pal = [dict(code=c["code"], name=c["name"], hex=c["hex"].lower()) for c in json.loads(Path(path).read_text(encoding="utf-8"))]
    for e in pal:
        e["lab"] = srgb_to_lab(hex_rgb(e["hex"]))
        e["L"] = float(e["lab"][0])
    for nr, i in enumerate(np.argsort([-e["L"] for e in pal], kind="stable"), start=1):
        pal[i]["nr"] = nr
    white = srgb_to_lab((255, 255, 255))
    pal.append(dict(code="", name="paper white (leave blank)", hex="#ffffff", lab=white, L=float(white[0]), nr=0))
    return pal


def _pick(src_lab, w, cand_lab, k, fixed=(), iters=50) -> list[int]:
    """Weighted k-medoids (greedy init + PAM swaps) choosing k of the candidates."""
    d = np.linalg.norm(src_lab[:, None] - cand_lab[None], axis=-1)  # src × cand
    chosen = list(fixed)
    for _ in range(k - len(chosen)):
        chosen.append(min((i for i in range(len(cand_lab)) if i not in chosen),
                          key=lambda i: (w * d[:, chosen + [i]].min(1)).sum()))
    for _ in range(iters):
        cost, improved = (w * d[:, chosen].min(1)).sum(), False
        for j in range(len(fixed), k):
            for i in range(len(cand_lab)):
                if i in chosen:
                    continue
                trial = chosen[:j] + [i] + chosen[j + 1:]
                c = (w * d[:, trial].min(1)).sum()
                if c < cost - 1e-9:
                    chosen, cost, improved = trial, c, True
        if not improved:
            break
    return chosen


def pick(image: Path, inventory: Path, k: int, fixed_codes=(), out: Path | None = None) -> list[dict]:
    """Choose the k inventory colours that best cover the image (weights = sqrt of pixel count,
    so small accents like stars survive). fixed_codes are always included."""
    px = np.asarray(Image.open(image).convert("RGB")).reshape(-1, 3)
    hist = Counter(map(tuple, px))
    if len(hist) > 4096:  # photo: bin to 4 bits per channel
        hist = Counter(map(tuple, (px // 16) * 16 + 8))
    colors = np.array(list(hist))
    w = np.sqrt(np.array(list(hist.values()), dtype=float) + 1)
    inv = json.loads(Path(inventory).read_text(encoding="utf-8"))
    codes = [c["code"] for c in inv]
    missing = [c for c in fixed_codes if c not in codes]
    assert not missing, f"not in {inventory.name}: {missing}"
    chosen = _pick(srgb_to_lab(colors), w, srgb_to_lab([c["rgb"] for c in inv]), k, [codes.index(c) for c in fixed_codes])
    sel = [inv[i] for i in chosen]
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(sel, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  -> {out}")
    return sel


if __name__ == "__main__":
    rgb = np.array([[0, 0, 0], [255, 255, 255], [31, 116, 182], [255, 229, 91]])
    assert (lab_to_srgb(srgb_to_lab(rgb)) == rgb).all()
    assert abs(srgb_to_lab((255, 255, 255))[0] - 100) < 1e-3
    print("ok")
