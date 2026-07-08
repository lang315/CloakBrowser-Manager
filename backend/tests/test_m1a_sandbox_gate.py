# backend/tests/test_m1a_sandbox_gate.py
from unittest.mock import AsyncMock, patch
import backend.browser_manager as bm

def _launch_kwargs(monkeypatch, container=False, env=None):
    if env is not None: monkeypatch.setenv("CBM_CONTAINER", env)
    elif container: monkeypatch.setenv("CBM_CONTAINER", "1")
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
    assert k and k.get("stealth_args") is True and "chromium_sandbox" not in k

def test_container_env_falsy_zero_selects_desktop(monkeypatch, tmp_db):
    """CBM_CONTAINER=0 must NOT be treated as a truthy container signal — a
    strict allow-list check (not bool(str)) is required so this selects desktop
    (sandbox stays ON) instead of silently disabling the sandbox."""
    k = _launch_kwargs(monkeypatch, env="0")
    assert k.get("stealth_args") is False and k.get("chromium_sandbox") is True
