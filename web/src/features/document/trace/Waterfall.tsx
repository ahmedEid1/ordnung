/**
 * The steps of one reading as a waterfall: one row per step (its title, what it decided, how long it
 * took and a bar placed on the reading's time line), grouped by stage. A row opens to its facts; a
 * stage row also opens to its steps. A dated to-do's step links to the same "Why this date?" receipt
 * the letter shows, a repair call to the call it retried.
 */
import { useId, useMemo, useState, type ReactNode } from "react";
import { ChevronRight, FileSearch, Link2, ListChecks, type LucideIcon, Quote, Scale, ScanText, Sparkles } from "lucide-react";
import type { Item, RuleInfo, SpanKind, TraceSpan } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { TONES } from "@/lib/copy";
import { cn } from "@/lib/utils";
import { useTodayISO } from "@/lib/today";
import { WhyThisDate } from "../WhyThisDate";
import { barTone, formatMs, spanCopy, spanDetails } from "./copy";

const KIND_ICON: Record<SpanKind, LucideIcon> = {
  run: FileSearch,
  ocr: ScanText,
  model: Sparkles,
  verify: Quote,
  rules: Scale,
  link: Link2,
  plan: ListChecks,
};

export interface WaterfallContext {
  /** Length of the whole reading (the bars' scale). */
  total: number;
  /** Whether the times replay recorded answers (the demo): steps of code then take no time. */
  recorded: boolean;
  /** The app's today (dates in its year go without the year). */
  today: string;
  items: Map<string, Item>;
  rules: Map<string, RuleInfo>;
  partyName: (id: string) => string | null;
  /** The step of a usage-log call (for "Retry of …"). */
  callStep: Map<number, TraceSpan>;
  /** Open a step and move to it (a repair's link to the call it retried). */
  reveal: (spanId: string) => void;
  open: Set<string>;
  toggle: (spanId: string) => void;
}

/** A step's bar on the reading's time line (decorative: the duration is in the row's text). */
function Bar({ span, total }: { span: TraceSpan; total: number }) {
  const left = total > 0 ? (span.start_ms / total) * 100 : 0;
  const width = total > 0 ? (span.duration_ms / total) * 100 : 0;
  const tone = TONES[barTone(span)];
  return (
    <span className="relative mt-1.5 block h-1.5 w-full overflow-hidden rounded-full bg-surface-2" aria-hidden>
      <span
        className={cn("absolute inset-y-0 rounded-full", tone.solid, span.kind !== "model" && span.status === "ok" && barTone(span) === "neutral" && "opacity-60")}
        style={{ left: `${Math.min(left, 99)}%`, width: `max(${width}%, 4px)` }}
      />
    </span>
  );
}

function Details({ span, ctx }: { span: TraceSpan; ctx: WaterfallContext }) {
  const rows = spanDetails(span, ctx.partyName, ctx.today);
  const a = span.attributes;
  const item = span.ref?.type === "item" ? ctx.items.get(span.ref.id) : undefined;
  const ruleIds = Array.isArray(a.rule_ids) ? (a.rule_ids as string[]) : [];
  const citations = [...new Set(ruleIds.map((id) => ctx.rules.get(id)?.citation || ctx.rules.get(id)?.title).filter(Boolean))];
  const repairOf = typeof a.repair_of === "number" ? ctx.callStep.get(a.repair_of) : undefined;
  const extra: ReactNode[] = [];
  if (citations.length) extra.push(<Row key="rules" label="Rules applied" value={citations.join(" · ")} />);
  return (
    <div className="space-y-3">
      {rows.length || extra.length ? (
        <dl className="grid grid-cols-[minmax(6.5rem,2fr)_minmax(0,3fr)] gap-x-3 gap-y-1.5 text-[13px] leading-5 sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)] sm:gap-x-4">
          {rows.map((r) => (
            <Row key={r.label} label={r.label} value={r.value} />
          ))}
          {extra}
        </dl>
      ) : null}
      {repairOf ? (
        <p className="text-[13px] leading-5 text-muted">
          Retried the answer of{" "}
          <button
            type="button"
            onClick={() => ctx.reveal(repairOf.id)}
            className="inline-flex min-h-6 items-center font-medium text-accent underline-offset-2 hover:underline"
          >
            the call above
          </button>
          , with the problems listed.
        </p>
      ) : null}
      {span.kind === "rules" && item?.computation ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
          <span>The rules engine's receipt for this date:</span>
          <WhyThisDate receipt={item.computation} spec={item.date_spec} area={item.area} origin={item.origin} context={item.title} />
        </div>
      ) : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-ink">{value}</dd>
    </>
  );
}

