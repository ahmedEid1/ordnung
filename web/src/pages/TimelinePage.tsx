import { Page } from "@/components/shell/Page";
import { TimelineView } from "@/features/timeline/TimelineView";

/** Timeline: year-ahead life lanes + month-by-month list of every date (SPEC §14.4). */
export default function TimelinePage() {
  return (
    <Page title="Timeline">
      <TimelineView />
    </Page>
  );
}
