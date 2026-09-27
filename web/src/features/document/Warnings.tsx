/**
 * Everything that needs the person's eyes, right under the verdict: the scam banner, the
 * hidden-text banner, the "get advice" card of a high-stakes letter (a court order, a dismissal, a
 * landlord's letter), "get advice" when the letter can only be challenged in court (or it is
 * unclear how), "Please check" to-dos, the "When did this letter arrive?" question and any other
 * warnings from reading the letter.
 */
import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { ArrowRight, CalendarCheck, Check, EyeOff, Pencil, Scale, ShieldAlert, TriangleAlert, X } from "lucide-react";
import type { Document, DocumentDetail, Item, Suggestion } from "@/api/types";
import { api } from "@/api/endpoints";
import { qk, useUpdateDocument, useUpdateSuggestion } from "@/api/hooks";
import { cn } from "@/lib/utils";
import { GROUNDING_COPY } from "@/lib/copy";
import { formatDate, toISODate } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { ADVICE_LINKS } from "@/components/ui/Disclaimer";
import { Glossary } from "@/components/ui/Glossary";
import { Input } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { arrivalSavedNote, isServed, MAY_BE_PUBLIC_KINDS, needsArrivalDate, needsCheck, scamSuggestion } from "./verdict";
import { useItemActions } from "./actions";
import { useEvidence } from "./EvidenceContext";
import { LetterAdviceCard } from "./LetterAdvice";

export const SAFE_NOTE = "No warning does not mean it is safe.";

const isHiddenTextWarning = (w: string) => /invisible text|hidden text/i.test(w);

/** A reading's warning that only repeats the arrival question ("…when it arrived", "…when it was delivered"). */
export const REPEATS_ARRIVAL_QUESTION = /arriv|received|zugang|deliver|zustell/i;

/** Warnings shown in the scam banner / generic list (the hidden-text one has its own banner). */
function otherWarnings(doc: Document): string[] {
  return doc.warnings.filter((w) => w.trim() && w.trim() !== SAFE_NOTE && !(doc.hidden_text && isHiddenTextWarning(w)));
}

export function DocumentWarnings({ detail }: { detail: DocumentDetail }) {
  const doc = detail.document;
  const scam = scamSuggestion(detail);
  const checks = detail.items.filter(needsCheck);
  const arrival = detail.items.filter((i) => needsArrivalDate(i, doc));
  const remedy = doc.remedy?.type;
  const warnings = otherWarnings(doc);
  // the arrival question already explains the "we don't know when it arrived / was delivered" warning — and
  // once the person has dealt with the letter (objected, paid), when it arrived no longer matters
  const general =
    arrival.length || detail.advice?.handled ? warnings.filter((w) => !REPEATS_ARRIVAL_QUESTION.test(w)) : warnings;

  // a high-stakes letter's own card replaces the generic "get advice" one; urgent cards go first
  const advice = detail.advice && !scam ? <LetterAdviceCard key="letter-advice" advice={detail.advice} doc={doc} /> : null;
  const urgent = Boolean(detail.advice?.urgent);

  const blocks = [
    scam ? <ScamBanner key="scam" suggestion={scam} doc={doc} reasons={warnings} /> : null,
    doc.hidden_text ? <HiddenTextBanner key="hidden" /> : null,
    urgent ? advice : null,
    !detail.advice && (remedy === "klage" || remedy === "unclear") ? <AdviceCard key="advice" type={remedy} addressee={doc.remedy?.addressee ?? null} /> : null,
    arrival.length ? (
      <ArrivalQuestion key="arrival" doc={doc} items={arrival} mayBePublic={Boolean(detail.party && MAY_BE_PUBLIC_KINDS.includes(detail.party.kind))} />
    ) : null,
    ...checks.map((it) => <PleaseCheckItem key={it.id} item={it} />),
    !scam && general.length ? <GeneralWarnings key="general" warnings={general} /> : null,
    urgent ? null : advice,
  ].filter(Boolean);

  if (!blocks.length) return null;
  return (
    <section aria-label="Warnings and things to check" className="space-y-3">
      {blocks}
    </section>
  );
}

// ------------------------------------------------------------------------------------------------

/** Scam signs shown before "Show all": the few that say most. */
const TOP_SIGNS = 3;

/**
 * The letter's scam signs, strongest first: a payee/IBAN that doesn't match the sender comes
 * first, then signs about the money, then the rest. "Please check" notes aren't scam signs.
 */
