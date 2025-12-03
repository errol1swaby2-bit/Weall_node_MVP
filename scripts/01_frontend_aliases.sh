set -euo pipefail

# Ensure tsconfig has baseUrl + paths
jq '.compilerOptions.baseUrl="." |
     .compilerOptions.paths={"@/*":["src/*"]}' \
  tsconfig.json > tsconfig.json.tmp && mv tsconfig.json.tmp tsconfig.json

# Vite alias
apply_vite() {
  f="vite.config.ts"
  if [ -f "$f" ]; then
    if ! grep -q "resolve:" "$f"; then
      perl -0777 -pe 's/export default defineConfig\(\{([\s\S]*?)\}\);/export default defineConfig({\1,\n  resolve: { alias: { "@": fileURLToPath(new URL(".\/src", import.meta.url)) } }\n});/s' -i "$f"
      sed -i '1i import { fileURLToPath, URL } from "node:url";' "$f"
    fi
  fi
}
apply_vite

# Add typecheck script
if [ -f package.json ]; then
  jq '.scripts.typecheck="tsc --noEmit"' package.json > package.json.tmp && mv package.json.tmp package.json
fi

echo "✅ Frontend aliases set (@/*) and typecheck script added."
