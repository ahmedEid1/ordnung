/**
 * Contracts page logic: fixed costs, "Decide by" selection, plain-words notice rules, sorting and
 * the contracts-only life lanes. Pure functions (unit-tested in `model.test.ts`).
 */
import { addMonths, format } from "date-fns";
import type { Contract, ContractStatus, Lane, LaneBar, LaneBarStatus, TimelineMarker } from "@/api/types";
import { CONTRACT_REGIME_COPY, NOTICE_BASIS_COPY, copyFor } from "@/lib/copy";
import { addToTotals, formatDate, monthlyAmount, type Totals } from "@/lib/format";
import { addDaysISO, dayNumber } from "@/features/lanes/scale";
import { offersEndingLetter } from "./links";

// ------------------------------------------------------------------------------------------------
// Money
// ------------------------------------------------------------------------------------------------

/** Monthly cost of a contract (yearly / 12, quarterly / 3); null when unknown or one-off. */
export function contractMonthlyCost(c: Pick<Contract, "cost_amount" | "cost_interval">): number | null {
  return monthlyAmount(c.cost_amount, c.cost_interval);
}

export interface FixedCosts {
  /** in euros (contracts in another currency are in `monthlyTotals` only) */
  monthly: number;
  yearly: number;
  /** per currency — a $20 subscription is not €20 of the fixed costs */
  monthlyTotals: Totals;
  /** what a year of them costs, from each contract's own amount (€59.90 a year counts as €59.90) */
  yearlyTotals: Totals;
  /** active contracts with a known recurring cost */
  counted: number;
  /** active contracts without a known cost (not in the total) */
  unknown: number;
  /** active jobs: they pay you, so they are never a fixed cost (even when the letter names the pay) */
  jobs: number;
}

const PER_YEAR = { monthly: 12, quarterly: 4, yearly: 1 } as const;

/** Sum of the monthly costs of active contracts per currency (rounded to cents) and what a year of them costs. */
export function fixedCosts(contracts: Contract[]): FixedCosts {
  let monthlyTotals: Totals = {};
  let yearlyTotals: Totals = {};
  let counted = 0;
  let unknown = 0;
  let jobs = 0;
  for (const c of contracts) {
    if (c.status !== "active") continue;
    if (c.category === "employment") {
      jobs++;
      continue;
    }
    const m = contractMonthlyCost(c);
    if (m === null || c.cost_amount === null || !c.cost_interval || c.cost_interval === "once") {
      unknown++;
      continue;
    }
    monthlyTotals = addToTotals(monthlyTotals, m, c.cost_currency);
    yearlyTotals = addToTotals(yearlyTotals, c.cost_amount * PER_YEAR[c.cost_interval], c.cost_currency);
    counted++;
  }
  return { monthly: monthlyTotals.EUR ?? 0, yearly: yearlyTotals.EUR ?? 0, monthlyTotals, yearlyTotals, counted, unknown, jobs };
}

// ------------------------------------------------------------------------------------------------
// Decisions
// ------------------------------------------------------------------------------------------------

/**
 * The notice ends the contract before its term does: a fixed-term job its contract lets you leave
 * earlier by notice (`notice_before_end`) — the rules then plan that notice, and the job otherwise
 * ends by itself on its date. Missing the notice's date locks nothing in.
 */
function endsBeforeItsTerm(c: Pick<Contract, "computed">): boolean {
  const k = c.computed;
  return Boolean(k?.earliest_exit && k.current_term_end && k.earliest_exit < k.current_term_end);
}

/**
 * A window that closes and locks you in: after it, the contract runs on for another term (a
 * minimum term ending, a yearly renewal).
 */
export function isLockInDecision(c: Pick<Contract, "computed">): boolean {
  const k = c.computed;
  return Boolean(k?.cancel_by && k.send_by && (k.next_renewal || k.current_term_end)) && !endsBeforeItsTerm(c);
}

/**
 * A contract you can cancel any month (rent, statutory health insurance after its first year, a
 * fixed-term job its contract lets you leave earlier): no term runs out on you, so its "cancel by"
 * date only says when it would end — miss it, and it ends a month later. Never urgent.
 */
