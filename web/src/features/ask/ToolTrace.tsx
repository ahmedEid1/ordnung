import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Check, ChevronRight } from "lucide-react";
import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/utils";
import type { ToolStep } from "./stream";
import { Wrench } from "lucide-react";
import { TOOL_ICONS, toolLabel, toolResultText, unbreakDates, type TitleLookup } from "./tools";

/**
 * One step: its icon, its label and, once done, its result. On a phone the label wraps (a cut-off
 * "until 1…" hides the date) and the result goes on a muted second line; from `sm` up both share one
 * line and the label is truncated instead.
 */
function StepChip({ step, titleOf }: { step: ToolStep; titleOf?: TitleLookup }) {
  const Icon = TOOL_ICONS[step.name] ?? Wrench;
  const result = step.done && step.result ? unbreakDates(toolResultText(step.result)) : null;
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
      <span className="flex min-w-0 flex-col pt-0.5 sm:flex-row sm:items-center sm:gap-2 sm:pt-0">
        <span
          data-testid="tool-step-label"
          className={cn("min-w-0 break-words sm:truncate", step.done ? "text-ink/80" : "text-ink")}
        >
          {unbreakDates(toolLabel(step, titleOf))}
        </span>
        {result ? (
          <span
            data-testid="tool-step-result"
            className="flex min-w-0 items-center gap-1 text-[12px] leading-4 text-muted sm:shrink-0 sm:text-[13px] sm:leading-5"
          >
            <Check className="size-3 shrink-0 text-ok" aria-hidden />
            <span className="min-w-0 break-words">{result}</span>
          </span>
        ) : null}
      </span>
      {step.done ? (
        result ? null : (
          <>
            <Check className="mt-[5px] size-3.5 shrink-0 text-ok sm:mt-0" aria-hidden />
            <span className="sr-only">(done)</span>
          </>
        )
      ) : (
        <>
          <Spinner className="mt-[5px] size-3.5 shrink-0 text-accent sm:mt-0" />
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
                className="flex min-w-0 items-start gap-2 text-[13px] leading-5 sm:items-center"
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
