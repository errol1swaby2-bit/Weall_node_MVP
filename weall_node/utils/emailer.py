import logging
import re
import os
import os, smtplib, ssl, logging
from email.mime.text import MIMEText
from pathlib import Path

log = logging.getLogger("emailer")

# --- Load .env from project root explicitly ---
try:
    from dotenv import load_dotenv

    DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(DOTENV_PATH, override=False)
    log.info("Loaded .env from %s", DOTENV_PATH)
except Exception as e:
    log.warning("dotenv load skipped: %s", e)

# --- Read SMTP env (single source of truth) ---
SMTP_HOST = os.getenv("SMTP_HOST") or ""
SMTP_PORT = int(os.getenv("SMTP_PORT") or 0)
SMTP_USER = os.getenv("SMTP_USER") or ""
SMTP_PASS = os.getenv("SMTP_PASS") or ""
SMTP_FROM = os.getenv("SMTP_FROM") or ""

try:
    masked_user = (SMTP_USER[:2] + "***" + SMTP_USER[-2:]) if SMTP_USER else ""
    log.info(
        "SMTP env check — host=%r port=%r user=%r from=%r",
        SMTP_HOST,
        SMTP_PORT,
        masked_user,
        SMTP_FROM,
    )
except Exception:
    pass


def _connect():
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS and SMTP_FROM):
        raise RuntimeError(
            "SMTP not configured: ensure SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM are set"
        )
    # SSL 465 or STARTTLS 587
    if SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
        server.login(SMTP_USER, SMTP_PASS)
        return server
    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
    server.ehlo()
    try:
        server.starttls(context=ssl.create_default_context())
    except smtplib.SMTPNotSupportedError:
        pass
    server.login(SMTP_USER, SMTP_PASS)
    return server


def send_email(to_addr: str, subject: str, body: str, bcc_self: bool = False) -> bool:
        if os.getenv("WEALL_DEV_EMAIL") == "1":
          body_str = ""
          try: body_str = str(locals().get("body") or locals().get("message") or "")
          except Exception: pass
          m = re.search(r"\b(\d{6})\b", body_str)
          code = m.group(1) if m else "000000"
          logging.warning("DEV_EMAIL ECHO: to=%s subject=%s code=%s body=%r", str(locals().get("to")), str(locals().get("subject")), code, body_str)
          return True
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to_addr

        rcpts = [to_addr]
        if bcc_self:
            rcpts.append(SMTP_USER)

        with _connect() as s:
            s.sendmail(SMTP_FROM, rcpts, msg.as_string())
        log.info("Email sent to %s", to_addr)
        return True
    except Exception as e:
        log.error("Email send failed to %s: %s", to_addr, e)
        raise


def send_verification_code(to_addr: str, code: str, minutes_valid: int = 10) -> bool:
        if os.getenv("WEALL_DEV_EMAIL") == "1":
          body_str = ""
          try: body_str = str(locals().get("body") or locals().get("message") or "")
          except Exception: pass
          m = re.search(r"\b(\d{6})\b", body_str)
          code = m.group(1) if m else "000000"
          logging.warning("DEV_EMAIL ECHO: to=%s subject=%s code=%s body=%r", str(locals().get("to")), str(locals().get("subject")), code, body_str)
          return True
    subject = "WeAll Tier-1 verification code"
    body = (
        f"Your WeAll Tier-1 verification code is:\n"
        f"{code}\n\n"
        f"This code expires in {minutes_valid} minutes.\n"
        f"If you did not request this, you can ignore this email."
    )
    return send_email(to_addr, subject, body, bcc_self=False)
