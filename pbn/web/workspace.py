"""Everything the web app reads and writes, without HTTP: inventories, uploaded images, projects.

Layout below the root (the repository by default):
  palettes/*.json                    built-in inventories (read only)
  examples/*/*.toml, projects/*/*.toml   projects
  projects/.web/inventories/*.json   uploaded inventories
  projects/.web/images/<id>/         uploaded or opened images: original.*, work.png, meta.json
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .. import inventory, prepare
from ..cluster import cluster
from ..config import DEFAULTS, Project
from ..palette import palette_from_entries, pick_entries, srgb_to_lab
from ..quantize import assign, stats

MAX_SIDE = 1000      # working size for interactive analysis; the pipeline itself uses work_width
THUMB_SIDE = 240
PROJECT_GLOBS = ("examples/*/*.toml", "projects/*/*.toml")
RASTER = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
CARRY_OVER = ("aspect", "work_width", "svg_density", "crop_scan")  # copied into a project made from another


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    if not s:
        raise ValueError("name must contain letters or digits")
    return s[:60]


def title(stem: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_\s]+", stem) if w)


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a, np.uint8).tobytes()).decode("ascii")


def _toml(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # JSON string escapes are valid TOML
    if isinstance(v, list):
        return "[" + ", ".join(_toml(x) for x in v) + "]"
    raise TypeError(type(v))


def _thumbnail(src: Path, dst: Path, side: int) -> None:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        im = im.convert("RGB")
        im.thumbnail((side, side), Image.LANCZOS)
        im.save(dst)


class Workspace:
    def __init__(self, root: str | Path = "."):
        self.root = Path(root).resolve()
        self.data = self.root / "projects" / ".web"
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    # ---- inventories -------------------------------------------------------------------------

    def _inventory_files(self) -> dict[str, tuple[str, Path]]:
        out = {}
        for kind, d in (("built-in", self.root / "palettes"), ("uploaded", self.data / "inventories")):
            for f in sorted(d.glob("*.json")):
                out[self.rel(f)] = (kind, f)
        return out

    def inventories(self) -> list[dict]:
        out = []
        for iid, (kind, f) in self._inventory_files().items():
            try:
                inv = inventory.load(f)
            except (ValueError, OSError):
                continue
            step = max(1, len(inv) // 24)
            out.append(dict(id=iid, name=title(f.stem), kind=kind, count=len(inv),
                            preview=[e["hex"] for e in inv[::step]][:24]))
        return out

    def inventory(self, iid: str) -> list[dict]:
        """Entries plus Lab (for distances in the browser)."""
        files = self._inventory_files()
        if iid not in files:
            raise LookupError(f"unknown inventory {iid!r}")
        inv = inventory.load(files[iid][1])
        for e, lab in zip(inv, srgb_to_lab([e["rgb"] for e in inv])):
            e["lab"] = [round(float(x), 3) for x in lab]
        return inv

    def save_inventory(self, name: str, text: str, filename: str = "") -> dict:
        entries = inventory.parse(text, filename)
        d = self.data / "inventories"
        d.mkdir(parents=True, exist_ok=True)
        base, i = slug(name or Path(filename).stem), 1
        f = d / f"{base}.json"
        while f.exists():
            i += 1
            f = d / f"{base}-{i}.json"
        f.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return dict(id=self.rel(f), count=len(entries))

    # ---- images ------------------------------------------------------------------------------

    def _image_dir(self, iid: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{16}", iid) or not (self.data / "images" / iid / "work.png").exists():
            raise LookupError(f"unknown image {iid!r}")
        return self.data / "images" / iid

    def image_info(self, iid: str) -> dict:
        d = self._image_dir(iid)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        with Image.open(d / "work.png") as im:
            return dict(id=iid, width=im.width, height=im.height, **meta)

    def image_path(self, iid: str) -> Path:
        return self._image_dir(iid) / "work.png"

    def add_image(self, data: bytes, filename: str) -> dict:
        ext = Path(filename).suffix.lower()
        if ext not in RASTER | {".svg"}:
            raise ValueError(f"unsupported file type {ext or '?'} (use PNG, JPEG, WebP, TIFF or SVG)")
        if ext == ".svg" and not shutil.which("magick"):
            raise ValueError("SVG sources need ImageMagick 7 (`magick`) on the server")
        iid = hashlib.sha1(data).hexdigest()[:16]
        d = self.data / "images" / iid
        if not (d / "work.png").exists():
            d.mkdir(parents=True, exist_ok=True)
            src = d / f"original{ext}"
            src.write_bytes(data)
            try:
                if ext == ".svg":
                    prepare.render_svg(src, d / "work.png", MAX_SIDE)
                else:
                    _thumbnail(src, d / "work.png", MAX_SIDE)
            except Exception:
                shutil.rmtree(d, ignore_errors=True)
                raise ValueError(f"cannot read {filename} as an image") from None
            (d / "meta.json").write_text(json.dumps(dict(name=Path(filename).stem, original=src.name)), encoding="utf-8")
        return self.image_info(iid)

    def _img(self, iid: str) -> dict:
        """Cached arrays of a working image (a few at a time)."""
        with self._lock:
            if iid in self._cache:
                self._cache.move_to_end(iid)
                return self._cache[iid]
        rgb = np.asarray(Image.open(self.image_path(iid)).convert("RGB"))
        rec = dict(rgb=rgb, lab=srgb_to_lab(rgb), clusters={})
        with self._lock:
            self._cache[iid] = rec
            while len(self._cache) > 6:
                self._cache.popitem(last=False)
        return rec

    def clusters(self, iid: str, n: int) -> dict:
        if not 2 <= n <= 64:
            raise ValueError("number of image colours must be between 2 and 64")
        rec = self._img(iid)
        if n not in rec["clusters"]:
            rec["clusters"][n] = cluster(rec["rgb"], n)
        c = rec["clusters"][n]
        h, w = c["labels"].shape
        return dict(n=n, width=w, height=h, labels=b64(c["labels"]), clusters=[
            dict(i=i, hex="#%02x%02x%02x" % tuple(c["rgb"][i]), lab=[round(float(x), 3) for x in c["lab"][i]],
                 share=float(c["share"][i])) for i in range(len(c["share"]))])

    def pick(self, iid: str, inventory_id: str, k: int, fixed: list[str], candidates: list[str] | None) -> list[dict]:
        inv = self.inventory(inventory_id)
        if candidates is not None:
            keep = set(candidates) | set(fixed)
            inv = [e for e in inv if e["code"] in keep]
        return pick_entries(self._img(iid)["rgb"].reshape(-1, 3), inv, k, fixed)

    def quantize(self, iid: str, entries: list[dict], q: dict) -> dict:
        """The pipeline's quantize step on the working image: what the plot will really use."""
        unknown = set(q) - set(DEFAULTS["quantize"])
        if unknown:
            raise ValueError(f"unknown quantize settings: {sorted(unknown)}")
        q = DEFAULTS["quantize"] | q
        rec = self._img(iid)
        pal = palette_from_entries(inventory.normalize(entries))
        idx = assign(rec["lab"], pal, q)
        st = {s["code"]: s for s in stats(rec["lab"], idx, pal, 0.0)}
        return dict(labels=b64(idx), palette=[
            dict(nr=e["nr"], code=e["code"], name=e["name"], hex=e["hex"], share_pct=st[e["code"]]["share_pct"],
                 hex_mean=st[e["code"]]["hex_mean"], undrawable=inventory.undrawable(e["code"])) for e in pal])

    # ---- projects ----------------------------------------------------------------------------

    def _project(self, rel: str) -> Project:
        if rel not in {self.rel(f) for g in PROJECT_GLOBS for f in self.root.glob(g)}:
            raise LookupError(f"unknown project {rel!r}")
        return Project(self.root / rel)

    def projects(self) -> list[dict]:
        out = []
        for g in PROJECT_GLOBS:
            for f in sorted(self.root.glob(g)):
                try:
                    p = Project(f)
                except Exception as ex:  # a broken TOML shouldn't hide the others
                    out.append(dict(path=self.rel(f), name=f.stem, error=str(ex)))
                    continue
                prepared = (p.out / "source.png").exists()
                out.append(dict(path=self.rel(f), name=p.name, source=p.source.name,
                                palette=self.rel(p.palette_path), has_palette=p.palette_path.exists(), prepared=prepared,
                                thumb=prepared or (p.source.suffix.lower() in RASTER and p.source.exists())))
        return out

    def project_thumb(self, rel: str) -> Path:
        p = self._project(rel)
        src = p.out / "source.png" if (p.out / "source.png").exists() else p.source
        if src.suffix.lower() not in RASTER or not src.exists():
            raise LookupError("no preview yet")
        key = hashlib.sha1(f"{src}:{src.stat().st_mtime_ns}".encode()).hexdigest()[:16]
        dst = self.data / "thumbs" / f"{key}.png"
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            _thumbnail(src, dst, THUMB_SIDE)
        return dst

    def open_project(self, rel: str) -> dict:
        """Prepare the project's source if needed (same as `run … prepare`) and register it as an image."""
        p = self._project(rel)
        src = p.out / "source.png"
        if not src.exists():
            if p.source.suffix.lower() == ".svg" and not shutil.which("magick"):
                raise ValueError("this project has an SVG source: run `prepare` once where ImageMagick is installed")
            prepare.run(p)
        iid = hashlib.sha1(f"{rel}:{src.stat().st_mtime_ns}".encode()).hexdigest()[:16]
        d = self.data / "images" / iid
        if not (d / "work.png").exists():
            d.mkdir(parents=True, exist_ok=True)
            _thumbnail(src, d / "work.png", MAX_SIDE)
            (d / "meta.json").write_text(json.dumps(dict(name=p.name, project=rel)), encoding="utf-8")
        palette = inventory.load(p.palette_path) if p.palette_path.exists() else []
        for e in palette:
            e["lab"] = [round(float(x), 3) for x in srgb_to_lab(e["rgb"])]
        return dict(image=self.image_info(iid), project=dict(
            path=rel, name=p.name, palette_file=self.rel(p.palette_path), palette=palette, quantize=p.q))

    def save_palette(self, rel: str, entries: list[dict]) -> dict:
        """Update an existing project's palette file."""
        p = self._project(rel)
        entries = inventory.normalize(entries)
        p.palette_path.parent.mkdir(parents=True, exist_ok=True)
        p.palette_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return dict(path=rel, palette_file=self.rel(p.palette_path))

    def create_project(self, name: str, iid: str, entries: list[dict], q: dict) -> dict:
        """projects/<name>/ with the source, palette.json and <name>.toml (settings of the origin
        project are carried over when the image came from one)."""
        entries = inventory.normalize(entries)
        meta = self.image_info(iid)
        name = slug(name)
        d = self.root / "projects" / name
        if d.exists():
            raise FileExistsError(f"projects/{name} already exists")
        cfg, tables = {}, {"quantize": {}}
        if meta.get("project"):
            origin = self._project(meta["project"])
            src = origin.source
            cfg = {k: origin.cfg[k] for k in CARRY_OVER if origin.cfg[k] != DEFAULTS[k]}
            tables = {t: {k: v for k, v in origin.cfg[t].items() if v != DEFAULTS[t][k]}
                      for t in ("quantize", "segment", "layout", "plotter")}
        else:
            src = self._image_dir(iid) / meta["original"]
        tables["quantize"] |= {k: v for k, v in q.items() if k in DEFAULTS["quantize"] and v != DEFAULTS["quantize"][k]}

        d.mkdir(parents=True)
        shutil.copy2(src, d / f"source{src.suffix.lower()}")
        (d / "palette.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        lines = [f"# created with `python -m pbn web` from {meta.get('project') or meta['name']}",
                 f'source = "source{src.suffix.lower()}"', 'palette = "palette.json"']
        lines += [f"{k} = {_toml(v)}" for k, v in cfg.items()]
        for t, vals in tables.items():
            if vals:
                lines += ["", f"[{t}]"] + [f"{k} = {_toml(v)}" for k, v in vals.items()]
        toml = d / f"{name}.toml"
        toml.write_text("\n".join(lines) + "\n", encoding="utf-8")
        Project(toml)  # validates what we just wrote
        return dict(path=self.rel(toml))
