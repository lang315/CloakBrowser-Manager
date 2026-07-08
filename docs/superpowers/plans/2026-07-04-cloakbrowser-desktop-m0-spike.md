# CloakBrowser Desktop — M0 Packaging Spike — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the frozen PyInstaller + pywebview + Playwright + `cloakbrowser` desktop stack can launch a CloakBrowser profile through an **authenticated proxy** — **sandboxed**, **hardened-signed**, **cookie-authenticated** — on a clean macOS M1 **and** a clean Windows 10. This is the go/no-go gate for the entire Python-native path (spec `2026-07-04-cloakbrowser-desktop-python-native-design.md` §9 M0).

**Architecture:** A thin frozen-app entrypoint (`packaging/app_entry.py`) sets the per-OS data/cache dirs + the Windows event-loop policy, sanitizes the PyInstaller subprocess env, starts the existing FastAPI backend under uvicorn in a **background thread**, and opens a **pywebview** window on the **main thread** pointed at `http://localhost:<ephemeral>`. A minimal de-VNC of `browser_manager.launch()` lets a profile spawn as a native OS window. PyInstaller `onedir` bundles Playwright's node driver.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, `cloakbrowser` (Playwright + patched Chromium), pywebview, PyInstaller; macOS `codesign`/`notarytool`; Windows Inno Setup/NSIS + WebView2 Evergreen bootstrapper.

## Global Constraints

*(Copied verbatim from the spec — every task implicitly includes these.)*
- **onedir on both OSes** — never onefile.
- **Sandbox ON:** strip `--no-sandbox`; the sandbox test MUST run on the **downloaded** binary, not a dev-signed build.
- **Env-sanitize:** restore the bootloader's `*_ORIG` values + strip `_MEIPASS` paths from `os.environ`, **after** the app's own C-extension imports, **before** any Playwright launch.
- **Windows:** `asyncio.WindowsProactorEventLoopPolicy()` set at process start; uvicorn `loop="asyncio"`; uvicorn in a **background thread**, pywebview on the **main thread**.
- **Cookie:** `HttpOnly; SameSite=Strict`, **NO `Secure`**; a single `CANON_HOST = "localhost"` — the webview origin, the Set-Cookie host, and the Host-allowlist canonical are all `localhost`.
- **macOS entitlements:** `com.apple.security.cs.allow-jit` + `com.apple.security.cs.allow-unsigned-executable-memory`; sign every nested Mach-O **inside-out** (no `--deep`).
- **Fail-closed checksum** locally; never set `CLOAKBROWSER_SKIP_CHECKSUM` in a shipped build.
- **Pin the Playwright backend** (`playwright`, not `patchright`) for the spike.
- **This is a spike:** each task's "test" is a runnable verification with a recorded PASS/FAIL. A FAIL on Task 6, 7, 8, or 10 is a legitimate M0 outcome that may send the project back to the Go decision — record it, don't paper over it.

**Hardware/credential prerequisites (start day 1):** a clean macOS M1, a clean Windows 10 VM/machine, an **Apple Developer certificate** (~$99/yr, ~days), a **Windows OV/EV code-signing certificate** (1-3 wk identity validation), and a **known-good authenticated HTTP proxy** (host:port:user:pass) with a distinct exit IP for Task 8.

---

## Task 1: Per-OS data/cache dirs + minimal de-VNC of `launch()`

Without this the app can't run off `/data` and `launch()` calls KasmVNC binaries absent on mac/win.

**Files:**
- Modify: `backend/database.py:14` (DATA_DIR resolution)
- Modify: `backend/browser_manager.py` (strip VNC from `__init__`, `RunningProfile`, `launch`, `stop`, `_on_browser_closed`, `get_status`)
- Test: `backend/tests/test_m0_launch.py` (new)

