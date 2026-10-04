// The pipeline as UI steps, in order. A step module exports
//   { id, title, ready(state) -> bool, mount(el) -> unmount? }
// Later steps (regions, vectors, layout, plot) are added to this list.

import source from './source.js';
import inventory from './inventory.js';
import mapping from './mapping.js';
import result from './result.js';

export const steps = [source, inventory, mapping, result];
