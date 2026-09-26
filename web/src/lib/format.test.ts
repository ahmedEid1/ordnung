import { describe, expect, it } from "vitest";
import inlineDateForms from "./inlineDateForms.json";
import {
  daysUntil,
  formatCompact,
  formatDate,
  formatFactValue,
  formatInlineDates,
  formatFileSize,
  formatIban,
  formatIntervalSuffix,
  formatMoney,
  formatPercent,
  formatRelativeDays,
  formatTime,
  formatUsd,
  looksGerman,
  monthlyAmount,
  parseLooseNumber,
  toISODate,
  tryParseDate,
  urgencyOf,
} from "./format";

const TODAY = "2026-09-28"; // Monday — the demo's simulated today

describe("dates", () => {
  it("parses ISO dates as local calendar days", () => {
    const d = tryParseDate("2026-10-16")!;
    expect(d.getFullYear()).toBe(2026);
    expect(d.getMonth()).toBe(9);
    expect(d.getDate()).toBe(16);
    expect(toISODate(d)).toBe("2026-10-16");
    expect(tryParseDate("not a date")).toBeNull();
    expect(tryParseDate(null)).toBeNull();
  });

  it("formats in the app's styles", () => {
    expect(formatDate("2026-10-16")).toBe("Fri 16 Oct");
    expect(formatDate("2026-10-16", { today: TODAY })).toBe("Fri 16 Oct");
    expect(formatDate("2027-02-10", { today: TODAY })).toBe("Wed 10 Feb 2027");
    expect(formatDate("2026-10-16", { style: "medium" })).toBe("16 Oct 2026");
    expect(formatDate("2026-10-16", { style: "long" })).toBe("Friday, 16 October 2026");
    expect(formatDate("2026-10-16", { style: "numeric" })).toBe("16.10.2026");
    expect(formatDate("2026-10-16", { style: "month" })).toBe("October 2026");
    expect(formatDate("2026-10-16", { style: "day", withYear: "always" })).toBe("16 Oct 2026");
    expect(formatDate(null)).toBe("—");
    expect(formatTime("10:30:00")).toBe("10:30");
    expect(formatTime("9:05")).toBe("09:05");
  });

  it("counts calendar days against the given today, not the browser clock", () => {
    expect(daysUntil("2026-10-08", TODAY)).toBe(10);
    expect(daysUntil("2026-09-26", TODAY)).toBe(-2);
    expect(daysUntil(TODAY, TODAY)).toBe(0);
  });

  it("phrases relative days", () => {
    expect(formatRelativeDays(TODAY, TODAY)).toBe("today");
    expect(formatRelativeDays("2026-09-29", TODAY)).toBe("tomorrow");
    expect(formatRelativeDays("2026-10-03", TODAY)).toBe("in 5 days");
    expect(formatRelativeDays("2026-10-14", TODAY)).toBe("in 16 days");
    expect(formatRelativeDays("2026-10-26", TODAY)).toBe("in 4 weeks");
    expect(formatRelativeDays("2027-01-28", TODAY)).toBe("in 4 months");
    expect(formatRelativeDays("2026-09-26", TODAY)).toBe("2 days overdue");
    expect(formatRelativeDays("2026-09-27", TODAY)).toBe("1 day overdue");
    expect(formatRelativeDays("2026-09-27", TODAY, "event")).toBe("yesterday");
    expect(formatRelativeDays("2026-09-18", TODAY, "event")).toBe("10 days ago");
  });

  it("buckets urgency", () => {
    expect(urgencyOf("2026-09-20", TODAY)).toBe("overdue");
    expect(urgencyOf("2026-09-20", TODAY, "event")).toBe("past");
    expect(urgencyOf(TODAY, TODAY)).toBe("today");
    expect(urgencyOf("2026-09-30", TODAY)).toBe("soon");
    expect(urgencyOf("2026-10-05", TODAY)).toBe("week");
    expect(urgencyOf("2026-10-20", TODAY)).toBe("month");
    expect(urgencyOf("2026-12-01", TODAY)).toBe("later");
  });
});