**Interfaces:**
- Produces: `db.DATA_DIR` resolves to a writable per-OS dir honoring `CBM_DATA_DIR` env override; `BrowserManager.launch(profile)` returns a `RunningProfile` with fields `profile_id`, `context`, `cdp_port` (no `display`/`ws_port`); `get_status(id)` returns `{"status","cdp_url"}` (no vnc fields).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_m0_launch.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/lang/GolandProjects/github.com/lang315/CloakBrowser-Manager && python -m pytest backend/tests/test_m0_launch.py -v`
Expected: FAIL — `test_running_profile_has_no_vnc_fields` fails (`display` still present); env-override test fails (no `CBM_DATA_DIR` support).

- [ ] **Step 3: Implement the data-dir resolution**

Replace `backend/database.py:14` (`DATA_DIR = Path("/data")`) with:

```python
import sys

def _default_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CloakBrowser Manager"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "CloakBrowser Manager"
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "CloakBrowser Manager"

DATA_DIR = Path(os.environ.get("CBM_DATA_DIR") or _default_data_dir())
```
(Ensure `import os` and `from pathlib import Path` exist at the top of `database.py`.)

- [ ] **Step 4: Implement the minimal de-VNC of `browser_manager.py`**

Make these exact edits:
- Delete `from .vnc_manager import VNCManager` (`:17`).
- In `RunningProfile` (`:150-155`), delete the `display: int` and `ws_port: int` fields.
- In `__init__`, delete `self.vnc = VNCManager()` (`:162`).
- In `launch()`: delete `display, ws_port = await self.vnc.allocate()` (`:176`) and its `except` rollback `await self.vnc.stop_vnc(display)` (`:183`); delete the `await self.vnc.start_vnc(display, ws_port, ...)` block (`:196-201`); remove `env={**os.environ, "DISPLAY": f":{display}"}` from the `launch_persistent_context_async(...)` call (`:233`); build `RunningProfile(profile_id=..., context=..., cdp_port=cdp_port)` (drop `display=`/`ws_port=`, `:262-263`); in the final `except`, drop `await self.vnc.stop_vnc(display)` (`:286`).
- In `stop()` and `_on_browser_closed()`, delete the `await self.vnc.stop_vnc(running.display)` lines (`:296`, `:314`).
- In `get_status()` (`:322-326`), return `{"status": "running", "cdp_url": f"http://localhost/api/profiles/{profile_id}/cdp"}` when running and `{"status": "stopped", "cdp_url": None}` when stopped (drop `vnc_ws_port`/`display`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_m0_launch.py -v`
Expected: PASS (both).

- [ ] **Step 6: Commit**

```bash
git add backend/database.py backend/browser_manager.py backend/tests/test_m0_launch.py
git commit -m "feat(m0): per-OS data dir + minimal de-VNC launch path"
```

---

## Task 2: Frozen-app entrypoint (env-sanitize + uvicorn bg thread + pywebview main thread)

**Files:**
- Create: `packaging/app_entry.py`
- Create: `packaging/__init__.py` (empty)
- Test: `backend/tests/test_app_entry.py`

**Interfaces:**
- Produces: `packaging.app_entry.sanitize_frozen_env()` (idempotent; strips `_MEIPASS` from `DYLD_LIBRARY_PATH`/`LD_LIBRARY_PATH`, restores `*_ORIG`); `packaging.app_entry.pick_port() -> int`; `packaging.app_entry.main()` (blocking; runs the app).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_app_entry.py
import os
from packaging.app_entry import sanitize_frozen_env, pick_port

