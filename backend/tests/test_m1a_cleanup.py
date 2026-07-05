import asyncio
import os
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

def test_cleanup_stale_does_not_kill_substring_match_outside_user_data_dir(tmp_db):
    """A process merely mentioning the profiles path (grep, an editor, pytest itself)
    must NOT be killed — only a real --user-data-dir= argument counts."""
    profiles_root = str((bm.db.DATA_DIR / "profiles").resolve())
    grep_proc = MagicMock()
    grep_proc.info = {"cmdline": ["grep", "-r", f"{profiles_root}/abc"]}
    with patch("psutil.process_iter", return_value=[grep_proc]):
        asyncio.run(bm.BrowserManager().cleanup_stale())
    grep_proc.kill.assert_not_called()

def test_cleanup_stale_skips_own_pid(tmp_db):
    """Even if a future flag made our own cmdline match, we must never self-kill."""
    profiles_root = str((bm.db.DATA_DIR / "profiles").resolve())
    self_proc = MagicMock()
    self_proc.pid = os.getpid()
    self_proc.info = {"cmdline": ["Chromium", f"--user-data-dir={profiles_root}/abc"]}
    with patch("psutil.process_iter", return_value=[self_proc]):
        asyncio.run(bm.BrowserManager().cleanup_stale())
    self_proc.kill.assert_not_called()
