/**
 * Grounding chip that doubles as "show me on the page": "Found in the letter · p.2",
 * "Read by AI from the photo", "Couldn't find this — please check", "Confirmed by you".
 * Clicking it selects the fact (the viewer scrolls to the highlight and pulses it).
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

export function EvidenceChip({
  grounding,
  page,
  anchorId,
  what,
  compact,
  className,
}: {
  grounding: Grounding;
  page?: number | null;
  /** Evidence anchor to select on click (renders a button when set). */
  anchorId?: string | null;
  /** What the chip is about, for screen readers ("Refund"). */
  what?: string;
  compact?: boolean;
  className?: string;
}) {
  const { select, hover } = useEvidence();
  const c = copyFor(GROUNDING_COPY, grounding);
  const t = TONES[c.tone];
  const Icon = c.icon;
  const base = compact ? SHORT[grounding] : c.label;
  const text = page && (grounding === "verified" || grounding === "model_read") ? `${base} · p.${page}` : base;
  const cls = cn(
    "inline-flex max-w-full items-center gap-1 rounded-full px-2 py-[3px] text-[11.5px] font-medium leading-4",
    t.soft,
    t.text,
    className,
  );
  const inner = (
    <>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">{text}</span>
    </>
  );
  if (!anchorId) return <span className={cls}>{inner}</span>;
  return (
    <Tooltip content={c.hint ? `${c.hint} Click to see it on the page.` : "Show on the page"}>
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
