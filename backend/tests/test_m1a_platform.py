"""M1a Task 2: host-OS --fingerprint-platform default + platform_detectable."""

import backend.database as db
import backend.browser_manager as bm


def test_host_platform_matches_runtime():
    import sys
    expected = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
    assert db.host_platform() == expected


def test_new_profile_defaults_to_host_platform(tmp_db):
    p = db.create_profile("t")
    assert p["platform"] == db.host_platform()


def test_fingerprint_uses_host_when_platform_missing():
    args = bm.BrowserManager()._build_fingerprint_args({"fingerprint_seed": 1, "platform": None})
    assert f"--fingerprint-platform={db.host_platform()}" in args
