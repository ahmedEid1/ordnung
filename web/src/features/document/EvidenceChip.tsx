/**
 * Grounding chip that doubles as "show me on the page": "Found in the letter · p.2",
 * "Read by AI from the photo", "Couldn't find this — please check", "Confirmed by you".
 * Clicking it selects the fact (the viewer scrolls to the highlight and pulses it).
 *
 * The page number is left out for a one-page letter ("· p.1" says nothing there). Where a whole
 * list shares one grounding, the list says it once and each chip is just its icon (`iconOnly`), a
 * 24 px button with the same words in its tooltip and name (UI audit round 1: seven identical
 * "Read by AI from the photo · p.1" pills on a passport).
 */
import type { Grounding } from "@/api/types";
import { cn } from "@/lib/utils";
import { GROUNDING_COPY, TONES, copyFor } from "@/lib/copy";
import { Tooltip } from "@/components/ui/Tooltip";
import { useEvidence } from "./EvidenceContext";

const SHORT: Record<Grounding, string> = {
  verified: "Found in the letter",
  model_read: "Read by AI from the photo",
  unverified: "Please check",
  user: "Confirmed by you",
};

/** What the chip says: "Found in the letter · p.2" (no page on a one-page letter). */
export function evidenceText(grounding: Grounding, opts: { page?: number | null; pages?: number | null; compact?: boolean } = {}): string {
  const base = opts.compact ? SHORT[grounding] : copyFor(GROUNDING_COPY, grounding).label;
  const showPage = opts.page && (grounding === "verified" || grounding === "model_read") && !(opts.pages === 1);
  return showPage ? `${base} · p.${opts.page}` : base;
}

export function EvidenceChip({
  grounding,
  page,
  pages,
  anchorId,
  what,
  compact,
  iconOnly,
  className,
}: {
  grounding: Grounding;
  page?: number | null;
  /** How many pages the letter has: a one-page letter's chip leaves the page out. */
  pages?: number | null;
  /** Evidence anchor to select on click (renders a button when set). */
  anchorId?: string | null;
  /** What the chip is about, for screen readers ("Refund"). */
  what?: string;
  compact?: boolean;
  /** Only the icon (the list around it says the grounding once); the words move into the tooltip and the name. */
  iconOnly?: boolean;
  className?: string;
}) {
  const { select, hover } = useEvidence();
  const c = copyFor(GROUNDING_COPY, grounding);
  const t = TONES[c.tone];
  const Icon = c.icon;
  const text = evidenceText(grounding, { page, pages, compact });
  const hint = c.hint ? `${c.hint} Click to see it on the page.` : "Show on the page";

  if (iconOnly && anchorId) {
    return (
      <Tooltip content={`${text} — show it on the page`}>
        <button
          type="button"
          onClick={() => select(anchorId)}
          onMouseEnter={() => hover(anchorId)}
          onMouseLeave={() => hover(null)}
          aria-label={`${text} — show${what ? ` “${what}”` : ""} on the page`}
          className={cn(
            "inline-grid size-6 shrink-0 cursor-pointer place-items-center rounded-full align-middle transition-[filter,box-shadow] hover:brightness-95 hover:shadow-[0_0_0_1px_currentColor] dark:hover:brightness-110",
            t.soft,
            t.text,
            className,
          )}
        >
          <Icon className="size-3.5" aria-hidden />
        </button>
      </Tooltip>
    );
  }

  const cls = cn("inline-flex max-w-full items-center gap-1 rounded-full px-2 py-[3px] text-[12px] font-medium leading-4", t.soft, t.text, className);
  const inner = (
    <>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">{text}</span>
    </>
  );
  if (!anchorId) return <span className={cls}>{inner}</span>;
  return (
    <Tooltip content={hint}>
      <button
        type="button"
        onClick={() => select(anchorId)}
        onMouseEnter={() => hover(anchorId)}
        onMouseLeave={() => hover(null)}
        className={cn(cls, "cursor-pointer transition-[filter,box-shadow] hover:brightness-95 hover:shadow-[0_0_0_1px_currentColor] dark:hover:brightness-110")}
      >
        {inner}
        {what ? <span className="sr-only"> — show “{what}” on the page</span> : null}
      </button>
    </Tooltip>
  );
}
