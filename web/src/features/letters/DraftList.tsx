import { Link } from "react-router";
import { ChevronRight } from "lucide-react";
import type { Draft, Party } from "@/api/types";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { SectionHeader } from "@/components/ui/SectionHeader";
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

/**
 * One letter in the list: kind, recipient, German subject, status and the important date. The list is a
 * container: a roomy one (from 36rem) puts the status and date in a column on the right, a narrow one
 * (a phone, or beside the "How letters work" card) under the subject — the same facts either way, and the
 * title is never squeezed out by them (UI audit round 1).
 */
export function DraftRow({ draft, party }: { draft: Draft; party?: Party | null }) {
  const sendBy = draft.status !== "sent" ? draft.send_guidance?.send_by : null;
  const title = draftTitle(draft, party?.name);
  const subject = draft.subject || "No subject yet";
  return (
    <li>
      <Link
        to={`/letters/${draft.id}`}
        data-draft-row
        className={cn(
          "group grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3.5 gap-y-1.5 px-4 py-3.5 transition-colors hover:bg-surface-2/60 sm:px-5",
          "@xl/drafts:grid-cols-[auto_minmax(0,1fr)_auto_auto]",
          // drawn inside the row (the card clips what sticks out), rounded like the card's corners
          "focus-visible:-outline-offset-2 focus-visible:rounded-[calc(var(--radius-card)-1px)] focus-visible:bg-surface-2/60",
        )}
      >
        <DraftKindIcon kind={draft.kind} className="row-span-2 @xl/drafts:row-span-1" />
        <span className="min-w-0">
          <span title={title} className="line-clamp-2 break-words text-[14.5px] font-medium leading-snug text-ink">
            {title}
          </span>
          <span lang={draft.language} title={subject} className="mt-0.5 block truncate text-[13px] text-muted">
            {subject}
          </span>
        </span>
        <span
          data-draft-meta
          className={cn(
            "col-start-2 row-start-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] leading-5 text-muted",
            "@xl/drafts:col-start-3 @xl/drafts:row-start-1 @xl/drafts:max-w-52 @xl/drafts:flex-col @xl/drafts:items-end @xl/drafts:gap-1.5 @xl/drafts:text-right",
          )}
        >
          <StatusPill of="draft" status={draft.status} />
          {draft.status === "sent" && draft.sent_at ? (
            <span>
              <DateText date={draft.sent_at.slice(0, 10)} style="day" /> {sentVia(draft.sent_channel)}
            </span>
          ) : sendBy ? (
            <Countdown date={sendBy} prefix="Send by" />
          ) : (
            <span>
              Started <DateText date={draft.created_at.slice(0, 10)} style="day" />
            </span>
          )}
        </span>
        <ChevronRight
          className="col-start-3 row-span-2 row-start-1 size-4 text-faint transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none @xl/drafts:col-start-4 @xl/drafts:row-span-1"
          aria-hidden
        />
      </Link>
    </li>
  );
}

export function DraftGroup({ title, drafts, parties, id }: { title: string; drafts: Draft[]; parties: Map<string, Party>; id: string }) {
  if (!drafts.length) return null;
  return (
    // no margin after the last group: the page's grid gap follows it
    <section aria-labelledby={id} className="mb-8 last:mb-0">
      {/* the app's one section label (13 px), flush with the page title and the cards (UI audit round 2) */}
      <SectionHeader id={id} title={title} count={drafts.length} className="mb-2.5" />
      <ul className="card @container/drafts divide-y divide-line overflow-hidden">
        {drafts.map((d) => (
          <DraftRow key={d.id} draft={d} party={d.party_id ? parties.get(d.party_id) : null} />
        ))}
      </ul>
    </section>
  );
}
