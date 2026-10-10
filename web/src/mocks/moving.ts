/**
 * The static demo's moving checklist: a simplified port of `src/ordnung/secretary/moving.py` (the `moved_house`
 * Idea rule) over the mock state, in the API's words. After a move told in Settings → Profile it lists registering
 * the new address within two weeks (§ 17 Abs. 1 BMG; the day is never moved off a weekend), each sender with a running contract (a
 * contract named after the flat is counted, never named), and the broadcasting fee office when no listed sender
 * is the broadcaster. `moving-cases.json` holds the same ledgers for this port and the API's rule.
 *
 * Left out of the port: senders known only from their letters (the API lists those of a kind that keeps your
 * address and wrote in the last three years), scam signs and private letters, and the 60 days before the move
 * within which a new-address letter marked sent counts (here any one does).
 */
import { addDays, differenceInCalendarDays, format, parseISO } from "date-fns";
import type { Contract, Draft, Party, Profile, Suggestion, SuggestionAction } from "@/api/types";
import type { MockDb } from "./db";
import { nowTs } from "./db";

export const MOVED_HOUSE_RULE = "moved_house";
/** The checklist ends this many days after the move; a move may be told this far back. */
export const MOVE_WINDOW_DAYS = 180;
/** How far ahead a move may be told. */
export const MOVE_AHEAD_DAYS = 90;
/** Why a day outside the window is refused (the API's `MOVE_WINDOW_PROBLEM`). */
export const MOVE_WINDOW_PROBLEM = "Ordnung's moving checklist is for a move in the last six months or the next three — check the day.";

const KIND_ORDER = ["employer", "bank", "insurer", "health_insurer", "public_broadcaster", "landlord", "utility", "telecom", "university", "tax_office", "immigration_office"];
const BROADCASTING_TIP =
  "If you pay the broadcasting fee (Rundfunkbeitrag) for your flat, change your address online at rundfunkbeitrag.de. If you moved in with someone who already pays, you can de-register instead.";
const KIND_TIPS: Record<string, string> = {
  bank: "Many banks let you change it in online banking.",
  insurer: "Most insurers let you change it in their app or online account.",
  health_insurer: "Most insurers let you change it in their app or online account.",
  employer: "Tell HR or payroll: your payslips and tax papers go there.",
  landlord: "A landlord you are leaving needs it for your deposit and the last operating-cost statement.",
  utility: "Note your meter readings on the day you move out and send them in.",
  telecom: "If they provide your internet at home, ask whether they can move the line to the new address.",
  public_broadcaster: BROADCASTING_TIP,
  tax_office: "Letters about your tax return go there.",
  immigration_office: "Letters about your residence permit go there.",
  university: "Letters about your enrolment go there.",
};
const CATEGORY_TIPS: Record<string, string> = {
  bank: KIND_TIPS.bank!,
  insurance: KIND_TIPS.insurer!,
  employment: KIND_TIPS.employer!,
  rent: KIND_TIPS.landlord!,
  energy: KIND_TIPS.utility!,
  gas: KIND_TIPS.utility!,
  internet: "Ask whether they can move your line to the new address.",
};
const REGISTRATION_BODY =
  "Register at the citizens' office (Bürgeramt or Einwohnermeldeamt) where you now live, within two weeks of moving in. Take your ID card or passport and your landlord's confirmation that you moved in (Wohnungsgeberbestätigung) — ask your landlord for it.";
/** The shortest address line a contract's name is checked for. */
const ADDRESS_LINE_MIN = 5;

export interface MovingLedger {
  profile: Pick<Profile, "moved_on" | "address" | "old_address">;
  parties: readonly Pick<Party, "id" | "name" | "kind">[];
  contracts: readonly Pick<Contract, "id" | "party_id" | "name" | "category" | "status">[];
  drafts: readonly Pick<Draft, "kind" | "party_id" | "status">[];
  today: string;
}

/** "Thu 8 Oct" (the year only when it isn't today's), as the API's `day_label`. */
function dayLabel(day: string, today: string): string {
  return format(parseISO(day), day.slice(0, 4) === today.slice(0, 4) ? "EEE d MMM" : "EEE d MMM yyyy");
}

/** Whether a move told for `movedOn` may start a checklist on `today` (the API's `move_problem`). */
export function moveAllowed(movedOn: string, today: string): boolean {
  const days = differenceInCalendarDays(parseISO(today), parseISO(movedOn));
  return days <= MOVE_WINDOW_DAYS && -days <= MOVE_AHEAD_DAYS;
}

const fold = (s: string) => s.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
const byText = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

function reason(contracts: MovingLedger["contracts"], lines: readonly string[]): string {
  const sorted = [...contracts].sort((a, b) => byText(a.name.toLowerCase(), b.name.toLowerCase()) || byText(a.id, b.id));
  const shown = sorted.filter((c) => !lines.some((l) => fold(c.name).includes(l))).map((c) => `“${c.name}”`).slice(0, 2);
  const more = sorted.length - shown.length;
  if (sorted.length === 1) return shown.length ? `Your contract ${shown[0]} with them is running.` : "Your contract with them is running.";
  if (!shown.length) return `Your ${sorted.length} contracts with them are running.`;
  return `Your contracts ${more ? `${shown.join(", ")} and ${more} more` : shown.join(" and ")} with them are running.`;
}

