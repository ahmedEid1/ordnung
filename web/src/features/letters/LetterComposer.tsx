import { Fragment, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { Building2, Check, FileX, Languages, Mail, Plus, Scale, Search, Sparkles, type LucideIcon } from "lucide-react";
import { useContracts, useCreateDraft, useDocument, useDocuments, useParties, useProfile, useSuggestions } from "@/api/hooks";
import type { Contract, Document, DraftKind, Party } from "@/api/types";
import { useOptionalAddLetters } from "@/components/shell/AddLetters";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { Dialog } from "@/components/ui/Dialog";
import { AdviceLinks, Disclaimer } from "@/components/ui/Disclaimer";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Glossary } from "@/components/ui/Glossary";
import { KindIcon } from "@/components/ui/KindBadge";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { Avatar } from "@/components/ui/Avatar";
import { CONTRACT_CATEGORY_COPY, copyFor, documentKindLabel, partyKindLabel } from "@/lib/copy";
import { useTodayISO } from "@/lib/today";
import { keepCitations, protectRefs } from "@/lib/glue";
import { cn, prefersReducedMotion } from "@/lib/utils";
import { offersEndingLetter } from "@/features/contracts/links";
import { isRollingContract } from "@/features/contracts/model";
import {
  canSuspend,
  cancellableContracts,
  letterDate,
  mayBeCourt,
  needsTypedCourt,
  objectionCheck,
  objectionDeadline,
  objectionDocuments,
  namesHousehold,
  sameName,
  usableDocuments,
  type ComposerPrefill,
} from "./logic";
import {
  SCHUFA_ADDRESS,
  TEMPLATES,
  TEMPLATE_BY_KIND,
  detailsPayload,
  fieldError,
  isTemplateKind,
  joinAnd,
  letterDefaults,
  missingFields,
  sortForTemplate,
  statutoryDeadlines,
  templateRefusal,
  type DetailValues,
  type TemplateConfig,
  CLAIMANT_NOTE,
} from "./templates";
import { TemplateFields } from "./TemplateFields";

interface KindOption {
  kind: DraftKind;
  title: string;
  description: ReactNode;
  icon: LucideIcon;
}

const KIND_OPTIONS: KindOption[] = [
  { kind: "cancellation", title: "Cancel a contract", description: <>End a contract — <Glossary term="Kündigung" translate={false} plain />: phone, gym, electricity…</>, icon: FileX },
  {
    kind: "objection",
    title: "Object to a decision",
    description: (
      <>
        <Glossary term="Einspruch" translate={false} plain /> or <Glossary term="Widerspruch" translate={false} plain /> against a decision or court order
      </>
    ),
    icon: Scale,
  },
  { kind: "general_reply", title: "Reply to a letter", description: "Answer, ask a question or send a document", icon: Mail },
];

const PLACEHOLDER: Record<"cancellation" | "objection" | "general_reply", string> = {
  cancellation: "e.g. Please confirm by email. I'm moving abroad at the end of the year.",
  objection: "e.g. My laptop is used mainly for work — my employer can confirm this.",
  general_reply: "e.g. Ask for the receipts behind the utility bill and suggest paying in two instalments.",
};

/** An objection's example wishes by the kind of letter it answers (a tax example fits only a tax letter). */
const OBJECTION_PLACEHOLDER: Partial<Record<NonNullable<Document["kind"]>, string>> = {
  court_payment_order: "e.g. I cancelled this subscription in 2022 and owe nothing.",
  enforcement_order: "e.g. I never received the payment order this is based on.",
  landlord_notice: "e.g. My child changes school next year, and I have nowhere else to go.",
};

function wishesPlaceholder(kind: DraftKind, letterKind?: Document["kind"] | null): string {
  if (isTemplateKind(kind)) return TEMPLATE_BY_KIND[kind].wishes;
  if (kind === "objection" && letterKind) return OBJECTION_PLACEHOLDER[letterKind] ?? PLACEHOLDER.objection;
  return PLACEHOLDER[kind];
}

/** A choice's radio circle — every way to choose in the composer shows one (a tick once chosen). */
function RadioDot({ selected, className }: { selected: boolean; className?: string }) {
  return (
    <span
      className={cn(
        "grid size-5 shrink-0 place-items-center rounded-full border transition-colors",
        selected ? "border-accent bg-accent text-on-accent" : "border-line-strong bg-surface",
        className,
      )}
      aria-hidden
      data-radio-dot
    >
      {selected ? <Check className="size-3" strokeWidth={3} /> : null}
    </span>
  );
}

/** The focus ring of a card that holds a visually hidden radio: only the radio's own keyboard focus rings it. */
const CARD_FOCUS = "has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-accent";
const CARD_STATE = (selected: boolean) =>
  selected ? "border-accent/60 bg-accent-soft/50 shadow-[0_0_0_1px_var(--color-accent)]" : "border-line bg-surface hover:border-line-strong";

function OptionRow({
  selected,
  disabled,
  onSelect,
  children,
  name,
  value,
}: {
  selected: boolean;
  disabled?: boolean;
  onSelect: () => void;
  children: ReactNode;
  name: string;
  value: string;
}) {
  return (
    <label
      className={cn(
        "group relative flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 transition-[border-color,background-color,box-shadow]",
        CARD_FOCUS,
        CARD_STATE(selected),
        disabled && "cursor-not-allowed opacity-55 hover:border-line",
      )}
    >
      <input type="radio" name={name} value={value} checked={selected} disabled={disabled} onChange={onSelect} className="sr-only" />
      {children}
      <RadioDot selected={selected} />
    </label>
  );
}

function StepLabel({ n, children, id }: { n: number; children: ReactNode; id?: string }) {
  return (
    <h3 id={id} className="mb-2.5 flex items-center gap-2 text-[13px] font-semibold text-ink">
      {/* read as "Step 1: What do you want to do?", never "1What do you…" */}
      <span aria-hidden className="grid size-5 shrink-0 place-items-center rounded-full bg-surface-3 text-[11px] font-bold text-muted">
        {n}
      </span>
      <span className="sr-only">Step {n}: </span>
      {children}
    </h3>
  );
}

function ListSkeleton() {
  return (
    <div className="space-y-2" aria-hidden>
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-14 w-full rounded-xl" />
      ))}
    </div>
  );
}

/**
 * A choice's words: its name on up to two lines (the whole of it on hover and for screen readers — two
 * statements for two years differ only at the end), then the facts that tell it apart, one separator
 * style, wrapping rather than cut off.
 */
function OptionText({ title, meta, below }: { title: string; meta: ReactNode[]; below?: ReactNode }) {
  const parts = meta.filter((p) => p !== null && p !== undefined && p !== false && p !== "");
  return (
    <span className="min-w-0 flex-1">
      {/* a phone's narrow row gets a third line ("Gesetzliche Kranken- und Pflegeversicherung bei Muster BKK") */}
      {/* a reference stays whole ("TM-2026-0048213", never "TM- / 2026-…"); the title keeps it plain */}
      <span title={title} className="line-clamp-3 break-words text-[14px] font-medium leading-snug text-ink sm:line-clamp-2">
        {protectRefs(title)}
      </span>
      {parts.length ? (
        <span className="mt-0.5 block text-[12.5px] leading-snug text-muted [overflow-wrap:anywhere]">
          {parts.map((p, i) => (
            <Fragment key={i}>
              {i ? (
                <>
                  {" "}
                  <span aria-hidden>·</span>{" "}
                </>
              ) : null}
              {p}
            </Fragment>
          ))}
        </span>
      ) : null}
      {below}
    </span>
  );
}

