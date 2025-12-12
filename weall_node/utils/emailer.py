"""
weall_node.utils.emailer
---------------------------------
Simple SMTP-based email helper for WeAll.

- Reads SMTP_* settings from the project .env.
- Provides:
    - send_email(...)
    - send_verification_code(...)
- Supports a DEV mode to avoid actually sending emails while
  still surfacing the verification code in logs.

Usage notes
-----------
Set the following env vars (usually via .env at project root):

    SMTP_HOST
    SMTP_PORT
    SMTP_USER
    SMTP_PASS
    SMTP_FROM

Optional dev helpers:

    WEALL_DEV_EMAIL=1   -> do not send, just log the email and any 6-digit code
"""

import logging
import os
import re
import smtplib
import ssl
from email.mime.text import MIMEText
from pathlib import Path

log = logging.getLogger("emailer")

# --- Load .env from project root explicitly (best effort) ---
try:
    from dotenv import load_dotenv

    DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(DOTENV_PATH, override=False)
    log.info("Loaded .env from %s", DOTENV_PATH)
except Exception as e:  # pragma: no cover - non-critical
    log.warning("dotenv load skipped: %s", e)

# --- Read SMTP env (single source of truth) ---
SMTP_HOST = os.getenv("SMTP_HOST") or ""
SMTP_PORT = int(os.getenv("SMTP_PORT") or 0)
SMTP_USER = os.getenv("SMTP_USER") or ""
SMTP_PASS = os.getenv("SMTP_PASS") or ""
SMTP_FROM = os.getenv("SMTP_FROM") or ""

try:  # pragma: no cover - logging only
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
    """
    Create and return an authenticated SMTP client.

    Uses SSL when port == 465, otherwise tries STARTTLS.
    """
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS and SMTP_FROM):
        raise RuntimeError(
            "SMTP not configured: ensure SMTP_HOST, SMTP_PORT, "
            "SMTP_USER, SMTP_PASS, SMTP_FROM are set"
        )

    # SSL 465 or STARTTLS 587/other
    if SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
        server.login(SMTP_USER, SMTP_PASS)
        return server

    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
    server.ehlo()
    try:
        server.starttls(context=ssl.create_default_context())
    except smtplib.SMTPNotSupportedError:
        # Some dev/test SMTP daemons don't support STARTTLS.
        pass
    server.login(SMTP_USER, SMTP_PASS)
    return server


def _dev_echo_email(to_addr: str, subject: str, body: str) -> bool:
    """
    In dev mode, don't actually send email.

    Instead, log key details plus any 6-digit code in the body.
    This is controlled via WEALL_DEV_EMAIL=1.
    """
    body_str = str(body or "")
    m = re.search(r"\b(\d{6})\b", body_str)
    code = m.group(1) if m else "000000"

    # Use the module logger, not root.
    log.warning(
        "DEV_EMAIL ECHO: to=%s subject=%s code=%s body_preview=%r",
        to_addr,
        subject,
        code,
        body_str[:256],  # avoid log spam
    )
    return True


def send_email(to_addr: str, subject: str, body: str, bcc_self: bool = False) -> bool:
    """
    Send a plain-text email.

    Returns True on success, raises on hard failure.

    In dev mode (WEALL_DEV_EMAIL=1) this will *not* talk to SMTP
    and will instead log a DEV_EMAIL ECHO message with any
    6-digit code discovered in the body.
    """
    if os.getenv("WEALL_DEV_EMAIL") == "1":
        return _dev_echo_email(to_addr, subject, body)

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to_addr

        rcpts = [to_addr]
        if bcc_self:
            rcpts.append(SMTP_USER or SMTP_FROM)

        with _connect() as s:
            s.sendmail(SMTP_FROM, rcpts, msg.as_string())

        log.info("Email sent to %s", to_addr)
        return True
    except Exception as e:  # pragma: no cover - depends on SMTP env
        log.error("Email send failed to %s: %s", to_addr, e)
        raise


def send_verification_code(to_addr: str, code: str, minutes_valid: int = 10) -> bool:
    """
    Convenience helper for Tier-1 verification emails.

    This just builds a standard verification email and passes it
    through send_email(), so dev mode behavior is inherited.
    """
    subject = "WeAll Tier-1 verification code"
    body = (
        "Your WeAll Tier-1 verification code is:\n"
        f"{code}\n\n"
        f"This code expires in {minutes_valid} minutes.\n"
        "If you did not request this, you can ignore this email."
    )
    return send_email(to_addr, subject, body, bcc_self=False)