function row(
  entity: string,
  moved: string,
  fields: Pick<Suggestion, "kind" | "title" | "body" | "rationale" | "priority" | "due_date" | "refs"> & { action: SuggestionAction },
): Suggestion {
  return {
    id: `sug_move_${entity}_${moved}`,
    fingerprint: `${MOVED_HOUSE_RULE}:${entity}:${moved}`,
    status: "new",
    snoozed_until: null,
    source: "rule",
    rule_id: MOVED_HOUSE_RULE,
    savings_estimate: null,
    created_at: "",
    updated_at: "",
    ...fields,
  };
}

/** The `moved_house` rows of this ledger (none without a move, or once it is more than six months ago). */
export function movingIdeas(ledger: MovingLedger): Suggestion[] {
  const moved = ledger.profile.moved_on;
  if (!moved || differenceInCalendarDays(parseISO(ledger.today), parseISO(moved)) > MOVE_WINDOW_DAYS) return [];
  const today = ledger.today;
  const movedLabel = dayLabel(moved, today);
  const due = format(addDays(parseISO(moved), 14), "yyyy-MM-dd");
  const missed = due < today;
  const ideas: Suggestion[] = [
    row("registration", moved, {
      kind: "deadline",
      priority: "high",
      title: missed ? `Register your new address — it was due ${dayLabel(due, today)}` : `Register your new address by ${dayLabel(due, today)}`,
      body: `${REGISTRATION_BODY} ${missed ? "Register as soon as you can." : "Appointments are often booked out, so book one soon."}`,
      rationale: `You moved in on ${movedLabel}; registering is due within two weeks (§ 17 Abs. 1 BMG).`,
      due_date: due,
      refs: [],
      action: { type: "none", draft_kind: null, target_type: null, target_id: null, label: "Tick it off once you're registered" },
    }),
  ];
  const running = new Map<string, MovingLedger["contracts"][number][]>();
  for (const c of ledger.contracts) if (c.status === "active" && c.party_id) running.set(c.party_id, [...(running.get(c.party_id) ?? []), c]);
  const listed = ledger.parties
    .filter((p) => running.has(p.id))
    .sort((a, b) => {
      const rank = (p: Pick<Party, "kind">) => (KIND_ORDER.includes(p.kind) ? KIND_ORDER.indexOf(p.kind) : KIND_ORDER.length);
      return rank(a) - rank(b) || byText(a.name.toLowerCase(), b.name.toLowerCase()) || byText(a.id, b.id);
    });
  if (!listed.some((p) => p.kind === "public_broadcaster")) {
    ideas.push(
      row("broadcasting_fee", moved, {
        kind: "hygiene",
        priority: "low",
        title: "Tell the broadcasting fee office your new address",
        body: BROADCASTING_TIP,
        rationale: `You moved in on ${movedLabel}.`,
        due_date: null,
        refs: [],
        action: { type: "none", draft_kind: null, target_type: null, target_id: null, label: "Tick it off once it's changed" },
      }),
    );
  }
  const told = new Set(ledger.drafts.filter((d) => d.kind === "address_change" && d.status === "sent" && d.party_id).map((d) => d.party_id));
  const lines = [ledger.profile.address, ledger.profile.old_address].flatMap((a) => a.split("\n").map(fold)).filter((l) => l.length >= ADDRESS_LINE_MIN);
  for (const p of listed) {
    if (told.has(p.id)) continue;
    const contracts = running.get(p.id)!;
    const tip = p.kind === "public_broadcaster" ? BROADCASTING_TIP : (KIND_TIPS[p.kind] ?? contracts.map((c) => CATEGORY_TIPS[c.category]).find(Boolean));
    ideas.push(
      row(p.id, moved, {
        kind: "hygiene",
        priority: "low",
        title: `Tell ${p.name} your new address`,
        body: [reason(contracts, lines), tip].filter(Boolean).join(" "),
        rationale: `You moved in on ${movedLabel}.`,
        due_date: null,
        refs: [{ type: "party", id: p.id }],
        action: { type: "open", draft_kind: null, target_type: "party", target_id: p.id, label: "Write the letter" },
      }),
    );
  }
  return ideas;
}

/**
 * Run the rule over the mock state and keep its rows like the API's reconcile: a row still produced is refreshed
 * (the person's status kept; an expired one comes back as new), a new one is added, and an open one no longer
 * produced expires. Ticked and hidden rows of an earlier move stay as they are.
 */
export function refreshMovingIdeas(db: MockDb): void {
  const now = nowTs();
  const { profile, parties, contracts, drafts, suggestions } = db.state;
  const fresh = movingIdeas({ profile, parties, contracts, drafts, today: db.today });
  const live = new Set(fresh.map((s) => s.id));
  for (const s of fresh) {
    const had = suggestions.find((x) => x.id === s.id);
    if (!had) {
      suggestions.unshift({ ...s, created_at: now, updated_at: now });
      continue;
    }
    Object.assign(had, { title: s.title, body: s.body, rationale: s.rationale, priority: s.priority, refs: s.refs, action: s.action, due_date: s.due_date, updated_at: now });
    if (had.status === "expired") Object.assign(had, { status: "new", snoozed_until: null });
  }
  for (const s of suggestions) {
    if (s.rule_id === MOVED_HOUSE_RULE && !live.has(s.id) && (s.status === "new" || s.status === "snoozed")) Object.assign(s, { status: "expired", updated_at: now });
  }
}
