import { describe, expect, it } from "vitest";
import type { Recurrence } from "@/api/types";
import { makeItem } from "@/features/document/fixtures";
import REPEAT_LABELS from "./repeatLabels.json";
import { nextNote, repeatChoiceOf, repeatLabel, repeatOptions, repeatRule, type RepeatChoice } from "./repeat";

const rule = (r: Partial<Recurrence>): Recurrence => ({ interval: 1, unit: "months", working_day: null, day_of_month: null, ...r });

describe("repeatLabel", () => {
  it("says what the server's describe() says, for every pair the server's test reads too", () => {
    expect(REPEAT_LABELS.length).toBeGreaterThan(10);
    for (const [r, label] of REPEAT_LABELS as [Partial<Recurrence>, string][]) expect(repeatLabel(rule(r)), JSON.stringify(r)).toBe(label);
  });

  it("starts with a capital where it starts a line, and says nothing for a date that doesn't repeat", () => {
    expect(repeatLabel(rule({ working_day: 3 }), { capital: true })).toBe("Every month on the 3rd working day");
    expect(repeatLabel(null)).toBeNull();
    expect(repeatLabel(undefined)).toBeNull();
  });
});

describe("repeatOptions", () => {
  const labels = (date: string, current?: Recurrence | null) => repeatOptions(date, current).map((o) => o.label);

  it("names the day chosen, and no day before one is chosen; weekly is not offered", () => {
    expect(labels("2026-10-14")).toEqual([
      "Doesn't repeat",
      "Every month on the 14th",
      "Every month on a working day",
      "Every 3 months on the 14th",
      "Every 6 months on the 14th",
      "Every year on 14 October",
    ]);
    expect(labels("")).toEqual(["Doesn't repeat", "Every month", "Every month on a working day", "Every 3 months", "Every 6 months", "Every year"]);
    expect(repeatOptions("2026-10-14").map((o) => o.value)).toEqual(["never", "month", "working_day", "quarter", "half_year", "year"]);
  });

  it("says a 29th to 31st falls on a shorter month's last day", () => {
    expect(labels("2026-10-31")[1]).toBe("Every month on the 31st (or the month's last day)");
    expect(labels("2026-10-29")[3]).toBe("Every 3 months on the 29th (or the month's last day)");
    expect(labels("2026-10-28")[1]).toBe("Every month on the 28th");
    expect(labels("2028-02-29")[5]).toBe("Every year on 29 February (or the month's last day)");
  });

  it("keeps a rule the dialog can't make as it is, and says so", () => {
    const fortnightly = rule({ interval: 2, unit: "weeks" });
    expect(repeatOptions("2026-10-14", fortnightly).at(-1)).toEqual({ value: "current", label: "Every 2 weeks (as now)" });
    expect(labels("2026-10-14", rule({}))).toHaveLength(6);
  });
});

describe("repeatRule and repeatChoiceOf", () => {
  it("make the rule the server reads, and read it back", () => {
    expect(repeatRule("never", 3)).toBeNull();
    expect(repeatRule("month", 3)).toEqual(rule({}));
    expect(repeatRule("working_day", -1)).toEqual(rule({ working_day: -1 }));
    expect(repeatRule("quarter", 3)).toEqual(rule({ interval: 3 }));
    expect(repeatRule("half_year", 3)).toEqual(rule({ interval: 6 }));
    expect(repeatRule("year", 3)).toEqual(rule({ unit: "years" }));
    for (const choice of ["never", "month", "working_day", "quarter", "half_year", "year"] as RepeatChoice[]) {
      expect(repeatChoiceOf(repeatRule(choice, 5), "2026-10-14").choice).toBe(choice);
    }
    expect(repeatChoiceOf(rule({ working_day: 5 }), "2026-10-14")).toEqual({ choice: "working_day", workingDay: 5 });
  });

  it("reads every 12 months as every year (the server's same_rule), and any other rule as the current one", () => {
    expect(repeatChoiceOf(rule({ interval: 12 }), "2026-10-14").choice).toBe("year");
    expect(repeatChoiceOf(rule({ interval: 2, unit: "weeks" }), "2026-10-14").choice).toBe("current");
    expect(repeatChoiceOf(rule({ interval: 2 }), "2026-10-14").choice).toBe("current");
    expect(repeatChoiceOf(rule({ interval: 3, working_day: 1 }), "2026-10-14").choice).toBe("current");
    // a day of the month is the plain rule when it is the schedule's own day, and else one the dialog can't make
    expect(repeatChoiceOf(rule({ day_of_month: 14 }), "2026-10-14").choice).toBe("month");
    expect(repeatChoiceOf(rule({ day_of_month: 1 }), "2026-10-14").choice).toBe("current");
    expect(repeatChoiceOf(null, "2026-10-14")).toEqual({ choice: "never", workingDay: 3 });
  });
});

describe("nextNote", () => {
  const before = makeItem({ id: "itm_r", status: "open", due_date: "2026-10-05", recurrence: rule({ working_day: 3 }) });

  it("names the next date a repeating to-do moved on to", () => {
    expect(nextNote({ ...before, due_date: "2026-11-04" }, before)).toBe("Next: Wed 4 Nov");
    expect(nextNote({ ...before, due_date: "2027-01-05" }, before, "2026-09-28")).toBe("Next: Tue 5 Jan 2027");
  });

  it("says nothing when it closed, doesn't repeat or stayed where it was", () => {
    expect(nextNote({ ...before, status: "done", due_date: "2026-11-04" }, before)).toBeNull();
    expect(nextNote({ ...before, recurrence: null, due_date: "2026-11-04" }, before)).toBeNull();
    expect(nextNote(before, before)).toBeNull();
    expect(nextNote({ ...before, due_date: null }, before)).toBeNull();
  });
});
