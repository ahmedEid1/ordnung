import { useMemo } from "react";
import { motion } from "motion/react";
import { RotateCw } from "lucide-react";
import { useProfile } from "@/api/hooks";
import { useSimulatedToday } from "@/lib/today";
import { Button } from "@/components/ui/Button";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingLabel, Skeleton, SkeletonCard, SkeletonText } from "@/components/ui/Skeleton";
import { ComingUp } from "./ComingUp";
import { Greeting } from "./Greeting";
import { IdeasSection } from "./Ideas";
import { LifeAtAGlance } from "./LifeAtAGlance";
import { RecentLetters } from "./RecentLetters";
import { SecretaryNote } from "./SecretaryNote";
import { CalendarCard, PleaseCheckCard } from "./SideCards";
import { TopThree } from "./TopThree";
import { stagger } from "./motion";
import { agendaSentence, toPayTotals } from "./selection";
import { useTodayData } from "./useTodayData";

function TodaySkeleton() {
  return (
    <div className="space-y-8" aria-busy>
      <LoadingLabel>Loading your day…</LoadingLabel>
      <div className="space-y-3">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-11 w-80 max-w-full" />
      </div>
      <div className="card p-6">
        <SkeletonText lines={3} />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SkeletonCard lines={2} />
        <SkeletonCard lines={2} />
        <SkeletonCard lines={2} />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <SkeletonCard lines={5} />
        <SkeletonCard lines={3} />
      </div>
    </div>
  );
}

/**
 * The Today page: greeting, the secretary's note, Top 3 this week, "Coming up", Ideas, the
 * calendar and "Please check" cards, life at a glance and recent letters (SPEC §14.1).
 */
export function TodayView() {
  const data = useTodayData();
  const profile = useProfile();
  const { simulated } = useSimulatedToday();
  // The demo simulates a morning (the note was written at 07:00); otherwise follow the clock.
  const hour = useMemo(() => (simulated ? 9 : new Date().getHours()), [simulated]);

  if (data.isPending) return <TodaySkeleton />;
  if (data.isError || !data.dash || !data.derived) {
    return (
      <EmptyState
        className="mt-6"
        headingLevel={1}
        illustration="error"
        title="Couldn't load your day"
        description="Your letters and dates are safe — Ordnung just didn't answer. Try again in a moment."
        action={
          <Button variant="primary" icon={RotateCw} onClick={() => void data.dashboard.refetch()} loading={data.dashboard.isFetching}>
            Try again
          </Button>
        }
      />
    );
  }

  const { dash, derived, partyById, reviewDocs } = data;
  const name = dash.greeting_name || profile.data?.name.split(" ")[0] || "";
  const fallback = agendaSentence(derived.top, derived.nextUp ? [derived.nextUp] : [], derived.day);

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="flex flex-col gap-8 sm:gap-10">
      <div className="flex flex-col gap-6">
        <Greeting name={name} today={derived.day} money={dash.money} toPay={toPayTotals(derived.candidates)} hour={hour} />
        <SecretaryNote fallback={fallback} />
      </div>

      <TopThree actions={derived.top} next={derived.nextUp} partyById={partyById} today={derived.day} />

      <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,23rem)] lg:gap-6">
        <ComingUp actions={derived.rest} all={derived.candidates} partyById={partyById} today={derived.day} />
        <div className="flex min-w-0 flex-col gap-4">
          <PleaseCheckCard docs={reviewDocs} />
          <CalendarCard idea={derived.calendar} />
          <IdeasSection shown={derived.ideas.shown} more={derived.ideas.more} today={derived.day} pinnedIds={derived.pinnedIds} />
        </div>
      </div>

      <LifeAtAGlance areas={dash.areas} />

      <RecentLetters docs={dash.recent_documents} partyById={partyById} />

      <div className="flex justify-center">
        <Disclaimer className="max-w-xl" />
      </div>
    </motion.div>
  );
}
