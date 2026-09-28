/**
 * The letters list: grouped rows (being read → just read from New mail → last 7 days → months)
 * with a page thumbnail, title, sender, kind, arrival date, status (Please check / Private /
 * Possible scam / a live mini stepper while reading) and open to-dos.
 *
 * The layout follows the list's own width (container query), not the screen: stacked rows — the
 * title on up to two lines, then the sender and a wrapping line of chips — until the list is
 * 56rem wide; from there a table with kind, arrival date and to-do columns (the title on one line,
 * in full in its tooltip), and from 64rem the letter's summary next to the sender.
 */
import { Link } from "react-router";
import { useId, useMemo } from "react";
import { ListTodo, Lock, ShieldAlert } from "lucide-react";
import type { Document, MailTrayItem, Party } from "@/api/types";
import { useSuggestions } from "@/api/hooks";
import { useOpenedTrayDocs, useTrayByDoc } from "@/features/tour/newMail";
import { actionFromItem } from "@/features/today/selection";
import { ActionCountdown } from "@/features/today/TopThree";
import { api } from "@/api/endpoints";
import { useJobProgress } from "@/api/sse";
import { JOB_STAGE_COPY, PIPELINE_STEPS, copyFor, stageToStep } from "@/lib/copy";
import { formatDate } from "@/lib/format";
import { NBSP, protectRefs } from "@/lib/glue";
import { useTodayISO } from "@/lib/today";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { DateText } from "@/components/ui/DateText";
import { KindBadge } from "@/components/ui/KindBadge";
import { PartyChip } from "@/components/ui/PartyChip";
import { StatusPill } from "@/components/ui/StatusPill";
import { Stepper } from "@/components/ui/Stepper";
import { inboxDateInfo, isReading, pinJustRead, type LetterGroup, type OpenSummary } from "./filters";
import { useSeenLetters } from "./seen";

