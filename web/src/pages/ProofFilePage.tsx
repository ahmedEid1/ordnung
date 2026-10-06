import { Link, useParams } from "react-router";
import { ArrowLeft } from "lucide-react";
import { useDocument } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { Page } from "@/components/shell/Page";
import { buttonVariants } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { ProofFileView, proofPageTitle } from "@/features/letters/ProofFileView";
import { useStickyError } from "@/lib/hooks";

/**
 * `/letters/:id/proofs/:docId` — one proof file of a sent letter: what it is, for which letter, the file
 * itself and "Remove this proof". It is named by its kind ("Proof: Posting receipt"), never by the
 * file's name; its breadcrumb and back button lead to the letter ("Back to Letter", like "Back to
 * Inbox"). Its column starts under the breadcrumb, as on the letter's own page; a failed load says so
 * like every other page (the shared LoadError), with the way back to the letter.
 */
export default function ProofFilePage() {
  const { id = "", docId } = useParams();
  const q = useDocument(docId);
  const link = q.data?.proof_of.find((l) => l.draft_id === id) ?? q.data?.proof_of[0] ?? null;
  const letterHref = `/letters/${link?.draft_id ?? id}`;
  // the letter's subject can be long: the breadcrumb says where it leads, the page names the letter
  const parent = { to: letterHref, label: "Letter" };
  // a retry of a failed load may start over as "pending": the message stays (and isn't announced again)
  const loaded = Boolean(q.data);
  const error = useStickyError(q.error, loaded);
  const failed = !loaded && error !== null;
  const gone = (failed && error instanceof ApiError && error.status === 404) || (q.data && !link);
  const back = (
    <Link to={letterHref} className={buttonVariants({ variant: gone ? "primary" : "secondary" })}>
      <ArrowLeft aria-hidden />
      Back to the letter
    </Link>
  );
  return (
    <Page title={link ? proofPageTitle(link.kind) : "Proof"} parent={parent} className="pt-4 md:pt-6">
      {gone ? (
        <EmptyState
          className="mx-auto mt-8 max-w-xl"
          headingLevel={1}
          illustration="search"
          title="This proof isn't here (anymore)"
          description="It may have been removed from the letter. The letter itself is where you left it."
          action={back}
        />
      ) : failed ? (
        <div className="mx-auto mt-8 max-w-xl">
          <LoadError headingLevel={1} title="Couldn't open this proof" error={error} onRetry={() => void q.refetch()} retrying={q.isFetching} />
          <p className="mt-4 flex justify-center">{back}</p>
        </div>
      ) : q.data && link ? (
        <ProofFileView key={q.data.document.id} detail={q.data} draftId={link.draft_id} />
      ) : (
        <div aria-busy="true" className="max-w-3xl">
          <h1 className="sr-only" data-loading>Proof</h1>
          <LoadingLabel>Opening the proof…</LoadingLabel>
          <Skeleton className="mb-4 h-8 w-64" />
          <SkeletonText lines={3} />
        </div>
      )}
    </Page>
  );
}
