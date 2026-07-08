"""Cross-platform single-instance file lock."""
import sys
from pathlib import Path

def acquire(lock_path: Path):
    """Return a held lock handle, or None if another process holds it.
    Keep the returned handle alive for the app's lifetime."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f
