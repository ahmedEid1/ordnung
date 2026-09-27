import { Page } from "@/components/shell/Page";
import { WeekView } from "@/features/week/WeekView";

/** "This week": the guided weekly admin session. */
export default function WeekPage() {
  return (
    <Page title="This week" parent={{ to: "/", label: "Today" }}>
      <WeekView />
    </Page>
  );
}
