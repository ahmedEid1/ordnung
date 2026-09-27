/**
 * "This week": the guided weekly admin session (`GET /api/week`, `ordnung/secretary/week.py`) — seven
 * short steps, one at a time, then "All clear until …". Nothing is paid, sent or closed for the person:
 * each row links to where they act (Pay and Confirm right here). "Finish" remembers the session.
 * URL state: `?step=new|check|pay|post|waiting|decide|file`.
 */
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ArrowLeft, ArrowRight, Check, CircleCheck, Plus, Sparkles, TriangleAlert } from "lucide-react";
import { useWeek, useWeekDone } from "@/api/hooks";
import type { WeekStep, WeeklySession } from "@/api/types";
import { useAddLetters } from "@/components/shell/AddLetters";
import { PageHeader } from "@/components/shell/Page";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Countdown } from "@/components/ui/Countdown";
import { EmptyArt, EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { Money } from "@/components/ui/Money";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { Stepper } from "@/components/ui/Stepper";
import { formatMoney, glueText } from "@/lib/format";
import { useFormatDate } from "@/lib/today";
import { cn, prefersReducedMotion } from "@/lib/utils";
import { STEP_META, entryHref, stepCount, type StepId } from "./steps";
import { WeekEntryRow } from "./WeekEntryRow";

const DESCRIPTION = "About ten minutes: seven short steps through your paperwork. Nothing is paid, sent or closed for you.";
/** The step list beside the step once the page is wide enough (measured on the page, not the window). */
const LAYOUT = "grid grid-cols-1 items-start gap-6 @[52rem]:grid-cols-[15rem_minmax(0,1fr)]";

function StepList({ steps, current, visited, onPick }: { steps: WeekStep[]; current: number; visited: ReadonlySet<StepId>; onPick: (i: number) => void }) {
  return (
    <nav aria-label="Steps of the session" className="hidden @[52rem]:block @[52rem]:sticky @[52rem]:top-20">
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

function StepPanel({ step, index, total }: { step: WeekStep; index: number; total: number }) {
  const last = index === total - 1;
  const meta = STEP_META[step.id];
  const headingRef = useRef<HTMLHeadingElement>(null);
  const first = useRef(true);
  // moving to another step takes the focus to its heading (not on the first render: the page is new)
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    headingRef.current?.focus({ preventScroll: true });
    headingRef.current?.scrollIntoView?.({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [step.id]);
  const transfers = step.id === "pay" && step.total !== null;
  return (
    <Card as="section" padding="lg" aria-labelledby={`week-step-${step.id}`} className="scroll-mt-20">
      <p className="text-[12.5px] font-semibold uppercase tracking-[0.06em] text-muted">
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
      {step.more ? (
        <p className="mt-3 text-[13.5px] text-muted">
          And {step.more} more.{" "}
          <Link to={meta.more.to} className="rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent">
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

function AllClear({ week, onShow }: { week: WeeklySession; onShow: (step: StepId) => void }) {
  const formatDate = useFormatDate();
  const next = week.next_deadline;
  const heading = useRef<HTMLHeadingElement>(null);
  // the card replaces the step the person finished: the focus (and a screen reader) goes to it
  useEffect(() => heading.current?.focus(), []);
  const overdue = week.overdue;
  const overdueStep = week.steps.find((s) => s.entries.some((e) => e.overdue));
  const title = overdue
    ? `${overdue} ${overdue === 1 ? "thing is" : "things are"} overdue`
    : next?.date
      ? next.date <= week.today
        ? "One thing to do today"
        : `All clear until ${formatDate(next.date)}`
      : "All clear";
  return (
    <Card as="section" padding="lg" aria-labelledby="week-done-title" className="flex flex-col items-center text-center">
      {overdue ? (
        <span className="mb-3 grid size-14 place-items-center rounded-full bg-danger-soft text-danger-ink" aria-hidden>
          <TriangleAlert className="size-7" />
        </span>
      ) : (
        <EmptyArt kind="clear" className="mb-3" />
      )}
      <h2 id="week-done-title" ref={heading} tabIndex={-1} className="display text-[26px] font-semibold leading-tight text-ink outline-none">
        {title}
      </h2>
      {overdue ? (
        <p className="mt-2 max-w-md text-[14.5px] leading-relaxed text-muted">
          {overdue === 1 ? "Its date has passed: act on it first" : "Their dates have passed: act on them first"}, or contact the sender if you
          can't.{" "}
          {overdueStep ? (
            <button
              type="button"
              onClick={() => onShow(overdueStep.id)}
              className="inline min-h-6 rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
            >
              See {overdue === 1 ? "it" : "them"}
            </button>
          ) : null}
        </p>
      ) : null}
      {next?.date ? (
        <p className="mt-2 max-w-md text-[14.5px] leading-relaxed text-muted">
          Next:{" "}
          <Link to={entryHref(next)} className="rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent [overflow-wrap:anywhere]">
            {glueText(next.title)}
          </Link>
          <span aria-hidden>{"\u00a0·"}</span> <Countdown date={next.date} className="text-[14.5px]" />
        </p>
      ) : !overdue ? (
        <p className="mt-2 max-w-md text-[14.5px] leading-relaxed text-muted">Nothing is due from today on.</p>
      ) : null}
      <p className="mt-2 text-[13.5px] text-muted">Session saved — {nextPromptText(week, (d) => formatDate(d))}.</p>
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
        description="Add your letters: each week this review walks you through what they ask of you — new mail, payments, replies and decisions — in about ten minutes."
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
  const formatDate = useFormatDate();
  const [params, setParams] = useSearchParams();
  const [visited, setVisited] = useState<Set<StepId>>(() => new Set());
  const [finished, setFinished] = useState(false);

  const [lastError, setLastError] = useState<unknown>(null);
  if (q.error && q.error !== lastError) setLastError(q.error);
  else if (q.data && lastError !== null) setLastError(null);
  const failed = !q.data && (q.isError || lastError !== null);

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
      title="This week"
      description={
        <>
          {DESCRIPTION}
          {week?.last_session ? <span className="block text-[13.5px]">Last session: {formatDate(week.last_session)}.</span> : null}
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
          onShow={(id) => {
            setFinished(false);
            go(steps.findIndex((s) => s.id === id));
          }}
        />
      </>
    );
  }
  if (week.overdue === 0 && steps.every((s) => stepCount(s) === 0)) {
    return (
      <>
        {header}
        <NothingToReview week={week} />
      </>
    );
  }

  const last = index === steps.length - 1;
  const nextStep = steps[index + 1];
  return (
    <>
      {header}
      <div className="@container">
        <div className="mb-5 @[52rem]:hidden">
          {/* ticks only on the steps looked at (as the step list beside it); the card says "Step n of m" */}
          <Stepper
            steps={steps.map((s) => ({ id: s.id, label: s.title, short: STEP_META[s.id].short }))}
            current={index}
            doneIds={visited}
            labels="all"
            fallback="none"
            size="sm"
            label="Steps of the session"
          />
        </div>
        <div className={LAYOUT}>
          <StepList steps={steps} current={index} visited={visited} onPick={go} />
          <div className="flex min-w-0 flex-col gap-4">
            <StepPanel step={step} index={index} total={steps.length} />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Button variant="ghost" icon={ArrowLeft} onClick={() => go(index - 1)} disabled={index === 0}>
                Back
              </Button>
              {last ? (
                <Button variant="primary" icon={Sparkles} onClick={finish} loading={done.isPending}>
                  Finish — all done
                </Button>
              ) : (
                // the accessible name starts with the visible words ("Next: Check — Please check"), WCAG 2.5.3
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
          </div>
        </div>
      </div>
    </>
  );
}
