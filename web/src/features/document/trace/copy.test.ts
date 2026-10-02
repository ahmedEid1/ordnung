import { describe, expect, it } from "vitest";
import type { TraceChange, TraceRun, TraceSpan } from "@/api/types";
import { assertNoRawEnums } from "@/lib/copy";
import { barTone, changeText, compareBase, exportCommand, formatMs, runResult, runTitle, shellPath, spanCopy, spanDetails, specText } from "./copy";

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

  it("says when Claude was asked for what its reading left out, and whether that answer was used (ingest/extract.py)", () => {
    const asked = { prompt: "reading_gaps", prompt_version: "12.7.1.c1", request_model: "sonnet" };
    const used = span({
      kind: "model",
      key: "run/model:extract_complete",
      attributes: { ...asked, outcome: "repaired", reading_gap: "empty", accepted: true, kept_because: null },
    });
    expect(spanCopy(used)).toEqual({
      title: "Claude, asked for what it left out",
      summary: "Sonnet · asked because the reading came back almost blank",
      flag: { text: "Answer used", tone: "ok" },
    });
    expect(barTone(used)).toBe("accent");
    const usedDetails = spanDetails(used);
    expect(usedDetails).toContainEqual({ label: "Prompt", value: "reading gaps (asked again), version 12.7.1.c1" });
    expect(usedDetails).toContainEqual({ label: "Asked because", value: "The reading came back almost blank" });
    expect(usedDetails).toContainEqual({ label: "Reading kept", value: "This answer — more complete than the first" });
    expect(usedDetails).toContainEqual({ label: "Answer", value: "Usable" });

    // a usable answer no more complete than the first: the first reading stays, Ordnung's own check takes over
    const kept = span({
      kind: "model",
      key: "run/model:extract_complete",
      attributes: { ...asked, outcome: "repaired", reading_gap: "remedy_left_out", accepted: false, kept_because: "not_better" },
    });
    expect(spanCopy(kept).flag).toEqual({ text: "First reading kept", tone: "warn" });
    expect(spanCopy(kept).summary).toBe("Sonnet · asked because the reading left out the deadline to object");
    expect(barTone(kept)).toBe("warn");
    expect(spanDetails(kept)).toContainEqual({ label: "Reading kept", value: "The first — this answer was no more complete" });

    // an unusable answer is no failure of the reading: warn, not danger
    const unusable = span({
      kind: "model",
      key: "run/model:extract_complete",
      attributes: { ...asked, outcome: "failed", reading_gap: "empty", accepted: false, kept_because: "unusable" },
    });
    expect(barTone(unusable)).toBe("warn");
    expect(spanCopy(unusable).flag).toEqual({ text: "First reading kept", tone: "warn" });
    expect(spanDetails(unusable)).toContainEqual({ label: "Reading kept", value: "The first — this answer wasn't usable" });
    expect(spanDetails(unusable)).toContainEqual({ label: "Answer", value: "Not usable" });
    const fewer = spanDetails(span({ kind: "model", key: "run/model:extract_complete", attributes: { ...asked, accepted: false, kept_because: "quotes" } }));
    expect(fewer).toContainEqual({ label: "Reading kept", value: "The first — fewer of this answer's quotes were found in the letter" });

    // a call that broke off (a rate limit) is a failure like any other
    const broken = span({ kind: "model", key: "run/model:extract_complete", status: "error", attributes: { ...asked, outcome: "failed" } });
    expect(barTone(broken)).toBe("danger");
    expect(spanCopy(broken).flag).toEqual({ text: "Failed", tone: "danger" });

    // a comparison's step has no facts: its key still names it
    expect(spanCopy(span({ kind: "model", key: "run/model:extract_complete" })).title).toBe("Claude, asked for what it left out");
    expect(changeText(change({ kind: "model", name: "Extract · complete", key: "run/model:extract_complete", field: "present", before: false, after: true }))).toEqual({
      what: "Claude, asked for what it left out",
      detail: "Only in the newer reading",
    });

    // read again and compared: whether the re-ask's answer was used, and its usable answer is no repair's "fix"
    const reask = { kind: "model" as const, name: "Extract · complete", key: "run/model:extract_complete" };
    expect(changeText(change({ ...reask, field: "accepted", before: true, after: false })).detail).toBe("Answer used: yes → no");
    expect(changeText(change({ ...reask, field: "outcome", before: "failed", after: "repaired" })).detail).toBe("Answer: not usable → usable");

    // every reason the first reading was kept is said in words (KeptBecause in src/ordnung/ingest/extract.py)
    const reasons = ["no_answer", "unanswered", "unusable", "not_better", "date", "dropped", "uncovered", "unchecked", "later", "ungrounded", "quotes"];
    const labels = reasons.map((because) => {
      const rows = spanDetails(span({ kind: "model", key: "run/model:extract_complete", attributes: { ...asked, accepted: false, kept_because: because } }));
      const row = rows.find((r) => r.label === "Reading kept");
      expect(row?.value).toMatch(/^The first — /);
      assertNoRawEnums(row?.value ?? "");
      return row?.value;
    });
    expect(new Set(labels).size).toBe(reasons.length);

    for (const step of [used, kept, unusable, broken]) {
      const copy = spanCopy(step);
      assertNoRawEnums(`${copy.title} ${copy.summary} ${copy.flag?.text ?? ""}`);
      for (const row of spanDetails(step)) assertNoRawEnums(`${row.label} ${row.value}`);
    }
  });

  it("describes quotes, links and planning from their facts", () => {
    const quote = spanCopy(
      span({ kind: "verify", label: "Pay the parking fine", attributes: { target: "item", grounding: "unverified", best_score: 72.4, reasons: ["date_not_in_quote"] } }),
    );
    expect(quote.title).toBe("Pay the parking fine");
    expect(quote.summary).toBe("To-do · Not found (closest passage 72 %) · the quote doesn't state the date");
    expect(quote.flag?.text).toBe("Please check");
    // a recurrence's day of the month its quote doesn't name (graded like a working day)
    const fee = spanCopy(span({ kind: "verify", label: "Monthly gym fee", attributes: { target: "item", grounding: "verified", best_score: 100, reasons: ["day_of_month_not_in_quote"] } }));
    expect(fee.summary).toMatch(/· the quote doesn't state the day of the month$/);
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
    expect(spanCopy(span({ kind: "link", name: "Thread", attributes: { decision: "email", case_id: "cas_1", reference_kind: null } })).summary).toBe("Thread · Joined its e-mail's thread");
    expect(spanCopy(span({ kind: "plan", label: "Pay rent", attributes: { action: "kept_later_date", moved: false } })).summary).toMatch(/^Kept its later date/);
    const candidates = spanDetails(span({ kind: "link", name: "Sender", attributes: { decision: "new", candidates: [{ party_id: "pty_a", score: 66.7 }] } }), (id) =>
      id === "pty_a" ? "Stadt Musterstadt" : null,
    );
    expect(candidates).toContainEqual({ label: "Compared with", value: "Stadt Musterstadt (67 %)" });
  });

  it("says when a reading came back incomplete and Ordnung added a to-do of its own (ingest/gaps.py)", () => {
    const facts = { quotes: 1, verified: 1, model_read: 0, unverified: 0, needs_check: 1 };
    const checked = spanCopy(span({ kind: "verify", name: "Check quotes", attributes: { ...facts, reading_gap: "empty", check_item: "dated" } }));
    expect(checked.title).toBe("Quotes checked on the page");
    expect(checked.summary).toBe("1 quote: 1 in the text · reading came back incomplete — Ordnung added a to-do");
    // its own to-do is the one to check: not counted twice
    expect(checked.flag).toEqual({ text: "Reading incomplete", tone: "warn" });
    const more = spanCopy(span({ kind: "verify", name: "Check quotes", attributes: { ...facts, needs_check: 3, reading_gap: "remedy_left_out", check_item: "dated" } }));
    expect(more.flag).toEqual({ text: "Reading incomplete · 2 to check", tone: "warn" });
    // a complete reading's step is as before
    const complete = spanCopy(span({ kind: "verify", name: "Check quotes", attributes: facts }));
    expect(complete.summary).toBe("1 quote: 1 in the text");
    expect(complete.flag).toEqual({ text: "1 to check", tone: "warn" });
    // the to-do's own quote step names the reason in words, never its code
    const todo = spanCopy(
      span({ kind: "verify", label: "Deadline to object", attributes: { target: "item", grounding: "verified", page: 2, reasons: ["reading_incomplete"] } }),
    );
    expect(todo.summary).toBe("To-do · Found on page 2 · added by Ordnung because Claude's reading came back incomplete");
    // "Read this letter yourself" quotes nothing: nothing was looked for (UX review 2, R2UX-9)
    const placeholder = spanCopy(
      span({ kind: "verify", label: "Read this letter yourself", attributes: { target: "item", grounding: "unverified", slot_key: "check:reading", reasons: ["reading_incomplete"] } }),
    );
    expect(placeholder.summary).toMatch(/^To-do · Added by Ordnung — no sentence to find/);
    expect(todo.flag?.text).toBe("Please check");
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

  it("titles a reading by what happened: read, read again — or only stored (R2-document-pay-reading-6)", () => {
    const run = { reading: 1, trigger: "read", result: "processed", started_at: "2026-09-28T08:48:00Z" } as TraceRun;
    expect(runTitle(run, false)).toBe("Read on 28 Sep 2026");
    expect(runTitle({ ...run, reading: 2, trigger: "read_again" }, true)).toBe("Reading 2 · read again on 28 Sep 2026");
    // a letter from the watched folder waits unread: never "Read on …" next to "Stored — not read yet"
    const held = { ...run, result: "held" } as TraceRun;
    expect(runTitle(held, false)).toBe("Stored on 28 Sep 2026");
    expect(runTitle(held, true)).toBe("Reading 1 · stored on 28 Sep 2026");
    expect(runResult({ ...held, status: "ok", ended: "done", error: null })).toEqual({ text: "Stored — not read yet", tone: "neutral" });
  });

  it("names how a reading ended", () => {
    const run = { status: "ok", ended: "done", result: "processed", error: null } as TraceRun;
    expect(runResult(run)).toEqual({ text: "Filed", tone: "ok" });
    expect(runResult({ ...run, result: "needs_review" })).toEqual({ text: "Filed — something to check", tone: "warn" });
    // a letter from the watched folder is only stored until the person answers
    expect(runResult({ ...run, result: "held" })).toEqual({ text: "Stored — not read yet", tone: "neutral" });
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

  it("says where a quote's numbers were found: a photo's only in Claude's transcript, never “on the page”", () => {
    const numbers = (a: Record<string, unknown>) =>
      spanDetails(span({ kind: "verify", attributes: { target: "item", digit_groups: 2, ...a } })).find((r) => r.label === "Numbers")?.value;
    expect(numbers({ grounding: "verified", page: 1, digits_matched: true })).toBe("2 numbers checked digit by digit — all in the letter's text");
    expect(numbers({ grounding: "model_read", page: 1, digits_matched: true })).toBe(
      "2 numbers checked digit by digit — all in Claude's transcript — compare with the paper letter",
    );
    expect(numbers({ grounding: "unverified", digits_matched: false })).toBe("2 numbers checked digit by digit — not all in the closest passage");
    expect(numbers({ grounding: "unverified", digits_matched: null })).toBe("2 numbers checked digit by digit — no close passage");
    expect(changeText(change({ field: "digits_matched", before: false, after: true })).detail).toBe("Numbers in the passage found: no → yes");
  });

  it("names a computed date by its deadline's nature, as the Today page does", () => {
    const date = (nature: string, extra: Record<string, unknown> = {}) =>
      span({ kind: "rules", name: "Date", label: "X", attributes: { spec: { type: "fixed", date: "2026-10-08", nature }, due_date: "2026-10-08", ...extra } });
    const labels = (nature: string, extra?: Record<string, unknown>) => spanDetails(date(nature, extra)).map((r) => r.label);
    expect(spanDetails(date("appointment"))).toContainEqual({ label: "On", value: "Thu 8 Oct 2026" });
    expect(labels("other")).toContain("Date");
    expect(labels("payment")).toContain("Pay by");
    expect(labels("payment", { send_by: "2026-10-05" })).toEqual(expect.arrayContaining(["Transfer by", "Must arrive by"]));
    expect(labels("objection", { send_by: "2026-10-05" })).toEqual(expect.arrayContaining(["Send by", "Must arrive by"]));
    for (const nature of ["appointment", "other", "payment"]) expect(labels(nature)).not.toContain("Must arrive by");
    expect(spanCopy(date("payment", { send_by: "2026-10-05" })).summary).toBe("→ Thu 8 Oct 2026 · transfer by Mon 5 Oct 2026");
    // a refund coming in: nobody transfers it
    expect(spanDetails(date("payment", { send_by: "2026-10-05" }), undefined, undefined, false).map((r) => r.label)).toContain("Send by");
    expect(spanCopy(date("objection", { send_by: "2026-10-05" })).summary).toBe("→ Thu 8 Oct 2026 · send by Mon 5 Oct 2026");
  });

  it("names a newer model of the same family by its full id", () => {
    const same = changeText(change({ kind: "model", name: "Extract", field: "served_model", before: "claude-sonnet-x-1", after: "claude-sonnet-x-2" }));
    expect(same.detail).toBe("Model: claude-sonnet-x-1 → claude-sonnet-x-2");
    const other = changeText(change({ kind: "model", name: "Extract", field: "served_model", before: "claude-sonnet-x-1", after: "claude-opus-x-1" }));
    expect(other.detail).toBe("Model: Sonnet → Opus");
  });
});