/** A next step this close (in days) is spelled out under the letter. */
const NEXT_STEP_DAYS = 14;

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
  const justRead = useOpenedTrayDocs();
  const seen = useSeenLetters();
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
  const shown = useMemo(() => pinJustRead(groups, justRead), [groups, justRead]);
  return (
    <div className="@container">
      {/* the page's h1 → this h2 → one h3 per group, with or without the New-mail tray above */}
      <h2 className="sr-only">Your letters</h2>
      <div className="space-y-7">
        {shown.map((g) => (
          <section key={g.key} aria-labelledby={`grp-${g.key}`}>
            <h3 id={`grp-${g.key}`} className="eyebrow mb-2 flex items-center gap-1.5">
              {g.label}
              <span aria-hidden className="font-medium tabular-nums">
                · {g.docs.length}
              </span>
              <span className="sr-only">{` (${g.docs.length} ${g.docs.length === 1 ? "letter" : "letters"})`}</span>
            </h3>
            <ul className="card divide-y divide-line overflow-hidden">
              {g.docs.map((d) => {
                const item = tray.get(d.id);
                return (
                  <LetterRow
                    key={d.id}
                    doc={d}
                    party={d.party_id ? parties.get(d.party_id) ?? null : null}
                    open={open.get(d.id)}
                    tray={item}
                    isNew={Boolean(item) && !isReading(d) && !seen.has(d.id)}
                    scam={scams.has(d.id)}
                  />
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

/** A small picture of the letter's first page (a lock on private ones). */
export function Thumb({ doc }: { doc: Document }) {
  const reading = isReading(doc);
  return (
    // a sheet of paper, dimmed in dark mode so 20 white pages don't glare off the dark card
    <span className="relative block h-[54px] w-10 shrink-0 overflow-hidden rounded-[4px] border border-line bg-white shadow-[0_1px_2px_rgb(0_0_0/0.06)] dark:border-line-strong dark:bg-surface-2">
      {doc.kind || !reading ? (
        <img
          src={api.thumbnailUrl(doc.id)}
          alt=""
          loading="lazy"
          decoding="async"
          className="absolute left-0 top-0 h-auto w-[170%] max-w-none dark:brightness-[0.8] dark:contrast-[1.05]"
        />
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

/**
 * The mini stepper of a letter being read, on a line of its own (the title never moves): the
 * step's name ("Checking…") next to it, what exactly happens in its tooltip ("Checking every fact
 * against the page") — the New-mail card above tells the whole story.
 */
function ReadingStatus({ doc }: { doc: Document }) {
  const job = useJobProgress(doc.id);
  const step = job?.status === "done" ? PIPELINE_STEPS.length : stageToStep(job?.stage);
  let name = doc.status === "queued" ? "Waiting to be read…" : "Reading…";
  if (job) name = step >= PIPELINE_STEPS.length ? JOB_STAGE_COPY.done.label : `${PIPELINE_STEPS[step]?.label ?? "Reading"}…`;
  const detail = job ? copyFor(JOB_STAGE_COPY, job.status === "done" ? "done" : (job.stage ?? "intake")).label : undefined;
  return (
    <div className="mt-2 flex min-w-0 items-center gap-2.5">
      <Stepper steps={PIPELINE_STEPS} current={step} size="sm" labels="none" className="w-24 shrink-0" label={`Reading ${doc.filename}`} />
      <span title={detail} className="line-clamp-2 min-w-0 text-xs text-muted">
        {name}
      </span>
    </div>
  );
}

/** "23_steuerbescheid_2025_p1.pdf" → "Steuerbescheid 2025 p1" (while a letter has no title yet). */
function readableFilename(name: string): string {
  const base = name.replace(/\.[a-z0-9]{2,4}$/i, "").replace(/[_-]+/g, " ").replace(/^\d+\s+/, "").trim();
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : "New letter";
}

function LetterRow({
  doc,
  party,
  open,
  tray,
  isNew,
  scam,
}: {
  doc: Document;
  party: Party | null;
  open?: OpenSummary;
  tray?: MailTrayItem;
  isNew: boolean;
  scam?: boolean;
}) {
  const today = useTodayISO();
  const describedBy = useId();
  const reading = isReading(doc);
  const next = scam || reading ? null : open?.next ?? null;
  // the same wording as Today: "transfer by Thu 1 Oct · in 3 days", "Thu 8 Oct, 10:30 · in 10 days"
  const action = next ? actionFromItem(next, { today }) : null;
  const urgent = action ? action.daysLeft <= NEXT_STEP_DAYS : false;
  // while it is being read a letter has no title yet: the tray's subject, else a tidy file name
  const title = doc.title ?? (tray ? `${tray.subject} — ${tray.sender}` : readableFilename(doc.filename));
  const todos = open?.count ? `${open.count} open ${open.count === 1 ? "to-do" : "to-dos"}` : null;

  const status = reading ? null : scam ? (
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
  const newBadge = (
    <Badge tone="accent" dot className="shrink-0">
      New
    </Badge>
  );

  return (
    <li className="group relative transition-colors hover:bg-surface-2/50 focus-within:bg-surface-2/50">
      <div className="grid grid-cols-[40px_minmax(0,1fr)] gap-x-3.5 px-4 py-3.5 sm:px-5 @4xl:grid-cols-[40px_minmax(0,1fr)_11rem_5.25rem_5.75rem] @4xl:items-center">
        <Thumb doc={doc} />
        <div className="min-w-0">
          <div className="flex min-w-0 items-start gap-2 @4xl:items-center">
            <Link
              to={`/documents/${doc.id}`}
              title={title}
              aria-describedby={todos ? describedBy : undefined}
              className="line-clamp-2 min-w-0 break-words text-[14.5px] font-medium leading-snug text-ink outline-none after:absolute after:inset-0 after:content-[''] focus-visible:after:rounded-none focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-accent @4xl:block @4xl:truncate"
            >
              {protectRefs(title)}
            </Link>
            {/* table rows: status and "New" after the title (stacked rows: on the chip line) */}
            {status ? <span className="hidden shrink-0 @4xl:inline-flex">{status}</span> : null}
            {isNew ? <span className="hidden shrink-0 @4xl:inline-flex">{newBadge}</span> : null}
            {/* the to-do count for a screen reader moving from letter to letter */}
            {todos ? (
              <span id={describedBy} hidden>
                {todos}
              </span>
            ) : null}
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-2 text-sm text-muted">
            {party ? (
              <PartyChip party={party} className="relative z-10 shrink-0 border-transparent bg-transparent py-0 pl-0 hover:bg-surface @5xl:max-w-[60%]" />
            ) : doc.party_id === null && !reading ? (
              <span className="shrink-0 text-muted">No sender</span>
            ) : null}
            {doc.summary ? (
              <span title={doc.summary} className="hidden min-w-0 flex-1 truncate @5xl:block">
                {doc.summary}
              </span>
            ) : null}
          </div>
          {reading ? <ReadingStatus doc={doc} /> : null}
          {/* stacked rows: the title gets the full width; "New", status, kind, arrival and to-dos wrap under the sender */}
          <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 empty:hidden @4xl:hidden">
            {isNew ? newBadge : null}
            {status}
            {doc.kind ? <KindBadge docKind={doc.kind} /> : null}
            {reading ? null : <ArrivalDate doc={doc} served={open?.served} className="text-sm text-muted" />}
            {open?.count ? <TodoCount open={open} urgent={urgent} /> : null}
          </div>
          {urgent && next && action ? (
            <p className="mt-1.5 text-[12.5px]">
              {/* the dot stays with the title; references never break at their hyphens */}
              <span className="text-muted">{`${protectRefs(next.title)}${NBSP}·`}</span>{" "}
              <ActionCountdown action={action} variant="text" className="text-[12.5px]" />
            </p>
          ) : null}
        </div>
        <div className="hidden min-w-0 @4xl:block">{doc.kind ? <KindBadge docKind={doc.kind} /> : null}</div>
        <div className="hidden text-right text-sm text-muted @4xl:block">
          <ArrivalDate doc={doc} served={open?.served} />
        </div>
        <div className="hidden justify-end @4xl:flex">{open?.count ? <TodoCount open={open} urgent={urgent} /> : null}</div>
      </div>
    </li>
  );
}

/**
 * When the letter arrived ("26 Sep") — the date its group is built from — with the letter's own
 * date in the tooltip ("Arrived Sat 26 Sep · letter dated Thu 24 Sep").
 */
function ArrivalDate({ doc, served, className }: { doc: Document; served?: boolean; className?: string }) {
  const today = useTodayISO();
  const { date, verb, docDate } = inboxDateInfo(doc, served);
  const tip = `${verb} ${formatDate(date, { today })}${docDate ? ` · letter dated ${formatDate(docDate, { today })}` : ""}`;
  return (
    <span title={tip} className={cn("whitespace-nowrap", className)}>
      <span className="sr-only">{verb} </span>
      <DateText date={date} style="day" />
    </span>
  );
}

/** "2 to-dos": what it counts, in words; the next one in its tooltip. */
function TodoCount({ open, urgent }: { open: OpenSummary; urgent: boolean }) {
  const noun = open.count === 1 ? "to-do" : "to-dos";
  const tip = `${open.count} open ${noun}${open.next ? ` · next: ${open.next.title}` : ""}`;
  return (
    <Badge tone={urgent ? "warn" : "neutral"} icon={ListTodo} title={tip} className="shrink-0 font-semibold tabular-nums">
      {open.count} {noun}
    </Badge>
  );
}
