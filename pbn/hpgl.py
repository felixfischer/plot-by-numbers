"""Step 6 – HPGL output, static check, calibration sheet, serial sender.

- HPGL/1, minimal command set: IN; SP1; VS; PU x,y; PD x,y,…; SP0;
  absolute plotter units (default 40 PU/mm), one pen for everything.
- order: contours -> numbers -> legend -> frame, nearest-neighbour within each group
  (lines may be reversed); consecutive lines that touch keep the pen down.
Output: out/<name>.hpgl, out/report.md; `calib` writes out/calib-test.hpgl
"""
from __future__ import annotations

import json
import math
import re
import sys
import time

from . import font
from .palette import load_palette

PEN_UP_MM_S, LIFT_S = 400.0, 0.15  # only for the time estimate


def pu(p, x: float, y: float) -> tuple[int, int]:
    c = p.plot
    return (round((x * c["scale_x"] + c["offset_x_mm"]) * c["pu_per_mm"]),
            round((y * c["scale_y"] + c["offset_y_mm"]) * c["pu_per_mm"]))


def order(lines: list, start=(0.0, 0.0)) -> tuple[list, tuple]:
    """Greedy nearest neighbour; a line may be reversed."""
    # ponytail: O(n²), < 1 s for ~500 lines; use a k-d tree from tens of thousands on
    rest, out, pos = list(lines), [], start
    while rest:
        i, rev = min(((i, r) for i in range(len(rest)) for r in (False, True)),
                     key=lambda t: math.dist(pos, rest[t[0]][-1 if t[1] else 0]))
        l = rest.pop(i)
        l = l[::-1] if rev else l
        out.append(l)
        pos = l[-1]
    return out, pos


def hpgl(p, lines: list) -> str:
    cmds, cur, n = ["IN;", "SP1;", f"VS{p.plot['speed_cm_s']};"], None, p.plot["pd_chunk"]
    for l in lines:
        pts = [pu(p, *xy) for xy in l]
        if pts[0] != cur:
            cmds.append("PU%d,%d;" % pts[0])
        cur = pts[-1]
        for k in range(1, len(pts), n):
            cmds.append("PD" + ",".join(f"{x},{y}" for x, y in pts[k:k + n]) + ";")
    return "\n".join(cmds + ["PU;", "SP0;"]) + "\n"


def check(p, code: str) -> None:
    """Syntax + every coordinate inside the drawable area."""
    xmax, ymax = pu(p, p.plot_w, p.plot_h)
    for c in filter(None, (c.strip() for c in code.split(";"))):
        assert re.fullmatch(r"(IN|SP\d|VS\d+|PU|P[UD]-?\d+,-?\d+(,-?\d+,-?\d+)*)", c), c
        nums = list(map(int, re.findall(r"-?\d+", c[2:]))) if c[:2] in ("PU", "PD") else []
        for x, y in zip(nums[::2], nums[1::2]):
            assert 0 <= x <= xmax and 0 <= y <= ymax, f"outside the drawable area: {c[:40]}"


def stats(lines: list) -> tuple[float, float]:
    draw = sum(math.dist(a, b) for l in lines for a, b in zip(l, l[1:]))
    travel = sum(math.dist(a[-1], b[0]) for a, b in zip(lines, lines[1:]))
    return draw, travel


