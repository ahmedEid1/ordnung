import { Link, useParams } from "react-router";
import { RotateCw } from "lucide-react";
import { useDraft, useParties } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { Page } from "@/components/shell/Page";
import { Button, buttonVariants } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { LetterView } from "@/features/letters/LetterView";
import { draftTitle } from "@/features/letters/logic";

const PARENT = { to: "/letters", label: "Letters" };

function LetterSkeleton() {
  return (
    <div aria-busy="true">
      <LoadingLabel>Opening your letter…</LoadingLabel>
      <Skeleton className="h-4 w-48" />
      <Skeleton className="mt-3 h-9 w-2/3 max-w-lg" />
      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="card grid gap-6 p-6 md:grid-cols-2">
          <SkeletonText lines={9} />
          <SkeletonText lines={9} />
        </div>
        <div className="space-y-6">
          <div className="card p-5">
            <SkeletonText lines={5} />
          </div>
          <div className="card p-5">
            <SkeletonText lines={4} />
          </div>
        </div>
      </div>
    </div>
  );
}

/** `/letters/:id` — edit, check and send a drafted letter. */
export default function LetterPage() {
  const { id } = useParams();
  const q = useDraft(id);
  const parties = useParties();
  const party = q.data?.party_id ? parties.data?.find((p) => p.id === q.data!.party_id) : null;
  const title = q.data ? draftTitle(q.data, party?.name) : "Letter draft";

  return (
    <Page title={title} parent={PARENT} width="wide">
      {q.isPending ? (
        <LetterSkeleton />
      ) : q.isError ? (
        q.error instanceof ApiError && q.error.status === 404 ? (
          <EmptyState
            className="mx-auto mt-8 max-w-xl"
            illustration="search"
            title="This letter isn't here (anymore)"
            description="It may have been deleted. Your other letters are where you left them."
            action={
              <Link to="/letters" className={buttonVariants({ variant: "primary" })}>
                Back to Letters
              </Link>
            }
          />
        ) : (
          <EmptyState
            className="mx-auto mt-8 max-w-xl"
            illustration="error"
            title="Couldn't open this letter"
            description={q.error instanceof Error ? q.error.message : "Something went wrong."}
            action={
              <Button variant="primary" icon={RotateCw} onClick={() => void q.refetch()} loading={q.isFetching}>
                Try again
              </Button>
            }
          />
        )
      ) : (
        <LetterView key={q.data.id} draft={q.data} />
      )}
    </Page>
  );
}
