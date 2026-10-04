"""plot-by-numbers CLI – run `python -m pbn -h`."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from . import hpgl, layout, prepare, quantize, segment, swatch, vectorize
from .config import Project
from .palette import pick

STEPS = {"prepare": prepare, "quantize": quantize, "segment": segment,
         "vectorize": vectorize, "layout": layout, "hpgl": hpgl}


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m pbn", description="Pen-plotter paint-by-numbers templates.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run pipeline steps (default: all)")
    r.add_argument("project", type=Path, help="project TOML")
    r.add_argument("steps", nargs="*", choices=list(STEPS), metavar="step", help=f"any of: {', '.join(STEPS)}")
    r.add_argument("--from", dest="start", choices=list(STEPS), help="run from this step to the end")

    k = sub.add_parser("pick", help="choose K colours from an inventory for the prepared source")
    k.add_argument("project", type=Path)
    k.add_argument("inventory", type=Path)
    k.add_argument("k", type=int)
    k.add_argument("--fixed", default="", help="comma-separated codes that must be included, e.g. Y15,E49")
    k.add_argument("-o", "--out", type=Path, help="write selection JSON (default: the project's palette file)")

    c = sub.add_parser("calib", help="write out/calib-test.hpgl for the project's plotter settings")
    c.add_argument("project", type=Path)

    s = sub.add_parser("send", help="send an HPGL file over a serial port")
    s.add_argument("file")
    s.add_argument("port", help="e.g. /dev/cu.usbserial-1130 or COM3")
    s.add_argument("--baud", type=int, default=9600)

    w = sub.add_parser("swatch", help="A4 swatch card PDF for an inventory")
    w.add_argument("inventory", type=Path)
    w.add_argument("-o", "--out", type=Path)
    w.add_argument("--bw", action="store_true", help="no colour fills (toner-friendly)")

    a = ap.parse_args()
    if a.cmd == "run":
        p = Project(a.project)
        names = list(STEPS)
        for name in a.steps or (names[names.index(a.start):] if a.start else names):
            print(f"[{name}]")
            t = time.time()
            STEPS[name].run(p)
            print(f"  ({time.time() - t:.1f} s)")
    elif a.cmd == "pick":
        p = Project(a.project)
        sel = pick(p.out / "source.png", a.inventory, a.k, [f for f in a.fixed.split(",") if f], a.out or p.palette_path)
        for e in sel:
            print(f"  {e['code']:>5}  {e['hex']}  {e['name']}")
    elif a.cmd == "calib":
        hpgl.calib(Project(a.project))
    elif a.cmd == "send":
        hpgl.send(a.file, a.port, a.baud)
    elif a.cmd == "swatch":
        swatch.run(a.inventory, a.out, a.bw)


if __name__ == "__main__":
    main()
