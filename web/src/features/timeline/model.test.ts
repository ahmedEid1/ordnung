import { describe, expect, it } from "vitest";
import type { TimelineEntry } from "@/api/types";
import { TIMELINE_TYPES } from "@/api/types";
import { assertNoRawEnums } from "@/lib/copy";
import {
  NO_FILTERS,
  activeFilterCount,
  applyFilters,
  entryForDate,
  entryMeta,
  entryStatus,
  filterOptions,
  filtersFromParams,
  filtersToParams,
  groupByMonth,
} from "./model";
import { reminderSentence } from "./calendar";

const TODAY = "2026-09-28";

let n = 0;
const entry = (e: Partial<TimelineEntry> & Pick<TimelineEntry, "date">): TimelineEntry => ({
  id: `e${++n}`,
  time: null,
  type: "deadline",
  title: `Entry ${n}`,
  subtitle: null,
  status: "open",
  priority: "normal",
  area: "home",
  ref: { type: "item", id: `itm_${n}` },
  party_name: null,
  amount: null,
  currency: null,
  past: e.date < TODAY,
  ...e,
});

describe("groupByMonth", () => {
  const entries = [
    entry({ date: "2026-10-14", title: "Phone cancellation must arrive" }),
    entry({ date: "2026-09-03", title: "Rent September", type: "payment", amount: 640, status: "done" }),
    entry({ date: "2026-09-30", title: "TechMarkt reminder", type: "payment", amount: 94.99 }),
    entry({ date: "2026-09-28", title: "Letter arrived", type: "document", status: "processed" }),
    entry({ date: "2026-10-05", title: "Rent October", type: "payment", amount: 640 }),
    entry({ date: "2027-01-15", title: "Semester fee", type: "payment", amount: 312.4 }),
  ];

  it("groups chronologically by calendar month, entries sorted by date", () => {
    const groups = groupByMonth(entries, TODAY);
    expect(groups.map((g) => g.key)).toEqual(["2026-09", "2026-10", "2027-01"]);
    expect(groups.map((g) => `${g.month} ${g.year}`)).toEqual(["September 2026", "October 2026", "January 2027"]);
    expect(groups[0]!.entries.map((e) => e.date)).toEqual(["2026-09-03", "2026-09-28", "2026-09-30"]);
    expect(groups[1]!.entries.map((e) => e.title)).toEqual(["Rent October", "Phone cancellation must arrive"]);
  });

  it("places the Today divider before the first entry dated today or later", () => {
    const [sep, oct] = groupByMonth(entries, TODAY);
    expect(sep!.todayIndex).toBe(1);
    expect(oct!.todayIndex).toBeNull();
  });

  it("sums only open payments from today on", () => {
    const [sep, oct, jan] = groupByMonth(entries, TODAY);
    expect(sep!.toPay).toEqual({ EUR: 94.99 }); // September rent is done and in the past
    expect(oct!.toPay).toEqual({ EUR: 640 });
    expect(jan!.toPay).toEqual({ EUR: 312.4 });
  });

  it("sums each currency on its own (a $50 invoice is not €50 of the month)", () => {
    const [oct] = groupByMonth(
      [entry({ date: "2026-10-05", type: "payment", amount: 640 }), entry({ date: "2026-10-09", type: "payment", amount: 50, currency: "USD" })],
      TODAY,
    );
    expect(oct!.toPay).toEqual({ EUR: 640, USD: 50 });
  });

  it("creates today's month when it has no entries, so the divider always has a home", () => {
    const groups = groupByMonth([entry({ date: "2026-08-01" }), entry({ date: "2026-11-01" })], TODAY, { from: "2026-06-01", to: "2027-09-30" });
    expect(groups.map((g) => g.key)).toEqual(["2026-08", "2026-09", "2026-11"]);
    expect(groups[1]!.entries).toHaveLength(0);
    expect(groups[1]!.todayIndex).toBe(0);
    expect(groups[0]!.past).toBe(true);
  });

  it("puts the divider at the end of the month when everything this month is past", () => {
    const [sep] = groupByMonth([entry({ date: "2026-09-02" }), entry({ date: "2026-09-10" })], TODAY);
    expect(sep!.todayIndex).toBe(2);
  });

  it("orders same-day entries by time, then kind (deadlines before payments)", () => {
    const [g] = groupByMonth(
      [
        entry({ date: "2026-10-14", type: "payment", title: "Fee" }),
        entry({ date: "2026-10-14", type: "appointment", time: "10:30", title: "Appointment" }),
        entry({ date: "2026-10-14", type: "deadline", title: "Cancel" }),
      ],
      TODAY,
    );
    expect(g!.entries.map((e) => e.title)).toEqual(["Cancel", "Fee", "Appointment"]);
  });
});

