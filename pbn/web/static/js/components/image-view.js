// Canvas view of the working image. Shows either the original or a label map recoloured
// (labels: Uint8Array, one entry per pixel; colours: '#rrggbb' per label), and can fade
// everything except a set of labels. Pointer positions are reported in image pixels.
// Reusable for later steps (regions, numbers) that also produce label maps.

import { h } from '../dom.js';
import { hexRgb } from '../color.js';

const FADE = 0.28;  // share of the original colour that stays visible when faded
const FADE_TO = 238;

/** '#rrggbb' -> packed RGBA for a little-endian Uint32Array view of ImageData. */
const pack = ([r, g, b]) => (255 << 24 | b << 16 | g << 8 | r) >>> 0;
const fade = rgb => rgb.map(v => Math.round(v * FADE + FADE_TO * (1 - FADE)));

export class ImageView {
  constructor({ width, height, src }) {
    this.w = width;
    this.h = height;
    this.canvas = h('canvas', { width, height });
    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
    this.tip = h('div.tooltip', { hidden: true });
    this.el = h('div.image-view', {}, this.canvas, this.tip);
    this.original = null;
    this.ready = new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        this.ctx.drawImage(img, 0, 0, width, height);
        this.original = new Uint32Array(this.ctx.getImageData(0, 0, width, height).data.buffer.slice(0));
        this.faded = this.original.map(c => pack(fade([c & 255, c >> 8 & 255, c >> 16 & 255])));
        resolve();
      };
      img.onerror = reject;
      img.src = src;
    });
  }

  /**
   * layer: null (original) or {labels, colors}
   * focus: null or {labels, keep: Set|Array of label values} – everything else is faded
   */
  render(layer = null, focus = null) {
    if (!this.original) return;
    const n = this.w * this.h;
    const out = new ImageData(this.w, this.h);
    const px = new Uint32Array(out.data.buffer);
    let keep = null;
    if (focus) {
      keep = new Uint8Array(256);
      for (const k of focus.keep) keep[k] = 1;
    }
    if (layer) {
      const rgb = layer.colors.map(c => hexRgb(c ?? '#ff00ff'));
      const on = rgb.map(pack), off = rgb.map(c => pack(fade(c)));
      const L = layer.labels, F = focus?.labels;
      for (let i = 0; i < n; i++) px[i] = keep && !keep[F[i]] ? off[L[i]] : on[L[i]];
    } else if (keep) {
      const F = focus.labels;
      for (let i = 0; i < n; i++) px[i] = keep[F[i]] ? this.original[i] : this.faded[i];
    } else {
      px.set(this.original);
    }
    this.ctx.putImageData(out, 0, 0);
  }

  /** Image pixel under a pointer event, or null outside. */
  pixelAt(e) {
    const r = this.canvas.getBoundingClientRect();
    const x = Math.floor((e.clientX - r.left) / r.width * this.w);
    const y = Math.floor((e.clientY - r.top) / r.height * this.h);
    return x >= 0 && y >= 0 && x < this.w && y < this.h ? { x, y, i: y * this.w + x } : null;
  }

  showTip(e, content) {
    if (!content) { this.tip.hidden = true; return; }
    this.tip.replaceChildren(content);
    this.tip.hidden = false;
    const r = this.el.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    this.tip.style.left = `${Math.min(x + 14, r.width - this.tip.offsetWidth - 4)}px`;
    this.tip.style.top = `${y + 18 + this.tip.offsetHeight > r.height ? y - this.tip.offsetHeight - 10 : y + 18}px`;
  }
}
