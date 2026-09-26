import { Page } from "@/components/shell/Page";
import { TodayView } from "@/features/today/TodayView";

/** Today (SPEC §14.1) — the home screen. */
export default function TodayPage() {
  return (
    <Page title="Today">
      <TodayView />
    </Page>
  );
}
