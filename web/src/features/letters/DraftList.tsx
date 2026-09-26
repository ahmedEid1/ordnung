import { Link } from "react-router";
import { ChevronRight } from "lucide-react";
import type { Draft, Party } from "@/api/types";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { StatusPill } from "@/components/ui/StatusPill";
import { DRAFT_KIND_COPY, TONES, copyFor } from "@/lib/copy";
import { cn } from "@/lib/utils";
import { draftTitle, sentVia } from "./logic";

/** Tinted icon for a letter kind (cancellation / objection / reply). */
export function DraftKindIcon({ kind, size = "md", className }: { kind: Draft["kind"]; size?: "sm" | "md" | "lg"; className?: string }) {
  const c = copyFor(DRAFT_KIND_COPY, kind);
  const t = TONES[c.tone];
  const Icon = c.icon;
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center",
        size === "sm" ? "size-7 rounded-md [&>svg]:size-3.5" : size === "md" ? "size-10 rounded-xl [&>svg]:size-[18px]" : "size-12 rounded-xl [&>svg]:size-5",
        t.soft,
        t.icon,
        className,
      )}
    >
      <Icon />
    </span>
  );
}

/** One letter in the list: kind, recipient, German subject, status and the important date. */
export function DraftRow({ draft, party }: { draft: Draft; party?: Party | null }) {
  const sendBy = draft.status !== "sent" ? draft.send_guidance?.send_by : null;
  return (
    <li>
      <Link
        to={`/letters/${draft.id}`}
        className="group flex items-center gap-3.5 px-4 py-3.5 transition-colors hover:bg-surface-2/60 focus-visible:bg-surface-2/60 sm:px-5"
      >
        <DraftKindIcon kind={draft.kind} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14.5px] font-medium text-ink">{draftTitle(draft, party?.name)}</span>
          <span lang={draft.language} className="mt-0.5 block truncate text-[13px] text-muted">
            {draft.subject || "No subject yet"}
          </span>
          <span className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-muted sm:hidden">
            <StatusPill of="draft" status={draft.status} />
            {sendBy ? <Countdown date={sendBy} prefix="send by" /> : null}
          </span>
        </span>
        <span className="hidden shrink-0 flex-col items-end gap-1.5 sm:flex">
          <StatusPill of="draft" status={draft.status} />
          {draft.status === "sent" && draft.sent_at ? (
            <span className="text-[12.5px] text-muted">
              <DateText date={draft.sent_at.slice(0, 10)} style="day" /> {sentVia(draft.sent_channel)}
            </span>
          ) : sendBy ? (
            <Countdown date={sendBy} prefix="send by" className="text-[12.5px]" />
          ) : (
            <span className="text-[12.5px] text-muted">
              Started <DateText date={draft.created_at.slice(0, 10)} style="day" />
            </span>
          )}
        </span>
        <ChevronRight className="size-4 shrink-0 text-faint transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none" aria-hidden />
      </Link>
    </li>
  );
}

export function DraftGroup({ title, drafts, parties, id }: { title: string; drafts: Draft[]; parties: Map<string, Party>; id: string }) {
  if (!drafts.length) return null;
  return (
    <section aria-labelledby={id} className="mb-8">
      <h2 id={id} className="mb-2.5 px-1 text-[12.5px] font-semibold uppercase tracking-[0.07em] text-muted">
        {title} <span className="font-medium text-muted">· {drafts.length}</span>
      </h2>
      <ul className="card divide-y divide-line overflow-hidden">
        {drafts.map((d) => (
          <DraftRow key={d.id} draft={d} party={d.party_id ? parties.get(d.party_id) : null} />
        ))}
      </ul>
    </section>
  );
}
