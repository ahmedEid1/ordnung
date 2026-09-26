import { cn } from "@/lib/utils";
import { CONFIDENCE_COPY, TONES, copyFor } from "@/lib/copy";
import type { Confidence } from "@/api/types";

export interface ConfidenceNoteProps {
  confidence: Confidence;
  /** Reasons from the receipt / computation (`warnings`). */
  warnings?: string[];
  /** Hide the note entirely for high confidence without warnings (default true). */
  hideWhenHigh?: boolean;
  className?: string;
}

/**
 * How sure the computed date is, with the reasons. High confidence without warnings renders
 * nothing by default (calm UI); medium/low always explain why.
 */
export function ConfidenceNote({ confidence, warnings = [], hideWhenHigh = true, className }: ConfidenceNoteProps) {
  if (hideWhenHigh && confidence === "high" && warnings.length === 0) return null;
  const c = copyFor(CONFIDENCE_COPY, confidence);
  const t = TONES[c.tone];
  const Icon = c.icon;
  return (
    <div className={cn("rounded-lg px-3 py-2.5 text-[13px] leading-5", t.soft, className)}>
      <div className={cn("flex items-center gap-1.5 font-medium", t.text)}>
        <Icon className="size-4 shrink-0" aria-hidden />
        {c.label}
      </div>
      {warnings.length ? (
        <ul className="mt-1.5 list-disc space-y-0.5 pl-6 text-ink/85 marker:text-muted">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
