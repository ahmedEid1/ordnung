import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { reloadIfServing } from "./staleChunks";

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("a page chunk that failed to load (UX audit U7)", () => {
  it("loads the new build while Ordnung answers — once a minute at most", async () => {
    const health = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", health);
    const reload = vi.fn();
    await reloadIfServing(reload);
    expect(health).toHaveBeenCalledWith("/api/health", { cache: "no-store" });
    expect(reload).toHaveBeenCalledOnce();
    await reloadIfServing(reload);
    expect(reload).toHaveBeenCalledOnce();
  });

  it("keeps the app on screen when Ordnung stopped: no reload into the browser's error page", async () => {
    vi.stubGlobal("fetch", async () => Promise.reject(new TypeError("Failed to fetch")));
    const reload = vi.fn();
    await reloadIfServing(reload);
    expect(reload).not.toHaveBeenCalled();
    // and a reload is still possible once it is back
    vi.stubGlobal("fetch", async () => new Response("{}", { status: 200 }));
    await reloadIfServing(reload);
    expect(reload).toHaveBeenCalledOnce();
  });
});
