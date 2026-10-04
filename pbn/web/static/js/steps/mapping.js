// Step 3: map the picture's colours (clusters) onto inventory colours. Several image colours
// on the same inventory colour = the palette gets smaller. Interaction:
//   click / shift / ctrl-click image colours (list or picture) to select,
//   click a candidate or palette colour to assign, drag image colours onto palette colours,
//   drag a palette colour onto another to merge them, pin colours to keep them.

import { api } from '../api.js';
import { h, busy, toast, debounce, pct, go } from '../dom.js';
import { state, set, edit, subscribe, undo, redo, canUndo, canRedo, resetHistory } from '../store.js';
import { PAPER, PAPER_ENTRY, inkOn, meanLab, labHex } from '../color.js';
import { entry, isOwned, ownedEntries, paletteCodes, reducedPalette, nearest, mapToNearest, initialMapping, exportPalette } from '../model.js';
import { ImageView } from '../components/image-view.js';

const DRAG_CLUSTERS = 'application/x-pbn-clusters';
const DRAG_CODE = 'application/x-pbn-code';
const label = code => (code === PAPER ? 'paper' : code);

function storageGet(k, fallback) {
  try { return localStorage.getItem(k) ?? fallback; } catch { return fallback; }
}
function storageSet(k, v) {
  try { localStorage.setItem(k, v); } catch { /* not persisted */ }
}

const PIN_ICON = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M9.8 1.5 14.5 6.2l-1.6.6-2.7 2.7.3 3.2-1.2 1.2-2.6-2.6L3 15l-.9-.9 3.7-3.7-2.6-2.6 1.2-1.2 3.2.3 2.7-2.7z" fill="currentColor"/></svg>';

