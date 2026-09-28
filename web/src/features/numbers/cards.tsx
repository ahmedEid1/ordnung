/**
 * The cards of My numbers: an identity document with its expiry, an open case with the references to
 * quote, and a call sheet per organisation (contact, your numbers, its open cases, its own numbers).
 */
import { Link } from "react-router";
import { AtSign, CalendarClock, ChevronRight, ExternalLink, FileText, Globe, Phone, TriangleAlert } from "lucide-react";
import type { CallSheet, IdentityDocument, OpenCase } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { Countdown } from "@/components/ui/Countdown";
import { KindIcon } from "@/components/ui/KindBadge";
import { mailtoUrl, websiteUrl } from "@/features/party/timeline";
import { usePartyDrawer } from "@/lib/party-drawer";
import { glueText } from "@/lib/format";
import { useFormatDate, useTodayISO } from "@/lib/today";
import { cn, plural } from "@/lib/utils";
import { NumberRow, Sep } from "./NumberRow";

const letterHref = (id: string) => `/documents/${encodeURIComponent(id)}`;

/** A link to a letter, as the cards write it: "Last letter: Payslip for August 2026 · 31 Aug". */
function LetterLink({ id, title, date, prefix }: { id: string; title: string; date?: string | null; prefix: string }) {
  const formatDate = useFormatDate();
  return (
    <p className="flex min-w-0 items-start gap-1.5 text-[12.5px] leading-5 text-muted">
      <FileText className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span className="min-w-0">
        {prefix}{" "}
        <Link to={letterHref(id)} className="rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent [overflow-wrap:anywhere]">
          {glueText(title)}
        </Link>
        {date ? (
          <>
            <Sep />
            <span className="whitespace-nowrap">{formatDate(date, { style: "day" })}</span>
          </>
        ) : null}
      </span>
    </p>
  );
}

const DOCUMENT_STATUS: Record<IdentityDocument["status"], { label: string; tone: "ok" | "warn" | "danger" | "neutral" }> = {
  ok: { label: "Valid", tone: "ok" },
  renew_soon: { label: "Renew soon", tone: "warn" },
  expired: { label: "Expired", tone: "danger" },
  unknown: { label: "Expiry unknown", tone: "neutral" },
};

export function DocumentCard({ doc }: { doc: IdentityDocument }) {
  const formatDate = useFormatDate();
  const status = DOCUMENT_STATUS[doc.status];
  return (
    <Card as="article" padding="md" accent={doc.status === "expired" ? "danger" : doc.status === "renew_soon" ? "warn" : undefined} className="flex min-w-0 flex-1 flex-col">
      <div className="flex items-start gap-3">
        <KindIcon docKind={doc.kind === "residence_permit" ? "residence_permit" : "identity_document"} />
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-6 text-ink">{doc.name}</h3>
          {doc.valid_until ? (
            <p className="flex flex-wrap items-center gap-x-2 text-[13px] leading-5 text-muted">
              <span className="inline-flex items-center gap-1">
                <CalendarClock className="size-3.5 shrink-0" aria-hidden />
                <span>
                  Valid until <span className="whitespace-nowrap">{formatDate(doc.valid_until, { style: "medium" })}</span>
                </span>
              </span>
              <Countdown date={doc.valid_until} mode="event" className="text-[13px]" />
            </p>
          ) : (
            <p className="text-[13px] leading-5 text-muted">No expiry date in your letters</p>
          )}
        </div>
        <Badge tone={status.tone} className="shrink-0">
          {status.label}
        </Badge>
      </div>
      {/* the card's full width: beside the badge it would be a narrow column on a phone */}
      {doc.valid_until && doc.needs_check ? <Unconfirmed what="this date" className="mt-2" /> : null}
      {doc.number ? (
        <NumberRow number={doc.number} showLetter={false} className="mt-1 border-t border-line" />
      ) : (
        <p className="mt-3 border-t border-line pt-3 text-[13px] leading-5 text-muted">The number isn't in your letters yet — it's on the card or in the passport itself.</p>
      )}
      {doc.note ? <p className="mt-1 text-[13px] leading-5 text-ink/80">{doc.note}</p> : null}
      {doc.letter ? (
        <div className="mt-auto pt-3">
          <LetterLink prefix="From" id={doc.letter.id} title={doc.letter.title} date={doc.letter.date} />
        </div>
      ) : null}
    </Card>
  );
}

/** "Compare this date with the letter": Ordnung could not confirm it (read by AI from a photo, not found). */
function Unconfirmed({ what, className }: { what: string; className?: string }) {
  return (
    <p className={cn("mt-0.5 flex items-start gap-1 text-[12.5px] leading-5 text-warn-ink", className)}>
      <TriangleAlert className="mt-[3px] size-3.5 shrink-0" aria-hidden />
      <span>Compare {what} with the letter: Ordnung couldn't confirm it.</span>
    </p>
  );
}

