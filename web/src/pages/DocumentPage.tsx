import { Link, useParams } from "react-router";
import { ArrowLeft, Inbox } from "lucide-react";
import { useDocument, useHealth, useMailTray } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { Page } from "@/components/shell/Page";
import { useOriginParent } from "@/components/shell/origin";
import { EmptyState } from "@/components/ui/EmptyState";
import { buttonVariants } from "@/components/ui/Button";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel } from "@/components/ui/Skeleton";
import { DocumentSkeleton, DocumentView } from "@/features/document/DocumentView";
import { isReading } from "@/features/inbox/filters";
import { useMarkLetterSeen } from "@/features/inbox/seen";

/** Every letter lives in the Inbox: its parent when it wasn't opened from another section. */
const HOME = { to: "/inbox", label: "Inbox" };

/**
 * A letter link that finds nothing. In the demo, letters still waiting in New mail aren't letters yet —
 * their links (from before a reset) lead here, so the page says where to open them (UI audit round 1:
 * "It may have been deleted" for a letter nobody had opened).
 */
function LetterNotFound() {
  const demo = Boolean(useHealth().data?.demo);
  const tray = useMailTray(demo);
  const waiting = demo && (tray.data ?? []).some((t) => !t.opened);
  return (
    <EmptyState
      className="mx-auto mt-8 max-w-xl"
      headingLevel={1}
      illustration="search"
      title={waiting ? "This letter isn't in your inbox" : "This letter is no longer here"}
      description={
        waiting
          ? "If it's one of the letters in New mail, it hasn't been opened yet — open it there first. Otherwise it was deleted."
          : "It may have been deleted, or the link is incomplete. Everything else in your inbox is where you left it."
      }
      action={
        <Link to="/inbox" className={buttonVariants({ variant: "primary" })}>
          {waiting ? <Inbox aria-hidden /> : <ArrowLeft aria-hidden />}
          {waiting ? "Open New mail" : "Back to Inbox"}
        </Link>
      }
    />
  );
}

/**
 * `/documents/:id` — the Document viewer (verdict, evidence on the page, why this date). Its
 * breadcrumb and phone back button lead to where it was opened from (Today, Timeline, Ask…).
 */
export default function DocumentPage() {
  const { id } = useParams();
  const q = useDocument(id);
  const doc = q.data?.document;
  const parent = useOriginParent(HOME);
  // the Inbox's "New" badge clears once the letter itself was shown
  useMarkLetterSeen(doc && !isReading(doc) ? doc.id : null);
  const notFound = q.isError && q.error instanceof ApiError && q.error.status === 404;
  const title = doc ? (doc.title ?? doc.filename) : notFound ? "Letter not found" : "Letter";

  // the viewer sits closer under the top bar; a message about the letter keeps the page's own spacing, as on a
  // draft's page (UI audit round 1)
  return (
    <Page title={title} parent={parent} className={q.isError ? undefined : "pt-4 md:pt-6"}>
      {q.isPending ? (
        <>
          {/* the page has its heading while it loads, too */}
          <h1 className="sr-only">Letter</h1>
          <LoadingLabel>Opening the letter…</LoadingLabel>
          <DocumentSkeleton />
        </>
      ) : q.isError ? (
        notFound ? (
          <LetterNotFound />
        ) : (
          <div className="mx-auto mt-8 max-w-xl">
            {/* a calm sentence; the server's own words under "Technical details" (UI audit round 1: "Something went wrong (UI audit)") */}
            <LoadError
              headingLevel={1}
              title="Couldn't open this letter"
              description="Your letters are safe — Ordnung couldn't load this one just now. Try again in a moment."
              error={q.error}
              onRetry={() => void q.refetch()}
              retrying={q.isFetching}
            />
            <p className="mt-4 flex justify-center">
              <Link to={parent.to} className={buttonVariants({ variant: "secondary" })}>
                <ArrowLeft aria-hidden />
                Back to {parent.label}
              </Link>
            </p>
          </div>
        )
      ) : (
        <DocumentView key={q.data.document.id} detail={q.data} />
      )}
    </Page>
  );
}