export function isRollingContract(c: Pick<Contract, "computed" | "status">): boolean {
  const k = c.computed;
  return c.status === "active" && Boolean(k?.cancel_by) && !k?.next_renewal && (!k?.current_term_end || endsBeforeItsTerm(c));
}

/** Rules under which an uncancelled contract simply continues after its term, cancellable any month. */
export const CONTINUES_MONTHLY = new Set<string>(["bgb309_new", "tkg56", "stromgvv20", "sgbv175"]);

/**
 * A contract that ends by itself on its end date (a fixed-term job). Not one whose end date is
 * only the end of its minimum term: a consumer contract that then runs on month by month (it has
 * a next renewal, or a rule that keeps it going) is not ending.
 */
export function isFixedTerm(c: Pick<Contract, "computed" | "end_date">): boolean {
  const k = c.computed;
  if (!c.end_date || (k?.current_term_end && k.current_term_end !== c.end_date)) return false;
  return !k?.next_renewal && !CONTINUES_MONTHLY.has(k?.regime ?? "");
}

/**
 * Terms we couldn't work out (low confidence, and no date at all — usually the notice period is
 * missing from the letter): nothing about how it ends may be drawn as if it were known.
 */
export function termsUnclear(c: Pick<Contract, "computed" | "status">): boolean {
  const k = c.computed;
  return c.status === "active" && k?.confidence === "low" && !k.cancel_by && !k.earliest_exit && !k.current_term_end && !k.next_renewal;
}

/**
 * The notice period is the one the person entered on the card ("Save notice period" records it as a
 * quote confirmed by them, `grounding: "user"`): nothing is left to check against the letter.
 */
export function noticeFromYou(c: Pick<Contract, "evidence">): boolean {
  return c.evidence.some((e) => e.grounding === "user");
}

/**
 * How the rules engine starts its warning when the letter gave no notice period and it assumed the longest
 * the law allows (`_MISSING_NOTICE` in `src/ordnung/rules/contracts.py`).
 */
export const NOTICE_ASSUMED = "The contract's notice period wasn't found";

/**
 * The dates rest on a notice period the rules assumed — the letter gave none (walkthrough of phase 2: the
 * Deutschlandticket's card said "1 month's notice … Earliest end Mon 2 Nov" with no "Please check", while its
 * letter says "by the 10th of a month, to that month's end"). Not once the person entered the period.
 */
export function noticeAssumed(c: Pick<Contract, "computed" | "status" | "evidence">): boolean {
  return c.status === "active" && !noticeFromYou(c) && (c.computed?.warnings ?? []).some((w) => w.startsWith(NOTICE_ASSUMED));
}

/**
 * Rules that read the contract's own day of the month for notice when its basis is the end of a month
 * (`_notice_day` in `src/ordnung/rules/contracts.py`) — and a current account's, which follows its terms as
 * written once they say the end of a month.
 */
const NOTICE_DAY_REGIMES = new Set<string>(["bgb309_new", "bgb309_old", "tkg56", "as_written", "bgb675h"]);

/** The contract's own day of the month for notice counts for it (with the end of a month as the basis). */
export function noticeDayCounts(c: Pick<Contract, "computed">): boolean {
  return NOTICE_DAY_REGIMES.has(c.computed?.regime ?? "as_written");
}

/**
 * A fixed-term job, which its contract may let you leave earlier by ordinary notice (`notice_before_end`, read
 * for a job only: `_ends_by_itself` in `src/ordnung/rules/contracts.py`).
 */
export function earlyNoticeCounts(c: Pick<Contract, "category" | "end_date">): boolean {
  return c.category === "employment" && Boolean(c.end_date);
}

/**
 * The notice terms can be entered or changed on the card: terms we couldn't work out, terms the rules
 * follow as written (no statutory rule), a period the rules assumed, terms the person entered (a typo
 * stays correctable) — and the terms a notice period can't say, which a misreading can get wrong: the
 * contract's own day of the month the rules read, or whether a fixed-term job can be left earlier.
 */
export function noticeEditable(
  c: Pick<Contract, "computed" | "status" | "evidence" | "category" | "end_date" | "notice_day" | "notice_basis" | "notice_value" | "notice_unit">,
): boolean {
  const byDay = noticeDayCounts(c) && noticeDayPhrase(c) !== null;
  return c.status === "active" && (termsUnclear(c) || c.computed?.regime === "as_written" || noticeAssumed(c) || noticeFromYou(c) || byDay || earlyNoticeCounts(c));
}

