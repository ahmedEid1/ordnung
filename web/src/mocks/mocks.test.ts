import { describe, expect, it } from "vitest";
import { createMockServer } from "./server";
import { letterFor } from "./db";
import type { Dashboard, DocumentDetail, Evidence, Item, Lane, TimelineEntry } from "@/api/types";
import { findRawEnums } from "@/lib/copy";

const srv = () => createMockServer({ staticDemo: false, latency: 0 });

async function get<T>(s: ReturnType<typeof srv>, path: string, query = ""): Promise<T> {
  const res = await s.handle("GET", path, new URLSearchParams(query), undefined);
  expect(res.ok, `${path} → ${res.status}`).toBe(true);
  return (await res.json()) as T;
}

describe("mock dataset", () => {
  it("locates every evidence quote on its rendered letter page (boxes inside the page)", () => {
    const s = srv();
    const all: Evidence[] = [
      ...s.db.state.items.flatMap((i) => i.evidence),
      ...s.db.state.contracts.flatMap((c) => c.evidence),
      ...s.db.state.documents.flatMap((d) => d.key_facts.map((f) => f.evidence).filter((e): e is Evidence => Boolean(e))),
    ];
    expect(all.length).toBeGreaterThan(60);
    for (const e of all) {
      expect(e.grounding, `quote not found in ${e.doc_id}: “${e.quote}”`).not.toBe("unverified");
      expect(e.page).toBeGreaterThanOrEqual(1);
      expect(e.boxes.length).toBeGreaterThan(0);
      for (const b of e.boxes) {
        expect(b.x0).toBeGreaterThanOrEqual(0);
        expect(b.x1).toBeLessThanOrEqual(1);
        expect(b.y0).toBeLessThan(b.y1);
        expect(b.x0).toBeLessThan(b.x1);
      }
    }
  });

  it("renders page images for every letter", () => {
    const s = srv();
    for (const d of s.db.state.documents) {
      const letter = letterFor(d.id);
      expect(letter, d.id).not.toBeNull();
      expect(letter!.pages[0]).toMatch(/^<svg/);
      expect(s.resolveAsset(`/documents/${d.id}/pages/1.jpg`)).toMatch(/^data:image\/svg\+xml/);
    }
  });

  it("computes a consistent dashboard for Mon 28 Sep 2026", async () => {
    const s = srv();
    const dash = await get<Dashboard>(s, "/dashboard");
    expect(dash.today).toBe("2026-09-28");
    expect(dash.greeting_name).toBe("Sam");
    expect(dash.money.fixed_costs_monthly).toBeCloseTo(987, 2);
    expect(dash.attention.map((i) => i.id).slice(0, 2)).toEqual(["itm_parking", "itm_tm_dunning"]);
    expect(dash.decisions.map((c) => c.id)).toContain("ctr_phone");
    expect(dash.suggestions.length).toBeGreaterThanOrEqual(5);
    // views must never carry raw enums in human text fields
    for (const a of dash.areas) expect(findRawEnums(`${a.label} ${a.headline}`)).toEqual([]);
  });

  it("serves the timeline and lanes", async () => {
    const s = srv();
    const tl = await get<TimelineEntry[]>(s, "/timeline", "from=2026-09-01&to=2026-12-31");
    expect(tl.some((e) => e.ref.id === "itm_abh_appt" && e.time === "10:30")).toBe(true);
    expect([...tl].map((e) => e.date)).toEqual([...tl].map((e) => e.date).sort());
    const lanes = await get<Lane[]>(s, "/lanes");
    expect(lanes.map((l) => l.id)).toContain("lane_residence");
    expect(lanes.find((l) => l.id === "lane_tax")).toBeUndefined();
  });

  it("processes a New-mail letter live: stages, then items, ideas and lanes appear", async () => {
    const s = createMockServer({ staticDemo: false, latency: 0.001 });
    const res = await s.handle("POST", "/demo/mail", new URLSearchParams(), { id: "mail_finanzamt" });
    expect(res.status).toBe(200);
    await new Promise((r) => setTimeout(r, 60));
    const detail = await get<DocumentDetail>(s, "/documents/doc_tax");
    expect(detail.document.status).toBe("processed");
    expect(detail.document.remedy?.type).toBe("einspruch");
    const objection = detail.items.find((i) => i.id === "itm_tax_objection") as Item;
    expect(objection.due_date).toBe("2026-10-21");
    expect(objection.computation?.summary).toBe(
      "Letter dated Tue 15 Sep 2026 counts as delivered on Sat 19 Sep, moved to Mon 21 Sep; one month later is Wed 21 Oct 2026.",
    );
    expect(objection.evidence.every((e) => e.grounding === "model_read")).toBe(true);
    expect(detail.pages).toHaveLength(2);
    const lanes = await get<Lane[]>(s, "/lanes");
    expect(lanes.find((l) => l.id === "lane_tax")).toBeDefined();
  });

  it("confirming the parking fine's arrival recomputes the date with high confidence", async () => {
    const s = srv();
    await s.handle("PATCH", "/documents/doc_parking", new URLSearchParams(), { received_date: "2026-09-25" });
    const detail = await get<DocumentDetail>(s, "/documents/doc_parking");
    const it = detail.items.find((i) => i.id === "itm_parking")!;
    expect(it.due_date).toBe("2026-10-02");
    expect(it.computation?.confidence).toBe("high");
    expect(detail.document.status).toBe("processed");
  });

  it("keeps no unrecorded question, and its reply carries no message id (like the API's demo miss)", async () => {
    const s = srv();
    const res = await s.handle("POST", "/ask", new URLSearchParams(), { question: "What is the meaning of life?" });
    const done = (await res.text())
      .split("\n\n")
      .filter((block) => block.startsWith("data: "))
      .map((block) => JSON.parse(block.slice(6)) as { type: string; message_id?: string; thread_id?: string; text?: string })
      .find((e) => e.type === "done")!;
    // the UI marks an answer "Checked against your records" only when it was stored — this one never was checked
    expect(done.message_id).toBeUndefined();
    expect(done.text).toMatch(/recorded answers/);
    const history = await s.handle("GET", `/chat/${done.thread_id}`, new URLSearchParams(), undefined);
    expect(await history.json()).toEqual([]);
  });

  it("streams recorded Ask answers as SSE", async () => {
    const s = srv();
    const res = await s.handle("POST", "/ask", new URLSearchParams(), { question: "Can I still cancel my phone contract?" });
    expect(res.headers.get("Content-Type")).toBe("text/event-stream");
    const text = await res.text();
    // like the API: default `message` events whose JSON data carries the `type`
    expect(text).not.toContain("event:");
    expect(text).toContain('data: {"type":"tool_use"');
    expect(text).toContain("[item:itm_phone_cancel]");
    expect(text).toMatch(/data: \{"type":"done","text":".*"thread_id":"thr_/);
    expect(text).toMatch(/"citations":\[\{"type":"[a-z]+","id":"[a-z]+_[a-z_]+","label":"/);
  });

  it("sends no word before the check, then the checked answer with Ordnung's note (like the API)", async () => {
    const s = srv();
    const res = await s.handle("POST", "/ask", new URLSearchParams(), { question: "What did the Finanzamt send me?" });
    const events = (await res.text())
      .split("\n\n")
      .filter((block) => block.startsWith("data: "))
      .map(
        (block) =>
          JSON.parse(block.slice(6)) as { type: string; text?: string; note?: string | null; citations?: { id: string; label: string | null }[] },
      );
    const streamed = events.filter((e) => e.type === "text").map((e) => e.text ?? "").join("");
    const done = events.find((e) => e.type === "done")!;
    // like the real API, no word of the answer is sent before the check (review round 4): one "writing"
    // event, then the checked answer — the model's own date arithmetic never shows, not even briefly
    expect(events.filter((e) => e.type === "text")).toHaveLength(1);
    expect(streamed).toBe("");
    expect(done.text).not.toContain("17 Oct");
    expect(done.text).toContain("post it by **Thu 15 Oct** to be safe.");
    expect(done.text).toContain("**“324,00 €”**");
    // the note travels in its own field, like the API's
    expect(done.text).not.toContain("Checked by Ordnung");
    expect(done.note).toMatch(/^Left out 1 sentence: its date or amount isn't in the letter/);
    const threadId = (done as { thread_id?: string }).thread_id;
    const history = await s.handle("GET", `/chat/${threadId}`, new URLSearchParams(), undefined);
    const thread = (await history.json()) as { role: string; note: string | null }[];
    expect(thread.map((m) => m.note)).toEqual([null, done.note]);
    // the tax letter waits unopened in New mail: its records are labelled from the tray, never by id
    expect(done.citations!.map((c) => c.label)).toEqual([
      "Finanzamt Musterstadt",
      "Income tax assessment 2025",
      expect.stringMatching(/Einspruch/),
    ]);
  });

  it("refuses Claude-only actions in the static demo with a friendly message", async () => {
    const s = createMockServer({ staticDemo: true, latency: 0 });
    const res = await s.handle("POST", "/suggestions/review", new URLSearchParams(), {});
    expect(res.status).toBe(403);
    const body = (await res.json()) as { detail: string; code: string };
    expect(body.code).toBe("static_demo");
    expect(body.detail).toMatch(/Install Ordnung/);
  });
});
