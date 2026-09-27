import { describe, expect, it } from "vitest";
import type { Lane, LaneBar, TimelineEntry, TimelineMarker } from "@/api/types";
import { TIMELINE_TYPES } from "@/api/types";
import { assertNoRawEnums } from "@/lib/copy";
import {
  NO_FILTERS,
  activeFilterCount,
  applyFilters,
  emptyFilterHint,
  emptyLanesCopy,
  entryDetail,
  entryForDate,
  entryMeta,
  entryRole,
  entryStatus,
  filterLanes,
  filterOptions,
  filterSummary,
  filtersFromParams,
  filtersToParams,
  foldPast,
  groupByMonth,
  openDateCount,
} from "./model";
import { CALENDAR_GUIDES, reminderDays, reminderSentence } from "./calendar";

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

  it("counts each menu's options against the other filters, so no option leads to an empty list", () => {
    // with Wohnbau chosen there are no deadlines: "Deadlines (0)", greyed out in the menu
    const o = filterOptions(entries, { ...NO_FILTERS, party: "Wohnbau Musterstadt eG" }, TODAY);
    expect(o.types.map((t) => [t.value, t.count])).toEqual([
      ["deadline", 0],
      ["payment", 2],
    ]);
    // the chosen party's own menu still counts over all people (its own filter doesn't apply)
    expect(o.parties.map((p) => p.count)).toEqual([1, 2]);
    // past dates hidden: September's payment no longer counts
    expect(filterOptions(entries, { ...NO_FILTERS, showPast: false }, TODAY).types.find((t) => t.value === "payment")?.count).toBe(1);
    // a chosen value that no entry has (an old link) is still offered, so the menu shows it
    expect(filterOptions(entries, { ...NO_FILTERS, party: "Gone GmbH" }, TODAY).parties.map((p) => p.label)).toContain("Gone GmbH");
  });

  it("sums up the chosen filters and what to try when nothing matches", () => {
    expect(filterSummary(NO_FILTERS)).toBeNull();
    expect(filterSummary({ ...NO_FILTERS, type: "payment", area: "mobility" })).toBe("Payments · Getting around");
    expect(emptyFilterHint({ ...NO_FILTERS, type: "task", party: "Musterbank eG" })).toBe("Try another kind or person.");
    expect(emptyFilterHint({ ...NO_FILTERS, type: "task", area: "home", party: "X" })).toBe("Try another kind, area or person.");
    expect(emptyFilterHint({ ...NO_FILTERS, party: "X" })).toBe("Try another person or organisation.");
    // "or show past dates" only while past dates are hidden
    expect(emptyFilterHint({ ...NO_FILTERS, area: "home" })).toBe("Try another area.");
    expect(emptyFilterHint({ ...NO_FILTERS, area: "home", showPast: false })).toBe("Try another area, or show past dates.");
    expect(emptyFilterHint({ ...NO_FILTERS, showPast: false })).toMatch(/show past dates/);
  });

  it("never lets the lanes say 'nothing' while the list below has dates", () => {
    expect(emptyLanesCopy({ ...NO_FILTERS, area: "mobility" }, 3)).toEqual({ title: "These dates aren't on the lanes", description: "All 3 are in the list below." });
    expect(emptyLanesCopy({ ...NO_FILTERS, area: "mobility" }, 1).description).toBe("It's in the list below.");
    // the lanes show the whole year: no "show past dates" there
    expect(emptyLanesCopy({ ...NO_FILTERS, area: "tax", showPast: false }, 0)).toEqual({ title: "Nothing on the lanes for these filters", description: "Try another area." });
    // letters are records, never drawn
    expect(emptyLanesCopy({ ...NO_FILTERS, type: "document" }, 12).title).toBe("Letters aren't drawn on the lanes");
    expect(emptyLanesCopy({ ...NO_FILTERS, type: "document", showPast: false }, 0).description).toMatch(/Show past/);
    expect(emptyLanesCopy(NO_FILTERS, 5).title).toBe("Nothing on your lanes yet");
  });
});

describe("foldPast (phones start the list at Today)", () => {
  it("folds earlier months and this month's earlier days, and says how many", () => {
    const groups = groupByMonth(
      [entry({ date: "2026-08-03" }), entry({ date: "2026-09-02" }), entry({ date: "2026-09-10" }), entry({ date: "2026-09-30" }), entry({ date: "2026-10-01" })],
      TODAY,
    );
    const { groups: shown, hidden } = foldPast(groups);
    expect(hidden).toBe(3);
    expect(shown.map((g) => [g.key, g.entries.map((e) => e.date), g.todayIndex, g.folded])).toEqual([
      ["2026-09", ["2026-09-30"], 0, 2],
      ["2026-10", ["2026-10-01"], null, undefined],
    ]);
  });

  it("keeps everything when nothing lies before today", () => {
    const groups = groupByMonth([entry({ date: "2026-09-30" })], TODAY);
    expect(foldPast(groups)).toEqual({ groups, hidden: 0 });
  });
});