export default {
  id: 'mapping',
  title: 'Mapping',
  ready: s => !!s.analysis && s.analysis.image === s.source?.id && paletteCodes().length > 0,

  mount(root) {
    const ui = {
      selection: new Set(),
      anchor: null,
      hover: null,      // {clusters: Set} | {codes: Set}
      preview: null,    // code shown for the selection while hovering a candidate
      mode: storageGet('pbn.view', 'mapping'),
      space: false,
      spotlight: storageGet('pbn.spotlight', '1') === '1',
      sort: storageGet('pbn.sort', 'share'),
      candLimit: 12,
      palLimit: 9,
      k: null,          // auto-pick size once the user changed it
      search: '',
      pipeline: null,   // {key, labels, palette}
      order: [],        // cluster indices in list order
    };

    // ---- skeleton -------------------------------------------------------------------------

    const view = new ImageView({ width: state.source.width, height: state.source.height, src: api.imageUrl(state.source.id) });
    const imagePane = h('section.pane.image-pane', {}, view.el,
      h('p.hint', {}, 'Hover to inspect · click to select (shift/ctrl adds) · hold Space for the original'));
    const listEl = h('div.cl-list', { role: 'listbox', 'aria-multiselectable': 'true', 'aria-label': 'Image colours' });
    const listHead = h('div.pane-head');
    const clusterPane = h('section.pane.cluster-pane', {}, listHead, listEl);
    const candPane = h('section.pane.cand-pane');
    const paletteBar = h('section.palette-bar');
    const toolbar = h('div.toolbar.map-toolbar');
    root.append(h('section.page.wide', {}, toolbar, paletteBar, h('div.mapping-grid', {}, imagePane, clusterPane, candPane)));

    // ---- actions --------------------------------------------------------------------------

    const clusters = () => state.analysis?.clusters ?? [];

    function assign(indices, code) {
      if (!indices.size) return;
      const m = [...state.mapping];
      for (const i of indices) m[i] = code;
      edit({ mapping: m });
    }

    function removeColour(code) {
      const rest = paletteCodes().filter(c => c !== code).map(entry);
      const pool = rest.length ? rest : ownedEntries().filter(e => e.code !== code);
      const idx = state.mapping.map((c, i) => (c === code ? i : -1)).filter(i => i >= 0);
      const re = mapToNearest(pool, idx.map(i => clusters()[i]));
      const m = [...state.mapping];
      idx.forEach((i, k) => { m[i] = re[k]; });
      const pinned = new Set(state.pinned);
      pinned.delete(code);
      edit({ mapping: m, pinned });
    }

    function merge(from, to) {
      if (from === to) return;
      const pinned = new Set(state.pinned);
      pinned.delete(from);
      edit({ mapping: state.mapping.map(c => (c === from ? to : c)), pinned });
      toast(`Merged ${label(from)} into ${label(to)}`);
    }

    function togglePin(code) {
      const pinned = new Set(state.pinned);
      pinned.has(code) ? pinned.delete(code) : pinned.add(code);
      edit({ pinned });
    }

    function select(i, e = {}) {
      const s = ui.selection;
      if (e.shiftKey && ui.anchor != null) {
        const a = ui.order.indexOf(ui.anchor), b = ui.order.indexOf(i);
        for (const j of ui.order.slice(Math.min(a, b), Math.max(a, b) + 1)) s.add(j);
      } else if (e.ctrlKey || e.metaKey) {
        s.has(i) ? s.delete(i) : s.add(i);
      } else {
        ui.selection = new Set([i]);
      }
      ui.anchor = i;
      ui.candLimit = 12;
      ui.palLimit = 9;
      renderSelection();
    }

    function selectCodes(codes) {
      ui.selection = new Set(state.mapping.map((c, i) => (codes.has(c) ? i : -1)).filter(i => i >= 0));
      ui.anchor = null;
      renderSelection();
    }

    function clearSelection() {
      ui.selection = new Set();
      renderSelection();
    }

    async function autoPick(k, btn) {
      const inv = state.inventory;
      const fixed = [...state.pinned].filter(c => inv.byCode.get(c)?.hex === entry(c)?.hex);
      const outside = [...state.pinned].filter(c => !fixed.includes(c)).map(entry).filter(Boolean);
      await busy(btn, async () => {
        const picked = await api.pick(state.source.id, {
          inventory: inv.id, k: Math.max(k - outside.length, fixed.length), fixed,
          candidates: state.owned ? [...state.owned] : null,
        });
        edit({ mapping: mapToNearest([...picked, ...outside]) });
        toast(`Picked ${picked.length + outside.length} colours`);
      });
    }

    // ---- pipeline preview (the real quantize step on the server) ---------------------------

    const pipelineKey = () => JSON.stringify([paletteCodes().map(c => [c, entry(c).hex]), state.quantize]);
    const pipelineValid = () => ui.pipeline?.key === pipelineKey();

    const fetchPipeline = debounce(async () => {
      if (ui.mode !== 'pipeline' || pipelineValid() || !paletteCodes().length) return;
      const key = pipelineKey();
      await busy(imagePane, async () => {
        const r = await api.quantize(state.source.id, exportPalette(), state.quantize);
        if (key === pipelineKey()) {
          ui.pipeline = { key, ...r };
          renderImage();
          renderPalette();
        }
      });
    }, 250);

    // ---- rendering ------------------------------------------------------------------------

    let frame = 0;
    function renderImage() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const a = state.analysis;
        if (!a) return view.render();
        const showMapping = ui.preview != null || ui.mode === 'mapping' || (ui.mode === 'pipeline' && !pipelineValid());
        let layer = null;
        if (ui.space) layer = null;
        else if (ui.mode === 'pipeline' && pipelineValid() && ui.preview == null) {
          layer = { labels: ui.pipeline.labels, colors: ui.pipeline.palette.map(e => e.hex) };
        } else if (showMapping) {
          layer = {
            labels: a.labels,
            colors: a.clusters.map((c, i) => entry(ui.preview != null && ui.selection.has(i) ? ui.preview : state.mapping[i])?.hex),
          };
        }
        let focus = null;
        if (ui.hover?.clusters) focus = { labels: a.labels, keep: ui.hover.clusters };
        else if (ui.hover?.codes) {
          if (layer && layer.labels !== a.labels) {
            const keep = ui.pipeline.palette.map((e, k) => (ui.hover.codes.has(e.code || PAPER) ? k : -1)).filter(k => k >= 0);
            focus = { labels: ui.pipeline.labels, keep };
          } else {
            focus = { labels: a.labels, keep: state.mapping.map((c, i) => (ui.hover.codes.has(c) ? i : -1)).filter(i => i >= 0) };
          }
        } else if (ui.spotlight && ui.selection.size && !ui.space) focus = { labels: a.labels, keep: ui.selection };
        view.render(layer, focus);
      });
    }

    function renderToolbar() {
      const n = h('input', { type: 'range', min: 4, max: 48, value: state.n, 'aria-label': 'Number of image colours' });
      const nOut = h('output', {}, String(state.n));
      n.addEventListener('input', () => { nOut.textContent = n.value; });
      n.addEventListener('change', () => { set({ n: +n.value }); ensureAnalysis(); });
      const k = h('input.num', { type: 'number', min: 1, max: 64, value: ui.k ?? Math.min(10, paletteCodes().length || 10), 'aria-label': 'Number of colours to pick' });
      k.addEventListener('change', () => { ui.k = +k.value; });
      const pickBtn = h('button', { title: 'Choose the k inventory colours that best cover the picture (pinned colours stay)', onclick: () => autoPick(+k.value, pickBtn) }, 'Auto-pick');
      const cw = h('input.num', { type: 'number', min: 0.2, max: 4, step: 0.1, value: state.quantize.chroma_weight, 'aria-label': 'Chroma weight' });
      cw.addEventListener('change', () => { const v = +cw.value; if (v > 0) set({ quantize: { ...state.quantize, chroma_weight: v } }); });
      const modes = [['mapping', 'Mapping', 'Every image colour in its assigned inventory colour'],
                     ['pipeline', 'Plot preview', 'The quantize step of the pipeline with this palette (nearest colour per pixel + noise removal)'],
                     ['original', 'Original', 'The picture as it is']];
      toolbar.replaceChildren(
        h('label.field', { title: 'How many colours the picture is reduced to before mapping' }, 'Image colours', n, nOut),
        h('div.group', {},
          h('button', { title: 'Map every image colour to its nearest owned inventory colour', onclick: () => edit({ mapping: mapToNearest(ownedEntries()) }) }, 'Nearest'),
          h('span.joined', {}, pickBtn, k)),
        h('div.group', {},
          h('button', { onclick: undo, disabled: !canUndo(), title: 'Undo (Ctrl+Z)', 'aria-label': 'Undo' }, '↶'),
          h('button', { onclick: redo, disabled: !canRedo(), title: 'Redo (Ctrl+Shift+Z)', 'aria-label': 'Redo' }, '↷')),
        h('label.field', { title: 'Colour distance = dL² + w·(da² + db²). Higher = hue and saturation matter more than lightness' }, 'Chroma weight', cw),
        h('div.segmented', { role: 'group', 'aria-label': 'View' }, modes.map(([id, txt, title]) =>
          h('button', { 'aria-pressed': String(ui.mode === id), title, onclick: () => setMode(id) }, txt))),
        h('label.check', {}, h('input', { type: 'checkbox', checked: ui.spotlight, onchange: e => {
          ui.spotlight = e.target.checked;
          storageSet('pbn.spotlight', ui.spotlight ? '1' : '0');
          renderImage();
        } }), 'Spotlight selection'));
    }

    function setMode(m) {
      ui.mode = m;
      storageSet('pbn.view', m);
      renderToolbar();
      renderImage();
      renderPalette();
      fetchPipeline();
    }

    function chip(r, nr) {
      const e = r.entry, paper = r.code === PAPER;
      const pipe = pipelineValid() && ui.mode === 'pipeline' ? ui.pipeline.palette.find(p => (p.code || PAPER) === r.code) : null;
      const el = h('div.chip', {
        class: [r.pinned && 'pinned', !r.clusters.length && 'unused', paper && 'paper'].filter(Boolean).join(' '),
        draggable: !paper, dataset: { code: r.code },
        title: `${paper ? '' : `${nr}. `}${e.code === PAPER ? '' : e.code + ' · '}${e.name} · ${e.hex}\n${r.clusters.length} image colours` +
          (paper ? '' : '\nDrag onto another colour to merge'),
      },
        h('div.chip-sw', { style: { background: e.hex, color: inkOn(e.hex) } }, paper ? '0' : String(nr)),
        h('div.chip-body', {},
          h('strong', {}, label(r.code)),
          h('span.muted', {}, pipe ? `${pipe.share_pct.toFixed(1)} % plot` : r.clusters.length ? pct(r.share) : 'unused')),
        paper ? null : h('div.chip-actions', {},
          h('button.icon', { class: r.pinned ? 'on' : null, 'aria-pressed': String(r.pinned), title: r.pinned ? 'Pinned: stays in the palette and is kept by auto-pick' : 'Pin', dataset: { act: 'pin' }, innerHTML: PIN_ICON }),
          h('button.icon', { title: 'Remove from palette (its image colours go to the nearest remaining colour)', dataset: { act: 'remove' } }, '×')));
      return el;
    }

    function renderPalette() {
      const { list, paper } = reducedPalette();
      const chips = list.map(r => chip(r, r.nr));
      if (paper.clusters.length) chips.push(chip(paper, 0));
      paletteBar.replaceChildren(
        h('div.pb-head', {},
          h('h2', {}, 'Reduced palette'),
          h('span.muted', {}, `${list.length} colours from ${clusters().length} image colours · painting order, 1 = lightest`),
          h('button.primary', { disabled: !list.length, onclick: () => go('result') }, 'Next: result →')),
        h('div.chips', {}, chips.length ? chips : h('p.muted', {}, 'No colours yet – use “Nearest” or “Auto-pick”.')));
    }

    function renderClusters() {
      const a = state.analysis;
      if (!a) { listEl.replaceChildren(h('p.muted', {}, 'Analysing…')); return; }
      const cl = a.clusters;
      const pal = reducedPalette().list;
      const nrOf = new Map(pal.map(r => [r.code, r.nr]));
      ui.order = cl.map(c => c.i);
      if (ui.sort === 'light') ui.order.sort((x, y) => cl[y].lab[0] - cl[x].lab[0]);
      if (ui.sort === 'target') ui.order.sort((x, y) => (nrOf.get(state.mapping[x]) ?? 999) - (nrOf.get(state.mapping[y]) ?? 999) || cl[y].share - cl[x].share);
      const maxShare = Math.max(...cl.map(c => c.share));
      listHead.replaceChildren(
        h('h2', {}, `Image colours`),
        h('select', { 'aria-label': 'Sort', onchange: e => { ui.sort = e.target.value; storageSet('pbn.sort', ui.sort); renderClusters(); } },
          [['share', 'by area'], ['light', 'by lightness'], ['target', 'by palette colour']].map(([v, t]) => h('option', { value: v, selected: ui.sort === v }, t))));
      listEl.replaceChildren(...ui.order.map(i => {
        const c = cl[i], code = state.mapping[i], e = entry(code) ?? PAPER_ENTRY;
        const d = nearest(c.lab, [e], 1)[0].d;
        return h('div.cl-row', {
          role: 'option', draggable: true, dataset: { i: String(i) }, 'aria-selected': String(ui.selection.has(i)),
          title: `Image colour ${c.hex} · ${pct(c.share)} of the picture\n→ ${label(code)} ${e.name} (Δ ${d.toFixed(1)})`,
        },
          h('span.sw', { style: { background: c.hex } }),
          h('span.share', {}, h('span.bar', { style: { width: `${(c.share / maxShare) * 100}%` } }), h('span', {}, pct(c.share))),
          h('span.arrow', { 'aria-hidden': 'true' }, '→'),
          h('span.sw.target', { style: { background: e.hex } }),
          h('span.code', {}, label(code)),
          h('span.delta', { class: d > 20 ? 'bad' : d > 10 ? 'warn' : null }, d.toFixed(1)));
      }));
    }

    function candTile(e, d, selHex, extra = {}) {
      const owned = e.code === PAPER || isOwned(e.code);
      return h('button.cand', {
        dataset: { code: e.code }, class: owned ? null : 'not-owned',
        title: `${label(e.code)} · ${e.name} · ${e.hex}${owned ? '' : ' (not owned)'}${d != null ? `\nΔ ${d.toFixed(1)}` : ''}`,
        ...extra,
      },
        h('span.split', {}, selHex ? h('span', { style: { background: selHex } }) : null, h('span', { style: { background: e.hex } })),
        h('span.cand-text', {}, h('strong', {}, label(e.code)), h('span.muted', {}, e.name)),
        d != null ? h('span.delta', {}, d.toFixed(1)) : null);
    }

    function searchBox(onInput) {
      const box = h('input.search', { type: 'search', placeholder: 'Search the inventory by code or name…', value: ui.search });
      box.addEventListener('input', debounce(() => { ui.search = box.value; onInput(); }, 150));
      return box;
    }

    function searchResults(lab, selHex) {
      const q = ui.search.trim().toLowerCase();
      if (!q) return null;
      const hits = state.inventory.entries.filter(e => `${e.code} ${e.name}`.toLowerCase().includes(q));
      const rows = lab ? nearest(lab, hits) : hits.map(e => ({ entry: e, d: null }));
      return h('div.cand-section', {}, h('h3', {}, `Search · ${hits.length}`),
        h('div.cand-grid', {}, rows.slice(0, 60).map(({ entry: e, d }) => candTile(e, d, selHex))));
    }

    function renderCandidates() {
      const sel = [...ui.selection].map(i => clusters()[i]).filter(Boolean);
      const inPalette = new Set(paletteCodes());
      const results = h('div');
      const fillSearch = () => results.replaceChildren(searchResults(sel.length ? meanLab(sel) : null, sel.length ? labHex(meanLab(sel)) : null) ?? '');

      if (!sel.length) {
        candPane.replaceChildren(
          h('div.pane-head', {}, h('h2', {}, 'Inventory')),
          h('p.muted', {}, 'Select image colours on the left or in the picture, then pick the inventory colour they should become. ' +
            'Drag image colours onto a palette colour to merge them; drag one palette colour onto another to merge both.'),
          searchBox(fillSearch), results);
        fillSearch();
        return;
      }
      const lab = meanLab(sel), selHex = labHex(lab);
      const share = sel.reduce((s, c) => s + c.share, 0);
      const pal = nearest(lab, [...inPalette].map(entry));
      const inv = nearest(lab, ownedEntries().filter(e => !inPalette.has(e.code)), ui.candLimit);
      const paperD = nearest(lab, [PAPER_ENTRY], 1)[0].d;
      const targets = new Set(sel.map(c => state.mapping[c.i]));
      const current = targets.size === 1 ? [...targets][0] : null;
      const mark = e => (e.code === current ? { 'aria-current': 'true' } : {});

      candPane.replaceChildren(
        h('div.pane-head', {},
          h('span.sel-sw', { style: { background: selHex } }),
          h('div.grow', {}, h('h2', {}, `${sel.length} image colour${sel.length > 1 ? 's' : ''} selected`),
            h('span.muted', {}, `${pct(share)} of the picture · now ${[...targets].map(label).join(', ')}`)),
          h('button.icon', { title: 'Clear selection (Esc)', 'aria-label': 'Clear selection', onclick: clearSelection }, '×')),
        pal.length ? h('div.cand-section', {}, h('h3', {}, 'In your palette'),
          h('div.cand-grid', {}, pal.slice(0, ui.palLimit).map(({ entry: e, d }) => candTile(e, d, selHex, mark(e)))),
          pal.length > ui.palLimit ? h('button.link', { onclick: () => { ui.palLimit = Infinity; renderCandidates(); } }, `Show all ${pal.length}`) : null) : null,
        h('div.cand-section', {}, h('h3', {}, 'Nearest in your inventory'),
          h('div.cand-grid', {}, inv.map(({ entry: e, d }) => candTile(e, d, selHex, mark(e))),
            candTile(PAPER_ENTRY, paperD, selHex, mark(PAPER_ENTRY))),
          ui.candLimit < 96 ? h('button.link', { onclick: () => { ui.candLimit *= 2; renderCandidates(); } }, 'Show more') : null),
        searchBox(fillSearch), results);
      fillSearch();
    }

    function renderSelection() {
      for (const row of listEl.children) row.setAttribute?.('aria-selected', String(ui.selection.has(+row.dataset.i)));
      renderCandidates();
      renderImage();
    }

    function renderAll() {
      renderToolbar();
      renderPalette();
      renderClusters();
      renderCandidates();
      renderImage();
      fetchPipeline();
    }

    // ---- analysis -------------------------------------------------------------------------

    async function ensureAnalysis() {
      const a = state.analysis;
      if (a && a.image === state.source.id && a.n === state.n) {
        if (state.mapping.length !== a.clusters.length) set({ mapping: initialMapping(a.clusters) });
        return;
      }
      await busy(root.querySelector('.mapping-grid'), async () => {
        const r = await api.clusters(state.source.id, state.n);
        const mapping = initialMapping(r.clusters);
        ui.selection = new Set();
        ui.anchor = null;
        resetHistory();
        set({ analysis: { ...r, image: state.source.id }, mapping });
      });
    }

    // ---- events ---------------------------------------------------------------------------

    const clusterAt = e => {
      const p = view.pixelAt(e);
      return p && state.analysis ? state.analysis.labels[p.i] : null;
    };

    let lastHover = null;
    view.canvas.addEventListener('pointermove', e => {
      const i = clusterAt(e);
      if (i == null) return;
      const c = clusters()[i], code = state.mapping[i], t = entry(code) ?? PAPER_ENTRY;
      view.showTip(e, h('div.tip', {},
        h('span.sw', { style: { background: c.hex } }), '→', h('span.sw', { style: { background: t.hex } }),
        h('strong', {}, label(code)), h('span', {}, pct(c.share))));
      if (i !== lastHover) {
        lastHover = i;
        ui.hover = { clusters: new Set([i]) };
        renderImage();
        listEl.querySelector('.cl-row.hover')?.classList.remove('hover');
        listEl.querySelector(`.cl-row[data-i="${i}"]`)?.classList.add('hover');
      }
    });
    view.canvas.addEventListener('pointerleave', () => {
      lastHover = null;
      ui.hover = null;
      view.showTip(null);
      listEl.querySelector('.cl-row.hover')?.classList.remove('hover');
      renderImage();
    });
    view.canvas.addEventListener('click', e => {
      const i = clusterAt(e);
      if (i == null) return;
      select(i, { ctrlKey: e.shiftKey || e.ctrlKey || e.metaKey });
      listEl.querySelector(`.cl-row[data-i="${i}"]`)?.scrollIntoView({ block: 'nearest' });
    });

    listEl.addEventListener('click', e => {
      const row = e.target.closest('.cl-row');
      if (row) select(+row.dataset.i, e);
    });
    listEl.addEventListener('pointerover', e => {
      const row = e.target.closest('.cl-row');
      const i = row ? +row.dataset.i : null;
      if (ui.hover?.clusters?.has(i) && ui.hover.clusters.size === 1) return;
      ui.hover = row ? { clusters: new Set([i]) } : null;
      renderImage();
    });
    listEl.addEventListener('pointerleave', () => { ui.hover = null; renderImage(); });
    listEl.addEventListener('dragstart', e => {
      const i = +e.target.closest('.cl-row').dataset.i;
      if (!ui.selection.has(i)) { ui.selection = new Set([i]); renderSelection(); }
      e.dataTransfer.setData(DRAG_CLUSTERS, JSON.stringify([...ui.selection]));
      e.dataTransfer.effectAllowed = 'move';
    });

    paletteBar.addEventListener('click', e => {
      const c = e.target.closest('.chip');
      if (!c) return;
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (act === 'pin') togglePin(c.dataset.code);
      else if (act === 'remove') removeColour(c.dataset.code);
      else if (ui.selection.size && !e.shiftKey && !(e.ctrlKey || e.metaKey) && ![...ui.selection].every(i => state.mapping[i] === c.dataset.code)) {
        assign(ui.selection, c.dataset.code);  // with a selection: assign it to this colour
      } else selectCodes(new Set([c.dataset.code]));
    });
    paletteBar.addEventListener('pointerover', e => {
      const c = e.target.closest('.chip');
      const code = c?.dataset.code;
      if (code ? ui.hover?.codes?.has(code) : !ui.hover) return;
      ui.hover = code ? { codes: new Set([code]) } : null;
      renderImage();
    });
    paletteBar.addEventListener('pointerleave', () => { ui.hover = null; renderImage(); });
    paletteBar.addEventListener('dragstart', e => {
      const c = e.target.closest('.chip');
      if (c) e.dataTransfer.setData(DRAG_CODE, c.dataset.code);
    });

    candPane.addEventListener('click', e => {
      const t = e.target.closest('.cand');
      if (!t) return;
      if (ui.selection.size) assign(ui.selection, t.dataset.code);
      else if (t.dataset.code !== PAPER) {
        const pinned = new Set(state.pinned).add(t.dataset.code);
        edit({ pinned });
        toast(`Pinned ${t.dataset.code} to the palette`);
      }
    });
    candPane.addEventListener('pointerover', e => {
      const code = e.target.closest('.cand')?.dataset.code ?? null;
      const want = ui.selection.size ? code : null;
      if (want === ui.preview) return;
      ui.preview = want;
      renderImage();
    });
    candPane.addEventListener('pointerleave', () => { if (ui.preview != null) { ui.preview = null; renderImage(); } });

    // drop targets: palette chips and candidate tiles
    for (const zone of [paletteBar, candPane]) {
      zone.addEventListener('dragover', e => {
        const t = e.target.closest('.chip, .cand');
        const types = e.dataTransfer.types;
        if (t && (types.includes(DRAG_CLUSTERS) || (types.includes(DRAG_CODE) && t.classList.contains('chip')))) {
          e.preventDefault();
          zone.querySelector('.drop-target')?.classList.remove('drop-target');
          t.classList.add('drop-target');
        }
      });
      zone.addEventListener('dragleave', e => e.target.closest?.('.chip, .cand')?.classList.remove('drop-target'));
      zone.addEventListener('drop', e => {
        const t = e.target.closest('.chip, .cand');
        if (!t) return;
        e.preventDefault();
        t.classList.remove('drop-target');
        const ids = e.dataTransfer.getData(DRAG_CLUSTERS), code = e.dataTransfer.getData(DRAG_CODE);
        if (ids) assign(new Set(JSON.parse(ids)), t.dataset.code);
        else if (code) merge(code, t.dataset.code);
      });
    }

    const typing = e => e.target.closest?.('input, select, textarea');
    const onKey = e => {
      if (typing(e)) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); }
      else if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); }
      else if (e.key === 'Escape') clearSelection();
      else if (e.key === ' ' && !e.repeat) { e.preventDefault(); ui.space = true; renderImage(); }
    };
    const onKeyUp = e => { if (e.key === ' ') { ui.space = false; renderImage(); } };
    window.addEventListener('keydown', onKey);
    window.addEventListener('keyup', onKeyUp);

    const off = subscribe(p => {
      if ('analysis' in p) { renderClusters(); }
      if ('mapping' in p || 'pinned' in p || 'quantize' in p || 'analysis' in p) {
        renderToolbar();
        renderPalette();
        renderClusters();
        renderCandidates();
        renderImage();
        fetchPipeline();
      }
    });

    renderAll();
    view.ready.then(renderImage).catch(() => toast('Could not load the picture', 'error'));
    ensureAnalysis();

    return () => {
      off();
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('keyup', onKeyUp);
      cancelAnimationFrame(frame);
    };
  },
};
