/**
 * Dates you add yourself that repeat, in the mock database as `POST`/`PATCH /api/items` file them (audit item 26;
 * tests/test_api_items_repeat.py is the API's side): placed by their rule at once, moved on when marked done (Undo
 * brings the date back), and started again at their date only when the person says so. The mock's today is Mon
 * 28 Sep 2026; Sat 3 Oct is a public holiday, and a working day is Monday to Saturday.
 */
import { describe, expect, it } from "vitest";
import type { Item, Recurrence } from "@/api/types";
import { createMockServer } from "./server";

const srv = () => createMockServer({ staticDemo: false, latency: 0 });
const MONTHLY: Recurrence = { interval: 1, unit: "months", working_day: null, day_of_month: null };
const THIRD_WORKING_DAY: Recurrence = { ...MONTHLY, working_day: 3 };

async function add(s: ReturnType<typeof srv>, due: string, recurrence: Partial<Recurrence> | null, extra: Record<string, unknown> = {}): Promise<Item> {
  const res = await s.handle("POST", "/items", new URLSearchParams(), { kind: "reminder", title: "UStVA", due_date: due, recurrence, ...extra });
  expect(res.status).toBe(201);
  return (await res.json()) as Item;
}

async function patch(s: ReturnType<typeof srv>, id: string, body: Record<string, unknown>): Promise<Item> {
  const res = await s.handle("PATCH", `/items/${id}`, new URLSearchParams(), body);
  expect(res.ok).toBe(true);
  return (await res.json()) as Item;
}

