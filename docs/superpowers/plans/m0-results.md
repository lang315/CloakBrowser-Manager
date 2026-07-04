# M0 Results — Tasks 5 + 6 (bundled)

Branch: `feature/desktop-native-app`
Scope: native-launch proof (non-frozen backend, then frozen `.app`) + sandbox-on fix.

## Task 6 — strip `--no-sandbox`

**Finding: two independent sources inject `--no-sandbox`, not one.**

1. `cloakbrowser.config.get_default_stealth_args()` unconditionally includes
   `--no-sandbox` (container-era). Gated by `launch_persistent_context_async(stealth_args=...)`
   — `stealth_args=False` skips it. Safe to disable wholesale: the only other
   two defaults that function contributes (`--fingerprint=<seed>`,
   `--fingerprint-platform=`) are already supplied unconditionally by the
   Manager's own `_build_fingerprint_args()`, since the DB schema guarantees
   `fingerprint_seed` (`NOT NULL`) and `platform` (`DEFAULT 'windows'`) are
   always set. `--enable-automation`/`--enable-unsafe-swiftshader` suppression
   (`ignore_default_args=IGNORE_DEFAULT_ARGS`) is applied unconditionally by
   `launch_persistent_context_async` regardless of `stealth_args` — unaffected.
2. **Playwright's own Chromium launcher** (`_innerDefaultArgs()` in the bundled
   Node driver, `playwright/driver/package/lib/coreBundle.js`) pushes
   `--no-sandbox` by default: `if (options.chromiumSandbox !== true) chromeArguments.push("--no-sandbox")`.
   cloakbrowser never sets `chromium_sandbox`, so this fires regardless of
   `stealth_args`. This was **not documented anywhere in cloakbrowser** and
   was only found by reading the driver bundle after `stealth_args=False`
   alone empirically failed to remove the flag (see below) — grepping the
   whole cloakbrowser package confirms `--no-sandbox` has exactly one Python-level
   source (`config.py:50`), so the second source had to be in Playwright itself.

**Fix** (`backend/browser_manager.py`, `BrowserManager.launch()`): pass both
`stealth_args=False` and `chromium_sandbox=True` to
`launch_persistent_context_async(...)`. `chromium_sandbox` isn't a named
parameter of that wrapper — it flows through its `**kwargs` straight into
Playwright's real `launch_persistent_context()` call, which is exactly where
Playwright reads it.

**Test**: `backend/tests/test_m0_sandbox.py` (new). Asserts on the actual
kwargs passed to the (mocked) `launch_persistent_context_async` call —
`stealth_args is False` and `chromium_sandbox is True` — plus a regression
guard that `--fingerprint=`/`--fingerprint-platform=` are still present in
`args`. A test on `_build_fingerprint_args()` alone (the plan's original
suggestion) would have passed trivially before *and* after the fix, since
that method never emitted `--no-sandbox` in the first place — confirmed by
reverting the source change and observing `test_m0_sandbox.py` go red
(`KeyError: 'stealth_args'`) while the rest of the suite stayed green.

Full suite: `./.venv/bin/python -m pytest backend/tests -q` → **190 passed**.

## Task 5 — launch verification

