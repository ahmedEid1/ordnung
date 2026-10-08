/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { createMockServer } from "./server";
import { letterFor } from "./db";
import type {
  Activity,
  Contract,
  Dashboard,
  DocumentDetail,
  Draft,
  Evidence,
  Item,
  Lane,
  RuleInfo,
  TimelineEntry,
  ListedItem,
  WeeklySession,
} from "@/api/types";
import { findRawEnums } from "@/lib/copy";
import { needsArrivalDate } from "@/features/document/verdict";
import { TRAY_DOCUMENTS } from "./data/documents";
import { BRIEF_TEXT, PROFILE } from "./data/system";
import { FALLBACK_ANSWER, RECORDED, SUGGESTED_QUESTIONS } from "./data/ask";
import { CHECK_LABELS, DRAFTS } from "./data/drafts";
import { PARTIES } from "./data/parties";
import { CONTRACTS } from "./data/contracts";
import { ITEMS } from "./data/items";

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
    // a proof file is a photo of a receipt, not a letter: it has a picture of its own
    for (const d of s.db.state.documents.filter((x) => x.source === "proof")) {
      expect(s.resolveAsset(`/documents/${d.id}/pages/1.jpg`), d.id).toMatch(/^data:image\/svg\+xml/);
    }
    for (const d of s.db.state.documents.filter((x) => x.source !== "proof")) {
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
    // like the API's `is_decision`: a term that locks in — never a contract you can end any month (the
    // Deutschlandticket by the 10th, the job its contract lets Sam leave), however soon its send-by date
    expect(dash.decisions.map((c) => c.id)).toEqual(["ctr_phone"]);
    const rolling = s.db.state.contracts.filter((c) => c.id === "ctr_dticket" || c.id === "ctr_job");
    expect(rolling.map((c) => c.computed?.send_by)).toEqual(["2026-10-05", "2026-09-28"]);
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
    // like the API, a range clips the bars to it (the chart says "continues after", never an invented end)
    const ranged = await get<Lane[]>(s, "/lanes", "from=2026-06-01&to=2027-09-30");
    const lease = ranged.find((l) => l.id === "lane_home")!.bars[0]!;
    expect([lease.start, lease.end]).toEqual(["2026-06-01", "2027-09-30"]);
    for (const b of ranged.flatMap((l) => l.bars)) for (const m of b.markers) expect(m.date >= "2026-06-01" && m.date <= "2027-09-30").toBe(true);
  });

  it("words a timeline to-do's day as the API does: transfer, direct debit or post (R2-inbox-timeline-contracts-3)", async () => {
    const s = srv();
    const items = s.db.state.items;
    Object.assign(items.find((i) => i.id === "itm_parking")!, { send_by: "2026-09-25" });
    Object.assign(items.find((i) => i.id === "itm_bkk")!, { send_by: "2026-10-13", description: "Collected by direct debit (Lastschrift)." });
    const tl = await get<TimelineEntry[]>(s, "/timeline", "from=2026-09-01&to=2026-12-31");
    const subtitle = (id: string) => tl.find((e) => e.ref.id === id)?.subtitle;
    expect(subtitle("itm_parking")).toBe("Transfer by Fri 25 Sep");
    expect(subtitle("itm_bkk")).toBe("Collected by direct debit");
    expect(subtitle("itm_gym_price")).toBe("Send by Tue 6 Oct");
  });

  it("lists to-dos with why they are set aside, as the API does", async () => {
    const s = srv();
    s.db.state.items.find((i) => i.id === "itm_tm_invoice")!.status = "open";
    const items = await get<ListedItem[]>(s, "/items", "status=open");
    expect(items.find((i) => i.id === "itm_tm_invoice")?.aside).toEqual({ item_id: "itm_tm_invoice", reason: "replaced", replaced_by: "doc_tm_dunning" });
    expect(items.find((i) => i.id === "itm_tm_dunning")?.aside).toBeNull();
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

  it("says on the letter that a re-filed letter keeps the dates of the kind it was read as (no rules engine)", async () => {
    // review round 1: a Mahnbescheid re-filed as an enforcement order still said "object (Widerspruch)"
    const s = srv();
    await s.handle("PATCH", "/documents/doc_lease", new URLSearchParams(), { kind: "landlord_notice" });
    let doc = (await get<DocumentDetail>(s, "/documents/doc_lease")).document;
    const notes = doc.warnings.filter((w) => w.startsWith("Online demo:"));
    expect(notes).toHaveLength(1);
    expect(notes[0]).toMatch(/still those of the kind it was read as, “.+”\. This demo has no rules engine to work them out again for “Notice from your landlord”/);
    // filed as another kind again: still one note; back as read: none
    await s.handle("PATCH", "/documents/doc_lease", new URLSearchParams(), { kind: "rent_increase" });
    doc = (await get<DocumentDetail>(s, "/documents/doc_lease")).document;
    expect(doc.warnings.filter((w) => w.startsWith("Online demo:"))).toHaveLength(1);
    await s.handle("PATCH", "/documents/doc_lease", new URLSearchParams(), { kind: "rent_lease" }); // as it was read
    doc = (await get<DocumentDetail>(s, "/documents/doc_lease")).document;
    expect(doc.warnings.filter((w) => w.startsWith("Online demo:"))).toEqual([]);
  });

  it("drops a statement's card once the person files it as the utility bill it is stored as (review round 2)", async () => {
    const s = srv();
    const before = await get<DocumentDetail>(s, "/documents/doc_nebenkosten");
    expect(before.document.kind).toBe("utility_bill");
    expect(before.advice?.kind).toBe("operating_costs");
    await s.handle("PATCH", "/documents/doc_nebenkosten", new URLSearchParams(), { kind: "utility_bill" });
    expect((await get<DocumentDetail>(s, "/documents/doc_nebenkosten")).advice).toBeNull();
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
    expect(it.consequence).toBe("FitWell says it will charge €32.90 from 1 Nov unless you object.");
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
    expect(BRIEF_TEXT).toMatch(/Nebenkosten back payment \(€184\.30 by Fri 9 Oct\)/);
    const activity = await get<Activity[]>(srv(), "/activity");
    expect(activity.find((a) => a.ref_id === "doc_gym_price")?.message).toBe("Read “Gym price increase — FitWell” (1 page)");
    expect(new Set(activity.map((a) => a.id)).size).toBe(activity.length);
    const times = activity.map((a) => a.ts);
    expect([...times].sort().reverse()).toEqual(times);
  });

  it("keeps no unrecorded question, and answers it with the API's demo miss", async () => {
    const s = srv();
    const res = await s.handle("POST", "/ask", new URLSearchParams(), { question: "What is the meaning of life?" });
    const events = (await res.text())
      .split("\n\n")
      .filter((block) => block.startsWith("data: "))
      .map((block) => JSON.parse(block.slice(6)) as { type: string; error?: string; error_code?: string });
    // like the local demo: one error whose code makes the Ask page show a note, not a failure to retry
    expect(events).toEqual([{ type: "error", error: FALLBACK_ANSWER, text: FALLBACK_ANSWER, error_code: "demo_miss" }]);
    const threads = s.db.state.chat.filter((m) => m.content === "What is the meaning of life?");
    expect(threads).toEqual([]);
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

  it("writes money the app's English way (€94.99) wherever the sample life speaks English", async () => {
    const s = srv();
    for (const id of Object.keys(TRAY_DOCUMENTS)) s.db.applyTrayDocument(id);
    const st = s.db.state;
    const english: (string | null | undefined)[] = [
      BRIEF_TEXT,
      FALLBACK_ANSWER,
      ...RECORDED.flatMap((r) => [r.text, ...r.tools.map((t) => t.result)]),
      ...st.documents.flatMap((d) => [d.title, d.summary, d.explanation, ...d.key_facts.flatMap((f) => [f.label, f.value]), ...d.warnings]),
      ...st.cases.flatMap((c) => [c.title, c.summary]),
      ...st.items.flatMap((i) => [i.title, i.description, i.action, i.consequence, i.computation?.summary]),
      ...st.suggestions.flatMap((x) => [x.title, x.body]),
      ...st.contracts.flatMap((c) => [c.name, c.cancel_hint, c.computed?.summary, ...(c.computed?.notes ?? []), ...(c.computed?.warnings ?? [])]),
      ...st.drafts.map((d) => d.body_translation),
      ...st.activity.map((a) => a.message),
      ...(await get<Lane[]>(s, "/lanes")).flatMap((l) => [l.label, ...l.markers.map((m) => m.label), ...l.bars.flatMap((b) => [b.label, ...b.markers.map((m) => m.label)])]),
    ];
    expect(english.filter(Boolean).length).toBeGreaterThan(300);
    // "94,99 €", "5 €", "1.049 €", "32,10 ct" read as German next to the app's "€94.99"
    const germanMoney = /\d[\s\u00a0]?€|\d,\d{2}(?!\d)/;
    expect(english.filter((t): t is string => Boolean(t && germanMoney.test(t)))).toEqual([]);
  });

  it("gives each kind of letter the API's checks, with details that fit it", async () => {
    // the labels are the API's, word for word
    const py = readFileSync(resolve(__dirname, "../../../src/ordnung/drafts/checks.py"), "utf8");
    const block = /LABELS: dict\[str, str\] = \{([\s\S]*?)\n\}/.exec(py)?.[1] ?? "";
    expect(Object.fromEntries([...block.matchAll(/"(\w+)": "([^"]+)"/g)].map((m) => [m[1], m[2]]))).toEqual(CHECK_LABELS);

    const s = srv();
    const detail = (d: Draft, id: string) => d.checks.find((c) => c.id === id)?.detail;
    const phone = await get<Draft>(s, "/drafts/drf_phone");
    expect(phone.checks.every((c) => c.ok)).toBe(true);
    expect(detail(phone, "has_dates")).toBe("Says when the contract should end.");
    expect(detail(phone, "has_reference")).toBe("Mentions 7700 4412 09.");

    // the reply to the landlord: no end date to state, its tenant number, sent by email
    const reply = await get<Draft>(s, "/drafts/drf_wohnbau");
    expect(reply.checks.every((c) => c.ok)).toBe(true);
    expect(reply.checks.map((c) => c.label).join(" ")).not.toMatch(/end date/i);
    expect(detail(reply, "has_dates")).toBe("No dates are needed for this letter.");
    expect(detail(reply, "has_reference")).toBe("Mentions 12-0412-07.");
    expect(detail(reply, "delivery_channel_ok")).toBe("Email to vermietung@wohnbau-musterstadt.example is fine for this letter.");

    // an objection names the decision's date; a reply with a gap to fill says so — and saving checks again
    s.db.applyTrayDocument("doc_tax");
    const objection = (await (await s.handle("POST", "/drafts", new URLSearchParams(), { kind: "objection", doc_id: "doc_tax" })).json()) as Draft;
    expect(detail(objection, "has_dates")).toBe("Names the date of the decision.");
    const question = (await (await s.handle("POST", "/drafts", new URLSearchParams(), { kind: "general_reply", doc_id: "doc_nebenkosten", instructions: "ask" })).json()) as Draft;
    expect(question.checks.find((c) => c.id === "no_placeholders")).toMatchObject({ ok: false, detail: "Replace “…” before sending." });
    const saved = (await (
      await s.handle("PATCH", `/drafts/${question.id}`, new URLSearchParams(), { body: question.body.replace("…", "Wann kann ich die Belege einsehen?") })
    ).json()) as Draft;
    expect(saved.checks.every((c) => c.ok)).toBe(true);
  });

  it("uses the demo persona's two-line address", () => {
    expect(PROFILE.address).toBe("Beispielweg 5\n12345 Musterstadt");
  });

  it("addresses FunkNetz's cancellation to the address its letter and details show, as the demo does", () => {
    const funknetz = PARTIES.find((p) => p.id === "pty_funknetz")!;
    const draft = DRAFTS.find((d) => d.id === "drf_phone")!;
    expect(draft.recipient_block).toBe(`${funknetz.name}\n${funknetz.address!.replace(", ", "\n")}`);
  });

  it("answers a question without a recording with the demo miss in the online demo too (its Ask page says why)", async () => {
    // every suggested question has a recording, so only questions of one's own get the note
    for (const q of SUGGESTED_QUESTIONS) {
      const lower = q.toLowerCase();
      expect(RECORDED.some((r) => r.question.toLowerCase() === lower || r.match.some((g) => g.every((w) => lower.includes(w)))), q).toBe(true);
    }
    const ask = async (staticDemo: boolean) => {
      const res = await createMockServer({ staticDemo, latency: 0 }).handle("POST", "/ask", new URLSearchParams(), { question: "Who won the football?" });
      return res.text();
    };
    // no words, no "writing" line: the page shows its note for the code, the same in mock mode (?mock=1)
    for (const staticDemo of [true, false]) {
      const reply = await ask(staticDemo);
      expect(reply).not.toContain('"type":"text"');
      expect(reply).not.toContain('"type":"done"');
      expect(reply).toContain('"error_code":"demo_miss"');
    }
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
    expect(done.text).toContain("**“€324.00”**");
    // the note travels in its own field, like the API's
    expect(done.text).not.toContain("Checked by Ordnung");
    expect(done.note).toMatch(/^Left out 1 sentence: its date, time or amount isn't among the dates and amounts Ordnung saved/);
    const threadId = (done as { thread_id?: string }).thread_id;
    const history = await s.handle("GET", `/chat/${threadId}`, new URLSearchParams(), undefined);
    const thread = (await history.json()) as { role: string; note: string | null; note_label: string | null; checked: boolean }[];
    expect(thread.map((m) => m.note)).toEqual([null, done.note]);
    // like the API: the label comes with the answer, and a stored answer says it was checked
    expect((done as { note_label?: string }).note_label).toBe("Checked by Ordnung:");
    expect(thread.map((m) => [m.checked, m.note_label])).toEqual([
      [false, null],
      [true, "Checked by Ordnung:"],
    ]);
    // the tax letter waits unopened in New mail: its records are labelled from the tray, never by id
    expect(done.citations!.map((c) => c.label)).toEqual([
      "Finanzamt Musterstadt",
      "Income tax assessment 2025",
      expect.stringMatching(/Einspruch/),
    ]);
  });

  it("says in the weekly session that a letter from the folder waits, and that one kept private was not read", async () => {
    const s = srv();
    const note = async () => {
      const week = await get<WeeklySession>(s, "/week");
      return week.steps.find((st) => st.id === "new")!.entries.find((e) => e.ref.id === "doc_folder_scan")?.note;
    };
    expect(await note()).toBe("Not read yet — read it with Claude or keep it private.");
    const res = await s.handle("POST", "/documents/held/keep-private", new URLSearchParams(), { doc_ids: ["doc_folder_scan"] });
    expect(res.ok).toBe(true);
    expect(await note()).toBe("Kept private — not read, so look through it yourself.");
  });

  it("adds a date of the person's own as the API files it, in the online demo too — a letter kept private included", async () => {
    const s = createMockServer({ staticDemo: true, latency: 0 });
    const post = (body: unknown) => s.handle("POST", "/items", new URLSearchParams(), body);
    const created = await post({ kind: "payment", title: " Pay the caretaker ", due_date: "2026-10-20", amount: 45, doc_id: "doc_folder_scan", area: "home" });
    expect(created.status).toBe(201);
    const item = (await created.json()) as Item;
    expect(item).toMatchObject({
      title: "Pay the caretaker",
      currency: "EUR",
      direction: "out",
      origin: "manual",
      grounding: "user",
      due_date_source: "manual",
      slot_key: null,
      filed_on: s.db.today,
      doc_id: "doc_folder_scan",
    });
    // on the letter's page, the timeline and Today like any other date
    expect((await get<DocumentDetail>(s, "/documents/doc_folder_scan")).items.map((i) => i.id)).toContain(item.id);
    expect((await get<TimelineEntry[]>(s, "/timeline")).some((e) => e.ref.type === "item" && e.ref.id === item.id)).toBe(true);
    // refused as the API refuses it
    expect((await post({ kind: "reminder", title: "x", doc_id: "doc_nope" })).status).toBe(404);
    expect((await post({ kind: "reminder", title: "  " })).status).toBe(422);
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

describe("the mock's clock (walkthrough of phase 2)", () => {
  it("stamps what it records on the demo's today, never the real date", async () => {
    const s = srv();
    s.openAllMail();
    const today = s.db.today;
    const docs = s.db.state.documents.filter((d) => d.ai_processed_at && d.updated_at >= `${today}T00:00:00Z`);
    for (const d of docs) expect(d.ai_processed_at!.slice(0, 10) <= today).toBe(true);
    const created = await s.handle("POST", "/items", new URLSearchParams(), { kind: "task", title: "Call the office" });
    const item = (await created.json()) as Item;
    expect(item.created_at.slice(0, 10)).toBe(today);
  });
});

describe("mock contracts", () => {
  it("like the API: notice terms the person saves clear the letter's day of the month, and an Undo puts it back", async () => {
    const s = srv();
    const bank = s.db.state.contracts.find((c) => c.id === "ctr_bank")!;
    bank.notice_day = 10;
    const patch = async (body: Record<string, unknown>) => {
      const res = await s.handle("PATCH", "/contracts/ctr_bank", new URLSearchParams(), body);
      expect(res.ok).toBe(true);
      return ((await res.json()) as { notice_day: number | null }).notice_day;
    };
    expect(await patch({ cost_amount: 5.9 })).toBe(10);
    expect(await patch({ notice_value: 1, notice_unit: "months", notice_basis: "end_of_month" })).toBeNull();
    expect(await patch({ notice_value: null, notice_unit: null, notice_basis: null, notice_day: 10 })).toBe(10);
  });

  const patched = async (id: string, body: Record<string, unknown>) => {
    const res = await srv().handle("PATCH", `/contracts/${id}`, new URLSearchParams(), body);
    expect(res.ok).toBe(true);
    return (await res.json()) as Contract;
  };

  it("like the rules engine: the Deutschlandticket's day of the month, corrected on its card", async () => {
    const day15 = await patched("ctr_dticket", { notice_value: null, notice_unit: null, notice_basis: "end_of_month", notice_day: 15 });
    expect(day15.computed).toMatchObject({ cancel_by: "2026-10-15", safe_date: "2026-10-15", send_by: "2026-10-09", earliest_exit: "2026-10-31", confidence: "high", warnings: [] });
    expect(day15.computed!.summary).toBe("To leave on Sat 31 Oct 2026, your notice must arrive by Thu 15 Oct 2026 (the 15th of the month, as the contract says); send it by Fri 9 Oct.");
    expect(day15.evidence.filter((e) => e.grounding === "user").map((e) => e.quote)).toEqual(["notice by the 15th of the month, to the end of that month"]);
    // as the engine gives it for the demo's own terms (web/src/mocks/data/contracts.ts)
    const again = await patched("ctr_dticket", { notice_value: null, notice_unit: null, notice_basis: "end_of_month", notice_day: 10 });
    const ticket = CONTRACTS.find((c) => c.id === "ctr_dticket")!;
    expect(again.computed).toMatchObject({ ...ticket.computed, steps: ticket.computed!.steps.map((st) => ({ label: st.label, date: st.date })) });
    // the day cleared, a period instead: at most one month, from any day (§ 309 Nr. 9 BGB)
    const month = await patched("ctr_dticket", { notice_value: 3, notice_unit: "months", notice_basis: "end_of_month" });
    expect(month.notice_day).toBeNull();
    expect(month.computed!.summary).toBe("You can cancel any time with one month's notice: if your cancellation arrives by Fri 2 Oct 2026, the contract ends on Mon 2 Nov 2026.");
  });

  it("like the rules engine: a fixed-term job's early notice, ticked or not on its card", async () => {
    const terms = { notice_value: 4, notice_unit: "weeks", notice_basis: null, notice_day: null };
    const fixed = await patched("ctr_job", { ...terms, notice_before_end: false });
    expect(fixed.computed).toMatchObject({ current_term_end: "2027-03-31", cancel_by: null, send_by: null, earliest_exit: "2027-03-31" });
    expect(fixed.computed!.summary).toBe("This contract ends by itself on Wed 31 Mar 2027 — no cancellation needed.");
    expect(fixed.evidence.filter((e) => e.grounding === "user").map((e) => e.quote)).toEqual(["four weeks' notice to the 15th or the end of a month"]);
    const early = await patched("ctr_job", { ...terms, notice_before_end: true });
    const job = CONTRACTS.find((c) => c.id === "ctr_job")!;
    expect(early.computed).toMatchObject({ ...job.computed, notes: job.computed!.notes, steps: job.computed!.steps.map((st) => ({ label: st.label, date: st.date })) });
    // two weeks (the probation period's): at least four weeks before the end date (§ 622 Abs. 1 BGB)
    const short = await patched("ctr_job", { ...terms, notice_value: 2, notice_before_end: true });
    expect(short.computed).toMatchObject({ cancel_by: "2026-10-03", earliest_exit: "2026-10-31" });
    expect(short.computed!.warnings).toEqual([expect.stringMatching(/^Before the fixed term's end we used at least four weeks' notice/)]);
  });
});
