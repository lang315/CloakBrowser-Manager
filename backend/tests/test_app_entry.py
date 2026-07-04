import os
from desktop.app_entry import sanitize_frozen_env, pick_port

def test_sanitize_removes_meipass(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123/lib:/usr/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib")
    monkeypatch.setattr("sys._MEIPASS", "/tmp/_MEI123", raising=False)
    sanitize_frozen_env()
    assert "/tmp/_MEI123" not in os.environ.get("LD_LIBRARY_PATH", "")

def test_pick_port_is_free():
    p = pick_port()
    assert 1024 < p < 65536
