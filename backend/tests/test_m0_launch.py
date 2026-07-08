import os, sys, importlib
from pathlib import Path

def test_data_dir_honors_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CBM_DATA_DIR", str(tmp_path / "cbm"))
    import backend.database as db
    importlib.reload(db)
    assert db.DATA_DIR == tmp_path / "cbm"

def test_running_profile_has_no_vnc_fields():
    from backend.browser_manager import RunningProfile
    fields = RunningProfile.__dataclass_fields__
    assert "display" not in fields and "ws_port" not in fields
