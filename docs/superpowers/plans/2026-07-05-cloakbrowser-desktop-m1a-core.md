# CloakBrowser Desktop — M1a (Usable Core, Unsigned) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Complete the de-VNC + harden the launch lifecycle so the native desktop app is a usable, crash-resilient single-user core (unsigned) — orphan cleanup, host-OS fingerprint default, single-instance safety, safe profile deletion, and a container-safe sandbox gate.

**Architecture:** Builds on M0 (branch `feature/desktop-native-app`, commits `a66ade1..0f6af42`). M0 already delivered: per-OS `DATA_DIR` (T1), the frozen entrypoint (T2), loopback cookie + Host-allowlist (T3), the PyInstaller bundle (T4), and the native sandboxed launch with `--no-sandbox` stripped (T5/T6). M1a finishes the launch-lifecycle backend work that M0 stubbed or deferred. No signing, no frontend rebuild (that's M1c), no CDP-proxy opt-in (that's M1b).

**Tech Stack:** Python 3.12, FastAPI, `cloakbrowser`, `psutil` (new — cross-platform process/lock cleanup), pytest.

## Global Constraints

*(From the spec + M0 findings — every task implicitly includes these.)*
- **Orphan/lock cleanup identifies OUR processes ONLY by our `user_data_dir` path (`<DATA_DIR>/profiles/<id>`), NEVER by process name** — the binary is literally `Chromium`; a name match would kill the user's Chrome + every Electron app.
- **Sandbox ON on desktop** (M0 strips `--no-sandbox` via `stealth_args=False` + `chromium_sandbox=True`). The container path must stay able to keep `--no-sandbox` — gate on an explicit `CBM_CONTAINER` marker; **desktop is the default**.
- **Host-OS `--fingerprint-platform` default** — never silently default a Mac to `windows` (detectable GPU/font/UA mismatch). Cross-OS spoofing stays possible but is flagged `detectable`.
- **Single local user, loopback only.** Two instances on one `profiles.db` = data corruption → must be prevented.
- Run tests via `./.venv/bin/python -m pytest ...`. Baseline: **192 passed**.

---

## Task 1: Rewrite `cleanup_stale` — orphan Chromium + stale Singleton locks (by user_data_dir, never name)

**Files:**
- Modify: `backend/requirements.txt` (add `psutil>=6.0`)
- Modify: `backend/browser_manager.py` (`cleanup_stale`, currently a no-op stub)
- Test: `backend/tests/test_m1a_cleanup.py`

**Interfaces:**
- Produces: `BrowserManager.cleanup_stale()` (async) kills only Chromium processes whose command line contains our `<DATA_DIR>/profiles` path, and deletes `Singleton{Lock,Cookie,Socket}` under each `profiles/<id>/`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_m1a_cleanup.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_cleanup.py -v`
Expected: FAIL — `cleanup_stale` is a no-op; `psutil` not imported.

- [ ] **Step 3: Add psutil + implement**

Add `psutil>=6.0` to `backend/requirements.txt`, then `./.venv/bin/python -m pip install "psutil>=6.0"`. Replace `cleanup_stale` in `browser_manager.py`:

```python
async def cleanup_stale(self):
    """Kill orphaned Chromium from a prior run + delete stale singleton locks.
    Identifies OUR processes ONLY by our profiles dir in the command line —
    NEVER by process name (the binary is named 'Chromium')."""
    import psutil
    profiles_root = str(db.DATA_DIR / "profiles")
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            if any(profiles_root in str(a) for a in cmdline):
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    for lock in Path(profiles_root).glob("*/Singleton*"):
        lock.unlink(missing_ok=True)
```
Ensure `from . import database as db` and `from pathlib import Path` are imported.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_cleanup.py backend/tests -q`
Expected: PASS (new tests + full suite green).

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/browser_manager.py backend/tests/test_m1a_cleanup.py
git commit -m "feat(m1a): cleanup_stale kills orphan Chromium by user_data_dir + clears singleton locks"
```

---

## Task 2: Host-OS `--fingerprint-platform` default + `detectable` flag

**Files:**
- Modify: `backend/models.py:16` (`ProfileCreate.platform` default), `:77` (`ProfileResponse.platform`)
- Modify: `backend/database.py` (host-OS default in `create_profile`)
- Modify: `backend/browser_manager.py` (`_build_fingerprint_args` already falls back to `"windows"` from M0 — change the fallback to host-OS; expose whether the chosen platform mismatches the host)
- Test: `backend/tests/test_m1a_platform.py`

**Interfaces:**
- Produces: `backend.database.host_platform() -> str` returning `"macos"`/`"windows"`/`"linux"` for the host; new profiles default their `platform` to it; `get_status`/profile responses include `platform_detectable: bool` (True when the profile's platform ≠ host).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_m1a_platform.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_platform.py -v`
Expected: FAIL — `host_platform` undefined; default is `"windows"`.

- [ ] **Step 3: Implement**

