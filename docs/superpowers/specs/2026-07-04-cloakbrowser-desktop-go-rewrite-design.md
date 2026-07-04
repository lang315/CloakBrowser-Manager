# CloakBrowser Desktop Manager — Go Rewrite (Long-term) — Design

**Date:** 2026-07-04
**Status:** Approved for planning; **starts after** the Python-native app ships
**Companion spec:** `2026-07-04-cloakbrowser-desktop-python-native-design.md` — **the reference oracle** for stealth parity

## 1. Context & goal

After the Python-native desktop app ships (companion spec), rewrite it in **Go** as the long-term codebase: a single static native binary, no Python/Node runtime, owned end-to-end. The user is a Go developer and intends to develop the product in Go long-term — which makes the "divergence tax" (chasing upstream `cloakbrowser`) an accepted, deliberate cost rather than a drawback.

**Critical enabler:** the shipped Python app is the **stealth-parity oracle**. Every fingerprint/behavior the Go build produces is diffed against the Python app's known-good output (the detection-suite baseline captured in the Python spec §10). This removes the biggest fear of a from-scratch stealth reimplementation — validation is *comparison against a working reference*, not guesswork against live detection sites.

**Key fact (settled during review):** the stealth is **compiled into the patched Chromium binary** and activated by CLI `--fingerprint-*` flags (`cloakbrowser/config.py:37-38,59-60`). Neither language "owns" the stealth. Go's job is to build the right flags, spawn the binary, and reproduce the thin Playwright-provided layer (proxy auth, a few CDP-emulation settings).

## 2. Non-goals
- Not started until the Python app is shipped and its oracle baseline exists.
- Not a feature expansion over the Python app (parity first), except where noted (humanize, §8).
- No Playwright, no Python, no Node runtime in the shipped artifact.

## 3. Architecture

```
┌─ Wails v2 window (WKWebView / WebView2) ─────────┐
│  React SPA (reused from Python app, as-is)        │
└──────────────┬────────────────────────────────────┘
       /api/*   │  AssetServer.Handler → Go http.ServeMux   (UI; HTTP only, no WS)
┌──────────────▼──────────────── Go binary ─────────────────────┐
│  same http.ServeMux ALSO on 127.0.0.1:PORT TCP listener        │
│    (external Playwright/Puppeteer → token-gated CDP proxy)      │
│  store(modernc sqlite) · profile · browser · binary · api      │
│  Go→JS push via Wails EventsEmit (NOT webview WebSocket)        │
└──────────────┬─────────────────────────────────────────────────┘
      spawn     │ patched Chromium + --fingerprint-* + --remote-debugging-pipe
┌──────────────▼──────────┐
│ Profile = native window  │
└──────────────────────────┘
```

**Confirmed by feasibility review (`go-arch`):**
- **2-listener topology is correct.** Wails v2 has **no** "load external URL as main content" (embedded assets only); `AssetServer.Handler` is a real `http.Handler` for the UI, and the same `*http.ServeMux` also serves a real `127.0.0.1:PORT` TCP listener for external CDP clients (which cannot reach the `wails://` internal scheme).
- **`AssetServer.Handler` cannot serve WebSockets** (no `http.Hijacker` over `wails://`). So: UI push uses **Wails `EventsEmit`** (e.g. first-run download progress, live status); external CDP WS runs on the **real TCP listener** (fine). Pin **Vite 4** for `wails dev` (AssetServer.Handler fallback is broken on Vite ≥5).
- **modernc.org/sqlite** (pure-Go, no cgo) for the store. Note: Wails macOS still needs cgo (WebKit), so **per-OS build runners are mandatory** regardless.

## 4. What ports from the `cloakbrowser` library

Total lib = 6894 lines, but the **used** subset is far smaller. Estimated Go port ≈ **1000-1300 lines** (excluding humanize):

| Source | Lines | Nature | Go port |
|---|---|---|---|
| `config.py` | 238 | flag strings, platform map, version map, binary paths | **Trivial** — pure Go, no deps |
| `download.py` | 578 | download + SHA256 + tar/zip extract + auto-update marker | **Mechanical** — `net/http`+`archive/tar`+`archive/zip`+`crypto/sha256`, zero third-party (imports no Playwright) |
| `geoip.py` | 315 | GeoLite2-City `.mmdb` reader + country→locale + proxy-IP resolve | mmdb read via `oschwald/maxminddb-golang`/`geoip2-golang`; rest mechanical |
| `browser.py` (used subset) | ~150 of 1191 | one persistent-context launch path + `build_args` dedup | Mechanical string-building; the file is 6 near-duplicate variants + 27% docstrings — we implement **one** async path |
| `browser_manager._build_fingerprint_args` | ~37 | `--fingerprint-*` f-strings | **Verbatim** |

