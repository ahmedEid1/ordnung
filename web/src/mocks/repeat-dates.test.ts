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

  it("are removed with dismissed, and set open again just as they were", async () => {
    const s = srv();
    const ustva = await add(s, "2026-10-01", THIRD_WORKING_DAY);
    expect(await patch(s, ustva.id, { status: "dismissed" })).toMatchObject({ status: "dismissed", due_date: "2026-10-05" });
    expect(await patch(s, ustva.id, { status: "open" })).toMatchObject({ status: "open", due_date: "2026-10-05", recurrence: THIRD_WORKING_DAY });
  });
});