def test_sanitize_removes_meipass(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123/lib:/usr/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib")
    monkeypatch.setattr("sys._MEIPASS", "/tmp/_MEI123", raising=False)
    sanitize_frozen_env()
    assert "/tmp/_MEI123" not in os.environ.get("LD_LIBRARY_PATH", "")

def test_pick_port_is_free():
    p = pick_port()
    assert 1024 < p < 65536
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_app_entry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'packaging.app_entry'`.

- [ ] **Step 3: Write the entrypoint**

```python
# packaging/app_entry.py
"""Frozen desktop entrypoint: env-sanitize → uvicorn (bg thread) → pywebview (main thread)."""
import os, sys, socket, threading, time, secrets, asyncio, urllib.request

CANON_HOST = "localhost"

def sanitize_frozen_env() -> None:
    """Strip PyInstaller's _MEIPASS from the dynamic-loader paths so spawned
    subprocesses (Playwright node driver, Chromium) don't inherit them.
    Restore the bootloader's *_ORIG values. Call AFTER the app's own C-ext
    imports, BEFORE any Playwright launch. (Mostly Linux insurance — macOS uses
    @rpath and strips DYLD_* on spawn; Windows uses the DLL dir.)"""
    meipass = getattr(sys, "_MEIPASS", None)
    for var in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH"):
        orig = os.environ.pop(var + "_ORIG", None)
        if orig is not None:
            os.environ[var] = orig
        elif meipass and var in os.environ:
            parts = [p for p in os.environ[var].split(os.pathsep) if meipass not in p]
            if parts:
                os.environ[var] = os.pathsep.join(parts)
            else:
                os.environ.pop(var, None)

def pick_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return port

def _wait_ready(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    url = f"http://{CANON_HOST}:{port}/api/status"
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1); return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("backend did not become ready")

def main() -> None:
    # Windows: Playwright's async subprocess needs the Proactor loop policy.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # Keep the library's binary + GeoLite2 cache under our app-data root (single root).
    import backend.database as db  # C-ext (sqlite) import happens here
    os.environ.setdefault("CLOAKBROWSER_CACHE_DIR", str(db.DATA_DIR / "cloakbrowser-cache"))

    sanitize_frozen_env()  # after C-ext imports, before any launch

    # Per-session UI cookie secret (Task 4 reads it).
    os.environ["CBM_UI_SECRET"] = secrets.token_urlsafe(32)

    import uvicorn
    port = pick_port()
    os.environ["CBM_PORT"] = str(port)
    config = uvicorn.Config("backend.main:app", host="127.0.0.1", port=port,
                            log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    _wait_ready(port)

    import webview
    webview.create_window("CloakBrowser Manager", f"http://{CANON_HOST}:{port}")
    webview.start()  # blocks on the main thread

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Install the new runtime deps + run the unit test**

Run:
```bash
python -m pip install pywebview pyinstaller
python -m pytest backend/tests/test_app_entry.py -v
```
Expected: PASS (both).

- [ ] **Step 5: Smoke-run UNFROZEN (window + API reachable)**

Run: `cd /Users/lang/GolandProjects/github.com/lang315/CloakBrowser-Manager && python -m packaging.app_entry`
Expected: a native window opens showing the built SPA (run `cd frontend && npm install && npm run build` first if `frontend/dist` is missing); `curl -s http://localhost:$CBM_PORT/api/status` (in another shell, using the printed port) returns JSON. Close the window; process exits. **Record PASS/FAIL.**

- [ ] **Step 6: Commit**

```bash
git add packaging/app_entry.py packaging/__init__.py backend/tests/test_app_entry.py
git commit -m "feat(m0): frozen entrypoint — env-sanitize, uvicorn bg thread, pywebview main thread"
```

---

## Task 3: Minimal cookie auth + exact Host-allowlist (M0 subset)

Full split-credential model is M1b; M0 proves the cookie round-trips through the webview and the Host-allowlist doesn't break same-origin fetches.

**Files:**
- Modify: `backend/main.py` (AuthMiddleware — cookie set on SPA bootstrap, Host check)
- Test: `backend/tests/test_m0_auth.py`

**Interfaces:**
- Consumes: `os.environ["CBM_UI_SECRET"]` (Task 2).
- Produces: middleware that (a) rejects requests whose `Host` hostname ∉ `{localhost,127.0.0.1,[::1]}`; (b) sets an `HttpOnly; SameSite=Strict` cookie `cbm_ui=<CBM_UI_SECRET>` (no `Secure`) on the SPA index response; (c) allows `/api/*` only with the valid cookie.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_m0_auth.py
import os
os.environ["CBM_UI_SECRET"] = "test-secret"
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app, base_url="http://localhost")

def test_rejects_bad_host():
    r = client.get("/api/status", headers={"Host": "127.0.0.1.evil.com"})
    assert r.status_code == 403

def test_api_requires_cookie():
    r = client.get("/api/profiles", headers={"Host": "localhost"})
    assert r.status_code == 401

def test_index_sets_httponly_cookie_without_secure():
    r = client.get("/", headers={"Host": "localhost"})
    setc = r.headers.get("set-cookie", "")
    assert "cbm_ui=" in setc and "HttpOnly" in setc and "Secure" not in setc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_m0_auth.py -v`
Expected: FAIL — bad-Host returns 200 (no Host check); no cookie set.

- [ ] **Step 3: Implement in the existing `AuthMiddleware`**

In `backend/main.py`, replace the `AuthMiddleware` body so its `__call__` (ASGI) does, in order: parse the `Host` header, reject with 403 if the hostname is not an exact member of `{"localhost","127.0.0.1","::1"}`; for `/api/*` (except `/api/status`), require `request.cookies.get("cbm_ui")` to `hmac.compare_digest` against `os.environ["CBM_UI_SECRET"]` else 401; for the SPA index (`GET /` or the catch-all HTML response), set `response.set_cookie("cbm_ui", os.environ["CBM_UI_SECRET"], httponly=True, samesite="strict", secure=False)`. Remove the old `AUTH_TOKEN` optionality for this path. (Reference the exact-match + WS rules in spec §4.3; the full Bearer split is M1b.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_m0_auth.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_m0_auth.py
git commit -m "feat(m0): loopback cookie auth + exact Host-allowlist"
```

---

## Task 4: PyInstaller onedir spec (bundle Playwright driver, pin backend)

**Files:**
- Create: `packaging/cloakbrowser-manager.spec`
- Create: `packaging/build_mac.sh`

**Interfaces:**
- Produces: `dist/CloakBrowser Manager.app` (macOS) / `dist/CloakBrowser Manager/` (Windows), onedir, with `frontend/dist` bundled and the Playwright driver collected.

- [ ] **Step 1: Ensure the SPA build exists**

Run: `cd frontend && npm install && npm run build && cd ..`
Expected: `frontend/dist/index.html` exists.

- [ ] **Step 2: Write the PyInstaller spec**

```python
# packaging/cloakbrowser-manager.spec
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
datas, binaries, hiddenimports = [], [], []
for pkg in ("playwright", "cloakbrowser"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
# Exclude Playwright's own browser download — cloakbrowser downloads its binary.
datas = [(s, d) for (s, d) in datas if ".local-browsers" not in s]
datas += [("../frontend/dist", "frontend/dist")]

a = Analysis(["app_entry.py"], pathex=[".."], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports + ["backend.main"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CloakBrowser Manager",
          console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="CloakBrowser Manager")  # onedir
app = BUNDLE(coll, name="CloakBrowser Manager.app",
             bundle_identifier="dev.cloakbrowser.manager")
```

- [ ] **Step 3: Write the mac build script**

```bash
# packaging/build_mac.sh
#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
pyinstaller --noconfirm --clean cloakbrowser-manager.spec
echo "Built: dist/CloakBrowser Manager.app"
```

- [ ] **Step 4: Build**

Run: `chmod +x packaging/build_mac.sh && ./packaging/build_mac.sh`
Expected: `packaging/dist/CloakBrowser Manager.app` exists; build completes without a `FileExistsError` from the Playwright driver. **Record PASS/FAIL** (driver-bundling failure here is the classic frozen-Playwright landmine).

- [ ] **Step 5: Commit**

```bash
git add packaging/cloakbrowser-manager.spec packaging/build_mac.sh
git commit -m "feat(m0): PyInstaller onedir spec bundling Playwright driver + SPA"
```

---

## Task 5: Frozen app launches (window + API + profile) on macOS — unsigned

**Files:** none (verification task on the Task 4 artifact).

- [ ] **Step 1: Launch the frozen app**

Run: `open "packaging/dist/CloakBrowser Manager.app"`
Expected: the native window opens showing the SPA. **Record PASS/FAIL.** If the window is blank, run from a terminal to see logs: `"packaging/dist/CloakBrowser Manager.app/Contents/MacOS/CloakBrowser Manager"`.

- [ ] **Step 2: Create + launch a profile through the UI**

In the app: create a profile (no proxy), click Launch.
Expected: a **native Chromium window** opens (the patched binary downloads on first run — may take minutes; watch the terminal). **Record PASS/FAIL** — this proves the frozen entrypoint's env-sanitize let the node driver + Chromium spawn correctly.

- [ ] **Step 3: Record the result**

Append PASS/FAIL + notes to `docs/superpowers/plans/m0-results.md` (create it). Commit:
```bash
git add docs/superpowers/plans/m0-results.md
git commit -m "docs(m0): record frozen-app launch result (macOS unsigned)"
```

---

## Task 6: Sandbox ON — strip `--no-sandbox`, verify the downloaded binary launches sandboxed

**Files:**
- Modify: `backend/browser_manager.py` (`_build_fingerprint_args` — filter `--no-sandbox`)
- Test: `backend/tests/test_m0_sandbox.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_m0_sandbox.py
from backend.browser_manager import BrowserManager
def test_no_sandbox_is_stripped():
    args = BrowserManager()._build_fingerprint_args({"fingerprint_seed": 12345})
    assert "--no-sandbox" not in args
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_m0_sandbox.py -v`
Expected: FAIL if `_build_fingerprint_args` emits `--no-sandbox`. (If it doesn't emit it directly, the flag comes from `cloakbrowser.config.get_default_stealth_args`; see Step 3.)

- [ ] **Step 3: Strip `--no-sandbox` at the Manager boundary**

In `browser_manager.py` `launch()`, after building `extra_args`, filter it: `extra_args = [a for a in extra_args if a != "--no-sandbox"]`. Because the library's `get_default_stealth_args()` injects `--no-sandbox` internally, ALSO pass `stealth_args`-aware handling: verify via Step 4 whether the launched Chromium is sandboxed; if the library still injects it, set the documented env/flag to suppress it or pass explicit args with `stealth_args=False` + a hand-built stealth set (record which was needed).

- [ ] **Step 4: Verify the DOWNLOADED binary launches sandboxed (macOS)**

Launch a profile from the frozen app, then run:
`ps aux | grep -i chromium | grep -v grep`
Expected: the Chromium command line does **NOT** contain `--no-sandbox`. Confirm the process runs (no immediate crash). **Record PASS/FAIL.** If the sandbox fails to initialize for the unsigned downloaded binary under the hardened runtime (Task 8), record it — this is the escalation trigger in spec §4.4.

- [ ] **Step 5: Commit**

```bash
git add backend/browser_manager.py backend/tests/test_m0_sandbox.py docs/superpowers/plans/m0-results.md
git commit -m "feat(m0): strip --no-sandbox; verify sandboxed launch on downloaded binary"
```

---

## Task 7: Authenticated-proxy launch + exit-IP + CDP round-trip (macOS) — the core M0 proof

**Files:** none (verification on a profile configured with a real auth proxy).

- [ ] **Step 1: Configure a profile with an authenticated proxy**

In the app, create a profile with `proxy = host:port:user:pass` (your known-good auth proxy). Launch it.
Expected: the native Chromium window opens without a proxy-auth dialog (Playwright supplies creds). **Record PASS/FAIL.**

- [ ] **Step 2: Verify the exit IP**

In the launched profile, navigate to `https://api.ipify.org`.
Expected: the page shows the **proxy's** exit IP, not your real IP. **Record PASS/FAIL.**

- [ ] **Step 3: Verify a CDP round-trip via the opt-in proxy**

Enable external automation on the profile (per spec §4.3a — opt-in), then from a separate Python:
```python
from playwright.sync_api import sync_playwright
bearer = open(<0600 bearer file path>).read().strip()   # path from the app UI
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(f"http://localhost:{PORT}/api/profiles/{ID}/cdp",
                                    headers={"Authorization": f"Bearer {bearer}"})
    print(b.contexts[0].pages[0].title())
```
Expected: prints the page title (a successful CDP round-trip through the bearer-gated proxy). **Record PASS/FAIL.** *(If the opt-in external path is not yet wired at M0, substitute a direct pipe-CDP check and note the gap for M1b.)*

- [ ] **Step 4: Commit the recorded results**

```bash
git add docs/superpowers/plans/m0-results.md
git commit -m "docs(m0): record auth-proxy + exit-IP + CDP round-trip (macOS)"
```

---

## Task 8: macOS hardened-runtime sign + notarize; cookie in WKWebView; native-close detection

**Files:**
- Create: `packaging/entitlements.plist`
- Create: `packaging/sign_notarize.sh`

- [ ] **Step 1: Write the entitlements**

```xml
<!-- packaging/entitlements.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.cs.allow-jit</key><true/>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
</dict></plist>
```

- [ ] **Step 2: Write the sign+notarize script (inside-out, no `--deep`)**

```bash
# packaging/sign_notarize.sh
#!/bin/bash
set -euo pipefail
APP="packaging/dist/CloakBrowser Manager.app"
ID="Developer ID Application: <YOUR NAME> (<TEAMID>)"
ENT="packaging/entitlements.plist"
# Sign every nested Mach-O inside-out (node, dylibs) THEN the app bundle.
find "$APP/Contents" \( -name "*.dylib" -o -name "*.so" -o -name "node" \) -print0 \
  | xargs -0 -I{} codesign --force --options runtime --timestamp --entitlements "$ENT" -s "$ID" {}
codesign --force --options runtime --timestamp --entitlements "$ENT" -s "$ID" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
ditto -c -k --keepParent "$APP" packaging/dist/CBM.zip
xcrun notarytool submit packaging/dist/CBM.zip --keychain-profile "AC_PASSWORD" --wait
xcrun stapler staple "$APP"
```

- [ ] **Step 3: Sign, notarize, staple**

Run: `chmod +x packaging/sign_notarize.sh && ./packaging/sign_notarize.sh`
Expected: `notarytool` returns `Accepted`; `stapler staple` succeeds. **Record PASS/FAIL** (notarizing a JIT/node bundle is a known landmine).

- [ ] **Step 4: Verify on a clean Mac (Gatekeeper + cookie + close-detection)**

Copy the stapled `.app` to a **clean** macOS M1 (no dev tools), open it.
Expected: opens with **no** Gatekeeper "damaged"/"unidentified" block; the SPA loads (proves the **HttpOnly-no-Secure cookie round-trips in WKWebField**); launch a profile, then **close the native Chromium window** and confirm the app flips the profile to `stopped` within a few seconds (proves `context.on("close")` fires natively — spec §8 #9). **Record PASS/FAIL for each.**

- [ ] **Step 5: Commit**

```bash
git add packaging/entitlements.plist packaging/sign_notarize.sh docs/superpowers/plans/m0-results.md
git commit -m "feat(m0): macOS hardened sign+notarize; verify clean-Mac launch, cookie, close-detection"
```

---

## Task 9: Windows 10 M0 (clean machine) — build, WebView2, Proactor async launch, sign

**Files:**
- Create: `packaging/build_win.ps1`
- Create: `packaging/installer.iss` (Inno Setup: onedir + WebView2 Evergreen bootstrapper)

**Interfaces:** mirrors Tasks 4-8 on Windows; the async-launch path exercises `WindowsProactorEventLoopPolicy` (Task 2).

- [ ] **Step 1: Write the Windows build script**

```powershell
# packaging/build_win.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
pyinstaller --noconfirm --clean cloakbrowser-manager.spec
Write-Host "Built: dist/CloakBrowser Manager/"
```

- [ ] **Step 2: Build on a clean Windows 10 machine**

Run (Win10): `python -m pip install pywebview pyinstaller ; cd frontend; npm install; npm run build; cd ..; powershell -File packaging/build_win.ps1`
Expected: `packaging/dist/CloakBrowser Manager/CloakBrowser Manager.exe` exists. **Record PASS/FAIL.**

- [ ] **Step 3: Launch + verify the async path (the Proactor gate)**

Run the `.exe`. Create a profile, Launch.
Expected: the window opens (WebView2 present or bootstrapper installed); a native Chromium window opens — proving `launch_persistent_context_async` works under `WindowsProactorEventLoopPolicy` in the background uvicorn thread (Task 2). If you see `NotImplementedError` in logs, the loop policy is wrong. **Record PASS/FAIL.**

- [ ] **Step 4: Auth-proxy + exit-IP + CDP round-trip (repeat Task 7 on Windows)**

Same checks as Task 7. **Record PASS/FAIL.**

- [ ] **Step 5: Package with WebView2 bootstrapper + code-sign**

Write `packaging/installer.iss` (Inno Setup) that packages the onedir output and runs the WebView2 Evergreen bootstrapper if absent; build the installer; sign the `.exe`/installer with your OV/EV cert (`signtool sign /fd SHA256 /tr <timestamp> ...`). Install on a **clean** Win10 (no WebView2 preinstalled).
Expected: installs, launches without a missing-WebView2 error, SmartScreen does not hard-block a signed installer. **Record PASS/FAIL.**

- [ ] **Step 6: Commit**

```bash
git add packaging/build_win.ps1 packaging/installer.iss docs/superpowers/plans/m0-results.md
git commit -m "feat(m0): Windows build + WebView2 bootstrapper + signed installer; verify Proactor async launch"
```

---

## Task 10: M0 gate decision

**Files:**
- Modify: `docs/superpowers/plans/m0-results.md`

- [ ] **Step 1: Tabulate results**

Fill `m0-results.md` with a PASS/FAIL row for each: mac frozen launch (T5), sandbox on downloaded binary (T6), auth-proxy+exit-IP+CDP (T7), mac notarize+clean-Mac+cookie+close (T8), Windows build+Proactor+proxy+WebView2 (T9).

- [ ] **Step 2: Decide the gate**

Write the verdict:
- **GREEN** (all PASS) → proceed to write the M1a plan (spec §9).
- **YELLOW** (fixable FAILs) → list the specific blockers + retries before M1a.
- **RED** (a structural FAIL — e.g. cannot notarize the JIT/node bundle, or the sandbox cannot init on the downloaded binary, or Playwright cannot be frozen) → **revisit the Go decision** (companion spec); the Python-native path is not viable as-is.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/m0-results.md
git commit -m "docs(m0): M0 gate verdict"
```

---

## Self-Review (completed)

- **Spec coverage (M0 slice of §9):** frozen stack (T2,T4,T5) · env-sanitize (T2) · Windows Proactor + thread model (T2,T9) · onedir + driver bundling (T4) · minimal de-VNC to run (T1) · per-OS data + unified cache root (T1,T2) · auth-proxy + exit-IP + CDP round-trip (T7,T9) · sandbox-on downloaded binary (T6) · cookie HttpOnly-no-Secure in both webviews (T3,T8,T9) · macOS hardened sign+notarize inside-out + allow-jit (T8) · native-close detection #9 (T8) · WebView2 bootstrapper (T9) · gate verdict incl. Go-fallback (T10). Deferred to later plans (correctly): full credential split, opt-in CDP full wiring, ProfileViewer rebuild, creds-at-rest, first-run progress UI, single-instance lock.
- **Placeholder scan:** the `<YOUR NAME>/<TEAMID>` and bearer-file-path and proxy `host:port:user:pass` are **operator-supplied secrets/identities**, intentionally not literal — flagged inline, not TODOs.
- **Type consistency:** `RunningProfile` drops `display`/`ws_port` (T1) consistently with `get_status` (T1) and the spec's response-field change; `CANON_HOST="localhost"`, `CBM_UI_SECRET`, `CBM_PORT` used consistently across T2/T3.
```
