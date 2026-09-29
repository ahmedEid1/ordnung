import { Page } from "@/components/shell/Page";
import { WEEKLY_REVIEW } from "@/features/week/steps";
import { WeekView } from "@/features/week/WeekView";

/** The weekly review: the guided weekly admin session. */
export default function WeekPage() {
  return (
    <Page title={WEEKLY_REVIEW} parent={{ to: "/", label: "Today" }}>
      <WeekView />
    </Page>
  );
}
