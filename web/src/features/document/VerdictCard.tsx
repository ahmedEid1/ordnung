/**
 * The verdict card — the first thing on a letter: what this is, what you need to do, by when
 * (with "Why this date?"), what happens if you ignore it, and one main button.
 */
import { Fragment, type ReactNode } from "react";
import { Link } from "react-router";
import {
  ArrowRight,
  CalendarPlus,
  Check,
  CircleCheckBig,
  Clock,
  EyeOff,
  History,
  Info,
  Landmark,
  ListChecks,
  Mail,
  PenLine,
  Scale,
  ShieldAlert,
  TriangleAlert,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import type { DocumentDetail, DocumentKind, DraftKind, Item, PartyKind, Suggestion } from "@/api/types";
import { useUpdateSuggestion, useWaitAgain } from "@/api/hooks";
import { isDirectDebit } from "@/lib/payments";
import { toast } from "@/components/ui/Toast";
import { cn } from "@/lib/utils";
import { daysUntil, formatDate, formatInlineText, formatMoney, formatRelativeDays, formatTime, glueText, urgencyOf, type Urgency } from "@/lib/format";
import { useToday } from "@/lib/today";
import { Badge } from "@/components/ui/Badge";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { ADVICE_LINKS, AdviceLinks, Disclaimer } from "@/components/ui/Disclaimer";
import { KindBadge } from "@/components/ui/KindBadge";
import { useModelLang } from "@/components/ui/ModelText";
import { PartyChip } from "@/components/ui/PartyChip";
import { Popover } from "@/components/ui/Popover";
import { StatusPill } from "@/components/ui/StatusPill";
import {
  asideItems,
  chooseMainAction,
  consequenceWords,
  decisionSuggestion,
  existingDraft,
  hasLongWord,
  incomingMoney,
  isOpenItem,
  isConsentRequest,
  isOptionalObjection,
  isServed,
  isLetterSettled,
  leadsWithDecision,
  mustAct,
  needsArrivalDate,
  needsCheck,
  notOwedReason,
  otherLawDeadlines,
  scamSuggestion,
  usesLaw,
  verdictWords,
  withoutIfYouDisagree,
  type AsideItem,
  type MainAction,
  type NotOwed,
} from "./verdict";
import { icsFileName, icsHref, useItemActions, useStartDraft } from "./actions";
import { KindPicker } from "./KindPicker";
import { isDeadlineCheck, READING_CHECK_SLOT } from "./Warnings";
import { canSuspend, needsTypedCourt } from "@/features/letters/logic";
import { composerHref } from "@/features/today/selection";
import { PayPanel } from "./PayPanel";
import { GlossaryText } from "./Explained";
import { englishInline, isGermanText } from "./fact-text";
import { adviceFor, WhyThisDate } from "./WhyThisDate";
import { GermanTerms } from "@/lib/germanTerms";
import { keepCitations, NB_HYPHEN, protectRefs } from "@/lib/glue";
import { DEMO_NOTE } from "@/mocks/mode";
import { AnswerButton } from "@/features/inbox/AnswerButton";
import { usePhoneCompanion } from "@/features/phone/client";

const countdownTone: Record<Urgency, string> = {
  overdue: "bg-danger text-white dark:text-canvas",
  today: "bg-danger text-white dark:text-canvas",
  soon: "bg-danger text-white dark:text-canvas",
  week: "bg-surface text-warn-ink ring-1 ring-warn/30",
  month: "bg-surface text-ink ring-1 ring-line",
  later: "bg-surface text-muted ring-1 ring-line",
  past: "bg-surface text-muted ring-1 ring-line",
};

const dateTone: Record<Urgency, string> = {
  overdue: "bg-danger-soft border-danger/20",
  today: "bg-danger-soft border-danger/20",
  soon: "bg-danger-soft border-danger/20",
  week: "bg-warn-soft border-warn/25",
  month: "bg-accent-soft/70 border-accent/15",
  later: "bg-surface-2 border-line",
  past: "bg-surface-2 border-line",
};

function Section({ label, icon: Icon, children, className }: { label: string; icon: LucideIcon; children: ReactNode; className?: string }) {
  return (
    <div className={cn("border-t border-line px-5 py-4 sm:px-6", className)}>
      {/* the card's title is the page's h1, so its sections are h2 (the app's eyebrow style) */}
      <h2 className="eyebrow mb-1.5 flex items-center gap-1.5">
        <Icon className="size-3.5 shrink-0" aria-hidden />
        {label}
      </h2>
      {children}
    </div>
  );
}

/** What the verdict says under a payment that may not be owed yet ({@link notOwedReason}). */
const NOT_OWED: Record<NotOwed, string> = {
  late_statement:
    "Check before you pay: this statement seems to have come too late, so you may owe no back-payment (§\u00a0556 Abs.\u00a03 BGB). See the card on this page.",
  consent:
    "Decide before you pay: the higher rent is only owed once you agree to the increase (§\u00a0558b Abs.\u00a01 BGB), and paying it can count as agreeing. See the card on this page.",
  if_agreed:
    "Only if you agreed to the increase: the higher rent is due from this date. If you didn't, keep paying your current rent — paying the higher one can count as agreeing (§\u00a0558b Abs.\u00a01 BGB).",
};

/** What the verdict says about a letter that must be acted on when no to-do carries its date. */
const ADVICE_NOW: Record<string, string> = {
  landlord_notice: "Get advice now: your landlord is ending your tenancy. Have the notice checked by a tenants' association — see the card on this page.",
  dismissal: "Get advice now: only a court action within three weeks of receiving a dismissal keeps your rights — see the card on this page.",
  default: "Get advice now: this is a court order with a short deadline — see the card on this page.",
};

const SEE_THE_CARD = "see the card on this page";

/** "The letter says: „…“" — the letter's German words under the English, smaller and marked German. */
function LetterSays({ text, className }: { text: string; className?: string }) {
  return (
    <p className={cn("mt-1.5 text-[13px] leading-relaxed text-muted wrap-break-word", className)}>
      The letter says:{" "}
      <q lang="de" className="italic text-ink/75 hyphens-auto">
        {keepCitations(formatInlineText(text.replace(/^[„“"]|[“”"]$/g, ""), { rewrite: false }))}
      </q>
    </p>
  );
}

/**
 * A letter's file name as its headline (one nobody read has no title): it breaks after an underscore, never
 * inside a date ("Scan_" / "2026-09-28_0914.pdf", not "Scan_2026-09-" / "28_0914.pdf" at 320 px).
 */
function FileName({ name }: { name: string }) {
  const parts = name.replace(/\d+(?:-\d+)+/g, (d) => d.replace(/-/g, NB_HYPHEN)).split("_");
  return (
    <>
      {parts.map((p, i) => (
        <Fragment key={i}>
          {i ? (
            <>
              _<wbr />
            </>
          ) : null}
          {p}
        </Fragment>
      ))}
    </>
  );
}

/** A verdict line that points to the advice card: "see the card on this page" links to it. */
function CardLink({ text, docId }: { text: string; docId: string }) {
  const at = text.indexOf(SEE_THE_CARD);
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <a
        href={`#advice-card-${docId}`}
        className="underline decoration-warn/50 underline-offset-2 hover:decoration-warn"
        onClick={(e) => {
          // the online demo routes by the hash: scroll to the card (and focus its title) without navigating
          e.preventDefault();
          document.getElementById(`advice-card-${docId}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
          document.getElementById(`advice-${docId}`)?.focus({ preventScroll: true });
        }}
      >
        {SEE_THE_CARD}
      </a>
      {text.slice(at + SEE_THE_CARD.length)}
    </>
  );
}

/**
 * A private letter nobody read: Ordnung can't say what it asks, so it never says "nothing to do".
 * One kept private while it waited for the person (the server's `can_wait_again`) can wait again (its
 * "Keep private" undone): from there the person can let Claude read it. The waiting card then takes
 * this card's place, so focus moves to its heading (`onAnswered`: the page moves it once that card is
 * rendered); a failed undo leaves focus on the button.
 */
function NotRead({ doc, canWaitAgain: canWait, onAnswered }: { doc: DocumentDetail["document"]; canWaitAgain: boolean; onAnswered?: (from: DocumentDetail["document"]["status"]) => void }) {
  const wait = useWaitAgain();
  // whether Claude may read it is decided on the computer: a paired phone doesn't offer it
  const phone = usePhoneCompanion();
  const canWaitAgain = canWait && !phone;
  return (
    <>
      <p className="flex items-start gap-2 text-[16px] font-medium leading-snug text-ink">
        <EyeOff className="mt-0.5 size-[18px] shrink-0 text-muted" aria-hidden />
        <span>Not read — Ordnung can't tell you what this letter asks, or by when.</span>
      </p>
      <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted">
        It was kept private, so none of its dates, amounts or deadlines were read. Look through it yourself.
      </p>
      {canWaitAgain ? (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
          <AnswerButton
            size="sm"
            icon={Undo2}
            busy={wait.isPending}
            onClick={() =>
              wait
                .mutateAsync([doc.id])
                .then((res) => {
                  if (!res.documents.length) {
                    toast({ title: "It can't wait again", description: "Only a letter kept private from your folder, and not read since, can.", tone: "warn" });
                    return;
                  }
                  toast({ title: "It's back with the letters not read yet", description: "Choose “Read it” to have Claude read it.", tone: "info" });
                  onAnswered?.(doc.status);
                })
                .catch(() => undefined) // the request's own error toast says what went wrong
            }
          >
            Undo “Keep private”
          </AnswerButton>
          <span className="text-[13px] text-muted">It goes back to the letters not read yet, where you can let Claude read it.</span>
        </div>
      ) : null}
    </>
  );
}

export interface VerdictCardProps {
  detail: DocumentDetail;
  primary: Item | null;
  /** Scroll to the "When did this letter arrive?" question. */
  onAskArrival?: () => void;
  /** "Undo “Keep private”" went through (`from`: the status it answered): the card goes, and focus belongs to the waiting card that takes its place. */
  onAnswered?: (from: DocumentDetail["document"]["status"]) => void;
}

export function VerdictCard({ detail, primary, onAskArrival, onAnswered }: VerdictCardProps) {
  const doc = detail.document;
  const today = useToday();
  // the title and the summary are Claude's, in the person's language (a file name is no one's)
  const titleLang = useModelLang(doc.title);
  const summaryLang = useModelLang(doc.summary);
  const scam = scamSuggestion(detail);
  const decisionIdea = decisionSuggestion(detail);
  // a price increase's special right / a notice window leads — not the new monthly fee
  const decision = !scam && leadsWithDecision(decisionIdea, primary) ? decisionIdea : null;
  const main: MainAction = decision ? { type: "decide", suggestion: decision } : chooseMainAction(detail, primary);
  const open = !decision && primary && isOpenItem(primary) ? primary : null;
  const askArrival = open ? needsArrivalDate(open, doc) : false;
  const checkDate = open ? needsCheck(open) : false;
  const debit = open ? isDirectDebit(open) : false;
  // a court order's or a dismissal's deadline isn't optional: doing nothing has consequences
  const optional = open ? isOptionalObjection(open) && !mustAct(doc) : false;
  // a price increase that asks for consent: a choice, not a to-do (the buttons stay quiet, as for an objection)
  const consent = open ? isConsentRequest(open, doc) : false;
  // never a to-do the server set aside: it is listed under "Probably dealt with" below, not also as overdue
  const alsoByLaw = !scam && !decision ? otherLawDeadlines(detail.items, open, detail.set_aside) : [];
  const demoNote = doc.warnings.find((w) => w.startsWith(DEMO_NOTE));
  // an operating-cost statement is recognised on read (ADR 0010) and filed under the model's kind: the badge
  // names what the card below says it is, never "Utility bill" over an operating-cost statement's card
  const shownKind = detail.advice?.kind === "operating_costs" ? "operating_costs" : doc.kind;
  const refund = incomingMoney(detail.items);
  // a late operating-cost statement's back-payment, a rent increase's new rent: still a to-do, but
  // checked (or decided) before it is paid
  const notOwed = open ? notOwedReason(open, detail.advice, detail.items) : null;
  const refundText = refund?.amount != null ? `${formatMoney(refund.amount, { currency: refund.currency })} comes back to you` : null;
  // English first, the letter's German below it (UI audit round 1: "Semesterbeitrag … überweisen" as the headline)
  const words = open ? verdictWords(open, detail.party?.name) : null;
  // open to-dos that are not one to act on: replaced by a payment reminder, or long past when the letter came
  const allAsides = scam ? [] : asideItems(detail);
  const replaced = allAsides.find((a) => a.aside.reason === "replaced");
  // when the reminder is all there is to say, the headline and the main button say it — no row repeating it
  const asides = !open && !decision ? allAsides.filter((a) => a.aside.reason !== "replaced") : allAsides;
  const reminder = replaced ? detail.related.find((d) => d.id === replaced.aside.replaced_by) : undefined;
  const reminderDate = reminder?.doc_date ?? reminder?.received_date ?? null;
  const served = isServed(doc, detail.items);
  const sameDay = Boolean(doc.doc_date && doc.received_date && doc.doc_date === doc.received_date);
  // "Based on the law as of …" only where a law worked the date out — not under a passport's expiry
  const law = !scam && (Boolean(decision) || Boolean(open?.due_date && usesLaw(open)));
  const advice = open && (open.priority === "high" || open.priority === "critical") ? verdictAdvice(detail.advice, open.area, doc.kind, detail.party?.kind) : undefined;
  const footer = law ? <Disclaimer advice={advice} /> : !scam && advice?.length ? <AdviceLinks advice={advice} className="block text-xs leading-5 text-muted" /> : null;

  return (
    <article
      aria-labelledby="verdict-title"
      className={cn("card overflow-hidden", scam && "border-danger/40")}
    >
      {scam ? <div className="h-1 bg-danger" aria-hidden /> : null}
      {/* 1 — what this is */}
      <header className="px-5 pb-4 pt-5 sm:px-6 sm:pt-6">
        <p className="sr-only">What this is</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <KindBadge docKind={shownKind} />
          {!scam && doc.status !== "queued" && doc.status !== "processing" ? <KindPicker doc={{ id: doc.id, kind: shownKind }} /> : null}
          {scam ? (
            <Badge tone="danger" icon={ShieldAlert}>
              Possible scam
            </Badge>
          ) : doc.status === "needs_review" ? (
            <StatusPill of="document" status="needs_review" />
          ) : null}
          {/* privacy statements name who doesn't read it, as the held card, Inbox, Today and Settings do */}
          {doc.ai_private ? <Badge tone="neutral">Private — not read by Claude</Badge> : null}
        </div>
        <h1
          id="verdict-title"
          tabIndex={-1}
          {...(doc.title && doc.title !== doc.filename ? titleLang : {})}
          className={cn(
            // German compounds break at their joints (soft hyphens, marked German), never mid-syllable, and a
            // reference number never at its hyphens; the detail-page title size (26 → 30 px, as the "How it was
            // read" tab's), a step smaller on phones for a title with a very long word
            "display mt-3 scroll-mt-24 font-semibold text-ink outline-none wrap-break-word hyphens-manual",
            hasLongWord(doc.title ?? doc.filename) ? "text-detail-long" : "text-detail",
          )}
        >
          {/* the letter's words as written, with an amount and its "€" ("30 €") and a reference kept whole */}
          {/* a private letter is titled by its file name (nothing read it): shown as one */}
          {doc.title && doc.title !== doc.filename ? <GermanTerms text={glueText(doc.title)} /> : <FileName name={doc.filename} />}
        </h1>
        <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[13px] text-muted">
          {detail.party ? <PartyChip party={detail.party} /> : null}
          {/* one run of text: when it wraps, no separator is left at the start of a line */}
          {doc.doc_date || doc.received_date ? (
            <span>
              {doc.doc_date ? (
                <>
                  Letter of <DateText date={doc.doc_date} style="day" className="text-ink/85" />
                </>
              ) : null}
              {doc.doc_date && doc.received_date ? ", " : null}
              {doc.received_date ? (
                <>
                  {/* a court's letter is served: its one date is "delivered", as the question and the receipts say */}
                  {served ? (doc.doc_date ? "delivered" : "Delivered") : doc.doc_date ? "arrived" : "Arrived"}{" "}
                  {sameDay ? "the same day" : <DateText date={doc.received_date} style="day" className="text-ink/85" />}
                </>
              ) : null}
            </span>
          ) : null}
        </div>
        {/* money and dates the app's way, units and reference numbers kept whole ("MV-" / "2025-0412", "184.30" / "€") */}
        {doc.summary ? (
          <p className="mt-3 text-[15px] leading-relaxed text-ink/80 wrap-break-word" {...summaryLang}>
            {englishInline(doc.summary)}
          </p>
        ) : null}
        {demoNote ? (
          // the online demo's own note (a re-filed letter keeps the old kind's dates): next to what it is about
          <p className="mt-3 flex gap-2 rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-[13px] leading-snug text-warn-ink">
            <Info className="mt-px size-4 shrink-0" aria-hidden />
            <span className="min-w-0">{demoNote}</span>
          </p>
        ) : null}
      </header>

      {/* 2 — what you need to do */}
      <Section label="What you need to do" icon={ListChecks}>
        {scam ? (
          <p className="text-[16px] font-medium leading-snug text-danger-ink">
            Don't pay. Check with the real sender first — use contact details from an older letter, not from this one.
          </p>
        ) : decision ? (
          <>
            <p className="text-[16px] font-medium leading-snug text-ink">{decision.title}</p>
            <p className="mt-1 text-[13px] leading-relaxed text-muted">{decision.body}</p>
          </>
        ) : open && words && optional ? (
          <>
            <p className="flex items-start gap-2 text-[16px] font-medium leading-snug text-ink">
              <CircleCheckBig className="mt-0.5 size-[18px] shrink-0 text-ok" aria-hidden />
              <span>Nothing to do{refundText ? ` — ${refundText}` : " if the decision is right"}.</span>
            </p>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink/80 wrap-break-word">
              {/* the whole action here, however long: it is the small print under "Nothing to do" */}
              <span className="font-medium">Only if you disagree:</span>{" "}
              <GlossaryText text={keepCitations(withoutIfYouDisagree(words.body ?? words.lead))} inline markGerman />
            </p>
            {words.quote ? <LetterSays text={words.quote} /> : null}
          </>
        ) : open && words && consent ? (
          <>
            <p className="text-[16px] font-medium leading-snug text-ink">Your choice: agree to the new price — or don't.</p>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink/80 wrap-break-word">
              <span className="font-medium">If you agree:</span> <GlossaryText text={keepCitations(words.body ?? words.lead)} inline markGerman />
            </p>
            {words.quote ? <LetterSays text={words.quote} /> : null}
          </>
        ) : open && words ? (
          <>
            <p className="text-[16px] font-medium leading-snug text-ink wrap-break-word">
              {/* a citation stays whole ("§ 549 Abs. 2 BGB" broke after "Abs." at 320 px — review round 4 of phase 2) */}
              <GlossaryText text={keepCitations(words.lead)} inline markGerman />
            </p>
            {words.body ? (
              // a paragraph of law is no headline: the title leads and the action follows as body text
              // (review round 3 of phase 2: 12 lines of 16 px above the date)
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink/80 wrap-break-word">
                <GlossaryText text={keepCitations(words.body)} inline markGerman />
              </p>
            ) : null}
            {words.sub ? (
              isGermanText(words.sub) ? (
                <p lang="de" className="mt-1 text-[13px] text-muted wrap-break-word hyphens-auto">
                  {protectRefs(words.sub)}
                </p>
              ) : (
                <p className="mt-1 text-[13px] text-muted wrap-break-word">
                  <GlossaryText text={protectRefs(words.sub)} inline markGerman />
                </p>
              )
            ) : null}
            {words.quote ? <LetterSays text={words.quote} /> : null}
            {/* dated, the date box below says it */}
            {debit && !open.due_date ? <p className="mt-1 text-[13px] text-muted">Collected automatically by direct debit — nothing to transfer.</p> : null}
            {notOwed === "if_agreed" ? (
              // decided, but Ordnung doesn't know which way: a plain note, not a warning
              <p className="mt-2 flex items-start gap-1.5 text-[13.5px] leading-snug text-ink/80">
                <Info className="mt-0.5 size-3.5 shrink-0 text-muted" aria-hidden />
                <span>{NOT_OWED[notOwed]}</span>
              </p>
            ) : notOwed ? (
              <p className="mt-2 flex items-start gap-1.5 text-[13.5px] leading-snug text-warn-ink">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <span>{NOT_OWED[notOwed]}</span>
              </p>
            ) : null}
            {alsoByLaw.length ? (
              <ul className="mt-3 space-y-1.5" aria-label="Also due by law">
                {alsoByLaw.map((i) => {
                  // a law's other deadline may come first (registering as job-seeking before the court action):
                  // it gets the same countdown and urgency as the main date, never a quiet grey line
                  const urgency = i.due_date ? urgencyOf(i.due_date, today) : "later";
                  return (
                    <li
                      key={i.id}
                      className={cn("flex items-start gap-2 rounded-lg border px-3 py-2 text-[13.5px] leading-snug text-ink", i.due_date ? dateTone[urgency] : "border-transparent bg-surface-2/70")}
                    >
                      <Scale className="mt-0.5 size-3.5 shrink-0 text-muted" aria-hidden />
                      <span className="min-w-0">
                        <span className="font-medium">Also: </span>
                        <GlossaryText text={i.title} />
                        {i.due_date ? (
                          <>
                            {" "}
                            — by <DateText date={i.due_date} style="medium" className="font-semibold" />{" "}
                            <Countdown date={i.due_date} variant="pill" className="align-[1px]" />
                          </>
                        ) : null}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </>
        ) : mustAct(doc) && !isLetterSettled(detail) ? (
          // a court order, a dismissal or a landlord's notice without an open to-do (a notice without notice
          // period, or one whose end we couldn't read) is never "nothing to do" — unless the person has dealt
          // with it (objected, went to court: the server's `advice.handled`): then it is filed
          <p className="flex items-start gap-2 text-[16px] font-medium leading-snug text-ink">
            <Scale className="mt-0.5 size-[18px] shrink-0 text-warn" aria-hidden />
            <span>
              <CardLink text={ADVICE_NOW[doc.kind ?? "default"] ?? ADVICE_NOW.default} docId={doc.id} />
            </span>
          </p>
        ) : replaced ? (
          // an invoice its payment reminder took over: never "Pay" here as well (UI audit round 1)
          <div className="flex items-start gap-2">
            <CircleCheckBig className="mt-0.5 size-[18px] shrink-0 text-ok" aria-hidden />
            <div className="min-w-0">
              <p className="text-[16px] font-medium leading-snug text-ink">Nothing to pay on this letter — a payment reminder replaced it.</p>
              <p className="mt-1 text-[13.5px] leading-relaxed text-ink/80">
                Pay the reminder{reminderDate ? (
                  <>
                    {" "}
                    of <DateText date={reminderDate} style="short" />
                  </>
                ) : null}{" "}
                instead — pay once, not twice.
              </p>
            </div>
          </div>
        ) : doc.ai_private && !doc.ai_processed_at ? (
          <NotRead doc={doc} canWaitAgain={detail.can_wait_again} onAnswered={onAnswered} />
        ) : (
          <p className="flex items-start gap-2 text-[15px] font-medium leading-snug text-ink">
            <CircleCheckBig className="mt-0.5 size-[18px] shrink-0 text-ok" aria-hidden />
            <span>{refundText ? `Nothing to do — ${refundText}.` : "Nothing right now — it's filed for your records."}</span>
          </p>
        )}
      </Section>

      {/* 3 — by when */}
      {decision?.due_date ? (
        <Section label="Decide by" icon={Clock}>
          <div className={cn("rounded-xl border px-4 py-3.5", dateTone[urgencyOf(decision.due_date, today)])}>
            <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
              <p className="display text-[28px] font-semibold leading-none text-ink sm:text-[32px]">
                <time dateTime={decision.due_date}>{formatDate(decision.due_date, { style: "short", today })}</time>
              </p>
              <span className={cn(PILL, countdownTone[urgencyOf(decision.due_date, today)])}>{formatRelativeDays(decision.due_date, today)}</span>
            </div>
            <p className={LINE}>
              <Mail className={LINE_ICON} aria-hidden />
              <span>If you cancel by post, send it by this day so it arrives in time.</span>
            </p>
          </div>
        </Section>
      ) : null}
      {!scam && open?.due_date ? (
        <DateBox
          item={open}
          optional={optional}
          decide={consent}
          debit={debit}
          checkDate={checkDate}
          askArrival={askArrival}
          served={isServed(doc, [open])}
          onAskArrival={onAskArrival}
        />
      ) : null}

      {/* 4 — if you ignore it */}
      {scam ? (
        <Section label="If you pay" icon={TriangleAlert}>
          <p className="text-[14.5px] leading-relaxed text-ink/85">
            The money goes to an account this sender has never used before, and may be hard to get back.
          </p>
        </Section>
      ) : decision ? (
        <Section label="If you do nothing" icon={CircleCheckBig}>
          <p className="text-[14.5px] leading-relaxed text-ink/85">
            {decision.rule_id === "price_increase_right"
              ? "Nothing bad happens — the contract simply continues at the new price."
              : "Nothing bad happens — the contract simply continues."}
          </p>
        </Section>
      ) : open?.consequence ? (
        <Consequence text={open.consequence} label={consent ? "If you don't agree" : optional ? "If you do nothing" : "If you ignore it"} />
      ) : null}

      {/* 5 — to-dos that are not one to act on: quiet, after the verdict, never between it and its date */}
      {asides.length ? (
        <Section label="Probably dealt with" icon={History}>
          <ul className="space-y-1.5" aria-label="Probably dealt with">
            {asides.map((a) => (
              <AsideRow key={a.item.id} entry={a} detail={detail} />
            ))}
          </ul>
        </Section>
      ) : null}

      <Actions detail={detail} main={main} primary={open} optional={optional || consent} footer={footer} />
    </article>
  );
}

const PILL = "inline-flex items-center rounded-full px-2.5 py-1 text-[13px] font-semibold tabular-nums leading-4";
/** A line under the big date: the icon sits on the first line when the text wraps. */
const LINE = "mt-2.5 flex items-start gap-1.5 text-[13px] leading-5 text-ink/80";
const LINE_ICON = "mt-[3px] size-3.5 shrink-0 text-muted";

/**
 * The big date of the to-do the verdict is about. A transfer counts to the day it has to go out ("Transfer
 * by Tue 29 Sep · tomorrow", then "Due Wed 30 Sep") — the day that matters first; a direct debit says when it
 * is collected, in quiet colours (nothing to do but keep the money there).
 */
function DateBox({
  item,
  optional,
  decide = false,
  debit,
  checkDate,
  askArrival,
  served,
  onAskArrival,
}: {
  item: Item;
  optional: boolean;
  /** a choice to make by the date (a price increase that asks for consent) */
  decide?: boolean;
  debit: boolean;
  checkDate: boolean;
  askArrival: boolean;
  served: boolean;
  onAskArrival?: () => void;
}) {
  const today = useToday();
  const due = item.due_date!;
  const isAppointment = item.kind === "appointment";
  const mode = isAppointment ? "event" : "due";
  // the transfer has to go out first: its day leads while it is still ahead
  const transferBy =
    item.kind === "payment" && item.direction !== "in" && !debit && item.send_by && item.send_by !== due && daysUntil(item.send_by, today) >= 0
      ? item.send_by
      : null;
  const shown = transferBy ?? due;
  const urgency = urgencyOf(shown, today, mode);
  const label = isAppointment ? "When" : optional ? "Only if you disagree" : decide ? "Decide by" : debit ? "Collected on" : transferBy ? "Transfer by" : "By when";
  return (
    <Section label={label} icon={debit ? Landmark : Clock}>
      <div className={cn("rounded-xl border px-4 py-3.5", optional || debit ? dateTone.later : dateTone[urgency])}>
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <p className="display text-[28px] font-semibold leading-none text-ink sm:text-[32px]">
            <time dateTime={shown}>{formatDate(shown, { style: "short", today })}</time>
            {!transferBy && item.due_time ? <span className="ml-2 text-[20px] text-ink/70">{formatTime(item.due_time)}</span> : null}
          </p>
          <span className={cn(PILL, debit ? countdownTone.month : countdownTone[urgency])}>{formatRelativeDays(shown, today, mode)}</span>
        </div>
        {debit ? (
          <p className={LINE}>
            <Landmark className={LINE_ICON} aria-hidden />
            <span>Collected automatically — keep the money in your account.</span>
          </p>
        ) : transferBy ? (
          <p className={LINE}>
            <Landmark className={LINE_ICON} aria-hidden />
            <span>
              Due <DateText date={due} className="font-semibold text-ink" /> — it has to reach their account by then.
            </span>
          </p>
        ) : item.send_by && item.send_by !== due ? (
          <p className={LINE}>
            {item.kind === "payment" ? <Landmark className={LINE_ICON} aria-hidden /> : <Mail className={LINE_ICON} aria-hidden />}
            <span>
              {item.kind === "payment" ? "Transfer it by" : "By post, send it by"} <DateText date={item.send_by} className="font-semibold text-ink" />
            </span>
          </p>
        ) : null}
        {checkDate ? (
          <p className="mt-2.5 flex items-start gap-1.5 text-[13px] leading-5 text-warn-ink">
            <TriangleAlert className="mt-[3px] size-3.5 shrink-0" aria-hidden />
            <span>
              {item.slot_key === READING_CHECK_SLOT || isDeadlineCheck(item)
                ? "Ordnung took this date from the letter itself — please check it below."
                : "We couldn't find this date in the letter — please check it below."}
            </span>
          </p>
        ) : null}
        {askArrival ? (
          <p className="mt-2.5 flex items-start gap-1.5 text-[13px] leading-5 text-warn-ink">
            <TriangleAlert className="mt-[3px] size-3.5 shrink-0" aria-hidden />
            <span>
              Counted from the letter date — the earliest possible.{" "}
              {onAskArrival ? (
                <button type="button" onClick={onAskArrival} className="font-semibold underline underline-offset-2 hover:no-underline">
                  {served ? "Tell us when it was delivered" : "Tell us when it arrived"}
                </button>
              ) : null}
            </span>
          </p>
        ) : null}
        {item.computation ? (
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
            <WhyThisDate receipt={item.computation} spec={item.date_spec} area={item.area} origin={item.origin} item={item} />
            {/* the person confirmed it: their date, not ours to doubt (a receipt keeps its low grade) */}
            {item.computation.confidence !== "high" && item.grounding !== "user" ? (
              <span className="text-[12px] text-muted">{item.computation.confidence === "medium" ? "Worth a second look" : "Please check this date"}</span>
            ) : null}
          </div>
        ) : null}
      </div>
    </Section>
  );
}

/** "If you ignore it": English first — a German consequence as what it warns of, its words below. */
function Consequence({ text, label }: { text: string; label: string }) {
  const c = consequenceWords(text);
  return (
    <Section label={label} icon={TriangleAlert}>
      <p className="text-[14.5px] leading-relaxed text-ink/85 wrap-break-word">
        <GlossaryText text={keepCitations(c.lead)} inline markGerman />
      </p>
      {c.quote ? <LetterSays text={c.quote} /> : null}
    </Section>
  );
}

/**
 * A to-do the server set aside, quietly under what to do: "replaced by the payment reminder of Thu 10 Sep —
 * pay that one, not both" with a link to it, or "Still open? … was due 1 Oct 2025" with Mark done.
 */
function AsideRow({ entry, detail }: { entry: AsideItem; detail: DocumentDetail }) {
  const { item, aside } = entry;
  const actions = useItemActions();
  const date = item.due_date;
  if (aside.reason === "replaced") {
    const reminder = detail.related.find((d) => d.id === aside.replaced_by);
    const when = reminder?.doc_date ?? reminder?.received_date;
    return (
      <li className="rounded-lg border border-line bg-surface-2/60 px-3 py-2 text-[13.5px] leading-snug text-ink/85">
        <span className="min-w-0 wrap-break-word">
          <GlossaryText text={protectRefs(item.title)} inline markGerman /> — replaced by the payment reminder
          {when ? (
            <>
              {" "}
              of <DateText date={when} style="short" />
            </>
          ) : null}
          : pay that one, not both.{" "}
          {aside.replaced_by ? (
            <Link to={`/documents/${aside.replaced_by}`} className="inline-flex min-h-6 items-center gap-1 font-medium text-accent underline-offset-2 hover:underline">
              Open the reminder
              <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          ) : null}
        </span>
      </li>
    );
  }
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line bg-surface-2/60 px-3 py-2 text-[13.5px] leading-snug text-ink/85">
      <span className="min-w-0 flex-1 basis-56">
        <span className="wrap-break-word">
          <span className="font-medium">Still open?</span> <GlossaryText text={protectRefs(item.title)} inline markGerman />
          {date ? (
            <>
              {" "}
              was due <DateText date={date} style="day" /> — already past when the letter was added, so probably dealt with.
            </>
          ) : (
            " — probably dealt with already."
          )}
        </span>
      </span>
      <Button variant="ghost" size="sm" icon={Check} className="ml-auto" aria-label={`Mark “${item.title}” done`} onClick={() => actions.markDone(item)}>
        Mark done
      </Button>
    </li>
  );
}

/** Letters about a tenancy: their advice is the tenants' association's, whatever area the letter was read under. */
const TENANCY_KINDS = new Set(["landlord_notice", "rent_increase", "operating_costs"]);

/**
 * The verdict's "Unsure? Get independent advice" link: a high-stakes letter's from its card's kind — the
 * tenants' association for a tenancy letter, none for the others (the card lists its own help: a court's
 * desk, a union) — never the area's (review round 2: a statement read under "residence" pointed to the
 * Studierendenwerk while its card listed the Mieterverein); any other letter's from its kind, sender and area
 * ({@link adviceFor}).
 */
function verdictAdvice(advice: DocumentDetail["advice"], area: Item["area"], docKind?: DocumentKind | null, partyKind?: PartyKind | null) {
  if (advice) return TENANCY_KINDS.has(advice.kind) ? ADVICE_LINKS.rent : undefined;
  return adviceFor(area, docKind, partyKind);
}

/** "Keep it": the person decided not to cancel — the decision Idea goes (with undo). */
function KeepButton({ suggestion }: { suggestion: Suggestion }) {
  const update = useUpdateSuggestion();
  return (
    <Button
      variant="ghost"
      icon={Check}
      loading={update.isPending}
      onClick={() =>
        // the promise, not mutate's callbacks: this button leaves with its Idea once the lists are refreshed, and a
        // button that has gone gets no callbacks (review round 4 of phase 2)
        update.mutateAsync({ id: suggestion.id, patch: { status: "dismissed" } }).then(
          () =>
            toast({
              title: "Kept",
              description: "Ordnung won't remind you about this window again.",
              undo: () => update.mutate({ id: suggestion.id, patch: { status: "new" } }),
            }),
          () => undefined, // the error toast comes from the mutation's meta
        )
      }
    >
      Keep it
    </Button>
  );
}

const DRAFT_NOUN: Partial<Record<DraftKind, string>> = { objection: "objection", cancellation: "cancellation" };

/**
 * A letter of this kind the person already started: "Continue your objection" (or "Open your objection" once
 * sent) with its status, instead of drafting a second one.
 */
function StartedDraft({ kind, detail, quiet }: { kind: DraftKind; detail: DocumentDetail; quiet?: boolean }) {
  const draft = existingDraft(detail.drafts, kind);
  if (!draft) return null;
  const noun = DRAFT_NOUN[kind] ?? "letter";
  const sent = draft.status === "sent";
  return (
    <>
      <Link to={`/letters/${draft.id}`} className={buttonVariants({ variant: quiet || sent ? "secondary" : "primary" })}>
        <PenLine aria-hidden />
        {sent ? `Open your ${noun}` : `Continue your ${noun}`}
      </Link>
      <StatusPill of="draft" status={draft.status} />
    </>
  );
}

/** "Add to calendar": downloads the date as a calendar file and says so (it used to download silently). */
function CalendarButton({ item, primary }: { item: Item; primary?: boolean }) {
  return (
    <a
      href={icsHref(item)}
      download={icsFileName(item)}
      className={buttonVariants({ variant: primary ? "primary" : "secondary" })}
      onClick={() => toast.success("Calendar file downloaded", { description: "Open it to add the date to your calendar." })}
    >
      <CalendarPlus aria-hidden />
      Add to calendar
    </a>
  );
}

function Actions({
  detail,
  main,
  primary,
  optional,
  footer,
}: {
  detail: DocumentDetail;
  main: MainAction;
  primary: Item | null;
  optional: boolean;
  /** The disclaimer or the advice links: inside the band, under the buttons. */
  footer: ReactNode;
}) {
  const doc = detail.document;
  const actions = useItemActions();
  const draft = useStartDraft();
  // the calendar file stays on the computer (ADR 0017): a phone offers no "Add to calendar"
  const phone = usePhoneCompanion();

  const mainEl: ReactNode = (() => {
    switch (main.type) {
      case "decide": {
        const target = main.suggestion.action?.target_type === "contract" ? main.suggestion.action.target_id : null;
        return (
          <>
            {existingDraft(detail.drafts, "cancellation") ? (
              <StartedDraft kind="cancellation" detail={detail} />
            ) : (
              <Button
                variant="primary"
                icon={PenLine}
                loading={draft.pending}
                onClick={() => draft.start("cancellation", { doc_id: doc.id, contract_id: target, party_id: doc.party_id, case_id: doc.case_id })}
              >
                Draft cancellation
              </Button>
            )}
            <KeepButton suggestion={main.suggestion} />
          </>
        );
      }
      case "draft":
        // started already: continue that letter, never a second one (UI audit round 1)
        if (existingDraft(detail.drafts, main.draftKind)) return <StartedDraft kind={main.draftKind} detail={detail} quiet={optional} />;
        // an objection that may ask to suspend enforcement: the composer asks (an explicit choice, §§ 719,
        // 707 ZPO / Aussetzung der Vollziehung) — never drafted without the question
        // … and one to a court order filed from a sender that is no court: the composer asks for the court
        // (the objection never goes to the claimant — review round 3 of phase 2)
        if (main.draftKind === "objection" && (canSuspend(doc) || needsTypedCourt(doc, detail.party))) {
          return (
            <Link to={composerHref("objection", { docId: doc.id })} className={buttonVariants({ variant: optional ? "secondary" : "primary" })}>
              <PenLine aria-hidden />
              {main.label}
            </Link>
          );
        }
        return (
          <Button
            variant={optional ? "secondary" : "primary"}
            icon={PenLine}
            loading={draft.pending}
            onClick={() =>
              draft.start(main.draftKind, {
                doc_id: doc.id,
                contract_id: main.item?.contract_id ?? null,
                party_id: doc.party_id,
                case_id: doc.case_id,
              })
            }
          >
            {main.label}
          </Button>
        );
      case "pay":
        return (
          <Popover label="Pay" placement="top-start" className="w-[22rem] p-4" content={(close) => (
              <PayPanel
                item={main.item}
                doc={doc}
                code={detail.girocodes.find((g) => g.item_id === main.item.id)}
                onPaid={() => actions.markDone(main.item, { title: "Marked as paid" })}
                close={close}
              />
            )}>
            <Button variant="primary" icon={Landmark}>
              Pay {main.item.amount != null ? formatMoney(main.item.amount, { currency: main.item.currency }) : ""}
            </Button>
          </Popover>
        );
      case "calendar":
        return phone ? null : <CalendarButton item={main.item} primary />;
      case "done":
        return (
          <Button variant="primary" icon={Check} onClick={() => actions.markDone(main.item)}>
            Mark done
          </Button>
        );
      case "reminder":
        return (
          <Link to={`/documents/${main.docId}`} className={buttonVariants({ variant: "primary" })}>
            Open the payment reminder
            <ArrowRight aria-hidden />
          </Link>
        );
      case "scam":
        return main.realDocId ? (
          <Link to={`/documents/${main.realDocId}`} className={buttonVariants({ variant: "secondary" })}>
            Compare with your real letter
            <ArrowRight aria-hidden />
          </Link>
        ) : null;
      default:
        return null;
    }
  })();

  const showCalendar = !phone && primary?.due_date && main.type !== "calendar" && main.type !== "scam" && main.type !== "decide";
  const showDone = primary && main.type !== "done" && main.type !== "scam" && main.type !== "decide";
  const buttons = Boolean(mainEl || showCalendar || showDone);
  if (!buttons && !footer) return null;

  return (
    <div className="border-t border-line bg-surface-2/40 px-5 py-4 sm:px-6">
      {buttons ? (
        <div className="flex flex-wrap items-center gap-2">
          {mainEl}
          {showCalendar && primary ? <CalendarButton item={primary} /> : null}
          {/* the quiet one sits apart at the end of the row (it wrapped alone and indented at 320 px) */}
          {showDone && primary ? (
            <Button variant="ghost" icon={Check} className="ml-auto" onClick={() => actions.markDone(primary)}>
              Mark done
            </Button>
          ) : null}
        </div>
      ) : null}
      {/* the disclaimer belongs to the dates and buttons above: inside the band, not loose under it */}
      {footer ? <div className={cn(buttons && "mt-3.5 border-t border-line pt-3")}>{footer}</div> : null}
    </div>
  );
}
