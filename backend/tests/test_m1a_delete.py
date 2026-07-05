# backend/tests/test_m1a_delete.py
from pathlib import Path
from backend.main import _rmtree_with_retry  # new helper

def test_rmtree_retry_eventually_removes(tmp_path):
    d = tmp_path / "p"; d.mkdir(); (d / "f").write_text("x")
    _rmtree_with_retry(d, attempts=3, delay=0.01)
    assert not d.exists()

def test_rmtree_retry_raises_on_persistent_failure(tmp_path, monkeypatch):
    import shutil, pytest
    d = tmp_path / "p"; d.mkdir()  # must exist, else _rmtree_with_retry's exists() guard short-circuits
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError):
        _rmtree_with_retry(d, attempts=2, delay=0.01)