type CaseStep = NonNullable<OpenCase["next_item"]>;

/** To-dos that can be overdue (`triggers.OVERDUE_KINDS`); an appointment or reminder that passed just happened. */
const OVERDUE_KINDS = new Set<CaseStep["kind"]>(["deadline", "payment", "task"]);

/**
 * The day a case's next step shows, by the weekly session's rule (`secretary/week.py`, "The day on a
 * row"): an appointment — and a fee paid at it — *on* its day; else *by* the day to act (the send-by day
 * when it comes first); once that day has passed but the due date has not, *act today* with the due
 * date; once the due date has passed, *overdue*, counted from the due date.
 */
export type NextWhen =
  | { kind: "on" | "by" | "past"; date: string }
  | { kind: "act_today"; due: string | null }
  | { kind: "overdue"; due: string };

export function nextStepWhen(item: Pick<CaseStep, "kind" | "due_date" | "send_by" | "at_appointment">, today: string): NextWhen | null {
  const { due_date: due, send_by: send } = item;
  if (item.kind === "appointment" || item.kind === "reminder" || item.at_appointment) return due ? { kind: "on", date: due } : null;
  if (due && due < today) return OVERDUE_KINDS.has(item.kind) ? { kind: "overdue", due } : { kind: "past", date: due };
  if (send && send < today) return { kind: "act_today", due };
  const day = send && (!due || send <= due) ? send : due;
  return day ? { kind: "by", date: day } : null;
}

function NextDay({ when }: { when: NextWhen }) {
  const formatDate = useFormatDate();
  switch (when.kind) {
    case "overdue":
      return <Countdown date={when.due} prefix="due" className="text-[13px]" />;
    case "act_today":
      return when.due ? <Countdown date={when.due} prefix="act today — due" className="text-[13px]" /> : <span className="font-medium text-danger-ink">act today</span>;
    case "past":
      return <Countdown date={when.date} mode="event" showDate className="text-[13px]" />;
    default:
      return (
        <span className="whitespace-nowrap text-muted">
          {when.kind} {formatDate(when.date)}
        </span>
      );
  }
}

/** "Next: Pay the fine · by Thu 1 Oct" (a fee paid at the appointment: on its day; "act today — due …" once the day to act passed; overdue from the due date). */
function NextStep({ item }: { item: CaseStep }) {
  const today = useTodayISO();
  const when = nextStepWhen(item, today);
  return (
    <>
      <p className="text-[13px] leading-5 text-ink/85">
        <span className="font-medium text-ink">Next:</span> <span className="[overflow-wrap:anywhere]">{glueText(item.title)}</span>
        {when ? (
          <>
            <Sep />
            <NextDay when={when} />
          </>
        ) : null}
      </p>
      {item.needs_check ? <Unconfirmed what="it" /> : null}
    </>
  );
}

export function OpenCaseCard({ found, showParty = true }: { found: OpenCase; showParty?: boolean }) {
  const drawer = usePartyDrawer();
  return (
    <Card as="article" padding="md" className="flex min-w-0 flex-1 flex-col">
      <h3 className="text-[15px] font-semibold leading-6 text-ink [overflow-wrap:anywhere]">{glueText(found.title)}</h3>
      {showParty && found.party_name ? (
        <p className="text-[13px] leading-5 text-muted">
          {found.party_id ? (
            <button type="button" onClick={() => drawer.open(found.party_id!)} className="inline min-h-6 rounded text-left font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent [overflow-wrap:anywhere]">
              {glueText(found.party_name)}
            </button>
          ) : (
            glueText(found.party_name)
          )}
          {found.open_items > 1 ? (
            <>
              <Sep />
              <span className="whitespace-nowrap">{plural(found.open_items, "open to-do")}</span>
            </>
          ) : null}
        </p>
      ) : null}
      {found.next_item ? (
        <div className="mt-2">
          <NextStep item={found.next_item} />
        </div>
      ) : null}
      <ul className="mt-1 divide-y divide-line" aria-label="References to quote">
        {found.references.map((ref) => (
          <li key={ref.key}>
            <NumberRow number={ref} showLetter={Boolean(ref.letter && ref.letter.id !== found.letter?.id)} compactLetter />
          </li>
        ))}
      </ul>
      {found.letter ? (
        <div className="mt-auto border-t border-line pt-3">
          <LetterLink prefix="Latest letter" id={found.letter.id} title={found.letter.title} date={found.letter.date} />
        </div>
      ) : null}
    </Card>
  );
}

