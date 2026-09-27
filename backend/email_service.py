"""Configured-recipient, approval-gated SMTP delivery for KAVACH drafts."""
from __future__ import annotations

import os
import re
import smtplib
from email.message import EmailMessage
from typing import Any


def _settings() -> dict[str, Any]:
    host = os.getenv("KAVACH_EMAIL_HOST", "smtp.gmail.com").strip()
    try:
        port = int(os.getenv("KAVACH_EMAIL_PORT", "465"))
    except ValueError:
        port = 0
    user = os.getenv("KAVACH_EMAIL_USER", "").strip()
    password = os.getenv("KAVACH_EMAIL_APP_PASSWORD", "").strip()
    secure = os.getenv("KAVACH_EMAIL_SECURE", "true").casefold() in {"1", "true", "yes", "on"}
    enabled = os.getenv("KAVACH_EMAIL_ENABLED", "false").casefold() in {"1", "true", "yes", "on"}
    recipients = {dept: os.getenv(f"KAVACH_{dept}_EMAIL", "").strip() for dept in ("POLICE", "HOSPITAL", "FIRE", "TRAFFIC", "MUNICIPAL")}
    return {"host": host, "port": port, "user": user, "password": password, "secure": secure, "enabled": enabled, "recipients": recipients}


def email_provider_status() -> dict[str, Any]:
    settings = _settings()
    configured = bool(settings["host"] and 1 <= settings["port"] <= 65535 and settings["user"] and settings["password"])
    has_recipient = any(settings["recipients"].values())
    state = "NOT_CONFIGURED" if not configured or not has_recipient else "READY" if settings["enabled"] else "CONFIGURED"
    return {"provider": "Gmail SMTP" if settings["host"] == "smtp.gmail.com" else "SMTP", "status": state, "configured": configured, "enabled": settings["enabled"], "recipientsConfigured": has_recipient, "secure": settings["secure"], "host": settings["host"], "port": settings["port"], "reason": "Set backend SMTP app password, sender, and at least one approved recipient" if not configured or not has_recipient else "Set KAVACH_EMAIL_ENABLED=true to allow approved sends" if not settings["enabled"] else None}


def configured_recipient(department: str) -> str | None:
    address = _settings()["recipients"].get(department.upper())
    if address and re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", address):
        return address
    return None


def send_configured_email(department: str, recipient: str, subject: str, body: str) -> dict[str, Any]:
    settings = _settings()
    allowed_recipient = configured_recipient(department)
    if not settings["enabled"]:
        return {"status": "BLOCKED", "provider": "Gmail SMTP", "reason": "KAVACH_EMAIL_ENABLED is false"}
    if not settings["user"] or not settings["password"] or not allowed_recipient:
        return {"status": "NOT_CONFIGURED", "provider": "Gmail SMTP", "reason": "Sender credentials or approved department recipient are missing"}
    if recipient.casefold() != allowed_recipient.casefold():
        return {"status": "BLOCKED", "provider": "Gmail SMTP", "reason": "Recipient is not the configured department recipient"}
    message = EmailMessage()
    message["From"] = settings["user"]
    message["To"] = allowed_recipient
    message["Subject"] = subject[:200]
    message.set_content(body[:12000])
    try:
        if settings["secure"]:
            smtp = smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=10)
        else:
            smtp = smtplib.SMTP(settings["host"], settings["port"], timeout=10)
        with smtp:
            if not settings["secure"]:
                smtp.starttls()
            smtp.login(settings["user"], settings["password"])
            refused = smtp.send_message(message)
        if refused:
            return {"status": "FAILED", "provider": "Gmail SMTP", "reason": "SMTP server refused one or more recipients"}
        return {"status": "SENT", "provider": "Gmail SMTP", "acceptedBySmtp": True, "deliveryVerified": False}
    except Exception as exc:
        return {"status": "FAILED", "provider": "Gmail SMTP", "reason": f"SMTP operation failed ({type(exc).__name__})", "acceptedBySmtp": False, "deliveryVerified": False}
