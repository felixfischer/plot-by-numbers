// App shell: step navigation (hash routing) and mounting of the current step.

import { steps } from './steps/index.js';
import { state, subscribe } from './store.js';
import { h } from './dom.js';

const nav = document.querySelector('.steps');
const view = document.getElementById('view');
let current = null, unmount = null;

/** A step can be visited once all steps before it are ready. */
const reachable = i => steps.slice(0, i).every(s => s.ready(state));

function renderNav() {
  nav.replaceChildren(...steps.map((s, i) => {
    const ok = reachable(i);
    return h(ok ? 'a' : 'span', {
      class: ['step', s === current && 'active', s.ready(state) && 'done', !ok && 'locked'].filter(Boolean).join(' '),
      href: ok ? `#${s.id}` : null,
      'aria-current': s === current ? 'step' : null,
    }, h('span.step-nr', {}, String(i + 1)), h('span.step-title', {}, s.title));
  }));
}

function route() {
  const want = location.hash.slice(1);
  let i = Math.max(0, steps.findIndex(s => s.id === want));
  while (i > 0 && !reachable(i)) i--;
  const step = steps[i];
  if (location.hash.slice(1) !== step.id) history.replaceState(null, '', `#${step.id}`);
  if (step !== current) {
    unmount?.();
    current = step;
    view.replaceChildren();
    view.dataset.step = step.id;
    unmount = step.mount(view) ?? null;
    window.scrollTo(0, 0);
  }
  renderNav();
}

window.addEventListener('hashchange', route);
subscribe(renderNav);
route();
