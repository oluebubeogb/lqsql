const H = { 'x-lqsql': '1' };
// Set by the server in index.html: '' at the domain root, '/lqsql' when ROOT_PATH is used.
export const BASE = (typeof window !== 'undefined' && window.__ROOT_PATH__) || '';
const A = `${BASE}/api/`;

export class ApiError extends Error {
  constructor(msg, status, data) { super(msg); this.status = status; this.data = data; }
}

async function handle(r) {
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    if (r.status === 401 && !location.hash.startsWith('#/login')) window.dispatchEvent(new Event('lqsql:logout'));
    throw new ApiError((data && data.error) || r.statusText || 'Request failed', r.status, data);
  }
  return data;
}

const qs = (p) => Object.entries(p || {}).filter(([, v]) => v !== undefined && v !== null && v !== '')
  .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');

export const api = {
  get: (path, params) => fetch(`${A}${path}${params ? '?' + qs(params) : ''}`, { credentials: 'same-origin' }).then(handle),
  send: (method, path, body) => fetch(`${A}${path}`, {
    method, credentials: 'same-origin', headers: { ...H, 'content-type': 'application/json' }, body: JSON.stringify(body || {}),
  }).then(handle),
  post: (path, body) => api.send('POST', path, body),
  patch: (path, body) => api.send('PATCH', path, body),
  upload: (path, form) => fetch(`${A}${path}`, { method: 'POST', credentials: 'same-origin', headers: H, body: form }).then(handle),
  url: (path, params) => `${A}${path}?${qs(params)}`,
  // NDJSON streaming (import progress)
  async stream(path, { body, form, onEvent }) {
    const r = await fetch(`${A}${path}`, {
      method: 'POST', credentials: 'same-origin',
      headers: form ? H : { ...H, 'content-type': 'application/json' },
      body: form || JSON.stringify(body),
    });
    if (!r.ok) return handle(r);
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
        if (line) onEvent(JSON.parse(line));
      }
    }
    if (buf.trim()) onEvent(JSON.parse(buf));
  },
  async download(path, body, fallbackName) {
    const r = await fetch(`${A}${path}`, { method: 'POST', credentials: 'same-origin', headers: { ...H, 'content-type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) return handle(r);
    const cd = r.headers.get('content-disposition') || '';
    const m = /filename="([^"]+)"/.exec(cd);
    const blob = await r.blob();
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = m ? m[1] : fallbackName;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  },
};

export const fmtNum = (n) => (n === null || n === undefined ? '—' : Number(n).toLocaleString());
export function fmtBytes(b) {
  if (b === null || b === undefined) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; let v = Number(b);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v < 10 && i ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
}
