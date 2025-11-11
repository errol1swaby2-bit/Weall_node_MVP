// Minimal fetch wrapper that always carries cookies and prefixes API base
const API_BASE = import.meta.env.VITE_API_BASE?.replace(/\/$/, '') || ''

type Json = Record<string, any>

async function request(path: string, opts: RequestInit = {}) {
  const url = path.startsWith('http') ? path : API_BASE + path
  const res = await fetch(url, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    },
    credentials: 'include', // << important for HttpOnly cookie sessions
  })
  if (!res.ok) {
    let text = await res.text().catch(()=> '')
    try { const j = JSON.parse(text); text = (j as any).detail || (j as any).error || text } catch {}
    throw new Error(text || `HTTP ${res.status}`)
  }
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return res.json()
  return res.text()
}

export const api = {
  get: (path: string) => request(path),
  post: (path: string, body: Json) => request(path, { method: 'POST', body: JSON.stringify(body) }),
  del:  (path: string) => request(path, { method: 'DELETE' }),
}
