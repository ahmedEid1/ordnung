import { Link, useParams } from "react-router";
import { RotateCw } from "lucide-react";
import { useDocument } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { Page } from "@/components/shell/Page";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button, buttonVariants } from "@/components/ui/Button";
import { LoadingLabel } from "@/components/ui/Skeleton";
import { DocumentSkeleton, DocumentView } from "@/features/document/DocumentView";

const PARENT = { to: "/inbox", label: "Inbox" };

/** `/documents/:id` — the Document viewer (verdict, evidence on the page, why this date). */
export default function DocumentPage() {
  const { id } = useParams();
  const q = useDocument(id);
  const doc = q.data?.document;

  return (
    <Page title={doc ? (doc.title ?? doc.filename) : "Letter"} parent={PARENT} width="wide" className="pt-4 md:pt-6">
      {q.isPending ? (
        <>
          <LoadingLabel>Opening the letter…</LoadingLabel>
          <DocumentSkeleton />
        </>
      ) : q.isError ? (
        q.error instanceof ApiError && q.error.status === 404 ? (
          <EmptyState
            className="mx-auto mt-8 max-w-xl"
            headingLevel={1}
            illustration="search"
            title="This letter isn't here (anymore)"
            description="It may have been deleted. Everything else in your inbox is where you left it."
            action={
              <Link to="/inbox" className={buttonVariants({ variant: "primary" })}>
                Back to Inbox
              </Link>
            }
          />
        ) : (
          <EmptyState
            className="mx-auto mt-8 max-w-xl"
            headingLevel={1}
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
        <DocumentView key={q.data.document.id} detail={q.data} />
      )}
    </Page>
  );
}
