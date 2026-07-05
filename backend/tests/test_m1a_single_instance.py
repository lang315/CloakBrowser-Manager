"""M1a Task 4: cross-platform single-instance file lock."""
from pathlib import Path
from backend.single_instance import acquire


def test_second_acquire_fails(tmp_path):
    p = tmp_path / "app.lock"
    h1 = acquire(p)
    assert h1 is not None
    h2 = acquire(p)
    assert h2 is None  # second instance refused
