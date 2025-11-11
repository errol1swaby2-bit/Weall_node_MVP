set -euo pipefail

APP="weall_node/main.py"; [ -f "$APP" ] || APP="main.py"

python3 - "$APP" <<'PY'
import sys, io

p = sys.argv[1]
with io.open(p, "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

# Preserve any shebang/encoding header at file top
i = 0
while i < len(lines) and (lines[i].startswith("#!") or "coding" in lines[i][:40] or lines[i].strip() == ""):
    i += 1

# Collect all future-import lines anywhere in the file
future_lines = []
rest = []
for idx, line in enumerate(lines):
    if line.lstrip().startswith("from __future__ import "):
        if line not in future_lines:
            future_lines.append(line)
    else:
        rest.append(line)

# Rebuild: [shebang/encoding/blank]* + future imports + the rest (ensuring one blank line after future)
head = lines[:i]
body = rest[i:] if i < len(rest) else []
# Remove any leading blank lines from body (we'll add a single blank later)
while body and body[0].strip() == "":
    body.pop(0)

new_lines = head + future_lines
if new_lines and (not new_lines[-1].endswith("\n")):
    new_lines[-1] += "\n"
# add exactly one blank line after futures section
if future_lines:
    new_lines.append("\n")
new_lines += body

with io.open(p, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print(f"✅ Fixed future import placement in {p}")
PY