/**
 * The person's cancellation of this contract, marked as sent (the API's `cancellation_sent`), while the
 * contract is still active: the decision is taken — no "Decide by", no "Draft cancellation"
 * (walkthrough of phase 2).
 */
export function cancellationSent(c: Pick<Contract, "status" | "cancellation_sent">): Contract["cancellation_sent"] {
  return c.status === "active" ? (c.cancellation_sent ?? null) : null;
}

/**
 * Why a contract's card asks "Please check" (the rules' confidence is low), in words for its tooltip
 * and a screen reader — or null when it doesn't: the person entered the notice period themselves.
 */
export function pleaseCheckHint(c: Pick<Contract, "computed" | "status" | "evidence">): string | null {
  if (noticeFromYou(c)) return null;
  if (c.computed?.confidence !== "low") {
    return noticeAssumed(c) ? "The letter gives no notice period, so Ordnung assumed the longest the law allows — check the contract and add it" : null;
  }
  if (termsUnclear(c)) return "Ordnung couldn't work out how this contract ends — check the letter for the notice period";
  if (c.computed.regime === "as_written") return "Ordnung follows the notice period as written — check it against the contract";
  return "Ordnung isn't sure of these dates — check them against the contract";
}

/**
 * Active contracts a letter can end whose send-by date is between today and `days` ahead, soonest
 * first — only real decisions ({@link isLockInDecision}); rolling contracts reopen every month.
 */
export function decideBy(contracts: Contract[], today: string, days = 60): Contract[] {
  const t = dayNumber(today);
  return contracts
    .filter((c) => {
      // a cancellation marked as sent: decided
      const s = offersEndingLetter(c) && isLockInDecision(c) && !cancellationSent(c) ? c.computed?.send_by : null;
      if (!s) return false;
      const d = dayNumber(s) - t;
      return d >= 0 && d <= days;
    })
    .sort((a, b) => a.computed!.send_by!.localeCompare(b.computed!.send_by!));
}

/** The next date to act on for a contract (send-by, else must-arrive-by), if still ahead. */
export function nextActionDate(c: Contract, today: string): string | null {
  if (isRollingContract(c)) return null; // cancellable any month: nothing to act on by a date
  if (cancellationSent(c)) return null; // sent: nothing left to act on by a date
  const d = c.computed?.send_by ?? c.computed?.cancel_by ?? null;
  return d && d >= today ? d : null;
}

/** Cards order: upcoming actions first (soonest), then by monthly cost (highest), then name. */
export function sortContracts(contracts: Contract[], today: string): Contract[] {
  return [...contracts].sort((a, b) => {
    const da = nextActionDate(a, today);
    const db = nextActionDate(b, today);
    if (da && db && da !== db) return da.localeCompare(db);
    if (da && !db) return -1;
    if (db && !da) return 1;
    const ma = contractMonthlyCost(a) ?? -1;
    const mb = contractMonthlyCost(b) ?? -1;
    return mb - ma || a.name.localeCompare(b.name);
  });
}

export type StatusFilter = ContractStatus | "all";

export function filterByStatus(contracts: Contract[], status: StatusFilter): Contract[] {
  return status === "all" ? contracts : contracts.filter((c) => c.status === status);
}

// ------------------------------------------------------------------------------------------------
// Rules in plain words
// ------------------------------------------------------------------------------------------------

/** "1 month's notice", "4 weeks' notice", null when the contract doesn't say. */
export function noticePhrase(c: Pick<Contract, "notice_value" | "notice_unit">): string | null {
  if (!c.notice_value || !c.notice_unit) return null;
  const unit = c.notice_unit.replace(/s$/, "");
  return c.notice_value === 1 ? `1 ${unit}'s notice` : `${c.notice_value} ${unit}s' notice`;
}

const ORDINAL_SUFFIX: Record<number, string> = { 1: "st", 2: "nd", 3: "rd" };

/** "1st", "2nd", "3rd", "10th", "11th", "21st" (as `ordinal` in `src/ordnung/rules/explain.py`). */
export function ordinal(day: number): string {
  const teen = day % 100 >= 11 && day % 100 <= 13;
  return `${day}${teen ? "th" : (ORDINAL_SUFFIX[day % 10] ?? "th")}`;
}

