import { Link, useParams } from "react-router";
import { ArrowLeft } from "lucide-react";
import { useDraft, useParties } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { Page } from "@/components/shell/Page";
import { buttonVariants } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { LetterView } from "@/features/letters/LetterView";
import { draftTitle } from "@/features/letters/logic";
import { useStickyError } from "@/lib/hooks";

const PARENT = { to: "/letters", label: "Letters" };

function LetterSkeleton() {
  return (
    <div aria-busy="true">
      <h1 className="sr-only" data-loading>Letter</h1>
      <LoadingLabel>Opening your letter…</LoadingLabel>
      <Skeleton className="h-4 w-48" />
      <Skeleton className="mt-3 h-9 w-2/3 max-w-lg" />
      <div className="mt-8 space-y-6">
        <div className="card grid gap-6 p-6 md:grid-cols-2">
          <SkeletonText lines={9} />
          <SkeletonText lines={9} />
        </div>
        <div className="grid gap-6 md:grid-cols-2">
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

  // A retry of a failed load may start over as "pending": remember the error, so the message stays
  // on screen (and isn't announced again) while "Try again" runs.
  const loaded = Boolean(q.data);
  const error = useStickyError(q.error, loaded);
  const failed = !loaded && error !== null;
  const notFound = failed && error instanceof ApiError && error.status === 404;

  const title = q.data ? draftTitle(q.data, party?.name) : notFound ? "Letter not found" : failed ? "Letter" : "Letter draft";
  const back = (
    <Link to="/letters" className={buttonVariants({ variant: notFound ? "primary" : "secondary" })}>
      <ArrowLeft aria-hidden />
      Back to Letters
    </Link>
  );

  return (
    <Page title={title} parent={PARENT}>
      {q.data ? (
        <LetterView key={q.data.id} draft={q.data} />
      ) : notFound ? (
        <EmptyState
          className="mx-auto mt-8 max-w-xl"
          headingLevel={1}
          illustration="search"
          title="This letter isn't here (anymore)"
          description="It may have been deleted. Your other letters are where you left them."
          action={back}
        />
      ) : failed ? (
        <div className="mx-auto mt-8 max-w-xl">
          <LoadError
            headingLevel={1}
            title="Couldn't open this letter"
            error={error}
            onRetry={() => void q.refetch()}
            retrying={q.isFetching}
          />
          <p className="mt-4 flex justify-center">{back}</p>
        </div>
      ) : (
        <LetterSkeleton />
      )}
    </Page>
  );
}
