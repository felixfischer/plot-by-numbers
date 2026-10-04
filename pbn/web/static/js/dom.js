// Tiny DOM helpers: h() builds elements, toast() reports, busy() wraps async work.

export function h(tag, props = {}, ...children) {
  const [name, ...classes] = tag.split('.');
  const el = document.createElement(name || 'div');
  if (classes.length) el.className = classes.join(' ');
  for (const [k, v] of Object.entries(props ?? {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className += (el.className ? ' ' : '') + v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k in el && !k.includes('-')) el[k] = v;  // properties (value, checked, textContent, …)
    else el.setAttribute(k, v === true ? '' : v);
  }
  el.append(...children.flat(Infinity).filter(c => c != null && c !== false));
  return el;
}

export function toast(msg, kind = 'info') {
  const el = h(`div.toast.${kind}`, { role: kind === 'error' ? 'alert' : 'status' }, msg);
  document.getElementById('toasts').append(el);
  setTimeout(() => el.classList.add('out'), kind === 'error' ? 6000 : 3000);
  setTimeout(() => el.remove(), kind === 'error' ? 6400 : 3400);
}

/** Run fn while `el` shows a spinner; errors become toasts. Returns fn's result or undefined. */
export async function busy(el, fn) {
  el?.classList.add('busy');
  try {
    return await fn();
  } catch (err) {
    toast(err.message, 'error');
    console.error(err);
  } finally {
    el?.classList.remove('busy');
  }
}

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export const pct = x => `${(x * 100).toFixed(x < 0.01 ? 2 : 1)} %`;

export function download(filename, text, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  h('a', { href: url, download: filename }).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Go to a step by id (used by "Next" buttons). */
export function go(id) {
  location.hash = id;
}