| Check | Result | Evidence |
|---|---|---|
| Chromium binary downloads on first run | **PASS** | `cloakbrowser` log: `Download complete: 140 MB`, `SHA256SUMS signature verified: Ed25519 OK`, `Checksum verified: SHA-256 OK`, extracted to `chromium-145.0.7632.109.2`. Launch endpoint returned `200`. |
| Native Chromium process spawns | **PASS** | `POST /api/profiles/{id}/launch` → `200 {"status":"running",...}`; `ps aux` showed the main `Chromium` process plus GPU/renderer/utility helper processes, all in state `S`/`Ss` (running), main process alive 23s+ with no restart/respawn. |
| `--no-sandbox` absent from the launched Chromium's command line | **PASS** (after both-flags fix; **FAIL** with `stealth_args=False` alone) | `ps aux \| grep -i chromium \| grep -v grep \| grep -c -- "--no-sandbox"` → `0` across every process (main + GPU + 2x renderer + 2x utility). Before adding `chromium_sandbox=True`, the identical check showed `--no-sandbox` still present (Playwright's own default — see Task 6 finding). |
| Sandbox initializes on the downloaded/unsigned binary (no crash) | **PASS** | All helper processes carry `--seatbelt-client=<fd>` (macOS Seatbelt sandbox handshake token — only present when the sandbox is actually engaged). Main process + helpers stayed alive (`ps -p ... -o stat,etime`: `Ss`/`S`, `00:23` elapsed) with no crash/defunct/respawn. This directly answers the spec §4.4 risk ("Seatbelt may fail to init for an unsigned downloaded binary under the hardened runtime") — it did not fail on this downloaded, unsigned, dev (non-hardened-runtime) build. |
| Bonus: stealth not regressed by the sandbox change | **PASS** | Connected over CDP (`ws://127.0.0.1:5100/devtools/browser/...`) via Playwright's `connect_over_cdp`: `navigator.webdriver = False`. |
| Frozen `.app` starts, runs its own uvicorn | **PASS** | `open "desktop/dist/CloakBrowser Manager.app"`; after 15s, `ps aux` showed the app process alive; `lsof -a -p <pid> -i -P` showed `TCP localhost:56950 (LISTEN)` plus an `ESTABLISHED` connection from the webview window; `curl http://localhost:56950/api/status` → `200 {"running_count":0,"binary_version":"146.0.7680.177.5","profiles_total":0}`. GUI itself was not driven (not required — process+port+API is sufficient evidence uvicorn started correctly inside the frozen bundle). App quit cleanly (`kill`); port released. |

### Full downloaded-binary Chromium command line (post-fix, main process)

```
/tmp/cbm-m0/cache/chromium-145.0.7632.109.2/Chromium.app/Contents/MacOS/Chromium
--disable-field-trial-config --disable-background-networking --disable-background-timer-throttling
--disable-backgrounding-occluded-windows --disable-back-forward-cache --disable-breakpad
--disable-client-side-phishing-detection --disable-component-extensions-with-background-pages
--disable-component-update --no-default-browser-check --disable-default-apps --disable-dev-shm-usage
--disable-edgeupdater --disable-extensions --disable-features=... --enable-features=CDPScreenshotNewSurface
--allow-pre-commit-input --disable-hang-monitor --disable-ipc-flooding-protection --disable-popup-blocking
--disable-prompt-on-repost --disable-renderer-backgrounding --force-color-profile=srgb
--metrics-recording-only --no-first-run --password-store=basic --use-mock-keychain --no-service-autorun
--export-tagged-pdf --disable-search-engine-choice-screen --unsafely-disable-devtools-self-xss-warnings
--edge-skip-compat-layer-relaunch --disable-infobars --disable-search-engine-choice-screen --disable-sync
--ignore-gpu-blocklist --disable-infobars --test-type --use-angle=swiftshader --fingerprint=55205
--fingerprint-platform=windows --fingerprint-screen-width=1920 --fingerprint-screen-height=1080
--remote-debugging-port=5100 --user-data-dir=/tmp/cbm-m0/profiles/ecdef23c-271f-4fa8-a6ca-8fb5c11a86aa
--remote-debugging-pipe about:blank
```

No `--no-sandbox` anywhere in the line (nor in any GPU/renderer/utility helper's command line).

## Notes / follow-ups for final whole-branch review (not acted on here)

- `_build_fingerprint_args()` still emits `--test-type` with the comment
  `# suppress "unsupported flag: --no-sandbox" bad flags warning`. That flag
  is stale now that `--no-sandbox` is gone, but `--test-type` also suppresses
  other first-run infobars/warnings and wasn't in scope for this task
  (surgical fix only) — flagging for the final review pass.
- The design spec (`2026-07-04-cloakbrowser-desktop-python-native-design.md:146`)
  also calls for stripping `--use-angle=swiftshader` (forces software GL,
  a container/no-GPU artifact) — out of scope for Task 6 (`--no-sandbox` only)
  but tracked there for whichever task owns §4.1.
- `task-5-brief.md` / `task-6-brief.md` referenced by the dispatch prompt do
  not exist in `.superpowers/sdd/` (only tasks 1-4 have brief/report files).
  Worked from the bundled dispatch instructions plus the master plan
  (`docs/superpowers/plans/2026-07-04-cloakbrowser-desktop-m0-spike.md`,
  Task 5/6 sections) instead.
