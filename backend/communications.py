"""Approval-gated outbound communication adapters.

The local adapter only records an event. n8n delivery is disabled unless an
operator configures a fixed environment URL and explicitly enables it.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class LocalWebhookProvider:
    name = "LOCAL_EVENT_WEBHOOK"

    def send(self, event: dict[str, Any]) -> dict[str, Any]:
        return {"provider": self.name, "status": "RECORDED_LOCALLY", "externalDelivery": False, "event": event}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class N8NWebhookProvider:
    name = "N8N_WEBHOOK"

    @staticmethod
    def configured() -> bool:
        # No trusted identity integration exists in this build. Never let a
        # caller-supplied role label authorize an external side effect.
        return False

    def send(self, event: dict[str, Any]) -> dict[str, Any]:
        url = os.getenv("N8N_WEBHOOK_URL", "").strip()
        if not self.configured():
            return LocalWebhookProvider().send(event)
        body = json.dumps(event, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "KAVACH-local-demo/1.0"}, method="POST")
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=5) as response:
                return {"provider": self.name, "status": "DELIVERED", "http_status": response.status, "externalDelivery": True}
        except urllib.error.HTTPError as exc:
            return {"provider": self.name, "status": "FAILED", "http_status": exc.code, "externalDelivery": False}
        except Exception as exc:
            return {"provider": self.name, "status": "FAILED", "error": type(exc).__name__, "externalDelivery": False}


def _valid_webhook_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme == "https" and host:
            return True
        return parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        return False


def send_approved_event(event: dict[str, Any]) -> dict[str, Any]:
    if N8NWebhookProvider.configured():
        return N8NWebhookProvider().send(event)
    return LocalWebhookProvider().send(event)


def communication_status() -> dict[str, Any]:
    return {
        "provider": "LOCAL_EVENT_WEBHOOK",
        "status": "BLOCKED_AUTH_NOT_IMPLEMENTED",
        "external_delivery_enabled": False,
        "source": "KAVACH local audit event",
        "reason": "External delivery remains blocked until authenticated identity and trusted authorization are implemented",
    }
