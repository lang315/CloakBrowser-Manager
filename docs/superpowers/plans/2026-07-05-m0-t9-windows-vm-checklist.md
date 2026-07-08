# M0 Task 9 — Windows VM Verification Checklist

Run these in a **clean Windows 10 or 11 VM** to complete the M0 gate's Windows half. Win11 ships the WebView2 runtime; Win10 often does not (see step 7). The **headline check is 5b** — it proves `WindowsProactorEventLoopPolicy` lets async Playwright spawn a subprocess inside the background uvicorn thread (the one Windows-specific packaging risk go-arch flagged).

Report each step PASS/FAIL back (or append to `docs/superpowers/plans/m0-results.md`). Do **not** commit real proxy credentials.

## 1. Prerequisites
- Windows 10/11 x64 VM, **Python 3.12** (from python.org, "Add to PATH"), **Node.js 20+**, **Git**.
- Get the branch: `git clone <repo> && cd CloakBrowser-Manager && git checkout feature/desktop-native-app` (or copy the working tree into the VM).

## 2. Python env + deps (PowerShell, from repo root)
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt pytest pytest-asyncio pywebview pyinstaller "psutil>=6.0"
.\.venv\Scripts\python.exe -c "import cloakbrowser, fastapi, playwright, uvicorn, webview, psutil; print('imports OK')"
```

## 3. Sanity: run the test suite
```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```
Expect **208 passed** (proves the backend + the `msvcrt` single-instance branch + Windows paths import/run).

## 4. Build the frontend + the frozen onedir
```powershell
cd frontend; npm install; npm run build; cd ..
powershell -ExecutionPolicy Bypass -File desktop\build_win.ps1
```
- **CHECK (4):** `desktop\dist\CloakBrowser Manager\CloakBrowser Manager.exe` exists; the build finished without a Playwright-driver `FileExistsError`.

## 5. Launch + verify (the core Windows proofs)
Run the frozen app: double-click the `.exe` (or run it from a terminal to see logs).

- **5a — window opens.** The control-panel SPA renders (proves WebView2 works). On Win10 with no runtime, see step 7 first.
- **5b — async launch (THE key check).** In the app: create a profile (no proxy), click **Launch**. A **native Chromium window** must open. If the logs show `NotImplementedError` in `_make_subprocess_transport`, the Proactor loop policy isn't taking effect — capture the traceback. First launch downloads the ~140MB Chromium (allow a few minutes).
- **5c — authenticated proxy (Windows T7-equivalent).** Create another profile with **your proxy** in `host:port:user:pass` form (do NOT paste it into any committed file). Launch it, navigate to `https://api.ipify.org?format=json`. The IP must be the **proxy's egress**, not the VM's real IP (check the VM's real IP with `curl https://api.ipify.org` in a normal browser/terminal). No `407` dialog → proxy auth works on Windows.
- **5d — sandbox on.** In Task Manager / `Get-Process`, the launched Chromium runs and its command line has **no** `--no-sandbox` (desktop default; `CBM_CONTAINER` is unset). It must not crash immediately (Windows sandbox init OK).
- **5e — single instance.** Launch the `.exe` a second time while the first runs → it must refuse (the first holds the `msvcrt` lock on `%APPDATA%\CloakBrowser Manager\app.lock`). Note: per the recorded M1a finding, the 2nd instance currently dies via the 30s `_wait_ready` timeout rather than a crisp message — a slow-but-correct refusal is a PASS.

## 6. (Optional) installer
```powershell
# Install Inno Setup (https://jrsoftware.org/isdl.php), then:
iscc desktop\installer.iss
```
Produces `desktop\Output\CloakBrowserManager-Setup.exe`. **Signing** the setup + app `.exe` needs your **OV/EV code-signing cert** (`signtool sign /fd SHA256 /tr <timestamp-url> /td SHA256 ...`) — deferred until the cert is available; unsigned will trigger SmartScreen.

## 7. Win10-only: WebView2 runtime
If the window is blank / fails to init on Win10, install the Evergreen runtime once: download **MicrosoftEdgeWebview2Setup.exe** from Microsoft and run `MicrosoftEdgeWebview2Setup.exe /silent /install` (or bundle it via the commented `[Run]` line in `installer.iss`). Win11 skips this.

## Gate outcome
- All of 4, 5a–5e PASS → **Windows M0 is GREEN** (unsigned); only code-signing (cert) remains.
- 5b `NotImplementedError` → the Proactor policy needs fixing in `desktop/app_entry.py` before proceeding.
- 5a blank on Win11 → WebView2/pywebview integration issue — capture logs.
