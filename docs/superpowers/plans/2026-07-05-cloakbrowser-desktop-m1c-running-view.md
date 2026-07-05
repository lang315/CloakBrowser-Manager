# CloakBrowser Desktop M1c — Running-View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dead noVNC `ProfileViewer` with a CDP-driven "mission-control" panel that focuses/lists/controls the native Chromium window.

**Architecture:** Add 3 backend endpoints proxying Chrome's `/json` HTTP CDP (activate/new/close) beside the existing `cdp_json_list` proxy, plus an auto-raise on launch. The frontend gains 4 thin `api.ts` methods and a new `RunningPanel` component; `ProfileViewer` + `@novnc/novnc` are deleted. Backend RFB/vnc_manager/clipboard code is left as an inert tombstone.

**Tech Stack:** FastAPI + httpx (backend), React 19 + Tailwind + lucide-react + vitest/testing-library (frontend). Spec: `docs/superpowers/specs/2026-07-05-cloakbrowser-desktop-m1c-running-view-design.md`.

## Global Constraints

- Branch: `feature/desktop-native-app`. Do not work on `main`.
- Backend endpoints MUST return JSON — the frontend `request()` helper always calls `res.json()`; never pass Chrome's plain-text bodies through.
- Do NOT delete backend VNC code (`vnc_manager.py`, the RFB proxy block, `vnc_proxy`, `/clipboard` endpoints). Scope decision: tombstone kept. This milestone only *adds* backend endpoints.
- Backend tests run from repo root: `pytest` (pyproject sets `testpaths=backend/tests`, `asyncio_mode=auto` — async tests need no decorator).
- Frontend: `cd frontend && npm test` (vitest run) and `npm run build` (`tsc -b` under `strict` + `noUnusedLocals`/`noUnusedParameters`/`noUncheckedIndexedAccess`, then vite build). `tsc` MUST pass — under `noUncheckedIndexedAccess`, `tabs[0]` is `CdpTarget | undefined` and must be guarded.
- Chrome DevTools HTTP contract: `/json/activate/{id}` and `/json/close/{id}` are GET (return plain text, 404 on unknown id); `/json/new?<url>` is PUT (Chromium ≥ M111) and returns the new target JSON. Chrome appends the raw query string as the target URL.
- Endpoint auth/host-allowlist is handled by the existing `AuthMiddleware`; new routes need nothing extra.

---

### Task 1: Backend CDP control endpoints (activate / close / new)

**Files:**
- Modify: `backend/main.py` (add `quote` to the `urllib.parse` import at line 17; add 3 routes after `cdp_json_list`, which ends at line 873)
- Test: `backend/tests/test_api.py` (add beside the existing `test_cdp_json_*` tests, ~line 484)

**Interfaces:**
- Consumes: `browser_mgr.running.get(profile_id)` → `RunningProfile | None` with `.cdp_port: int`; module globals `httpx`, `logger`, `HTTPException`.
- Produces: `POST /api/profiles/{id}/cdp/json/activate/{target_id}` → `{"ok": true}`; `POST /api/profiles/{id}/cdp/json/close/{target_id}` → `{"ok": true}`; `POST /api/profiles/{id}/cdp/json/new?url=<u>` → new-target JSON (`url` optional).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py` (uses the existing `_mock_running_profile` helper at line 376 and the `httpx.AsyncClient` mock shape from `test_cdp_json_version_rewrites_ws_url`):

```python
# ── CDP control endpoints (M1c) ──────────────────────────────────────────────


