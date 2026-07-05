# backend/tests/test_m1a_sandbox_gate.py
from unittest.mock import AsyncMock, patch
import backend.browser_manager as bm

def _launch_kwargs(monkeypatch, container):
    if container: monkeypatch.setenv("CBM_CONTAINER", "1")
    else: monkeypatch.delenv("CBM_CONTAINER", raising=False)
    mgr = bm.BrowserManager()
    with patch.object(bm, "launch_persistent_context_async", new=AsyncMock()) as m:
        import asyncio
        try: asyncio.run(mgr.launch({"id": "x", "user_data_dir": "/tmp/x", "fingerprint_seed": 1}))
        except Exception: pass
        return m.call_args.kwargs if m.call_args else {}

def test_desktop_default_sandbox_on(monkeypatch, tmp_db):
    k = _launch_kwargs(monkeypatch, container=False)
    assert k.get("stealth_args") is False and k.get("chromium_sandbox") is True

def test_container_keeps_no_sandbox(monkeypatch, tmp_db):
    k = _launch_kwargs(monkeypatch, container=True)
    assert k.get("stealth_args") is not False  # library default (adds --no-sandbox)
