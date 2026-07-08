# CloakBrowser Desktop M1c — Running-View ("Mission Control") Design

**Date:** 2026-07-05
**Branch:** `feature/desktop-native-app`
**Status:** approved (design), pending spec review

## Problem

On desktop the browser opens as a **native OS window** (M0 dropped the in-container
KasmVNC/X11 stack). But the frontend still renders the container-era `ProfileViewer`,
which is 100% noVNC: it opens `ws://…/api/profiles/{id}/vnc`, the backend immediately
closes it (`main.py:784-799`, code `4006 "VNC not available"`), and the viewer paints a
**blank white canvas**. Users read this as "the browser didn't load" — even though a full
Chromium (6 processes, live CDP on the allocated port) launched fine, just hidden **behind**
the maximized app window.

## Goal

Replace the dead noVNC viewer with a **mission-control panel**: the native window is where
you browse; the app *controls* it over the CDP the Manager already exposes. No embedded
pixels, no screenshot mirror (a mirror can't be clicked, and clicking would mean
re-implementing input injection over CDP = rebuilding the noVNC we're removing).

## Scope decisions (user-confirmed)

- **App role:** mission control, **no live-preview mirror**.
- **Cleanup depth:** frontend-only. **Leave** the dead backend RFB proxy (~546 lines),
  `vnc_manager.py`, and `/clipboard` endpoints as an inert tombstone — the container path
  may reclaim them later. This milestone only *adds* backend endpoints; it deletes only
  frontend noVNC.
- **No mirror / no in-app interaction surface** beyond: focus window, list/activate/close
  tabs, open a URL.

## Architecture

```
launch → browser_manager auto-raises native window (Page.bringToFront)
app RunningPanel  ──poll 2s──►  GET  /api/profiles/{id}/cdp/json/list      (exists)
                  ──click tab─►  POST /api/profiles/{id}/cdp/json/activate/{tid}   (new)
                  ──open URL──►  POST /api/profiles/{id}/cdp/json/new?url=…        (new)
                  ──close [x]─►  POST /api/profiles/{id}/cdp/json/close/{tid}      (new)
```

All four proxy Chrome's DevTools **HTTP** endpoints on `127.0.0.1:{cdp_port}` — the same
loopback CDP the existing `cdp_json_list`/`cdp_json_version` proxies use (`main.py:820-873`).
No new sockets, no WS for the control actions.

### Backend — 3 new endpoints (`backend/main.py`, beside `cdp_json_list`)

Mirror the existing proxy shape: look up `browser_mgr.running.get(profile_id)` → 404 if
absent; `httpx.AsyncClient` GET/PUT to `http://127.0.0.1:{running.cdp_port}/json/…` →
502 on unreachable; return **JSON** (frontend `request()` always calls `res.json()`, so we
must not pass Chrome's plain-text bodies through).

- `POST …/cdp/json/activate/{target_id}` → Chrome `GET /json/activate/{id}`. Returns
  `{"ok": true}`; Chrome 404 ("No such target") → HTTP 404. Activating **raises the OS
  window** and focuses the tab (Chrome calls the platform foreground API). This backs both
  "Focus browser window" (activate the active tab) and per-row tab clicks.
- `POST …/cdp/json/new?url=<u>` → Chrome `PUT /json/new?<u>` (GET was removed in Chromium
  ~M111). Chrome appends the raw query string as the target URL, so build the upstream URL
  as `/json/new?` + `urllib.parse.quote(u, safe="")`; return the new target JSON.
  **Risk:** modern Chrome may gate `/json/new` (Host/`--remote-allow-origins` checks). The
  Manager already launches with `--remote-debugging-port`, and the call is server-side from
  `127.0.0.1`, so it should pass — but **Task 1 verifies this on the VM first**. Fallback if
  gated: open a `Page` via the existing CDP WS proxy and `Page.navigate` (documented in the
  plan, only implemented if the HTTP path fails).
- `POST …/cdp/json/close/{target_id}` → Chrome `GET /json/close/{id}`. Returns `{"ok": true}`;
  Chrome 404 → HTTP 404.

### Backend — auto-raise on launch (`backend/browser_manager.py`)

In `launch()`, after the context exists and `context.pages` is populated (~`:292`), before
returning the `RunningProfile`:

```python
try:
    if context.pages:
        await context.pages[0].bring_to_front()
except Exception as exc:
    logger.warning("bring_to_front failed for %s: %s", profile_id, exc)
```

Unconditional + guarded (harmless in the container; fixes "window hidden behind app" on
desktop). Does not affect launch success on failure.

### Frontend — `RunningPanel.tsx` replaces `ProfileViewer`

New `frontend/src/components/RunningPanel.tsx`, rendered at `App.tsx:245` in place of
`<ProfileViewer>` (same guard: `view === "view" && selected.status === "running"`). Props:
`profileId: string`, `cdpUrl: string | null`. React 19 + Tailwind + lucide (existing stack).

- `useEffect` polls `api.listTabs(profileId)` every 2s (interval cleared on unmount);
  filters to `type === "page"`. First tab treated as active for the Focus button.
- **Focus browser window** button → `api.activateTab(profileId, tabs[0].id)`.
- **Address bar** (input + Go) → `api.openUrl(profileId, url)` then refresh list.
- **Tab rows**: title + url (truncated); click → `activateTab`; `[x]` → `closeTab` then refresh.
- **CDP url** shown with a copy button (reuse `cdpUrl`).
- Poll 404 (profile stopped) → call `onDisconnect()` (same prop `ProfileViewer` had) so
  `App` returns to the edit/empty view. Empty list → "No tabs". Poll network error →
  keep last list, no crash.

Stop stays in the header (`App.tsx:193` → `onStop={handleStop}`); the panel does **not**
duplicate it.

### Frontend — `api.ts` additions

```ts
export interface CdpTarget {
  id: string; type: string; title: string; url: string;
  webSocketDebuggerUrl?: string;
}
// in `api`:
listTabs:    (id: string) => request<CdpTarget[]>(`/api/profiles/${id}/cdp/json/list`),
activateTab: (id: string, t: string) => request<{ ok: boolean }>(`/api/profiles/${id}/cdp/json/activate/${t}`, { method: "POST" }),
openUrl:     (id: string, url: string) => request<CdpTarget>(`/api/profiles/${id}/cdp/json/new?url=${encodeURIComponent(url)}`, { method: "POST" }),
closeTab:    (id: string, t: string) => request<{ ok: boolean }>(`/api/profiles/${id}/cdp/json/close/${t}`, { method: "POST" }),
```

### Deletions (frontend only)

- `frontend/src/components/ProfileViewer.tsx` — remove (replaced).
- `frontend/src/novnc.d.ts` — remove.
- `@novnc/novnc` — remove from `frontend/package.json` (+ lockfile).
- Remove the `ProfileViewer` import + `handleVncDisconnect` rename (keep the handler,
  rewire as `onDisconnect` for `RunningPanel`).
- `api.setClipboard`/`api.getClipboard` stay (backend `/clipboard` tombstone stays); the
  VNC-era clipboard *UI* (Ctrl+V interception) dies with `ProfileViewer`.

## Error handling

| Case | Behavior |
|---|---|
| Profile not running | endpoints → 404; panel `onDisconnect()` → leave view |
| CDP unreachable | endpoints → 502; panel keeps last tab list, retries next poll |
| `/json/new` gated by Chrome | Task 1 catches it on VM; fall back to WS `Page.navigate` |
| auto-raise throws | logged, launch still succeeds |
| Empty tab list | "No tabs" placeholder |

## Testing

- **Backend** (`backend/tests/test_api.py`, mirror `test_set_clipboard_success`): mock
  `RunningProfile(cdp_port=5100)` in `browser_mgr.running`, patch `httpx.AsyncClient` to a
  fake 200 → assert activate/close return `{"ok": true}` and hit the right upstream path;
  not-running → 404; upstream 404 → 404.
- **Backend** (`test_browser_manager.py`): `launch()` calls `context.pages[0].bring_to_front()`
  (mock context) and swallows its exception.
- **Frontend** (`RunningPanel.test.tsx`, vitest + testing-library, mirror
  `useProfiles.test.ts`): mocked `listTabs` → tab titles render; tab click → `activateTab(id, tid)`;
  URL + Go → `openUrl(id, url)`; `[x]` → `closeTab(id, tid)`.
- **Integration (the real proof, on the Win11 VM):** launch → native window auto-raises →
  panel lists tabs → click raises window → open URL creates a tab → no blank canvas.

## Out of scope

Backend RFB/`vnc_manager`/`/clipboard` removal (tombstone kept); Dockerfile KasmVNC strip;
screenshot preview; in-app interactive browsing; window management beyond CDP activate.
