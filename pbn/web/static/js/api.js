// fetch wrappers for the JSON API (pbn/web/app.py). Errors carry the server's message.

async function req(method, url, body, headers = {}) {
  const opt = { method, headers: { ...headers } };
  if (body instanceof Blob) opt.body = body;
  else if (body !== undefined) {
    opt.body = JSON.stringify(body);
    opt.headers['content-type'] = 'application/json';
  }
  const r = await fetch(url, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
  return data;
}

const q = params => new URLSearchParams(params).toString();

export function decodeLabels(b64) {
  const s = atob(b64), a = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i);
  return a;
}

export const api = {
  // source image
  projects: () => req('GET', '/api/projects'),
  projectThumb: path => `/api/projects/thumb?${q({ path })}`,
  openProject: path => req('POST', '/api/projects/open', { path }),
  uploadImage: file => req('POST', '/api/images', file, { 'x-filename': encodeURIComponent(file.name) }),
  imageUrl: id => `/api/images/${id}/work.png`,

  // inventory
  inventories: () => req('GET', '/api/inventories'),
  inventory: id => req('GET', `/api/inventories/get?${q({ id })}`),
  uploadInventory: (name, filename, text) => req('POST', '/api/inventories', { name, filename, text }),

  // colour mapping
  async clusters(id, n) {
    const r = await req('GET', `/api/images/${id}/clusters?${q({ n })}`);
    return { ...r, labels: decodeLabels(r.labels) };
  },
  pick: (id, body) => req('POST', `/api/images/${id}/pick`, body),
  async quantize(id, palette, quantize) {
    const r = await req('POST', `/api/images/${id}/quantize`, { palette, quantize });
    return { ...r, labels: decodeLabels(r.labels) };
  },

  // result
  createProject: body => req('POST', '/api/projects', body),
  savePalette: (path, palette) => req('PUT', '/api/projects/palette', { path, palette }),
};
