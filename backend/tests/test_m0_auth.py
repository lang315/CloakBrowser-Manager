"""M0 spike: exact Host-allowlist + loopback `cbm_ui` cookie auth.

CBM_UI_SECRET is set per-test via `monkeypatch.setenv` (scoped) rather than
at module level, so it never leaks into other test modules sharing this
pytest session — AuthMiddleware reads it fresh from os.environ per request.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture()
def client():
    """Fresh TestClient per test — avoids a shared cookie jar leaking the
    `cbm_ui` cookie set by one test into another."""
    return TestClient(app, base_url="http://localhost")


def test_rejects_bad_host(client: TestClient):
    r = client.get("/api/status", headers={"Host": "127.0.0.1.evil.com"})
    assert r.status_code == 403


def test_api_requires_cookie(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CBM_UI_SECRET", "test-secret")
    r = client.get("/api/profiles", headers={"Host": "localhost"})
    assert r.status_code == 401


def test_index_sets_httponly_cookie_without_secure(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CBM_UI_SECRET", "test-secret")
    r = client.get("/", headers={"Host": "localhost"})
    setc = r.headers.get("set-cookie", "")
    assert "cbm_ui=" in setc and "HttpOnly" in setc and "Secure" not in setc
