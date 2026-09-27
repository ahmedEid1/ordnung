/**
 * Today's one gentle prompt for the weekly session — on Sundays, or when the last one is a week old
 * (the backend decides: `WeeklySession.due`) — with "Start" and "Not now". When no session is due, a
 * quiet link at the foot of Today keeps the session one tap away. No nagging: "Not now" hides it until
 * the next one is due.
 */
import { Link } from "react-router";
import { motion } from "motion/react";
import { CalendarCheck, ChevronRight } from "lucide-react";
import { useWeek, useWeekDismiss } from "@/api/hooks";
import { Button, buttonVariants } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { focusWhenReady } from "@/features/today/focus";
import { fadeUp } from "@/features/today/motion";
import { useFormatDate } from "@/lib/today";
import { cn } from "@/lib/utils";
import { sessionHighlights } from "./steps";

export function WeeklyPrompt() {
  const week = useWeek();
  const dismiss = useWeekDismiss();
  const formatDate = useFormatDate();
  const data = week.data;
  if (!data?.due) return null;
  const highlights = sessionHighlights(data);
  return (
    <motion.section
      variants={fadeUp}
      aria-labelledby="weekly-prompt-title"
      className="rounded-[var(--radius-card)] border border-accent/25 bg-accent-soft/60 p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-surface text-accent shadow-[var(--shadow-card)]" aria-hidden>
          <CalendarCheck className="size-[18px]" />
        </span>
        <div className="min-w-0 flex-1 basis-[16rem]">
          <h2 id="weekly-prompt-title" className="text-[15px] font-semibold leading-6 text-ink">
            Time for your weekly review
          </h2>
          <p className="text-[13.5px] leading-5 text-ink/80">
            About {data.minutes} minutes{highlights.length ? `: ${highlights.join(" · ")}` : "."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/week" className={buttonVariants({ variant: "primary", size: "sm" })}>
            Start
          </Link>
          <Button
            variant="ghost"
            size="sm"
            loading={dismiss.isPending}
            onClick={() =>
              dismiss.mutate(undefined, {
                onSuccess: (after) => {
                  const when = after.next_prompt ? `on ${formatDate(after.next_prompt)}` : "when it is due";
                  toast({ title: "Not now", description: `Today suggests it again ${when} — or open it any time from the foot of this page.` });
                  // the prompt is gone: the focus goes on to the next section, never to the page's top
                  focusWhenReady(() => document.getElementById("coming-up-title"));
                },
              })
            }
          >
            Not now
          </Button>
        </div>
      </div>
    </motion.section>
  );
}

/** The session is always one tap away: a quiet line at the foot of Today when no prompt is showing. */
export function WeeklyLink({ className }: { className?: string }) {
  const week = useWeek();
  const formatDate = useFormatDate();
  const data = week.data;
  if (!data || data.due) return null;
  return (
    <Link
      to="/week"
      className={cn(
        "group inline-flex min-h-8 items-center gap-2 rounded-lg px-2 text-[13.5px] text-muted outline-none transition-colors hover:text-ink focus-visible:ring-2 focus-visible:ring-accent",
        className,
      )}
    >
      <CalendarCheck className="size-4 shrink-0" aria-hidden />
      <span>
        Weekly review{data.last_session ? <span> · last done {formatDate(data.last_session)}</span> : null}
      </span>
      <ChevronRight className="size-4 shrink-0 transition-transform group-hover:translate-x-0.5" aria-hidden />
    </Link>
  );
}