function scamSigns(reasons: string[]): string[] {
  const rank = (w: string) =>
    /^possible scam/i.test(w) ? 0 : /iban|payee|account|bank/i.test(w) ? 1 : /deadline|hours|threat|pressure|not to contact/i.test(w) ? 2 : 3;
  return reasons.filter((w) => !/^please check\b/i.test(w)).sort((a, b) => rank(a) - rank(b));
}

function ScamBanner({ suggestion, doc, reasons }: { suggestion: Suggestion; doc: Document; reasons: string[] }) {
  const update = useUpdateSuggestion();
  const [all, setAll] = useState(false);
  const real = suggestion.refs.find((r) => r.type === "document" && r.id !== doc.id);
  const signs = scamSigns(reasons);
  const shown = all ? signs : signs.slice(0, TOP_SIGNS);
  return (
    <div role="alert" className="overflow-hidden rounded-2xl border border-danger/35 bg-danger-soft">
      <div className="flex gap-3 px-4 pb-3 pt-4 sm:px-5">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-danger text-white dark:text-canvas">
          <ShieldAlert className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-[15.5px] font-semibold leading-snug text-danger-ink">This looks like a scam — don't pay</h2>
          <p className="mt-1.5 text-[14px] leading-relaxed text-ink/85">
            Don't pay or reply until you've checked with the sender using contact details you already know — not the ones in this letter.
          </p>
          {shown.length ? (
            <>
              <h3 className="mt-3 text-[12px] font-semibold uppercase tracking-[0.07em] text-danger-ink/80">
                {signs.length === 1 ? "The warning sign" : all || signs.length <= TOP_SIGNS ? `${signs.length} warning signs` : `The ${TOP_SIGNS} strongest of ${signs.length} warning signs`}
              </h3>
              <ul className="mt-1.5 space-y-1.5">
                {shown.map((r) => (
                  <li key={r} className="flex gap-2 text-[13.5px] leading-snug text-ink/85 [overflow-wrap:anywhere]">
                    <X className="mt-[3px] size-3.5 shrink-0 text-danger" strokeWidth={3} aria-hidden />
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
              {signs.length > TOP_SIGNS ? (
                <button
                  type="button"
                  onClick={() => setAll(!all)}
                  aria-expanded={all}
                  className="mt-2 text-[13px] font-semibold text-danger-ink underline-offset-2 hover:underline"
                >
                  {all ? "Show fewer" : `Show all ${signs.length} signs`}
                </button>
              ) : null}
            </>
          ) : (
            <p className="mt-1.5 text-[13.5px] leading-snug text-ink/85">{suggestion.body}</p>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-danger/15 bg-surface/50 px-4 py-2.5 sm:px-5">
        {real ? (
          <Link
            to={`/documents/${real.id}`}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] font-semibold text-danger-ink transition-colors hover:bg-danger/10"
          >
            Open your real letter from this sender <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        ) : null}
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto"
          loading={update.isPending}
          onClick={() =>
            update.mutate(
              { id: suggestion.id, patch: { status: "dismissed" } },
              {
                onSuccess: () =>
                  toast({
                    title: "Warning removed",
                    description: "You checked it with the sender. We'll keep comparing new letters.",
                    undo: () => update.mutate({ id: suggestion.id, patch: { status: "new" } }),
                  }),
              },
            )
          }
        >
          I checked — it's genuine
        </Button>
      </div>
      <p className="border-t border-danger/15 px-4 py-2 text-[12px] font-medium text-muted sm:px-5">
        {SAFE_NOTE} Ordnung compares bank details with earlier letters; it can't catch every trick.
      </p>
    </div>
  );
}

function HiddenTextBanner() {
  return (
    <Callout tone="danger" icon={EyeOff} title="This document contains hidden text aimed at software — we ignored it">
      Some text on the page is invisible to people (white or tiny print). It can be used to trick AI tools, so Ordnung never
      sent it to Claude. Treat the letter with extra care.
    </Callout>
  );
}

function AdviceCard({ type, addressee }: { type: "klage" | "unclear"; addressee: string | null }) {
  const links = [...ADVICE_LINKS.consumer, ...ADVICE_LINKS.tax];
  return (
    <Callout
      tone="warn"
      icon={Scale}
      title={type === "klage" ? "This can only be challenged in court — get advice" : "We couldn't tell how to object — get advice"}
    >
      {type === "klage" ? (
        <p>
          The letter says the next step is a <span lang="de">Klage</span> (court action){addressee ? ` at ${addressee}` : ""}. Ordnung
          doesn't compute court deadlines or draft court papers. Please talk to an advice service soon.
        </p>
      ) : (
        <p>
          The instructions on how to object (the <Glossary term="Rechtsbehelfsbelehrung" translate={false} />) are missing or
          unclear, so we show no date. Missing instructions can mean a one-year period (§ 356 Abs. 2 AO, § 58 Abs. 2 VwGO, § 66 Abs. 2 SGG) — but
          don't rely on it. Ask for advice.
        </p>
      )}
      <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
        {links.map((l) => (
          <li key={l.href}>
            <a href={l.href} target="_blank" rel="noreferrer noopener" className="text-[13px] font-semibold text-accent hover:underline">
              {l.label} ↗<span className="sr-only"> (opens in a new tab)</span>
            </a>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[12px] text-muted">Not legal advice.</p>
    </Callout>
  );
}

/**
 * "When did this letter arrive?" for to-dos that count from the arrival. `mayBePublic`: the sender's
 * kind may be an authority's (a company, insurer, utility or employer), so a late arrival may not move
 * the date — the question says so, and the toast after saving says what the engine did.
 */
function ArrivalQuestion({ doc, items, mayBePublic }: { doc: Document; items: Item[]; mayBePublic: boolean }) {
  const todayISO = useTodayISO();
  const qc = useQueryClient();
  const served = isServed(doc, items);
  const update = useUpdateDocument();
  // A court's letter counts from the date the postman wrote on the envelope, often days before it was
  // opened: nothing is filled in for it, so one Save can never move a court deadline later by mistake.
  const [date, setDate] = useState(doc.received_date ?? (served ? "" : todayISO));
  const min = doc.doc_date ?? undefined;
  const valid = Boolean(date) && date <= todayISO && (!min || date >= min);
  const quick = served
    ? []
    : [0, 1, 2]
        .map((n) => {
          const d = new Date(`${todayISO}T00:00:00`);
          d.setDate(d.getDate() - n);
          return toISODate(d);
        })
        .filter((d) => !min || d >= min);

  const subject = items.length === 1 ? `“${items[0]!.title}” counts` : "These dates count";
  // a letter that may be an authority's never counts from later than it would usually count as delivered
  const unlessLate = mayBePublic && !served
    ? " — unless it took longer than letters usually do: this sender may be an authority, so we then still count from the day it would usually have arrived"
    : "";

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    update.mutate(
      { id: doc.id, patch: { received_date: date } },
      {
        onSuccess: async () => {
          if (served) {
            // a start the letter itself names counts when it is earlier (see "Why this date?")
            toast.success("Thanks — dates updated", {
              description: `Counting from ${formatDate(date, { style: "short" })}, the delivery date on the envelope — or from an earlier start the letter names.`,
            });
            return;
          }
          // the items as recomputed with the arrival day: they say what the date now counts from
          const fresh = await qc
            .fetchQuery({ queryKey: qk.documents.detail(doc.id), queryFn: () => api.document(doc.id), staleTime: 5_000 })
            .catch(() => undefined);
          const asked = new Set(items.map((i) => i.id));
          const recomputed = (fresh?.items ?? []).filter((i) => asked.has(i.id));
          // a delivery day the letter states counts when it is earlier than the one entered
          const named = recomputed.some((i) => i.date_spec?.anchor === "receipt" && Boolean(i.date_spec.anchor_date));
          const note = recomputed.length ? arrivalSavedNote(date, recomputed) : "See “Why this date?” for what each date counts from.";
          toast.success("Thanks — dates updated", {
            description: named ? `${note} Where the letter names an earlier delivery day, that day counts.` : note,
          });
        },
      },
    );
  };

  return (
    <form id="arrival-question" onSubmit={submit} className="rounded-2xl border border-warn/30 bg-warn-soft px-4 py-4 sm:px-5">
      <div className="flex gap-3">
        <CalendarCheck className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold text-warn-ink">{served ? "When was it delivered?" : "When did this letter arrive?"}</h2>
          <p className="mt-1 text-[13.5px] leading-relaxed text-ink/85">
            {served ? (
              <>
                {subject} from the day the court's letter was delivered — the postman wrote that date on the yellow envelope it
                came in. Until you tell us, we count from the letter date{doc.doc_date ? ` (${formatDate(doc.doc_date, { style: "day" })})` : ""}, the
                earliest possible.
              </>
            ) : (
              <>
                {subject} from the day the letter reached you{unlessLate}. Until you tell us, we count from the letter date
                {doc.doc_date ? ` (${formatDate(doc.doc_date, { style: "day" })})` : ""} — the earliest possible, so you're never late.
              </>
            )}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {quick.map((d, i) => (
              <button
                key={d}
                type="button"
                onClick={() => setDate(d)}
                aria-pressed={date === d}
                className={cn(
                  "h-8 rounded-full border px-3 text-[13px] font-medium transition-colors",
                  date === d ? "border-warn bg-surface text-ink" : "border-warn/30 bg-surface/50 text-ink/80 hover:bg-surface",
                )}
              >
                {i === 0 ? "Today" : i === 1 ? "Yesterday" : formatDate(d, { style: "short" })}
              </button>
            ))}
            <label className={served ? "text-[13px] font-medium text-ink" : "sr-only"} htmlFor="arrival-date">
              {served ? "Date on the yellow envelope" : "Arrival date"}
            </label>
            <Input
              id="arrival-date"
              type="date"
              value={date}
              min={min}
              max={todayISO}
              onChange={(e) => setDate(e.target.value)}
              className="h-8 w-auto bg-surface"
              // an empty field (a court's envelope date isn't prefilled) is not an error: Save waits for a date
              aria-invalid={(Boolean(date) && !valid) || undefined}
            />
            <Button type="submit" size="sm" variant="primary" loading={update.isPending} disabled={!valid}>
              Save
            </Button>
          </div>
        </div>
      </div>
    </form>
  );
}

function PleaseCheckItem({ item }: { item: Item }) {
  const { dismiss, changeDate, confirmItem, pending } = useItemActions();
  const { select } = useEvidence();
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState(item.due_date ?? "");
  const ev = item.evidence.find((e) => e.grounding === "unverified" || !e.value_consistent) ?? item.evidence[0];
  const notFound = item.grounding === "unverified" || ev?.grounding === "unverified";

  return (
    <div className="rounded-2xl border border-warn/30 bg-warn-soft px-4 py-4 sm:px-5">
      <div className="flex gap-3">
        <TriangleAlert className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-[12px] font-semibold uppercase tracking-[0.07em] text-warn-ink">Please check</h2>
          <p className="mt-1 text-[15px] font-medium leading-snug text-ink">
            {item.title}
            {item.due_date ? <span className="font-normal text-ink/80"> — by {formatDate(item.due_date, { style: "short" })}</span> : null}
          </p>
          <p className="mt-1 text-[13px] leading-5 text-ink/75">
            {notFound ? GROUNDING_COPY.unverified.label + "." : "The date or amount doesn't match the sentence it came from."}
          </p>
          {ev?.quote ? (
            <blockquote lang="de" className="mt-2 text-[13.5px] leading-relaxed text-ink">
              <button type="button" onClick={() => select(`item:${item.id}:${item.evidence.indexOf(ev)}`)} className="text-left hover:underline">
                <span className="marker box-decoration-clone px-0.5">“{ev.quote}”</span>
              </button>
            </blockquote>
          ) : null}
          {editing ? (
            <form
              className="mt-3 flex flex-wrap items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (date) changeDate(item, date, () => setEditing(false));
              }}
            >
              <label className="sr-only" htmlFor={`date-${item.id}`}>
                New date for {item.title}
              </label>
              <Input id={`date-${item.id}`} type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-8 w-auto bg-surface" autoFocus />
              <Button type="submit" size="sm" variant="primary" disabled={!date} loading={pending}>
                Save date
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </form>
          ) : (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" icon={Check} onClick={() => confirmItem(item)} disabled={pending}>
                Correct
              </Button>
              <Button size="sm" variant="secondary" icon={Pencil} onClick={() => setEditing(true)}>
                Change date
              </Button>
              <Button size="sm" variant="ghost" icon={X} onClick={() => dismiss(item)} disabled={pending}>
                Not a real to-do
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function GeneralWarnings({ warnings }: { warnings: string[] }) {
  return (
    <Callout tone="warn" title="Please check">
      <ul className="space-y-1">
        {warnings.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
    </Callout>
  );
}
