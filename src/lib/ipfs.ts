// IPFS helpers (env-driven)
const IPFS_API = import.meta.env.VITE_IPFS_API?.replace(/\/$/, '') || 'http://127.0.0.1:5001'
const IPFS_GATEWAY = import.meta.env.VITE_IPFS_GATEWAY?.replace(/\/$/, '') || 'https://ipfs.io'

export function gatewayUrl(cid: string, path?: string) {
  const suffix = path ? `/${path.replace(/^\//,'')}` : ''
  return `${IPFS_GATEWAY}/ipfs/${cid}${suffix}`
}

export async function cat(cid: string, path?: string) {
  const url = `${IPFS_API}/api/v0/cat?arg=${encodeURIComponent(`/ipfs/${cid}${path?'/'+path.replace(/^\/+/,''):''}`)}`
  const res = await fetch(url, { credentials: 'omit' })
  if (!res.ok) throw new Error(`IPFS cat failed: ${res.status}`)
  return res.text()
}
