import { useMemo, useState } from "react";
import { motion } from "motion/react";
import { Link } from "react-router";
import { Lock, Plus } from "lucide-react";
import { ApiError } from "@/api/client";
import { useProfile } from "@/api/hooks";
import { useAddLetters } from "@/components/shell/AddLetters";
import { useSimulatedToday, useTodayISO } from "@/lib/today";
import { Button } from "@/components/ui/Button";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { ComingUp } from "./ComingUp";
import { Greeting } from "./Greeting";
import { IdeasSection } from "./Ideas";
import { LifeAtAGlance } from "./LifeAtAGlance";
import { RecentLetters } from "./RecentLetters";
import { SecretaryNote } from "./SecretaryNote";
import { CalendarCard, PLEASE_CHECK_SHOWN, PleaseCheckCard, repeatsPleaseCheck } from "./SideCards";
import { TopThree } from "./TopThree";
import { WaitingCard } from "./WaitingCard";
import { AttentionCard } from "./AttentionCard";
import { stagger } from "./motion";
import { agendaSentence, toPayTotals } from "./selection";
import { useTodayData } from "./useTodayData";
import { WeeklyLink, WeeklyPrompt } from "@/features/week/WeeklyPrompt";
import { useStickyError } from "@/lib/hooks";

/**
 * Coming up and the side cards (Please check, calendar) sit side by side once the page is wide
 * enough for both — measured on the page's own width (a container query), so an open sidebar
 * doesn't squeeze Coming up into a sliver.
 */
const SPLIT = "grid grid-cols-1 items-start gap-8 @[56rem]:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] @[56rem]:gap-6";
/** The side column starts level with Coming up's card, under its section header (13 px × 1.5 + mb-3). */
const SIDE = "flex min-w-0 flex-col gap-4 @[56rem]:pt-[calc(0.8125rem*1.5+0.75rem)]";
/**
 * Ideas take the full width below, two columns once there is room. (The list is IdeasSection's
 * own <ul>; it lays itself out as a single column.)
 */
const IDEAS = "@container [&>section>ul]:grid [&>section>ul]:grid-cols-1 [&>section>ul]:items-start @[40rem]:[&>section>ul]:grid-cols-2 @[40rem]:[&>section>ul]:gap-4";

/** "Good morning" for the demo's simulated morning (its note was written at 07:00), else the clock. */
function useGreetingHour(): number {
  const { simulated } = useSimulatedToday();
  return useMemo(() => (simulated ? 9 : new Date().getHours()), [simulated]);
}

