/**
 * Everything that needs the person's eyes, right under the verdict: the scam banner, the
 * hidden-text banner, the "get advice" card of a high-stakes letter (a court order, a dismissal, a
 * landlord's letter), "get advice" when the letter can only be challenged in court (or it is
 * unclear how), "Please check" to-dos, the "When did this letter arrive?" question and any other
 * warnings from reading the letter.
 */
import { useState, type FormEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { ArrowRight, CalendarCheck, Check, EyeOff, Pencil, Scale, ShieldAlert, TriangleAlert, X } from "lucide-react";
import type { Document, DocumentDetail, Item, Suggestion } from "@/api/types";
import { api } from "@/api/endpoints";
import { qk, useUpdateDocument, useUpdateSuggestion } from "@/api/hooks";
import { cn } from "@/lib/utils";
import { GROUNDING_COPY } from "@/lib/copy";
import { formatDate, glueText, toISODate } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { Button } from "@/components/ui/Button";
import { DateText } from "@/components/ui/DateText";
import { Callout } from "@/components/ui/Callout";
import { ADVICE_LINKS } from "@/components/ui/Disclaimer";
import { Glossary } from "@/components/ui/Glossary";
import { Input } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { arrivalSavedNote, isCourtServed, isServed, MAY_BE_PUBLIC_KINDS, needsArrivalDate, needsCheck, scamSuggestion } from "./verdict";
import { HIGH_STAKES_KINDS } from "@/api/types";
import { useItemActions } from "./actions";
import { useEvidence } from "./EvidenceContext";
import { LetterAdviceCard } from "./LetterAdvice";
import { DEMO_NOTE } from "@/mocks/mode";

export const SAFE_NOTE = "No warning does not mean it is safe.";

const HIGH_STAKES = new Set<string>(HIGH_STAKES_KINDS);

/**
 * A reading's warning about text meant for software — the hidden-text banner says it (UI audit round 1: "text
 * addressed to an AI (“Hinweis an KI-Assistenten”) … Ordnung treated it as ordinary content" repeated the
 * banner as a scam sign, and contradicted it).
 */
const isHiddenTextWarning = (w: string) =>
  /invisible text|hidden text|addressed to (?:an? )?(?:AI|KI)\b|\bKI-Assistent|AI assistant|prompt injection|instructions? (?:aimed at|for|to) (?:an? )?AI\b/i.test(w);

/** A reading's warning that only repeats the arrival question ("…when it arrived", "…when it was delivered"). */
export const REPEATS_ARRIVAL_QUESTION = /arriv|received|zugang|deliver|zustell/i;

/**
 * The reading's own count of dates it couldn't confirm ("1 date could not be confirmed against the letter's
 * text."; letters read before UI audit R1-backend-7 say "Please check: 1 date …"): each of those to-dos has its
 * own "Please check" card, which says it — and once they are confirmed, the count is out of date (UI audit
 * round 1: "Please check" three times on one letter).
 */
const UNCONFIRMED_DATES = /^(?:please check:\s*)?\d+\s+dates?\s+could not be confirmed/i;

/** A claim about an IBAN's checksum ("does not pass the standard IBAN checksum"). */
const IBAN_CHECK_CLAIM =
  /\biban\b.*(?:check ?sum|check digits?|prüfsumme|prüfziffer|mod(?:ulo)?[ -]?97)|(?:check ?sum|check digits?|prüfsumme|prüfziffer).*\biban\b/i;
const NEGATIVE = /n't\b|\b(?:not|fails?|failed|failing|invalid|wrong|incorrect|ungültig|falsch|nicht)\b/i;

/** Ordnung's own sentence for an IBAN that fails the bank check (as under the bank details). */
export const IBAN_FAILS_CHECK = "The IBAN in this letter doesn't pass the bank check — most likely a misprint. Compare it with the paper letter before you pay.";

/** A warning's sentences (a full stop, then a capital letter or an opening quote). */
const sentences = (w: string) => w.split(/(?<=[.!?])\s+(?=[A-ZÄÖÜ„“"(])/);

/**
 * The reading's claims about the IBAN's checksum, squared with Ordnung's own check (`payment.iban_valid`): a
 * failure the check doesn't confirm is dropped (UI audit round 1: "IBAN … does not pass the standard IBAN
 * checksum" on a valid IBAN), a confirmed one is said in Ordnung's words, once. Without a check, as read. Since
 * R1-backend-7 the backend squares them when it reads a letter (`square_iban_claims` in
 * `src/ordnung/ingest/plan.py`); this keeps letters read before that right.
 */
export function squareIbanClaims(warnings: string[], ibanValid: boolean | null | undefined): string[] {
  if (ibanValid == null) return warnings;
  const out: string[] = [];
  for (const w of warnings) {
    const parts = sentences(w.trim());
    // a valid IBAN keeps a claim that agrees ("the IBAN's check digits are valid, but …")
    const wrong = (s: string) => IBAN_CHECK_CLAIM.test(s) && (!ibanValid || NEGATIVE.test(s));
    const kept = parts.filter((s) => !wrong(s));
    if (kept.length < parts.length && !ibanValid && !out.includes(IBAN_FAILS_CHECK)) out.push(IBAN_FAILS_CHECK);
    if (kept.length) out.push(kept.join(" "));
  }
  return out;
}

/** "Please check: the amount…" under the card's own "Please check" heading: "The amount…". */
function withoutPleaseCheck(w: string): string {
  const rest = w.replace(/^please check\s*[:—–-]\s*/i, "");
  return rest ? rest.charAt(0).toUpperCase() + rest.slice(1) : w;
}

/**
 * The warning that Claude's reading came back incomplete and Ordnung added a to-do of its own
 * (`gap_warning` in `src/ordnung/ingest/gaps.py`). It is no scam sign, and it is said only while that to-do
 * still needs checking: once the person confirmed, dated, finished or dismissed it, it is out of date.
 */
const GAP_WARNING = /^(?:Claude's reading of this letter came back almost blank|This letter explains how to (?:object|challenge it in court), but Claude's reading)/;

/**
 * The warning that Claude's reading left out a date the letter sets (pay by, send by) and Ordnung added it as a
 * to-do of its own (`deadline_warning` in `src/ordnung/ingest/gaps.py`): no scam sign, and said only while one of
 * those to-dos still needs checking.
 */
const DEADLINE_WARNING = /^Claude's reading of this letter left out /;

/**
 * Warnings shown in the scam banner / generic list (the hidden-text one has its own banner, the online demo's
 * own note sits in the verdict, the count of unconfirmed dates is said by their own cards, the incomplete
 * reading's note only while its to-do needs checking).
 */
function otherWarnings(doc: Document, items: Item[]): string[] {
  const checking = items.some((i) => i.slot_key === READING_CHECK_SLOT && needsCheck(i));
  const checkingDates = items.some((i) => isDeadlineCheck(i) && needsCheck(i));
  const shown = doc.warnings.filter(
    (w) =>
      w.trim() &&
      w.trim() !== SAFE_NOTE &&
      !(doc.hidden_text && isHiddenTextWarning(w)) &&
      !w.startsWith(DEMO_NOTE) &&
      !UNCONFIRMED_DATES.test(w.trim()) &&
      (checking || !GAP_WARNING.test(w.trim())) &&
      (checkingDates || !DEADLINE_WARNING.test(w.trim())),
  );
  return squareIbanClaims(shown, doc.payment?.iban ? doc.payment.iban_valid : null);
}

export function DocumentWarnings({ detail }: { detail: DocumentDetail }) {
  const doc = detail.document;
  const scam = scamSuggestion(detail);
  const checks = detail.items.filter(needsCheck);
  const arrival = detail.items.filter((i) => needsArrivalDate(i, doc));
  const remedy = doc.remedy?.type;
  const warnings = otherWarnings(doc, detail.items);
  // the arrival question already explains the "we don't know when it arrived / was delivered" warning — and
  // once the person has dealt with the letter (objected, paid), when it arrived no longer matters
  const general =
    arrival.length || detail.advice?.handled ? warnings.filter((w) => !REPEATS_ARRIVAL_QUESTION.test(w)) : warnings;

  // a high-stakes letter's own card replaces the generic "get advice" one; urgent cards go first
  const advice = detail.advice && !scam ? <LetterAdviceCard key="letter-advice" advice={detail.advice} doc={doc} party={detail.party} /> : null;
  const urgent = Boolean(detail.advice?.urgent);

  const blocks = [
    // the Idea's own list and count (the API's `scam_signs`); the letter's warnings where there is none
    scam ? <ScamBanner key="scam" suggestion={scam} doc={doc} reasons={detail.scam_signs?.length ? detail.scam_signs : warnings} /> : null,
    doc.hidden_text ? <HiddenTextBanner key="hidden" /> : null,
    urgent ? advice : null,
    !detail.advice && (remedy === "klage" || remedy === "unclear") ? <AdviceCard key="advice" type={remedy} addressee={doc.remedy?.addressee ?? null} /> : null,
    arrival.length ? (
      <ArrivalQuestion key="arrival" doc={doc} items={arrival} mayBePublic={Boolean(detail.party && MAY_BE_PUBLIC_KINDS.includes(detail.party.kind))} />
    ) : null,
    ...checks.map((it) => <PleaseCheckItem key={it.id} item={it} scam={Boolean(scam)} />),
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
  return reasons
    .filter((w) => !/^please check\b/i.test(w) && !GAP_WARNING.test(w.trim()) && !DEADLINE_WARNING.test(w.trim()))
    .sort((a, b) => rank(a) - rank(b));
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
              {/* the full ink: at 80 % the 12 px caps fell under 4.5:1 on the pink (UI audit round 1) */}
              <h3 className="eyebrow mt-3 text-danger-ink">
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
                  // a 24 px tall target (WCAG 2.5.8; UI audit round 1)
                  className="mt-1.5 inline-flex min-h-6 items-center rounded-md text-[13px] font-semibold text-danger-ink underline-offset-2 hover:underline"
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
            // the promise, not mutate's callbacks: this button leaves with the warning once the lists are refreshed
            // (review round 4 of phase 2)
            update.mutateAsync({ id: suggestion.id, patch: { status: "dismissed" } }).then(
              () =>
                toast({
                  title: "Warning removed",
                  description: "You checked it with the sender. We'll keep comparing new letters.",
                  undo: () => update.mutate({ id: suggestion.id, patch: { status: "new" } }),
                }),
              () => undefined, // the error toast comes from the mutation's meta
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
          can't draft or file court actions. Please talk to an advice service soon.
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
  // a court's letter, or an authority's served with a Postzustellungsurkunde: the same envelope, other words
  const sender = isCourtServed(doc, items) ? "the court's letter" : "the letter";
  const update = useUpdateDocument();
  // A court's letter, or an authority's served with a Postzustellungsurkunde, counts from the date the postman
  // wrote on the yellow envelope, often days before it was opened or picked up — and a dismissal, a landlord's notice or a rent increase from the day it was put in the letterbox,
  // even if the person was away: nothing is filled in for these, so one Save can never move a deadline the law
  // sets later by mistake (review round 2 of phase 2: a dismissal uploaded after a holiday saved "today").
  const highStakes = HIGH_STAKES.has(doc.kind ?? "");
  const [date, setDate] = useState(doc.received_date ?? (served || highStakes ? "" : todayISO));
  const min = doc.doc_date ?? undefined;
  const valid = Boolean(date) && date <= todayISO && (!min || date >= min);
  // an invalid day is said, not only shown in red (WCAG 3.3.1) — in the words of the question: a court's letter
  // is delivered, its date is on the envelope; the letter's date has its year when it isn't this year's
  const letterDate = min ? formatDate(min, { style: "day", today: todayISO }) : "";
  const problem = !date || valid
    ? null
    : date > todayISO
      ? served
        ? "That day is after today — enter the date on the yellow envelope."
        : "That day is after today — enter the day it actually arrived."
      : served
        ? `That day is before the letter's own date (${letterDate}) — a letter can't be delivered before it was written. Check the date on the envelope again, or whether the letter's date was read right.`
        : `That day is before the letter's own date (${letterDate}) — a letter can't arrive before it was written. Check the day again, or whether the letter's date was read right.`;
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
  // a letter that may be an authority's never counts from later than it would usually count as delivered —
  // but a high-stakes letter is a declaration under private law (a dismissal from a city too): the law's dates
  // count from the day it really arrived (§ 130 BGB, § 4 KSchG), whoever sent it (review round 2 of phase 2)
  const unlessLate = mayBePublic && !served && !highStakes
    ? " — unless it took longer than letters usually do: this sender may be an authority, so we then still count from the day it would usually have arrived"
    : "";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    // Awaited here, not in mutate()'s own onSuccess: the hook refetches the letter first, which answers the
    // question and unmounts this form — TanStack Query then drops a per-call callback, so the toast and the
    // focus never came (review round 3 of phase 2). This closure outlives the form.
    try {
      await update.mutateAsync({ id: doc.id, patch: { received_date: date } });
    } catch {
      return; // the mutation's own error toast says what went wrong; the form stays for another try
    }
    // the question goes away once answered: keyboard focus moves to the verdict and its new date, in view
    const title = document.getElementById("verdict-title");
    title?.focus({ preventScroll: true });
    title?.scrollIntoView({ block: "start" });
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
  };

  return (
    <form id="arrival-question" onSubmit={(e) => void submit(e)} className="rounded-2xl border border-warn/30 bg-warn-soft px-4 py-4 sm:px-5">
      <div className="flex gap-3">
        <CalendarCheck className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold text-warn-ink">{served ? "When was it delivered?" : "When did this letter arrive?"}</h2>
          <p className="mt-1 text-[13.5px] leading-relaxed text-ink/85">
            {served ? (
              <>
                {subject} from the day {sender} was delivered — the postman wrote that date on the yellow envelope it came
                in, also when it was left at the post office for you to pick up. Until you tell us, we count from the letter date{doc.doc_date ? ` (${formatDate(doc.doc_date, { style: "day" })})` : ""}, the
                earliest possible.
              </>
            ) : (
              <>
                {subject} from the day the letter reached you — the day it was put in your letterbox or handed to you, even if you
                were away or opened it later{unlessLate}. Until you tell us, we count from the letter date
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
              aria-invalid={problem ? true : undefined}
              aria-describedby={problem ? "arrival-date-problem" : undefined}
            />
            <Button type="submit" size="sm" variant="primary" loading={update.isPending} disabled={!valid}>
              Save
            </Button>
          </div>
          {problem ? (
            <p id="arrival-date-problem" className="mt-2 text-[13px] leading-5 text-danger-ink">
              {problem}
            </p>
          ) : null}
        </div>
      </div>
    </form>
  );
}

/**
 * The slot of the to-do Ordnung files itself when Claude's reading of a letter came back incomplete
 * (`CHECK_SLOT` in `src/ordnung/ingest/gaps.py`): the objection deadline worked out from the letter's own
 * instructions on how to object, or — without them — an undated "Read this letter yourself".
 */
export const READING_CHECK_SLOT = "check:reading";

/**
 * The slot of a to-do Ordnung files itself for a fixed date the letter sets for the person (pay by, send by) that
 * Claude's reading left out (`DEADLINE_SLOT` in `src/ordnung/ingest/gaps.py`): `check:deadline`, `check:deadline#2` …
 */
export const DEADLINE_CHECK_SLOT = "check:deadline";

/** A to-do Ordnung filed for a date the reading left out ({@link DEADLINE_CHECK_SLOT}). */
export function isDeadlineCheck(item: Pick<Item, "slot_key">): boolean {
  return (item.slot_key ?? "").split("#")[0] === DEADLINE_CHECK_SLOT;
}

/** Why a to-do needs checking, under its title. */
function checkReason(item: Item, scam: boolean, notFound: boolean): string {
  if (scam)
    return "This letter shows signs of a scam: don't pay before you've checked with the sender, using contact details you already know.";
  if (item.slot_key === READING_CHECK_SLOT) {
    // the placeholder "Read this letter yourself" is a task; the objection deadline, dated or not, a deadline
    if (item.kind === "task")
      return "Claude's reading of this letter came back almost blank. Read the letter yourself; if it asks you to do something by a date, give this to-do that date with “Set a date”.";
    return item.due_date
      ? "Ordnung worked this date out from the letter's own instructions on how to object, because Claude's reading left it out."
      : "Ordnung found the letter's instructions on how to object but couldn't work out the date from them — enter the deadline with “Set a date”.";
  }
  if (isDeadlineCheck(item))
    return "Ordnung took this date from the letter's own words, because Claude's reading left it out — check it against the letter.";
  return notFound ? GROUNDING_COPY.unverified.label + "." : "The date or amount doesn't match the sentence it came from.";
}

/** The German terms Ordnung writes into its own titles and notes, marked for screen readers. */
const GERMAN_TERM = /\b(Widerspruch|Einspruch|Klage|Rechtsbehelfsbelehrung)\b/;

function WithGermanTerms({ text }: { text: string }) {
  return (
    <>
      {text.split(GERMAN_TERM).map((part, i) =>
        i % 2 ? (
          <span key={i} lang="de">
            {part}
          </span>
        ) : (
          part
        ),
      )}
    </>
  );
}

/**
 * A to-do whose date or amount Ordnung couldn't confirm against the letter. On a letter with scam signs it
 * is the demand not to pay: no date to correct — only "not a real to-do" or "it's a real to-do" (walkthrough of
 * phase 2: "Correct / Change date" invited the person to confirm the date of a scam payment). The to-do Ordnung
 * filed for an incomplete reading says so instead ({@link READING_CHECK_SLOT}).
 */
function PleaseCheckItem({ item, scam = false }: { item: Item; scam?: boolean }) {
  const { dismiss, changeDate, confirmItem, markDone, pending } = useItemActions();
  const { select } = useEvidence();
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState(item.due_date ?? "");
  const ev = item.evidence.find((e) => e.grounding === "unverified" || !e.value_consistent) ?? item.evidence[0];
  const notFound = item.grounding === "unverified" || ev?.grounding === "unverified";
  const own = item.slot_key === READING_CHECK_SLOT;
  // "Read this letter yourself": reading it is the whole task — when the letter asks for nothing, it's done
  const placeholder = own && item.kind === "task";

  return (
    <CheckCard>
      <p className="mt-1 text-[15px] font-medium leading-snug text-ink wrap-break-word">
        {own ? <WithGermanTerms text={item.title} /> : item.title}
        {item.due_date && !scam ? (
          <span className="font-normal text-ink/80">
            {" "}
            — by <DateText date={item.due_date} />
          </span>
        ) : null}
      </p>
      <p className="mt-1 text-[13px] leading-5 text-ink/75">{checkReason(item, scam, notFound)}</p>
      {ev?.quote ? (
        <blockquote lang="de" className="mt-2 text-[13.5px] leading-relaxed text-ink">
          <button type="button" onClick={() => select(`item:${item.id}:${item.evidence.indexOf(ev)}`)} className="min-h-6 text-left hover:underline">
            <span className="marker box-decoration-clone px-0.5">“{ev.quote}”</span>
          </button>
        </blockquote>
      ) : null}
      {scam ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" icon={X} onClick={() => dismiss(item)} disabled={pending}>
            Not a real to-do
          </Button>
          <Button size="sm" variant="ghost" icon={Check} onClick={() => confirmItem(item)} disabled={pending}>
            It's a real to-do
          </Button>
        </div>
      ) : editing ? (
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
          {placeholder ? (
            <Button size="sm" variant="secondary" icon={Check} onClick={() => markDone(item, { title: "Marked as read" })} disabled={pending}>
              I've read it — nothing to do
            </Button>
          ) : own && !item.due_date ? null : (
            // an undated deadline of Ordnung's own has no date to call correct: "Correct" would file it undated for good
            <Button size="sm" variant="secondary" icon={Check} onClick={() => confirmItem(item)} disabled={pending}>
              Correct
            </Button>
          )}
          <Button size="sm" variant="secondary" icon={Pencil} onClick={() => setEditing(true)}>
            {item.due_date ? "Change date" : "Set a date"}
          </Button>
          <Button size="sm" variant="ghost" icon={X} onClick={() => dismiss(item)} disabled={pending}>
            Not a real to-do
          </Button>
        </div>
      )}
    </CheckCard>
  );
}

/**
 * The one "Please check" card — a to-do to confirm and the reading's other warnings look alike: the same
 * box, icon and heading (UI audit round 1: an eyebrow h2 on one, a callout's bold title on the other).
 */
function CheckCard({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-warn/30 bg-warn-soft px-4 py-4 sm:px-5">
      <div className="flex gap-3">
        <TriangleAlert className="mt-px size-5 shrink-0 text-warn" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="eyebrow leading-5 text-warn-ink">Please check</h2>
          {children}
        </div>
      </div>
    </div>
  );
}

function GeneralWarnings({ warnings }: { warnings: string[] }) {
  const lines = warnings.map(withoutPleaseCheck);
  const text = "text-[14px] leading-relaxed text-ink/85 wrap-break-word";
  // the reading's words as written, with a reference ("TM-2026-0048213") and an amount ("89.99 EUR") kept whole
  return (
    <CheckCard>
      {lines.length === 1 ? (
        <p className={cn("mt-1", text)}>
          <WithGermanTerms text={glueText(lines[0]!)} />
        </p>
      ) : (
        <ul className="mt-1.5 space-y-1.5">
          {lines.map((w) => (
            <li key={w} className={cn("flex gap-2", text)}>
              <span aria-hidden className="mt-[9px] size-1.5 shrink-0 rounded-full bg-warn" />
              <span className="min-w-0">
                <WithGermanTerms text={glueText(w)} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </CheckCard>
  );
}
