"""M0 spike: exact Host-allowlist + loopback `cbm_ui` cookie auth.

CBM_UI_SECRET is set per-test via `monkeypatch.setenv` (scoped) rather than
at module level, so it never leaks into other test modules sharing this
pytest session — AuthMiddleware reads it fresh from os.environ per request.
"""
from __future__ import annotations

import pytest
from fastapi import WebSocketDisconnect
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
    assert "samesite=strict" in setc.lower()


def test_ws_cdp_rejects_cleanly_instead_of_crashing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
):
    """Regression: _check_cbm_cookie must not crash on WebSocket scopes.

    It used to build a `starlette.requests.Request(scope)`, whose `__init__`
    asserts `scope["type"] == "http"` — raising AssertionError for every
    WebSocket connection (CDP/VNC) once CBM_UI_SECRET is set. It must instead
    reject cleanly (WebSocketDisconnect with the auth-failure close code)
    rather than crash.
    """
    monkeypatch.setenv("CBM_UI_SECRET", "test-secret")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/api/profiles/test-profile/cdp", headers={"Host": "localhost"}
        ):
            pass
    assert exc_info.value.code == 4401
