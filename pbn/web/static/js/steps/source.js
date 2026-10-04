// Step 1: the picture – upload an image or open a project (examples/, projects/).

import { api } from '../api.js';
import { h, busy, toast, go } from '../dom.js';
import { state, set, subscribe, resetHistory } from '../store.js';
import { loadInventory } from './inventory.js';

function useSource(source, project = null) {
  resetHistory();
  set({
    source, project,
    analysis: null, mapping: [],
    pinned: new Set(project?.palette.map(e => e.code) ?? []),
    extra: new Map((project?.palette ?? []).map(e => [e.code, e])),
    quantize: project ? { ...project.quantize } : { chroma_weight: 1.4 },
  });
}

/** The inventory that contains most of a project's palette (same code and hex). */
async function guessInventory(palette) {
  let best = null;
  for (const inv of await api.inventories()) {
    const hex = new Map((await api.inventory(inv.id)).map(e => [e.code, e.hex]));
    const hits = palette.filter(e => hex.get(e.code) === e.hex.toLowerCase()).length;
    if (hits && (!best || hits > best.hits)) best = { inv, hits };
  }
  return best?.inv;
}

async function upload(file, el) {
  await busy(el, async () => {
    const img = await api.uploadImage(file);
    useSource(img);
    toast(`Loaded ${file.name}`);
    go('inventory');
  });
}

async function openProject(p, el) {
  await busy(el, async () => {
    const r = await api.openProject(p.path);
    useSource(r.image, r.project);
    if (r.project.palette.length) {
      const inv = await guessInventory(r.project.palette);
      if (inv) await loadInventory(inv.id, inv.name);
    }
    toast(`Opened ${p.name}`);
    go(state.inventory ? 'mapping' : 'inventory');
  });
}

function current() {
  const s = state.source;
  if (!s) return null;
  return h('div.card.current', {},
    h('img.thumb', { src: api.imageUrl(s.id), alt: '' }),
    h('div.grow', {},
      h('h2', {}, s.name),
      h('p.muted', {}, `${s.width} × ${s.height} px working size`,
        state.project ? ` · project ${state.project.path} · ${state.project.palette.length} palette colours` : ' · uploaded image')),
    h('button.primary', { onclick: () => go('inventory') }, 'Next: inventory →'));
}

export default {
  id: 'source',
  title: 'Picture',
  ready: s => !!s.source,

  mount(el) {
    const input = h('input', { type: 'file', accept: 'image/*,.svg', hidden: true,
      onchange: e => e.target.files[0] && upload(e.target.files[0], drop) });
    const drop = h('label.card.drop', {
      ondragover: e => { e.preventDefault(); drop.classList.add('over'); },
      ondragleave: () => drop.classList.remove('over'),
      ondrop: e => {
        e.preventDefault();
        drop.classList.remove('over');
        const f = e.dataTransfer.files[0];
        if (f) upload(f, drop);
      },
    }, input,
      h('div.drop-icon', { 'aria-hidden': 'true' }, '⬆'),
      h('strong', {}, 'Drop an image here or click to choose'),
      h('span.muted', {}, 'PNG, JPEG, WebP, TIFF – SVG if ImageMagick is installed'));

    const list = h('div.project-grid', {}, h('p.muted', {}, 'Loading…'));
    const slot = h('div');
    el.append(h('section.page', {},
      h('h1', {}, 'Choose a picture'),
      h('p.lead', {}, 'Start from an image, or open a project to rework its palette.'),
      slot,
      h('div.cols', {},
        drop,
        h('div.card', {}, h('h2', {}, 'Projects'), list))));

    const renderCurrent = () => slot.replaceChildren(current() ?? '');
    renderCurrent();
    api.projects().then(ps => {
      list.replaceChildren(...(ps.length ? ps.map(p => {
        const tile = h('button.project', {
          disabled: !!p.error, title: p.error ?? p.path,
          onclick: () => openProject(p, tile),
        },
          p.thumb ? h('img', { src: api.projectThumb(p.path), alt: '' })
            : h('div.noimg', { title: 'Preview after the first prepare step' }, p.source?.split('.').pop() ?? '?'),
          h('strong', {}, p.name),
          h('span.muted', {}, p.error ? 'invalid TOML' : p.path));
        return tile;
      }) : [h('p.muted', {}, 'No projects in examples/ or projects/ yet.')]));
    }).catch(err => toast(err.message, 'error'));
    return subscribe(p => { if ('source' in p) renderCurrent(); });
  },
};
