import { Page } from "@/components/shell/Page";
import { NumbersView } from "@/features/numbers/NumbersView";

/** My numbers: yours, your documents, open cases and a call sheet per organisation. */
export default function NumbersPage() {
  return (
    <Page title="My numbers">
      <NumbersView />
    </Page>
  );
}