/** One step: a disclosure row, then (open) its facts and its own steps. */
function StepRow({ span, steps, childrenOf, ctx }: { span: TraceSpan; steps: TraceSpan[]; childrenOf: Map<string, TraceSpan[]>; ctx: WaterfallContext }) {
  const open = ctx.open.has(span.id);
  const panelId = useId();
  const copy = spanCopy(span, ctx.today);
  const Icon = KIND_ICON[span.kind];
  const count = steps.length;
  // the demo replays Claude's answers with their recorded times; steps of code are not timed there
  const unmeasured = ctx.recorded && span.kind !== "model" && span.duration_ms === 0;
  // a group of steps (its own facts are none) says which steps it holds
  const summary = count && !Object.keys(span.attributes).length ? steps.map((s) => s.name).join(" · ") : copy.summary;
  return (
    <li id={`step-${span.id}`} className="scroll-mt-24">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => ctx.toggle(span.id)}
        className="group flex w-full min-w-0 items-start gap-2.5 rounded-lg px-2 py-2.5 text-left transition-colors hover:bg-surface-2/70 focus-visible:-outline-offset-2 sm:px-3"
      >
        <ChevronRight className={cn("mt-1 size-4 shrink-0 text-muted transition-transform motion-reduce:transition-none", open && "rotate-90")} aria-hidden />
        <span
          className={cn("mt-0.5 grid size-6 shrink-0 place-items-center rounded-md border border-line bg-surface", span.kind === "model" ? "text-accent" : "text-muted")}
          aria-hidden
        >
          <Icon className="size-3.5" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-start justify-between gap-3">
            <span className="min-w-0 break-words text-[14px] font-medium leading-5 text-ink">{copy.title}</span>
            <span className="shrink-0 pt-px text-[12.5px] tabular-nums leading-5 text-muted">
              {unmeasured ? (
                <>
                  <span aria-hidden>—</span>
                  <span className="sr-only">not measured</span>
                </>
              ) : (
                formatMs(span.duration_ms)
              )}
            </span>
          </span>
          <span className="mt-0.5 block break-words text-[13px] leading-5 text-muted">
            {summary}
            {count ? <span className="sr-only">. {count === 1 ? "1 step inside" : `${count} steps inside`}</span> : null}
          </span>
          {copy.flag ? (
            <Badge tone={copy.flag.tone} className="mt-1.5">
              {copy.flag.text}
            </Badge>
          ) : null}
          <Bar span={span} total={ctx.total} />
        </span>
      </button>
      {open ? (
        <div id={panelId} className="pb-3 pl-[2.125rem] pr-2 sm:pl-[2.375rem] sm:pr-3">
          <Details span={span} ctx={ctx} />
          {count ? (
            <ol aria-label={`Steps of “${copy.title}”`} className="mt-2 border-l border-line pl-1.5 sm:pl-2">
              {steps.map((child) => (
                <StepRow key={child.id} span={child} steps={childrenOf.get(child.id) ?? []} childrenOf={childrenOf} ctx={ctx} />
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export interface WaterfallProps {
  spans: TraceSpan[];
  recorded: boolean;
  items: Item[];
  rules: RuleInfo[];
  partyName: (id: string) => string | null;
}

/** The reading's steps (its root is the summary above them): every stage, then its steps when opened. */
export function Waterfall({ spans, recorded, items, rules, partyName }: WaterfallProps) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(initiallyOpen(spans)));
  const today = useTodayISO();
  const childrenOf = useMemo(() => {
    const map = new Map<string, TraceSpan[]>();
    for (const s of spans) if (s.parent_id) map.set(s.parent_id, [...(map.get(s.parent_id) ?? []), s]);
    return map;
  }, [spans]);
  const root = spans[0];
  const byId = useMemo(() => new Map(spans.map((s) => [s.id, s])), [spans]);
  const itemMap = useMemo(() => new Map(items.map((i) => [i.id, i])), [items]);
  const ruleMap = useMemo(() => new Map(rules.map((r) => [r.id, r])), [rules]);
  const callStep = useMemo(
    () => new Map(spans.flatMap((s) => (typeof s.attributes.call_id === "number" ? [[s.attributes.call_id as number, s] as const] : []))),
    [spans],
  );
  const ctx: WaterfallContext = {
    total: root?.duration_ms ?? 0,
    recorded,
    today,
    items: itemMap,
    rules: ruleMap,
    partyName,
    callStep,
    open,
    toggle: (id) =>
      setOpen((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      }),
    reveal: (id) => {
      const path: string[] = [];
      for (let s = byId.get(id); s; s = s.parent_id ? byId.get(s.parent_id) : undefined) path.push(s.id);
      setOpen((prev) => new Set([...prev, ...path]));
      requestAnimationFrame(() => {
        const row = document.getElementById(`step-${id}`);
        if (typeof row?.scrollIntoView === "function") row.scrollIntoView({ block: "center" });
        row?.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
      });
    },
  };
  if (!root) return null;
  const top = childrenOf.get(root.id) ?? [];
  return (
    <ol aria-label="Steps of this reading" className="card divide-y divide-line/70 p-1.5 sm:p-2">
      {top.map((s) => (
        <StepRow key={s.id} span={s} steps={childrenOf.get(s.id) ?? []} childrenOf={childrenOf} ctx={ctx} />
      ))}
    </ol>
  );
}

/** Steps worth seeing first: a model call whose answer didn't fit, failed or was repaired. */
function initiallyOpen(spans: TraceSpan[]): string[] {
  const byId = new Map(spans.map((s) => [s.id, s]));
  const open = new Set<string>();
  for (const s of spans) {
    const outcome = s.attributes.outcome;
    if (s.status !== "error" && outcome !== "invalid" && outcome !== "failed" && outcome !== "repaired") continue;
    for (let p = s.parent_id ? byId.get(s.parent_id) : undefined; p?.parent_id; p = p.parent_id ? byId.get(p.parent_id) : undefined) open.add(p.id);
  }
  return [...open];
}