In `backend/database.py` add:
```python
def host_platform() -> str:
    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
```
In `create_profile`, change the platform default from `fields.get("platform", "windows")` to `fields.get("platform") or host_platform()`. In `backend/models.py`, change `ProfileCreate.platform` default from `"windows"` to `None` (so the DB layer applies the host default) — keep the `Literal[...] | None` type. In `browser_manager.py` `_build_fingerprint_args`, change the M0 fallback `p = profile.get("platform") or "windows"` to `p = profile.get("platform") or db.host_platform()`. Add `platform_detectable` (`profile["platform"] != host_platform()`) to the dict `get_status` returns and to `ProfileResponse`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_platform.py backend/tests -q`
Expected: PASS. (Update any existing test that asserted a `"windows"` default to expect `host_platform()`.)

- [ ] **Step 5: Commit**

```bash
git add backend/models.py backend/database.py backend/browser_manager.py backend/tests/test_m1a_platform.py
git commit -m "feat(m1a): default fingerprint-platform to host OS; expose platform_detectable"
```

---

## Task 3: Container-safe sandbox gate (`CBM_CONTAINER` marker; desktop default = sandbox ON)

**Files:**
- Modify: `backend/browser_manager.py` (`launch` — make `stealth_args`/`chromium_sandbox` conditional)
- Modify: `entrypoint.sh` (export `CBM_CONTAINER=1`)
- Test: `backend/tests/test_m1a_sandbox_gate.py`

**Interfaces:**
- Produces: `launch()` strips `--no-sandbox` (sandbox ON) unless `CBM_CONTAINER` is set, in which case it preserves the container's `--no-sandbox` behavior.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_m1a_sandbox_gate.py
from unittest.mock import AsyncMock, patch
import backend.browser_manager as bm

def _launch_kwargs(monkeypatch, container):
    if container: monkeypatch.setenv("CBM_CONTAINER", "1")
    else: monkeypatch.delenv("CBM_CONTAINER", raising=False)
    mgr = bm.BrowserManager()
    with patch.object(bm, "launch_persistent_context_async", new=AsyncMock()) as m:
        import asyncio
        try: asyncio.run(mgr.launch({"id": "x", "user_data_dir": "/tmp/x", "fingerprint_seed": 1}))
        except Exception: pass
        return m.call_args.kwargs if m.call_args else {}

def test_desktop_default_sandbox_on(monkeypatch, tmp_db):
    k = _launch_kwargs(monkeypatch, container=False)
    assert k.get("stealth_args") is False and k.get("chromium_sandbox") is True

def test_container_keeps_no_sandbox(monkeypatch, tmp_db):
    k = _launch_kwargs(monkeypatch, container=True)
    assert k.get("stealth_args") is not False  # library default (adds --no-sandbox)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_sandbox_gate.py -v`
Expected: FAIL — the M0 code sets `stealth_args=False`/`chromium_sandbox=True` unconditionally, so the container test fails.

- [ ] **Step 3: Implement the gate**

In `browser_manager.py` `launch()`, before the `launch_persistent_context_async(...)` call:
```python
_desktop = not os.environ.get("CBM_CONTAINER")
```
Pass `stealth_args=(False if _desktop else True)` and, only when `_desktop`, `chromium_sandbox=True` (omit the kwarg entirely in container mode so the library keeps its `--no-sandbox` default). Keep the `--no-sandbox` scrub of `launch_args` (M0) in BOTH modes only for desktop — in container mode leave `launch_args` untouched. (Ensure `import os` present.) In `entrypoint.sh`, add `export CBM_CONTAINER=1` before the `uvicorn` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_sandbox_gate.py backend/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/browser_manager.py entrypoint.sh backend/tests/test_m1a_sandbox_gate.py
git commit -m "feat(m1a): gate sandbox-on to desktop; container keeps --no-sandbox via CBM_CONTAINER"
```

---

## Task 4: Single-instance lock

**Files:**
- Create: `backend/single_instance.py`
- Modify: `backend/main.py` (acquire the lock in `lifespan`)
- Test: `backend/tests/test_m1a_single_instance.py`

**Interfaces:**
- Produces: `single_instance.acquire(lock_path: Path) -> object | None` — returns a held lock handle, or `None` if another instance holds it. Cross-platform (`fcntl` on POSIX, `msvcrt` on Windows).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_m1a_single_instance.py
from pathlib import Path
from backend.single_instance import acquire

def test_second_acquire_fails(tmp_path):
    p = tmp_path / "app.lock"
    h1 = acquire(p)
    assert h1 is not None
    h2 = acquire(p)
    assert h2 is None  # second instance refused
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_single_instance.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# backend/single_instance.py
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
```

- [ ] **Step 4: Wire into lifespan**

