// The colour mapping as pure-ish functions over `state`: which inventory colour each image
// colour goes to, and the reduced palette that results from it.

import { state } from './store.js';
import { PAPER, PAPER_ENTRY, dist } from './color.js';

export function entry(code) {
  if (code === PAPER) return PAPER_ENTRY;
  // a project's own palette entries win: the same code may mean another colour in another inventory
  return state.extra.get(code) ?? state.inventory?.byCode.get(code) ?? null;
}

export const isOwned = code => !state.owned || state.owned.has(code);
export const ownedEntries = () => (state.inventory?.entries ?? []).filter(e => isOwned(e.code));

/** Codes in the reduced palette: pinned ones plus every mapping target (paper white excluded). */
export function paletteCodes() {
  const s = new Set(state.pinned);
  for (const c of state.mapping) if (c && c !== PAPER) s.add(c);
  return [...s].filter(c => entry(c));
}

/** Rows of the reduced palette, painting order (1 = lightest), plus the paper-white row. */
export function reducedPalette() {
  const clusters = state.analysis?.clusters ?? [];
  const rows = new Map(paletteCodes().map(c => [c, { code: c, entry: entry(c), share: 0, clusters: [], pinned: state.pinned.has(c) }]));
  const paper = { code: PAPER, entry: PAPER_ENTRY, share: 0, clusters: [], pinned: false };
  state.mapping.forEach((c, i) => {
    const r = c === PAPER ? paper : rows.get(c);
    if (r && clusters[i]) { r.share += clusters[i].share; r.clusters.push(i); }
  });
  const list = [...rows.values()].sort((a, b) => b.entry.lab[0] - a.entry.lab[0]);
  list.forEach((r, k) => { r.nr = k + 1; });
  return { list, paper };
}

/** entries sorted by distance to lab: [{entry, d}] (d = sqrt of the quantize metric). */
export function nearest(lab, entries, n = Infinity) {
  const w = state.quantize.chroma_weight;
  return entries.map(e => ({ entry: e, d: Math.sqrt(dist(lab, e.lab, w)) }))
    .sort((a, b) => a.d - b.d).slice(0, n);
}

/** Mapping of every cluster to its nearest entry of `pool` (or paper white). */
export function mapToNearest(pool, clusters = state.analysis.clusters) {
  const all = [...pool, PAPER_ENTRY];
  return clusters.map(c => nearest(c.lab, all, 1)[0].entry.code);
}

/** Default mapping for fresh clusters: nearest colour of the current palette if there is one,
 *  otherwise of the owned inventory. */
export function initialMapping(clusters) {
  const pool = paletteCodes().map(entry);
  return mapToNearest(pool.length ? pool : ownedEntries(), clusters);
}

/** Selection entries as written to the palette JSON (inventory format, painting order). */
export function exportPalette() {
  return reducedPalette().list.map(({ entry: e }) => {
    const o = { code: e.code, name: e.name };
    if (e.group) o.group = e.group;
    return Object.assign(o, { hex: e.hex, rgb: e.rgb });
  });
}
