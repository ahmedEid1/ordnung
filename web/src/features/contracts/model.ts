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
 * A window that closes and locks you in: after it, the contract runs on for another term (a
 * minimum term ending, a yearly renewal).
 */
export function isLockInDecision(c: Pick<Contract, "computed">): boolean {
  const k = c.computed;
  return Boolean(k?.cancel_by && k.send_by && (k.next_renewal || k.current_term_end));
}

/**
 * A contract you can cancel any month (rent, statutory health insurance after its first year): no
 * term runs out, so its "cancel by" date only says when it would end — miss it, and it ends a month
 * later. Never urgent.
 */
export function isRollingContract(c: Pick<Contract, "computed" | "status">): boolean {
  const k = c.computed;
  return c.status === "active" && Boolean(k?.cancel_by) && !k?.next_renewal && !k?.current_term_end;
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
 * The notice period can be entered or changed on the card: terms we couldn't work out, terms the
 * rules follow as written (no statutory rule), or terms the person entered (a typo stays correctable).
 */
export function noticeEditable(c: Pick<Contract, "computed" | "status" | "evidence">): boolean {
  return c.status === "active" && (termsUnclear(c) || c.computed?.regime === "as_written" || noticeFromYou(c));
}

/**
 * Why a contract's card asks "Please check" (the rules' confidence is low), in words for its tooltip
 * and a screen reader — or null when it doesn't: the person entered the notice period themselves.
 */
export function pleaseCheckHint(c: Pick<Contract, "computed" | "status" | "evidence">): string | null {
  if (c.computed?.confidence !== "low" || noticeFromYou(c)) return null;
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
      const s = offersEndingLetter(c) && isLockInDecision(c) ? c.computed?.send_by : null;
      if (!s) return false;
      const d = dayNumber(s) - t;
      return d >= 0 && d <= days;
    })
    .sort((a, b) => a.computed!.send_by!.localeCompare(b.computed!.send_by!));
}

/** The next date to act on for a contract (send-by, else must-arrive-by), if still ahead. */
export function nextActionDate(c: Contract, today: string): string | null {
  if (isRollingContract(c)) return null; // cancellable any month: nothing to act on by a date
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
  let text: string;
  switch (regime) {
    case "bgb309_new":
      text = inMinTerm
        ? `Minimum term until ${until}; after that cancellable any time with ${shortNotice} (consumer contract since March 2022)`
        : `Cancellable any time with ${shortNotice} (consumer contract since March 2022)`;
      break;
    case "bgb309_old":
      text = `Renews by up to 12 months at a time; ${notice ?? "up to 3 months' notice"} before the term ends (consumer contract from before March 2022)`;
      break;
    case "tkg56":
      text = inMinTerm
        ? `Minimum term until ${until}; after that cancellable any time with 1 month's notice (phone & internet contract)`
        : "Cancellable any time with 1 month's notice (phone & internet contract after its minimum term)";
      break;
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
      // a fixed-term job can only be ended early if the contract allows it (§ 15 Abs. 4 TzBfG):
      // name the notice only when the contract has one
      text = c.end_date
        ? `Fixed term until ${formatDate(c.end_date, { style: "day", today })} — it ends by itself${notice ? `. To leave earlier: ${notice}` : ", no notice needed"}`
        : `Employment: ${notice ?? "the statutory notice"}, at least the legal minimum`;
      break;
    default: {
      const basis = c.notice_basis ? copyFor(NOTICE_BASIS_COPY, c.notice_basis).label : null;
      // the person's own entry says so (the card then asks nothing more of it)
      if (notice) text = `${noticeFromYou(c) ? "As you entered it" : "As written in the contract"}: ${notice}${basis ? ` ${basis}` : ""}`;
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

    // a contract you can cancel any month has no window that closes — just when it would end
    const rolling = isRollingContract(c);
    if (c.status === "active" && comp?.cancel_by && !rolling) {
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
    const exit = comp?.earliest_exit;
    if (c.status === "active" && exit && exit >= today && exit !== termEnd && (!comp?.cancel_by || rolling)) {
      markers.push(marker(exit, "Earliest end (if you cancel now)", "other"));
    }
    return { id: c.id, label: c.name, area: c.area, bars, markers };
  });
}
