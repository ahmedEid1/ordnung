/** "To-dos & dates" from this letter: kind, date + countdown, amount, grounding, "Why this date?". */
import { CalendarPlus, Check, Ellipsis, ListTodo, Pencil, Repeat, RotateCcw, Scale, X } from "lucide-react";
import { useState } from "react";
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
import { PanelSection } from "./PanelSection";
import { WhyThisDate } from "./WhyThisDate";
import { icsFileName, icsHref, useItemActions } from "./actions";
import { isOpenItem, sortItems } from "./verdict";
import { isDirectDebit } from "@/lib/payments";

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

export function ItemsList({ items, docId }: { items: Item[]; docId: string }) {
  const list = sortItems(items);
  if (!list.length) return null;
  const open = list.filter(isOpenItem).length;
  return (
    <PanelSection id="todos" title="To-dos & dates" icon={ListTodo} count={open}>
      <ul className="card divide-y divide-line overflow-hidden">
        {list.map((it) => (
          <ItemRow key={it.id} item={it} docId={docId} />
        ))}
      </ul>
    </PanelSection>
  );
}

function ItemRow({ item, docId }: { item: Item; docId: string }) {
  const { markDone, reopen, dismiss, changeDate, pending } = useItemActions();
  const { hover } = useEvidence();
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState(item.due_date ?? "");
  const open = isOpenItem(item);
  const evIndex = item.evidence.findIndex((e) => e.doc_id === docId);
  const ev = evIndex >= 0 ? item.evidence[evIndex]! : null;
  const anchorId = ev ? `item:${item.id}:${evIndex}` : null;
  const rec = recurrenceLabel(item.recurrence);

  return (
    <li
      className={cn("group flex gap-3 px-4 py-3.5 transition-colors hover:bg-surface-2/40 sm:px-5", !open && "bg-surface-2/30")}
      onMouseEnter={() => anchorId && hover(anchorId)}
      onMouseLeave={() => anchorId && hover(null)}
    >
      <button
        type="button"
        onClick={() => (open ? markDone(item) : reopen(item))}
        disabled={pending}
        aria-label={open ? `Mark “${item.title}” as done` : `Reopen “${item.title}”`}
        aria-pressed={!open}
        className={cn(
          "mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border-[1.5px] transition-colors",
          open ? "border-line-strong text-transparent hover:border-accent hover:text-accent/60" : "border-ok bg-ok text-white dark:text-canvas",
        )}
      >
        <Check className="size-3" strokeWidth={3.5} aria-hidden />
      </button>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <p className={cn("text-[14.5px] font-medium leading-snug", open ? "text-ink" : "text-muted line-through decoration-muted/50")}>{item.title}</p>
          {item.amount != null ? <Money amount={item.amount} currency={item.currency} tone={item.direction === "in" ? "in" : "default"} className="text-[14px]" /> : null}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-[12.5px]">
          <KindBadge kind={item.kind} direction={item.direction} />
          {!open ? (
            <StatusPill of="item" status={item.status} />
          ) : item.due_date ? (
            <Countdown date={item.due_date} showDate time={item.due_time} mode={item.kind === "appointment" || item.kind === "milestone" || item.kind === "reminder" || item.direction === "in" ? "event" : "due"} className="text-[12.5px]" />
          ) : (
            <span className="text-muted">No date</span>
          )}
          {open && isDirectDebit(item) ? (
            <span className="text-muted">collected automatically</span>
          ) : open && item.send_by && item.send_by !== item.due_date ? (
            <span className="text-muted">
              {item.kind === "payment" ? "transfer by" : "post by"} <DateText date={item.send_by} style="day" className="font-medium text-ink/80" />
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
          {ev ? <EvidenceChip grounding={item.grounding === "user" ? "user" : ev.grounding} page={ev.page} anchorId={anchorId} what={item.title} compact /> : null}
          {!ev && item.origin === "rule" ? (
            <span className="inline-flex items-center gap-1 text-[12px] font-medium text-muted" title="The letter doesn't state this date — the law sets it.">
              <Scale className="size-3.5" aria-hidden />
              Set by law
            </span>
          ) : null}
          {item.computation ? <WhyThisDate receipt={item.computation} spec={item.date_spec} area={item.area} origin={item.origin} context={item.title} /> : null}
          {item.due_date_source === "manual" ? <span className="text-[12px] text-muted">Date set by you</span> : null}
        </div>
        {editing ? (
          <form
            className="mt-2.5 flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (date) changeDate(item, date, () => setEditing(false));
            }}
          >
            <label className="sr-only" htmlFor={`due-${item.id}`}>
              New date for {item.title}
            </label>
            <Input id={`due-${item.id}`} type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-8 w-auto" autoFocus />
            <Button type="submit" size="sm" variant="primary" disabled={!date} loading={pending}>
              Save date
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
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
        <IconButton icon={Ellipsis} label={`More actions for ${item.title}`} size="sm" className="-mr-1.5 -mt-1 opacity-70 group-hover:opacity-100" />
      </Menu>
    </li>
  );
}