/** A contract that can be cancelled any month: no countdown, nothing runs out (as on its card and in People). */
function AnyMonthPill({ className }: { className?: string }) {
  return (
    <span data-any-month className={cn("whitespace-nowrap rounded-full bg-surface-3 px-2 py-[3px] text-xs font-medium leading-4 text-muted", className)}>
      Cancel any month
    </span>
  );
}

function ContractOption({ c, party }: { c: Contract; party?: Party }) {
  // a contract you can cancel any month has no window that closes: its "send by" only says when it
  // would end, so it never counts down in red (UI audit round 2)
  const rolling = isRollingContract(c);
  const sendBy = rolling ? null : c.computed?.send_by;
  return (
    <>
      <KindIcon category={c.category} size="md" />
      <OptionText
        title={c.name}
        meta={[party?.name, copyFor(CONTRACT_CATEGORY_COPY, c.category).label]}
        // phones: the send-by date as a line of its own (a pill beside the name from 640 px)
        below={
          sendBy ? (
            <Countdown date={sendBy} prefix="Send by" className="mt-0.5 block text-[12.5px] leading-snug sm:hidden" />
          ) : rolling ? (
            <span className="mt-0.5 block text-[12.5px] font-medium leading-snug text-muted sm:hidden">Cancel any month</span>
          ) : null
        }
      />
      {sendBy ? <Countdown date={sendBy} prefix="Send by" variant="pill" className="hidden sm:inline-flex" /> : null}
      {rolling ? <AnyMonthPill className="hidden sm:inline-flex" /> : null}
    </>
  );
}

function DocOption({ d, party, pill }: { d: Document; party?: Party; pill?: ReactNode }) {
  const date = letterDate(d);
  return (
    <>
      <KindIcon docKind={d.kind} size="md" />
      <OptionText
        title={d.title ?? d.filename}
        meta={[party?.name ?? documentKindLabel(d.kind), date ? <DateText key="date" date={date} style="day" /> : null]}
        below={pill ? <span className="mt-1 flex sm:hidden">{pill}</span> : null}
      />
      {pill ? <span className="hidden shrink-0 sm:inline-flex">{pill}</span> : null}
    </>
  );
}

/** "Widerspruch possible": said on phones too (under the letter's name), not only beside it from 640 px. */
function PossiblePill({ term }: { term: string }) {
  return <span className="whitespace-nowrap rounded-full bg-k-expiry-soft px-2 py-0.5 text-[12px] font-medium text-k-expiry-ink">{term} possible</span>;
}

/** The box `el` scrolls in (the dialog's body), if any. */
function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p; p = p.parentElement) {
    const y = getComputedStyle(p).overflowY;
    if ((y === "auto" || y === "scroll") && p.scrollHeight > p.clientHeight) return p;
  }
  return null;
}

/** Rows a list shows before "Show all": the chosen one is always among them. */
const LIST_PREVIEW = 5;
/** Rows a list shows at most — searching finds the others. */
const LIST_CAP = 30;

/**
 * The choices of step 2, in the dialog's own scroll (no second scrolling box inside it, where a chosen
 * contract sat out of view): the one the composer was opened with first — right under the step's heading,
 * where the composer scrolls to — then the first few, the chosen one always among them, and "Show all"
 * for the rest (UI audit round 1).
 */
