import { Link } from "react-router";
import { useWaiting } from "@/api/hooks";
import { Page, PageHeader } from "@/components/shell/Page";
import { buttonVariants } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { WaitingList } from "@/features/waiting/WaitingList";

const PARENT = { to: "/letters", label: "Letters" };

function WaitingSkeleton() {
  return (
    <div aria-busy="true">
      <LoadingLabel>Loading what you're waiting for…</LoadingLabel>
      <Skeleton className="mb-3 h-3.5 w-28" />
      <div className="card divide-y divide-line">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex gap-3 px-5 py-4">
            <Skeleton className="size-9 rounded-xl" />
            <SkeletonText lines={3} className="flex-1" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** `/letters/waiting` — replies, money and callbacks the person is owed (SPEC §14.6). */
export default function WaitingPage() {
  const q = useWaiting();
  return (
    <Page title="Waiting for" parent={PARENT}>
      <PageHeader
        title="Waiting for"
        description="Replies to letters you sent, money a letter promised you and callbacks promised on the phone. When a letter answers one, Ordnung says so — you check it and close it."
      />
      {q.isPending ? (
        <WaitingSkeleton />
      ) : q.isError ? (
        <LoadError what="what you're waiting for" error={q.error} onRetry={() => void q.refetch()} retrying={q.isFetching} />
      ) : q.data.length ? (
        <WaitingList entries={q.data} />
      ) : (
        <EmptyState
          illustration="clear"
          headingLevel={2}
          title="Nothing to wait for"
          description="Mark a letter as sent, add a letter that says money is coming, or note a promise from a phone call (open who you spoke to — from a letter or a contract — and choose Note a call). It shows here until it's settled."
          action={
            <Link to="/letters" className={buttonVariants({ variant: "primary" })}>
              Go to your letters
            </Link>
          }
        />
      )}
    </Page>
  );
}