In `backend/main.py` `lifespan`, near the top, before `db.init_db()`:
```python
from . import single_instance
_lock = single_instance.acquire(db.DATA_DIR / "app.lock")
if _lock is None:
    logger.error("Another CloakBrowser Manager instance is already running.")
    raise SystemExit(1)
```
Keep `_lock` referenced for the process lifetime (assign to a module/app attribute so it isn't garbage-collected).

- [ ] **Step 5: Run tests + commit**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_single_instance.py backend/tests -q`
Expected: PASS.
```bash
git add backend/single_instance.py backend/main.py backend/tests/test_m1a_single_instance.py
git commit -m "feat(m1a): single-instance lock (prevents two managers on one profiles.db)"
```

---

## Task 5: Safe profile DELETE (terminate-then-retry, not `ignore_errors`)

**Files:**
- Modify: `backend/main.py:590` (the DELETE handler's `shutil.rmtree(..., ignore_errors=True)`)
- Test: `backend/tests/test_m1a_delete.py`

**Interfaces:**
- Produces: DELETE stops the running profile, then removes `user_data_dir` with a bounded retry (Windows releases Chromium file locks asynchronously); surfaces a real error if removal ultimately fails, instead of silently leaving an orphaned dir + a gone DB row.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_m1a_delete.py
from pathlib import Path
from backend.main import _rmtree_with_retry  # new helper

def test_rmtree_retry_eventually_removes(tmp_path):
    d = tmp_path / "p"; d.mkdir(); (d / "f").write_text("x")
    _rmtree_with_retry(d, attempts=3, delay=0.01)
    assert not d.exists()

def test_rmtree_retry_raises_on_persistent_failure(tmp_path, monkeypatch):
    import shutil, pytest
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError):
        _rmtree_with_retry(tmp_path / "p", attempts=2, delay=0.01)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_delete.py -v`
Expected: FAIL — `_rmtree_with_retry` undefined.

- [ ] **Step 3: Implement**

Add to `backend/main.py`:
```python
def _rmtree_with_retry(path, attempts: int = 5, delay: float = 0.2) -> None:
    """Remove a profile dir, retrying to survive Chromium's async lock release on Windows."""
    import shutil, time
    p = Path(path)
    if not p.exists():
        return
    last: Exception | None = None
    for _ in range(attempts):
        try:
            shutil.rmtree(p)
            return
        except OSError as exc:
            last = exc
            time.sleep(delay)
    raise last  # surface it — do not silently leave an orphan
```
Replace the `shutil.rmtree(user_data_dir, ignore_errors=True)` call at the DELETE handler with `_rmtree_with_retry(user_data_dir)`. Ensure the handler stops the running profile FIRST (it already does) and, on `_rmtree_with_retry` raising, returns a 500 with a clear message (the DB row deletion should happen only after the dir is gone, or be reported as partial).

- [ ] **Step 4: Run tests + commit**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_delete.py backend/tests -q`
Expected: PASS.
```bash
git add backend/main.py backend/tests/test_m1a_delete.py
git commit -m "feat(m1a): safe profile DELETE — terminate-then-retry rmtree, surface errors"
```

---

## Task 6: `auto_launch` stagger + concurrency cap

**Files:**
- Modify: `backend/browser_manager.py` (`auto_launch_all`)
- Test: `backend/tests/test_m1a_autolaunch.py`

**Interfaces:**
- Produces: `auto_launch_all()` launches auto-profiles with a small inter-launch delay (default 1.5s) so N first-run geoip downloads + N windows don't erupt simultaneously; a failed launch does not abort the rest.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_m1a_autolaunch.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_autolaunch.py -v`
Expected: FAIL — no stagger; and confirm current behavior aborts on failure or doesn't sleep.

- [ ] **Step 3: Implement**

In `auto_launch_all`, wrap each launch in try/except (log + continue on failure) and `await asyncio.sleep(1.5)` between launches (skip the sleep after the last one). Keep the existing 60s per-launch `wait_for` timeout.

- [ ] **Step 4: Run tests + commit**

Run: `./.venv/bin/python -m pytest backend/tests/test_m1a_autolaunch.py backend/tests -q`
Expected: PASS.
```bash
git add backend/browser_manager.py backend/tests/test_m1a_autolaunch.py
git commit -m "feat(m1a): stagger auto_launch + survive individual launch failures"
```

---

## Self-Review (completed)

- **Spec coverage (M1a slice of §9 + §4.1/§4.4 + §11):** cleanup_stale orphan+lock rewrite w/ identity rule (T1, §4.1/§8#10) · host-OS platform default + detectable flag (T2, §4.4) · container sandbox gate — the recorded merge caveat (T3) · single-instance lock (T4, §11) · DELETE terminate-then-retry (T5, §8#19) · auto_launch stagger (T6, §11). Deferred (correctly): cookie/bearer split + opt-in CDP proxy + fail-closed download + OSCrypt (M1b); ProfileViewer rebuild + auth-gate cookie path + frontend cleanup + first-run progress UI (M1c); signing (M2).
- **Placeholder scan:** none — every step has runnable code/commands.
- **Type consistency:** `db.host_platform()` used in T2 tests and `_build_fingerprint_args`; `CBM_CONTAINER` marker consistent T3↔entrypoint.sh; `_rmtree_with_retry(path, attempts, delay)` signature matches its test; `single_instance.acquire(Path) -> handle|None` consistent T4.
- **Note:** M1a is backend-only + `entrypoint.sh` — locally executable on this Mac exactly like M0's T1-3/T6 (Windows-specific paths in T4's `msvcrt` branch + T5's Windows lock-race are verified by logic/tests here, exercised for real on the T9 Windows machine).
```
