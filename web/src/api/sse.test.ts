import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { api } from "./endpoints";
import { __resetEventsForTests, claudeWaitReason, handleServerEvent, seedFromQueue, seedJob, useEvents } from "./sse";
import type { Job, JobProgressEvent } from "./types";
import { renderHook } from "@testing-library/react";

afterEach(() => __resetEventsForTests());

const progress = (job_id: string, status: JobProgressEvent["status"], stage: JobProgressEvent["stage"] = "extract"): JobProgressEvent => ({
  job_id,
  doc_id: "doc_x",
  stage: status === "done" ? "done" : stage,
  progress: status === "done" ? 1 : 0.3,
  status,
});

describe("seedJob", () => {
  it("does not take back a reading the server already finished (a seed that arrives after 'done')", () => {
    const qc = new QueryClient();
    const { result, rerender } = renderHook(() => useEvents());
    // "Read again": the job's events arrive while the mutation still refetches the ledger …
    handleServerEvent(qc, { type: "job.progress", data: progress("job_2", "running") });
    handleServerEvent(qc, { type: "job.progress", data: progress("job_2", "done") });
    // … and only then does the caller's onSuccess seed "Opening the file…"
    seedJob({ job_id: "job_2", doc_id: "doc_x", stage: "intake", progress: 0, status: "running" });
    rerender();
    expect(result.current.jobs.doc_x).toMatchObject({ job_id: "job_2", status: "done", stage: "done" });
  });

  it("keeps a failure that arrived before the seed", () => {
    const qc = new QueryClient();
    const { result, rerender } = renderHook(() => useEvents());
    handleServerEvent(qc, { type: "job.progress", data: { ...progress("job_2", "failed"), error: "Claude isn't set up." } });
    seedJob({ job_id: "job_2", doc_id: "doc_x", stage: "intake", progress: 0, status: "running" });
    rerender();
    expect(result.current.jobs.doc_x).toMatchObject({ status: "failed", error: "Claude isn't set up." });
  });

  it("replaces an earlier job of the same letter (read again after it was done or failed)", () => {
    const qc = new QueryClient();
    const { result, rerender } = renderHook(() => useEvents());
    handleServerEvent(qc, { type: "job.progress", data: progress("job_1", "failed") });
    seedJob({ job_id: "job_2", doc_id: "doc_x", stage: "intake", progress: 0, status: "running" });
    rerender();
    expect(result.current.jobs.doc_x).toMatchObject({ job_id: "job_2", status: "running", stage: "intake" });
    // and the server's events for the new job then move it on
    handleServerEvent(qc, { type: "job.progress", data: progress("job_2", "done") });
    rerender();
    expect(result.current.jobs.doc_x?.status).toBe("done");
  });

  it("shows the stepper at once when nothing is known yet", () => {
    const { result, rerender } = renderHook(() => useEvents());
    seedJob({ job_id: "job_1", doc_id: "doc_x", stage: "intake", progress: 0, status: "running" });
    rerender();
    expect(result.current.jobs.doc_x?.status).toBe("running");
  });
});

describe("seedFromQueue (on connecting: a reload, a new tab)", () => {
  const NOT_INSTALLED =
    "Waiting for Claude: Claude Code isn't installed on this computer yet. Ordnung reads this letter as soon as Claude is connected (Settings → Claude connection).";
  const STOPPED = "Ordnung was stopped before this letter was finished; it will continue.";
  const job = (id: string, doc_id: string, waiting_reason: string | null, status: Job["status"] = "queued"): Job => ({
    id,
    doc_id,
    status,
    waiting_reason,
    kind: "ingest",
    stage: null,
    progress: 0,
    attempts: 1,
    force: false,
    not_before: null,
    error: null,
    created_at: "2026-09-28T07:00:00Z",
    updated_at: "2026-09-28T07:00:00Z",
  });

  afterEach(() => vi.restoreAllMocks());

  it("says which letters wait and why, and shows the banner while one waits for Claude (final check F-M2)", async () => {
    vi.spyOn(api, "jobs").mockResolvedValue([job("job_a", "doc_a", NOT_INSTALLED), job("job_b", "doc_b", STOPPED), job("job_c", "doc_c", null, "running")]);
    const { result, rerender } = renderHook(() => useEvents());
    await seedFromQueue(Date.now());
    rerender();
    expect(api.jobs).toHaveBeenCalledWith(true);
    expect(claudeWaitReason(result.current.jobs.doc_a)).toBe(NOT_INSTALLED);
    expect(result.current.jobs.doc_b).toMatchObject({ status: "queued", waiting_reason: STOPPED });
    expect(claudeWaitReason(result.current.jobs.doc_b)).toBeNull();
    expect(result.current.jobs.doc_c).toBeUndefined();
    expect(result.current.paused).toEqual({ until: "", reason: "" });

    // the worker's next try says how it stands
    handleServerEvent(new QueryClient(), { type: "llm.resumed", data: {} });
    rerender();
    expect(result.current.paused).toBeNull();
  });

  it("keeps what was heard since the connection opened, and the pause the server sent first", async () => {
    const opened = Date.now();
    const qc = new QueryClient();
    const usage = { until: "2099-01-05T14:30:00Z", reason: "Usage limit reached." };
    handleServerEvent(qc, { type: "llm.paused", data: usage });
    handleServerEvent(qc, { type: "job.progress", data: { ...progress("job_a", "running"), doc_id: "doc_a" } });
    vi.spyOn(api, "jobs").mockResolvedValue([job("job_a", "doc_a", NOT_INSTALLED)]);
    const { result, rerender } = renderHook(() => useEvents());
    await seedFromQueue(opened);
    rerender();
    expect(result.current.jobs.doc_a?.status).toBe("running");
    expect(result.current.paused).toEqual(usage);
  });

  it("shows no banner for a letter that waits for another reason, and stays quiet when the queue can't be read", async () => {
    vi.spyOn(api, "jobs").mockResolvedValueOnce([job("job_b", "doc_b", STOPPED)]).mockRejectedValueOnce(new Error("offline"));
    const { result, rerender } = renderHook(() => useEvents());
    await seedFromQueue(Date.now());
    await seedFromQueue(Date.now());
    rerender();
    expect(result.current.paused).toBeNull();
  });
});