The Manager's own parity surface (post-VNC-drop) is ~800 lines of mostly mechanical CRUD (`database.py`, `models.py`, non-VNC `main.py`).

## 5. The genuinely-hard parts (design them explicitly)

### 5.1 Proxy authentication — extension, NOT `Fetch.continueWithAuth` (go-arch + stealth-sec converge)
`Fetch.enable` pauses **every** request until the client responds, dies on disconnect, and collides with any external Playwright that also enables Fetch — wrong for an interactively-driven browser.
**Design:** a **background-only MV3 proxy-auth extension** (`chrome.webRequest.onAuthRequired` returning credentials), loaded via `--load-extension`. `cloakbrowser/browser.py build_args` **already accepts `extension_paths`**, so the patched binary supports it. No CDP footprint, survives reconnects, invisible to page JS (no content scripts / `web_accessible_resources`). Credentials **never** in `--proxy-server=` (Chromium ignores inline creds there + leaks them in the process list).
Also re-port the special-char credential handling the library hardened (`browser.py` re-encoding, bugs **#157** password-truncation-at-`=`, **#182** Google-domain 407) — validate against the Python oracle. Re-port `_normalize_proxy` (`host:port:user:pass` shorthand) + `_validate_proxy` (`browser_manager.py:22-53`).

### 5.2 Single CDP owner via `--remote-debugging-pipe` (go-arch MAJOR + stealth-sec CRITICAL)
Two CDP clients on one debug **port** fight (documented `Network.enable timed out`). And a raw loopback debug port is itself unauthenticated/hijackable by any local process.
**Design:** launch with **`--remote-debugging-pipe`** (no TCP CDP port exposed). The Go app owns the pipe and re-exposes a **token-gated, pure-passthrough** CDP proxy on the TCP listener (it forwards bytes; it does **not** enable CDP domains itself → no domain-ownership conflict with the external client). Reproduce the Python proxy's `/json/version` + `/json/list` rewrites and **all 6 slash-variants** + suffix rewrite + ws/wss selection (`main.py:845-911`), or `connect_over_cdp()` breaks.

### 5.3 CDP-emulation parity (small but validate)
`color_scheme`/`user_agent`/`viewport` are Playwright **context kwargs** applied via CDP Emulation, not binary flags. Go maps them: `user_agent` → `--user-agent` or `Network.setUserAgentOverride` (with Client-Hints `userAgentMetadata`); `viewport` → `--window-size` (a real OS window!) or `Emulation.setDeviceMetricsOverride`; `color_scheme` → `Emulation.setEmulatedMedia`. ~80-150 lines. **Validate each against the oracle** — the in-code comment flags CDP emulation as "detectable," so parity here is a stealth-regression watch item.

### 5.4 Native-window lifecycle & orphan prevention (go-arch MINOR)
- Watch the Chromium process exit (`cmd.Wait()`) to reconcile status → stopped (replaces Playwright's `context.on("close")`).
- Prevent orphans on app-kill: **Windows** — Job Object with `KILL_ON_JOB_CLOSE`; **macOS** — `Setpgid` + kill the process group.
- Clean stale `Singleton*` locks before launch (cross-platform; Chromium leaves them on crash).

### 5.5 Binary integrity — fail CLOSED (stealth-sec HIGH)
Unlike the Python library (fails **open** on missing checksum, honors `CLOAKBROWSER_SKIP_CHECKSUM`), the Go downloader must **fail closed**: keep TLS verify, **signature-pin** the download against a public key baked into the app (Ed25519/minisign or a pinned SHA256), no skip flag in shipped builds. Replicate the tar/zip **path-traversal + symlink guards** (extraction-RCE) from `download.py`. On macOS strip quarantine **only after** verification (`xattr -cr`, replicating `download.py`). This is a security **improvement** over the reused-as-is Python path.

## 6. Security model (same as Python spec, enforced in Go)
Per-session bearer token on **every** `/api` request incl. the CDP WS proxy; strict **Host-header allowlist** (`127.0.0.1`/`localhost`); loopback bind; `--remote-debugging-pipe` so no raw CDP port exists. Proxy passwords encrypted at rest (Keychain/DPAPI), app-data `0700`, credentials masked/token-gated in list responses.

## 7. Data & stealth defaults
Per-OS app-data dir (mac `~/Library/Application Support/CloakBrowser Manager`, win `%APPDATA%`). Default `--fingerprint-platform` to the **host OS** (never silent Windows-on-Mac); keep per-profile `--fingerprint-gpu-*` consistent with the host platform (avoid cross-profile GPU linkability, stealth-sec MED). Bind WebRTC IP to the resolved proxy exit-IP; derive timezone/locale from the proxy when set — never fall through to the host TZ (stealth-sec LOW, more fragile natively than in the container).

## 8. humanize (deferred phase / optional)
The Python app reuses the library's `humanize` for free but it is **inert for external automation** (it patches the Manager's Playwright context, which external CDP clients don't drive). Making it *real* in Go is a **new product**, not parity: port the algorithms (config presets `default`/`careful`, Bezier mouse, typing cadence + mistype, scroll physics, actionability via CDP isolated worlds — ~1500-2500 Go lines by review estimate, correctness-risk not volume-risk) and expose a **new automation surface** `POST /api/profiles/<id>/human/{move,click,type,scroll}` driving the browser via chromedp `Input.dispatch*`. **This is a final phase (M3) and must justify itself independently** — most users drive via their own external CDP, not our REST API. Skip unless explicitly wanted.

## 9. Milestones (risk-sliced) — usable early, expensive tail last

| Milestone | Content | Exit criteria |
|---|---|---|
| **M0 — tracer** | Wails scaffold + reuse SPA; port `config`/`download`(fail-closed)/`_build_fingerprint_args`; spawn binary with host-matched flags via `os/exec`; native window; stop (Job Object/killpg); **local unsigned build**. | Create 1 profile → binary downloads (progress) → native window opens with fingerprint **matching the Python oracle** → stop kills it. **Usable locally.** |
| **M1 — parity core** | Full CRUD + tags/notes + auto_launch + headless + color_scheme/UA/viewport (§5.3) + bookmarks/DDG prefs; per-OS data dir; Singleton cleanup; unique CDP pipe; lifespan wiring; frontend rework carried over from Python app; **signed .dmg + .exe** opening on clean machines. | Feature-parity with Python M1; installers open on clean M1/Win10. |
| **M2 — network/stealth** | Token-gated CDP proxy over pipe + `/json` rewrite parity + Host allowlist; authenticated proxy via extension (§5.1); geoip mmdb + WebRTC exit-IP + TZ/locale-from-proxy; creds encrypted at rest. | External Playwright `connect_over_cdp` works with token; authenticated proxy verified; **detection-suite parity with the oracle**. |
| **M3 — humanize** (optional, separate decision) | human engine + automation API (§8). | Only if greenlit. |

## 10. Testing & evidence — diff against the oracle
- Go unit tests: fingerprint-arg builder (**golden test** vs the Python app's emitted args), proxy normalize/validate, binary tag/version/URL resolver + fail-closed verify + extraction guards, store CRUD.
- **Oracle diffing (the core validation).** Both apps spawn the SAME binary with the SAME `--fingerprint-*` flags, so the fingerprint is identical *by construction* — the real divergence surface is only (i) the **exact launch argv** the app builds and (ii) the Playwright-emulated `color_scheme`/`user_agent`/`viewport`. So the diff is not "detection pass/fail" (a smoke test) — it is: for each fixed profile, assert the Go build emits the **byte-identical de-duped argv** the Python oracle recorded (Python spec §10), and produces the **same per-attribute fingerprint dump** (`navigator.*`, canvas/WebGL renderer, font metrics, emulated UA/scheme/viewport). Detection-suite results (sannysoft/creepjs/pixelscan/browserscan) are the coarse backstop on top. Any argv or per-attribute divergence is a stealth regression to fix before shipping that milestone.
- Integration: native window opens from the packaged Go app on clean M1/Win10; `/api` rejects missing token / wrong Host; external Playwright connects only with the token.

## 11. Risks & open questions
- **[RISK] Stealth-parity validation** — mitigated by the oracle, but CDP-emulation items (§5.3) and proxy edge cases (§5.1) are where regressions hide. Budget iteration against the detection suite.
- **[RISK] Divergence tax (accepted)** — `cloakbrowser` ships frequent patches (proxy #157/#182, per-platform binary versions, binary-path layout). Go must chase flag/version/layout changes; `get_binary_path` layout changes break silently. Accepted deliberately (user owns the stack in Go). Add a CI check that pins/verifies the expected binary layout.
- **[OPEN] humanize (§8)** — build in M3 or never; decide when parity is done.
- **[OPEN] `--no-sandbox`** — inherit the Python app's resolved decision.
- **[OPEN] Wails packaging depth** — Vite-4 pin for dev; WebView2 bootstrapper bundling on Win10; macOS notarization of a binary-spawning Wails app (replicate quarantine strip).
```