/** The loading page: the real greeting and the same blocks, in the same places, as the page it becomes. */
function TodaySkeleton({ name, today, hour }: { name: string; today: string; hour: number }) {
  return (
    <div className="@container flex flex-col gap-8 sm:gap-10" aria-busy="true">
      <LoadingLabel>Loading your day…</LoadingLabel>
      <div className="flex flex-col gap-6">
        <Greeting name={name} today={today} hour={hour} loading />
        <div className="card p-5 sm:p-7" aria-hidden>
          <div className="flex items-center gap-3">
            <Skeleton className="size-9 rounded-xl" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-3.5 w-40" />
              <Skeleton className="h-3 w-28" />
            </div>
          </div>
          <SkeletonText lines={3} className="mt-5 max-w-[62ch]" />
        </div>
      </div>
      <div className="@container" aria-hidden>
        <Skeleton className="mb-3 h-3.5 w-36" />
        <div className="grid grid-cols-1 gap-3 sm:gap-4 @4xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card flex min-h-[18rem] flex-col p-4 sm:p-5">
              <Skeleton className="h-6 w-44 rounded-full" />
              <Skeleton className="mt-4 h-4 w-3/4" />
              <Skeleton className="mt-2 h-6 w-24" />
              <SkeletonText lines={2} className="mt-3" />
              <Skeleton className="mt-auto h-6 w-40 rounded-full" />
              <div className="mt-3.5 flex items-center justify-between border-t border-line pt-3.5">
                <Skeleton className="h-8 w-20 rounded-lg" />
                <Skeleton className="h-4 w-24" />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className={SPLIT} aria-hidden>
        <div>
          <Skeleton className="mb-3 h-3.5 w-44" />
          <div className="card divide-y divide-line">
            {[0, 1].map((g) => (
              <div key={g} className="space-y-3 px-4 py-3 sm:px-5">
                <Skeleton className="h-3.5 w-32" />
                {[0, 1, 2].map((r) => (
                  <div key={r} className="flex items-center gap-3">
                    <Skeleton className="h-[52px] w-11 rounded-lg" />
                    <SkeletonText lines={2} className="flex-1" />
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
        <div className={SIDE}>
          <div className="card p-4 sm:p-5">
            <SkeletonText lines={3} />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Why the day didn't load, in words that fit the cause. */
export function dayErrorDescription(error: unknown): string {
  if (error instanceof ApiError && error.status >= 500) {
    return "Ordnung ran into a problem while putting your day together. Your letters and dates are safe — try again, and restart Ordnung if it keeps happening.";
  }
  if (error instanceof ApiError && error.status > 0) return "Ordnung couldn't put your day together. Your letters and dates are safe — try again in a moment.";
  return "Ordnung didn't answer. Your letters and dates are safe — is it still running on this computer?";
}

/** A fresh install with no letters yet: one clear first step instead of a page of zeros and "All clear". */
function FirstRun() {
  const { openPicker, uploading } = useAddLetters();
  return (
    <EmptyState
      illustration="inbox"
      title="Add your first letters"
      description="A PDF, a phone photo or a saved e-mail of any letter — a bill, a contract, a notice from an office."
      action={
        <Button variant="primary" icon={Plus} onClick={openPicker} loading={uploading}>
          Add letters
        </Button>
      }
    >
      <ul className="mt-6 w-full max-w-md space-y-2 text-left text-base leading-relaxed text-muted">
        {[
          "Ordnung reads each letter and explains it in plain English.",
          "Every date and amount lands here — what to do this week and what's coming up.",
          "Your secretary spots deadlines, fees that went up and letters that look like a scam.",
        ].map((line, i) => (
          <li key={line} className="flex gap-3">
            <span className="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent" aria-hidden>
              {i + 1}
            </span>
            {line}
          </li>
        ))}
      </ul>
      <p className="mt-5 inline-flex items-center gap-1.5 text-sm text-muted">
        <Lock className="size-3.5 shrink-0" aria-hidden /> Your files stay on this computer.
      </p>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted">
        Or let Ordnung pick up what your scanner saves:{" "}
        <Link to="/settings?section=folder" className="rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent">
          choose a watched folder
        </Link>
        . Moving from another computer? <code className="font-ident text-[13px] text-ink">ordnung restore</code> brings back your encrypted backup.
      </p>
    </EmptyState>
  );
}

/**
 * The Today page: greeting, the secretary's note, the letters waiting from the watched folder (when
 * any do), Top 3 this week, "Coming up" with the "Please check" and calendar cards beside it, Ideas,
 * life at a glance and recent letters (SPEC §14.1).
 */
export function TodayView() {
  const data = useTodayData();
  const profile = useProfile();
  const hour = useGreetingHour();
  const todayISO = useTodayISO();
  // the calendar card stays after its download (with what to do next) — its Idea is gone by then
  const [calendarDone, setCalendarDone] = useState(false);
  const profileName = profile.data?.name.split(" ")[0] ?? "";
  // A retry of a load that failed starts over as "pending" (and forgets the error), so remember the
  // last error: the message stays on screen, worded the same, while "Try again" runs.
  const error = data.dashboard.error;
  const lastError = useStickyError(error, Boolean(data.dash));
  const failed = !data.dash && (data.isError || Boolean(lastError));

  if (data.isPending && !failed) return <TodaySkeleton name={profileName} today={todayISO} hour={hour} />;
  if (failed || !data.dash || !data.derived) {
    return (
      <div className="flex flex-col gap-6">
        <Greeting name={profileName} today={todayISO} hour={hour} />
        <LoadError
          what="your day"
          description={dayErrorDescription(error ?? lastError)}
          error={error ?? lastError}
          onRetry={() => void data.dashboard.refetch()}
          retrying={data.dashboard.isFetching}
        />
      </div>
    );
  }

  const { dash, derived, partyById, reviewDocs } = data;
  const name = dash.greeting_name || profileName;

  if (!dash.stats.documents && !dash.recent_documents.length && !derived.candidates.length && !dash.stats.contracts && !dash.waiting) {
    return (
      <motion.div variants={stagger} initial="hidden" animate="show" className="flex flex-col gap-8 sm:gap-10">
        <Greeting name={name} today={derived.day} hour={hour} />
        <FirstRun />
      </motion.div>
    );
  }

  const fallback = agendaSentence(derived.top, derived.nextUp ? [derived.nextUp] : [], derived.day, dash.waiting);
  // an Idea that only says "Please check: <letter>" repeats the card that lists that letter
  const listed = new Set(reviewDocs.slice(0, PLEASE_CHECK_SHOWN).map((d) => d.id));
  const ideas = [...derived.ideas.shown, ...derived.ideas.more].filter((s) => !repeatsPleaseCheck(s, listed));
  const shownIdeas = derived.ideas.shown.length;
  const side = reviewDocs.length > 0 || Boolean(derived.calendar) || calendarDone;

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="@container flex flex-col gap-8 sm:gap-10">
      <div className="flex flex-col gap-6">
        <Greeting name={name} today={derived.day} money={dash.money} toPay={toPayTotals(derived.candidates)} hour={hour} />
        <SecretaryNote fallback={fallback} waiting={dash.waiting} />
        <WaitingCard count={dash.waiting} />
        <AttentionCard />
      </div>

      <TopThree actions={derived.top} next={derived.nextUp} partyById={partyById} today={derived.day} waiting={dash.waiting} />

      <WeeklyPrompt />

      <div className={side ? SPLIT : undefined}>
        <ComingUp actions={derived.rest} all={derived.candidates} partyById={partyById} today={derived.day} />
        {side ? (
          <div className={SIDE}>
            <PleaseCheckCard docs={reviewDocs} />
            <CalendarCard idea={derived.calendar} done={calendarDone} onDone={() => setCalendarDone(true)} />
          </div>
        ) : null}
      </div>

      <div className={IDEAS}>
        <IdeasSection
          shown={ideas.slice(0, shownIdeas)}
          more={ideas.slice(shownIdeas)}
          today={derived.day}
          pinnedIds={derived.pinnedIds}
          actions={derived.candidates}
        />
      </div>

      <LifeAtAGlance areas={dash.areas} />

      <RecentLetters docs={dash.recent_documents} partyById={partyById} />

      <div className="flex flex-col items-center gap-3">
        <WeeklyLink />
        <Disclaimer className="max-w-xl" />
      </div>
    </motion.div>
  );
}
