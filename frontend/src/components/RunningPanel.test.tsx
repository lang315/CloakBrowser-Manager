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
