# plot-by-numbers

Turn any picture into a **paint-by-numbers template drawn by a pen plotter**, matched to
the markers or paints you actually own.

![Pipeline: source → quantized to 10 Copic markers → regions → pencil plot](docs/pipeline.jpg)

You give it an image (SVG or raster) and a palette from a real product line (Copic,
Stylefile, Talens Ecoline, …). It produces:

- an **HPGL file** that draws every region outline, a number in each region, and a legend
  with **one pen in one pass** (a pencil works well, because you colour over it afterwards),
- a **colour proof** showing how the finished painting will look,
- a **colour reference sheet** and a plot report with stroke length and estimated plot time.

The numbers also give the **painting order**: 1 is the lightest colour and the highest number
is the darkest. Paint light to dark and leave paper white blank. Markers then can't bleed
dark into light.

| Colour proof | Plotted lines, 1:1 detail |
|---|---|
| ![Colour proof](docs/starry-night-color.jpg) | ![Line detail](docs/starry-night-detail.png) |

The example is Van Gogh's *The Starry Night*: 135 regions, 10 Copic Sketch markers, A3
landscape on a Roland DXY-1200, about 4 minutes of plotting.

## What's inside

| | |
|---|---|
| `pbn/` | The pipeline (Python, numpy/scipy/Pillow): prepare → quantize → segment → vectorize → layout → hpgl, plus `pick`, `calib`, `send` and `swatch` tools |
| `pbn/web/` | Browser app for mapping a picture's colours onto an inventory (`python -m pbn web`) |
| `palettes/` | Colour inventories of real products as JSON: **Copic Sketch** (350), **Stylefile Marker** (124), **Talens Ecoline** (59), **Artecho Acrylic** (48). `view.html` is a browser viewer for them |
| `examples/starry-night/` | Two complete projects: a stylised vector tracing and the raw museum photo |

Highlights:

- **Palette picking from what you own.** Weighted k-medoids in CIELAB chooses the *k*
  inventory colours that best cover the picture. You can force colours to stay in, for
  example the yellow of the moon.
- **Regions that follow the picture.** Colours are assigned with edge-aware smoothing
  (a guided filter on the colour costs): brush texture and noise average out, real edges
  stay where they are.
- **Regions you can actually paint.** Small regions merge into the neighbour that looks
  most alike, and a merged region takes the palette colour closest to its average picture
  colour. Small accents that stand out from everything around them (a star) are kept longer.
  Spikes and thin bridges are cut off, and regions too narrow for their number are merged.
  Boundaries are smoothed, and shared borders are drawn once.
- **Numbers that fit.** Each number goes at the point of the region farthest from its
  border. If a region is still too small for its number (e.g. with `min_width_mm = 0`), it
  is listed so you can write the number in by hand.
- **Plotter-agnostic HPGL/1.** It uses a minimal command set (`IN SP VS PU PD`) and its own
  single-stroke font, so the plotter's character set isn't needed. Path order is
  nearest-neighbour, the output is checked against the drawable area, and scale and offset
  can be calibrated.
- **Serial sender for old plotters without handshake lines.** It sends blocks of at most
  256 bytes and synchronises with an `OS;` query after each block.

## Install

