import { useId, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { addDays, format, parseISO } from "date-fns";
import { AlarmClock, ChevronDown, Lightbulb, PiggyBank, ShieldCheck, TrendingUp, Wallet, X } from "lucide-react";
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
import { focusAfterLeaving, focusWhenReady } from "./focus";
import { ideaActionLabel, ideaHref, payActionFor } from "./helpers";
import { ReadMore } from "./ReadMore";
import { ideaFigure, isFreshIdea, type TodayAction } from "./selection";
import { PayPopover } from "./TopThree";
import { TOUR_TARGETS } from "@/features/tour/steps";
import { RefText } from "@/features/ask/RefText";
import { HISTORY_DAYS } from "@/features/inbox/filters";

const quiet =
  "inline-flex h-8 items-center gap-1.5 rounded-md px-1.5 text-[12.5px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent";

const headingId = (id: string) => `idea-${id}`;

/** What the list does with focus when a card leaves (hidden, snoozed) or comes back (Undo). */
interface IdeaFocus {
  leaving: (id: string) => void;
  returning: (id: string) => void;
}

function IdeaCard({ idea, today, pinned, pay, focus }: { idea: Suggestion; today: string; pinned: boolean; pay: TodayAction | null; focus: IdeaFocus }) {
  const navigate = useNavigate();
  const update = useUpdateSuggestion();
  const figure = ideaFigure(idea);
  const actionLabel = ideaActionLabel(idea, { canPay: Boolean(pay) });
  const href = ideaHref(idea);
  const scam = idea.kind === "scam";
  const fresh = pinned || isFreshIdea(idea, today);
  const titleId = headingId(idea.id);

  const undo = (patch: Parameters<typeof update.mutateAsync>[0]["patch"]) => async () => {
    await update.mutateAsync({ id: idea.id, patch });
    focus.returning(idea.id);
  };

  const snooze = () => {
    const until = format(addDays(parseISO(today), 7), "yyyy-MM-dd");
    update.mutate(
      { id: idea.id, patch: { status: "snoozed", snoozed_until: until } },
      {
        onSuccess: () => {
          focus.leaving(idea.id);
          toast({
            title: `I'll bring this back on ${formatDate(until, { style: "short", today })}`,
            description: idea.title,
            undo: undo({ status: "new", snoozed_until: null }),
          });
        },
      },
    );
  };

  const dismiss = () => {
    update.mutate(
      { id: idea.id, patch: { status: "dismissed" } },
      {
        onSuccess: () => {
          focus.leaving(idea.id);
          toast({
            title: scam ? "Warning removed" : "Idea hidden",
            description: idea.title,
            undo: undo({ status: "new" }),
          });
        },
      },
    );
  };

  const accept = () => {
    if (idea.action?.type === "draft") update.mutate({ id: idea.id, patch: { status: "accepted" } }, { onError: () => undefined });
    if (href) navigate(href);
  };

  return (
    <motion.li layout variants={fadeUp} exit={collapseOut}>
      <article aria-labelledby={titleId} className={cn("card relative overflow-hidden p-4 sm:p-5", scam && "border-danger/40 bg-danger-soft/40")}>
        <div className="flex flex-wrap items-center gap-2">
          <KindBadge ideaKind={idea.kind} />
          {fresh ? (
            <Badge tone="accent" dot>
              New
            </Badge>
          ) : null}
          {/* a date long past is history ("89 days overdue" on a probation end helps nobody) */}
          {/* …and a scam's "pay by" is no deadline of yours */}
          {!scam && idea.due_date && daysUntil(idea.due_date, today) >= -HISTORY_DAYS ? <Countdown date={idea.due_date} className="ml-auto text-[12px]" /> : null}
        </div>
        <h3 id={titleId} data-idea-heading="" className="mt-2.5 text-[15px] font-semibold leading-snug text-ink [overflow-wrap:anywhere]">
          {idea.title}
        </h3>
        <ReadMore className="mt-1.5 text-[13.5px] leading-relaxed text-muted">
          <RefText text={idea.body} />
        </ReadMore>
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
        {pay ? (
          // the same Pay panel as Top 3: transfer details to copy and "Mark as paid"
          <div className="mt-3.5">
            <PayPopover action={pay}>
              <Button size="sm" variant="soft" icon={Wallet} aria-describedby={titleId}>
                {actionLabel}
              </Button>
            </PayPopover>
          </div>
        ) : actionLabel && href ? (
          <Button size="sm" variant={scam ? "danger" : "soft"} onClick={accept} aria-describedby={titleId} className="mt-3.5">
            {actionLabel}
          </Button>
        ) : null}
        <div className="-mx-1.5 mt-3 flex flex-wrap items-center justify-between gap-x-2 border-t border-line pt-2">
          {scam ? (
            // a scam warning is never snoozed or "not relevant": the person checks it with the sender
            <button type="button" onClick={dismiss} disabled={update.isPending} aria-describedby={titleId} className={quiet}>
              <ShieldCheck className="size-3.5" aria-hidden />
              I checked — it's genuine
            </button>
          ) : (
            <>
              <button type="button" onClick={snooze} disabled={update.isPending} aria-describedby={titleId} className={quiet}>
                <AlarmClock className="size-3.5" aria-hidden />
                Remind me in a week
              </button>
              <button type="button" onClick={dismiss} disabled={update.isPending} aria-describedby={titleId} className={quiet}>
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

const ideasCount = (n: number, word = "") => `${n} ${word}${n === 1 ? "Idea" : "Ideas"}`;

/**
 * "Ideas from your secretary": at most three new Ideas with action-named buttons, the money
 * figure (savings or extra cost), "Remind me in a week" and "Not relevant" (both with undo), and
 * "Show N more Ideas" / "Show fewer Ideas". An Idea about a payment opens the same Pay panel as
 * Top 3. Focus follows: to the first new Idea when the list grows, to the card now in the place of
 * one that was hidden, and back to a card brought back with Undo.
 */
export function IdeasSection({
  shown,
  more,
  today,
  pinnedIds,
  actions,
}: {
  shown: Suggestion[];
  more: Suggestion[];
  today: string;
  /** Ideas that came with the new mail (shown first, "New" badge). */
  pinnedIds?: ReadonlySet<string>;
  /** The page's actions (Top 3 and Coming up): an Idea about one of their payments gets its Pay panel. */
  actions?: readonly TodayAction[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [said, setSaid] = useState("");
  const listId = useId();
  const list = useRef<HTMLUListElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const ideas = expanded ? [...shown, ...more] : shown;
  const cardsOnPage = () => Array.from(list.current?.querySelectorAll<HTMLElement>("[data-idea-heading]") ?? []);

  const focus: IdeaFocus = {
    leaving: (id) => focusAfterLeaving(cardsOnPage, headingId(id), "ideas-title"),
    returning: (id) => focusWhenReady(() => document.getElementById(headingId(id))),
  };

  const onToggle = () => {
    if (!expanded) {
      // on to the first new Idea (its heading), once it is there
      const first = more[0]?.id;
      if (first) focusWhenReady(() => document.getElementById(headingId(first)), 1000, { always: true });
      setSaid(`${ideasCount(more.length, "more ")} shown`);
    } else {
      // the button keeps focus; once the extra cards have left, it is brought back into view
      // (the page got shorter above it)
      const until = performance.now() + 3000;
      const tick = () => {
        if (cardsOnPage().length > shown.length && performance.now() < until) return void requestAnimationFrame(tick);
        const r = toggle.current?.getBoundingClientRect();
        if (r && (r.top < 0 || r.bottom > window.innerHeight)) toggle.current?.scrollIntoView?.({ block: "center" });
      };
      requestAnimationFrame(tick);
      setSaid(`Showing ${ideasCount(shown.length)}`);
    }
    setExpanded(!expanded);
  };

  return (
    <motion.section variants={fadeUp} aria-labelledby="ideas-title" data-tour={TOUR_TARGETS.ideas}>
      <SectionHeader id="ideas-title" title="Ideas from your secretary" />
      {ideas.length ? (
        <ul ref={list} id={listId} className="flex flex-col gap-3">
          <AnimatePresence initial={false}>
            {ideas.map((s) => (
              <IdeaCard
                key={s.id}
                idea={s}
                today={today}
                pinned={Boolean(pinnedIds?.has(s.id))}
                // (never for a possible scam: its "payment" is what to check first)
                pay={s.kind === "scam" ? null : payActionFor(s, actions)}
                focus={focus}
              />
            ))}
          </AnimatePresence>
        </ul>
      ) : (
        <p className="card px-5 py-6 text-center text-base leading-relaxed text-muted">
          No new Ideas. Your secretary suggests things as letters arrive — you'll see them here.
        </p>
      )}
      {more.length ? (
        <Button
          ref={toggle}
          variant="ghost"
          size="sm"
          iconRight={ChevronDown}
          aria-expanded={expanded}
          aria-controls={listId}
          className={cn("mt-2 [&_svg]:transition-transform motion-reduce:[&_svg]:transition-none", expanded && "[&_svg]:rotate-180")}
          onClick={onToggle}
        >
          {expanded ? "Show fewer Ideas" : `Show ${ideasCount(more.length, "more ")}`}
        </Button>
      ) : null}
      {/* what the button did, said once (the list itself is not a live region: ten cards read out is too much) */}
      <p className="sr-only" aria-live="polite">
        {said}
      </p>
    </motion.section>
  );
}
