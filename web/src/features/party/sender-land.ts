/**
 * The question about a sender's state (Land) that the postcode on their letter suggests (ADR 0019): which of the
 * rules engine's warnings say a date may change once it is confirmed, and the words under the question. Ordnung
 * never sets the state itself: the server only suggests it (`region_suggestion`), and the person answers.
 */
import type { RegionSuggestion } from "@/api/types";
import { LAND_UNKNOWN } from "@/features/document/WhyThisDate";

/**
 * Länder whose authorities' letters count as delivered on the 4th day (`rules.delivery.VWVFG_FOUR_DAY_FROM`): only
 * there can confirming the state change a date the engine counted with 3 days. Hessen keeps the 3rd day by its own
 * law, and the Saarland's 4th day isn't confirmed: Ordnung counts 3 days there anyway.
 */
export const FOUR_DAY_LANDS: ReadonlySet<string> = new Set(["BB", "BE", "BW", "BY", "HB", "HH", "MV", "NI", "NW", "RP", "SH", "SN", "ST", "TH"]);

/** Why a letter's date may change once the sender's state is confirmed. */
export type LandWait = "earlier" | "email" | "days" | "holiday";

/**
 * What confirming `region` may do to a date with these warnings (`rules.deadlines.waits_for_sender_land`), the
 * strongest first: counted backwards it may be a day late (`earlier`), an e-mailed decision counted from the day it
 * was sent may count from the 3rd or 4th day (`email`, in every state but Brandenburg), a Land authority's letter may
 * count 4 days (`days`, only in a state with the 4-day rule), or a regional holiday may move it (`holiday`). `null`:
 * nothing.
 */
export function landWait(warnings: readonly string[], region: string): LandWait | null {
  if (warnings.some((w) => w.includes(LAND_UNKNOWN.earlier))) return "earlier";
  if (region !== "BB" && warnings.some((w) => w.includes(LAND_UNKNOWN.email))) return "email";
  if (FOUR_DAY_LANDS.has(region) && warnings.some((w) => w.includes(LAND_UNKNOWN.threeDays))) return "days";
  if (warnings.some((w) => w.startsWith(LAND_UNKNOWN.start))) return "holiday";
  return null;
}

/** "it" or "them". */
const them = (n: number) => (n === 1 ? "it" : "them");

/**
 * The line under the question in the sender's details: what their state decides, and what it may change now, by the
 * strongest reason among their waiting dates (`reason`, as `landWait` reads one letter's: `LAND_WAIT_REASON`). The
 * others may wait for a weaker reason, so what Ordnung counts is said of the reason's own dates ("such a decision",
 * "some of them"). A day more before the delivery day can push a period's end over a weekend and the holidays.
 */
export function senderLandLine(s: Pick<RegionSuggestion, "waiting" | "may_be_late" | "reason">): string {
  if (s.waiting <= 0) return "Their state's public holidays can move the dates in their letters.";
  const count = `This may change ${s.waiting} of your dates with them.`;
  const may = s.waiting === 1 ? "it may" : "they may";
  switch (s.reason ?? (s.may_be_late ? "earlier" : "holiday")) {
    case "earlier":
      return `${count} Until you answer, act a working day before ${them(s.waiting)}: a holiday in their state could make ${s.waiting === 1 ? "it" : "some of them"} earlier.`;
    case "email":
      return `${count} Their state decides whether an e-mailed decision counts from the day it arrived or the 3rd or 4th day after it was sent. Until you answer, Ordnung counts such a decision from the day it was sent, or from the arrival day you entered, so ${may} be several days early, more around weekends and holidays.`;
    case "days":
      return `${count} Their state decides whether their letters count as delivered after 3 or 4 days. Until you answer, Ordnung counts 3, so ${may} be a day early, more around weekends and holidays.`;
    case "holiday":
      return `${count} Until you answer, Ordnung counts only nationwide holidays, so ${may} be a day or two early.`;
  }
}

/** Why a letter asks, from its own dates. */
export const LAND_WAIT_REASON: Record<LandWait, string> = {
  earlier: "A holiday in their state could make a date earlier. Until you answer, act a working day before it.",
  email:
    "Their state decides whether an e-mailed decision counts from the day it arrived or the 3rd or 4th day after it was sent. Until you answer, Ordnung counts from the day it was sent, or from the arrival day you entered, so the date may be several days early, more around weekends and holidays.",
  days: "Their state decides whether this letter counts as delivered after 3 or 4 days. Until you answer, Ordnung counts 3, so the date may be a day early, more around weekends and holidays.",
  holiday:
    "Their state's public holidays may move this letter's dates. Until you answer, Ordnung counts only nationwide holidays, so a date may be a day or two early.",
};

/**
 * What the toast says once the sender's state is saved: their dates now skip its public holidays, and, when their
 * dates waited for its delivery rules (an e-mailed decision's day, or 3 or 4 days: `reason`), follow those too.
 */
export function savedStateLine(state: string, reason: LandWait | null | undefined): string {
  return reason === "email" || reason === "days"
    ? `Their dates now follow the delivery rules and public holidays of ${state}.`
    : `Their dates now skip the public holidays of ${state}.`;
}
