"""M1a Task 6: auto_launch_all staggers launches and survives individual failures."""
import asyncio
from unittest.mock import AsyncMock, patch
import backend.browser_manager as bm


def test_autolaunch_staggers_and_survives_failures(tmp_db):
    import backend.database as db
    db.create_profile("a", auto_launch=True)
    db.create_profile("b", auto_launch=True)
    mgr = bm.BrowserManager()
    calls = []
    async def fake_launch(p):
        calls.append(p["name"])
        if p["name"] == "a": raise RuntimeError("boom")
    with patch.object(mgr, "launch", new=AsyncMock(side_effect=fake_launch)), \
         patch.object(bm.asyncio, "sleep", new=AsyncMock()) as slept:
        asyncio.run(mgr.auto_launch_all())
    assert set(calls) == {"a", "b"}      # b still launched despite a failing
    assert slept.await_count >= 1        # staggered
