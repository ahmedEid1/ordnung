/**
 * The weekly review: the guided weekly admin session (`GET /api/week`, `ordnung/secretary/week.py`) —
 * short steps, one at a time (seven, and "Act now" first when something is overdue or due today), then
 * "All clear until …" ("for today" when the next day to act is tomorrow), "N things to do today" or "N
 * things are overdue". Nothing is paid, sent or closed for the person: each row links to where they act
 * (Pay and Confirm right here). "Finish" remembers the review. One name everywhere — "Weekly review" —
 * on Today, the page, its ending and its messages. URL state: `?step=now|new|check|pay|post|waiting|decide|file`.
 */
import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ArrowLeft, ArrowRight, Check, CircleCheck, Plus, Sparkles, TriangleAlert } from "lucide-react";
import { useDocuments, useWeek, useWeekDone } from "@/api/hooks";
import type { WeekEntry, WeekStep, WeeklySession } from "@/api/types";
import { useAddLetters } from "@/components/shell/AddLetters";
import { PageHeader } from "@/components/shell/Page";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Countdown } from "@/components/ui/Countdown";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EmptyArt, EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { Money } from "@/components/ui/Money";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { Stepper } from "@/components/ui/Stepper";
import { daysUntil, formatMoney, glueText } from "@/lib/format";
import { useFormatDate, useTodayISO } from "@/lib/today";
import { cn, plural, prefersReducedMotion } from "@/lib/utils";
import { STEP_META, WEEKLY_REVIEW, entryHref, stepCount, type StepId } from "./steps";
import { WeekEntryRow } from "./WeekEntryRow";
import { useStickyError } from "@/lib/hooks";

/** The header's line: how long, not how many steps — "Act now" comes and goes (the card says "Step 1 of 8"). */
export const describeSession = (minutes = 10) => `About ${minutes} minutes, one short step at a time through your paperwork. Nothing is paid, sent or closed for you.`;
/** The step list beside the step once the page is wide enough (measured on the page, not the window). */
const LAYOUT = "grid grid-cols-1 items-start gap-6 @[52rem]:grid-cols-[15rem_minmax(0,1fr)]";

