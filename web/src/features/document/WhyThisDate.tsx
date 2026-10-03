/**
 * "Why this date?" for a letter's to-do — the rules engine's receipt in the shared {@link Receipt}:
 * the key dates, the plain sentence, how sure we are (and why), what the letter says, then "Show
 * the rules" with every step, its citation and the holiday calendar. Always ends with the
 * point-of-use disclaimer (SPEC §21), with independent advice for high-stakes areas. A date counted
 * without the sender's Land says so, with the way to choose it.
 */
import { useQueryClient } from "@tanstack/react-query";
import { MapPin } from "lucide-react";
import type { Area, ComputationReceipt, DateSpec, Document, DocumentDetail, DocumentKind, Item, ItemOrigin, Party, PartyKind } from "@/api/types";
import { qk } from "@/api/hooks";
import { isTransfer } from "@/lib/payments";
import { usePartyDrawer } from "@/lib/party-drawer";
import { ADVICE_LINKS, type AdviceLink } from "@/components/ui/Disclaimer";
import { Receipt, ReceiptPopover, useReceiptSteps, type ReceiptDate } from "@/components/ui/Receipt";
import { looksAbroad } from "@/features/party/model";
import { dueDateLabel, sendByLabel } from "./dateLabels";

/**
 * How the rules engine says a date waits for the sender's Land: a regional holiday may move it
 * (`rules.deadlines.REGION_UNKNOWN`, how that warning starts), or a Land authority's own delivery rule may
 * (`rules.delivery`: "… we couldn't confirm this sender's, so we counted 3 days").
 */
const LAND_UNKNOWN = { start: "Holiday region unknown", threeDays: "couldn't confirm this sender's" } as const;

/** Letters about a tenancy: the tenants' association advises, whatever area the letter was read under. */
const TENANCY_KINDS: ReadonlySet<DocumentKind> = new Set<DocumentKind>(["rent_lease", "operating_costs", "rent_increase", "landlord_notice"]);

/**
 * Companies whose letters are consumer matters (an electricity contract, a phone bill, a gym): the consumer
 * advice centre, not the tenants' association or student services, when such a letter is filed under a home
 * or residence area.
 */
const CONSUMER_PARTIES: ReadonlySet<PartyKind> = new Set<PartyKind>(["utility", "telecom", "retailer", "gym", "bank", "insurer", "transport"]);

function areaAdvice(area: Area | null | undefined): AdviceLink[] | undefined {
  switch (area) {
    case "tax":
      return ADVICE_LINKS.tax;
    case "residence":
      return ADVICE_LINKS.residence;
    case "home":
      return ADVICE_LINKS.rent;
    case "mobility":
      return ADVICE_LINKS.fines;
    default:
      return undefined;
  }
}

/**
 * Independent advice links for high-stakes areas (tax, residence, rent, fines). The letter's kind and its
 * sender's kind come first when known: a lease or an operating-cost statement is the tenants' association's
 * (UI audit round 1: a landlord's statement read under "residence" pointed to the Studierendenwerk), a
 * residence permit the student services', a Stadtwerke bill filed under housing the consumer advice centre's.
 */
export function adviceFor(area: Area | null | undefined, docKind?: DocumentKind | null, partyKind?: PartyKind | null): AdviceLink[] | undefined {
  if ((docKind && TENANCY_KINDS.has(docKind)) || partyKind === "landlord") return ADVICE_LINKS.rent;
  if (docKind === "residence_permit" || partyKind === "immigration_office") return ADVICE_LINKS.residence;
  if (docKind === "tax_assessment" || docKind === "tax_letter" || partyKind === "tax_office") return ADVICE_LINKS.tax;
  if (docKind === "fine") return ADVICE_LINKS.fines;
  const byArea = areaAdvice(area);
  if (byArea && (area === "home" || area === "residence") && partyKind && CONSUMER_PARTIES.has(partyKind)) return ADVICE_LINKS.consumer;
  return byArea;
}

/** The to-do a receipt belongs to: what kind of date it is, and its letter. */
export type ReceiptItem = Pick<Item, "kind" | "direction" | "title" | "action" | "description" | "doc_id">;

/**
 * The receipt's key dates, named by the deadline's nature as the Today page and the verdict name them
 * (`dateLabels.ts`): an appointment's day is "On", a payment's "Pay by", an objection's "Must arrive by";
 * a bank transfer is made by its send-by day ("Transfer by", UI audit round 1: not "Send by" / "Post it
 * by" beside the verdict's "Transfer it by"), anything else is sent by it, and next to a send-by day the
 * due date is the day it must arrive. `transfer` says whether the to-do is a transfer (default: from
 * `item`, else from the spec's nature). A send-by day that is the due date itself (the usual posting time
 * has passed: "send it today") is no second tile — the verdict's date box leaves it out too (UI audit
 * round 2: "Send by Mon 28 Sep" beside "Must arrive by Mon 28 Sep").
 */
export function receiptDates(
  receipt: ComputationReceipt,
  item?: ReceiptItem | null,
  spec?: Pick<DateSpec, "nature"> | null,
  transfer?: boolean,
): ReceiptDate[] {
  const dates: ReceiptDate[] = [];
  const isTransferred = transfer ?? (item ? isTransfer(item) : undefined);
  if (receipt.send_by && receipt.send_by !== receipt.due_date) dates.push({ label: sendByLabel(spec?.nature, isTransferred), date: receipt.send_by });
  if (receipt.due_date) dates.push({ label: dueDateLabel(spec?.nature, Boolean(receipt.send_by)), date: receipt.due_date });
  if (receipt.safe_date && receipt.safe_date !== receipt.due_date) dates.push({ label: "Safe date (a working day)", date: receipt.safe_date });
  return dates;
}