describe("your own repeating dates in the mock", () => {
  it("are placed by their rule at once: a working day in the month their date names, a passed day on to the next one", async () => {
    const s = srv();
    // Thu 1, Fri 2, (Sat 3 Oct is a holiday), Mon 5 Oct — whichever October day was chosen
    expect((await add(s, "2026-10-14", THIRD_WORKING_DAY)).due_date).toBe("2026-10-05");
    // September's (Thu 3 Sep) has passed
    expect((await add(s, "2026-09-01", THIRD_WORKING_DAY)).due_date).toBe("2026-10-05");
    expect((await add(s, "2026-10-01", { ...MONTHLY, working_day: -1 })).due_date).toBe("2026-10-30");
    expect((await add(s, "2026-08-10", MONTHLY)).due_date).toBe("2026-10-10");
    expect((await add(s, "2026-10-14", { ...MONTHLY, day_of_month: 20 })).due_date).toBe("2026-10-20");
    const plain = await add(s, "2026-09-01", null);
    expect(plain).toMatchObject({ due_date: "2026-09-01", recurrence: null, date_spec: null });
    // where the schedule starts: the date given
    expect((await add(s, "2026-10-14", THIRD_WORKING_DAY)).date_spec?.date).toBe("2026-10-14");
  });

  it("move on when marked done and stay open, and Undo brings the date back; one read from a letter closes as before", async () => {
    const s = srv();
    const ustva = await add(s, "2026-10-01", THIRD_WORKING_DAY);
    // Sun 1 Nov: Mon 2, Tue 3, Wed 4 Nov
    expect(await patch(s, ustva.id, { status: "done" })).toMatchObject({ status: "open", due_date: "2026-11-04", completed_at: null });
    expect(await patch(s, ustva.id, { status: "open" })).toMatchObject({ status: "open", due_date: "2026-10-05" });
    const quarterly = await add(s, "2026-10-31", { ...MONTHLY, interval: 3 });
    expect((await patch(s, quarterly.id, { status: "done" })).due_date).toBe("2027-01-31");
    expect((await patch(s, quarterly.id, { status: "done" })).due_date).toBe("2027-04-30");

    const letters = s.db.state.items.find((i) => i.origin === "extracted" && i.recurrence && i.status === "open")!;
    const due = letters.due_date;
    expect(await patch(s, letters.id, { status: "done" })).toMatchObject({ status: "done", due_date: due });
  });

  it("start again at their date for a new rule or a rule sent with its date; a date alone stands in for one; no rule stops them", async () => {
    const s = srv();
    const every = await add(s, "2026-10-10", MONTHLY);
    const restarted = await patch(s, every.id, { due_date: "2026-10-15", recurrence: MONTHLY });
    expect([restarted.due_date, restarted.date_spec?.date]).toEqual(["2026-10-15", "2026-10-15"]);
    expect((await patch(s, every.id, { status: "done" })).due_date).toBe("2026-11-15");

    const once = await add(s, "2026-10-10", MONTHLY);
    expect((await patch(s, once.id, { due_date: "2026-10-12" })).date_spec?.date).toBe("2026-10-10");
    expect((await patch(s, once.id, { status: "done" })).due_date).toBe("2026-11-10");

    const changed = await add(s, "2026-10-15", MONTHLY);
    expect((await patch(s, changed.id, { recurrence: THIRD_WORKING_DAY })).due_date).toBe("2026-10-05");
    const stopped = await patch(s, changed.id, { recurrence: null });
    expect([stopped.recurrence, stopped.due_date]).toEqual([null, "2026-10-05"]);
    expect((await patch(s, changed.id, { status: "done" })).status).toBe("done");
  });

  it("moved alone, stand in for the date they replace: marked done, the next one after that comes, as in the API", async () => {
    const s = srv();
    // a monthly fee paid early: the 10th moved to the 5th, then paid — November's is next, not October's again
    const fee = await add(s, "2026-10-10", MONTHLY);
    await patch(s, fee.id, { due_date: "2026-10-05" });
    expect(await patch(s, fee.id, { status: "done" })).toMatchObject({ status: "open", due_date: "2026-11-10" });
    // Undo: back to the moved date, still standing in for the 10th
    expect((await patch(s, fee.id, { status: "open" })).due_date).toBe("2026-10-05");
    expect((await patch(s, fee.id, { status: "done" })).due_date).toBe("2026-11-10");
    // a working day moved later: November's 3rd working day (Wed 4 Nov) still comes after it
    const ustva = await add(s, "2026-10-01", THIRD_WORKING_DAY);
    await patch(s, ustva.id, { due_date: "2026-11-10" });
    expect((await patch(s, ustva.id, { status: "done" })).due_date).toBe("2026-11-04");
  });

  it("every week: moves on a week when marked done and Undo brings it back; a past start goes to its next week; every 2 weeks keeps its weekday", async () => {
    const s = srv();
    const WEEKLY: Recurrence = { ...MONTHLY, unit: "weeks" };
    const TWO_WEEKS: Recurrence = { ...WEEKLY, interval: 2 };
    // Thu 1 Oct, from Mon 28 Sep
    const physio = await add(s, "2026-10-01", WEEKLY, { title: "Physio" });
    expect([physio.due_date, physio.date_spec?.date]).toEqual(["2026-10-01", "2026-10-01"]);
    expect(await patch(s, physio.id, { status: "done" })).toMatchObject({ status: "open", due_date: "2026-10-08", completed_at: null });
    expect(await patch(s, physio.id, { status: "open" })).toMatchObject({ status: "open", due_date: "2026-10-01" });
    // Thu 3 Sep is weeks back: its next Thursday from today
    const past = await add(s, "2026-09-03", WEEKLY);
    expect([past.due_date, past.date_spec?.date]).toEqual(["2026-10-01", "2026-09-03"]);
    // every 2 weeks from Thu 10 Sep: Thu 24 Sep has passed, so Thu 8 Oct, then Thu 22 Oct
    const session = await add(s, "2026-09-10", TWO_WEEKS);
    expect(session.due_date).toBe("2026-10-08");
    expect((await patch(s, session.id, { status: "done" })).due_date).toBe("2026-10-22");
    // the same rule as 14 days, sent alone, is no new rule: no new start
    const same = await patch(s, session.id, { recurrence: { interval: 14, unit: "days" } });
    expect([same.due_date, same.date_spec?.date]).toEqual(["2026-10-22", "2026-09-10"]);
  });

  it("every week from decades back: its next week from today, as the server finds it (D1 review: the mock gave up after 1200 weeks)", async () => {
    const s = srv();
    const WEEKLY: Recurrence = { ...MONTHLY, unit: "weeks" };
    // Thu 6 Jan 2000 is 1395 weeks back; every 2 weeks from Thu 3 Jan 1980, 1220 steps
    const weekly = await add(s, "2000-01-06", WEEKLY);
    expect([weekly.due_date, weekly.date_spec?.date]).toEqual(["2026-10-01", "2000-01-06"]);
    expect((await patch(s, weekly.id, { status: "done" })).due_date).toBe("2026-10-08");
    expect((await add(s, "1980-01-03", { ...WEEKLY, interval: 2 })).due_date).toBe("2026-10-08");
  });

  it("every week, moved: alone it comes back to its weekday, with its rule every week after moves", async () => {
    const s = srv();
    const WEEKLY: Recurrence = { ...MONTHLY, unit: "weeks" };
    // "Only this one": Thu 1 Oct on Fri 2 Oct, then Thu 8 Oct
    const once = await add(s, "2026-10-01", WEEKLY);
    expect((await patch(s, once.id, { due_date: "2026-10-02" })).date_spec?.date).toBe("2026-10-01");
    expect((await patch(s, once.id, { status: "done" })).due_date).toBe("2026-10-08");
    // "This one and every one after": Fridays from Fri 2 Oct
    const every = await add(s, "2026-10-01", WEEKLY);
    const restarted = await patch(s, every.id, { due_date: "2026-10-02", recurrence: WEEKLY });
    expect([restarted.due_date, restarted.date_spec?.date]).toEqual(["2026-10-02", "2026-10-02"]);
    expect((await patch(s, every.id, { status: "done" })).due_date).toBe("2026-10-09");
  });

  it("are removed with dismissed, and set open again just as they were", async () => {
    const s = srv();
    const ustva = await add(s, "2026-10-01", THIRD_WORKING_DAY);
    expect(await patch(s, ustva.id, { status: "dismissed" })).toMatchObject({ status: "dismissed", due_date: "2026-10-05" });
    expect(await patch(s, ustva.id, { status: "open" })).toMatchObject({ status: "open", due_date: "2026-10-05", recurrence: THIRD_WORKING_DAY });
  });
});
