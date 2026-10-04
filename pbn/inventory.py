"""Colour inventories: validation and parsing of uploads (JSON, CSV, GIMP .gpl).

Every inventory is normalised to [{code, name, hex, rgb[, group]}], the format of palettes/*.json.
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

from .font import GLYPHS

_HEX = re.compile(r"#?([0-9a-fA-F]{6})")


def normalize(raw) -> list[dict]:
    """Validate inventory entries; raises ValueError with a readable message."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("expected a non-empty list of colours")
    out, seen = [], set()
    for i, c in enumerate(raw, 1):
        if not isinstance(c, dict):
            raise ValueError(f"entry {i}: expected an object")
        code = str(c.get("code", "")).strip()
        if not code:
            raise ValueError(f"entry {i}: missing code")
        if code in seen:
            raise ValueError(f"duplicate code {code!r}")
        seen.add(code)
        if c.get("hex"):
            m = _HEX.fullmatch(str(c["hex"]).strip())
            if not m:
                raise ValueError(f"{code}: bad hex value {c['hex']!r}")
            rgb = [int(m[1][j:j + 2], 16) for j in (0, 2, 4)]
        elif isinstance(c.get("rgb"), (list, tuple)) and len(c["rgb"]) == 3:
            rgb = [int(v) for v in c["rgb"]]
            if not all(0 <= v <= 255 for v in rgb):
                raise ValueError(f"{code}: rgb out of range")
        else:
            raise ValueError(f"{code}: needs hex or rgb")
        e = dict(code=code, name=str(c.get("name") or code).strip(), hex="#%02x%02x%02x" % tuple(rgb), rgb=rgb)
        if c.get("group"):
            e["group"] = str(c["group"])
        out.append(e)
    return out


def _gpl(text: str) -> list[dict]:
    """GIMP palette: 'R G B name' per line. Codes become 1..n, so the plotter font can draw them."""
    rows = []
    for line in text.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("#") or ":" in line.split()[0]:
            continue
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        rows.append(dict(rgb=[int(v) for v in parts[:3]], name=parts[3] if len(parts) > 3 else ""))
    return [dict(code=str(i), name=r["name"] or str(i), rgb=r["rgb"]) for i, r in enumerate(rows, 1)]


def _csv(text: str) -> list[dict]:
    """CSV/TSV with a header (code, name, hex) or without (columns in that order)."""
    first = text.lstrip().split("\n", 1)[0]
    delim = "\t" if "\t" in first else ";" if ";" in first else ","
    rows = [r for r in csv.reader(io.StringIO(text.strip()), delimiter=delim) if any(x.strip() for x in r)]
    head = [x.strip().lower() for x in rows[0]] if rows else []
    if "hex" in head or "code" in head:
        return [{k: v.strip() for k, v in zip(head, r)} for r in rows[1:]]
    return [dict(code=r[0].strip(), name=r[1].strip() if len(r) > 2 else "", hex=r[-1].strip()) for r in rows]


def parse(text: str, filename: str = "") -> list[dict]:
    ext = Path(filename).suffix.lower()
    if ext == ".gpl" or text.startswith("GIMP Palette"):
        return normalize(_gpl(text))
    if ext in (".csv", ".tsv", ".txt"):
        return normalize(_csv(text))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as ex:
        raise ValueError(f"not valid JSON: {ex}") from None
    return normalize(data)


def load(path: Path) -> list[dict]:
    path = Path(path)
    return parse(path.read_text(encoding="utf-8"), path.name)


def undrawable(code: str) -> str:
    """Characters of a code the plotter font has no glyph for ('' = fine)."""
    return "".join(sorted(set(code) - set(GLYPHS)))


if __name__ == "__main__":
    assert parse("code,name,hex\nY15,Cadmium Yellow,#FFE55B\n", "x.csv")[0]["rgb"] == [255, 229, 91]
    assert parse("GIMP Palette\nName: t\n#\n255 0 0\tRed\n", "t.gpl")[0] == dict(code="1", name="Red", hex="#ff0000", rgb=[255, 0, 0])
    assert parse('[{"code": "B18", "rgb": [31, 116, 182]}]')[0]["hex"] == "#1f74b6"
    assert undrawable("YR16") == "" and undrawable("Ab") == "Ab"
    print("ok")