def _mock_httpx(chrome_response):
    """Return a patched httpx.AsyncClient whose get/put yield chrome_response."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=chrome_response)
    mock_client.put = AsyncMock(return_value=chrome_response)
    return mock_client


def test_cdp_activate_not_running(app_client: TestClient):
    resp = app_client.post("/api/profiles/nonexistent/cdp/json/activate/ABC")
    assert resp.status_code == 404


def test_cdp_activate_success(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Act"})
    pid = create.json()["id"]
    _mock_running_profile(pid)
    chrome_response = MagicMock()
    chrome_response.status_code = 200
    with patch("httpx.AsyncClient", return_value=_mock_httpx(chrome_response)):
        resp = app_client.post(f"/api/profiles/{pid}/cdp/json/activate/ABC123")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    main.browser_mgr.running.pop(pid, None)


def test_cdp_activate_unknown_target_404(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Act404"})
    pid = create.json()["id"]
    _mock_running_profile(pid)
    chrome_response = MagicMock()
    chrome_response.status_code = 404
    with patch("httpx.AsyncClient", return_value=_mock_httpx(chrome_response)):
        resp = app_client.post(f"/api/profiles/{pid}/cdp/json/activate/NOPE")
    assert resp.status_code == 404
    main.browser_mgr.running.pop(pid, None)


def test_cdp_activate_chrome_unreachable_502(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "ActDown"})
    pid = create.json()["id"]
    _mock_running_profile(pid)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=ConnectionError("refused"))
    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = app_client.post(f"/api/profiles/{pid}/cdp/json/activate/ABC")
    assert resp.status_code == 502
    main.browser_mgr.running.pop(pid, None)


def test_cdp_close_success(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Close"})
    pid = create.json()["id"]
    _mock_running_profile(pid)
    chrome_response = MagicMock()
    chrome_response.status_code = 200
    with patch("httpx.AsyncClient", return_value=_mock_httpx(chrome_response)):
        resp = app_client.post(f"/api/profiles/{pid}/cdp/json/close/ABC123")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    main.browser_mgr.running.pop(pid, None)


def test_cdp_new_returns_target(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "NewTab"})
    pid = create.json()["id"]
    _mock_running_profile(pid)
    chrome_response = MagicMock()
    chrome_response.status_code = 200
    chrome_response.json.return_value = {"id": "T2", "type": "page", "url": "https://example.com"}
    with patch("httpx.AsyncClient", return_value=_mock_httpx(chrome_response)):
        resp = app_client.post(f"/api/profiles/{pid}/cdp/json/new?url=https://example.com")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://example.com"
    main.browser_mgr.running.pop(pid, None)


def test_cdp_new_not_running(app_client: TestClient):
    resp = app_client.post("/api/profiles/nonexistent/cdp/json/new")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_api.py -k "cdp_activate or cdp_close or cdp_new" -v`
Expected: FAIL — routes return 404/405 (not defined) so `test_cdp_activate_success` etc. fail.

- [ ] **Step 3: Add the `quote` import**

`backend/main.py` line 17 — change:

```python
from urllib.parse import urlparse
```

to:

```python
from urllib.parse import quote, urlparse
```

- [ ] **Step 4: Implement the endpoints**

Insert into `backend/main.py` immediately after `cdp_json_list` (after line 873):

```python
@app.post("/api/profiles/{profile_id}/cdp/json/activate/{target_id}")
async def cdp_activate(profile_id: str, target_id: str):
    """Activate (raise + focus) a CDP target. Chrome raises the OS window."""
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{running.cdp_port}/json/activate/{target_id}", timeout=5
            )
    except Exception as exc:
        logger.error("CDP proxy: activate failed for %s: %s", profile_id, exc)
        raise HTTPException(status_code=502, detail="CDP endpoint unreachable")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="No such tab")
    return {"ok": True}


@app.post("/api/profiles/{profile_id}/cdp/json/close/{target_id}")
async def cdp_close(profile_id: str, target_id: str):
    """Close a CDP target (tab)."""
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{running.cdp_port}/json/close/{target_id}", timeout=5
            )
    except Exception as exc:
        logger.error("CDP proxy: close failed for %s: %s", profile_id, exc)
        raise HTTPException(status_code=502, detail="CDP endpoint unreachable")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="No such tab")
    return {"ok": True}


@app.post("/api/profiles/{profile_id}/cdp/json/new")
async def cdp_new(profile_id: str, url: str = ""):
    """Open a new tab, optionally at `url`. Proxies Chrome's PUT /json/new.

    Chrome appends the raw query string as the target URL, so the URL is
    re-quoted onto `/json/new?` rather than passed as a `url=` parameter.
    """
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")
    target = f"http://127.0.0.1:{running.cdp_port}/json/new"
    if url:
        target += "?" + quote(url, safe="")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.put(target, timeout=5)
    except Exception as exc:
        logger.error("CDP proxy: new-tab failed for %s: %s", profile_id, exc)
        raise HTTPException(status_code=502, detail="CDP endpoint unreachable")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"CDP new-tab rejected ({resp.status_code})")
    return resp.json()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/test_api.py -k "cdp_activate or cdp_close or cdp_new" -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Run the full backend suite (no regressions)**

Run: `pytest -q`
Expected: previous count + 7 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/main.py backend/tests/test_api.py
git commit -m "feat(m1c): add CDP activate/close/new control endpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

> **Controller note (not an implementer step):** before Task 4 wires the address bar, verify `/json/new` actually works on the Win11 VM against a live profile:
> `Invoke-WebRequest -Method Put 'http://127.0.0.1:5100/json/new?https://example.com'`. If Chrome rejects it (needs `--remote-allow-origins` / Host gate), switch `cdp_new` to open a page and drive `Page.navigate` over the existing CDP WS proxy. The unit tests above are agnostic to which path ships.

---

### Task 2: Backend auto-raise on launch

**Files:**
- Modify: `backend/browser_manager.py` (add `_raise_window` method to `BrowserManager`; call it in `launch()` after the clipboard-init loop at line 296, before `running = RunningProfile(...)` at line 298)
- Test: `backend/tests/test_browser_manager.py`

**Interfaces:**
- Produces: `BrowserManager._raise_window(self, context, profile_id: str) -> None` — awaits `context.pages[0].bring_to_front()`, guarded so any failure is logged and swallowed.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_browser_manager.py`:

```python
# ── _raise_window (M1c auto-raise) ───────────────────────────────────────────


async def test_raise_window_brings_first_page_to_front():
    mgr = BrowserManager()
    page = AsyncMock()
    context = MagicMock()
    context.pages = [page]
    await mgr._raise_window(context, "pid")
    page.bring_to_front.assert_awaited_once()


async def test_raise_window_swallows_errors():
    mgr = BrowserManager()
    page = AsyncMock()
    page.bring_to_front = AsyncMock(side_effect=RuntimeError("boom"))
    context = MagicMock()
    context.pages = [page]
    await mgr._raise_window(context, "pid")  # must not raise


async def test_raise_window_no_pages_is_noop():
    mgr = BrowserManager()
    context = MagicMock()
    context.pages = []
    await mgr._raise_window(context, "pid")  # must not raise
```

Confirm the test file imports `AsyncMock`, `MagicMock`, and `BrowserManager` (add to the existing imports if missing — the file already constructs `BrowserManager()` for the `_allocate_cdp_port` tests).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_browser_manager.py -k raise_window -v`
Expected: FAIL — `AttributeError: 'BrowserManager' object has no attribute '_raise_window'`.

- [ ] **Step 3: Implement `_raise_window` and call it**

Add the method to `BrowserManager` (place it near `_on_browser_closed`):

```python
    async def _raise_window(self, context, profile_id: str) -> None:
        """Bring the profile's first page/window to the foreground so the native
        Chromium window isn't hidden behind the app window. Guarded — a failure
        here must never fail the launch (harmless no-op in the container)."""
        try:
            if context.pages:
                await context.pages[0].bring_to_front()
        except Exception as exc:
            logger.warning("bring_to_front failed for %s: %s", profile_id, exc)
```

In `launch()`, insert the call after the clipboard-init loop (after line 296), before `running = RunningProfile(...)`:

```python
            await self._raise_window(context, profile_id)

```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_browser_manager.py -k raise_window -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -q`
Expected: previous count + 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/browser_manager.py backend/tests/test_browser_manager.py
git commit -m "feat(m1c): raise native browser window on launch

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Frontend api.ts — CdpTarget type + 4 CDP methods

**Files:**
- Modify: `frontend/src/lib/api.ts` (export `ApiError`; add `CdpTarget` interface; add 4 methods to `api`)
- Test: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Produces: `export class ApiError` (now exported; already has public `status: number`); `export interface CdpTarget { id; type; title; url; webSocketDebuggerUrl? }`; `api.listTabs(id) → Promise<CdpTarget[]>`, `api.activateTab(id, targetId) → Promise<{ok:boolean}>`, `api.openUrl(id, url) → Promise<CdpTarget>`, `api.closeTab(id, targetId) → Promise<{ok:boolean}>`.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/lib/api.test.ts`:

```ts
// ── CDP control (M1c) ────────────────────────────────────────────────────────

describe("api CDP control", () => {
  it("listTabs GETs the cdp json/list path", async () => {
    const tabs = [{ id: "T1", type: "page", title: "X", url: "https://x.com" }];
    mockFetch.mockResolvedValueOnce(jsonResponse(tabs));
    const result = await api.listTabs("p1");
    expect(result).toEqual(tabs);
    expect(mockFetch).toHaveBeenCalledWith("/api/profiles/p1/cdp/json/list", {
      headers: { "Content-Type": "application/json" },
    });
  });

  it("activateTab POSTs to the activate path", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));
    await api.activateTab("p1", "T1");
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/profiles/p1/cdp/json/activate/T1");
    expect(options.method).toBe("POST");
  });

  it("openUrl POSTs to the new-tab path with an encoded url", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ id: "T2", type: "page", title: "", url: "https://a.com/?q=1" }));
    await api.openUrl("p1", "https://a.com/?q=1");
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/profiles/p1/cdp/json/new?url=https%3A%2F%2Fa.com%2F%3Fq%3D1");
    expect(options.method).toBe("POST");
  });

  it("closeTab POSTs to the close path", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));
    await api.closeTab("p1", "T1");
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/profiles/p1/cdp/json/close/T1");
    expect(options.method).toBe("POST");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/api.test.ts -t "CDP control"`
Expected: FAIL — `api.listTabs is not a function`.

- [ ] **Step 3: Implement**

In `frontend/src/lib/api.ts`: change `class ApiError` (line 76) to `export class ApiError`. Add the interface after the `SystemStatus` interface (line 74):

```ts
export interface CdpTarget {
  id: string;
  type: string;
  title: string;
  url: string;
  webSocketDebuggerUrl?: string;
}
```

Add these four methods inside the `api` object (before the closing `};` at line 158):

```ts
  listTabs: (id: string) =>
    request<CdpTarget[]>(`/api/profiles/${id}/cdp/json/list`),

  activateTab: (id: string, targetId: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}/cdp/json/activate/${targetId}`, {
      method: "POST",
    }),

  openUrl: (id: string, url: string) =>
    request<CdpTarget>(`/api/profiles/${id}/cdp/json/new?url=${encodeURIComponent(url)}`, {
      method: "POST",
    }),

  closeTab: (id: string, targetId: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}/cdp/json/close/${targetId}`, {
      method: "POST",
    }),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/api.test.ts`
Expected: PASS (existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts
git commit -m "feat(m1c): api.ts CDP tab-control methods

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Frontend RunningPanel + wire-up + delete noVNC

**Files:**
- Create: `frontend/src/components/RunningPanel.tsx`
- Create: `frontend/src/components/RunningPanel.test.tsx`
- Modify: `frontend/src/App.tsx` (swap `ProfileViewer` import + render for `RunningPanel`, lines 7 and 245-252)
- Delete: `frontend/src/components/ProfileViewer.tsx`, `frontend/src/novnc.d.ts`
- Modify: `frontend/package.json` (remove `@novnc/novnc` at line 14)

**Interfaces:**
- Consumes: `api.listTabs/activateTab/openUrl/closeTab`, `ApiError`, `CdpTarget` from Task 3.
- Produces: `RunningPanel({ profileId, cdpUrl, onDisconnect })` — same three props App already supplies to `ProfileViewer` (minus `clipboardSync`).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/RunningPanel.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RunningPanel } from "./RunningPanel";
import { api } from "../lib/api";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    api: {
      listTabs: vi.fn(),
      activateTab: vi.fn(),
      openUrl: vi.fn(),
      closeTab: vi.fn(),
    },
  };
});

const tab = { id: "T1", type: "page", title: "DuckDuckGo", url: "https://duckduckgo.com" };

beforeEach(() => {
  vi.clearAllMocks();
  (api.listTabs as ReturnType<typeof vi.fn>).mockResolvedValue([tab]);
  (api.activateTab as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true });
  (api.openUrl as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "T2", type: "page", title: "", url: "https://x.com" });
  (api.closeTab as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true });
});

describe("RunningPanel", () => {
  it("renders page tabs from listTabs", async () => {
    render(<RunningPanel profileId="p1" cdpUrl="/api/p1/cdp" onDisconnect={() => {}} />);
    expect(await screen.findByText("DuckDuckGo")).toBeTruthy();
  });

  it("activates a tab on row click", async () => {
    render(<RunningPanel profileId="p1" cdpUrl={null} onDisconnect={() => {}} />);
    fireEvent.click(await screen.findByText("DuckDuckGo"));
    await waitFor(() => expect(api.activateTab).toHaveBeenCalledWith("p1", "T1"));
  });

  it("opens a URL via openUrl", async () => {
    render(<RunningPanel profileId="p1" cdpUrl={null} onDisconnect={() => {}} />);
    await screen.findByText("DuckDuckGo");
    fireEvent.change(screen.getByPlaceholderText(/https/i), {
      target: { value: "https://x.com" },
    });
    fireEvent.click(screen.getByText("Go"));
    await waitFor(() => expect(api.openUrl).toHaveBeenCalledWith("p1", "https://x.com"));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/RunningPanel.test.tsx`
Expected: FAIL — cannot resolve `./RunningPanel`.

- [ ] **Step 3: Implement `RunningPanel.tsx`**

Create `frontend/src/components/RunningPanel.tsx`:

```tsx
import { useCallback, useEffect, useState } from "react";
import { Check, Copy, ExternalLink, X } from "lucide-react";
import { api, ApiError, type CdpTarget } from "../lib/api";

interface RunningPanelProps {
  profileId: string;
  cdpUrl: string | null;
  onDisconnect: () => void;
}

export function RunningPanel({ profileId, cdpUrl, onDisconnect }: RunningPanelProps) {
  const [tabs, setTabs] = useState<CdpTarget[]>([]);
  const [url, setUrl] = useState("");
  const [copied, setCopied] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listTabs(profileId);
      setTabs(list.filter((t) => t.type === "page"));
    } catch (err) {
      // 404 → profile stopped; other errors are transient, keep the last list.
      if (err instanceof ApiError && err.status === 404) onDisconnect();
    }
  }, [profileId, onDisconnect]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, [refresh]);

  const focusWindow = async () => {
    const first = tabs[0];
    if (first) await api.activateTab(profileId, first.id);
  };

  const openUrl = async () => {
    const u = url.trim();
    if (!u) return;
    await api.openUrl(profileId, u);
    setUrl("");
    refresh();
  };

  const closeTab = async (targetId: string) => {
    await api.closeTab(profileId, targetId);
    refresh();
  };

  const copyCdp = async () => {
    if (!cdpUrl) return;
    await navigator.clipboard.writeText(cdpUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="flex flex-col gap-4 p-6 h-full overflow-y-auto">
      <div className="flex items-center gap-3">
        <button
          onClick={focusWindow}
          className="flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500"
        >
          <ExternalLink size={16} /> Focus browser window
        </button>
        <span className="text-sm text-neutral-400">
          The browser is open in its own window.
        </span>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          openUrl();
        }}
        className="flex items-center gap-2"
      >
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://…"
          className="flex-1 rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100"
        />
        <button
          type="submit"
          className="rounded-md bg-neutral-700 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-600"
        >
          Go
        </button>
      </form>

      <div className="flex flex-col gap-1">
        <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Tabs
        </div>
        {tabs.length === 0 && (
          <div className="py-2 text-sm text-neutral-500">No tabs</div>
        )}
        {tabs.map((t) => (
          <div
            key={t.id}
            className="group flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-neutral-800"
          >
            <button
              onClick={() => api.activateTab(profileId, t.id)}
              className="flex min-w-0 flex-1 flex-col items-start text-left"
            >
              <span className="truncate text-sm text-neutral-100">
                {t.title || t.url || "(untitled)"}
              </span>
              <span className="truncate text-xs text-neutral-500">{t.url}</span>
            </button>
            <button
              onClick={() => closeTab(t.id)}
              aria-label="Close tab"
              className="rounded p-1 text-neutral-500 opacity-0 hover:text-red-400 group-hover:opacity-100"
            >
              <X size={16} />
            </button>
          </div>
        ))}
      </div>

      {cdpUrl && (
        <div className="mt-auto flex items-center gap-2 border-t border-neutral-800 pt-3">
          <span className="text-xs text-neutral-500">CDP</span>
          <code className="flex-1 truncate rounded bg-neutral-900 px-2 py-1 text-xs text-neutral-300">
            {cdpUrl}
          </code>
          <button
            onClick={copyCdp}
            aria-label="Copy CDP URL"
            className="rounded p-1 text-neutral-400 hover:text-neutral-100"
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the component tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/RunningPanel.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Wire into App.tsx and delete noVNC**

In `frontend/src/App.tsx`: change the import at line 7 —

```tsx
import { ProfileViewer } from "./components/ProfileViewer";
```
to
```tsx
import { RunningPanel } from "./components/RunningPanel";
```

Replace the render block at lines 245-252 —

```tsx
          {view === "view" && selected && selected.status === "running" && (
            <ProfileViewer
              key={selected.id}
              profileId={selected.id}
              cdpUrl={selected.cdp_url}
              clipboardSync={selected.clipboard_sync}
              onDisconnect={handleVncDisconnect}
            />
          )}
```
with
```tsx
          {view === "view" && selected && selected.status === "running" && (
            <RunningPanel
              key={selected.id}
              profileId={selected.id}
              cdpUrl={selected.cdp_url}
              onDisconnect={handleVncDisconnect}
            />
          )}
```

Delete the two files and drop the dependency:

```bash
git rm frontend/src/components/ProfileViewer.tsx frontend/src/novnc.d.ts
```

Edit `frontend/package.json` — remove the `"@novnc/novnc": "^1.4.0",` line (line 14). Then refresh the lockfile:

```bash
cd frontend && npm install
```

- [ ] **Step 6: Verify no dangling noVNC references, typecheck, build**

```bash
cd frontend && grep -rn "@novnc\|ProfileViewer" src && echo "FOUND — fix before continuing" || echo "clean"
npm run build
```
Expected: `clean`, then `tsc -b` passes (no unused-locals errors — `handleVncDisconnect` is still used) and vite build succeeds.

- [ ] **Step 7: Run the full frontend suite**

Run: `cd frontend && npm test`
Expected: all pass (RunningPanel + api + hooks).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(m1c): RunningPanel mission-control view, drop noVNC

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- 3 backend endpoints (activate/new/close) → Task 1 ✓
- auto-raise on launch → Task 2 ✓
- api.ts methods + CdpTarget → Task 3 ✓
- RunningPanel (focus, address bar, tab list, close, CDP copy, 2s poll, onDisconnect on 404) → Task 4 ✓
- delete ProfileViewer + novnc.d.ts + @novnc/novnc → Task 4 ✓
- leave backend RFB/vnc_manager/clipboard tombstone → not touched by any task ✓ (Global Constraint)
- `/json/new` risk verification → Task 1 controller note ✓
- Integration proof on VM → controller runs after Task 4 (below)

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `CdpTarget` defined in Task 3, consumed in Task 4; `ApiError` exported in Task 3, consumed in Task 4; `RunningPanel` props (`profileId`, `cdpUrl`, `onDisconnect`) match App's supplied props; `activateTab(id, targetId)`/`openUrl(id, url)`/`closeTab(id, targetId)` signatures identical across api.ts, tests, and RunningPanel.

## Post-plan integration (controller, after Task 4)

On the Win11 VM (`prlctl exec '{86b0eede-...}'`): rebuild frontend + frozen exe, launch a profile → confirm (a) native window auto-raises, (b) panel lists the about:blank tab, (c) Focus button raises the window, (d) address bar opens a tab (this is where the `/json/new` path is proven end-to-end), (e) no blank canvas. This is the real acceptance test for the milestone.
