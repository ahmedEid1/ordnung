/**
 * "From your folder — not read yet": files the watched folder brought in (with the attachments of
 * e-mails among them), stored on this computer and not read yet. The footer asks: "Read these N"
 * sends exactly the letters listed here to Claude (a file that arrives meanwhile is not included);
 * "Keep private" keeps them on this computer for good (docs/privacy.md, "The watched folder").
 *
 * When they are answered the group goes; `onAnswered` then says where focus goes (the letters list).
 * The toast and the focus move run from the request's own promise (the group is gone by then), and
 * "Keep private" can be undone from its toast. More letters than one request may name are answered
 * in several (the hooks do that).
 */
import { Link } from "react-router";
import { FolderInput, Lock, Sparkles } from "lucide-react";
import type { Document } from "@/api/types";
import { useFolder, useKeepHeldPrivate, useReadHeld, useWaitAgain } from "@/api/hooks";
import { formatDateTime } from "@/lib/format";
import { protectRefs } from "@/lib/glue";
import { useTodayISO } from "@/lib/today";
import { cn, plural } from "@/lib/utils";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { toast } from "@/components/ui/Toast";
import { AnswerButton } from "./AnswerButton";
import { Thumb } from "./LettersList";
import { fileKindLabel, readLabel, waitingRows, type WaitingRow } from "./waiting";

export function WaitingFromFolder({ docs, onAnswered }: { docs: readonly Document[]; onAnswered?: () => void }) {
  const rows = waitingRows(docs);
  const read = useReadHeld();
  const keep = useKeepHeldPrivate();
  const wait = useWaitAgain();
  // the demo that only replays its recordings can't read new letters: say so before "Read these" is tried
  const canRead = useFolder().data?.can_read ?? true;
  if (!rows.length) return null;
  const ids = rows.map((r) => r.doc.id);
  const n = ids.length;
  const busy = read.isPending || keep.isPending;

  const readThem = () =>
    read
      .mutateAsync(ids)
      .then((res) => {
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
      })
      .catch(() => undefined); // the request's own error toast says what went wrong
  const keepThem = () =>
    keep
      .mutateAsync(ids)
      .then((res) => {
        const kept = res.documents.map((d) => d.id);
        const count = kept.length;
        toast.success(count === 1 ? "Kept private" : `Kept ${plural(count, "letter")} private`, {
          description: `${count === 1 ? "It stays" : "They stay"} on this computer and ${count === 1 ? "is" : "are"} never sent to Claude — nothing in ${count === 1 ? "it" : "them"} was read.`,
          undo: count
            ? () =>
                wait
                  .mutateAsync(kept)
                  .then((back) => void toast({ title: back.documents.length === 1 ? "It's back with the letters not read yet" : "They're back with the letters not read yet", tone: "info" }))
                  .catch(() => undefined)
            : undefined,
        });
        onAnswered?.();
      })
      .catch(() => undefined);

  return (
    <section aria-labelledby="waiting-title" className="mb-10">
      <SectionHeader
        id="waiting-title"
        icon={FolderInput}
        title={
          <>
            <span aria-hidden>
              From your folder — not read yet
              <span className="font-medium tabular-nums">{` · ${n}`}</span>
            </span>
            <span className="sr-only">{`From your folder — not read yet, ${plural(n, "letter")}`}</span>
          </>
        }
        description="Stored on this computer and not read yet — nothing has been sent to Claude."
      />
      <div className="card overflow-hidden">
        <ul className="divide-y divide-line" aria-label="Letters not read yet">
          {rows.map((row) => (
            <WaitingItem key={row.doc.id} row={row} />
          ))}
        </ul>
        <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-3 border-t border-line bg-surface-2/40 px-4 py-3 sm:px-5">
          <p className="mr-auto min-w-0 basis-full text-sm leading-5 text-muted sm:basis-auto sm:flex-1">
            {!canRead
              ? "This demo can't read new letters — it only replays the answers recorded for Sam's letters."
              : n === 1
                ? "Claude reads it like a letter you add."
                : "Claude reads them like letters you add."}{" "}
            <Link to="/settings?section=folder" className="font-medium text-accent underline-offset-2 hover:underline">
              Watched folder settings
            </Link>
          </p>
          {/* phones: the two answers share the row */}
          <div className="flex w-full gap-2 sm:w-auto">
            <AnswerButton size="sm" icon={Lock} onClick={keepThem} busy={keep.isPending} blocked={busy} className="max-sm:flex-1">
              Keep private
            </AnswerButton>
            <AnswerButton size="sm" variant="primary" icon={Sparkles} onClick={readThem} busy={read.isPending} blocked={busy} className="max-sm:flex-1">
              {readLabel(n)}
              {" "}
              <span className="sr-only">with Claude</span>
            </AnswerButton>
          </div>
        </div>
      </div>
    </section>
  );
}

function WaitingItem({ row }: { row: WaitingRow }) {
  const today = useTodayISO();
  const { doc, email, nested } = row;
  // an e-mail is named by its subject and sender (read on this computer); anything else by its file name
  const title = doc.title ?? doc.filename;
  const emailName = email ? (email.title ?? email.filename) : "";
  return (
    <li
      className={cn("group relative flex items-start gap-3.5 px-4 py-3.5 transition-colors hover:bg-surface-2/50 focus-within:bg-surface-2/50 sm:px-5", nested && "pl-10 sm:pl-12")}
    >
      <Thumb doc={doc} />
      <div className="min-w-0 flex-1">
        <Link
          to={`/documents/${doc.id}`}
          title={title === doc.filename ? title : `${title} (${doc.filename})`}
          className="line-clamp-2 break-words text-[14.5px] font-medium leading-snug text-ink outline-none [overflow-wrap:anywhere] after:absolute after:inset-0 after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-accent"
        >
          {protectRefs(title)}
        </Link>
        <p className="mt-1 text-sm leading-5 text-muted">
          {fileKindLabel(doc.mime)}
          {doc.pages > 1 ? ` · ${plural(doc.pages, "page")}` : ""} · <span className="whitespace-nowrap">added {formatDateTime(doc.created_at, { today })}</span>
        </p>
        {email ? (
          <p className="mt-0.5 line-clamp-2 text-sm leading-5 text-muted [overflow-wrap:anywhere]" title={`Attached to “${emailName}”`}>
            Attached to “{protectRefs(emailName)}”
          </p>
        ) : null}
      </div>
    </li>
  );
}