function ChoiceList<T extends { id: string }>({
  items,
  selectedId,
  labelledBy,
  noun,
  render,
  emptyText,
}: {
  items: readonly T[];
  selectedId: string | null;
  labelledBy: string;
  /** "contracts", "letters", "decisions" — for "Show all 9 contracts". */
  noun: string;
  render: (item: T) => ReactNode;
  emptyText?: string | null;
}) {
  const listId = useId();
  const [expanded, setExpanded] = useState(false);
  // what was chosen when the list appeared came with the link that opened the composer; it stays first
  // (a later choice never moves under the pointer)
  const [pinned] = useState(selectedId);
  const ordered = useMemo(() => {
    const first = pinned ? items.find((i) => i.id === pinned) : undefined;
    return first ? [first, ...items.filter((i) => i !== first)] : items;
  }, [items, pinned]);
  const capped = ordered.slice(0, LIST_CAP);
  const foldable = capped.length > LIST_PREVIEW + 1;
  let shown: readonly T[] = foldable && !expanded ? capped.slice(0, LIST_PREVIEW) : capped;
  const chosen = selectedId ? items.find((i) => i.id === selectedId) : undefined;
  if (chosen && !shown.includes(chosen)) shown = [chosen, ...(foldable && !expanded ? shown.slice(0, LIST_PREVIEW - 1) : shown)];
  const more = items.length - capped.length;
  return (
    <div>
      <div role="radiogroup" id={listId} aria-labelledby={labelledBy} className="space-y-2" data-choice-list>
        {shown.map(render)}
        {!items.length && emptyText ? <p className="px-1 py-2 text-base text-muted">{emptyText}</p> : null}
      </div>
      {foldable || more > 0 ? (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
          {foldable ? (
            <Button variant="link" size="sm" aria-expanded={expanded} aria-controls={listId} onClick={() => setExpanded((v) => !v)}>
              {expanded ? "Show fewer" : more > 0 ? `Show ${capped.length} of ${items.length} ${noun}` : `Show all ${capped.length} ${noun}`}
            </Button>
          ) : null}
          {more > 0 && (expanded || !foldable) ? (
            <p className="text-[12.5px] leading-5 text-muted">
              Showing {capped.length} of {items.length} — search to find another.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** The letter chosen for an objection that can't be objected to — shown as chosen, not as a choice. */
function ChosenLetter({ d, party }: { d: Document; party?: Party }) {
  return (
    <div className="mb-2 flex items-center gap-3 rounded-xl border border-warn/40 bg-surface px-3 py-2.5" data-chosen-letter>
      <span className="sr-only">The letter you chose: </span>
      <DocOption d={d} party={party} />
    </div>
  );
}

/** Step 2 with nothing to choose (an empty install): why, and the way on — never a dead end. */
function NothingYet({ title, children, onAdd }: { title: string; children: ReactNode; onAdd: (() => void) | null }) {
  return (
    <Callout
      tone="info"
      title={title}
      action={
        onAdd ? (
          <Button size="sm" icon={Plus} onClick={onAdd}>
            Add letters
          </Button>
        ) : (
          <Link to="/inbox" className={buttonVariants({ size: "sm" })}>
            Go to the inbox
          </Link>
        )
      }
    >
      {children}
    </Callout>
  );
}

/** What the composer promises: the dialog's description. */
const ABOUT = "The legal sentences come from fixed templates; Claude only adds polite wording and the translation.";

type NothingKind = "cancellation" | "objection" | "general_reply" | "template";

/** What an empty install says in step 2, in the kind cards and next to the disabled button. */
const NOTHING: Record<NothingKind, { title: string; body: string; card: string; reason: string }> = {
  cancellation: {
    title: "No contracts to cancel yet",
    body: "Ordnung finds your contracts in the letters you add — a contract confirmation or a welcome letter, say. Add one, and it's listed here.",
    card: "No contracts yet — add a contract letter first.",
    reason: "Add a contract letter first — there's no contract to cancel yet.",
  },
  objection: {
    title: "No decision to object to yet",
    body: "An objection answers a decision whose letter explains how to object — a tax assessment, say. Add that letter, and it's listed here.",
    card: "None of your letters is a decision you can object to.",
    reason: "Add the decision first — none of your letters can be objected to.",
  },
  general_reply: {
    title: "No letters to answer yet",
    body: "Add the letter you want to answer. Any letter from a person or office also lets you write to them.",
    card: "No letters yet — add a letter first.",
    reason: "Add a letter first — there's nothing to answer yet.",
  },
  template: {
    title: "No one to write to yet",
    body: "Add a letter from them first — Ordnung takes their name and address from it.",
    card: "",
    reason: "Add a letter from them first — there's no one to write to yet.",
  },
};


/** Why an objection is possible when the law, not the letter's instructions, gives it. */
function StatutoryNote({ kind, term }: { kind: Document["kind"]; term: "Einspruch" | "Widerspruch" }) {
  if (kind === "landlord_notice") {
    return (
      <>
        If moving out would be a real hardship for you or your family, the law lets you object — a <Glossary term={term} /> (§{"\u00a0"}574 BGB). Text form is
        enough, so email counts; a signed letter by Einwurf-Einschreiben is the safest proof. A tenants' association can check your reasons first.
      </>
    );
  }
  if (kind === "enforcement_order") {
    return (
      <>
        The law gives you an <Glossary term={term} /> against an enforcement order (§{"\u00a0"}700 ZPO). It goes to the court that sent it; reasons can follow. The
        order can still be enforced while your objection is pending — tick below to ask the court to suspend it.
      </>
    );
  }
  return (
    <>
      The law gives you a <Glossary term={term} /> against a court payment order (§{"\u00a0"}694 ZPO). It goes to the court that sent it — no reasons needed. This
      letter objects to the whole claim. To object to only part of it (only the interest or the costs, say), use the form that came with the order and
      tick how much you object to — send the form or this letter, not both.
    </>
  );
}

/**
 * Step 1: the three everyday letters as cards, then the template letters as compact tiles. A card with
 * nothing to act on (no contracts, no decision to object to, no letters) is disabled with the reason
 * instead of its description — unless it is the chosen one (opened by a link), where step 2 says why.
 */
function KindChooser({ kind, onPick, unavailable }: { kind: DraftKind | null; onPick: (k: DraftKind) => void; unavailable: Partial<Record<DraftKind, string>> }) {
  return (
    <fieldset className="min-w-0">
      <legend className="sr-only">What do you want to do?</legend>
      <div className="grid gap-2 sm:grid-cols-3">
        {KIND_OPTIONS.map((o) => {
          const selected = kind === o.kind;
          const reason = selected ? undefined : unavailable[o.kind];
          const disabled = Boolean(reason);
          return (
            <label
              key={o.kind}
              className={cn(
                "relative grid cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-0.5 rounded-xl border p-3 transition-[border-color,background-color,box-shadow] sm:flex sm:flex-col sm:items-start sm:gap-2 sm:p-3.5",
                CARD_FOCUS,
                CARD_STATE(selected),
                disabled && "cursor-not-allowed bg-surface-2/40 hover:border-line",
              )}
            >
              <input type="radio" name="letter-kind" value={o.kind} checked={selected} disabled={disabled} onChange={() => onPick(o.kind)} className="sr-only" />
              {/* a disabled card fades its icon, name and circle — never the reason, which must stay readable */}
              <span className={cn("row-span-2 grid size-8 place-items-center rounded-lg", selected ? "bg-accent text-on-accent" : "bg-surface-2 text-muted", disabled && "opacity-55")}>
                <o.icon className="size-4" aria-hidden />
              </span>
              <span className={cn("text-[14px] font-semibold", disabled ? "text-muted" : "text-ink")}>{o.title}</span>
              <span className="col-start-2 text-[12.5px] leading-snug text-muted">{reason ?? o.description}</span>
              <RadioDot selected={selected} className={cn("col-start-3 row-span-2 row-start-1 sm:absolute sm:right-3 sm:top-3", disabled && "opacity-40")} />
            </label>
          );
        })}
      </div>
      <p id="cmp-more" className="eyebrow mb-2 mt-4">
        More letters from templates
      </p>
      <div role="group" aria-labelledby="cmp-more" className="grid gap-2 min-[480px]:grid-cols-2">
        {TEMPLATES.map((t) => {
          const selected = kind === t.kind;
          return (
            <label
              key={t.kind}
              className={cn(
                "relative flex cursor-pointer items-start gap-2.5 rounded-xl border px-3 py-2.5 transition-[border-color,background-color,box-shadow]",
                CARD_FOCUS,
                CARD_STATE(selected),
              )}
            >
              <input type="radio" name="letter-kind" value={t.kind} checked={selected} onChange={() => onPick(t.kind)} className="sr-only" />
              <span className={cn("mt-px grid size-7 shrink-0 place-items-center rounded-lg", selected ? "bg-accent text-on-accent" : "bg-surface-2 text-muted")}>
                <t.icon className="size-3.5" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-semibold leading-5 text-ink">{t.title}</span>
                <span className="block text-[12px] leading-snug text-muted">{t.blurb}</span>
              </span>
              <RadioDot selected={selected} className="mt-1" />
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

export interface LetterComposerProps {
  open: boolean;
  onClose: () => void;
  prefill: ComposerPrefill | null;
}

/**
 * "New letter": what (cancel / object / reply, or one of the template letters) → which contract,
 * letter or recipient → the facts a template needs → optional wishes → language →
 * `POST /api/drafts` → opens the editor. Objections are only offered for decisions whose
 * instructions (or the law, for a court order or a landlord's notice) give an Einspruch or Widerspruch.
 */
export function LetterComposer({ open, onClose, prefill }: LetterComposerProps) {
  // A new session (fresh form) whenever the composer is opened with a different pre-fill; closing
  // keeps the session so the dialog can animate out with its content.
  const sig = prefill ? JSON.stringify(prefill) : null;
  const [session, setSession] = useState({ sig, prefill, n: 0 });
  if (sig !== null && sig !== session.sig) setSession({ sig, prefill, n: session.n + 1 });
  return <ComposerDialog key={session.n} open={open && sig !== null} onClose={onClose} prefill={session.prefill} />;
}

/** `docs` with the letters of `kinds` first, each group in its own order. */
function fittingFirst(docs: Document[], kinds: readonly Document["kind"][] | undefined): Document[] {
  if (!kinds?.length) return docs;
  const fits = (d: Document) => kinds.includes(d.kind);
  return [...docs.filter(fits), ...docs.filter((d) => !fits(d))];
}

/** Recipient step of a template letter: a letter it answers, a person or organisation, or a typed address. */
function TemplateRecipient({
  config,
  docs,
  docId,
  setDocId,
  partyId,
  setPartyId,
  parties,
  loading,
  typed,
  setTyped,
  notice,
  claimant = false,
}: {
  config: TemplateConfig;
  docs: Document[];
  docId: string | null;
  setDocId: (id: string | null) => void;
  partyId: string | null;
  setPartyId: (id: string | null) => void;
  parties: Party[];
  loading: boolean;
  typed: string;
  setTyped: (v: string) => void;
  /** Why the chosen letter can't be answered this way — shown right under the letters, where it was chosen. */
  notice?: ReactNode;
  /** The letter goes to a court order's claimant, typed in (the court is the order's sender). */
  claimant?: boolean;
}) {
  const [filter, setFilter] = useState("");
  const byId = useMemo(() => new Map(parties.map((p) => [p.id, p])), [parties]);
  // the letters whose kind fits the template come first (a withdrawal's orders and contracts, a statement's
  // statements), the rest after them: any letter can still be chosen (review round 3 of phase 2); the letter
  // the composer was opened for is always shown (ChoiceList)
  const incoming = useMemo(
    () =>
      fittingFirst(
        docs.filter((d) => d.direction !== "outgoing"),
        config.letterKinds,
      ),
    [docs, config.letterKinds],
  );
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return incoming;
    return incoming.filter((d) => [d.title, d.filename, byId.get(d.party_id ?? "")?.name].some((s) => s?.toLowerCase().includes(q)));
  }, [incoming, filter, byId]);
  const noticeRef = useRef<HTMLDivElement>(null);
  const hasNotice = Boolean(notice);
  useEffect(() => {
    // a refusal is the reason the button stays disabled: bring it into view where the letter was chosen
    if (hasNotice) noticeRef.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [hasNotice, docId]);
  const sorted = useMemo(() => sortForTemplate(parties, config), [parties, config]);
  const letters = config.target === "letter-or-party";
  // a letter whose sender isn't in Ordnung: the person types who it goes to (the server needs a recipient)
  const chosen = letters && docId ? (docs.find((d) => d.id === docId) ?? null) : null;
  const unknownSender = Boolean(chosen && !chosen.party_id);

  // no search box and no list for an install without letters, no picker without people (UI audit round 1)
  const hasLetters = letters && incoming.length > 0;
  return (
    <div className="space-y-3">
      {letters ? (
        <>
          {hasLetters && (incoming.length > LIST_PREVIEW + 1 || filter) ? (
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a letter…" aria-label="Find a letter" className="pl-9" />
            </div>
          ) : null}
          {hasLetters && config.letterHint ? <p className="text-[12.5px] leading-5 text-muted">{config.letterHint}</p> : null}
          {loading ? (
            <ListSkeleton />
          ) : hasLetters ? (
            <ChoiceList
              items={shown}
              selectedId={docId}
              labelledBy="cmp-which"
              noun="letters"
              emptyText={filter ? `No letters match “${filter}”.` : null}
              render={(d) => (
                <OptionRow
                  key={d.id}
                  name="letter-about"
                  value={d.id}
                  selected={docId === d.id}
                  onSelect={() => {
                    setDocId(d.id);
                    setPartyId(null);
                  }}
                >
                  <DocOption d={d} party={byId.get(d.party_id ?? "")} />
                </OptionRow>
              )}
            />
          ) : null}
          {notice ? (
            <div ref={noticeRef} className="scroll-mb-4">
              {notice}
            </div>
          ) : null}
          {claimant ? (
            <Field
              label="The claimant (Antragsteller)"
              hint="The court order names who claims the money — type their name and address as the order shows them. The letter goes to them, not to the court."
              // the court is no claimant: the server refuses an offer to it (review round 3 of phase 2)
              error={mayBeCourt(typed) ? "That's a court — type the claimant the order names as the Antragsteller." : undefined}
            >
              <Textarea
                data-claimant-recipient
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                rows={4}
                className="min-h-24"
                placeholder={"Claimant's name\nStreet and number\nPostcode and town"}
              />
            </Field>
          ) : null}
          {/* only when the letter can be answered this way, and never next to the claimant's box (both would
              write the same text: review round 3 of phase 2) */}
          {unknownSender && !claimant && !notice ? (
            <Field label="Who is it for?" hint="This letter's sender isn't in Ordnung — type their name and address as the letter shows them.">
              <Textarea
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                rows={4}
                className="min-h-24"
                placeholder={"Company name\nStreet and number\nPostcode and town"}
              />
            </Field>
          ) : null}
        </>
      ) : null}
      {sorted.length ? (
        <Field label={hasLetters ? "Or write to someone without a letter" : "Recipient"} optional={hasLetters}>
          <Select
            value={docId && letters ? "" : (partyId ?? "")}
            onChange={(e) => {
              setPartyId(e.target.value || null);
              if (e.target.value) {
                setDocId(null);
                setTyped("");
              }
            }}
          >
            <option value="">Choose a person or organisation…</option>
            {sorted.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {partyKindLabel(p.kind)}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}
      {config.target === "party-or-typed" ? (
        <div className="rounded-xl border border-dashed border-line-strong/80 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[13px] font-medium text-ink">Not in Ordnung yet?</p>
            <Button
              size="sm"
              icon={Building2}
              onClick={() => {
                setTyped(SCHUFA_ADDRESS);
                setPartyId(null);
                setDocId(null);
              }}
            >
              Use SCHUFA's address
            </Button>
          </div>
          <p className="mt-1.5 text-[12.5px] leading-5 text-muted">SCHUFA, Germany's main credit agency, must send you a free copy of the data and scores it holds about you.</p>
          <Field label="Or type their name and address" hint="Every company or office must send you a free first copy of your data (Art. 15(3) GDPR)." className="mt-2">
            <Textarea
              value={typed}
              onChange={(e) => {
                setTyped(e.target.value);
                if (e.target.value.trim()) {
                  setPartyId(null);
                  setDocId(null);
                }
              }}
              rows={4}
              className="min-h-24"
              placeholder={"Company name\nStreet and number\nPostcode and town"}
            />
          </Field>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The From field of a letter answering one addressed to someone else (`DocumentDetail.addressed_to`). It starts with
 * the person's own name: the addressee's is one press away, and "Use my name" goes back — offered, never set (a
 * child's letter answered in the child's name would be the worse mistake). A household ("Familie Rivera") has no
 * one-press name: the person is among the people named and signs as themselves. A press keeps the keyboard in place
 * (focus moves to the button that took the pressed one's place) and a status line says whose name it now is. Code
 * never adds the name to the draft request (the related letter's title and summary, sent as read, may still name the
 * addressee).
 */
function SignerField({
  addressee,
  ownName,
  value,
  onChange,
  othersName,
}: {
  addressee: string;
  ownName: string;
  value: string;
  onChange: (name: string) => void;
  /** The field holds a name that isn't the person's own. */
  othersName: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const theirsRef = useRef<HTMLButtonElement>(null);
  const mineRef = useRef<HTMLButtonElement>(null);
  // after a press, the button that took the pressed one's place (else the field) gets the focus
  const focusNext = useRef<"theirs" | "mine" | null>(null);
  const [said, setSaid] = useState("");
  useEffect(() => {
    const next = focusNext.current;
    if (!next) return;
    focusNext.current = null;
    ((next === "theirs" ? theirsRef.current : mineRef.current) ?? inputRef.current)?.focus();
  }, [value]);
  const press = (name: string, next: "theirs" | "mine", line: string) => {
    focusNext.current = next;
    setSaid(line);
    onChange(name);
  };
  const household = namesHousehold(addressee);
  return (
    <div className="mt-4" data-signer>
      <Field
        label="From"
        hint={
          <span className="[overflow-wrap:anywhere]">
            This letter was addressed to {addressee}.{othersName ? <> It goes out in the name of {value.trim()}, who signs it.</> : null}
          </span>
        }
      >
        <Input ref={inputRef} value={value} onChange={(e) => onChange(e.target.value)} maxLength={120} autoComplete="off" spellCheck={false} />
      </Field>
      <div className="mt-2 flex flex-wrap gap-2">
        {!household && !sameName(value, addressee) ? (
          // an element, not a string: the Button truncates a string label, and a long name wraps at 320 px instead
          <Button
            ref={theirsRef}
            size="sm"
            className="h-auto min-h-8 max-w-full whitespace-normal py-1 text-left"
            onClick={() => press(addressee, "mine", `The letter now goes out in the name of ${addressee}.`)}
          >
            <span className="min-w-0 whitespace-normal [overflow-wrap:anywhere]">Reply in {addressee}'s name</span>
          </Button>
        ) : null}
        {ownName && !sameName(value, ownName) ? (
          <Button ref={mineRef} size="sm" variant="ghost" onClick={() => press(ownName, "theirs", "The letter now goes out in your name.")}>
            Use my name
          </Button>
        ) : null}
      </div>
      <p role="status" className="sr-only">
        {said}
      </p>
    </div>
  );
}

function ComposerDialog({ open, prefill, onClose }: { open: boolean; prefill: ComposerPrefill | null; onClose: () => void }) {
  const navigate = useNavigate();
  const today = useTodayISO();
  const docsQ = useDocuments();
  const contractsQ = useContracts();
  const partiesQ = useParties();
  const profileQ = useProfile();
  const suggestionsQ = useSuggestions();
  const create = useCreateDraft();

  const [kind, setKind] = useState<DraftKind | null>(prefill?.kind ?? null);
  const [contractId, setContractId] = useState<string | null>(prefill?.contractId ?? null);
  const [docId, setDocId] = useState<string | null>(prefill?.docId ?? null);
  const [partyId, setPartyId] = useState<string | null>(prefill?.partyId ?? null);
  const [typedRecipient, setTypedRecipient] = useState("");
  // instalments refused for a court order: the letter goes to the order's claimant, typed in
  const [toClaimant, setToClaimant] = useState(false);
  const [values, setValues] = useState<DetailValues>({});
  const [instructions, setInstructions] = useState("");
  // the application to suspend enforcement is a legal sentence: an explicit choice, never read from the wishes
  const [suspend, setSuspend] = useState(false);
  const [language, setLanguage] = useState<"de" | "en">("de");
  const [filter, setFilter] = useState("");
  // opened for a chosen letter ("Withdraw", "Ask for more time" on a letter): start at step 2, not the list of kinds
  const whichRef = useRef<HTMLElement>(null);
  const startAtWhich = Boolean(prefill?.kind);
  useEffect(() => {
    if (!open || !startAtWhich) return;
    const t = window.setTimeout(() => whichRef.current?.scrollIntoView?.({ block: "start" }), 60);
    return () => window.clearTimeout(t);
  }, [open, startAtWhich]);
  // a kind picked by hand: when step 2 starts below the fold (a phone, under the template tiles), bring it
  // up — before, nothing visible changed at 320 px (UI audit round 1)
  const picked = useRef(false);
  useEffect(() => {
    if (!picked.current || !kind) return;
    picked.current = false;
    const step = whichRef.current;
    const scroller = step ? scrollParent(step) : null;
    if (!step || !scroller) return;
    if (step.getBoundingClientRect().top > scroller.getBoundingClientRect().bottom - 96) {
      step.scrollIntoView?.({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
    }
  }, [kind]);
  const doc = docId ? (docsQ.data ?? []).find((d) => d.id === docId) ?? null : null;
  // the answered letter's own deadline and amount: the server uses them when the fields are left empty;
  // a landlord's notice's card says whether it has a hardship objection at all; an objection's deadline
  const needsCard = kind === "objection" && doc?.kind === "landlord_notice";
  const needsLetter = kind === "extension_request" || kind === "payment_plan" || kind === "objection";
  const letterQ = useDocument(needsLetter && docId ? docId : undefined);
  const defaults = useMemo(() => letterDefaults(letterQ.data?.items ?? []), [letterQ.data]);

  const parties = useMemo(() => new Map((partiesQ.data ?? []).map((p) => [p.id, p])), [partiesQ.data]);
  const docs = useMemo(() => usableDocuments(docsQ.data ?? []), [docsQ.data]);
  // letters flagged as a possible scam are never answered with a template (a withdrawal, instalments…)
  const scamDocIds = useMemo(
    () =>
      new Set(
        (suggestionsQ.data ?? [])
          .filter((s) => s.kind === "scam" && s.status !== "dismissed" && s.status !== "expired")
          .flatMap((s) => s.refs.filter((r) => r.type === "document").map((r) => r.id)),
      ),
    [suggestionsQ.data],
  );
  const templateDocs = useMemo(() => docs.filter((d) => !scamDocIds.has(d.id)), [docs, scamDocIds]);
  const objectable = useMemo(() => objectionDocuments(docsQ.data ?? []), [docsQ.data]);
  const contracts = useMemo(() => cancellableContracts(contractsQ.data ?? []), [contractsQ.data]);
  const template = isTemplateKind(kind) ? TEMPLATE_BY_KIND[kind] : null;
  // "Draft cancellation" from a letter: find the contract that letter belongs to
  const inferredContractId = useMemo(() => {
    const from = prefill?.docId;
    if (kind !== "cancellation" || contractId || !from) return null;
    return (contractsQ.data ?? []).find((c) => c.source_doc_id === from || c.evidence.some((e) => e.doc_id === from))?.id ?? null;
  }, [kind, contractId, prefill?.docId, contractsQ.data]);
  const effContractId = contractId ?? inferredContractId;
  const contract = effContractId ? (contractsQ.data ?? []).find((c) => c.id === effContractId) ?? null : null;
  const check = objectionCheck(doc, needsCard ? letterQ.data?.advice : null);
  const objectionBlocked = kind === "objection" && Boolean(doc) && !check.ok;
  const noObjectable = !docsQ.isPending && objectable.length === 0 && !(doc && check.ok);

  // an offer to a court order's claimant stays linked to the order, but goes to the claimant typed in
  const claimantMode = toClaimant && Boolean(doc) && template?.kind === "payment_plan";
  // an objection to a court order whose sender (as filed) is no court goes to the court, typed in — never to
  // the claimant, where it wouldn't stop the order (§ 694, § 700 ZPO; review round 3 of phase 2)
  const letterParty = doc?.party_id ? parties.get(doc.party_id) ?? null : null;
  const courtTyped = kind === "objection" && check.ok && needsTypedCourt(doc, letterParty);
  const courtOk = !courtTyped || mayBeCourt(typedRecipient);
  const recipientId =
    kind === "cancellation" ? contract?.party_id ?? null : claimantMode || courtTyped ? null : doc?.party_id ?? partyId;
  const recipient = recipientId ? parties.get(recipientId) ?? null : null;
  const partyList = useMemo(() => partiesQ.data ?? [], [partiesQ.data]);
  const incomingDocs = useMemo(() => docs.filter((d) => d.direction !== "outgoing"), [docs]);
  const replyDocs = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return incomingDocs;
    return incomingDocs.filter((d) => [d.title, d.filename, parties.get(d.party_id ?? "")?.name].some((s) => s?.toLowerCase().includes(q)));
  }, [incomingDocs, filter, parties]);

  // e.g. the broadcasting fee (from an old link): nothing to cancel — say why instead
  const contractBlocked = kind === "cancellation" && contract !== null && !offersEndingLetter(contract);
  const resignation = kind === "cancellation" && contract?.category === "employment";

  // an empty install: kinds with nothing to act on say so (step 1), and step 2 offers "Add letters" instead of an
  // empty list, an empty search and a picker without people (UI audit round 1)
  const loaded = !docsQ.isPending && !partiesQ.isPending;
  const noContracts = !contractsQ.isPending && contracts.length === 0;
  const noReply = loaded && incomingDocs.length === 0 && partyList.length === 0 && !doc;
  const templateIncoming = template && template.target === "letter-or-party" ? templateDocs.filter((d) => d.direction !== "outgoing").length : 0;
  const noTemplateTarget = Boolean(template) && template?.target !== "party-or-typed" && loaded && partyList.length === 0 && templateIncoming === 0 && !doc;
  const nothing: NothingKind | null =
    kind === "cancellation" && noContracts && !contract
      ? "cancellation"
      : kind === "objection" && noObjectable && !doc
        ? "objection"
        : kind === "general_reply" && noReply
          ? "general_reply"
          : noTemplateTarget
            ? "template"
            : null;
  const unavailable: Partial<Record<DraftKind, string>> = {
    ...(noContracts ? { cancellation: NOTHING.cancellation.card } : {}),
    ...(noObjectable ? { objection: NOTHING.objection.card } : {}),
    ...(noReply ? { general_reply: NOTHING.general_reply.card } : {}),
  };
  const adder = useOptionalAddLetters();
  const addLetters = adder
    ? () => {
        onClose();
        adder.openPicker();
      }
    : null;
  // an objection's deadline in plain words (the letter quotes it in German)
  const objectionDue = kind === "objection" && check.ok ? objectionDeadline(letterQ.data?.items ?? []) : null;
  const periodText = check.ok ? check.remedy?.period_text?.trim().replace(/[.„“"]+$/, "").replace(/^[„“"]+/, "") || null : null;
  // the To card below names the recipient: repeat the letter's addressee only when it names someone else
  const addressee = check.ok ? check.remedy?.addressee?.trim() || null : null;
  const addresseeElsewhere = addressee && !(recipient && addressee.toLowerCase().startsWith(recipient.name.toLowerCase())) ? addressee : null;

  // the letter answered (a cancellation's: its contract's letter, as the request's doc_id) was addressed to someone
  // else: the From field offers their name, starting with the person's own — never filled in for them (ADR 0019)
  const answeredId = kind === "cancellation" ? (contract?.source_doc_id ?? null) : docId;
  const answeredQ = useDocument(kind && answeredId ? answeredId : undefined);
  const letterAddressee = answeredQ.data?.document.id === answeredId ? (answeredQ.data?.addressed_to ?? null) : null;
  const ownName = profileQ.data?.name?.trim() ?? "";
  // what the person typed or chose, per answered letter: switching letters never carries one person's name to another
  const [signers, setSigners] = useState<Record<string, string>>({});
  const signer = answeredId && answeredId in signers ? signers[answeredId]! : ownName;
  const setSigner = (name: string) => {
    if (answeredId) setSigners((s) => ({ ...s, [answeredId]: name }));
  };
  const othersName = Boolean(signer.trim()) && !sameName(signer, ownName);

  // what the template form starts with: the contract's name (never a letter's title, which is Ordnung's
  // English summary, not what was ordered), the profile's address
  const templateValues: DetailValues = !template
    ? values
    : {
        ...(template.kind === "withdrawal" ? { subject_matter: contract?.name ?? "" } : {}),
        ...(template.kind === "address_change" ? { new_address: profileQ.data?.address ?? "" } : {}),
        ...values,
      };
  const missing = template ? missingFields(template, templateValues) : [];
  const invalid = template ? template.fields.some((f) => fieldError(f, templateValues, today, defaults)) : false;
  const typedTo = Boolean(typedRecipient.trim());
  const templateTarget = claimantMode
    ? typedTo && !mayBeCourt(typedRecipient)
    : Boolean((doc && (doc.party_id || typedTo)) || partyId || (template?.target === "party-or-typed" && typedTo));
  const refusal = template && doc ? templateRefusal(template.kind, doc.kind, claimantMode) : null;
  // the claimant's box takes focus once the person chose to write to them (review round 2: focus fell to <body>)
  useEffect(() => {
    if (!claimantMode) return;
    // after the dialog's focus guard has handled the removed button (it would move focus to the dialog)
    const t = window.setTimeout(() => document.querySelector<HTMLElement>("[data-claimant-recipient]")?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [claimantMode]);
  // the court's box takes focus when the objection needs it typed and it is empty — the footer already asks for
  // it, and the field sat below the fold (review round 4 of phase 2); once per box, never while typing
  const courtFocused = useRef(false);
  useEffect(() => {
    if (!courtTyped || courtFocused.current || typedRecipient.trim()) return;
    courtFocused.current = true;
    const t = window.setTimeout(() => {
      const box = document.querySelector<HTMLElement>("[data-court-recipient]");
      box?.scrollIntoView?.({ block: "center" });
      box?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(t);
  }, [courtTyped, typedRecipient]);
  // a request for more time can't move the deadlines the law sets: say so before it is written
  const lawDeadlines = kind === "extension_request" && !refusal ? statutoryDeadlines(letterQ.data?.items ?? []) : [];

  const ready =
    kind === "cancellation"
      ? Boolean(contract) && !contractBlocked
      : kind === "objection"
        ? Boolean(doc) && check.ok && !(needsCard && letterQ.isPending) && courtOk
        : kind === "general_reply"
          ? Boolean(doc || partyId)
          : template
            ? templateTarget && !refusal && !missing.length && !invalid
            : false;

  const pickKind = (k: DraftKind) => {
    picked.current = true;
    setKind(k);
    setToClaimant(false);
    if (k === "cancellation") setDocId(null);
    if (k !== "cancellation") setContractId(null);
    if (k === "objection" && doc && !objectionCheck(doc).ok) setDocId(null);
    if (isTemplateKind(k) && TEMPLATE_BY_KIND[k].target === "party" && doc) {
      setPartyId(doc.party_id);
      setDocId(null);
    }
    if (isTemplateKind(k) && doc && scamDocIds.has(doc.id)) setDocId(null);
    setValues({});
  };

  const submit = () => {
    if (!kind || !ready) return;
    const templated = template !== null;
    create.mutate(
      {
        kind,
        contract_id: kind === "cancellation" ? effContractId : templated ? (contract?.id ?? null) : null,
        doc_id: kind === "cancellation" ? (contract?.source_doc_id ?? null) : docId,
        party_id: recipientId,
        case_id: (kind === "cancellation" ? contract?.case_id : doc?.case_id) ?? null,
        instructions: instructions.trim() || undefined,
        language,
        suspend_enforcement: kind === "objection" && canSuspend(doc) ? suspend : undefined,
        // only a name the person chose: their own (or an emptied field) leaves the request as without the field
        sender_name: letterAddressee && othersName ? signer.trim() : undefined,
        details: template
          ? detailsPayload(template, templateValues, recipientId ? null : typedRecipient)
          : courtTyped
            ? { recipient: typedRecipient.trim() }
            : undefined,
      },
      {
        onSuccess: (draft) => {
          // not "next to it": on a phone the translation is behind a switch (UI audit round 1)
          toast.success("Your letter is ready to check", { description: "Check the English translation before you send anything." });
          onClose();
          navigate(`/letters/${draft.id}`);
        },
      },
    );
  };

  const whichLabel =
    kind === "cancellation" ? "Which contract?" : kind === "objection" ? "Which decision?" : template ? template.whichLabel : "Which letter are you answering?";
  const disabledReason = !kind
    ? "Choose what you want to do."
    : nothing
      ? NOTHING[nothing].reason
      : kind === "cancellation"
      ? contract
        ? contractBlocked
          ? "This contract can't be ended with a letter — see why above."
          : null
        : "Choose the contract to cancel."
      : kind === "objection"
        ? doc
          ? !check.ok
            ? objectable.length
              ? "You can't object to this letter — reply to it instead, or choose a decision below."
              : "You can't object to this letter — reply to it instead."
            : courtOk
              ? null
              : "Type the court's name and address — the objection goes to the court that issued the order."
          : "Choose the decision you object to."
        : kind === "general_reply"
          ? doc || partyId
            ? null
            : "Choose the letter you're answering, or who to write to."
          : refusal
            ? "This letter can't answer the one you chose — see why under the letters."
            : template && !templateTarget
              ? doc && !doc.party_id
                ? "Type who the letter is for — its sender isn't in Ordnung."
                : toClaimant
                  ? "Type the claimant's name and address."
                  : "Choose who the letter is for."
              : missing.length
              ? `Still needed: ${joinAnd(missing)}.`
              : invalid
                ? "Fix the date or amount marked above."
                : null;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="New letter"
      // on a phone the pinned header keeps only the title and the sentence scrolls with the form (below), so the
      // choices keep the sheet (UI audit round 2: 302 of 589 px were left for them at 320×640)
      description={<span className="max-sm:sr-only">{ABOUT}</span>}
      footer={
        <>
          {/* why the button is disabled — on phones above the buttons (the footer stacks in reverse), at most two
              lines there: the whole reason on hover and for screen readers */}
          <p
            id="cmp-why"
            className={cn(
              disabledReason && !ready
                ? "order-last text-[12.5px] leading-snug text-muted max-sm:line-clamp-2 sm:order-first sm:mr-auto sm:max-w-[22rem] sm:self-center [@media(max-height:560px)]:line-clamp-1"
                : "sr-only",
            )}
            title={disabledReason && !ready ? disabledReason : undefined}
            aria-live="polite"
          >
            {disabledReason && !ready ? disabledReason : ""}
          </p>
          {/* phones: side by side and 44 px tall — Cancel as wide as its word, the letter's button the rest */}
          <div data-composer-actions className="grid grid-cols-[auto_minmax(0,1fr)] gap-2 sm:contents">
            <Button onClick={onClose} className="max-sm:h-11">
              Cancel
            </Button>
            <Button
              variant="primary"
              icon={Sparkles}
              onClick={submit}
              disabled={!ready}
              loading={create.isPending}
              className="max-sm:h-11"
              // the reason travels with the disabled button, for a screen reader that lands on it
              aria-describedby={disabledReason && !ready ? "cmp-why" : undefined}
            >
              {create.isPending ? "Writing…" : "Write the letter"}
            </Button>
          </div>
        </>
      }
    >
      <div className="space-y-7 pb-2">
        {/* the dialog's description on a phone, where its header shows only the title; screen readers hear it
            once, as the dialog's description */}
        <p aria-hidden data-composer-about className="-mt-1.5 mb-5 text-base leading-relaxed text-muted sm:hidden">
          {ABOUT}
        </p>
        {/* 1 · what */}
        <section aria-labelledby="cmp-kind">
          <StepLabel n={1} id="cmp-kind">
            What do you want to do?
          </StepLabel>
          <KindChooser kind={kind} onPick={pickKind} unavailable={unavailable} />
        </section>

        {/* 2 · which */}
        {kind ? (
          <section ref={whichRef} aria-labelledby="cmp-which" className="scroll-mt-2">
            <StepLabel n={2} id="cmp-which">
              {whichLabel}
            </StepLabel>

            {nothing ? (
              <NothingYet title={NOTHING[nothing].title} onAdd={addLetters}>
                {NOTHING[nothing].body}
              </NothingYet>
            ) : null}

            {contractBlocked && contract ? (
              <Callout tone="warn" className="mb-3" title={`${contract.name} can't be cancelled`}>
                {contract.cancel_hint ?? "This isn't a contract you can end with a cancellation letter."}
              </Callout>
            ) : null}
            {kind === "cancellation" && !nothing ? (
              contractsQ.isPending ? (
                <ListSkeleton />
              ) : contracts.length ? (
                <ChoiceList
                  items={contracts}
                  selectedId={effContractId}
                  labelledBy="cmp-which"
                  noun="contracts"
                  render={(c) => (
                    <OptionRow key={c.id} name="letter-contract" value={c.id} selected={effContractId === c.id} onSelect={() => setContractId(c.id)}>
                      <ContractOption c={c} party={parties.get(c.party_id ?? "")} />
                    </OptionRow>
                  )}
                />
              ) : null
            ) : null}
            {/* about the chosen contract: under the choice, where the eye is (UI audit round 1) */}
            {resignation && contract?.cancel_hint && !contractBlocked ? (
              <Callout tone="info" className="mt-3" title="This drafts your resignation">
                {contract.cancel_hint}
              </Callout>
            ) : null}

            {kind === "objection" && !nothing ? (
              <>
                {objectionBlocked && !check.ok && doc ? (
                  <>
                    {/* the letter it is about, so "this letter" names one — never the decision listed under it */}
                    <ChosenLetter d={doc} party={parties.get(doc.party_id ?? "")} />
                    <Callout
                      tone="warn"
                      className="mb-4"
                      title={check.title}
                      action={
                        <Button size="sm" icon={Mail} onClick={() => setKind("general_reply")}>
                          Reply to this letter instead
                        </Button>
                      }
                    >
                      <p>{check.body}</p>
                      <p className="mt-1.5">
                        <AdviceLinks advice={check.advice} />
                      </p>
                    </Callout>
                    {objectable.length ? (
                      <p id="cmp-objectable" className="eyebrow mb-2 px-1">
                        Or choose a decision you can object to
                      </p>
                    ) : null}
                  </>
                ) : null}
                {docsQ.isPending ? (
                  <ListSkeleton />
                ) : objectable.length ? (
                  <ChoiceList
                    items={objectable}
                    selectedId={docId}
                    labelledBy={objectionBlocked ? "cmp-objectable" : "cmp-which"}
                    noun="decisions"
                    render={(d) => {
                      const c = objectionCheck(d);
                      return (
                        <OptionRow
                          key={d.id}
                          name="letter-doc"
                          value={d.id}
                          selected={docId === d.id}
                          onSelect={() => {
                            setDocId(d.id);
                            setSuspend(false);
                            setTypedRecipient("");
                          }}
                        >
                          <DocOption d={d} party={parties.get(d.party_id ?? "")} pill={c.ok ? <PossiblePill term={c.term} /> : null} />
                        </OptionRow>
                      );
                    }}
                  />
                ) : null}
                {doc && check.ok ? (
                  <div className="mt-2.5 space-y-1 text-[13px] leading-relaxed text-muted" data-objection-note>
                    <p>
                      {check.statutory ? (
                        <StatutoryNote kind={doc.kind} term={check.term} />
                      ) : (
                        <>
                          The letter allows {check.term === "Einspruch" ? "an" : "a"} <Glossary term={check.term} />
                          {addresseeElsewhere ? <> to {addresseeElsewhere}</> : null}. It's free, a short letter is enough and reasons can follow later.
                        </>
                      )}
                    </p>
                    {objectionDue?.due_date ? (
                      // the deadline in plain words first; the letter's German wording after it, as a quote of its own
                      <p>
                        Deadline: <Countdown date={objectionDue.due_date} showDate />
                        {periodText ? (
                          <>
                            {" "}
                            — in the letter's words (German):{" "}
                            <q lang="de" className="italic">
                              {periodText}
                            </q>
                          </>
                        ) : null}
                      </p>
                    ) : periodText ? (
                      <p>
                        The letter says (in German):{" "}
                        <q lang="de" className="italic">
                          {periodText}
                        </q>
                      </p>
                    ) : null}
                  </div>
                ) : null}
                {courtTyped ? (
                  <Field
                    className="mt-3"
                    label="The court that sent the order"
                    hint={`As the order and its yellow envelope show it (${
                      doc?.kind === "enforcement_order" ? "for a Vollstreckungsbescheid, the Mahngericht that issued it" : "for a Mahnbescheid usually a central Mahngericht"
                    }; a court's postcode alone is fine, no street needed). The objection goes to the court${letterParty ? `, not to ${letterParty.name}` : ""}.`}
                    error={typedRecipient.trim() && !courtOk ? "This doesn't look like a court's name — type it as the order shows it (e.g. “Amtsgericht Hünfeld”)." : undefined}
                  >
                    <Textarea
                      data-court-recipient
                      value={typedRecipient}
                      onChange={(e) => setTypedRecipient(e.target.value)}
                      rows={4}
                      className="min-h-24"
                      placeholder={"Amtsgericht …\nDepartment or street, as the order shows it\nPostcode and town"}
                    />
                  </Field>
                ) : null}
                {doc && check.ok && canSuspend(doc) ? (
                  <Checkbox
                    label={doc.kind === "enforcement_order" ? "Also ask the court to suspend enforcement for now" : "Also ask to suspend enforcement"}
                    description={
                      doc.kind === "enforcement_order"
                        ? "Adds the application for “einstweilige Einstellung” (§§ 719, 707 ZPO). The court decides; get advice about it."
                        : "Adds the application for “Aussetzung der Vollziehung”. For taxes and other public charges, an objection alone doesn't stop the payment being due."
                    }
                    checked={suspend}
                    onChange={(e) => setSuspend(e.target.checked)}
                    className="mt-3"
                  />
                ) : null}
              </>
            ) : null}

            {kind === "general_reply" && !nothing ? (
              <>
                {/* a search only where there is a list to search (UI audit round 1: an empty install had one) */}
                {incomingDocs.length > LIST_PREVIEW + 1 || filter ? (
                  <div className="relative mb-2.5">
                    <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
                    <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a letter…" aria-label="Find a letter" className="pl-9" />
                  </div>
                ) : null}
                {docsQ.isPending ? (
                  <ListSkeleton />
                ) : incomingDocs.length ? (
                  <ChoiceList
                    items={replyDocs}
                    selectedId={docId}
                    labelledBy="cmp-which"
                    noun="letters"
                    emptyText={filter ? `No letters match “${filter}”.` : null}
                    render={(d) => (
                      <OptionRow
                        key={d.id}
                        name="letter-reply"
                        value={d.id}
                        selected={docId === d.id}
                        onSelect={() => {
                          setDocId(d.id);
                          setPartyId(null);
                        }}
                      >
                        <DocOption d={d} party={parties.get(d.party_id ?? "")} />
                      </OptionRow>
                    )}
                  />
                ) : null}
                {partyList.length ? (
                  <div className={cn(incomingDocs.length > 0 && "mt-3")}>
                    <Field label={incomingDocs.length ? "Or write to someone without a letter" : "Who do you want to write to?"} optional={incomingDocs.length > 0}>
                      <Select
                        value={doc ? "" : (partyId ?? "")}
                        onChange={(e) => {
                          setPartyId(e.target.value || null);
                          if (e.target.value) setDocId(null);
                        }}
                      >
                        <option value="">Choose a person or organisation…</option>
                        {partyList.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name} — {partyKindLabel(p.kind)}
                          </option>
                        ))}
                      </Select>
                    </Field>
                  </div>
                ) : null}
              </>
            ) : null}

            {template && !nothing ? (
              <TemplateRecipient
                config={template}
                docs={templateDocs}
                docId={docId}
                setDocId={(id) => {
                  if (id !== docId) setToClaimant(false);
                  setDocId(id);
                }}
                partyId={partyId}
                setPartyId={(id) => {
                  setPartyId(id);
                  if (id) setToClaimant(false);
                }}
                parties={partiesQ.data ?? []}
                loading={docsQ.isPending}
                typed={typedRecipient}
                setTyped={setTypedRecipient}
                claimant={claimantMode}
                notice={
                  refusal ? (
                    <Callout
                      tone="warn"
                      title={refusal.title}
                      action={
                        refusal.toClaimant ? (
                          // the letter stays linked to the order (its reference and date): only who it goes to changes
                          <Button
                            size="sm"
                            icon={Mail}
                            className="h-auto min-h-8 max-w-full whitespace-normal py-1 text-left"
                            onClick={() => {
                              setToClaimant(true);
                              setPartyId(null);
                              setTypedRecipient("");
                            }}
                          >
                            {/* an element, not a string: the Button truncates a string label, and this is the only way on
                                from the refusal — it wraps at 320 px instead (review round 4 of phase 2) */}
                            <span className="min-w-0 whitespace-normal break-words">Write to the claimant instead</span>
                          </Button>
                        ) : refusal.seeCard && doc ? (
                          // the letter's advice card, scrolled to and its title focused (review round 3 of phase 2)
                          <Link to={`/documents/${doc.id}`} state={{ focus: "advice" }} className={buttonVariants({ size: "sm" })}>
                            Open the letter's card
                          </Link>
                        ) : undefined
                      }
                    >
                      {keepCitations(refusal.body)}
                    </Callout>
                  ) : claimantMode ? (
                    <Callout tone="info" title="The letter goes to the claimant">
                      {keepCitations(CLAIMANT_NOTE)}
                    </Callout>
                  ) : null
                }
              />
            ) : null}
            {refusal && !template ? (
              <Callout tone="warn" className="mt-3" title={refusal.title}>
                {keepCitations(refusal.body)}
              </Callout>
            ) : lawDeadlines.length ? (
              <Callout tone="info" className="mt-3" title="Deadlines set by law can't be extended by asking">
                {lawDeadlines.length === 1 ? (
                  <>
                    “{lawDeadlines[0]!.title}” (<DateText date={lawDeadlines[0]!.due_date!} style="medium" />) is set by law — meet it anyway.
                  </>
                ) : (
                  <>This letter's objection and legal deadlines are set by law — meet them anyway.</>
                )}{" "}
                Ask for more time only for something the sender set, such as sending documents.
              </Callout>
            ) : null}

            {recipient && !objectionBlocked && !refusal ? (
              // the whole name and address, wrapped: on a phone an ellipsis would hide where the letter goes
              <div className="mt-3 flex items-center gap-2.5 rounded-xl bg-surface-2/70 px-3 py-2.5 text-[13px]">
                <span className="text-muted">To</span>
                <Avatar name={recipient.name} kind={recipient.kind} size="sm" />
                <span className="min-w-0 flex-1 leading-snug [overflow-wrap:anywhere]">
                  <span className="font-medium text-ink">{recipient.name}</span>
                  {recipient.address ? <span className="block text-[12.5px] text-muted">{recipient.address}</span> : null}
                </span>
              </div>
            ) : null}

            {letterAddressee && !objectionBlocked && !refusal && !nothing ? (
              <SignerField addressee={letterAddressee} ownName={ownName} value={signer} onChange={setSigner} othersName={othersName} />
            ) : null}
          </section>
        ) : null}

        {/* 3 · the facts a template letter needs — none of the next steps while step 2 has nothing to choose */}
        {template && !refusal && !nothing && template.fields.length + (template.kind === "deposit_return" ? 1 : 0) > 0 ? (
          <section aria-labelledby="cmp-details">
            <StepLabel n={3} id="cmp-details">
              The details
            </StepLabel>
            <TemplateFields config={template} values={templateValues} onChange={setValues} today={today} profile={profileQ.data} defaults={defaults} />
          </section>
        ) : null}

        {/* wishes + language */}
        {kind && !objectionBlocked && !refusal && !nothing ? (
          <section aria-labelledby="cmp-extra" className="space-y-4">
            <StepLabel n={template && template.fields.length + (template.kind === "deposit_return" ? 1 : 0) > 0 ? 4 : 3} id="cmp-extra">
              Anything to add?
            </StepLabel>
            <Field label="Your wishes, in any language" optional hint="Claude turns this into polite wording. The legal sentences stay as they are.">
              <Textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder={wishesPlaceholder(kind, doc?.kind)} rows={3} className="min-h-20" />
            </Field>
            <div>
              <p id="cmp-lang" className="mb-1.5 flex items-center gap-1.5 text-[13px] font-medium text-ink">
                <Languages className="size-4 text-muted" aria-hidden /> Language of the letter
              </p>
              <SegmentedControl
                label="Language of the letter"
                value={language}
                onChange={setLanguage}
                options={[
                  { value: "de", label: "German (recommended)" },
                  { value: "en", label: "English" },
                ]}
              />
              <p className="mt-1.5 text-[12.5px] leading-5 text-muted">
                {language === "de"
                  ? "German offices and companies expect German. You'll get an English translation to check it against."
                  : "Only if you know the recipient reads English — German offices may not accept it."}
              </p>
            </div>
          </section>
        ) : null}

        <Disclaimer />
      </div>
    </Dialog>
  );
}
