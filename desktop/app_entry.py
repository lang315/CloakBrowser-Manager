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
