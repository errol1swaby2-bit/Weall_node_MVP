#!/usr/bin/env bash
set -euo pipefail

# We patch both helpers if they exist; no-op if a file is missing.

# --- Patch utils/emailer.py ---
FILE="weall_node/utils/emailer.py"
if [ -f "$FILE" ]; then
  cp -f "$FILE" "$FILE.bak.$(date +%s)"
  # ensure imports
  grep -q '^import os$' "$FILE" || sed -i '1i import os' "$FILE"
  grep -q '^import re$' "$FILE" || sed -i '1i import re' "$FILE"
  grep -q '^import logging$' "$FILE" || sed -i '1i import logging' "$FILE"

  # wrap any send function to dev-echo
  # This inserts a guard right after any "def send" line.
  sed -i -E '/^def[[:space:]]+send.*\(/a\
    \ \ \ \ if os.getenv("WEALL_DEV_EMAIL") == "1":\
    \ \ \ \ \ \ body_str = ""\
    \ \ \ \ \ \ try: body_str = str(locals().get("body") or locals().get("message") or "")\
    \ \ \ \ \ \ except Exception: pass\
    \ \ \ \ \ \ m = re.search(r"\\b(\\d{6})\\b", body_str)\
    \ \ \ \ \ \ code = m.group(1) if m else "000000"\
    \ \ \ \ \ \ logging.warning("DEV_EMAIL ECHO: to=%s subject=%s code=%s body=%r", str(locals().get("to")), str(locals().get("subject")), code, body_str)\
    \ \ \ \ \ \ return True' "$FILE"
  echo "[patched] $FILE"
fi

# --- Patch utils/email_utils.py ---
FILE="weall_node/utils/email_utils.py"
if [ -f "$FILE" ]; then
  cp -f "$FILE" "$FILE.bak.$(date +%s)"
  grep -q '^import os$' "$FILE" || sed -i '1i import os' "$FILE"
  grep -q '^import re$' "$FILE" || sed -i '1i import re' "$FILE"
  grep -q '^import logging$' "$FILE" || sed -i '1i import logging' "$FILE"

  # try to catch common helpers like send_email / send_verification / send_code
  sed -i -E '/^def[[:space:]]+(send_email|send_verification.*|send_code.*)\(/a\
    \ \ \ \ if os.getenv("WEALL_DEV_EMAIL") == "1":\
    \ \ \ \ \ \ body_str = ""\
    \ \ \ \ \ \ try: body_str = str(locals().get("body") or locals().get("message") or locals().get("text") or "")\
    \ \ \ \ \ \ except Exception: pass\
    \ \ \ \ \ \ m = re.search(r"\\b(\\d{6})\\b", body_str)\
    \ \ \ \ \ \ code = m.group(1) if m else "000000"\
    \ \ \ \ \ \ logging.warning("DEV_EMAIL ECHO: to=%s subject=%s code=%s body=%r", str(locals().get("to") or locals().get("email")), str(locals().get("subject","(no-subject)")), code, body_str)\
    \ \ \ \ \ \ return True' "$FILE"
  echo "[patched] $FILE"
fi

# Ensure the dev flag is exported when you run the server
RUN="bin/run_api_dev.sh"
if [ -f "$RUN" ]; then
  cp -f "$RUN" "$RUN.bak.$(date +%s)"
  grep -q 'WEALL_DEV_EMAIL=1' "$RUN" || sed -i '1iexport WEALL_DEV_EMAIL=1' "$RUN"
  echo "[patched] $RUN (export WEALL_DEV_EMAIL=1)"
fi

echo "[✓] DEV email echo enabled. Codes will print to api.log as: DEV_EMAIL ECHO: ..."
