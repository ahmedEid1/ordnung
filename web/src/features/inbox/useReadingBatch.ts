/**
 * Watches letters being read (SSE `job.progress`) while the Inbox is open and groups jobs that
 * overlap in time into a batch. When a whole batch has finished it calls `onDone(docIds)` —
 * the Inbox then shows the recap (several letters) or opens the letter (one New-mail letter).
 */
import { useRef } from "react";
import { useServerEvent } from "@/api/sse";
import type { JobStatus } from "@/api/types";

const FINAL: JobStatus[] = ["done", "failed"];

export function useReadingBatch(onDone: (docIds: string[], failed: string[]) => void): void {
  const batch = useRef(new Map<string, JobStatus>());

  useServerEvent("job.progress", (ev) => {
    const id = ev.doc_id;
    if (!id) return;
    const m = batch.current;
    if (!FINAL.includes(ev.status)) {
      m.set(id, ev.status);
      return;
    }
    if (!m.has(id)) return; // finished before we saw it running (e.g. opened elsewhere)
    m.set(id, ev.status);
    if ([...m.values()].every((s) => FINAL.includes(s))) {
      const ids = [...m.keys()];
      const failed = ids.filter((k) => m.get(k) === "failed");
      m.clear();
      onDone(ids, failed);
    }
  });
}