/**
 * The contract's own month-end rule — "by the 10th of the month, to the month's end" — when the rules
 * read it (`notice_day`; `_notice_day` in `src/ordnung/rules/contracts.py`): its notice basis is the
 * end of a month. A notice period it states too applies as well ("with 10 days' notice by the 10th …"):
 * `notice`, that period as the rules count it. Null otherwise.
 */
export function noticeDayPhrase(
  c: Pick<Contract, "notice_day" | "notice_basis" | "notice_value" | "notice_unit">,
  notice: string | null = noticePhrase(c),
): string | null {
  if (!c.notice_day || c.notice_basis !== "end_of_month") return null;
  return `${notice ? `with ${notice} ` : ""}by the ${ordinal(c.notice_day)} of the month, to the month's end`;
}

function noticeMonths(c: Pick<Contract, "notice_value" | "notice_unit">): number | null {
  if (!c.notice_value || !c.notice_unit) return null;
  return c.notice_unit === "months" ? c.notice_value : c.notice_unit === "weeks" ? c.notice_value / 4.35 : c.notice_value / 30.44;
}

function firstSentence(text: string | null | undefined): string | null {
  const t = (text ?? "").trim();
  if (!t) return null;
  const m = /^(.+?[.!?])(\s|$)/.exec(t);
  return (m ? m[1]! : t).trim();
}

export interface RuleInWords {
  /** e.g. "Cancellable any time with 1 month's notice (consumer contract since March 2022)" */
  text: string;
  /** main legal basis, e.g. "§ 56 TKG" (null for contracts that follow their own terms) */
  citation: string | null;
}

/**
 * How this contract can be ended, in one plain sentence, based on the rule the engine applied
 * (`computed.regime`). Never a promise — the "Why these dates?" popover has the details.
 */
export function ruleInWords(c: Contract, today: string): RuleInWords {
  const regime = c.computed?.regime ?? "as_written";
  const citation = regime === "as_written" ? null : CONTRACT_REGIME_COPY[regime].citation;
  const termEnd = c.computed?.current_term_end ?? null;
  const inMinTerm = Boolean(termEnd && termEnd >= today && c.initial_term_months);
  const until = termEnd ? formatDate(termEnd, { style: "day", today }) : "";
  const notice = noticePhrase(c);
  const shortNotice = (noticeMonths(c) ?? 1) < 1 && notice ? notice : "1 month's notice";
  // the contract's own "by the 10th of the month, to the month's end", where the rules read it — with its
  // notice period too, limited to a month where the consumer rules limit it after the first term
  const byDay = noticeDayPhrase(c, regime === "bgb309_new" || regime === "tkg56" ? notice && shortNotice : notice);
  let text: string;
  switch (regime) {
    case "bgb309_new": {
      const how = byDay ?? `any time with ${shortNotice}`;
      text = inMinTerm
        ? `Minimum term until ${until}; after that cancellable ${how} (consumer contract since March 2022)`
        : `Cancellable ${how} (consumer contract since March 2022)`;
      break;
    }
    case "bgb309_old":
      text = byDay
        ? `Cancellable ${byDay} (consumer contract from before March 2022)`
        : `Renews by up to 12 months at a time; ${notice ?? "up to 3 months' notice"} before the term ends (consumer contract from before March 2022)`;
      break;
    case "tkg56": {
      const how = byDay ?? "any time with 1 month's notice";
      text = inMinTerm
        ? `Minimum term until ${until}; after that cancellable ${how} (phone & internet contract)`
        : `Cancellable ${how} (phone & internet contract after its minimum term)`;
      break;
    }
    case "vvg11":
      text = `Renews every insurance year; cancel with ${notice ?? "3 months' notice"} before the insurance year ends`;
      break;
    case "sgbv175":
      text = "You can switch after 12 months of membership; a switch takes effect at the end of the second following month";
      break;
    case "stromgvv20":
      text = "Basic energy supply: cancellable any time with 2 weeks' notice";
      break;
    case "rent573c":
      text = "Open-ended: notice given by the 3rd working day of a month ends the tenancy at the end of the month after next — signed by hand on paper";
      break;
    case "employment622":
      // a fixed-term job can only be ended early by notice if its contract allows it (§ 15 Abs. 4 TzBfG,
      // `notice_before_end`): name the notice only then
      // (then at least the statutory notice: `_plan_employment` in `src/ordnung/rules/contracts.py`)
      text = c.end_date
        ? `Fixed term until ${formatDate(c.end_date, { style: "day", today })} — it ends by itself${c.notice_before_end ? `. To leave earlier: ${notice ? `${notice}, at least the legal minimum` : "the statutory notice"}` : ", no notice needed"}`
        : `Employment: ${notice ?? "the statutory notice"}, at least the legal minimum`;
      break;
    case "bgb675h":
      // a current account (§ 675h Abs. 1 BGB): no notice unless one was agreed, and at most a month of it counts
      text = notice ? `Current account: cancellable any time with ${notice} (at most one month counts)` : "Current account: cancellable any time, without notice";
      break;
    default: {
      const basis = c.notice_basis ? copyFor(NOTICE_BASIS_COPY, c.notice_basis).label : null;
      // the person's own entry says so (the card then asks nothing more of it)
      // (notice terms the person saves without a day clear it: the API's `_update`)
      const whose = noticeFromYou(c) ? "As you entered it" : "As written in the contract";
      if (byDay) text = `${whose}: cancellable ${byDay}`;
      else if (notice) text = `${whose}: ${notice}${basis ? ` ${basis}` : ""}`;
      else text = firstSentence(c.computed?.summary)?.replace(/\.$/, "") ?? "As written in the contract — no special legal rule applies";
    }
  }
  return { text, citation };
}

