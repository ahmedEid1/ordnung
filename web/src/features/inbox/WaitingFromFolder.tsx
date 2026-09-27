/**
 * "From your folder — waiting for you": files the watched folder brought in (with the attachments of
 * e-mails among them), stored on this computer and not read yet. The footer asks: "Read these N"
 * sends exactly the letters listed here to Claude (a file that arrives meanwhile is not included);
 * "Keep private" keeps them on this computer for good (docs/privacy.md, "The watched folder").
 *
 * When they are answered the group goes; `onAnswered` then says where focus goes (the letters list).
 */
import { Link } from "react-router";
import { FolderInput, Lock, Sparkles } from "lucide-react";
import type { Document } from "@/api/types";
import { useKeepHeldPrivate, useReadHeld } from "@/api/hooks";
import { formatDateTime } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { cn, plural } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { toast } from "@/components/ui/Toast";
import { Thumb } from "./LettersList";
import { fileKindLabel, readLabel, waitingRows, type WaitingRow } from "./waiting";

export function WaitingFromFolder({ docs, onAnswered }: { docs: readonly Document[]; onAnswered?: () => void }) {
  const rows = waitingRows(docs);
  const read = useReadHeld();
  const keep = useKeepHeldPrivate();
  if (!rows.length) return null;
  const ids = rows.map((r) => r.doc.id);
  const n = ids.length;
  const busy = read.isPending || keep.isPending;

  const readThem = () =>
    read.mutate(ids, {
      onSuccess: (res) => {
        const count = res.documents.length;
        if (count)
          toast.success(count === 1 ? "Claude is reading it" : `Claude is reading ${plural(count, "letter")}`, {
            description: "You'll see every step; dates and amounts are checked against the page.",
          });
        else
          toast({
            title: "Nothing left to read",
            description: "These were answered already.",
            tone: "info",
          });
        onAnswered?.();
      },
    });
  const keepThem = () =>
    keep.mutate(ids, {
      onSuccess: (res) => {
        const count = res.documents.length;
        toast.success(count === 1 ? "Kept private" : `Kept ${plural(count, "letter")} private`, {
          description: "They stay on this computer and are never sent to Claude.",
        });
        onAnswered?.();
      },
    });

  return (
    <section aria-labelledby="waiting-title" className="mb-10">
      <SectionHeader
        id="waiting-title"
        icon={FolderInput}
        title={
          <>
            <span aria-hidden>
              From your folder — waiting for you
              <span className="font-medium tabular-nums">{` · ${n}`}</span>
            </span>
            <span className="sr-only">{`From your folder — waiting for you, ${plural(n, "letter")}`}</span>
          </>
        }
        description="Stored on this computer and not read yet — nothing has been sent to Claude."
      />
      <div className="card overflow-hidden">
        <ul className="divide-y divide-line" aria-label="Letters waiting for you">
          {rows.map((row) => (
            <WaitingItem key={row.doc.id} row={row} />
          ))}
        </ul>
        <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-3 border-t border-line bg-surface-2/40 px-4 py-3 sm:px-5">
          <p className="mr-auto min-w-0 basis-full text-sm leading-5 text-muted sm:basis-auto sm:flex-1">
            Claude reads them like letters you add.{" "}
            <Link to="/settings?section=folder" className="font-medium text-accent underline-offset-2 hover:underline">
              Watched folder settings
            </Link>
          </p>
          {/* phones: the two answers share the row */}
          <div className="flex w-full gap-2 sm:w-auto">
            <Button size="sm" icon={Lock} onClick={keepThem} loading={keep.isPending} disabled={busy && !keep.isPending} className="max-sm:flex-1">
              Keep private
            </Button>
            <Button size="sm" variant="primary" icon={Sparkles} onClick={readThem} loading={read.isPending} disabled={busy && !read.isPending} className="max-sm:flex-1">
              {readLabel(n)}
              {" "}
              <span className="sr-only">with Claude</span>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}

function WaitingItem({ row }: { row: WaitingRow }) {
  const today = useTodayISO();
  const { doc, email, nested } = row;
  return (
    <li
      className={cn("group relative flex items-start gap-3.5 px-4 py-3.5 transition-colors hover:bg-surface-2/50 focus-within:bg-surface-2/50 sm:px-5", nested && "pl-10 sm:pl-12")}
    >
      <Thumb doc={doc} />
      <div className="min-w-0 flex-1">
        <Link
          to={`/documents/${doc.id}`}
          title={doc.filename}
          className="line-clamp-2 break-words text-[14.5px] font-medium leading-snug text-ink outline-none [overflow-wrap:anywhere] after:absolute after:inset-0 after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-accent"
        >
          {doc.filename}
        </Link>
        <p className="mt-1 text-sm leading-5 text-muted">
          {fileKindLabel(doc.mime)}
          {doc.pages > 1 ? ` · ${plural(doc.pages, "page")}` : ""} · added {formatDateTime(doc.created_at, { today })}
        </p>
        {email ? (
          <p className="mt-0.5 text-sm leading-5 text-muted [overflow-wrap:anywhere]" title={email.filename}>
            Attached to “{email.title ?? email.filename}”
          </p>
        ) : null}
      </div>
    </li>
  );
}
