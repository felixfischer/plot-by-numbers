// Central app state. Steps read `state`, change it with set() or edit() (undoable) and
// re-render in subscribe(). New pipeline steps add their own fields here.

export const state = {
  source: null,      // working image: {id, width, height, name, project?, original?}
  project: null,     // opened project: {path, name, palette_file, palette, quantize}
  inventory: null,   // {id, name, entries, byCode: Map}
  owned: null,       // Set of codes the user owns in this inventory, null = all
  n: 24,             // number of image colours (clusters)
  analysis: null,    // {n, width, height, clusters: [{i, hex, lab, share}], labels: Uint8Array}
  mapping: [],       // per cluster: inventory code, PAPER or null
  pinned: new Set(), // codes kept in the palette even without a cluster (fixed for auto-pick)
  extra: new Map(),  // code -> entry for palette colours that aren't in the inventory
  quantize: { chroma_weight: 1.4 },  // settings for the pipeline's quantize step
};

const listeners = new Set();

export function set(patch) {
  Object.assign(state, patch);
  for (const fn of [...listeners]) fn(patch);
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// ---- undo / redo for the mapping ------------------------------------------------------------

const past = [], future = [];
const snapshot = () => ({ mapping: [...state.mapping], pinned: new Set(state.pinned) });

/** Undoable change of mapping/pinned. */
export function edit(patch) {
  past.push(snapshot());
  if (past.length > 200) past.shift();
  future.length = 0;
  set(patch);
}

export function resetHistory() {
  past.length = future.length = 0;
}

export const canUndo = () => past.length > 0;
export const canRedo = () => future.length > 0;

export function undo() {
  if (!past.length) return;
  future.push(snapshot());
  set(past.pop());
}

export function redo() {
  if (!future.length) return;
  past.push(snapshot());
  set(future.pop());
}
