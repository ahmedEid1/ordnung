/**
 * The question about a sender's state (Land) that the postcode on their letter suggests (ADR 0019): which of the
 * rules engine's warnings say a date may change once it is confirmed, and the words under the question. Ordnung
 * never sets the state itself: the server only suggests it (`region_suggestion`), and the person answers.
 */
import type { RegionSuggestion } from "@/api/types";
import { LAND_UNKNOWN } from "@/features/document/WhyThisDate";

/**
 * Länder whose authorities' letters count as delivered on the 4th day (`rules.delivery.VWVFG_FOUR_DAY_FROM`): only
 * there can confirming the state change a date the engine counted with 3 days. Bremen, the Saarland and Thuringia
 * count 3 days anyway.
 */
export const FOUR_DAY_LANDS: ReadonlySet<string> = new Set(["BB", "BE", "BW", "BY", "HH", "MV", "NI", "NW", "RP", "SH", "SN", "ST"]);

/** Why a letter's date may change once the sender's state is confirmed. */
export type LandWait = "earlier" | "days" | "holiday";

/**
 * What confirming `region` may do to a date with these warnings (`rules.deadlines.waits_for_sender_land`), the
 * strongest first: counted backwards it may be a day late (`earlier`), a Land authority's letter may count 4 days
 * (`days`, only in a state with the 4-day rule), or a regional holiday may move it (`holiday`). `null`: nothing.
 */
export function landWait(warnings: readonly string[], region: string): LandWait | null {
  if (warnings.some((w) => w.includes(LAND_UNKNOWN.earlier))) return "earlier";
  if (FOUR_DAY_LANDS.has(region) && warnings.some((w) => w.includes(LAND_UNKNOWN.threeDays))) return "days";
  if (warnings.some((w) => w.startsWith(LAND_UNKNOWN.start))) return "holiday";
  return null;
}

/** "it" or "them". */
const them = (n: number) => (n === 1 ? "it" : "them");

/** The line under the question in the sender's details: what their state decides, and what it may change now. */
export function senderLandLine(s: Pick<RegionSuggestion, "waiting" | "may_be_late">): string {
  if (s.waiting <= 0) return "Their state's public holidays can move the dates in their letters.";
  const count = `This may change ${s.waiting} of your dates with them.`;
  return s.may_be_late
    ? `${count} Until you answer, act a working day before ${them(s.waiting)}: a holiday in their state could make ${them(s.waiting)} earlier.`
    : `${count} Until you answer, Ordnung counts only nationwide holidays, so ${s.waiting === 1 ? "it may" : "they may"} be a day or two early.`;
}

/** Why a letter asks, from its own dates. */
export const LAND_WAIT_REASON: Record<LandWait, string> = {
  earlier: "A holiday in their state could make a date earlier. Until you answer, act a working day before it.",
  days: "Their state decides whether this letter counts as delivered after 3 or 4 days. Until you answer, Ordnung counts 3, so the date may be a day early.",
  holiday:
    "Their state's public holidays may move this letter's dates. Until you answer, Ordnung counts only nationwide holidays, so a date may be a day or two early.",
};
