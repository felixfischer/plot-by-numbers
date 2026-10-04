// Colour helpers. Lab values come from the server (pbn/palette.py); here only distances.

export const PAPER = '__paper__';
export const PAPER_ENTRY = Object.freeze({ code: PAPER, name: 'Paper white (left blank)', hex: '#ffffff', lab: [100, 0, 0] });

/** Same metric as the quantize step: dL² + w·(da² + db²). */
export function dist(a, b, w) {
  const dL = a[0] - b[0], da = a[1] - b[1], db = a[2] - b[2];
  return dL * dL + w * (da * da + db * db);
}

export const hexRgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));

/** Text colour that stays readable on `hex`. */
export function inkOn(hex) {
  const [r, g, b] = hexRgb(hex);
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#1b1b1b' : '#ffffff';
}

/** Share-weighted mean Lab of clusters. */
export function meanLab(clusters) {
  let w = 0;
  const m = [0, 0, 0];
  for (const c of clusters) {
    w += c.share;
    for (let j = 0; j < 3; j++) m[j] += c.lab[j] * c.share;
  }
  return w ? m.map(v => v / w) : [50, 0, 0];
}

const lin = v => (v > 0.0031308 ? 1.055 * Math.abs(v) ** (1 / 2.4) - 0.055 : 12.92 * v);

/** Lab (D65) -> #rrggbb, for showing mean colours of selections. */
export function labHex([L, a, b]) {
  const fy = (L + 16) / 116, e = 6 / 29;
  const f = [fy + a / 500, fy, fy - b / 200].map(t => (t > e ? t ** 3 : (t - 4 / 29) * 3 * e * e));
  const [x, y, z] = [f[0] * 0.95047, f[1], f[2] * 1.08883];
  const rgb = [3.2404542 * x - 1.5371385 * y - 0.4985314 * z,
               -0.969266 * x + 1.8760108 * y + 0.041556 * z,
               0.0556434 * x - 0.2040259 * y + 1.0572252 * z];
  return '#' + rgb.map(v => Math.round(Math.min(1, Math.max(0, lin(v))) * 255).toString(16).padStart(2, '0')).join('');
}
