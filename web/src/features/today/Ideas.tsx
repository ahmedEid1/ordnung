import { useState } from "react";
import { useNavigate } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { addDays, format, parseISO } from "date-fns";
import { AlarmClock, ChevronDown, Lightbulb, PiggyBank, ShieldCheck, TrendingUp, X } from "lucide-react";
import { useUpdateSuggestion } from "@/api/hooks";
import type { Suggestion } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { KindBadge } from "@/components/ui/KindBadge";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { toast } from "@/components/ui/Toast";
import { daysUntil, formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { collapseOut, fadeUp } from "./motion";
import { ideaActionLabel, ideaHref } from "./helpers";
import { ideaFigure, isFreshIdea } from "./selection";
import { TOUR_TARGETS } from "@/features/tour/steps";
import { RefText } from "@/features/ask/RefText";
import { HISTORY_DAYS } from "@/features/inbox/filters";

const quiet =
  "inline-flex h-8 items-center gap-1.5 rounded-md px-1.5 text-[12.5px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent";

function IdeaCard({ idea, today, pinned }: { idea: Suggestion; today: string; pinned: boolean }) {
  const navigate = useNavigate();
  const update = useUpdateSuggestion();
  const figure = ideaFigure(idea);
  const actionLabel = ideaActionLabel(idea);
  const href = ideaHref(idea);
  const scam = idea.kind === "scam";
  const fresh = pinned || isFreshIdea(idea, today);

  const snooze = () => {
    const until = format(addDays(parseISO(today), 7), "yyyy-MM-dd");
    update.mutate(
      { id: idea.id, patch: { status: "snoozed", snoozed_until: until } },
      {
        onSuccess: () =>
          toast({
            title: `I'll bring this back on ${formatDate(until, { style: "short", today })}`,
            description: idea.title,
            undo: async () => {
              await update.mutateAsync({ id: idea.id, patch: { status: "new", snoozed_until: null } });
            },
          }),
      },
    );
  };

  const dismiss = () => {
    update.mutate(
      { id: idea.id, patch: { status: "dismissed" } },
      {
        onSuccess: () =>
          toast({
            title: scam ? "Warning removed" : "Idea hidden",
            description: idea.title,
            undo: async () => {
              await update.mutateAsync({ id: idea.id, patch: { status: "new" } });
            },
          }),
      },
    );
  };

  const accept = () => {
    if (idea.action?.type === "draft") update.mutate({ id: idea.id, patch: { status: "accepted" } }, { onError: () => undefined });
    if (href) navigate(href);
  };

  return (
    <motion.li layout variants={fadeUp} exit={collapseOut}>
      <article
        aria-labelledby={`idea-${idea.id}`}
        className={cn("card relative overflow-hidden p-4 sm:p-5", scam && "border-danger/40 bg-danger-soft/40")}
      >
        <div className="flex flex-wrap items-center gap-2">
          <KindBadge ideaKind={idea.kind} />
          {fresh ? (
            <Badge tone="accent" dot>
              {pinned ? "New" : "New today"}
            </Badge>
          ) : null}
          {/* a date long past is history ("89 days overdue" on a probation end helps nobody) */}
          {/* …and a scam's "pay by" is no deadline of yours */}
          {!scam && idea.due_date && daysUntil(idea.due_date, today) >= -HISTORY_DAYS ? <Countdown date={idea.due_date} className="ml-auto text-[12px]" /> : null}
        </div>
        <h3 id={`idea-${idea.id}`} className="mt-2.5 text-[15px] font-semibold leading-snug text-ink">
          {idea.title}
        </h3>
        <p className="mt-1.5 line-clamp-3 text-[13.5px] leading-relaxed text-muted">
          <RefText text={idea.body} />
        </p>
        {figure ? (
          <p
            className={cn(
              "mt-3 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-semibold tabular-nums",
              figure.tone === "ok" ? "bg-ok-soft text-ok-ink" : "bg-warn-soft text-warn-ink",
            )}
          >
            {figure.tone === "ok" ? <PiggyBank className="size-4" aria-hidden /> : <TrendingUp className="size-4" aria-hidden />}
            {figure.label}
          </p>
        ) : null}
        {idea.rationale ? (
          <p className="mt-2.5 flex items-start gap-1.5 text-[12px] leading-5 text-muted">
            <Lightbulb className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span>
              <span className="sr-only">Why you're seeing this: </span>
              <RefText text={idea.rationale} />
            </span>
          </p>
        ) : null}
        {actionLabel && href ? (
          <Button size="sm" variant={scam ? "danger" : "soft"} onClick={accept} className="mt-3.5">
            {actionLabel}
          </Button>
        ) : null}
        <div className="-mx-1.5 mt-3 flex flex-wrap items-center justify-between gap-x-2 border-t border-line pt-2">
          {scam ? (
            // a scam warning is never snoozed or "not relevant": the person checks it with the sender
            <button type="button" onClick={dismiss} disabled={update.isPending} className={quiet}>
              <ShieldCheck className="size-3.5" aria-hidden />
              I checked — it's genuine
            </button>
          ) : (
            <>
              <button type="button" onClick={snooze} disabled={update.isPending} className={quiet}>
                <AlarmClock className="size-3.5" aria-hidden />
                Remind me in a week
              </button>
              <button type="button" onClick={dismiss} disabled={update.isPending} className={quiet}>
                <X className="size-3.5" aria-hidden />
                Not relevant
              </button>
            </>
          )}
        </div>
      </article>
    </motion.li>
  );
}

/**
 * "Ideas from your secretary": at most three new Ideas with action-named buttons, the money
 * figure (savings or extra cost), "Remind me in a week" and "Not relevant" (both with undo).
 */
export function IdeasSection({
  shown,
  more,
  today,
  pinnedIds,
}: {
  shown: Suggestion[];
  more: Suggestion[];
  today: string;
  /** Ideas that came with the new mail (shown first, "New" badge). */
  pinnedIds?: ReadonlySet<string>;
}) {
  const [expanded, setExpanded] = useState(false);
  const list = expanded ? [...shown, ...more] : shown;
  return (
    <motion.section variants={fadeUp} aria-labelledby="ideas-title" data-tour={TOUR_TARGETS.ideas}>
      <SectionHeader id="ideas-title" title="Ideas from your secretary" icon={Lightbulb} />
      {list.length ? (
        <ul className="flex flex-col gap-3" aria-live="polite">
          <AnimatePresence initial={false}>
            {list.map((s) => (
              <IdeaCard key={s.id} idea={s} today={today} pinned={Boolean(pinnedIds?.has(s.id))} />
            ))}
          </AnimatePresence>
        </ul>
      ) : (
        <p className="card px-5 py-6 text-center text-sm leading-relaxed text-muted">
          No new Ideas. Your secretary suggests things as letters arrive — you'll see them here.
        </p>
      )}
      {more.length && !expanded ? (
        <Button variant="ghost" size="sm" iconRight={ChevronDown} className="mt-2" onClick={() => setExpanded(true)}>
          {more.length === 1 ? "Show 1 more Idea" : `Show ${more.length} more Ideas`}
        </Button>
      ) : null}
    </motion.section>
  );
}
