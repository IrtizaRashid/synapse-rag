"""OTP email delivery.

Priority:
  1. Resend REST API   (RESEND_API_KEY set)
  2. SMTP relay        (SMTP_HOST set)
  3. Dev mode          (explicit ALLOW_DEV_OTP=true only)

`send_otp_email` returns True when delivery succeeded via a real channel.
False means no email was delivered.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

import httpx

OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "180"))
APP_NAME = os.getenv("APP_NAME", "Synapse")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
MAIL_FROM = os.getenv("EMAIL_FROM", os.getenv("MAIL_FROM", "Synapse <onboarding@resend.dev>")).strip()
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()

log = logging.getLogger("auth.email")

_MAX_OTP_ATTEMPTS = int(os.getenv("MAX_OTP_ATTEMPTS", "3"))


def send_otp_email(email: str, code: str, purpose: str) -> bool:
    """Returns True when sent via a real channel, False otherwise."""
    if RESEND_API_KEY:
        if _send_via_resend(email, code, purpose):
            return True
    if SMTP_HOST:
        if _send_via_smtp(email, code, purpose):
            return True
    log.warning("No OTP email channel delivered a code for %s (purpose=%s)", email, purpose)
    return False


def _build_html(code: str, purpose: str) -> str:
    is_reset = purpose == "reset"
    heading = "Reset your password" if is_reset else "Verify your email"
    intro = (
        "We received a request to reset the password for your account."
        if is_reset
        else f"Use this code to finish securing your {APP_NAME} account."
    )
    return f"""<!doctype html><html><body style="margin:0;background:#eee7dc;font-family:Inter,Arial,sans-serif;padding:32px 12px;color:#211b24">
<div style="max-width:480px;margin:auto;background:#f5eee3;border:1px solid #cfc2b3;border-radius:18px;padding:32px;color:#211b24">
<div style="width:46px;height:46px;border-radius:12px;background:linear-gradient(135deg,#6d28d9,#8b5cf6);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:20px;color:#fff;margin-bottom:18px">{APP_NAME[0]}</div>
<h1 style="font-size:22px;margin:0 0 8px">{heading}</h1>
<p style="color:#6d6570;margin:0 0 22px;line-height:1.55">{intro}</p>
<p style="color:#6d6570;margin:0 0 10px">Your verification code is:</p>
<div style="background:#eee7dc;border:1px solid #cfc2b3;border-radius:12px;padding:18px;text-align:center;letter-spacing:8px;font-size:30px;font-weight:800;color:#6d28d9">{code}</div>
<p style="color:#6d6570;font-size:13px;margin:22px 0 0;line-height:1.55">This code expires in {max(1, OTP_TTL_SECONDS // 60)} minutes. After {_MAX_OTP_ATTEMPTS} incorrect attempts you must request a new code. If you did not request this, you can safely ignore this email.</p>
</div></body></html>"""


def _build_text(code: str, purpose: str) -> str:
    heading = "Reset your password" if purpose == "reset" else "Verify your email"
    return (
        f"{heading}\n\n"
        f"Your {APP_NAME} verification code is: {code}\n\n"
        f"This code expires in {max(1, OTP_TTL_SECONDS // 60)} minutes. "
        f"After {_MAX_OTP_ATTEMPTS} incorrect attempts you must request a new code.\n\n"
        "If you did not request this, you can safely ignore this email.\n"
    )


def _send_via_resend(email: str, code: str, purpose: str = "signup") -> bool:
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={"from": MAIL_FROM, "to": [email], "subject": "Reset your password" if purpose == "reset" else f"Verify your {APP_NAME} account",
                  "html": _build_html(code, purpose), "text": _build_text(code, purpose)},
            timeout=20,
        )
        if r.status_code == 200:
            log.info("Resend email sent to %s", email)
            return True
        log.warning("Resend failed (%s): %s", r.status_code, r.text)
    except Exception as exc:  # pragma: no cover
        log.warning("Resend raised: %s", exc)
    return False


def _send_via_smtp(email: str, code: str, purpose: str = "signup") -> bool:
    msg = EmailMessage()
    msg["Subject"] = "Reset your password" if purpose == "reset" else f"Verify your {APP_NAME} account"
    msg["From"] = MAIL_FROM
    msg["To"] = email
    msg.set_content(_build_text(code, purpose))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True
    except Exception as exc:  # pragma: no cover
        log.warning("SMTP send failed: %s", exc)
        return False
