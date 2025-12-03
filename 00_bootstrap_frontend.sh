#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$HOME/Weall_node_MVP}"
cd "$ROOT"

echo "==[00] Bootstrap frontend at $ROOT =="

# Ensure Node is present (Termux-friendly)
if ! command -v node >/dev/null 2>&1; then
  echo "[*] Installing Node (Termux). If not on Termux, install Node via your OS."
  if command -v pkg >/dev/null 2>&1; then
    pkg update -y && pkg install -y nodejs
  else
    echo "Please install Node.js manually and rerun."; exit 1
  fi
fi

# Create frontend if missing
if [ ! -d "frontend" ] || [ ! -f "frontend/package.json" ]; then
  echo "[*] Initializing Vite React TS in ./frontend"
  mkdir -p frontend
  npx --yes create-vite@latest frontend -- --template react-ts
fi

cd frontend

# Ensure deps installed
if [ ! -d "node_modules" ]; then
  echo "[*] Installing frontend deps"
  npm install
fi

# Ensure package.json scripts are sane & idempotent
node - <<'NODE'
const fs=require('fs');
const pjPath='package.json';
const pj=JSON.parse(fs.readFileSync(pjPath,'utf8'));
pj.scripts = Object.assign({
  dev: "vite",
  build: "tsc -b && vite build",
  preview: "vite preview --strictPort --port 4173"
}, pj.scripts||{});
fs.writeFileSync(pjPath, JSON.stringify(pj,null,2));
console.log("[*] package.json scripts ensured");
NODE

# Create vite.config.ts with /api proxy -> 127.0.0.1:8000
cat > vite.config.ts <<'TS'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false
      }
    }
  },
  preview: {
    port: 4173,
    strictPort: true
  }
})
TS

# Minimal src wiring (safe no-op if already present)
mkdir -p src
[ -f src/main.tsx ] || cat > src/main.tsx <<'TSX'
import React from 'react'
import ReactDOM from 'react-dom/client'

function App(){
  return (
    <div style={{padding:'1rem',fontFamily:'system-ui'}}>
      <h1>WeAll — Local Dev</h1>
      <p>Frontend is live. <code>/api/*</code> is proxied to <code>127.0.0.1:8000</code>.</p>
    </div>
  )
}
ReactDOM.createRoot(document.getElementById('root')!).render(<App/>)
TSX

[ -f index.html ] || cat > index.html <<'HTML'
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>WeAll — Local Dev</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
HTML

echo "[✓] Frontend bootstrapped/verified"
