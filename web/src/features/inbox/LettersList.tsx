/**
 * The letters list: month-grouped rows with a page thumbnail, sender, title, kind, letter date,
 * status (Please check / Private / live mini stepper while reading) and open to-dos.
 */
import { Link } from "react-router";
import { useMemo } from "react";
import { ListTodo, Lock, ShieldAlert } from "lucide-react";
import type { Document, MailTrayItem, Party } from "@/api/types";
import { useSuggestions } from "@/api/hooks";
import { isDirectDebit } from "@/lib/payments";
import { useTrayByDoc } from "@/features/tour/newMail";
import { api } from "@/api/endpoints";
import { useJobProgress } from "@/api/sse";
import { JOB_STAGE_COPY, PIPELINE_STEPS, copyFor, stageToStep } from "@/lib/copy";
import { cn } from "@/lib/utils";
import { daysUntil } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { Badge } from "@/components/ui/Badge";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { KindBadge } from "@/components/ui/KindBadge";
import { PartyChip } from "@/components/ui/PartyChip";
import { StatusPill } from "@/components/ui/StatusPill";
import { Stepper } from "@/components/ui/Stepper";
import { Tooltip } from "@/components/ui/Tooltip";
import { isReading, type LetterGroup, type OpenSummary } from "./filters";

