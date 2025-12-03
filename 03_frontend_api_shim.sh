#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$HOME/Weall_node_MVP}"
cd "$ROOT/frontend"

echo "==[03] Frontend API shim =="

mkdir -p src/lib
cat > src/lib/api.ts <<'TS'
const envUrl = (import.meta as any).env?.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

export const API_BASE = envUrl.replace(/\/+$/,'');

export async function api<T=any>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path.startsWith('/')? '': '/'}${path}`;
  const res = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers||{}) }});
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}
TS

# Example usage wiring (no-op if already using your own)
grep -q "WeAll — Local Dev" src/main.tsx 2>/dev/null && \
cat > src/main.tsx <<'TSX'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { api } from './lib/api'

function App(){
  const [status,setStatus] = React.useState<string>('…checking');
  React.useEffect(()=>{
    api('/api/health').then(
      (j:any)=>setStatus(j?.status||'ok'),
      ()=>setStatus('backend not reachable')
    );
  },[]);
  return (
    <div style={{padding:'1rem',fontFamily:'system-ui'}}>
      <h1>WeAll — Local Dev</h1>
      <p>Proxy: <code>/api → 127.0.0.1:8000</code></p>
      <p>Health: <b>{status}</b></p>
    </div>
  )
}
ReactDOM.createRoot(document.getElementById('root')!).render(<App/>)
TSX

echo "[✓] API shim added"
