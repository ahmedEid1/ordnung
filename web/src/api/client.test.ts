import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { ApiError, apiPath, assetUrl, messageFromDetail, request, setAssetResolver } from "./client";
import { api } from "./endpoints";
import { __resetEventsForTests, handleServerEvent, useEvents } from "./sse";
import { qk } from "./hooks";
import { renderHook } from "@testing-library/react";

afterEach(() => {
  vi.restoreAllMocks();
  setAssetResolver(null);
});

function mockFetch(status: number, body: unknown, headers: Record<string, string> = { "Content-Type": "application/json" }) {
  const fn = vi.fn(async () => new Response(body === undefined ? null : typeof body === "string" ? body : JSON.stringify(body), { status, headers }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("client", () => {
  it("builds /api paths and skips empty query values", () => {
    expect(apiPath("/documents", { q: "miete", kind: undefined, limit: 8, private: false, x: "" })).toBe("/api/documents?q=miete&limit=8&private=false");
    expect(apiPath("health")).toBe("/api/health");
  });

  it("GETs JSON without the client header", async () => {
    const f = mockFetch(200, { today: "2026-09-28" });
    await expect(request("/health")).resolves.toEqual({ today: "2026-09-28" });
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-Ordnung-Client"]).toBeUndefined();
    expect(init.credentials).toBe("same-origin");
  });

  it("sends X-Ordnung-Client and JSON on writes", async () => {
    const f = mockFetch(200, { id: "itm_1", status: "done" });
    await api.updateItem("itm_1", { status: "done" });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/items/itm_1");
    expect(init.method).toBe("PATCH");
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Ordnung-Client"]).toBe("web");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ status: "done" }));
  });

  it("uploads multipart form data", async () => {
    const f = mockFetch(201, { documents: [], jobs: [], duplicates: [] });
    await api.uploadDocuments([new File(["x"], "a.jpg", { type: "image/jpeg" }), new File(["y"], "b.jpg", { type: "image/jpeg" })], { combine: true });
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    const form = init.body as FormData;
    expect(form.getAll("files")).toHaveLength(2);
    expect(form.get("combine")).toBe("true");
    expect(form.get("private")).toBe("false");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("turns FastAPI errors into ApiError with the detail message", async () => {
    mockFetch(422, { detail: [{ msg: "field required" }, { msg: "bad date" }] });
    const err = await request("/items", { method: "POST", body: {} }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(422);
    expect((err as ApiError).message).toBe("field required; bad date");

    mockFetch(403, { detail: "Install Ordnung to try this", code: "static_demo" });
    const demo = (await api.runReview().catch((e: unknown) => e)) as ApiError;
    expect(demo.isStaticDemo).toBe(true);
    expect(demo.message).toBe("Install Ordnung to try this");
  });

  it("returns undefined for 204 and reports network failures as status 0", async () => {
    mockFetch(204, undefined);
    await expect(api.deleteItem("itm_1")).resolves.toBeUndefined();
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const err = (await api.health().catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(0);
  });

  it("extracts messages from detail shapes", () => {
    expect(messageFromDetail("Nope", "x")).toBe("Nope");
    expect(messageFromDetail({ message: "Paused" }, "x")).toBe("Paused");
    expect(messageFromDetail(undefined, "fallback")).toBe("fallback");
  });

  it("resolves asset URLs through an optional resolver (mock mode)", () => {
    expect(api.pageUrl("doc_1", 2)).toBe("/api/documents/doc_1/pages/2.jpg");
    setAssetResolver((p) => (p.endsWith(".jpg") ? `data:${p}` : null));
    expect(api.thumbnailUrl("doc_1")).toBe("data:/documents/doc_1/thumbnail.jpg");
    expect(assetUrl("/calendar.ics")).toBe("/api/calendar.ics");
  });
});

describe("server events", () => {
  it("tracks job progress per document and invalidates on completion", () => {
    __resetEventsForTests();
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { result, rerender } = renderHook(() => useEvents());

    handleServerEvent(qc, { type: "job.progress", data: { job_id: "job_1", doc_id: "doc_x", stage: "extract", progress: 0.3, status: "running" } });
    rerender();
    expect(result.current.jobs.doc_x?.stage).toBe("extract");
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.documents.all });

    spy.mockClear();
    handleServerEvent(qc, { type: "job.progress", data: { job_id: "job_1", doc_id: "doc_x", stage: "done", progress: 1, status: "done" } });
    rerender();
    expect(result.current.jobs.doc_x?.status).toBe("done");
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.dashboard });
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.mail });

    handleServerEvent(qc, { type: "llm.paused", data: { until: "2026-09-28T14:05:00Z", reason: "Usage limit reached." } });
    rerender();
    expect(result.current.paused?.reason).toBe("Usage limit reached.");
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.health }); // Claude's status may have changed

    // the API announces the end of the pause; the banner goes away without waiting for `until`
    handleServerEvent(qc, { type: "llm.resumed", data: {} });
    rerender();
    expect(result.current.paused).toBeNull();
  });

  it("refreshes what other windows, the CLI or the daily tick changed", () => {
    __resetEventsForTests();
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    handleServerEvent(qc, { type: "brief.updated", data: { date: "2026-09-28", source: "template" } });
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.brief });
    handleServerEvent(qc, { type: "document.deleted", data: { doc_id: "doc_x", purged: false } });
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.documents.all });
    handleServerEvent(qc, { type: "profile.updated", data: {} });
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.profile });
  });

  it("refreshes the letters when a to-do changed elsewhere (their GiroCodes follow its amount)", () => {
    __resetEventsForTests();
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    handleServerEvent(qc, { type: "item.updated", data: { item_id: "itm_x" } });
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.items.all });
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.documents.all });
  });
});