// ------------------------------------------------------------------------------------------------
// Contracts-only life lanes
// ------------------------------------------------------------------------------------------------

const NOTICE_LEAD_DAYS = 30;

function windowStatus(sendBy: string | null, cancelBy: string, today: string): LaneBarStatus {
  const t = dayNumber(today);
  if (dayNumber(cancelBy) < t) return "past";
  const d = dayNumber(sendBy ?? cancelBy) - t;
  if (d <= 14) return "urgent";
  if (d <= 60) return "attention";
  return "ok";
}

function addMonthsISO(iso: string, months: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return format(addMonths(new Date(y!, m! - 1, d!), months), "yyyy-MM-dd");
}

const marker = (date: string, label: string, kind: TimelineMarker["kind"]): TimelineMarker => ({ date, label, kind });

export interface LaneNote {
  text: string;
  tone: "warn" | "muted";
}

/**
 * The line under a contract's name in the chart when the next date on its lane would mislead:
 * terms we couldn't work out ask to be checked, and a contract that is no decision (cancellable
 * any month, or its minimum term just running out) says when it could end at the earliest — not
 * "Minimum term ends · in 2 days". Null: the chart's own next date.
 */
export function contractLaneNote(c: Contract, today: string): LaneNote | null {
  // short enough for a phone's lane label; the same words as the card's button
  if (termsUnclear(c)) return { text: "Check the letter", tone: "warn" };
  if (cancellationSent(c)) return { text: "Cancellation sent", tone: "muted" };
  const exit = c.computed?.earliest_exit;
  if (c.status !== "active" || !exit || exit < today || isLockInDecision(c) || isFixedTerm(c)) return null;
  return { text: `Earliest end · ${formatDate(exit, { style: "day", today })}`, tone: "muted" };
}

/**
 * One lane per contract: the current term (or the whole open-ended contract), what follows it
 * (renewal / month to month), the hatched "Time to cancel" window ending on the must-arrive-by
 * date with its send-by diamond, and the earliest possible end. Bars outside `range` are kept —
 * the chart clips them.
 */
