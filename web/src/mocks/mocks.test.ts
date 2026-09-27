import { describe, expect, it } from "vitest";
import { createMockServer } from "./server";
import { letterFor } from "./db";
import type { Activity, Dashboard, DocumentDetail, Evidence, Item, Lane, RuleInfo, TimelineEntry } from "@/api/types";
import { findRawEnums } from "@/lib/copy";
import { needsArrivalDate } from "@/features/document/verdict";
import { RECORDED } from "./data/ask";
import { ITEMS } from "./data/items";
import { BRIEF_TEXT } from "./data/system";

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

  it("asks when a company's letter arrived, and counts from the day given", async () => {
    // read as deemed delivery, but the engine counted FitWell's letter from its arrival (§ 130 BGB)
    const s = srv();
    const before = await get<DocumentDetail>(s, "/documents/doc_gym_price");
    const it0 = before.items.find((i) => i.id === "itm_gym_price")!;
    expect(it0.date_spec?.anchor).toBe("deemed_delivery");
    expect(needsArrivalDate(it0, before.document)).toBe(true);
    expect(before.document.warnings.join(" ")).toMatch(/don't know when this letter arrived/);
    await s.handle("PATCH", "/documents/doc_gym_price", new URLSearchParams(), { received_date: "2026-09-16" });
    const after = await get<DocumentDetail>(s, "/documents/doc_gym_price");
    const it1 = after.items.find((i) => i.id === "itm_gym_price")!;
    expect(it1.due_date).toBe("2026-10-14");
    expect(it1.send_by).toBe("2026-10-08");
    expect(it1.computation?.confidence).toBe("high");
    expect(needsArrivalDate(it1, after.document)).toBe(false);
    // the page no longer says the arrival day is unknown, next to "Counting from Wed 16 Sep"
    expect(after.document.warnings.join(" ")).not.toMatch(/arrived/);
    expect(it1.computation?.warnings.join(" ")).not.toMatch(/We assumed the letter arrived/);
  });

  it("moves FitWell's deadline off a weekend like the app (§ 193 BGB), with a send-by date", async () => {
    // arrival Sat 19 Sep: four weeks end on Sat 17 Oct, which moves to Mon 19 Oct
    const s = srv();
    await s.handle("PATCH", "/documents/doc_gym_price", new URLSearchParams(), { received_date: "2026-09-19" });
    const it = (await get<DocumentDetail>(s, "/documents/doc_gym_price")).items.find((i) => i.id === "itm_gym_price")!;
    expect(it.due_date).toBe("2026-10-19");
    expect(it.computation?.send_by).toBe("2026-10-13");
    expect(it.computation?.summary).toBe(
      "Four weeks after the day you received it (Sat 19 Sep 2026) is Sat 17 Oct 2026, a Saturday, so the deadline moves to Mon 19 Oct 2026.",
    );
    const shift = it.computation?.steps.find((step) => step.rule_id === "bgb_193");
    expect(shift?.label).toBe("Sat 17 Oct 2026 is a Saturday, so the deadline moves to Mon 19 Oct 2026");
    // an end on a holiday moves too, named as the engine names it (an arrival on a later demo day)
    const s2 = srv();
    await s2.handle("PATCH", "/documents/doc_gym_price", new URLSearchParams(), { received_date: "2026-10-04" });
    const it2 = (await get<DocumentDetail>(s2, "/documents/doc_gym_price")).items.find((i) => i.id === "itm_gym_price")!;
    expect([it2.due_date, it2.send_by]).toEqual(["2026-11-02", "2026-10-27"]);
    expect(it2.computation?.steps.find((step) => step.rule_id === "bgb_193")?.label).toBe(
      "Sun 1 Nov 2026 is a public holiday, Allerheiligen, so the deadline moves to Mon 2 Nov 2026",
    );
  });

  it("says what FitWell announces, not that silence makes the price rise binding", async () => {
    const s = srv();
    const detail = await get<DocumentDetail>(s, "/documents/doc_gym_price");
    const it = detail.items.find((i) => i.id === "itm_gym_price")!;
    expect(it.consequence).toBe("FitWell says it will charge 32,90 € from 1 Nov unless you object.");
    expect([it.consequence, it.description, detail.document.summary].join(" ")).not.toMatch(/applies from|rises from|raises your/);
  });

  it("links every rule of FitWell's receipt to the rules catalog, by the engine's ids", async () => {
    // the static demo mirrors the app's receipt: "Four weeks later" is bgb_188 (§ 188 BGB), not an id
    // the engine never emits, so "Why this date?" finds each rule and its law link
    const s = srv();
    const rules = new Map((await get<RuleInfo[]>(s, "/rules")).map((r) => [r.id, r]));
    for (const received of [null, "2026-09-19"]) {
      const s2 = srv();
      if (received) await s2.handle("PATCH", "/documents/doc_gym_price", new URLSearchParams(), { received_date: received });
      const it = (await get<DocumentDetail>(s2, "/documents/doc_gym_price")).items.find((i) => i.id === "itm_gym_price")!;
      for (const step of it.computation!.steps.filter((step) => step.rule_id && step.rule_id !== "postal_buffer")) {
        expect(rules.get(step.rule_id!)?.url, `${step.rule_id} in the mock rules`).toMatch(/^https:\/\/www\.gesetze-im-internet\.de\//);
      }
      expect(it.computation!.rule_ids).toContain("bgb_188");
    }
    // no receipt in the static demo points at a rule the catalog lacks
    for (const item of s.db.state.items) {
      for (const step of item.computation?.steps ?? []) {
        if (step.rule_id && ["bgb_187_1", "bgb_188", "bgb_193", "private_sender_arrival"].includes(step.rule_id)) {
          expect(rules.has(step.rule_id)).toBe(true);
        }
      }
    }
  });

  it("knows FitWell's objection deadline in the recorded Ask answers and the activity feed", async () => {
    // the dashboard shows it: an answer about October or this week must not leave it out
    for (const question of ["Which deadlines are coming up in October?", "What do I need to do this week?"]) {
      const answer = RECORDED.find((a) => a.question === question)!;
      expect(answer.text, question).toContain("[item:itm_gym_price]");
      expect(answer.text, question).toContain("Tue 6 Oct");
      expect(answer.citations).toContainEqual({ type: "item", id: "itm_gym_price" });
    }
    // the October answer states what its list_items call returns: every open October to-do of the mock ledger
    const october = RECORDED.find((a) => a.question === "Which deadlines are coming up in October?")!;
    const query = october.tools.find((t) => t.name === "list_items")!;
    const open = ITEMS.filter(
      (i) => i.status === query.input.status && i.due_date && i.due_date >= String(query.input.from) && i.due_date <= String(query.input.to),
    );
    expect(open.length).toBeGreaterThan(7);
    expect(query.result).toBe(`Found ${open.length} to-dos & dates`);
    expect(october.text).toContain(`**${open.length} open to-dos and dates**`);
    const cited = new Set([...october.text.matchAll(/\[item:(itm_[a-z_]+)\]/g)].map((m) => m[1]));
    expect([...cited].sort()).toEqual(open.map((i) => i.id).sort());
    expect(new Set(october.citations.map((c) => c.id))).toEqual(cited);
    // this week's answer and the brief name next week's payment too (Nebenkosten, Fri 9 Oct)
    const week = RECORDED.find((a) => a.question === "What do I need to do this week?")!;
    expect(week.text).toContain("[item:itm_nk]");
    expect(BRIEF_TEXT).toMatch(/Nebenkosten back payment \(184,30 €/);
    const activity = await get<Activity[]>(srv(), "/activity");
    expect(activity.find((a) => a.ref_id === "doc_gym_price")?.message).toBe("Read “Gym price increase — FitWell” (1 page)");
    expect(new Set(activity.map((a) => a.id)).size).toBe(activity.length);
    const times = activity.map((a) => a.ts);
    expect([...times].sort().reverse()).toEqual(times);
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

  it("refuses Claude-only actions in the static demo with a friendly message", async () => {
    const s = createMockServer({ staticDemo: true, latency: 0 });
    const res = await s.handle("POST", "/suggestions/review", new URLSearchParams(), {});
    expect(res.status).toBe(403);
    const body = (await res.json()) as { detail: string; code: string };
    expect(body.code).toBe("static_demo");
    expect(body.detail).toMatch(/Install Ordnung/);
  });
});