describe("filters", () => {
  const entries = [
    entry({ date: "2026-09-01", type: "payment", area: "home", party_name: "Wohnbau Musterstadt eG" }),
    entry({ date: "2026-10-05", type: "payment", area: "home", party_name: "Wohnbau Musterstadt eG" }),
    entry({ date: "2026-10-14", type: "deadline", area: "residence", party_name: "Ausländerbehörde" }),
    entry({ date: "2026-10-21", type: "deadline", area: "tax", party_name: null }),
  ];

  it("filter by kind, area, person/organisation and hide the past", () => {
    expect(applyFilters(entries, { ...NO_FILTERS, type: "payment" }, TODAY)).toHaveLength(2);
    expect(applyFilters(entries, { ...NO_FILTERS, area: "residence" }, TODAY)).toHaveLength(1);
    expect(applyFilters(entries, { ...NO_FILTERS, party: "Wohnbau Musterstadt eG" }, TODAY)).toHaveLength(2);
    expect(applyFilters(entries, { ...NO_FILTERS, showPast: false }, TODAY).map((e) => e.date)).toEqual(["2026-10-05", "2026-10-14", "2026-10-21"]);
    expect(applyFilters(entries, { type: "payment", area: "home", party: null, showPast: false }, TODAY)).toHaveLength(1);
  });

  it("round-trips through the URL and keeps unrelated params (e.g. the party drawer)", () => {
    const params = new URLSearchParams("party=pty_x&area=residence&type=bogus&past=0");
    const f = filtersFromParams(params);
    expect(f).toEqual({ type: null, area: "residence", party: null, showPast: false });
    expect(activeFilterCount(f)).toBe(2);
    const next = filtersToParams({ ...f, party: "Wohnbau Musterstadt eG", showPast: true }, params);
    expect(next.get("party")).toBe("pty_x");
    expect(next.get("with")).toBe("Wohnbau Musterstadt eG");
    expect(next.has("past")).toBe(false);
    expect(filtersFromParams(next).party).toBe("Wohnbau Musterstadt eG");
  });

  it("offers only values that occur, with counts and human labels", () => {
    const o = filterOptions(entries);
    expect(o.types).toEqual([
      { value: "deadline", label: "Deadlines", count: 2 },
      { value: "payment", label: "Payments", count: 2 },
    ]);
    expect(o.areas.map((a) => a.label)).toEqual(["Home", "Residence", "Tax"]);
    expect(o.parties.map((p) => `${p.label} (${p.count})`)).toEqual(["Ausländerbehörde (1)", "Wohnbau Musterstadt eG (2)"]);
  });
});

describe("copy", () => {
  it("never shows raw status values", () => {
    const statuses = ["open", "done", "dismissed", "snoozed", "missed", "overdue", "needs_review", "processed", "processing", "failed", "active", "cancelled", "ended", "sent", "draft", "final"];
    for (const type of TIMELINE_TYPES) {
      for (const status of statuses) {
        const s = entryStatus({ type, status, date: "2026-10-01", past: false }, TODAY);
        if (s) assertNoRawEnums(s.label, { exactWord: true });
      }
    }
    expect(entryStatus({ type: "document", status: "needs_review", date: TODAY, past: false }, TODAY)?.label).toBe("Please check");
    expect(entryStatus({ type: "payment", status: "open", date: "2026-09-01", past: true }, TODAY)?.label).toBe("Overdue");
    expect(entryStatus({ type: "payment", status: "overdue", date: "2026-09-01", past: true }, TODAY)?.label).toBe("Overdue");
    expect(entryStatus({ type: "payment", status: "open", date: "2026-10-01", past: false }, TODAY)).toBeNull();
    expect(entryStatus({ type: "contract", status: "active", date: "2026-10-01", past: false }, TODAY)).toBeNull();
  });

  it("maps send channels and drops repeated party names in the second line", () => {
    expect(entryMeta({ type: "draft", party_name: "FunkNetz Mobil GmbH", subtitle: "registered_letter", time: null })).toBe(
      "FunkNetz Mobil GmbH · Einschreiben (registered letter)",
    );
    expect(entryMeta({ type: "document", party_name: "Stadtwerke", subtitle: "Letter from Stadtwerke", time: null })).toBe("Stadtwerke");
    expect(entryMeta({ type: "deadline", party_name: null, subtitle: "Send by Thu 8 Oct", time: null })).toBe("Send by Thu 8 Oct");
  });

  it("finds the entry a lane marker points to", () => {
    const list = [entry({ date: "2026-10-05", title: "Rent for October" }), entry({ date: "2026-10-09", title: "Utility back payment" })];
    expect(entryForDate(list, "2026-10-09", "Utility back payment 184,30 €")?.title).toBe("Utility back payment");
    expect(entryForDate(list, "2026-10-06")?.title).toBe("Utility back payment");
    expect(entryForDate(list, "2026-12-01")).toBeNull();
  });

  it("describes calendar reminders from the profile", () => {
    expect(reminderSentence([14, 7, 3, 1])).toBe("Reminders: 14, 7, 3 and 1 days before each deadline (change them in Settings).");
    expect(reminderSentence([1])).toBe("Reminders: 1 day before each deadline (change them in Settings).");
    expect(reminderSentence(undefined)).toMatch(/follow your settings/);
  });
});
