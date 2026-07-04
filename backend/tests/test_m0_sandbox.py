"""M0 Task 6: verify --no-sandbox is actually stripped from the launched browser.

A unit test on `_build_fingerprint_args` alone would prove nothing here: that
method never emitted `--no-sandbox` in the first place. There are two
independent real sources, both external to the Manager's own arg-building:

1. cloakbrowser's `get_default_stealth_args()` unconditionally includes
   `--no-sandbox`, injected by `launch_persistent_context_async()` whenever
   it's called without `stealth_args=False`.
2. Playwright's OWN Chromium launcher (`_innerDefaultArgs()` in the driver)
   pushes `--no-sandbox` by default unless `chromium_sandbox=True` is passed
   explicitly — completely independent of cloakbrowser/stealth_args.

Confirmed empirically during M0 Task 6: passing stealth_args=False alone
was NOT sufficient — `ps aux` still showed --no-sandbox on the launched
Chromium's command line via source (2). Both flags must be set. So the
meaningful assertion is on the *kwargs actually passed to the library call*
— that's the boundary where the flag is (or isn't) suppressed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import backend.browser_manager as bm
from backend import database as db


@pytest.mark.asyncio
async def test_launch_disables_no_sandbox_sources(tmp_db, monkeypatch: pytest.MonkeyPatch):
    """BrowserManager.launch() must neutralize BOTH sources of --no-sandbox:
    stealth_args=False (cloakbrowser's own defaults) AND chromium_sandbox=True
    (Playwright's own defaults, forwarded via **kwargs)."""
    profile = db.create_profile(name="Sandbox Test", fingerprint_seed=12345, platform="macos")

    fake_context = MagicMock()
    fake_context.add_init_script = AsyncMock()
    fake_context.pages = []
    mock_launch = AsyncMock(return_value=fake_context)
    monkeypatch.setattr(bm, "launch_persistent_context_async", mock_launch)

    mgr = bm.BrowserManager()
    await mgr.launch(profile)

    mock_launch.assert_awaited_once()
    call_kwargs = mock_launch.call_args.kwargs
    assert call_kwargs["stealth_args"] is False
    assert call_kwargs["chromium_sandbox"] is True


@pytest.mark.asyncio
async def test_launch_stealth_args_false_does_not_lose_fingerprint(
    tmp_db, monkeypatch: pytest.MonkeyPatch
):
    """Guard against the regression this change could cause: turning off
    cloakbrowser's stealth_args also turns off its --fingerprint and
    --fingerprint-platform defaults. That's only safe because the Manager
    already supplies its own equivalents unconditionally (DB defaults
    guarantee fingerprint_seed/platform are always set) — assert they're
    still present in the args actually passed to the library."""
    profile = db.create_profile(name="Fingerprint Test", fingerprint_seed=54321, platform="macos")

    fake_context = MagicMock()
    fake_context.add_init_script = AsyncMock()
    fake_context.pages = []
    mock_launch = AsyncMock(return_value=fake_context)
    monkeypatch.setattr(bm, "launch_persistent_context_async", mock_launch)

    mgr = bm.BrowserManager()
    await mgr.launch(profile)

    call_kwargs = mock_launch.call_args.kwargs
    passed_args = call_kwargs["args"]
    assert "--fingerprint=54321" in passed_args
    assert "--fingerprint-platform=macos" in passed_args
    # Never our job to emit this — confirms it isn't sneaking back in via extra_args.
    assert "--no-sandbox" not in passed_args


def test_build_fingerprint_args_platform_falls_back_to_windows():
    """Regression guard for the fallback lost when stealth_args=False was
    introduced: cloakbrowser's own stealth_args default used to always inject
    --fingerprint-platform, masking a falsy `platform` on the profile. With
    stealth_args=False that safety net is gone, so _build_fingerprint_args
    itself must fall back to "windows" whenever platform is None, missing,
    or an empty string — otherwise a profile saved via
    PUT /api/profiles/{id} with {"platform": null} would launch with no
    platform spoof at all."""
    mgr = bm.BrowserManager()

    args = mgr._build_fingerprint_args({"fingerprint_seed": 1, "platform": None})
    assert "--fingerprint-platform=windows" in args

    args = mgr._build_fingerprint_args({"fingerprint_seed": 1})
    assert "--fingerprint-platform=windows" in args

    args = mgr._build_fingerprint_args({"fingerprint_seed": 1, "platform": ""})
    assert "--fingerprint-platform=windows" in args


@pytest.mark.asyncio
async def test_launch_scrubs_no_sandbox_from_launch_args(tmp_db, monkeypatch: pytest.MonkeyPatch):
    """launch_args is user-supplied (PUT /api/profiles/{id}) and forwarded
    straight to Chromium. If it contains --no-sandbox, that would defeat the
    chromium_sandbox=True fix above and reopen the sandbox-OFF RCE risk.
    Confirm it's scrubbed regardless of source, while unrelated user flags
    still pass through."""
    profile = db.create_profile(
        name="Launch Args Sandbox Test",
        fingerprint_seed=24680,
        launch_args=["--no-sandbox", "--some-other-flag"],
    )

    fake_context = MagicMock()
    fake_context.add_init_script = AsyncMock()
    fake_context.pages = []
    mock_launch = AsyncMock(return_value=fake_context)
    monkeypatch.setattr(bm, "launch_persistent_context_async", mock_launch)

    mgr = bm.BrowserManager()
    await mgr.launch(profile)

    passed_args = mock_launch.call_args.kwargs["args"]
    assert "--some-other-flag" in passed_args
    assert "--no-sandbox" not in passed_args
