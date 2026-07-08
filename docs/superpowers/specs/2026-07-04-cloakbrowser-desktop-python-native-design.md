# CloakBrowser Desktop Manager — Python-native (Ship-first) — Design **v2.1**

**Date:** 2026-07-04 · **v2.1** after 3 adversarial review rounds (packaging / security / scope / cold-read)
**Status:** Ready for planning
**Companion spec:** `2026-07-04-cloakbrowser-desktop-go-rewrite-design.md` (long-term Go rewrite; this app is its stealth-parity oracle)

> **v2.1 changelog (round-3 fixes):** one coherent **opt-in CDP topology** (proxy-gated) replaces the two contradictory ones. `cleanup_stale` gets an explicit **orphan-identity rule** (match our `user_data_dir`, never process name). The reused `_check_auth` is **split into two credentials** (UI cookie ≠ external bearer). The download path is honestly a **partial re-port of `download.py`** (not "wrapping"). Cookie drops `Secure` + pins one canonical loopback host. The **oracle** now captures argv + per-attribute values. Creds-at-rest encryption **deferred to v1.1**. Second cache root (`~/.cloakbrowser`) unified. Milestones re-split (M1a/M1b/M1c) and re-estimated (~7-9 wks).

## 1. Context & goal

Today CloakBrowser-Manager ships as **one Docker/Linux container**. Each profile launches a patched stealth Chromium ("CloakBrowser") with a unique fingerprint; because the browser runs headless in-container it is viewed in the web UI via **KasmVNC/noVNC**. Backend is FastAPI (`backend/`), frontend React 19 + Vite (`frontend/`); the browser is driven through the `cloakbrowser` Python library (a Playwright wrapper around the binary).

**Goal:** ship a **native desktop app for macOS (M1) and Windows 10** quickly, reusing the proven stealth stack. On desktop the browser opens as a **real OS window** — all VNC/X11 machinery is dropped.

