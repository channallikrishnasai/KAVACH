"""Authentication provider boundary; local demo identity is explicitly untrusted."""
from __future__ import annotations

from typing import Any


class AuthProvider:
    name = "AuthProvider"

    def getStatus(self) -> dict[str, Any]:
        raise NotImplementedError


class DemoAuthProvider(AuthProvider):
    name = "DemoAuthProvider"

    def getStatus(self) -> dict[str, Any]:
        return {"provider": self.name, "status": "DEMO_ONLY", "authenticated": False, "identityVerified": False, "role": "COMMANDER", "label": "DEMO AUTHENTICATION · NOT AN IDENTITY", "mode": "SIMULATED"}


class RealAuthProvider(AuthProvider):
    name = "RealAuthProvider"

    def getStatus(self) -> dict[str, Any]:
        return {"provider": self.name, "status": "NOT_CONFIGURED", "authenticated": False, "identityVerified": False, "role": None, "mode": "UNAVAILABLE", "error": "No trusted identity provider is integrated"}


demo_auth_provider = DemoAuthProvider()
real_auth_provider = RealAuthProvider()


def auth_status() -> dict[str, Any]:
    return {"mode": demo_auth_provider.getStatus(), "real": real_auth_provider.getStatus()}
