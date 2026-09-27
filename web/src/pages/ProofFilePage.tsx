import { Link, useParams } from "react-router";
import { RotateCw } from "lucide-react";
import { useDocument } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { Page } from "@/components/shell/Page";
import { Button, buttonVariants } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { ProofFileView } from "@/features/letters/ProofFileView";

/**
 * `/letters/:id/proofs/:docId` — one proof file of a sent letter: what it is, for which letter, the file
 * itself and "Remove this proof". Its breadcrumb and back button lead to the letter.
 */
export default function ProofFilePage() {
  const { id = "", docId } = useParams();
  const q = useDocument(docId);
  const link = q.data?.proof_of.find((l) => l.draft_id === id) ?? q.data?.proof_of[0] ?? null;
  // the letter's subject can be long: the breadcrumb says where it leads, the page names the letter
  const parent = { to: `/letters/${link?.draft_id ?? id}`, label: "Your letter" };
  const gone = (q.isError && q.error instanceof ApiError && q.error.status === 404) || (q.data && !link);
  return (
    <Page title={q.data ? `Proof: ${q.data.document.filename}` : "Proof"} parent={parent} className="pt-4 md:pt-6">
      {q.isPending ? (
        <div aria-busy="true" className="mx-auto max-w-3xl">
          <LoadingLabel>Opening the proof…</LoadingLabel>
          <Skeleton className="mb-4 h-8 w-64" />
          <SkeletonText lines={3} />
        </div>
      ) : gone ? (
        <EmptyState
          className="mx-auto mt-8 max-w-xl"
          headingLevel={1}
          illustration="search"
          title="This proof isn't here (anymore)"
          description="It may have been removed from the letter. The letter itself is where you left it."
          action={
            <Link to={`/letters/${id}`} className={buttonVariants({ variant: "primary" })}>
              Back to the letter
            </Link>
          }
        />
      ) : q.isError || !q.data ? (
        <EmptyState
          className="mx-auto mt-8 max-w-xl"
          headingLevel={1}
          illustration="error"
          title="Couldn't open this proof"
          description={q.error instanceof Error ? q.error.message : "Something went wrong."}
          action={
            <Button variant="primary" icon={RotateCw} onClick={() => void q.refetch()} loading={q.isFetching}>
              Try again
            </Button>
          }
        />
      ) : (
        <ProofFileView key={q.data.document.id} detail={q.data} draftId={link!.draft_id} />
      )}
    </Page>
  );
}
