import { afterEach, describe, expect, it } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { __resetEventsForTests, handleServerEvent, seedJob, useEvents } from "./sse";
import type { JobProgressEvent } from "./types";
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
