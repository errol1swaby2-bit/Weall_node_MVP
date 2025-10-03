#!/usr/bin/env python3
"""
Apply custom WeAll patch format (fixed for root-level files).
"""

import os
import sys

PATCH_FILE = "weall_prod_patch.patch"

if not os.path.exists(PATCH_FILE):
    print(f"Patch file '{PATCH_FILE}' not found!")
    sys.exit(1)

current_file = None
writing = False
buffer = []

with open(PATCH_FILE, "r") as f:
    for line in f:
        line = line.rstrip("\n")
        if line.startswith("*** Add File:") or line.startswith("*** Update File:"):
            # flush previous buffer
            if current_file and buffer:
                dir_name = os.path.dirname(current_file)
                if dir_name:
                    os.makedirs(dir_name, exist_ok=True)
                with open(current_file, "w") as outf:
                    outf.write("\n".join(buffer) + "\n")
                print(f"Applied {current_file}")
            # start new file
            current_file = line.split(":", 1)[1].strip()
            buffer = []
            writing = True
            continue
        elif line.startswith("*** End Patch"):
            # flush last file
            if current_file and buffer:
                dir_name = os.path.dirname(current_file)
                if dir_name:
                    os.makedirs(dir_name, exist_ok=True)
                with open(current_file, "w") as outf:
                    outf.write("\n".join(buffer) + "\n")
                print(f"Applied {current_file}")
            current_file = None
            buffer = []
            writing = False
            continue
        elif line.startswith("*** Begin Patch"):
            continue
        # collect lines for current file
        if writing and current_file:
            # remove leading '+' if present (patch format)
            if line.startswith("+") and not line.startswith("++"):
                line = line[1:]
            buffer.append(line)

print("Patch applied successfully.")