/** The to-do's letter's kind and sender, from the letter already loaded for the page (nothing is fetched). */
function useLetter(docId: string | null | undefined): { docKind: DocumentKind | null; party: Party | null } {
  const qc = useQueryClient();
  const detail = docId ? qc.getQueryData<DocumentDetail>(qk.documents.detail(docId)) : undefined;
  return { docKind: detail?.document.kind ?? null, party: detail?.party ?? null };
}

/**
 * The sender whose Land the date waits for: the person hasn't said which state this sender in Germany is in,
 * and the engine says that matters here — it counted nationwide holidays where a Land's holiday may make the
 * date later, or a Land authority's 3-day delivery rule (`LAND_UNKNOWN`), at lower confidence. `null` when the
 * Land is known, the sender looks abroad or the date doesn't depend on it (an appointment, a date read from a
 * photo whose only doubt is the photo).
 */
export function senderLandUnknown(receipt: Pick<ComputationReceipt, "warnings">, party: Party | null): Party | null {
  if (!party || party.region || looksAbroad(party)) return null;
  const waits = receipt.warnings.some((w) => w.startsWith(LAND_UNKNOWN.start) || w.includes(LAND_UNKNOWN.threeDays));
  return waits ? party : null;
}

/** "Ordnung doesn't know which state … is in" and the way to choose it (the sender's drawer, with its State picker). */
function SenderLandNote({ party }: { party: Party }) {
  const drawer = usePartyDrawer();
  return (
    <p className="flex items-start gap-1.5 text-sm leading-relaxed text-muted">
      <MapPin className="mt-1 size-3.5 shrink-0" aria-hidden />
      <span>
        Ordnung doesn't know which state {party.name} is in, so this date may be a few days early.{" "}
        <button
          type="button"
          onClick={() => drawer.open(party.id)}
          className="inline-flex min-h-6 items-center rounded-md font-medium text-accent underline decoration-accent/30 underline-offset-[3px] hover:decoration-accent"
        >
          Choose their state
        </button>
      </span>
    </p>
  );
}

/**
 * The language a letter is written in (its `language`, as the reading named it), from what is already loaded — the
 * letter's page, or a list of letters (Today, the Inbox); nothing is fetched. `null` when neither has it.
 */
export function useLetterLanguage(docId: string | null | undefined): string | null {
  const qc = useQueryClient();
  if (!docId) return null;
  const detail = qc.getQueryData<DocumentDetail>(qk.documents.detail(docId));
  if (detail) return detail.document.language;
  const lists = qc.getQueriesData<Document[]>({ queryKey: [...qk.documents.all, "list"] });
  const listed = lists.flatMap(([, docs]) => (Array.isArray(docs) ? docs : [])).find((d) => d.id === docId);
  return listed?.language ?? null;
}

export interface ReceiptViewProps {
  receipt: ComputationReceipt;
  /** What the letter says (shown as the quote the date came from). */
  spec?: DateSpec | null;
  area?: Area | null;
  /** Start with the rule steps open. */
  defaultShowRules?: boolean;
  /**
   * Where the to-do came from: a deadline the law adds (`rule`) has a spec Ordnung wrote in the law's
   * words — never shown as what the letter says.
   */
  origin?: ItemOrigin | null;
  /** The to-do: a transfer's "Transfer by", and its letter's kind for the advice links. */
  item?: ReceiptItem | null;
  /** The to-do is money you transfer (`isTransfer`), when no `item` says so: its send-by date is "Transfer by". */
  transfer?: boolean;
}

export function ReceiptView({ receipt, spec, area, defaultShowRules = false, origin, item, transfer }: ReceiptViewProps) {
  const steps = useReceiptSteps(receipt.steps);
  const { docKind, party } = useLetter(item?.doc_id);
  const landless = senderLandUnknown(receipt, party);
  // the letter's words are in the letter's language (the law's short wording is Ordnung's)
  const language = useLetterLanguage(item?.doc_id);
  return (
    <Receipt
      dates={receiptDates(receipt, item, spec, transfer)}
      summary={receipt.summary}
      confidence={receipt.confidence}
      warnings={receipt.warnings}
      quote={spec?.text ? (origin === "rule" ? { text: spec.text, source: "law", citation: spec.legal_basis } : { text: spec.text, language }) : null}
      steps={steps}
      holidayCalendar={receipt.holiday_calendar}
      defaultShowRules={defaultShowRules}
      advice={adviceFor(area, docKind, party?.kind)}
    >
      {landless ? <SenderLandNote party={landless} /> : null}
    </Receipt>
  );
}

/**
 * A "Why this date?" trigger that opens the receipt in a popover.
 *
 * @example <WhyThisDate receipt={item.computation} spec={item.date_spec} item={item} />
 */
export function WhyThisDate({
  receipt,
  spec,
  area,
  origin,
  item,
  transfer,
  context,
  title,
  className,
}: {
  receipt: ComputationReceipt;
  spec?: DateSpec | null;
  area?: Area | null;
  /** Where the to-do came from (see {@link ReceiptViewProps.origin}). */
  origin?: ItemOrigin | null;
  /** The to-do (see {@link ReceiptViewProps.item}). */
  item?: ReceiptItem | null;
  /** The to-do is money you transfer (see {@link ReceiptViewProps.transfer}). */
  transfer?: boolean;
  /** What the date belongs to (the to-do's title), for screen readers. */
  context?: string;
  /** The trigger's words (default "Why this date?"). */
  title?: string;
  className?: string;
}) {
  return (
    <ReceiptPopover
      content={<ReceiptView receipt={receipt} spec={spec} area={area} origin={origin} item={item} transfer={transfer} />}
      context={context}
      title={title}
      className={className}
    />
  );
}