def run(p) -> None:
    g = json.loads((p.out / "layout.json").read_text())["groups"]
    plot, pos, rows = [], (0.0, 0.0), []
    for name in ("contours", "digits", "legend", "frame"):
        ls, pos = order([[tuple(pt) for pt in l] for l in g[name]], pos)
        plot += ls
        rows.append((name, len(ls), sum(map(len, ls)), stats(ls)[0]))

    path = p.out / f"{p.name}.hpgl"
    code = hpgl(p, plot)
    check(p, code)
    path.write_text(code)

    draw, travel = stats(plot)
    vs = p.plot["speed_cm_s"]
    minutes = (draw / (vs * 10) + travel / PEN_UP_MM_S + 2 * len(plot) * LIFT_S) / 60
    pal = sorted((e for e in load_palette(p.palette_path) if e["nr"] > 0), key=lambda e: e["nr"])
    md = [f"# Plot report: {p.name}", "",
          f"Source: `{p.source.name}` · drawable area {p.plot_w:.1f} × {p.plot_h:.1f} mm · 1 pen (SP1)", "",
          "| Group | Lines | Points | Stroke length |", "|---|---:|---:|---:|"]
    md += [f"| {n} | {c} | {pts} | {d / 1000:.1f} m |" for n, c, pts, d in rows]
    md += ["", f"- Total: {len(plot)} lines, {sum(map(len, plot))} points, drawing {draw / 1000:.1f} m, travel {travel / 1000:.1f} m",
           f"- Estimated plot time at VS{vs} ({vs * 10} mm/s): **~{minutes:.0f} min**",
           f"- File: `{path.name}` ({path.stat().st_size / 1024:.0f} KB); plot `calib-test.hpgl` first",
           "", f"## Colours (paint light → dark, leave paper white blank)", "",
           "| Nr | Code | Name | Hex |", "|---:|---|---|---|"]
    md += [f"| {e['nr']} | {e['code']} | {e['name']} | {e['hex']} |" for e in pal]
    (p.out / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join("  " + l for l in md[4:12]))
    print(f"  -> {path}, {p.out / 'report.md'} (static check OK)")


def calib(p) -> None:
    """Squares 50/100 mm at (20,20), diagonal, mm ruler 0–100, corner marks 8 mm from the
    drawable-area corners, digit samples 1.0/1.2/1.5/2.0 mm -> choose digit_height_mm."""
    pw, ph = p.plot_w, p.plot_h
    sq = lambda x, y, s: [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]
    lines = [sq(20, 20, 100), sq(20, 20, 50), [(20, 20), (120, 120)], [(20, 140), (120, 140)]]
    lines += [[(20 + i, 140), (20 + i, 140 + (5 if i % 10 == 0 else 3 if i % 5 == 0 else 1.5))] for i in range(101)]
    lines += [[(pw - 13, 8), (pw - 8, 8), (pw - 8, 13)], [(8, ph - 13), (8, ph - 8), (13, ph - 8)],
              [(pw - 13, ph - 8), (pw - 8, ph - 8), (pw - 8, ph - 13)], [(13, 8), (8, 8), (8, 13)]]
    for i, h in enumerate((1.0, 1.2, 1.5, 2.0)):
        lines += font.text("0123456789", 170, 30 + i * 8, h)
    code = hpgl(p, lines)
    check(p, code)
    p.out.mkdir(parents=True, exist_ok=True)
    (p.out / "calib-test.hpgl").write_text(code)
    print(f"  -> {p.out / 'calib-test.hpgl'}")


def chunks(code: str, size: int = 256) -> list[str]:
    """Split at command boundaries into blocks of at most ~size bytes."""
    out, cur = [], ""
    for cmd in code.replace("\n", "").replace("\r", "").split(";"):
        if not cmd:
            continue
        if cur and len(cur) + len(cmd) + 1 > size:
            out.append(cur)
            cur = ""
        cur += cmd + ";"
    return out + [cur] if cur else out


def send(path: str, port: str, baud: int = 9600) -> None:
    """Serial 8N1 without hardware handshake: after every block send `OS;` and wait for the
    answer, so the plotter buffer never holds more than one block."""
    import serial  # pyserial, only needed here

    blocks = chunks(open(path).read())
    with serial.Serial(port, baud, timeout=120) as s:  # OS; only answers once the block is done
        s.reset_input_buffer()
        s.write(b"OI;")
        print("plotter:", s.read_until(b"\r").decode().strip() or "no answer")
        t0 = time.time()
        for i, b in enumerate(blocks, 1):
            s.write(b.encode() + b"OS;")
            if not s.read_until(b"\r"):
                sys.exit(f"timeout at block {i}/{len(blocks)} – check the plotter, then start again")
            print(f"\r{i}/{len(blocks)} blocks, {time.time() - t0:.0f} s", end="", flush=True)
        s.write(b"OE;")
        print("\ndone, error code (OE):", s.read_until(b"\r").decode().strip())


if __name__ == "__main__":
    demo = "IN;SP1;\nPU1,2;PD3,4;" * 50
    assert "".join(chunks(demo, 40)) == demo.replace("\n", "") and max(map(len, chunks(demo, 40))) <= 40
    assert [l[0] for l in order([[(5, 5), (9, 9)], [(1, 1), (0, 0)]])[0]] == [(0, 0), (5, 5)]
    print("ok")
