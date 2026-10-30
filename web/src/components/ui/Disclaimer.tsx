import { Fragment } from "react";
import { Scale, ExternalLink } from "lucide-react";
import type { Area, DocumentKind, LetterAdvice, PartyKind } from "@/api/types";
import { useRulesLastChecked } from "@/api/hooks";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/format";

export interface AdviceLink {
  /** The organisation's German name ("Mieterverein"). */
  label: string;
  /** What it is, in English ("tenants' association"). */
  note?: string;
  href: string;
}

/** Independent advice for high-stakes areas (SPEC §21). */
export const ADVICE_LINKS: Record<"residence" | "rent" | "consumer" | "tax" | "fines", AdviceLink[]> = {
  residence: [{ label: "Studierendenwerk", note: "student services", href: "https://www.studierendenwerke.de/" }],
  rent: [{ label: "Mieterverein", note: "tenants' association", href: "https://www.mieterbund.de/" }],
  consumer: [{ label: "Verbraucherzentrale", note: "consumer advice centre", href: "https://www.verbraucherzentrale.de/" }],
  tax: [{ label: "Lohnsteuerhilfeverein", note: "tax help", href: "https://www.bvl-verband.de/" }],
  fines: [{ label: "Verbraucherzentrale", note: "consumer advice centre", href: "https://www.verbraucherzentrale.de/" }],
};

/** Letters about a tenancy: the tenants' association advises, whatever area the letter was read under. */
const TENANCY_KINDS: ReadonlySet<DocumentKind> = new Set<DocumentKind>(["rent_lease", "operating_costs", "rent_increase", "landlord_notice"]);

/**
 * Senders whose letters are consumer matters (an electricity contract, a phone bill, a gym, the broadcasting fee):
 * the consumer advice centre, not the tenants' association or student services, when such a letter is filed under
 * a home or residence area.
 */
const CONSUMER_PARTIES: ReadonlySet<PartyKind> = new Set<PartyKind>(["utility", "telecom", "retailer", "gym", "bank", "insurer", "transport", "public_broadcaster"]);

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
 * "Unsure? Get independent advice": the one rule for the letter page, "Why this date?", the composer's objection
 * check and an objection's disclaimer. The letter comes first, then its sender, then the area it was read under:
 * - a letter with a "get advice" card (`card`, a high-stakes letter): the tenants' association for a tenancy letter,
 *   none for the others — the card lists its own help (a court's desk, a union);
 * - the broadcasting fee (its kind, or a public broadcaster's letter): the consumer advice centre, never the tenants'
 *   association, though it is filed under "home";
 * - a tenancy letter or a landlord's: the tenants' association (a statement read under "residence" pointed to the
 *   Studierendenwerk); a residence permit: student services; a tax letter: tax help; a fine: consumer advice;
 * - otherwise the area's, with a company's letter filed under a home or residence area sent to consumer advice.
 */
export function adviceFor(
  area: Area | null | undefined,
  docKind?: DocumentKind | null,
  partyKind?: PartyKind | null,
  card?: Pick<LetterAdvice, "kind"> | null,
): AdviceLink[] | undefined {
  if (card) return TENANCY_KINDS.has(card.kind) ? ADVICE_LINKS.rent : undefined;
  if (docKind === "broadcasting_fee" || partyKind === "public_broadcaster") return ADVICE_LINKS.consumer;
  if ((docKind && TENANCY_KINDS.has(docKind)) || partyKind === "landlord") return ADVICE_LINKS.rent;
  if (docKind === "residence_permit" || partyKind === "immigration_office") return ADVICE_LINKS.residence;
  if (docKind === "tax_assessment" || docKind === "tax_letter" || partyKind === "tax_office") return ADVICE_LINKS.tax;
  if (docKind === "fine") return ADVICE_LINKS.fines;
  const byArea = areaAdvice(area);
  if (byArea && (area === "home" || area === "residence") && partyKind && CONSUMER_PARTIES.has(partyKind)) return ADVICE_LINKS.consumer;
  return byArea;
}

/**
 * "Unsure? Get independent advice: Mieterverein (tenants' association) ↗." — the links open in a
 * new tab; their padding makes them taller targets without spreading the lines of the text around
 * them. They wrap like the sentence they are in: an inline box, the icon and the full stop joined to
 * the last word (as a block of their own they jumped to a new line on a phone, the icon at the far
 * edge and the full stop alone under it — UI audit round 1).
 */
export function AdviceLinks({ advice, className }: { advice: AdviceLink[]; className?: string }) {
  if (!advice.length) return null;
  return (
    <span className={className}>
      Unsure? Get independent advice:{" "}
      {advice.map((a, i) => (
        <Fragment key={a.href}>
          {i > 0 ? " or " : ""}
          <a
            href={a.href}
            target="_blank"
            rel="noreferrer noopener"
            data-advice-link
            className="-my-0.5 rounded-sm py-0.5 font-medium text-accent underline-offset-2 [overflow-wrap:anywhere] hover:underline"
          >
            <span lang="de">{a.label}</span>
            {a.note ? ` (${a.note})` : null}
            <span className="sr-only"> (opens in a new tab)</span>
            {"⁠"}
            <ExternalLink className="ml-1 inline size-3 align-[-0.1em]" aria-hidden />
          </a>
        </Fragment>
      ))}
      {"⁠."}
    </span>
  );
}

export interface DisclaimerProps {
  /** Law as of (defaults to the rules catalog's date from `GET /api/health`). */
  lastChecked?: string;
  /** Independent advice links to show (high-stakes areas). */
  advice?: AdviceLink[];
  /** `inline` single line, or `block` with a top border. */
  variant?: "inline" | "block";
  className?: string;
}

/**
 * Point-of-use legal disclaimer: "Based on the law as of 25 Sep 2026. Not legal advice. Not
 * reviewed by a lawyer." Show wherever dates are computed or letters are drafted. The date is the
 * backend's `rules_last_checked` (the day the rules catalog was checked against the law).
 */
export function Disclaimer({ lastChecked, advice, variant = "inline", className }: DisclaimerProps) {
  const catalogChecked = useRulesLastChecked();
  const asOf = lastChecked ?? catalogChecked;
  return (
    <div
      className={cn(
        "flex items-start gap-2 text-xs leading-5 text-muted",
        variant === "block" && "border-t border-line pt-3",
        className,
      )}
    >
      <Scale className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <p>
        {asOf ? `Based on the law as of ${formatDate(asOf, { style: "medium" })}. ` : null}Not legal advice. Not reviewed by a lawyer.
        {advice?.length ? (
          <>
            {" "}
            <AdviceLinks advice={advice} />
          </>
        ) : null}
      </p>
    </div>
  );
}
