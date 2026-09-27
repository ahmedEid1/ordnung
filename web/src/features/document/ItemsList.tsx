/** "To-dos & dates" from this letter: kind, date + countdown, amount, grounding, "Why this date?". */
import { CalendarPlus, Check, Ellipsis, ListTodo, Pencil, Repeat, RotateCcw, Scale, ShieldAlert, X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import type { Item, Recurrence } from "@/api/types";
import { cn } from "@/lib/utils";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { Input } from "@/components/ui/Field";
import { Button, IconButton } from "@/components/ui/Button";
import { KindBadge } from "@/components/ui/KindBadge";
import { Menu } from "@/components/ui/Menu";
import { Money } from "@/components/ui/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import { EvidenceChip } from "./EvidenceChip";
import { useEvidence } from "./EvidenceContext";
import { GlossaryText } from "./Explained";
import { PanelSection } from "./PanelSection";
import { WhyThisDate } from "./WhyThisDate";
import { icsFileName, icsHref, useItemActions } from "./actions";
import { englishInline, isGermanText } from "./fact-text";
import { formatMoney } from "@/lib/format";
import { plainText } from "@/lib/glue";
import { itemDateRole, undatedNote } from "./item-meta";
import { isOpenItem, sortItems } from "./verdict";

export function recurrenceLabel(r: Recurrence | null | undefined): string | null {
  if (!r) return null;
  const unit = { days: "day", weeks: "week", months: "month", years: "year" }[r.unit];
  return r.interval === 1 ? `every ${unit}` : `every ${r.interval} ${unit}s`;
}

function download(href: string, name: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * The list keeps the order it opened with while you're on the page: a to-do you tick off stays in
 * its place, struck through, instead of jumping to the end — so the next row doesn't slide under the
 * pointer (UI audit round 1: a double click ticked off two). New to-dos go after the others.
 */
function useSteadyOrder(items: Item[], docId: string): Item[] {
  const sorted = sortItems(items);
  const [first, setFirst] = useState(() => ({ docId, ids: sorted.map((i) => i.id) }));
  if (first.docId !== docId) setFirst({ docId, ids: sorted.map((i) => i.id) });
  const place = new Map(first.ids.map((id, i) => [id, i]));
  return [...sorted].sort((a, b) => (place.get(a.id) ?? Infinity) - (place.get(b.id) ?? Infinity));
}

export function ItemsList({ items, docId, pages, scam }: { items: Item[]; docId: string; pages?: number | null; scam?: boolean }) {
  const list = useSteadyOrder(items, docId);
  if (!list.length) return null;
  const open = list.filter(isOpenItem).length;
  return (
    // a scam letter's demands are no to-dos of yours: no count
    <PanelSection id="todos" title="To-dos & dates" icon={ListTodo} count={scam ? undefined : open} countLabel={`${open} open`}>
      <ul className="card divide-y divide-line overflow-hidden">
        {list.map((it) => (scam && isOpenItem(it) ? <ScamRow key={it.id} item={it} docId={docId} pages={pages} /> : <ItemRow key={it.id} item={it} docId={docId} pages={pages} />))}
      </ul>
    </PanelSection>
  );
}

/** The title with German admin terms explained and money and dates the app's way; a German title is marked German. */
function ItemTitle({ title }: { title: string }) {
  return isGermanText(title) ? (
    <span lang="de">
      <GlossaryText text={title} inline />
    </span>
  ) : (
    <GlossaryText text={title} inline markGerman />
  );
}

function evidenceOf(item: Item, docId: string) {
  const evIndex = item.evidence.findIndex((e) => e.doc_id === docId);
  const ev = evIndex >= 0 ? item.evidence[evIndex]! : null;
  return { ev, anchorId: ev ? `item:${item.id}:${evIndex}` : null };
}

/**
 * A demand in a letter with signs of a scam: said for what it is, muted — no countdown, no "transfer
 * by", nothing to tick off (UI audit round 1: it read as an urgent to-do with "Mark done").
 */
function ScamRow({ item, docId, pages }: { item: Item; docId: string; pages?: number | null }) {
  const { hover } = useEvidence();
  const { ev, anchorId } = evidenceOf(item, docId);
  const payment = item.kind === "payment" && item.direction !== "in";
  // the amount once: not again after a title that already says it ("… arrears (€254.35)")
  const amount = item.amount != null && !plainText(englishInline(item.title)).includes(formatMoney(item.amount, { currency: item.currency }));
  return (
    <li className="flex gap-3 px-4 py-3.5 sm:px-5" onMouseEnter={() => anchorId && hover(anchorId)} onMouseLeave={() => anchorId && hover(null)}>
      <span className="grid size-6 shrink-0 place-items-center rounded-full bg-danger-soft text-danger-ink" aria-hidden>
        <ShieldAlert className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[12.5px] font-semibold leading-5 text-danger-ink">
          {payment ? "Payment this letter demands — don't pay" : "What this letter asks — check with the real sender first"}
        </p>
        <p className="mt-0.5 text-[14px] leading-snug text-muted [overflow-wrap:anywhere] hyphens-auto">
          <ItemTitle title={item.title} />
          {amount ? (
            <>
              {" · "}
              <Money amount={item.amount} currency={item.currency} tone="muted" className="text-[14px]" />
            </>
          ) : null}
        </p>
        {ev ? (
          <div className="mt-2">
            <EvidenceChip grounding={item.grounding === "user" ? "user" : ev.grounding} page={ev.page} pages={pages} anchorId={anchorId} what={item.title} compact />
          </div>
        ) : null}
      </div>
    </li>
  );
}

function ItemRow({ item, docId, pages }: { item: Item; docId: string; pages?: number | null }) {
  const { markDone, reopen, dismiss, changeDate, pending } = useItemActions();
  const { hover } = useEvidence();
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState(item.due_date ?? "");
  const open = isOpenItem(item);
  const { ev, anchorId } = evidenceOf(item, docId);
  const rec = recurrenceLabel(item.recurrence);
  const role = itemDateRole(item);
  const menuId = `item-actions-${item.id}`;

  // back to the "More actions" button the editor was opened from (not <body>)
  const closeEditor = () => {
    setEditing(false);
    setDate(item.due_date ?? "");
    requestAnimationFrame(() => document.getElementById(menuId)?.focus());
  };
  const onEditorKey = (e: KeyboardEvent<HTMLFormElement>) => {
    if (e.key !== "Escape") return;
    e.preventDefault();
    e.stopPropagation();
    closeEditor();
  };

  return (
    <li
      className={cn("group relative flex gap-3 px-4 py-3.5 transition-colors hover:bg-surface-2/40 sm:px-5", !open && "bg-surface-2/30")}
      onMouseEnter={() => anchorId && hover(anchorId)}
      onMouseLeave={() => anchorId && hover(null)}
    >
      {/* a 24 px target around the 20 px circle; the name says what a press does (no aria-pressed on top of it) */}
      <button
        type="button"
        onClick={() => (open ? markDone(item) : reopen(item))}
        disabled={pending}
        aria-label={open ? `Mark “${item.title}” as done` : `Reopen “${item.title}”`}
        className="group/check -my-0.5 grid size-6 shrink-0 place-items-center rounded-full"
      >
        <span
          className={cn(
            "grid size-5 place-items-center rounded-full border-[1.5px] transition-colors",
            open ? "border-muted text-transparent group-hover/check:border-accent group-hover/check:text-accent" : "border-ok bg-ok text-white dark:text-canvas",
          )}
        >
          <Check className="size-3" strokeWidth={3.5} aria-hidden />
        </span>
      </button>
      <div className="min-w-0 flex-1">
        {/* a long German word breaks where it must, and on a phone the amount goes under the title rather than
            past its column (review round 2: "…Betriebskostenabrechnung)" and "€670.00" overflowed at 320 px).
            The "More actions" button sits in the corner, 10 px clear of the title and the amount; the lines below
            use the full width (UI audit round 1: the grounding chip was cut to "Read by AI from the ph…" at 320 px) */}
        <div className="flex flex-col items-start gap-0.5 pr-9 sm:flex-row sm:justify-between sm:gap-3">
          <p className={cn("min-w-0 text-[14.5px] font-medium leading-snug [overflow-wrap:anywhere] hyphens-auto", open ? "text-ink" : "text-muted line-through decoration-muted/50")}>
            <ItemTitle title={item.title} />
          </p>
          {item.amount != null ? <Money amount={item.amount} currency={item.currency} tone={item.direction === "in" ? "in" : "default"} className="shrink-0 text-[14px]" /> : null}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-[12.5px]">
          <KindBadge kind={item.kind} direction={item.direction} />
          {!open ? (
            <StatusPill of="item" status={item.status} />
          ) : role === "debit" ? (
            // the bank collects it: nothing to send, never louder than amber (as on Today)
            <Countdown date={item.due_date!} prefix="collected" cap="warn" className="text-[12.5px]" />
          ) : role === "on_site" ? (
            <Countdown date={item.due_date!} prefix="pay on site" time={item.due_time} className="text-[12.5px]" />
          ) : role === "undated" ? (
            undatedNote(item) ? <span className="text-muted">{undatedNote(item)}</span> : null
          ) : (
            <Countdown date={item.due_date!} showDate time={item.due_time} mode={role === "event" ? "event" : "due"} className="text-[12.5px]" />
          )}
          {open && role === "transfer" && item.send_by && item.send_by !== item.due_date ? (
            <span className="text-muted">
              transfer by <DateText date={item.send_by} style="day" className="font-medium text-ink/80" />
            </span>
          ) : open && role === "due" && item.send_by && item.send_by !== item.due_date ? (
            <span className="text-muted">
              post by <DateText date={item.send_by} style="day" className="font-medium text-ink/80" />
            </span>
          ) : null}
          {rec ? (
            <span className="inline-flex items-center gap-1 text-muted">
              <Repeat className="size-3" aria-hidden />
              {rec}
            </span>
          ) : null}
        </div>
        {item.description ? <p className="mt-1.5 text-[13px] leading-5 text-muted">{item.description}</p> : null}
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          {ev ? <EvidenceChip grounding={item.grounding === "user" ? "user" : ev.grounding} page={ev.page} pages={pages} anchorId={anchorId} what={item.title} compact /> : null}
          {!ev && item.origin === "rule" ? (
            <span className="inline-flex items-center gap-1 text-[12px] font-medium text-muted" title="The letter doesn't state this date — the law sets it.">
              <Scale className="size-3.5" aria-hidden />
              Set by law
            </span>
          ) : null}
          {item.computation ? <WhyThisDate receipt={item.computation} spec={item.date_spec} area={item.area} origin={item.origin} item={item} context={item.title} /> : null}
          {item.due_date_source === "manual" ? <span className="text-[12px] text-muted">Date set by you</span> : null}
        </div>
        {editing ? (
          <form
            className="mt-2.5 flex flex-wrap items-center gap-2"
            onKeyDown={onEditorKey}
            onSubmit={(e) => {
              e.preventDefault();
              if (date) changeDate(item, date, closeEditor);
            }}
          >
            <label className="sr-only" htmlFor={`due-${item.id}`}>
              New date for {item.title}
            </label>
            <Input id={`due-${item.id}`} type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-8 w-auto" autoFocus />
            {/* the two buttons stay together ("Cancel" never wraps alone) */}
            <span className="flex items-center gap-2">
              <Button type="submit" size="sm" variant="primary" disabled={!date} loading={pending}>
                Save date
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={closeEditor}>
                Cancel
              </Button>
            </span>
          </form>
        ) : null}
      </div>
      <Menu
        label={`Actions for ${item.title}`}
        heading={item.title}
        items={[
          ...(item.due_date ? [{ label: "Add to calendar", icon: CalendarPlus, onSelect: () => download(icsHref(item), icsFileName(item)) }] : []),
          { label: item.due_date ? "Change date" : "Set a date", icon: Pencil, onSelect: () => setEditing(true) },
          open ? { label: "Mark done", icon: Check, onSelect: () => markDone(item) } : { label: "Reopen", icon: RotateCcw, onSelect: () => reopen(item) },
          "separator" as const,
          { label: "Not a real to-do", icon: X, onSelect: () => dismiss(item), danger: true },
        ]}
      >
        <IconButton id={menuId} icon={Ellipsis} label={`More actions for ${item.title}`} size="sm" className="absolute top-2 right-2.5 opacity-70 group-hover:opacity-100 focus-visible:opacity-100 sm:right-3.5" />
      </Menu>
    </li>
  );
}
