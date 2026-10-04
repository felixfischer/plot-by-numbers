// Step 4: the reduced palette – checked with the real quantize step, then downloaded or
// saved into a project (new, or the opened one) for `python -m pbn run`.

import { api } from '../api.js';
import { h, busy, toast, download, go } from '../dom.js';
import { state } from '../store.js';
import { inkOn } from '../color.js';
import { exportPalette, paletteCodes, reducedPalette } from '../model.js';
import { ImageView } from '../components/image-view.js';

const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'picture';

function command(text) {
  const copy = h('button.icon', {
    title: 'Copy', 'aria-label': 'Copy command',
    onclick: () => navigator.clipboard?.writeText(text).then(() => toast('Copied')),
  }, '⧉');
  return h('div.command', {}, h('code', {}, text), copy);
}

function paletteTable(rows) {
  return h('table.palette-table', {},
    h('thead', {}, h('tr', {}, ['Nr', 'Colour', 'Code', 'Name', 'Hex', 'Plot share'].map(t => h('th', {}, t)))),
    h('tbody', {}, rows.map(r => h('tr', { class: r.code ? null : 'paper' },
      h('td.num', {}, String(r.nr)),
      h('td', {}, h('span.sw.big', { style: { background: r.hex, color: inkOn(r.hex) }, title: 'palette colour' }),
        r.hex_mean ? h('span.sw.mean', { style: { background: r.hex_mean }, title: `average of its pixels: ${r.hex_mean}` }) : null),
      h('td', {}, h('strong', {}, r.code || '—')),
      h('td', {}, r.name),
      h('td.mono', {}, r.hex),
      h('td.num', {}, `${r.share_pct.toFixed(1)} %`)))));
}

function warnings(rows) {
  const w = [];
  for (const r of rows) {
    if (r.undrawable) w.push(`${r.code}: the plotter font has no glyph for “${r.undrawable}” – add it to pbn/font.py or rename the code.`);
    if (r.code && r.share_pct === 0) w.push(`${r.code} is not used by the plot: every pixel is closer to another palette colour.`);
  }
  return w.length ? h('ul.warnings', {}, w.map(t => h('li', {}, t))) : null;
}

export default {
  id: 'result',
  title: 'Result',
  ready: s => !!s.analysis && paletteCodes().length > 0,

  mount(el) {
    const palette = exportPalette();
    const src = state.source;
    const view = new ImageView({ width: src.width, height: src.height, src: api.imageUrl(src.id) });
    const tableSlot = h('div', {}, h('p.muted', {}, 'Running the quantize step…'));
    const out = h('div.saved');
    const preview = h('div.card.result-preview', {},
      h('div.compare', {},
        h('figure', {}, h('img', { src: api.imageUrl(src.id), alt: 'Original' }), h('figcaption', {}, 'Original')),
        h('figure', {}, view.el, h('figcaption', {}, 'Plot preview (quantize step, reduced size)'))));

    const name = h('input', { type: 'text', value: slug(state.project ? `${state.project.name}-${palette.length}` : src.name), 'aria-label': 'Project name' });
    const createBtn = h('button.primary', {
      onclick: () => busy(createBtn, async () => {
        const r = await api.createProject({ name: name.value, image: src.id, palette, quantize: state.quantize });
        toast(`Created ${r.path}`);
        out.replaceChildren(h('p', {}, 'Saved. Run the rest of the pipeline:'), command(`python -m pbn run ${r.path}`));
      }),
    }, 'Create project');

    const updateBtn = state.project && h('button', {
      onclick: () => {
        if (!confirm(`Overwrite ${state.project.palette_file} with these ${palette.length} colours?`)) return;
        busy(updateBtn, async () => {
          await api.savePalette(state.project.path, palette);
          toast(`Updated ${state.project.palette_file}`);
          out.replaceChildren(h('p', {}, 'Saved. Rerun from the quantize step:'), command(`python -m pbn run ${state.project.path} --from quantize`));
        });
      },
    }, `Update ${state.project.palette_file}`);

    const cwNote = state.project && state.project.quantize.chroma_weight !== state.quantize.chroma_weight
      ? h('p.note', {}, `Chroma weight is ${state.quantize.chroma_weight} here but ${state.project.quantize.chroma_weight} in the project TOML – set [quantize] chroma_weight there to plot what you see.`)
      : null;

    const { list } = reducedPalette();
    el.append(h('section.page.wide', {},
      h('div.page-head', {},
        h('div', {}, h('h1', {}, 'Reduced palette'),
          h('p.lead', {}, `${list.length} colours, numbered in painting order (1 = lightest). Paper white stays blank.`)),
        h('button', { onclick: () => go('mapping') }, '← Back to mapping')),
      h('div.result-grid', {},
        preview,
        h('div', {},
          h('div.card', {}, tableSlot),
          h('div.card', {},
            h('h2', {}, 'Use it'),
            h('div.actions', {},
              h('button', { onclick: () => download(`${slug(src.name)}-palette.json`, JSON.stringify(palette, null, 2) + '\n') }, 'Download palette JSON'),
              updateBtn),
            h('label.field.stack', {}, 'New project in projects/', h('span.joined', {}, name, createBtn)),
            cwNote, out,
            h('p.muted.small', {}, 'Regions, vectors and the plot itself run in the CLI for now.'))))));

    busy(preview, async () => {
      const r = await api.quantize(src.id, palette, state.quantize);
      await view.ready;
      view.render({ labels: r.labels, colors: r.palette.map(e => e.hex) });
      const rows = [...r.palette].sort((a, b) => (a.nr || 1e9) - (b.nr || 1e9));
      tableSlot.replaceChildren(paletteTable(rows), warnings(rows) ?? '');
    });
  },
};