function StepList({ steps, current, visited, onPick }: { steps: WeekStep[]; current: number; visited: ReadonlySet<StepId>; onPick: (i: number) => void }) {
  return (
    <nav aria-label="Steps of the review" className="hidden @[52rem]:block @[52rem]:sticky @[52rem]:top-20">
      <ol className="flex flex-col gap-1">
        {steps.map((step, i) => {
          const meta = STEP_META[step.id];
          const count = stepCount(step);
          const active = i === current;
          const seen = visited.has(step.id) && !active;
          const Icon = meta.icon;
          return (
            <li key={step.id}>
              <button
                type="button"
                onClick={() => onPick(i)}
                aria-current={active ? "step" : undefined}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent",
                  active ? "bg-surface text-ink shadow-[var(--shadow-card)] ring-1 ring-line" : "text-muted hover:bg-surface-3/60 hover:text-ink",
                )}
              >
                <span
                  className={cn(
                    "grid size-7 shrink-0 place-items-center rounded-full text-[12px] font-semibold",
                    seen ? "bg-ok-soft text-ok-ink" : active ? "bg-accent text-on-accent" : "bg-surface-2 text-muted",
                  )}
                  aria-hidden
                >
                  {seen ? <Check className="size-3.5" /> : <Icon className="size-3.5" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13.5px] font-medium leading-5">{step.title}</span>
                  <span className="block text-[12px] leading-4 text-muted">{count ? `${count} to look at` : "Nothing this week"}</span>
                </span>
                {seen ? <span className="sr-only">(looked at)</span> : null}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/**
 * After Next, Back or a pick, the new step shows from the top of the steps — the phone's stepper and the
 * card's "Step n of m" clear of the sticky top bar (`scroll-padding-top`) — when that top is hidden under
 * the bar or the new heading is below the fold; otherwise nothing moves.
 */
function revealStep(heading: HTMLElement): void {
  // the top of the steps (`data-week-steps`): the phone's stepper, else the step list and the card side by side
  const top = heading.closest<HTMLElement>("[data-week-steps]") ?? heading;
  const clear = Number.parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
  if (top.getBoundingClientRect().top >= clear - 1 && heading.getBoundingClientRect().bottom <= window.innerHeight) return;
  top.scrollIntoView?.({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
}

function StepPanel({ step, index, total, focusOnMount = false }: { step: WeekStep; index: number; total: number; focusOnMount?: boolean }) {
  const last = index === total - 1;
  const meta = STEP_META[step.id];
  const headingRef = useRef<HTMLHeadingElement>(null);
  const first = useRef(!focusOnMount);
  // moving to another step takes the focus to its heading (not on the first render: the page is new —
  // unless the person came back from the ending, whose card this one replaces)
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const heading = headingRef.current;
    if (!heading) return;
    heading.focus({ preventScroll: true });
    revealStep(heading);
  }, [step.id]);
  const transfers = step.id === "pay" && step.total !== null;
  return (
    <Card as="section" padding="lg" aria-labelledby={`week-step-${step.id}`}>
      <p className="eyebrow">
        Step {index + 1} of {total}
      </p>
      <h2 id={`week-step-${step.id}`} ref={headingRef} tabIndex={-1} className="display mt-1 text-[24px] font-semibold leading-tight text-ink outline-none">
        {step.title}
      </h2>
      <p className="mt-1.5 text-[14.5px] leading-relaxed text-muted">{step.summary}</p>
      {transfers ? (
        <p className="mt-3 flex flex-wrap items-baseline gap-x-2 text-[14px] text-muted">
          To transfer this week:
          <Money amount={step.total} className="display text-[22px] font-semibold text-ink" />
          {Object.entries(step.total_other_currencies).map(([code, amount]) => (
            <span key={code} className="whitespace-nowrap font-semibold text-ink">
              + {formatMoney(amount, { currency: code })}
            </span>
          ))}
        </p>
      ) : null}
      {step.entries.length ? (
        <ul className="mt-3 divide-y divide-line border-t border-line">
          {step.entries.map((entry) => (
            <li key={entry.key}>
              <WeekEntryRow entry={entry} step={step.id} />
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-4 flex items-center gap-3 rounded-lg bg-ok-soft/60 px-3 py-3 text-[14px] text-ok-ink">
          <CircleCheck className="size-5 shrink-0" aria-hidden />
          {last ? "Nothing here this week — you're done: press Finish." : "Nothing here this week — on to the next step."}
        </div>
      )}
      {step.more || (meta.more.always && step.entries.length) ? (
        <p className="mt-3 text-[13.5px] text-muted">
          {step.more ? <>And {step.more} more. </> : null}
          <Link to={meta.more.to} className="-my-0.5 inline-block rounded py-0.5 font-medium leading-5 text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent">
            {meta.more.label}
          </Link>
        </p>
      ) : null}
    </Card>
  );
}

/** "Today suggests the next one on Sun 4 Oct" — the day the prompt policy names. */
export function nextPromptText(week: Pick<WeeklySession, "next_prompt">, formatDate: (d: string) => string): string {
  return week.next_prompt ? `Today suggests the next one on ${formatDate(week.next_prompt)}` : "Today suggests the next one when it is due";
}

/** Rows that are things to do today (not overdue; not an event, a letter added or something done). */
const TODAY_ROLES = new Set<NonNullable<WeekEntry["date_role"]>>(["due", "by", "on", "send_by", "transfer_by", "pay_by", "act_today", "at_appointment", "decide_by", "reply_by"]);
/** What the session's overdue count covers: the rows the server marks `overdue` (`week.py`, "The ending") —
 * to-dos past their due date, letters to send past the day to arrive by, and Waiting for entries past their
 * day — never Compare with the letter, which lists a to-do again beside its own step. */
export const isCountedOverdue = (entry: WeekEntry, step: WeekStep): boolean => entry.overdue && step.id !== "check";

export const isCountedToday = (entry: WeekEntry, step: WeekStep, today: string): boolean =>
  !entry.overdue &&
  entry.date === today &&
  entry.date_role !== null &&
  TODAY_ROLES.has(entry.date_role) &&
  (entry.ref.type === "item" || entry.ref.type === "contract") &&
  step.id !== "check";

/** A letter row Ordnung has not read: waiting from the watched folder, being read, or that couldn't be read. */
export const isUnreadRow = (entry: WeekEntry): boolean =>
  entry.ref.type === "document" && ["held", "queued", "processing", "failed"].includes(entry.status ?? "");

/** How many letters wait from the watched folder or couldn't be read — what Today counts as not read. */
function useUnreadCount(): number {
  const held = useDocuments({ status: "held" });
  const failed = useDocuments({ status: "failed" });
  return (held.data?.length ?? 0) + (failed.data?.length ?? 0);
}

/** The steps holding rows that match, with how many each holds (in the session's order). */
export function stepsWith(week: Pick<WeeklySession, "steps">, match: (entry: WeekEntry, step: WeekStep) => boolean): { step: WeekStep; count: number }[] {
  return week.steps.map((step) => ({ step, count: step.entries.filter((entry) => match(entry, step)).length })).filter((found) => found.count > 0);
}

/** "See them" (one step) or "See them: Act now (3) · Pay this week (2)" — a way to each step that holds them. */
function StepLinks({ found, many, onShow }: { found: { step: WeekStep; count: number }[]; many: boolean; onShow: (step: StepId) => void }) {
  const link = "inline min-h-6 rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent";
  const [only] = found;
  if (!only) return null;
  if (found.length === 1) {
    return (
      <button type="button" onClick={() => onShow(only.step.id)} className={link}>
        See {many ? "them" : "it"}
      </button>
    );
  }
  return (
    <>
      See them:{" "}
      {found.map(({ step, count }, i) => (
        <Fragment key={step.id}>
          {i ? <span aria-hidden>{"\u00a0· "}</span> : null}
          <button type="button" onClick={() => onShow(step.id)} className={cn(link, "whitespace-nowrap")}>
            {step.title} ({count})
          </button>
        </Fragment>
      ))}
    </>
  );
}

function AllClear({ week, unread, onShow }: { week: WeeklySession; unread: number; onShow: (step: StepId) => void }) {
  const formatDate = useFormatDate();
  const todayISO = useTodayISO();
  const next = week.next_deadline;
  const heading = useRef<HTMLHeadingElement>(null);
  // the card replaces the step the person finished: the focus (and a screen reader) goes to it
  useEffect(() => heading.current?.focus(), []);
  const overdue = week.overdue;
  const today = !overdue && Boolean(next?.date && next.date <= week.today);
  // the backend counts every day to act that is today (`due_today`); the next one is always among them
  const todayCount = today ? Math.max(1, week.due_today) : 0;
  // letters from the watched folder and letters that couldn't be read (`unread`) ask for who knows what: never
  // "All clear" while there are any — as on Today (UX U2), which counts them the same way
  const title = overdue
    ? `${overdue} ${overdue === 1 ? "thing is" : "things are"} overdue`
    : today
      ? todayCount === 1
        ? "One thing to do today"
        : `${todayCount} things to do today`
      : unread
        ? "Nothing due from the letters that were read"
        : next?.date
          ? // "until tomorrow" beside a red "tomorrow" is no all-clear: only today is
            daysUntil(next.date, todayISO) <= 1
            ? "All clear for today"
            : `All clear until ${formatDate(next.date)}`
          : "All clear";
  const unreadSteps = unread ? stepsWith(week, (entry, step) => step.id === "new" && isUnreadRow(entry)) : [];
  const overdueSteps = overdue ? stepsWith(week, isCountedOverdue) : [];
  const todaySteps = todayCount > 1 ? stepsWith(week, (e, step) => isCountedToday(e, step, week.today)) : [];
  return (
    <Card as="section" padding="lg" aria-labelledby="week-done-title" className="flex flex-col items-center text-center">
      {overdue ? (
        <span className="mb-3 grid size-14 place-items-center rounded-full bg-danger-soft text-danger-ink" aria-hidden>
          <TriangleAlert className="size-7" />
        </span>
      ) : (
        // the tick is for "All clear": a day with something to do, or letters not read, show the calendar
        <EmptyArt kind={today || unread ? "calendar" : "clear"} className="mb-3" />
      )}
      <h2 id="week-done-title" ref={heading} tabIndex={-1} className="display text-[26px] font-semibold leading-tight text-ink outline-none">
        {title}
      </h2>
      {overdue ? (
        <p className="mt-2 max-w-md text-[14.5px] leading-relaxed text-muted">
          {overdue === 1 ? "Its date has passed: act on it first" : "Their dates have passed: act on them first"}, or contact the sender if you
          can't. <StepLinks found={overdueSteps} many={overdue > 1} onShow={onShow} />
        </p>
      ) : null}
      {unread ? (
        <p className="mt-2 max-w-md text-[14.5px] leading-relaxed text-muted">
          {plural(unread, "letter")} {unread === 1 ? "isn't" : "aren't"} read yet: Ordnung can't tell what {unread === 1 ? "it asks" : "they ask"}{" "}
          until {unread === 1 ? "it is" : "they are"}. <StepLinks found={unreadSteps} many={unread > 1} onShow={onShow} />
        </p>
      ) : null}
      {next?.date ? (
        <p className="mt-2 max-w-md text-[14.5px] leading-relaxed text-muted">
          {todayCount > 1 ? "First:" : "Next:"}{" "}
          <Link to={entryHref(next)} className="rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent [overflow-wrap:anywhere]">
            {glueText(next.title)}
          </Link>
          <span aria-hidden>{"\u00a0·"}</span> <Countdown date={next.date} className="text-[14.5px]" />
          {todaySteps.length ? (
            <span className="block">
              <StepLinks found={todaySteps} many onShow={onShow} />
            </span>
          ) : null}
        </p>
      ) : !overdue ? (
        <p className="mt-2 max-w-md text-[14.5px] leading-relaxed text-muted">Nothing is due from today on.</p>
      ) : null}
      <p className="mt-2 text-[13.5px] text-muted">Review saved — {nextPromptText(week, (d) => formatDate(d))}.</p>
      <Link to="/" className={cn(buttonVariants({ variant: "primary" }), "mt-5")}>
        Back to Today
      </Link>
    </Card>
  );
}

/** Every step is empty: a first run (no letters yet) or a quiet week. */
function NothingToReview({ week }: { week: WeeklySession }) {
  const { openPicker, uploading } = useAddLetters();
  const formatDate = useFormatDate();
  const next = week.next_deadline;
  if (!week.last_session && !next) {
    return (
      <EmptyState
        illustration="letter"
        title="Nothing to review yet"
        description="Add your letters: each week this review walks you through what they ask of you — new mail, payments, replies and decisions — in about 10 minutes."
        action={
          <>
            <Button variant="primary" icon={Plus} onClick={openPicker} loading={uploading}>
              Add letters
            </Button>
            <Link to="/" className={buttonVariants({ variant: "secondary" })}>
              Back to Today
            </Link>
          </>
        }
      />
    );
  }
  return (
    <EmptyState
      illustration="clear"
      title="Nothing to review this week"
      description={
        next?.date
          ? `No new letters, nothing to check, pay, post or decide. Next: ${next.title} on ${formatDate(next.date)}.`
          : "No new letters, nothing to check, pay, post or decide."
      }
      action={
        <Link to="/" className={buttonVariants({ variant: "primary" })}>
          Back to Today
        </Link>
      }
    />
  );
}

function WeekSkeleton() {
  return (
    <div aria-busy="true" className="@container">
      <LoadingLabel>Loading your week…</LoadingLabel>
      <div className={LAYOUT} aria-hidden>
        <div className="hidden flex-col gap-2 @[52rem]:flex">
          {[0, 1, 2, 3, 4, 5, 6].map((i) => (
            <Skeleton key={i} className="h-12 w-full rounded-lg" />
          ))}
        </div>
        <div className="card p-5 sm:p-7">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-3 h-7 w-56" />
          <SkeletonText lines={4} className="mt-5" />
        </div>
      </div>
    </div>
  );
}

export function WeekView() {
  const q = useWeek();
  const done = useWeekDone();
  // loaded with the steps, so the ending says it from its first word
  const unread = useUnreadCount();
  const formatDate = useFormatDate();
  const [params, setParams] = useSearchParams();
  const [visited, setVisited] = useState<Set<StepId>>(() => new Set());
  const [finished, setFinished] = useState(false);
  // back from the ending ("See them"): the step's heading takes the focus the ending's card had
  const [returned, setReturned] = useState(false);

  const lastError = useStickyError(q.error, Boolean(q.data));
  const failed = !q.data && (q.isError || Boolean(lastError));

  const week = q.data;
  const steps = week?.steps ?? [];
  const wanted = params.get("step");
  const found = steps.findIndex((s) => s.id === wanted);
  const index = found >= 0 ? found : 0;
  const step = steps[index];

  const go = (i: number) => {
    if (step) setVisited((v) => new Set(v).add(step.id));
    const next = steps[i];
    if (!next) return;
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (i === 0) p.delete("step");
        else p.set("step", next.id);
        return p;
      },
      { replace: true, preventScrollReset: true },
    );
  };

  const finish = () => done.mutate(undefined, { onSuccess: () => setFinished(true) });

  const header = (
    <PageHeader
      eyebrow={week ? formatDate(week.today, { style: "long", withYear: "never" }) : undefined}
      title={WEEKLY_REVIEW}
      description={
        <>
          {describeSession(week?.minutes)}
          {week?.last_session ? <span className="block text-[13.5px]">Last review: {formatDate(week.last_session)}.</span> : null}
        </>
      }
    />
  );

  if (failed) {
    return (
      <>
        {header}
        <LoadError what="your week" error={q.error ?? lastError} onRetry={() => void q.refetch()} retrying={q.isFetching} />
      </>
    );
  }
  if (!week || !step) {
    return (
      <>
        {header}
        <WeekSkeleton />
      </>
    );
  }
  if (finished) {
    return (
      <>
        {header}
        <AllClear
          week={week}
          unread={unread}
          onShow={(id) => {
            setFinished(false);
            setReturned(true);
            go(steps.findIndex((s) => s.id === id));
          }}
        />
        <Disclaimer variant="block" className="mt-8" />
      </>
    );
  }
  if (week.overdue === 0 && steps.every((s) => stepCount(s) === 0)) {
    return (
      <>
        {header}
        <NothingToReview week={week} />
        {week.next_deadline ? <Disclaimer variant="block" className="mt-8" /> : null}
      </>
    );
  }

  const last = index === steps.length - 1;
  const nextStep = steps[index + 1];
  return (
    <>
      {header}
      <div className="@container" data-week-steps>
        <div className="mb-5 @[52rem]:hidden">
          {/* ticks only on the steps looked at (as the step list beside it), and any step a tap away; the card
              says "Step n of m". A name under every dot — on a phone over two lines — since the dots are the
              phone's way between the steps. */}
          <Stepper
            steps={steps.map((s) => ({ id: s.id, label: s.title, short: STEP_META[s.id].short }))}
            current={index}
            doneIds={visited}
            labels="all"
            fallback="stagger"
            size="sm"
            label="Steps of the review"
            onPick={go}
          />
        </div>
        <div className={LAYOUT}>
          <StepList steps={steps} current={index} visited={visited} onPick={go} />
          <div className="flex min-w-0 flex-col gap-4">
            <StepPanel step={step} index={index} total={steps.length} focusOnMount={returned} />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Button variant="ghost" icon={ArrowLeft} onClick={() => go(index - 1)} disabled={index === 0}>
                Back
              </Button>
              {last ? (
                <Button variant="primary" icon={Sparkles} onClick={finish} loading={done.isPending}>
                  Finish — all done
                </Button>
              ) : (
                // the accessible name starts with the visible words ("Next: Compare — Compare with the letter"), WCAG 2.5.3
                <Button variant="primary" onClick={() => go(index + 1)} className="min-w-0 max-w-full">
                  <span className="truncate">
                    Next: {nextStep ? STEP_META[nextStep.id].short : ""}
                    {nextStep && nextStep.title !== STEP_META[nextStep.id].short ? (
                      <>
                        {" "}
                        <span className="sr-only">— {nextStep.title}</span>
                      </>
                    ) : null}
                  </span>
                  <ArrowRight className="size-4 shrink-0" aria-hidden />
                </Button>
              )}
            </div>
            {/* every day on these steps is computed (a cancellation's, a transfer's, a letter's to post) */}
            <Disclaimer variant="block" className="mt-4" />
          </div>
        </div>
      </div>
    </>
  );
}