describe("money & numbers", () => {
  const nb = (s: string) => s.replace(/\u00a0|\u202f/g, " ");

  it("formats euros the German way", () => {
    expect(nb(formatMoney(184.3))).toBe("€184.30");
    expect(nb(formatMoney(1234.5))).toBe("€1,234.50");
    expect(nb(formatMoney(84, { signed: true }))).toBe("+€84.00");
    expect(nb(formatMoney(1440, { decimals: "auto" }))).toBe("€1,440");
    expect(nb(formatMoney(4.5, { decimals: "auto" }))).toBe("€4.50");
    expect(formatMoney(null)).toBe("—");
  });

  it("normalises intervals", () => {
    expect(formatIntervalSuffix("monthly")).toBe("/month");
    expect(formatIntervalSuffix("once")).toBe("");
    expect(monthlyAmount(59.9, "yearly")).toBe(4.99);
    expect(monthlyAmount(55.08, "quarterly")).toBe(18.36);
    expect(monthlyAmount(10, "once")).toBeNull();
  });

  it("formats sizes, tokens, cost, percentages and IBANs", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(1536)).toBe("1.5 KB");
    expect(formatFileSize(2_400_000)).toBe("2.3 MB");
    expect(formatCompact(438_900)).toBe("439k");
    expect(formatCompact(1_200_000)).toBe("1.2M");
    expect(formatCompact(9_120)).toBe("9.1k");
    expect(formatUsd(2.914)).toBe("$2.91");
    expect(formatUsd(0.004)).toBe("<$0.01");
    expect(formatPercent(0.873)).toBe("87 %");
    expect(formatIban("DE44500105175407324931")).toBe("DE44 5001 0517 5407 3249 31");
  });
});

describe("values copied from letters", () => {
  it("reads numbers written the German or the English way", () => {
    expect(parseLooseNumber("1.234,50")).toBe(1234.5);
    expect(parseLooseNumber("1,234.50")).toBe(1234.5);
    expect(parseLooseNumber("1234.00")).toBe(1234);
    expect(parseLooseNumber("23.298")).toBe(23298);
    expect(parseLooseNumber("324,00")).toBe(324);
    expect(parseLooseNumber("abc")).toBeNull();
  });

  it("formats money and dates of key facts in the app's format", () => {
    expect(formatFactValue("1234.00 EUR")).toBe("€1,234.00");
    expect(formatFactValue("23298 EUR")).toBe("€23,298.00");
    expect(formatFactValue("324,00 €")).toBe("€324.00");
    expect(formatFactValue("2026-10-08 09:15")).toBe("Thu 8 Oct 2026, 09:15");
    expect(formatFactValue("15.09.2026")).toBe("Tue 15 Sep 2026");
    expect(formatFactValue("MusterStrom Flex")).toBe("MusterStrom Flex");
  });

  it("formats ISO dates inside sentences", () => {
    expect(formatInlineDates("from 2026-09-28 to 2026-10-26", "2026-09-28")).toBe("from Mon 28 Sep to Mon 26 Oct");
  });

  it("keeps one weekday when the text writes one before an ISO date", () => {
    // review finding: a recorded answer's "due Wed 2026-09-30" showed as "due Wed Wed 30 Sep 2026"
    expect(formatInlineDates("due Wed 2026-09-30", "2026-09-28")).toBe("due Wed 30 Sep");
    expect(formatInlineDates("fällig Mi. 2026-09-30 und Thursday, 2026-10-01", "2026-09-28")).toBe(
      "fällig Wed 30 Sep und Thu 1 Oct",
    );
    expect(formatInlineDates("Monday 2026-09-28 10:30", "2026-09-28")).toBe("Mon 28 Sep, 10:30");
    expect(formatInlineDates("Womo 2026-09-30", "2026-09-28")).toBe("Womo Wed 30 Sep");
    expect(formatInlineDates("So 2026-09-30 it is", "2026-09-28")).toBe("So Wed 30 Sep it is");
  });

  it("formats exactly the inline date forms the Ask check reads (review round 4)", () => {
    // an ISO date-time the check did not read reached the person as "Fri 31 Dec 2027, 23:59" — in
    // Ordnung's own style. The check's test (tests/test_ask_support.py) reads the same list.
    for (const form of inlineDateForms) {
      const shown = formatInlineDates(`Due ${form} now.`);
      expect(shown, form).toMatch(/^Due (Fri 31 Dec 2027|31 Dec 2027)(, 23:59)? now\.$/);
    }
    // what is not in the list stays as written, so the check never has to read a formatted date
    expect(formatInlineDates("Due 2027-12-31Z now.")).toBe("Due 2027-12-31Z now.");
  });

  it("tells German sentences from English ones", () => {
    expect(looksGerman("Geht der Betrag nicht fristgerecht ein, müssen wir die Forderung übergeben.")).toBe(true);
    expect(looksGerman("Ausreichende Kontodeckung für die monatliche SEPA-Lastschrift sicherstellen.")).toBe(true);
    expect(looksGerman("Transfer the total amount to the account by the deadline shown.")).toBe(false);
    expect(looksGerman("File an objection (Einspruch) with the Finanzamt if you disagree.")).toBe(false);
  });
});
