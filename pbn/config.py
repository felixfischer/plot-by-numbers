"""Project config: one TOML file per picture, defaults below, paths relative to the TOML."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

DEFAULTS = {
    "source": None,        # .svg (rendered with ImageMagick) or any raster image
    "palette": None,       # selection JSON: list of inventory entries (code, name, hex, rgb)
    "out": "out",
    "name": None,          # base name of the .hpgl file, default: TOML file name
    "aspect": None,        # target width/height, e.g. the painting's real size; default: source aspect
    "work_width": 2000,    # processing width in px
    "svg_density": None,   # ImageMagick -density for SVG sources; default: just enough for work_width
    "crop_scan": False,    # photo of a canvas on a light background: deskew + cut the border
    "quantize": {
        "chroma_weight": 1.4,  # distance = dL² + w·(da² + db²)
        "dark_boost": 1.0,     # >1 spreads near-black, near-neutral pixels apart (dark photos)
        "dark_l": 35.0, "dark_span": 15.0, "dark_c": 28.0,
        "dark_only": [],       # palette codes only allowed where L* < dark_l
    },
    "segment": {
        "min_area_mm2": 45.0,   # smaller regions are merged into a neighbour
        "max_regions": 280,
        "smooth_mm": 1.0,       # Gaussian sigma for boundary smoothing, 0 = off
        "max_area_mm2": 2500.0, # regions above this only swallow isolated specks
    },
    "layout": {
        "margin_mm": 4.0,
        "legend_width_mm": 24.0,
        "gap_mm": 6.0,
        "digit_height_mm": 2.0,  # smallest size your pen still draws legibly (see `calib`)
        "box_mm": 12.0,          # legend swatch size
    },
    "plotter": {
        # Drawable area = the plotter's hard-clip limits (HPGL `OH;`), origin bottom left.
        # Default: Roland DXY-1200 with A3 landscape, 0,0–16158,11040 PU.
        "width_mm": 403.95, "height_mm": 276.0,
        "pu_per_mm": 40.0,
        "scale_x": 1.0, "scale_y": 1.0,        # calibration: measured 100 mm / 100
        "offset_x_mm": 0.0, "offset_y_mm": 0.0,
        "speed_cm_s": 15,                      # VS; slow is kinder to pencils
        "pd_chunk": 32,                        # points per PD command (small buffers on old plotters)
    },
}


class Project:
    def __init__(self, toml_path: str | Path):
        self.path = Path(toml_path).resolve()
        self.dir = self.path.parent
        raw = tomllib.loads(self.path.read_text(encoding="utf-8"))
        cfg = {k: (v | raw.get(k, {}) if isinstance(v, dict) else raw.get(k, v)) for k, v in DEFAULTS.items()}
        unknown = set(raw) - set(DEFAULTS)
        unknown |= {f"{k}.{s}" for k, v in raw.items() if isinstance(DEFAULTS.get(k), dict) for s in set(v) - set(DEFAULTS[k])}
        assert not unknown, f"unknown keys in {self.path.name}: {sorted(unknown)}"
        self.cfg = cfg
        self.q, self.seg, self.lay, self.plot = cfg["quantize"], cfg["segment"], cfg["layout"], cfg["plotter"]
        self.source = self.dir / cfg["source"]
        self.palette_path = self.dir / cfg["palette"]
        self.out = self.dir / cfg["out"]
        self.name = cfg["name"] or self.path.stem
        self.plot_w, self.plot_h = self.plot["width_mm"], self.plot["height_mm"]

    def geometry(self, w_px: int, h_px: int) -> dict:
        """Picture size on paper: as large as fits next to the legend, centred as one block."""
        L = self.lay
        area_w = self.plot_w - 2 * L["margin_mm"] - L["legend_width_mm"] - L["gap_mm"]
        area_h = self.plot_h - 2 * L["margin_mm"]
        img_w = min(area_w, area_h * w_px / h_px)
        img_h = img_w * h_px / w_px
        return dict(
            img_w=img_w, img_h=img_h, mm_per_px=img_w / w_px,
            x0=(self.plot_w - img_w - L["gap_mm"] - L["legend_width_mm"]) / 2,
            y0=(self.plot_h - img_h) / 2,
        )

    def work_size(self) -> tuple[int, int]:
        """(W, H) of the prepared source image."""
        from PIL import Image
        with Image.open(self.out / "source.png") as im:
            return im.size


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  -> {path}")
