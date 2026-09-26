import { cn } from "@/lib/utils";
import { GROUNDING_COPY, TONES, copyFor } from "@/lib/copy";
import type { Grounding } from "@/api/types";
import { Tooltip } from "./Tooltip";

export interface GroundingBadgeProps {
  grounding: Grounding;
  /** Page the quote was found on (shown as "· p.2"). */
  page?: number | null;
  /** Compact: icon + short label. */
  compact?: boolean;
  /** Click handler (e.g. scroll to the highlight). Renders a button when set. */
  onClick?: () => void;
  className?: string;
}

const SHORT: Record<Grounding, string> = {
  verified: "In the letter",
  model_read: "Read by AI",
  unverified: "Please check",
  user: "Confirmed",
};

/**
 * Evidence trust label (SPEC §21 wording — never "verified"):
 * verified → "Found in the letter · p.2" · model_read → "Read by AI from the photo" ·
 * unverified → "Couldn't find this — please check" · user → "Confirmed by you".
 */
export function GroundingBadge({ grounding, page, compact, onClick, className }: GroundingBadgeProps) {
  const c = copyFor(GROUNDING_COPY, grounding);
  const t = TONES[c.tone];
  const Icon = c.icon;
  const label = compact ? SHORT[grounding] ?? c.label : c.label;
  const withPage = page && (grounding === "verified" || grounding === "model_read") ? `${label} · p.${page}` : label;
  const cls = cn(
    "inline-flex max-w-full items-center gap-1.5 rounded-full px-2 py-[3px] text-[12px] font-medium leading-4",
    t.soft,
    t.text,
    onClick && "cursor-pointer transition-[filter] hover:brightness-95 dark:hover:brightness-110",
    className,
  );
  const inner = (
    <>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">{withPage}</span>
    </>
  );
  const el = onClick ? (
    <button type="button" className={cls} onClick={onClick}>
      {inner}
    </button>
  ) : (
    <span className={cls} tabIndex={c.hint ? 0 : undefined}>
      {inner}
    </span>
  );
  return c.hint ? <Tooltip content={c.hint}>{el}</Tooltip> : el;
}
