import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { RunningPanel } from "./RunningPanel";
import { api, ApiError } from "../lib/api";

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

  it("calls onDisconnect when the poll returns 404 (profile stopped)", async () => {
    const onDisconnect = vi.fn();
    (api.listTabs as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new ApiError(404, "Profile not running"),
    );
    render(<RunningPanel profileId="p1" cdpUrl={null} onDisconnect={onDisconnect} />);
    await waitFor(() => expect(onDisconnect).toHaveBeenCalledTimes(1));
  });

  it("keeps the last tab list and does not disconnect on a transient (non-404) error", async () => {
    vi.useFakeTimers();
    try {
      const onDisconnect = vi.fn();
      (api.listTabs as ReturnType<typeof vi.fn>)
        .mockResolvedValueOnce([tab])                      // initial poll succeeds
        .mockRejectedValue(new ApiError(500, "boom"));     // every later poll fails (transient)
      render(<RunningPanel profileId="p1" cdpUrl={null} onDisconnect={onDisconnect} />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);              // flush initial refresh()
      });
      expect(screen.getByText("DuckDuckGo")).toBeTruthy();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);           // fire the 2s interval → failing poll
      });
      expect(onDisconnect).not.toHaveBeenCalled();
      expect(screen.getByText("DuckDuckGo")).toBeTruthy(); // last list preserved
    } finally {
      vi.useRealTimers();
    }
  });
});