**Approach:** repackage the Python app natively — **PyInstaller** (onedir) + **pywebview** (native window over embedded FastAPI on loopback). Reuse the `cloakbrowser` library as a **dependency** — with two honest exceptions requiring a thin wrapper / partial re-port: (a) a frozen-app **env-sanitize** entrypoint (§3), and (b) a **partial re-port of the download/verify path** for progress + fail-closed integrity (§6.4). Everything else (launch, fingerprint args, geoip, proxy auth) is reused. Rationale: stealth is compiled into the binary; reusing the 6894-line library avoids re-earning its bug history (#157, #182) and rides upstream patches via `pip`. A Go rewrite follows later (companion spec) using this app as the stealth-parity oracle.

## 2. Non-goals
- No Go code (companion spec).
- No new server-side automation / `/human` API. `humanize` stays as the library wires it (§7).
- No networked/multi-user mode. Single local user; loopback only.
- **Automatic** migration of an existing Docker user's `/data` is a **non-goal** — documented manual copy instead (§11).
- No source edits to `cloakbrowser` beyond the partial download-path re-port (§6.4); deeper integrity fixes pushed upstream.

## 3. Architecture

```
┌─ pywebview native window (WKWebView / WebView2) ─┐
│  React SPA — served from http://<CANON_HOST>:<port>   (NOT file://)
└───────────────┬───────────────────────────────────┘
   HTTP /api     │  HttpOnly cookie (no Secure) + exact Host-allowlist
┌───────────────▼──── frozen Python (PyInstaller onedir) ──────────┐
│  entrypoint: sanitize os.environ (restore *_ORIG, strip _MEIPASS)│
│    AFTER app's own C-ext imports; BEFORE starting Playwright      │
│  FastAPI: CRUD · launch/stop · opt-in bearer-gated CDP proxy      │
│  cloakbrowser lib (dependency) + partial download re-port         │
└───────────────┬──────────────────────────────────────────────────┘
       spawn     │  patched Chromium + --fingerprint-* (sandbox ON)
┌────────────────▼───────────┐
│ Profile = native OS window  │
└─────────────────────────────┘
```

- **`CANON_HOST` invariant:** pywebview loads the SPA over **`http://<CANON_HOST>:<ephemeral>`** where `CANON_HOST` is the single canonical loopback host (recommend `localhost`; §4.3). The webview origin, the Set-Cookie host, and the Host-allowlist canonical MUST be identical — cookies are host-scoped (a cookie set on `127.0.0.1` is not sent to `localhost`). Not `file://`/custom scheme (breaks cookie scoping + Origin match). **Do not add a CORS middleware** (none exists today, `main.py:390`) — an origin-reflecting `CORSMiddleware` would nullify the exact-Origin rule.
- **Env-sanitize (belt-and-suspenders, correctly sequenced):** PyInstaller's bootloader points `DYLD_LIBRARY_PATH`/`LD_LIBRARY_PATH` at `sys._MEIPASS`, inherited by subprocesses — the Playwright **node driver** (`cloakbrowser/browser.py:214,467`) and the spawned Chromium. On macOS bundled dylibs resolve via `@rpath` (independent of `DYLD_*`, which macOS also strips on spawn) and on Windows via the DLL directory, so this is mostly **Linux-shaped insurance** — but some PyInstaller run-time hooks do set `DYLD_*`, and the node-driver spawn is only influenceable via global `os.environ`. Restore the bootloader's `*_ORIG` values **after** the app's own C-extension imports (§4.2 crypto/keyring, sqlite) and **before** starting Playwright.
- **Proxy auth is free** (Playwright-native `_resolve_proxy_config`) — sidesteps the Go path's `Fetch.continueWithAuth` + two-CDP-clients problems.

## 4. Backend changes (`backend/`)

### 4.1 De-VNC is a launch-lifecycle rewrite (not a line-delete)
`vnc_manager.py` deletion is trivial; the coupling in `browser_manager.py` is not. Edit surface:
- **`launch()`** — remove `display, ws_port = self.vnc.allocate()` (`:176`, before cdp_port/args) + its `self.vnc.stop_vnc(display)` rollback (`:183`); **remove `env={**os.environ, "DISPLAY": f":{display}"}`** into `launch_persistent_context_async` — no X11 on mac/win; meaningless/harmful. (This is also where §3's sanitized env applies; with `DISPLAY` gone and startup-sanitize done, the per-launch `env=` kwarg is redundant — collapse to one.)
- **`RunningProfile`** (`:150-155`) — drop `display`/`ws_port`.
- **`stop()` / `_on_browser_closed()` / `cleanup_all()`** — drop `self.vnc.*` teardown.
- **`cleanup_stale()`** — currently `self.vnc.cleanup_stale()` (X11 orphan kill). **Rewrite** for the desktop analogue with an explicit **orphan-identity rule (BLOCKER):** identify our orphaned Chromium **only** by our relocated `--user-data-dir` (`profiles/<id>/`) or our cache-dir binary path — **never by process name** (the binary is literally `Chromium`; `pkill -f Chromium/chrome` would kill the user's Chrome + every Electron app = data loss). Same rule scopes `Singleton*`-lock deletion.
- **`get_status()`** — stop returning `vnc_ws_port`/`display` (§5.3).
- **`__init__`** — remove `self.vnc = VNCManager()`.
- `main.py` — delete VNC WS proxy + RFB helpers (`188-372`, `677-844`), clipboard endpoints (`590-676`).
- Drop `--use-angle=swiftshader` (`:384`) and the `viewport = screen_height - 133` hack (`:229-232`).

### 4.2 Storage paths (unify BOTH data roots) + creds-at-rest
- Relocate `DATA_DIR` (`database.py:14`, `/data`): mac `~/Library/Application Support/CloakBrowser Manager`, win `%APPDATA%\CloakBrowser Manager`; dir mode `0700`.
- **Unify the second data root.** The library caches the Chromium binary + GeoLite2 at `~/.cloakbrowser` (`config.py` `get_cache_dir`, ~200MB). Set **`CLOAKBROWSER_CACHE_DIR`** under our app-data dir so uninstall/cleanup has one root, not two.
- **Creds-at-rest encryption → DEFERRED to v1.1.** For v1: `0700` app-data + **mask/omit proxy creds in list responses** (they exist as `user:pass@host` in `models.py:13,74`). Documented limitation: creds live in an `0700` dir; **exclude the app-data/secrets dir from cloud backup** (iCloud/OneDrive/Time-Machine) where possible. (Full Keychain/DPAPI encryption is v1.1 — its marginal gain over `0700` is only cloud-backup leakage; cost is fiddly cross-OS key derivation.)
- **KEEP (cheap, severe-if-true): verify the patched Chromium's cookie store uses OS OSCrypt** (Keychain/DPAPI), not a null/fixed key — anti-detect builds sometimes disable OSCrypt, leaving profile cookies plaintext-recoverable from `profiles/<id>/`. Investigate in M0/M1b; escalate if null-keyed.

### 4.3 Security model (one coherent topology)
The **container was the boundary**; native removes it. Mechanisms:

**(a) Raw CDP port OFF by default; external automation is opt-in via the bearer-gated proxy (single topology).** The `cloakbrowser` library adds **no** `--remote-debugging-port` (Playwright drives via pipe); the TCP port is **Manager-added** (`browser_manager.py:207`) on the predictable 5100-5199 range — a full unauthenticated control channel on 100% of launches. **Default: do not open it** (Playwright's pipe still works). When a profile **opts into external automation** (a per-profile toggle; **relaunch-required** — you cannot add `--remote-debugging-port` to a running Chromium):
  - Launch with `--remote-debugging-port=0`; **discover the actual port by reading the `DevToolsActivePort` file** in the user-data-dir (line 1 = port, line 2 = ws path), with a startup wait (the file appears only after Chromium writes it).
  - Set **`--remote-allow-origins=<CANON app origin>`** (a concrete origin, **not `*`**) to close the web/rebinding vector (Chromium already gates this since M111; belt-and-suspenders).
  - **The external client connects through the Manager's existing bearer-gated CDP proxy** (`main.py:845-1016`: `/cdp`, `/cdp/json/*` with `webSocketDebuggerUrl` rewrite + all slash-variants, `/cdp/devtools/*`, `_proxy_cdp_websocket`) — NOT to the raw port directly. The bearer (§4.3c) gates the proxy path.
  - **Documented residual (BLOCKER-fix, one sentence a planner must keep):** *opt-in external automation means this profile's raw CDP ws is reachable by any same-user local process for the profile's lifetime* — `--remote-allow-origins` gates the Origin header, but a local non-browser process sends no Origin and can read `DevToolsActivePort`/scan loopback and skip the proxy. The bearer protects the proxy path (stops other-users via `0600` + remote/cross-origin), **not** the raw port against same-user processes. Acceptable under §2's single-user model **only when explicitly opted in**; never default-on.

**(b) UI auth = HttpOnly cookie, no `Secure`.** Do not put the token in localStorage/JS or a webview-injected header. The backend serves the SPA and sets an **`HttpOnly; SameSite=Strict` cookie (NO `Secure`)** scoped to `CANON_HOST` on a one-time bootstrap; page JS never reads it; `fetch`/WS auto-send it. `Secure` is dropped deliberately — it's a no-op on loopback (no MITM) and is inconsistently honored over `http://127.0.0.1` on WKWebView (would silently break Mac auth). Cookies are host-scoped, not port-scoped (RFC 6265) — so the **exact-Origin rule below is the real CSRF control**, not cookie secrecy. Disable the pywebview inspector in production. (Note: the current SPA has **no** stored-XSS sink — `name/notes/tags` render as escaped JSX, no `dangerouslySetInnerHTML` — so HttpOnly is precautionary, not closing a live hole.)

**(c) External-CDP auth = separate bearer, distinct from the UI cookie.** Write a per-session bearer to a `0600` app-data file the user's own Playwright reads, for the opt-in proxy path. **The reused `_check_auth` scaffold (`main.py:57-80`) compares BOTH the cookie AND `Authorization: Bearer` against the SAME global `AUTH_TOKEN` — split it:** cookie validated (`compare_digest`) against the **UI secret**, `Bearer` against a **distinct external secret**. Otherwise the two "credentials" collapse to one value that also sits in the webview cookie store.

**Host-header allowlist (exact-match).** Reject any request whose `Host` is not an **exact** member of `{127.0.0.1, localhost, [::1]}` AND whose port ≠ our ephemeral port (substring/`startswith` → `127.0.0.1.attacker.com` rebinding bypass). Reject missing `Host`; apply on the **WebSocket upgrade** too. **Discriminator:** valid credential required always; `Origin` (when present) must equal the app origin; absent `Origin` allowed **iff** the credential is valid (a legit external Playwright sends no Origin — don't block on Origin-presence). Re-examine the scaffold's exempt-list (`main.py:54` exempts `/api/status`, which leaks `binary_version` + counts).

**Loopback bind** (necessary, not sufficient).

### 4.4 Stealth defaults
- **Default `--fingerprint-platform` = host OS** (not `models.py`'s `windows` default). **Dedup the duplicate flag:** `get_default_stealth_args()` emits `--fingerprint-platform` AND `_build_fingerprint_args` (`browser_manager.py:391-394`) appends another from the model default → on a Mac, `config.py`'s protective `macos` and the Manager's `windows` are BOTH passed and last-wins decides (likely spoofing Windows). Ensure a single, host-matched `--fingerprint-platform` (a de-duped argv also keeps the oracle honest, §10). Cross-OS spoofing = explicit opt-in + "detectable" UI warning.
- **Sandbox ON by default; strip `--no-sandbox`.** `get_default_stealth_args()` adds `--no-sandbox` unconditionally (`config.py:50`, container-era). Native, a renderer pointed at hostile sites **by design** with the sandbox off turns any renderer RCE into host code execution. Strip it. Sandbox-on is **fingerprint-neutral-to-positive** (real Chrome is sandboxed; the sandbox is OS process isolation, orthogonal to the compiled fingerprint). The only real risk is operational: the Chromium Seatbelt sandbox may fail to init for an **unsigned downloaded** binary under the hardened runtime → **M0 must test the sandbox on the DOWNLOADED binary specifically** (not a dev-signed build). If it genuinely can't sandbox, escalate as a serious finding.

### 4.5 Keep (reused behind the wrapper)
CRUD + tags + notes; launch/stop; **opt-in** bearer-gated CDP proxy (§4.3a); `auto_launch` (staggered, §11); `geoip`; `headless`; **authenticated proxy (Playwright-native — unchanged)**; default bookmarks + DuckDuckGo prefs; binary download/extract/auto-update (partial re-port §6.4); `launch_args`; `color_scheme`/`user_agent`/`viewport` (library, via Playwright CDP emulation).

## 5. Frontend changes (`frontend/src/`)
1. **Rebuild `ProfileViewer` (~294 lines).** It is 100% noVNC/RFB over `/vnc` + get/set clipboard + CDP-copy, mounted by `App.tsx:245-253` for every running profile. Replacement: a native-window control panel (the OS window *is* the viewer) — status, Stop/Relaunch, and the CDP endpoint only when external automation is opted in. Rewire the `view` state machine (`App.tsx:99-103,130-134`).
2. **Auth gate.** `App.tsx:20-36` calls `/api/auth/status` at startup → with the cookie, return `{auth_required:false, authenticated:true}` + no-op login/logout; `LoginPage` dormant.
3. **Response fields.** `LaunchResponse.vnc_ws_port` is a required int → 500 once VNC is gone. Make `vnc_ws_port`/`display` nullable/removed in `models.py` AND `api.ts`. Keep `status` + `cdp_url` (null unless external automation opted in).
4. **Enumerated cleanup (mechanical, don't miss):** remove `ProfileForm` `clipboard_sync` toggle (drop column + migrate); delete `api.ts` `getClipboard`/`setClipboard` (`:151,157`), `novnc.d.ts`, the `@novnc/novnc` dep (`package.json:14`); **fix the broken tests** `api.test.ts:78` (asserts `vnc_ws_port:6100, display:":100"`) and `useProfiles.test.ts:46,54` fixtures.

## 6. Packaging

### 6.0 PyInstaller mode & driver
- **`onedir` mandatory on BOTH OSes** (onefile breaks macOS notarization — nested `node`+dylibs invisible to `codesign` — + Win AV + Playwright frozen `FileExistsError`).
- **Bundle Playwright's node driver** — `compute_driver_executable` resolves via `__file__` (breaks frozen). PyInstaller hook / `--collect-all playwright`, exclude `.local-browsers`.
- **Pin the backend** (`playwright` vs `patchright`, `browser.py:743`) in M0.

### 6.1 Windows event loop
`launch_persistent_context_async` runs inside FastAPI. Windows needs **`WindowsProactorEventLoopPolicy`** (Selector loop → `NotImplementedError` on subprocess). Also: pywebview owns the **main thread** (Cocoa/WKWebView) → uvicorn runs in a **background thread**, which must still get the Proactor policy, and `loop.add_signal_handler` is unavailable off-main-thread. Configure uvicorn `loop="asyncio"`. This four-way coexistence is an explicit **M0 exit gate**.

### 6.2 macOS signing/notarization
Sign + notarize + staple, hardened runtime. The frozen `node`/V8 needs **`com.apple.security.cs.allow-jit`** (+ `allow-unsigned-executable-memory`). Sign every nested Mach-O **inside-out** before notarizing (avoid `--deep`); scope `disable-library-validation` as narrowly as notarization allows. Entitlements govern the app's own process — the separately-signed downloaded Chromium is unaffected; its quarantine is stripped by `xattr -cr` (`download.py`, runs fine from a frozen app). Prereq: **Apple Developer cert (~$99/yr) — procure day 1.**

### 6.3 Windows install + first-run progress
- `.exe` (onedir) + installer (Inno Setup/NSIS). WebView2 Evergreen is often absent on Win10 → bundle the bootstrapper (pywebview doesn't ship it). Prereq: **Windows OV/EV code-signing cert — procure day 1 (1-3 wk identity validation).**
- **First-run progress (mandatory)** — see §6.4; must cover **both** the initial Chromium download **and** the deferred GeoLite2 download (first geoip-profile launch, possibly weeks later — a second silent stall otherwise) **and** a **download-failure/retry** state (network dies mid-download → don't brick; retry/resume + clear error).

### 6.4 Download path — a **partial re-port** of `download.py` (honest scope; not "wrapping")
`_download_and_extract` (`download.py:133`) → `_download_file` (`:246`) is synchronous, private, hookless; `_verify_download_checksum` (`:176`) **warns-and-returns** on missing `SHA256SUMS` and honors `CLOAKBROWSER_SKIP_CHECKSUM` — there is no fail-closed switch. Neither byte-progress nor fail-closed is achievable by "wrapping." Scope explicitly:
- **Fail-closed (no interception needed):** after the library downloads, do an **independent** SHA256 check in the Manager (fetch `SHA256SUMS` ourselves / pin the hash) and **refuse launch on mismatch or absence**; never set `SKIP_CHECKSUM` in shipped builds.
- **Progress:** either (v1-lazy) a coarse **"downloading… (no %)"** spinner keyed off partial-file size polling, or **re-implement the download loop** in the Manager for true byte-progress (defer % to when the spinner proves insufficient). Pick per the M0 finding.
- The native supply-chain chain (downloaded-unsigned → quarantine-strip → weakened entitlements → sandbox) is a net-new native risk — fail-closed-local + sandbox-on + narrow entitlements mitigate; residual = trust in the download origin (signature-pinning pushed upstream / done natively in the Go spec).

## 7. humanize
Reused as today (`browser_manager.py:224-225`). **Honest UI caveat:** it patches the Manager's own Playwright context, not what an external CDP client drives → inert for external automation (unchanged from today). A real human engine is the Go spec's concern.

## 8. Parity gap disposition (v2.1)

| # | Item | Disposition |
|---|---|---|
| 1 | ProfileViewer noVNC | Rebuild ~294 lines (§5.1) |
| 2 | Auth gate | Cookie + stub `/api/auth/status` (§5.2) |
| 3 | Launch-arg builder | Reused; **de-dup `--fingerprint-platform`** (§4.4) |
| 4 | Authenticated proxy | Reused (Playwright-native) |
| 5 | `DATA_DIR=/data` + `~/.cloakbrowser` | Per-OS + **unify both roots** + `0700` (§4.2) |
| 6 | Binary download/verify | **Partial re-port** — fail-closed + progress (§6.4) |
| 7 | geoip | Reused; deferred-download progress + failure state (§6.3) |
| 8 | WebRTC IP | Reused |
| 9 | Native-window-closed detection | **MUST-VERIFY in M0** (macOS app-stays-open may not fire `context.on("close")`) |
| 10 | Singleton lock / orphan cleanup | **Rewrite with identity rule** — match `user_data_dir`, never process name (§4.1) |
| 11 | CDP port 5100-5199 | Replaced by opt-in `DevToolsActivePort` ephemeral, proxy-gated (§4.3a) |
| 12 | Response fields | Fix nullable (§5.3) |
| 13 | CDP `/json` proxy | Reused **as the single opt-in external path**, bearer-gated (§4.3a) |
| 14 | CSWSH origin check | Replaced by split cookie/bearer + exact Host-allowlist (§4.3) |
| 15 | viewport −133 | Drop (§4.1) |
| 16 | Lifespan cleanup/auto_launch | `cleanup_stale` rewrite (§4.1); `auto_launch` stagger (§11); `cleanup_all` reused minus VNC |
| 17 | `launch_args` | Reused |
| 18 | `clipboard_sync` field | Drop + migrate (§5.4) |
| 19 | DELETE = stop + rmtree | **Fix**: Windows lock-race → terminate-then-retry + surface errors (not `ignore_errors=True`) |
| 20 | `/api/status` `binary_version` | Keep; source `get_effective_version()`; re-examine auth-exempt |
| — | `--no-sandbox` / `--use-angle=swiftshader` | Strip both (§4.4/§4.1) |

## 9. Milestones (re-split, re-estimated)

- **M0 — Hardened packaging spike (~1-2 wk) — gates everything.** Freeze `cloakbrowser+playwright+FastAPI` (onedir); includes minimal de-VNC of `launch()`. **Exit (both clean macOS M1 + Windows 10):** launch through an **authenticated proxy** via the **async** path, verify **exit IP** + a **CDP round-trip**, from a **hardened-runtime, dev/ad-hoc-signed** build; **uvicorn-in-background-thread + pywebview-main-thread + async Playwright succeed on Windows**; sandbox verified on the **downloaded** binary; `context.on("close")` fires on native close (#9); the HttpOnly-no-Secure cookie round-trips on **both** WKWebView + WebView2. *Honest: may bounce back to the Go decision.*
- **M1a — Usable core, unsigned (~1.5-2 wk).** De-VNC lifecycle (§4.1, incl. orphan-identity `cleanup_stale`) + per-OS data dir + unified cache root + host-OS platform default + de-dup + sandbox-on + env-sanitize + pywebview shell + **single-instance lock** (moved here — data-integrity, not polish: two instances → same `user_data_dir` → profile corruption) + auto_launch stagger.
- **M1b — Security + integrity (~1.5-2 wk).** Split cookie/bearer `_check_auth` + exact Host-allowlist (+ rebinding tests) + opt-in proxy-gated CDP (`DevToolsActivePort`, relaunch-required, `--remote-allow-origins`) + fail-closed download check + response fields + OSCrypt investigation.
- **M1c — UI rebuild (~1-1.5 wk).** ProfileViewer control-panel rebuild + auth-gate cookie path + enumerated frontend cleanup (§5.4).
- **M2 — Distributable (~3-5 days active + cert lead).** Signed+notarized `.dmg` (inside-out, allow-jit); signed `.exe` + WebView2 bootstrapper; app icon (`.icns`/`.ico`); log file + "reveal logs"; first-run progress polish. **Exit:** opens on clean M1 + clean Win10 (no Gatekeeper "damaged", no missing WebView2); second instance refuses cleanly; logs discoverable.

**Honest total ≈ 7-9 weeks** (M0 1-2 + M1a 1.5-2 + M1b 1.5-2 + M1c 1-1.5 + M2 ~1 + buffer), **contingent on M0 passing** — M0 is a real coin-flip. Cert procurement starts day 1, parallel to M0.

## 10. Testing, evidence & the oracle
- pytest: CRUD, launch/stop mocks, split cookie/bearer + **exact** Host-allowlist (incl. rebinding-bypass cases), raw-port-off-by-default, `cleanup_stale` identity rule (must NOT match a decoy `Chromium`), response-schema, fail-closed download check.
- vitest: control-panel component; api.ts changes; fixed `api.test.ts`/`useProfiles.test.ts`.
- **Integration (per PR):** native window opening from the frozen onedir build; `curl` rejecting missing cookie + `Host: 127.0.0.1.evil.com`; default profile opening **no** listening port (`lsof`/`netstat`); opt-in external Playwright connecting only through the bearer-gated proxy.
- **Oracle baseline (for the Go rewrite — must be a diff-grade capture, not a smoke test):** because both apps spawn the SAME binary with the SAME flags, the fingerprint is identical by construction; the real divergence surface is (i) the **exact launch argv** the app builds and (ii) the Playwright-emulated `color_scheme`/`user_agent`/`viewport`. So §10 records, per fixed profile: the **exact argv**, and a **per-attribute fingerprint dump** (`navigator.*`, canvas/WebGL renderer, font metrics, emulated UA/scheme/viewport) — plus the detection-suite pass/fail (sannysoft/creepjs/pixelscan/browserscan) **sandboxed**. That argv+attribute record is what the Go build diffs against.

## 11. Risks & open questions
- **[RISK] PyInstaller + Playwright freeze** — the hardened M0 spike is the go/no-go (env pollution, Windows Proactor + thread model, notarizing a JIT/node bundle, cookie-over-loopback on WKWebView, sandbox on the downloaded binary).
- **[RISK] Supply-chain chain** (§6.4) — mitigated by fail-closed-local + sandbox-on + narrow entitlements; residual = trust in download origin.
- **[RISK] Sandbox requirement** — if the downloaded binary can't sandbox (§4.4), escalate; may force a rethink.
- **[TRACK] Creds-at-rest encryption → v1.1** (Keychain/DPAPI). v1 limitation documented (§4.2).
- **[TRACK] App self-update** — updating the PyInstaller **bundle** (Sparkle/macOS, Squirrel/MSIX/Windows), distinct from the binary auto-update. Deferred past v1; don't paint into a corner (version endpoint / update channel).
- **[GAP→M1b] DELETE data-loss + dead-proxy UX** — `rmtree` terminate-then-retry (§8 #19); a launched profile over a dead proxy (every page fails) needs a clear UI state.
- **[GAP→M2] Uninstall** — remove the unified app-data root (§4.2); document the manual `/data`→native migration (non-goal to automate, §2).
- **[OPEN] Progress mechanism** (coarse spinner vs download re-implement) — decide from the M0 download finding (§6.4).
- **[OPEN] color_scheme/user_agent/viewport** — Playwright CDP emulation (flagged "detectable" in-code); acceptable v1, captured in the oracle (§10).
```
