import { Scale, ExternalLink } from "lucide-react";
import { useRulesLastChecked } from "@/api/hooks";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/format";

export interface AdviceLink {
  label: string;
  href: string;
}

/** Independent advice for high-stakes areas (SPEC §21). */
export const ADVICE_LINKS: Record<"residence" | "rent" | "consumer" | "tax" | "fines", AdviceLink[]> = {
  residence: [{ label: "Studierendenwerk advice", href: "https://www.studierendenwerke.de/" }],
  rent: [{ label: "Mieterverein (tenants' association)", href: "https://www.mieterbund.de/" }],
  consumer: [{ label: "Verbraucherzentrale", href: "https://www.verbraucherzentrale.de/" }],
  tax: [{ label: "Lohnsteuerhilfeverein (tax help)", href: "https://www.bvl-verband.de/" }],
  fines: [{ label: "Verbraucherzentrale", href: "https://www.verbraucherzentrale.de/" }],
};

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
        "flex items-start gap-2 text-[12px] leading-5 text-muted",
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
            Unsure? Ask{" "}
            {advice.map((a, i) => (
              <span key={a.href}>
                {i > 0 ? " or " : ""}
                <a href={a.href} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 font-medium text-accent hover:underline">
                  {a.label}
                  <ExternalLink className="size-3" aria-hidden />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              </span>
            ))}
            .
          </>
        ) : null}
      </p>
    </div>
  );
}
