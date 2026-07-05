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
