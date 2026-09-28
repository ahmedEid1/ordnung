import { describe, expect, it } from "vitest";
import inlineDateForms from "./inlineDateForms.json";
import {
  daysUntil,
  formatCompact,
  formatDate,
  formatFactValue,
  formatInlineDates,
  formatInlineText,
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
  plainText,
  protectRefs,
  toISODate,
  tryParseDate,
  urgencyLevel,
  urgencyOf,
  urgencyTone,
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
    // a page's date line (This week, like Today's greeting) leaves the year out when asked …
    expect(formatDate("2026-09-28", { style: "long", withYear: "never" })).toBe("Monday, 28 September");
    // … and only then: "auto" (with or without today) and "always" keep it (screen-reader dates)
    expect(formatDate("2026-09-28", { style: "long", today: TODAY })).toBe("Monday, 28 September 2026");
    expect(formatDate("2026-09-28", { style: "long", withYear: "auto" })).toBe("Monday, 28 September 2026");
    expect(formatDate("2026-09-28", { style: "long", withYear: "always" })).toBe("Monday, 28 September 2026");
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

  it("buckets urgency on one scale", () => {
    expect(urgencyOf("2026-09-20", TODAY)).toBe("overdue");
    expect(urgencyOf("2026-09-20", TODAY, "event")).toBe("past");
    expect(urgencyOf(TODAY, TODAY)).toBe("today");
    expect(urgencyOf("2026-09-29", TODAY)).toBe("soon");
    expect(urgencyOf("2026-09-30", TODAY)).toBe("week");
    expect(urgencyOf("2026-10-05", TODAY)).toBe("week");
    expect(urgencyOf("2026-10-06", TODAY)).toBe("month");
    expect(urgencyOf("2026-10-28", TODAY)).toBe("month");
    expect(urgencyOf("2026-10-29", TODAY)).toBe("later");
  });

  it("colours urgency the same everywhere: red up to tomorrow, amber within a week, ink within 30 days", () => {
    const level = (date: string) => urgencyLevel(urgencyOf(date, TODAY));
    expect(["2026-09-27", TODAY, "2026-09-29"].map(level)).toEqual(["danger", "danger", "danger"]);
    expect(["2026-09-30", "2026-10-05"].map(level)).toEqual(["warn", "warn"]);
    // the FunkNetz send-by date, 10 days out: plain ink on every page
    expect(level("2026-10-08")).toBe("ink");
    expect(level("2026-11-30")).toBe("muted");
    expect(urgencyTone("today")).toMatchObject({ level: "danger", text: "text-danger-ink", soft: "bg-danger-soft", stripe: "bg-danger" });
    expect(urgencyTone("week")).toMatchObject({ level: "warn", text: "text-warn-ink", stripe: "bg-warn" });
    expect(urgencyTone("month").text).toBe("text-ink");
    expect(urgencyTone("later").text).toBe("text-muted");
  });

  it("caps direct debits and appointments at amber, and can show later dates in ink", () => {
    expect(urgencyTone("today", { cap: "warn" }).level).toBe("warn");
    expect(urgencyTone("overdue", { cap: "warn" }).text).toBe("text-warn-ink");
    expect(urgencyTone("week", { cap: "warn" }).level).toBe("warn");
    expect(urgencyTone("month", { cap: "warn" }).level).toBe("ink");
    expect(urgencyTone("later", { inkLater: true }).text).toBe("text-ink");
    expect(urgencyTone("past", { inkLater: true }).text).toBe("text-muted");
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
    expect(formatPercent(0.873)).toBe("87%");
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(null)).toBe("—");
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

  it("formats a German answer's dates the German way (review round 3 of phase 2)", () => {
    expect(formatInlineDates("Die Nachzahlung ist bis 2026-10-15 fällig", undefined, "de")).toBe(
      "Die Nachzahlung ist bis Do. 15.10.2026 fällig",
    );
    expect(formatInlineDates("Termin Mi. 2026-10-14 10:00", undefined, "de")).toBe("Termin Mi. 14.10.2026, 10:00");
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

describe("running text", () => {
  const NBSP = "\u00a0";
  const show = (s: string) => s.replace(/\u00a0/g, "⍽");

  it("keeps reference and ID numbers whole at their hyphens", () => {
    expect(protectRefs("Invoice TM-2026-0048213")).toBe("Invoice TM\u20112026\u20110048213");
    expect(protectRefs("Wohnung 05-2-03, FN-88213407, PHV 71-4471220")).toBe("Wohnung 05\u20112\u201103, FN\u201188213407, PHV 71\u20114471220");
    // words with hyphens still break normally
    expect(protectRefs("Nordrhein-Westfalen, E-Mail, SEPA-Lastschrift")).toBe("Nordrhein-Westfalen, E-Mail, SEPA-Lastschrift");
    expect(plainText(protectRefs("TM-2026-0048213 ab 14 Oct"))).toBe("TM-2026-0048213 ab 14 Oct");
    expect(plainText(`Wed${NBSP}14${NBSP}Oct`)).toBe("Wed 14 Oct");
  });

  it("writes money the app's one way", () => {
    const money = (s: string) => formatInlineText(s).replace(/\u00a0|\u202f/g, " ");
    expect(money("Pay 94.99 EUR now")).toBe("Pay €94.99 now");
    expect(money("a fee of 30.00 € and 94,99 €")).toBe("a fee of €30.00 and €94.99");
    expect(money("back pay of 1.560,00 € (EUR 1,560.00)")).toBe("back pay of €1,560.00 (€1,560.00)");
    expect(money("a 30 € Verwarnungsgeld")).toBe("a €30 Verwarnungsgeld");
    expect(money("already €156.55/month")).toBe("already €156.55/month");
    expect(money("in 2026 the rent rises")).toBe("in 2026 the rent rises");
  });

  it("glues dates, law references and units so they never break apart", () => {
    expect(show(formatInlineText("by Wed 14 Oct, 10:30"))).toBe("by Wed⍽14⍽Oct, 10:30");
    expect(show(formatInlineText("until Wednesday, 14 October 2026"))).toBe("until Wednesday,⍽14⍽October⍽2026");
    expect(show(formatInlineText("(§ 56 Abs. 3 TKG) and Art. 6 DSGVO"))).toBe("(§⍽56 Abs.⍽3 TKG) and Art.⍽6 DSGVO");
    expect(show(formatInlineText("from 2026-10-08", { today: TODAY }))).toBe("from Thu⍽8⍽Oct");
    // a Separate word or a Mark is not a month
    expect(show(formatInlineText("Separate 3 Mark"))).toBe("Separate 3 Mark");
  });

  it("only glues (never rewrites) text quoted from a letter", () => {
    const quote = "Bitte zahlen Sie 184,30 € bis zum 14. Oktober 2026 um 10:30 Uhr (§ 286 BGB).";
    expect(show(formatInlineText(quote, { rewrite: false }))).toBe(
      "Bitte zahlen Sie 184,30⍽€ bis zum 14.⍽Oktober⍽2026 um 10:30⍽Uhr (§⍽286 BGB).",
    );
  });
});