describe("filterLanes (the lanes under the list's filters)", () => {
  const marker = (date: string, label: string, kind: TimelineMarker["kind"]): TimelineMarker => ({ date, label, kind });
  const bar = (id: string, ref: LaneBar["ref"], kind: LaneBar["kind"] = "contract", markers: TimelineMarker[] = []): LaneBar => ({
    id,
    label: id,
    start: "2026-01-01",
    end: "2027-06-30",
    kind,
    status: "ok",
    markers,
    ref,
  });
  const lanes: Lane[] = [
    { id: "residence", label: "Residence", area: "residence", bars: [bar("permit", { type: "item", id: "itm_permit" }, "validity")], markers: [] },
    {
      id: "contracts",
      label: "Contracts",
      area: "other",
      bars: [
        bar("phone", { type: "contract", id: "ctr_phone" }, "contract", [marker("2026-11-15", "Continues · cancel any time", "renewal")]),
        bar("ticket", { type: "contract", id: "ctr_ticket" }),
        bar("bank", { type: "contract", id: "ctr_bank" }),
      ],
      markers: [],
    },
    {
      id: "money",
      label: "Money",
      area: "money",
      bars: [],
      markers: [marker("2026-10-01", "Monatliche Abbuchung Deutschlandticket", "payment"), marker("2026-10-15", "Monthly health insurance contribution", "payment")],
    },
  ];
  const entries = [
    entry({ date: "2026-11-30", type: "expiry", area: "residence", ref: { type: "item", id: "itm_permit" }, party_name: "Ausländerbehörde" }),
    entry({ date: "2026-11-14", type: "contract", area: "home", ref: { type: "contract", id: "ctr_phone" }, party_name: "FunkNetz" }),
    entry({ date: "2026-10-01", type: "payment", area: "mobility", title: "Monatliche Abbuchung Deutschlandticket", party_name: "Verkehrsbetriebe" }),
    entry({ date: "2026-10-15", type: "payment", area: "health", title: "Monthly health insurance contribution", party_name: "Muster BKK" }),
    entry({ date: "2026-10-20", type: "payment", area: "mobility", title: "Parking fine", party_name: "Ordnungsamt" }),
  ];
  // open-ended contracts have no dated entry in the range: their area comes from the contract
  const contracts = new Map([
    ["ctr_ticket", { area: "mobility" as const, party: "Verkehrsbetriebe" }],
    ["ctr_bank", { area: "money" as const, party: "Musterbank eG" }],
  ]);
  const ids = (ls: Lane[]) => ls.map((l) => [l.id, [...l.bars.map((b) => b.id), ...l.markers.map((m) => m.label)]]);

  it("keeps every lane when no kind, area or person is chosen (Show past doesn't touch the year)", () => {
    expect(filterLanes(lanes, { ...NO_FILTERS, showPast: false }, { entries })).toBe(lanes);
  });

  it("judges each bar and marker by its own area, not its lane's", () => {
    expect(ids(filterLanes(lanes, { ...NO_FILTERS, area: "mobility" }, { entries, contracts }))).toEqual([
      ["contracts", ["ticket"]],
      ["money", ["Monatliche Abbuchung Deutschlandticket"]],
    ]);
    // "other" is the Contracts lane's placeholder area, not a filter match for its contracts
    expect(filterLanes(lanes, { ...NO_FILTERS, area: "other" }, { entries, contracts })).toEqual([]);
    expect(ids(filterLanes(lanes, { ...NO_FILTERS, area: "residence" }, { entries, contracts }))).toEqual([["residence", ["permit"]]]);
  });

  it("filters by kind and person too", () => {
    expect(ids(filterLanes(lanes, { ...NO_FILTERS, type: "payment" }, { entries, contracts }))).toEqual([
      ["money", ["Monatliche Abbuchung Deutschlandticket", "Monthly health insurance contribution"]],
    ]);
    expect(ids(filterLanes(lanes, { ...NO_FILTERS, type: "expiry" }, { entries, contracts }))).toEqual([["residence", ["permit"]]]);
    expect(ids(filterLanes(lanes, { ...NO_FILTERS, party: "Musterbank eG" }, { entries, contracts }))).toEqual([["contracts", ["bank"]]]);
    expect(filterLanes(lanes, { ...NO_FILTERS, type: "document" }, { entries, contracts })).toEqual([]);
  });

  it("uses the area and to-do the server sends with a mark, where it does", () => {
    const withOrigin = [{ ...lanes[2]!, markers: [{ ...marker("2026-12-01", "Premium", "payment"), area: "insurance", ref: null }] }] as unknown as Lane[];
    expect(filterLanes(withOrigin, { ...NO_FILTERS, area: "insurance" }, { entries })).toHaveLength(1);
    expect(filterLanes(withOrigin, { ...NO_FILTERS, area: "money" }, { entries })).toHaveLength(0);
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

  it("drops the sender a letter's summary starts with ('TechMarkt Online GmbH · TechMarkt Online GmbH sent …')", () => {
    const party = "TechMarkt Online GmbH";
    expect(entryDetail({ party_name: party, subtitle: "TechMarkt Online GmbH sent a 1st payment reminder for invoice TM-2026" })).toBe("Sent a 1st payment reminder for invoice TM-2026");
    expect(entryDetail({ party_name: "Muster BKK", subtitle: "Muster BKK (statutory health insurer) informs Sam that …" })).toBe("Informs Sam that …");
    expect(entryDetail({ party_name: "Global Talent Foundation", subtitle: "The Global Talent Foundation, represented by Dr. Exa, awards …" })).toBe("Represented by Dr. Exa, awards …");
    // only a whole name: "Muster" is not "Musterbank eG"
    expect(entryDetail({ party_name: "Muster", subtitle: "Musterbank eG raises its fees" })).toBe("Musterbank eG raises its fees");
    expect(entryMeta({ type: "document", party_name: party, subtitle: "TechMarkt Online GmbH sent a reminder", time: null })).toBe("TechMarkt Online GmbH · Sent a reminder");
  });

  it("says what each date is", () => {
    expect(entryRole({ type: "payment", status: "open" })).toBe("Payment due");
    expect(entryRole({ type: "payment", status: "done" })).toBe("Payment");
    expect(entryRole({ type: "document", status: "processed" })).toBe("Letter");
    expect(entryRole({ type: "draft", status: "sent" })).toBe("You sent");
    expect(entryRole({ type: "expiry", status: "open" })).toBe("Expires");
    for (const type of TIMELINE_TYPES) assertNoRawEnums(entryRole({ type, status: "open" }), { exactWord: true });
  });

  it("finds the entry a lane marker points to", () => {
    const list = [entry({ date: "2026-10-05", title: "Rent for October" }), entry({ date: "2026-10-09", title: "Utility back payment" })];
    expect(entryForDate(list, "2026-10-09", "Utility back payment 184,30 €")?.title).toBe("Utility back payment");
    expect(entryForDate(list, "2026-10-06")?.title).toBe("Utility back payment");
    expect(entryForDate(list, "2026-12-01")).toBeNull();
  });

  it("never lets one shared word pick another bill of the same day", () => {
    const electricity = entry({ date: "2026-10-15", type: "payment", title: "Monthly advance payment (Abschlag) for electricity", amount: 48 });
    const health = entry({ date: "2026-10-15", type: "payment", title: "Monthly health & nursing care insurance contribution", amount: 156.55 });
    const list = [electricity, health];
    // the marker's label is the to-do's title: the exact match wins, whatever sorts first
    expect(entryForDate(list, "2026-10-15", "Monthly health & nursing care insurance contribution")).toBe(health);
    // a shortened label: the title sharing the largest part of its words
    expect(entryForDate(list, "2026-10-15", "Health insurance contribution")).toBe(health);
    expect(entryForDate(list, "2026-10-15", "Electricity advance payment")).toBe(electricity);
    // the to-do itself, when the marker says which one
    expect(entryForDate(list, "2026-10-15", "Monthly payment", health.ref)).toBe(health);
  });

  it("counts the open dates the calendar file holds", () => {
    expect(
      openDateCount([
        entry({ date: "2026-10-01", type: "payment" }),
        entry({ date: "2026-10-02", type: "payment", status: "done" }),
        entry({ date: "2026-09-01", type: "document", status: "processed" }),
        entry({ date: "2026-09-02", type: "draft", status: "sent" }),
        entry({ date: "2026-10-08", type: "contract", status: "active" }),
      ]),
    ).toBe(2);
    expect(openDateCount([])).toBe(0);
  });

  it("describes calendar reminders from the profile", () => {
    // Settings → Calendar says it in the words of the Reminders chips
    expect(reminderSentence([14, 7, 3, 1])).toBe("2 weeks, 1 week, 3 days and 1 day before each deadline");
    expect(reminderSentence([1])).toBe("1 day before each deadline");
    expect(reminderSentence([0, 21, 21])).toBe("3 weeks before each deadline and on the day");
    expect(reminderSentence([0])).toBe("on the day of each deadline");
    expect(reminderSentence(undefined)).toBeNull();
    expect(reminderDays([3, 14, 3])).toBe("14 and 3 days before each deadline");
    expect(reminderDays([])).toBeNull();
  });

  it("numbers each way of importing on its own (Mac and iPhone are alternatives, not steps 1–3)", () => {
    const apple = CALENDAR_GUIDES.find((g) => g.app === "apple")!;
    expect(apple.sections.map((s) => [s.title, s.steps.length])).toEqual([
      ["On a Mac", 2],
      ["On an iPhone or iPad", 1],
    ]);
    const outlook = CALENDAR_GUIDES.find((g) => g.app === "outlook")!;
    expect(outlook.sections.map((s) => s.title)).toEqual(["Outlook on the web", "Outlook for Windows"]);
    // every link placeholder has its link
    for (const g of CALENDAR_GUIDES) for (const s of g.sections) for (const step of s.steps) expect(step.text.includes("{link}")).toBe(Boolean(step.link));
  });
});
