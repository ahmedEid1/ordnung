import { Fragment, useId, useMemo, useState, type ReactNode } from "react";
import { Check, FileX, Mail, Scale, type LucideIcon } from "lucide-react";
import type { Contract, DraftKind, ListedLetter, Party } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { Glossary } from "@/components/ui/Glossary";
import { KindIcon } from "@/components/ui/KindBadge";
import { Skeleton } from "@/components/ui/Skeleton";
import { CONTRACT_CATEGORY_COPY, copyFor, documentKindLabel } from "@/lib/copy";
import { protectRefs } from "@/lib/glue";
import { cn } from "@/lib/utils";
import { isRollingContract } from "@/features/contracts/model";
import {
  letterDate,
} from "./logic";
import {
  TEMPLATES,
} from "./templates";

export interface KindOption {
  kind: DraftKind;
  title: string;
  description: ReactNode;
  icon: LucideIcon;
}

export const KIND_OPTIONS: KindOption[] = [
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

/** A choice's radio circle — every way to choose in the composer shows one (a tick once chosen). */
export function RadioDot({ selected, className }: { selected: boolean; className?: string }) {
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
export const CARD_FOCUS = "has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-accent";
export const CARD_STATE = (selected: boolean) =>
  selected ? "border-accent/60 bg-accent-soft/50 shadow-[0_0_0_1px_var(--color-accent)]" : "border-line bg-surface hover:border-line-strong";

export function OptionRow({
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

export function StepLabel({ n, children, id }: { n: number; children: ReactNode; id?: string }) {
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

export function ListSkeleton() {
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
export function OptionText({ title, meta, below }: { title: string; meta: ReactNode[]; below?: ReactNode }) {
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
export function AnyMonthPill({ className }: { className?: string }) {
  return (
    <span data-any-month className={cn("whitespace-nowrap rounded-full bg-surface-3 px-2 py-[3px] text-xs font-medium leading-4 text-muted", className)}>
      Cancel any month
    </span>
  );
}

export function ContractOption({ c, party }: { c: Contract; party?: Party }) {
  // a contract you can cancel any month has no window that closes: its "send by" only says when it
  // would end, so it never counts down in red
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

export function DocOption({ d, party, pill }: { d: ListedLetter; party?: Party; pill?: ReactNode }) {
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
export function PossiblePill({ term }: { term: string }) {
  return <span className="whitespace-nowrap rounded-full bg-k-expiry-soft px-2 py-0.5 text-[12px] font-medium text-k-expiry-ink">{term} possible</span>;
}

/** The box `el` scrolls in (the dialog's body), if any. */
export function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p; p = p.parentElement) {
    const y = getComputedStyle(p).overflowY;
    if ((y === "auto" || y === "scroll") && p.scrollHeight > p.clientHeight) return p;
  }
  return null;
}

/** Rows a list shows before "Show all": the chosen one is always among them. */
export const LIST_PREVIEW = 5;
/** Rows a list shows at most — searching finds the others. */
export const LIST_CAP = 30;

/**
 * The choices of step 2, in the dialog's own scroll (no second scrolling box inside it, where a chosen
 * contract sat out of view): the one the composer was opened with first — right under the step's heading,
 * where the composer scrolls to — then the first few, the chosen one always among them, and "Show all"
 * for the rest.
 */
export function ChoiceList<T extends { id: string }>({
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
export function ChosenLetter({ d, party }: { d: ListedLetter; party?: Party }) {
  return (
    <div className="mb-2 flex items-center gap-3 rounded-xl border border-warn/40 bg-surface px-3 py-2.5" data-chosen-letter>
      <span className="sr-only">The letter you chose: </span>
      <DocOption d={d} party={party} />
    </div>
  );
}

/**
 * Step 1: the three everyday letters as cards, then the template letters as compact tiles. A card with
 * nothing to act on (no contracts, no decision to object to, no letters) is disabled with the reason
 * instead of its description — unless it is the chosen one (opened by a link), where step 2 says why.
 */
export function KindChooser({ kind, onPick, unavailable }: { kind: DraftKind | null; onPick: (k: DraftKind) => void; unavailable: Partial<Record<DraftKind, string>> }) {
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
