// Step 2: the colour inventory – a built-in product line or an upload – and which of its
// colours the user actually owns (remembered per inventory in localStorage).

import { api } from '../api.js';
import { h, busy, toast, go } from '../dom.js';
import { state, set, subscribe } from '../store.js';
import { inkOn } from '../color.js';

const ownedKey = id => `pbn.owned.${id}`;

export async function loadInventory(id, name) {
  const entries = await api.inventory(id);
  let owned = null;
  try {
    const saved = JSON.parse(localStorage.getItem(ownedKey(id)));
    if (Array.isArray(saved)) owned = new Set(saved);
  } catch { /* storage unavailable: everything counts as owned */ }
  const same = state.inventory?.id === id;
  set({
    inventory: { id, name, entries, byCode: new Map(entries.map(e => [e.code, e])) },
    owned,
    mapping: same ? state.mapping : [],
  });
}

function setOwned(owned) {
  const all = owned.size === state.inventory.entries.length;
  try {
    if (all) localStorage.removeItem(ownedKey(state.inventory.id));
    else localStorage.setItem(ownedKey(state.inventory.id), JSON.stringify([...owned]));
  } catch { /* not persisted */ }
  set({ owned: all ? null : owned });
}

function inventoryCard(inv) {
  const card = h('button.inv-card', {
    class: state.inventory?.id === inv.id ? 'selected' : null,
    'aria-pressed': String(state.inventory?.id === inv.id),
    onclick: () => busy(card, () => loadInventory(inv.id, inv.name)),
  },
    h('div.strip', {}, inv.preview.map(c => h('span', { style: { background: c } }))),
    h('strong', {}, inv.name),
    h('span.muted', {}, `${inv.count} colours · ${inv.kind}`));
  return card;
}

function uploadCard(refresh) {
  const input = h('input', {
    type: 'file', accept: '.json,.csv,.tsv,.txt,.gpl', hidden: true,
    onchange: async e => {
      const f = e.target.files[0];
      if (!f) return;
      await busy(card, async () => {
        const r = await api.uploadInventory(f.name.replace(/\.[^.]+$/, ''), f.name, await f.text());
        toast(`Uploaded ${r.count} colours`);
        await refresh();
        const inv = (await api.inventories()).find(i => i.id === r.id);
        await loadInventory(r.id, inv?.name ?? f.name);
      });
      e.target.value = '';
    },
  });
  const card = h('label.inv-card.upload', {}, input,
    h('strong', {}, '+ Upload your own'),
    h('span.muted', {}, 'JSON like palettes/*.json, CSV (code, name, hex) or GIMP .gpl'));
  return card;
}

function ownedPanel() {
  const inv = state.inventory;
  if (!inv) return h('p.muted.center', {}, 'Choose an inventory above.');
  const owned = state.owned ?? new Set(inv.entries.map(e => e.code));
  const count = h('span.muted');
  const grid = h('div.swatch-grid');
  const search = h('input.search', { type: 'search', placeholder: 'Filter by code or name…' });

  const tiles = inv.entries.map(e => {
    const t = h('button.sw-tile', {
      style: { background: e.hex, color: inkOn(e.hex) }, title: `${e.code} · ${e.name} · ${e.hex}`,
      onclick: () => {
        const o = new Set(state.owned ?? inv.entries.map(x => x.code));
        o.has(e.code) ? o.delete(e.code) : o.add(e.code);
        setOwned(o);
      },
    }, h('span', {}, e.code));
    t.dataset.code = e.code;
    t.dataset.text = `${e.code} ${e.name}`.toLowerCase();
    return t;
  });
  grid.append(...tiles);

  const update = () => {
    const o = state.owned;
    for (const t of tiles) {
      const on = !o || o.has(t.dataset.code);
      t.classList.toggle('off', !on);
      t.setAttribute('aria-pressed', String(on));
    }
    count.textContent = `${o ? o.size : inv.entries.length} of ${inv.entries.length} owned`;
  };
  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase();
    for (const t of tiles) t.hidden = q && !t.dataset.text.includes(q);
  });
  const visible = () => tiles.filter(t => !t.hidden).map(t => t.dataset.code);
  const bulk = fn => () => { const o = new Set(state.owned ?? inv.entries.map(x => x.code)); visible().forEach(c => fn(o, c)); setOwned(o); };

  update();
  return {
    update,
    el: h('div.card', {},
      h('div.card-head', {},
        h('div', {}, h('h2', {}, `Your colours · ${inv.name}`),
          h('p.muted', {}, 'Click a colour to mark it as not owned. Suggestions and auto-pick only use owned colours.')),
        h('button.primary', { onclick: () => go('mapping') }, 'Next: map colours →')),
      h('div.toolbar', {}, search,
        h('button', { onclick: bulk((o, c) => o.add(c)), title: 'Mark the visible colours as owned' }, 'All'),
        h('button', { onclick: bulk((o, c) => o.delete(c)), title: 'Mark the visible colours as not owned' }, 'None'),
        h('button', { onclick: bulk((o, c) => (o.has(c) ? o.delete(c) : o.add(c))) }, 'Invert'),
        count),
      grid),
  };
}

export default {
  id: 'inventory',
  title: 'Inventory',
  ready: s => !!s.inventory && (!s.owned || s.owned.size > 0),

  mount(el) {
    const cards = h('div.inv-grid');
    const slot = h('div');
    let panel = null;
    el.append(h('section.page', {},
      h('h1', {}, 'Choose your colour inventory'),
      h('p.lead', {}, 'The markers or paints you work with. The picture’s colours will be mapped onto these.'),
      cards, slot));

    let list = [];
    const renderCards = () => cards.replaceChildren(...list.map(inventoryCard), uploadCard(refresh));
    const refresh = async () => { list = await api.inventories(); renderCards(); };
    const renderPanel = () => { panel = ownedPanel(); slot.replaceChildren(panel.el ?? panel); };

    refresh().catch(err => toast(err.message, 'error'));
    renderPanel();
    return subscribe(p => {
      if ('inventory' in p) { renderCards(); renderPanel(); }
      else if ('owned' in p) panel?.update?.();
    });
  },
};
