import { describe, expect, it } from "vitest";
import type { TraceChange, TraceRun, TraceSpan } from "@/api/types";
import { assertNoRawEnums } from "@/lib/copy";
import { changeText, compareBase, exportCommand, formatMs, runResult, shellPath, spanCopy, spanDetails, specText } from "./copy";

const span = (s: Partial<TraceSpan>): TraceSpan => ({
  id: "spn_1",
  parent_id: "spn_0",
  depth: 1,
  key: "run/x",
  kind: "run",
  name: "",
  stage: null,
  start_ms: 0,
  duration_ms: 0,
  status: "ok",
  error: null,
  attributes: {},
  call: null,
  ref: null,
  label: null,
  ...s,
});

const change = (c: Partial<TraceChange>): TraceChange => ({
  key: "run/x",
  kind: "verify",
  name: "Quote",
  field: "grounding",
  before: null,
  after: null,
  ref: null,
  label: null,
  ...c,
});

describe("trace copy", () => {
  it("formats durations from microseconds to minutes", () => {
    expect(formatMs(0)).toBe("0 ms");
    expect(formatMs(0.4)).toBe("<1 ms");
    expect(formatMs(12.4)).toBe("12 ms");
    expect(formatMs(4200)).toBe("4.2 s");
    expect(formatMs(32_000)).toBe("32 s");
    expect(formatMs(103_706)).toBe("1 min 44 s");
    expect(formatMs(120_000)).toBe("2 min");
  });

  it("puts a DateSpec's structure in words (never its wording)", () => {
    expect(specText({ type: "relative", amount: 1, unit: "weeks", anchor: "receipt" })).toBe("1 week after the day it reached you");
    expect(specText({ type: "relative", amount: 1, unit: "months", anchor: "deemed_delivery", delivery_rule: "de_admin_post" })).toBe(
      "1 month after the day it counts as delivered (posted by an authority)",
    );
    expect(specText({ type: "relative", amount: 3, unit: "months", anchor: "explicit_date", anchor_date: "2026-04-01" })).toBe("3 months after 1 Apr 2026");
    expect(specText({ type: "fixed", date: "2026-10-09" })).toBe("A fixed date: 9 Oct 2026");
    expect(specText({ type: "none" })).toBe("No date");
    expect(specText(null)).toBe("—");
  });

  it("says how a model call's answer turned out", () => {
    const invalid = spanCopy(span({ kind: "model", key: "run/model:extract", attributes: { outcome: "invalid", request_model: "sonnet", prompt: "extract" } }));
    expect(invalid.title).toBe("Claude reads the letter");
    expect(invalid.flag).toEqual({ text: "Answer didn't fit — asked again", tone: "warn" });
    const repaired = spanCopy(span({ kind: "model", key: "run/model:extract_repair", attributes: { outcome: "repaired", prompt: "extract_repair" } }));
    expect(repaired.title).toBe("Claude, asked again");
    expect(repaired.flag?.tone).toBe("ok");
    const page = spanCopy(span({ kind: "model", attributes: { page: 2, legible: true, chars: 2388, outcome: "ok", served_model: "sonnet" } }));
    expect(page.title).toBe("Page 2 read by Claude");
    expect(page.summary).toBe("Sonnet · 2.4k characters");
    const cached = spanCopy(span({ kind: "model", attributes: { outcome: "ok", cache_hit: true } }));
    expect(cached.flag).toEqual({ text: "From the cache", tone: "ok" });
    const details = spanDetails(span({ kind: "model", attributes: { prompt: "extract_repair", prompt_version: "8.7.1.r1", outcome: "failed" } }));
    expect(details).toContainEqual({ label: "Prompt", value: "extract (repair), version 8.7.1.r1" });
    expect(details).toContainEqual({ label: "Answer", value: "Not usable" });
  });

  it("describes quotes, links and planning from their facts", () => {
    const quote = spanCopy(
      span({ kind: "verify", label: "Pay the parking fine", attributes: { target: "item", grounding: "unverified", best_score: 72.4, reasons: ["date_not_in_quote"] } }),
    );
    expect(quote.title).toBe("Pay the parking fine");
    expect(quote.summary).toBe("To-do · Not found (closest passage 72 %) · the quote doesn't state the date");
    expect(quote.flag?.text).toBe("Please check");
    expect(spanCopy(span({ kind: "verify", attributes: { target: "key_fact", grounding: "model_read", page: 1 } })).summary).toBe(
      "Key fact · Found in the transcript of page 1",
    );
    const sender = spanCopy(
      span({ kind: "link", name: "Sender", label: "TechMarkt Online GmbH", attributes: { decision: "identifier", reference_kind: "kundennummer", candidates: [] } }),
    );
    expect(sender).toEqual({ title: "TechMarkt Online GmbH", summary: "Sender · Known — found by its customer number" });
    expect(spanCopy(span({ kind: "link", name: "Sender", attributes: { decision: "none", candidates: [] } })).summary).toBe("No sender found");
    const scam = spanCopy(span({ kind: "link", name: "Payment check", attributes: { finding: "iban_changed", iban_valid: true, iban_known: false, iban_added: false } }));
    expect(scam.summary).toBe("The IBAN differs from the one this sender used before");
    expect(scam.flag?.tone).toBe("danger");
    expect(
      spanCopy(span({ kind: "link", name: "Thread", label: "Invoice", attributes: { decision: "reference", case_id: "cas_1", reference_kind: "rechnungsnummer" } }))
        .summary,
    ).toBe("Thread · Joined by its invoice number");
    expect(spanCopy(span({ kind: "plan", label: "Pay rent", attributes: { action: "kept_later_date", moved: false } })).summary).toMatch(/^Kept its later date/);
    const candidates = spanDetails(span({ kind: "link", name: "Sender", attributes: { decision: "new", candidates: [{ party_id: "pty_a", score: 66.7 }] } }), (id) =>
      id === "pty_a" ? "Stadt Musterstadt" : null,
    );
    expect(candidates).toContainEqual({ label: "Compared with", value: "Stadt Musterstadt (67 %)" });
  });

  it("puts what changed between two readings in words, never raw codes or ids", () => {
    expect(changeText(change({ label: "Pay the fine", field: "grounding", before: "unverified", after: "verified" }))).toEqual({
      what: "Pay the fine",
      detail: "Where it was found: not found → in the text",
    });
    expect(changeText(change({ kind: "rules", name: "Date", label: "Pay", field: "due_date", before: "2026-10-01", after: "2026-10-02" })).detail).toBe(
      "Date: Thu 1 Oct 2026 → Fri 2 Oct 2026",
    );
    expect(changeText(change({ kind: "model", name: "Extract · repair", key: "run/model:extract_repair", field: "present", before: true, after: false }))).toEqual({
      what: "Claude, asked again",
      detail: "Only in the earlier reading",
    });
    const party = changeText(change({ kind: "link", name: "Sender", label: "Stadtwerke", field: "party_id", before: "pty_a", after: "pty_b" }));
    expect(party.detail).toBe("A different sender than before");
    const plan = changeText(change({ kind: "plan", name: "To-do", label: "Pay", field: "action", before: "created", after: "kept_edited" }));
    expect(plan.detail).toBe("What happened: new to-do → kept as you edited it");
    for (const text of [party, plan]) assertNoRawEnums(`${text.what} ${text.detail}`);
  });

  it("names how a reading ended", () => {
    const run = { status: "ok", ended: "done", result: "processed", error: null } as TraceRun;
    expect(runResult(run)).toEqual({ text: "Filed", tone: "ok" });
    expect(runResult({ ...run, result: "needs_review" })).toEqual({ text: "Filed — something to check", tone: "warn" });
    expect(runResult({ ...run, status: "error", ended: "failed", result: "failed", error: "x" }).tone).toBe("danger");
    expect(runResult({ ...run, status: "error", ended: "paused", result: null, error: "Paused" })).toEqual({ text: "Paused — read again later", tone: "warn" });
    expect(runResult({ ...run, status: "error", ended: "stopped", result: null, error: "Stopped" })).toEqual({ text: "Stopped — read again later", tone: "warn" });
  });

  it("compares with the newest earlier reading that was done", () => {
    const r = (reading: number, ended: TraceRun["ended"]) => ({ reading, ended, trace_id: `trc_${reading}` }) as TraceRun;
    const runs = [r(4, "done"), r(3, "paused"), r(2, "stopped"), r(1, "done")];
    expect(compareBase(runs, runs[0]!)?.reading).toBe(1);
    expect(compareBase(runs, runs[1]!)?.reading).toBe(1);
    expect(compareBase([r(2, "done"), r(1, "failed")], r(2, "done"))?.reading).toBe(1);
    expect(compareBase(runs, runs[3]!)).toBeUndefined();
  });

  it("writes the export command for the reading shown and the server's folder", () => {
    expect(exportCommand("doc_a", { reading: null, dataDir: null })).toBe("ordnung trace doc_a --otel -o trace.json");
    expect(exportCommand("doc_a", { reading: 2, dataDir: "/Users/sam/Library/Application Support/ordnung-demo" })).toBe(
      'ordnung trace doc_a --reading 2 --otel -o trace.json --data-dir "/Users/sam/Library/Application Support/ordnung-demo"',
    );
    expect(shellPath('/tmp/a"b')).toBe(`'/tmp/a"b'`);
    expect(shellPath("/tmp/it's $HOME")).toBe(`'/tmp/it'\\''s $HOME'`);
  });

  it("names a newer model of the same family by its full id", () => {
    const same = changeText(change({ kind: "model", name: "Extract", field: "served_model", before: "claude-sonnet-4-5", after: "claude-sonnet-4-6" }));
    expect(same.detail).toBe("Model: claude-sonnet-4-5 → claude-sonnet-4-6");
    const other = changeText(change({ kind: "model", name: "Extract", field: "served_model", before: "claude-sonnet-4-5", after: "claude-opus-4-1" }));
    expect(other.detail).toBe("Model: Sonnet → Opus");
  });
});