function Contact({ sheet }: { sheet: CallSheet }) {
  const mailto = mailtoUrl(sheet.email);
  const site = websiteUrl(sheet.website);
  if (!sheet.phone && !sheet.email && !site) {
    return <p className="text-[13px] leading-5 text-muted">No phone or e-mail in their letters.</p>;
  }
  const link = "inline-flex min-h-6 min-w-0 items-center rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent";
  return (
    <ul className="flex flex-col gap-1 text-[13.5px]" aria-label="Contact">
      {sheet.phone ? (
        <li className="flex items-center gap-2">
          <Phone className="size-4 shrink-0 text-muted" aria-hidden />
          <a href={`tel:${sheet.phone.replace(/[^\d+]/g, "")}`} className={link}>
            {sheet.phone}
          </a>
        </li>
      ) : null}
      {sheet.email ? (
        <li className="flex items-center gap-2">
          <AtSign className="size-4 shrink-0 text-muted" aria-hidden />
          {mailto ? (
            <a href={mailto} className={link}>
              <span className="min-w-0 [overflow-wrap:anywhere]">{sheet.email}</span>
            </a>
          ) : (
            <span className="min-w-0 text-ink [overflow-wrap:anywhere]">{sheet.email}</span>
          )}
        </li>
      ) : null}
      {site ? (
        <li className="flex items-center gap-2">
          <Globe className="size-4 shrink-0 text-muted" aria-hidden />
          <a href={site} target="_blank" rel="noreferrer noopener" className={cn(link, "gap-1")}>
            <span className="min-w-0 [overflow-wrap:anywhere]">{sheet.website?.replace(/^https?:\/\//, "")}</span>
            <ExternalLink className="size-3 shrink-0" aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        </li>
      ) : null}
    </ul>
  );
}

export function CallSheetCard({ sheet, openTheirs = false }: { sheet: CallSheet; openTheirs?: boolean }) {
  const drawer = usePartyDrawer();
  const headingId = `sheet-${sheet.party_id}`;
  return (
    <Card as="article" padding="md" aria-labelledby={headingId} className="flex min-w-0 flex-1 flex-col">
      <div className="flex items-start gap-3">
        <KindIcon partyKind={sheet.kind} />
        <div className="min-w-0 flex-1">
          <h3 id={headingId} className="text-[15px] font-semibold leading-6 text-ink [overflow-wrap:anywhere]">
            <button type="button" onClick={() => drawer.open(sheet.party_id)} className="rounded text-left outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent">
              {glueText(sheet.name)}
            </button>
          </h3>
          {sheet.open_items ? <p className="text-[13px] leading-5 text-muted">{plural(sheet.open_items, "open to-do")}</p> : null}
        </div>
      </div>
      <div className="mt-3">
        <Contact sheet={sheet} />
      </div>
      {sheet.numbers.length ? (
        <div className="mt-3 border-t border-line">
          {/* each number says which letter it is from when that is not the last letter named below */}
          <ul className="divide-y divide-line">
            {sheet.numbers.map((n) => (
              <li key={n.key}>
                <NumberRow number={n} showLetter={Boolean(n.letter && n.letter.id !== sheet.last_letter?.id)} compactLetter />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {sheet.open_cases.map((found) => (
        <div key={found.key} className="mt-1 rounded-lg bg-surface-2/70 px-3 pt-2">
          <p className="text-[12px] font-semibold uppercase tracking-[0.06em] text-muted">Open case</p>
          <p className="text-[13.5px] font-medium leading-5 text-ink [overflow-wrap:anywhere]">{glueText(found.title)}</p>
          {found.next_item ? <NextStep item={found.next_item} /> : null}
          <ul className="divide-y divide-line">
            {found.references.map((ref) => (
              <li key={ref.key}>
                <NumberRow number={ref} showLetter={Boolean(ref.letter && ref.letter.id !== sheet.last_letter?.id)} compactLetter />
              </li>
            ))}
          </ul>
        </div>
      ))}
      {sheet.their_numbers.length ? (
        // open when a search matched only here, so the person sees why the sheet was found
        <details key={openTheirs ? "open" : "closed"} open={openTheirs} className="group mt-3 border-t border-line pt-2">
          <summary className="inline-flex min-h-8 cursor-pointer list-none items-center gap-1 rounded text-[13px] font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent [&::-webkit-details-marker]:hidden">
            <ChevronRight className="size-4 shrink-0 transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden />
            Their own numbers ({sheet.their_numbers.length})
          </summary>
          <p className="mt-1 text-[12.5px] leading-5 text-muted">Registry, tax and bank numbers of {sheet.name} — not yours, but handy to recognise their letters and direct debits.</p>
          <ul className="divide-y divide-line">
            {sheet.their_numbers.map((n) => (
              <li key={n.key}>
                <NumberRow number={n} masked={false} showLetter={false} />
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {sheet.last_letter ? (
        <div className="mt-auto pt-3">
          <LetterLink prefix="Last letter" id={sheet.last_letter.id} title={sheet.last_letter.title} date={sheet.last_letter.date} />
        </div>
      ) : null}
    </Card>
  );
}
