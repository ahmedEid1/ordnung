import { Page } from "@/components/shell/Page";
import { ContractsView } from "@/features/contracts/ContractsView";

/** Contracts: fixed costs, "Decide by" callouts, terms & notice-window lanes, contract cards (SPEC §14.5). */
export default function ContractsPage() {
  return (
    <Page title="Contracts">
      <ContractsView />
    </Page>
  );
}