Requires Python ≥ 3.11 and, for SVG sources, [ImageMagick](https://imagemagick.org) 7 (`magick`).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`pyserial` is only needed for `send`, `starlette` and `uvicorn` only for `web`.

## Quick start: the example

```bash
python -m pbn run examples/starry-night/starry-night.toml
```

The results are written to `examples/starry-night/out/`. Run it with
`starry-night-photo.toml` instead to start from the photo of the painting.

## Make your own

**1. Create a project.** Put your image somewhere, for example `projects/harbour/source.jpg`,
and add `projects/harbour/harbour.toml` next to it:

```toml
source = "source.jpg"
palette = "palette.json"     # created in step 3
```

All other settings have defaults (see [Configuration](#configuration)). Paths are relative
to the TOML file.

**2. Prepare the source** (render or resize it to the working size):

```bash
python -m pbn run projects/harbour/harbour.toml prepare
```

**3. Pick colours** from an inventory. This example chooses 10 Copic markers and keeps Y15:

```bash
python -m pbn pick projects/harbour/harbour.toml palettes/copic-sketch.json 10 --fixed Y15
```

The result is written to the project's `palette` file. You can also write that file by
hand: it's a JSON list of inventory entries, in any order.

**4. Run the rest and review:**

```bash
python -m pbn run projects/harbour/harbour.toml --from quantize
```

| Check | File in `out/` | If it's wrong |
|---|---|---|
| Colours | `quantized_compare.png` | Swap colours in the palette file, or use `pick` with other `--fixed` codes |
| Regions | `regions.png` | Change `[segment]`: `min_area_mm2` (larger = fewer, bigger regions), `max_regions`, `smooth_mm`, `neck_mm`; `[quantize]` `filter_mm` (larger = calmer shapes) |
| Sheet | `preview.png` (1:1 at 8 px/mm), `preview_color.png` | Change `[layout]` |

After a change, rerun from the step it affects, for example `--from segment`.

**5. Calibrate the plotter once** (see [Plotter setup](#plotter-setup)), then plot:

```bash
python -m pbn send projects/harbour/out/harbour.hpgl /dev/cu.usbserial-1130
```

Then colour the sheet light to dark, following `color-reference.png`.

## Web app: map colours visually

```bash
pip install starlette uvicorn
python -m pbn web --open          # http://127.0.0.1:8000/
```

A browser front end for choosing the palette, in four steps:

1. **Picture**: upload an image, or open a project from `examples/` or `projects/` (its
   palette and `[quantize]` settings are loaded, the inventory is detected).
2. **Inventory**: a built-in product line or your own upload (JSON like `palettes/*.json`,
   CSV with `code,name,hex`, or a GIMP `.gpl`). Click colours you don't own to exclude them
   from suggestions; this is remembered per inventory in the browser.
3. **Mapping**: the picture is reduced to *n* image colours (k-means in CIELAB). Each one is
   mapped to an inventory colour; image colours sharing an inventory colour make the palette
   smaller.
   - Select image colours in the list or by clicking the picture (Shift/Ctrl adds), then
     click a candidate. Hovering a candidate previews it in the picture.
   - Drag image colours onto a palette colour, or one palette colour onto another to merge.
   - **Nearest** maps everything to the closest owned colour; **Auto-pick k** runs the same
     k-medoids as `pick`, keeping pinned colours.
   - **Plot preview** runs the real `quantize` step with the current palette. Hold Space for
     the original, Ctrl+Z / Ctrl+Shift+Z to undo / redo.
4. **Result**: palette in painting order with each colour's share of the plot. Download the
   JSON, update the opened project's palette file, or create `projects/<name>/` with source,
   `palette.json` and TOML, ready for `python -m pbn run`.

Uploads and uploaded inventories are kept in `projects/.web/`. The server only listens on
localhost by default. Code: [`pbn/web/`](pbn/web) (`workspace.py` for files and pipeline
calls, `app.py` for the routes, `static/js/steps/` for one module per step), so later pipeline
steps can be added as further steps.

## Commands

```text
python -m pbn run    PROJECT.toml [STEP ...] [--from STEP]   pipeline, default: all steps
python -m pbn pick   PROJECT.toml INVENTORY.json K [--fixed CODES] [-o OUT.json]
python -m pbn calib  PROJECT.toml                            out/calib-test.hpgl
python -m pbn send   FILE.hpgl PORT [--baud 9600]
python -m pbn swatch INVENTORY.json [-o OUT.pdf] [--bw]      A4 swatch card
python -m pbn web    [--root DIR] [--port 8000] [--open]     browser app (needs starlette, uvicorn)
python -m pbn png    PALETTE.json [-o OUT.png]               palette as PNG strip (1 px per colour)
```

| Step | Does | Writes to `out/` |
|---|---|---|
| `prepare` | Renders an SVG without antialiasing, or resizes a raster image. `crop_scan` straightens a photographed canvas and removes its border | `source.png` |
| `quantize` | Maps each pixel to the cheapest palette colour in Lab after edge-aware smoothing of the colour costs (guided filter) | `labels.png`, `palette.json`, `quantized_compare.png` |
| `segment` | Connected components, merging by size and colour similarity, boundary smoothing, neck cutting, minimum width | `regions.npz`, `regions.png` |
| `vectorize` | Traces shared boundaries once, smooths them (Douglas–Peucker + Chaikin), places numbers | `vectors.json`, `regions.svg` |
| `layout` | Sheet layout in mm with picture, legend, frame and corner marks | `layout.json`, `preview.svg/.png`, `preview_color.png`, `color-reference.png/.pdf` |
| `hpgl` | Orders the paths, writes HPGL and checks it | `<name>.hpgl`, `report.md` |

## Configuration

The values below are the defaults, from [`pbn/config.py`](pbn/config.py). Unknown keys
are rejected, so typos don't go unnoticed.

```toml
source = "…"            # .svg or raster image (required)
palette = "…"           # selection JSON (required)
out = "out"
name = "<toml name>"    # name of the .hpgl file
aspect = 1.27           # optional: stretch to this width/height (e.g. the real canvas)
work_width = 2000       # processing width in px; the mm scale follows from the sheet
svg_density = 84        # optional: ImageMagick -density, default = just enough for work_width
crop_scan = false       # photo of a canvas on a light background: deskew + crop the border

[quantize]
chroma_weight = 1.4     # distance = dL² + w·(da² + db²)
dark_boost = 1.0        # e.g. 2.5 for dark photos: spreads near-black tones apart
dark_l = 35.0           # dark_boost works below this L*…
dark_span = 15.0        # …fading in over this range…
dark_c = 28.0           # …and only on near-neutral pixels (chroma < dark_c)
dark_only = []          # codes only allowed where L* < dark_l, e.g. ["BG78"]
filter_mm = 1.0         # edge-aware smoothing radius, 0 = old majority filter + opening
filter_eps = 0.02       # edges weaker than about ΔE 100·√eps are smoothed away

[segment]
min_area_mm2 = 45.0
max_regions = 280
smooth_mm = 1.0         # 0 = off
max_area_mm2 = 2500.0   # big regions stop swallowing neighbours
contrast_de = 20.0      # a region this far (ΔE) from all its neighbours counts as 2× its area
neck_mm = 1.5           # cut off spikes and bridges narrower than this, 0 = off
min_width_mm = …        # merge narrower regions (inscribed circle); default: too narrow for
                        # the region's number at digit_height_mm, 0 = off

[layout]
margin_mm = 4.0
legend_width_mm = 24.0
gap_mm = 6.0
digit_height_mm = 2.0   # smallest height your pen draws legibly
box_mm = 12.0           # legend swatches (shrink automatically for many colours)

[plotter]
width_mm = 403.95       # drawable area = hard-clip limits, origin bottom left
height_mm = 276.0       # (default: Roland DXY-1200, A3 landscape)
pu_per_mm = 40.0        # plotter units per mm (HP/Roland: 1 PU = 0.025 mm)
scale_x = 1.0           # calibration: measured length of the 100 mm line / 100
scale_y = 1.0
offset_x_mm = 0.0       # shifts the whole plot
offset_y_mm = 0.0
speed_cm_s = 15         # VS; slower is kinder to pencils
pd_chunk = 32           # points per PD command (small buffers on old plotters)
```

## Plotter setup

1. **Drawable area.** Load your paper and send `OH;` (output hard-clip limits). The plotter
   replies `x1,y1,x2,y2` in plotter units. Set `width_mm = x2 / pu_per_mm` and
   `height_mm = y2 / pu_per_mm`.
2. **Calibration sheet.** Run `python -m pbn calib PROJECT.toml` and plot
   `out/calib-test.hpgl`. Measure the 100 mm square and ruler and set `scale_x`/`scale_y`.
   Then pick the smallest digit row (1.0 / 1.2 / 1.5 / 2.0 mm) that is legible with your pen
   and set it as `digit_height_mm`.
3. **Sending.** `send` talks 8N1 at 9600 baud and needs no CTS/DSR lines. It prints the
   plotter's `OI` identification first and the `OE` error code at the end. Any other way of
   getting HPGL to the plotter works too.

The HPGL is plain HPGL/1 and should run on most HP-compatible pen plotters. It was tested on
a Roland DXY-1200.

## Palettes

An inventory is a JSON list:

```json
[{ "code": "B18", "name": "Lapis Lazuli", "hex": "#1f74b6", "rgb": [31, 116, 182] }]
```

A selection (a project's `palette`) has the same format and lists only the colours used.

- **Browse:** run `python3 -m http.server` and open
  `http://localhost:8000/palettes/view.html?src=copic-sketch.json`, or open the file and use
  the file picker.
- **Check against reality:** `python -m pbn swatch palettes/copic-sketch.json` prints an A4
  card with the digital colour next to an empty field. Paint a real stroke into each field.
  The hex values are taken from manufacturer charts and are only approximations of the
  real ink.
- **Export as PNG:** `python -m pbn png palettes/copic-sketch.json` writes a one-pixel-high
  strip, one pixel per colour, for tools that take a palette as an image. Up to 256 colours
  it is an indexed PNG whose colour table is the palette; more colours fall back to RGB.
- **Add your own:** any product line works. Codes can use digits and the letters
  `B C E F G N R T V W Y`. Add glyphs to [`pbn/font.py`](pbn/font.py) if you need more.

## The example: *The Starry Night*

`examples/starry-night/` contains:

- `source/Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg`: the museum photo
  (Google Art Project via Wikimedia Commons, public domain)
- `source/starry-night-vectorized.svg`: a stylised vector tracing made in
  Affinity Designer, with flat colour areas that give clean regions
- `starry-night.toml`: the vector tracing, using
  `palettes/copic-affinity.json` (picked with `--fixed Y15,YR16,E49` so the moon, star cores
  and cypress strokes survive). Result: about 145 regions, each with its number
- `starry-night-photo.toml`: the photo, with `crop_scan`, `dark_boost = 2.5` and a palette
  that includes BG78/W9 for the dark cypress. Result: about 250 regions

## Ideas / not done yet

- Several pens, for example coloured outlines (the HPGL writer always uses `SP1`)
- HPGL/2 or G-code output for other plotters and pen-equipped CNC machines
