import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
import backend.browser_manager as bm

def test_cleanup_stale_kills_only_our_chromium(tmp_db, monkeypatch):
    profiles_root = str(bm.db.DATA_DIR / "profiles")
    ours = MagicMock(); ours.info = {"cmdline": ["Chromium", f"--user-data-dir={profiles_root}/abc"]}
    users = MagicMock(); users.info = {"cmdline": ["Google Chrome", "--user-data-dir=/Users/x/Library/Chrome"]}
    with patch("psutil.process_iter", return_value=[ours, users]):
        asyncio.run(bm.BrowserManager().cleanup_stale())
    ours.kill.assert_called_once()
    users.kill.assert_not_called()

def test_cleanup_stale_deletes_singleton_locks(tmp_db):
    d = bm.db.DATA_DIR / "profiles" / "abc"; d.mkdir(parents=True)
    lock = d / "SingletonLock"; lock.write_text("x")
    with patch("psutil.process_iter", return_value=[]):
        asyncio.run(bm.BrowserManager().cleanup_stale())
    assert not lock.exists()