export function LettersList({
  groups,
  parties,
  open,
}: {
  groups: LetterGroup[];
  parties: Map<string, Party>;
  open: Map<string, OpenSummary>;
}) {
  const tray = useTrayByDoc();
  const suggestions = useSuggestions();
  // letters with an open scam warning never show a countdown to pay
  const scams = useMemo(
    () =>
      new Set(
        (suggestions.data ?? [])
          .filter((s) => s.kind === "scam" && s.status !== "dismissed" && s.status !== "expired")
          .flatMap((s) => s.refs.filter((r) => r.type === "document").map((r) => r.id)),
      ),
    [suggestions.data],
  );
  return (
    <div className="space-y-7">
      {groups.map((g) => (
        <section key={g.key} aria-labelledby={`grp-${g.key}`}>
          <h3 id={`grp-${g.key}`} className="mb-2 flex items-center gap-2 px-1 text-[12.5px] font-semibold uppercase tracking-[0.07em] text-muted">
            {g.label}
            <span className="font-medium tabular-nums text-muted">· {g.docs.length}</span>
          </h3>
          <ul className="card divide-y divide-line overflow-hidden">
            {g.docs.map((d) => (
              <LetterRow
                key={d.id}
                doc={d}
                party={d.party_id ? parties.get(d.party_id) ?? null : null}
                open={open.get(d.id)}
                tray={tray.get(d.id)}
                scam={scams.has(d.id)}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Thumb({ doc }: { doc: Document }) {
  const reading = isReading(doc);
  return (
    <span className="relative block h-[54px] w-10 shrink-0 overflow-hidden rounded-[4px] border border-line bg-white shadow-[0_1px_2px_rgb(0_0_0/0.06)]">
      {doc.kind || !reading ? (
        <img src={api.thumbnailUrl(doc.id)} alt="" loading="lazy" decoding="async" className="absolute left-0 top-0 h-auto w-[170%] max-w-none dark:brightness-[0.92]" />
      ) : null}
      {reading ? <span className="absolute inset-0 animate-pulse bg-accent-soft/70 motion-reduce:animate-none" aria-hidden /> : null}
      {doc.ai_private ? (
        <span className="absolute bottom-0.5 right-0.5 grid size-4 place-items-center rounded-full bg-ink/80 text-canvas">
          <Lock className="size-2.5" aria-hidden />
        </span>
      ) : null}
    </span>
  );
}

function ReadingStatus({ doc }: { doc: Document }) {
  const job = useJobProgress(doc.id);
  const step = job?.status === "done" ? PIPELINE_STEPS.length : stageToStep(job?.stage);
  const label = job ? `${copyFor(JOB_STAGE_COPY, job.stage ?? "intake").label}…` : doc.status === "queued" ? "Waiting to be read…" : "Reading…";
  return (
    <div className="flex w-full min-w-0 items-center gap-2.5 sm:w-auto">
      <Stepper steps={PIPELINE_STEPS} current={step} size="sm" labels="none" className="w-24 shrink-0" label={`Reading ${doc.filename}`} />
      <span className="truncate text-[12px] text-muted">{label}</span>
    </div>
  );
}

/** "23_steuerbescheid_2025_p1.pdf" → "Steuerbescheid 2025 p1" (while a letter has no title yet). */
function readableFilename(name: string): string {
  const base = name.replace(/\.[a-z0-9]{2,4}$/i, "").replace(/[_-]+/g, " ").replace(/^\d+\s+/, "").trim();
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : "New letter";
}

function LetterRow({ doc, party, open, tray, scam }: { doc: Document; party: Party | null; open?: OpenSummary; tray?: MailTrayItem; scam?: boolean }) {
  const today = useTodayISO();
  const reading = isReading(doc);
  const next = scam ? null : open?.next;
  const nextDate = next ? (next.send_by ?? next.due_date) : null;
  const urgent = nextDate ? daysUntil(nextDate, today) <= 14 : false;
  // while it is being read a letter has no title yet: the tray's subject, else a tidy file name
  const title = doc.title ?? (tray ? `${tray.subject} — ${tray.sender}` : readableFilename(doc.filename));

  const status = reading ? (
    <ReadingStatus doc={doc} />
  ) : scam ? (
    <Badge tone="danger" icon={ShieldAlert}>
      Possible scam
    </Badge>
  ) : doc.status === "needs_review" || doc.status === "failed" ? (
    <StatusPill of="document" status={doc.status} />
  ) : doc.ai_private ? (
    <Badge tone="neutral" icon={Lock}>
      Private
    </Badge>
  ) : null;

  return (
    <li className="group relative transition-colors hover:bg-surface-2/50 focus-within:bg-surface-2/50">
      <div className="grid grid-cols-[40px_minmax(0,1fr)] gap-x-3.5 px-4 py-3.5 sm:px-5 md:grid-cols-[40px_minmax(0,1fr)_10.5rem_5.25rem_3.5rem] md:items-center">
        <Thumb doc={doc} />
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <Link
              to={`/documents/${doc.id}`}
              className="truncate text-[14.5px] font-medium text-ink outline-none after:absolute after:inset-0 after:content-[''] focus-visible:after:rounded-none focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-accent"
            >
              {title}
            </Link>
            {status ? <span className="hidden shrink-0 sm:inline-flex">{status}</span> : null}
            {tray && !reading ? (
              <Badge tone="accent" dot className="shrink-0">
                New
              </Badge>
            ) : null}
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-2 text-[13px] text-muted">
            {party ? (
              <PartyChip party={party} className="relative z-10 shrink-0 border-transparent bg-transparent py-0 pl-0 hover:bg-surface" />
            ) : doc.party_id === null && !reading ? (
              <span className="shrink-0 text-muted">No sender</span>
            ) : null}
            {doc.summary ? <span className="hidden truncate lg:inline">{doc.summary}</span> : null}
          </div>
          {/* phone: meta line */}
          <div className="mt-2 flex flex-wrap items-center gap-1.5 md:hidden">
            {status ? <span className="sm:hidden">{status}</span> : null}
            {doc.kind ? <KindBadge docKind={doc.kind} /> : null}
            {doc.doc_date ? <DateText date={doc.doc_date} style="day" className="text-[12.5px] text-muted" /> : null}
            {open?.count ? <TodoCount open={open} urgent={urgent} /> : null}
          </div>
          {urgent && next?.due_date && !reading ? (
            <p className="mt-1.5 text-[12.5px]">
              <span className="text-muted">{next.title} · </span>
              <Countdown
                date={isDirectDebit(next) ? next.due_date : next.send_by ?? next.due_date}
                prefix={isDirectDebit(next) ? "collected" : next.send_by ? (next.kind === "payment" ? "transfer by" : "send by") : undefined}
                className="text-[12.5px]"
              />
            </p>
          ) : null}
        </div>
        <div className="hidden min-w-0 md:block">{doc.kind ? <KindBadge docKind={doc.kind} /> : null}</div>
        <div className="hidden text-right text-[13px] text-muted md:block">
          {doc.doc_date ? <DateText date={doc.doc_date} style="day" /> : <span aria-hidden>—</span>}
        </div>
        <div className="hidden justify-end md:flex">{open?.count ? <TodoCount open={open} urgent={urgent} /> : null}</div>
      </div>
    </li>
  );
}

function TodoCount({ open, urgent }: { open: OpenSummary; urgent: boolean }) {
  const label = `${open.count} open ${open.count === 1 ? "to-do" : "to-dos"}`;
  return (
    <Tooltip content={open.next ? `${label} · next: ${open.next.title}` : label}>
      <span
        tabIndex={0}
        className={cn(
          "relative z-10 inline-flex h-[22px] items-center gap-1 rounded-full px-2 text-[12px] font-semibold tabular-nums",
          urgent ? "bg-warn-soft text-warn-ink" : "bg-surface-2 text-ink/75",
        )}
        aria-label={label}
      >
        <ListTodo className="size-3" aria-hidden />
        {open.count}
        <span aria-hidden className="hidden font-medium xl:inline">{open.count === 1 ? "to-do" : "to-dos"}</span>
      </span>
    </Tooltip>
  );
}