export function contractLanes(contracts: Contract[], range: { from: string; to: string }, today: string): Lane[] {
  const beyond = addDaysISO(range.to, 1);
  return contracts.map((c) => {
    const comp = c.computed;
    const ref = { type: "contract", id: c.id };
    const start = c.start_date ?? c.concluded_date ?? range.from;
    const termEnd = comp?.current_term_end ?? null;
    const bars: LaneBar[] = [];
    const markers: TimelineMarker[] = [];
    const past = (end: string): LaneBarStatus => (end < today ? "past" : "ok");
    const bar = (id: string, label: string, s: string, e: string, extra: Partial<LaneBar> = {}): LaneBar => ({
      id: `${c.id}:${id}`,
      label,
      start: s,
      end: e < s ? s : e,
      kind: "contract",
      status: past(e),
      markers: [],
      ref,
      ...extra,
    });

    if (c.status !== "active") {
      const end = c.end_date ?? termEnd ?? today;
      bars.push(bar("term", c.status === "cancelled" ? "Cancelled — runs until" : "Ended", start, end, { markers: [marker(end, "Ends", "expiry")] }));
    } else if (c.end_date && isFixedTerm(c)) {
      bars.push(bar("term", "Fixed term", start, c.end_date, { markers: [marker(c.end_date, "Ends", "expiry")] }));
    } else if (termEnd) {
      const regime = comp?.regime;
      const firstTerm = Boolean(c.initial_term_months) && (!c.start_date || addMonthsISO(c.start_date, c.initial_term_months!) > termEnd);
      const termLabel = regime === "vvg11" ? "Insurance year" : firstTerm ? "Minimum term" : "Current term";
      const next = addDaysISO(termEnd, 1);
      const renewalMonths = c.renewal_term_months ?? (regime === "vvg11" ? 12 : null);
      // a renewed term: draw only the current period, not every year since the start
      const termStart = !firstTerm && renewalMonths ? addMonthsISO(next, -renewalMonths) : start;
      bars.push(bar("term", termLabel, termStart > start ? termStart : start, termEnd, { markers: [marker(termEnd, `${termLabel} ends`, "other")] }));
      if (renewalMonths && regime !== "tkg56" && regime !== "bgb309_new") {
        const until = addDaysISO(addMonthsISO(next, renewalMonths), -1);
        bars.push(
          bar("renewal", regime === "vvg11" ? "Next insurance year" : `Renews for ${renewalMonths} months`, next, until, {
            markers: comp?.next_renewal ? [marker(comp.next_renewal, "Renews", "renewal")] : [],
          }),
        );
      } else {
        bars.push(bar("after", "Cancellable any time", next, beyond, { open_end: true }));
      }
    } else if (termsUnclear(c)) {
      // no notice period in the letter: don't draw it as cancellable any time (nor invent an end)
      bars.push(bar("open", "Terms unclear", start, beyond, { open_end: true }));
    } else {
      const anyTime = c.notice_basis === "any_time" || comp?.regime === "bgb309_new" || comp?.regime === "stromgvv20";
      bars.push(bar("open", anyTime ? "Cancellable any time" : "Open-ended", start, beyond, { open_end: true }));
    }

    // a contract you can cancel any month has no window that closes — just when it would end; nor has one
    // whose cancellation was sent (final review: the chart still said "Send by 8 Oct" after it was)
    const rolling = isRollingContract(c);
    const sent = Boolean(cancellationSent(c));
    if (c.status === "active" && comp?.cancel_by && !rolling && !sent) {
      const sendBy = comp.send_by;
      const windowMarkers = [marker(comp.cancel_by, "Must arrive by", "cancel_by")];
      if (sendBy) windowMarkers.unshift(marker(sendBy, "Send by", "send_by"));
      bars.push({
        id: `${c.id}:notice`,
        label: "Time to cancel",
        start: addDaysISO(sendBy ?? comp.cancel_by, -NOTICE_LEAD_DAYS),
        end: comp.cancel_by,
        kind: "notice_window",
        status: windowStatus(sendBy, comp.cancel_by, today),
        markers: windowMarkers,
        ref,
      });
    }
    // the contract's own date (its `ref`): the chart draws it on the bar it falls on, not on a row of its own
    const exit = comp?.earliest_exit;
    if (c.status === "active" && exit && exit >= today && sent) {
      markers.push({ ...marker(exit, "Ends (cancellation sent)", "other"), ref });
    } else if (c.status === "active" && exit && exit >= today && exit !== termEnd && (!comp?.cancel_by || rolling)) {
      markers.push({ ...marker(exit, "Earliest end (if you cancel now)", "other"), ref });
    }
    return { id: c.id, label: c.name, area: c.area, bars, markers };
  });
}
