import { Fragment } from "react";
import { Scale, ExternalLink } from "lucide-react";
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
