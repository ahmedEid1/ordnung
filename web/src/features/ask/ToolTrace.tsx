import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Check, ChevronRight } from "lucide-react";
import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/utils";
import type { ToolStep } from "./stream";
import { Wrench } from "lucide-react";
import { TOOL_ICONS, toolLabel, toolResultText, unbreakDates, type TitleLookup } from "./tools";

/**
 * One step: its icon, its label and, once done, its result. The label wraps at every width (a cut-off
 * "until 1…" hides the date); the result goes on a muted second line up to `lg`, and follows the label on
 * its line from `lg` up when there is room. The icon and the done mark sit at the label's first line.
 */
function StepChip({ step, titleOf }: { step: ToolStep; titleOf?: TitleLookup }) {
  const Icon = TOOL_ICONS[step.name] ?? Wrench;
  const result = step.done && step.result ? unbreakDates(toolResultText(step.result)) : null;
  const label = toolLabel(step, titleOf);
  return (
    <>
      <span
        className={cn(
          "grid size-6 shrink-0 place-items-center rounded-md border transition-colors",
          step.done ? "border-line bg-surface text-muted" : "border-accent/30 bg-accent-soft text-accent",
        )}
        aria-hidden
      >
        <Icon className="size-3.5" />
      </span>
      {/* the label wraps at every width — a date range's end or a letter's title is never cut off, and no
          hover-only title holds what keyboard and touch can't reach (review round 3 of phase 2); from lg up
          the result follows on the same line when there is room */}
      <span className="flex min-w-0 flex-col pt-0.5 lg:flex-row lg:flex-wrap lg:items-baseline lg:gap-x-2">
        <span
          data-testid="tool-step-label"
          className={cn("min-w-0 break-words", step.done ? "text-ink/80" : "text-ink")}
        >
          {unbreakDates(label)}
        </span>
        {result ? (
          <span
            data-testid="tool-step-result"
            className="flex min-w-0 items-center gap-1 text-[12px] leading-4 text-muted sm:text-[13px] sm:leading-5 lg:shrink-0"
          >
            <Check className="size-3 shrink-0 text-ok" aria-hidden />
            <span className="min-w-0 break-words">{result}</span>
          </span>
        ) : null}
      </span>
      {step.done ? (
        result ? null : (
          <>
            <Check className="mt-[5px] size-3.5 shrink-0 text-ok" aria-hidden />
            <span className="sr-only">(done)</span>
          </>
        )
      ) : (
        <>
          <Spinner className="mt-[5px] size-3.5 shrink-0 text-accent" />
          <span className="sr-only">(working)</span>
        </>
      )}
    </>
  );
}

/**
 * The visible tool trace ("Searched your letters for "Kündigung"", "Opened …"): live while the
 * answer streams, folded into "Looked at 3 things" once it is done.
 */
export function ToolTrace({ steps, live, titleOf }: { steps: ToolStep[]; live: boolean; titleOf?: TitleLookup }) {
  const [open, setOpen] = useState(false);
  const reduce = useReducedMotion();
  if (!steps.length) return null;
  const expanded = live || open;
  const n = steps.length;
  return (
    <div className="mb-3">
      {!live ? (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="-ml-1 inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-[12.5px] font-medium text-muted transition-colors hover:text-ink"
        >
          <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} aria-hidden />
          {n === 1 ? "Looked at 1 thing" : `Looked at ${n} things`} in your records
        </button>
      ) : null}
      <AnimatePresence initial={false}>
        {expanded ? (
          <motion.ol
            key="steps"
            aria-label="What Ordnung looked at"
            initial={reduce ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, height: 0 }}
            transition={{ duration: 0.18 }}
            className={cn("space-y-1.5 overflow-hidden", !live && "mt-2 border-l border-line pl-3")}
          >
            {steps.map((s, i) => (
              <motion.li
                key={i}
                initial={reduce ? false : { opacity: 0, x: -4 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.2 }}
                // the icon at the label's first line at every width: centred beside a wrapped label it sat mid-block
                // (review round 4 of phase 2)
                className="flex min-w-0 items-start gap-2 text-[13px] leading-5"
              >
                <StepChip step={s} titleOf={titleOf} />
              </motion.li>
            ))}
          </motion.ol>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
