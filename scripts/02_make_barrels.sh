set -euo pipefail
shopt -s globstar nullglob
for d in src/components src/pages src/hooks src/lib src/store; do
  [ -d "$d" ] || continue
  if [ ! -f "$d/index.ts" ] && [ ! -f "$d/index.tsx" ]; then
    # Create a lazy export-all; devs can refine later.
    echo 'export * from "./";' > "$d/index.ts"
  fi
done
echo "✅ Added missing index.ts barrel files where absent."
