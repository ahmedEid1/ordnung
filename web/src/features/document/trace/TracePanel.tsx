/**
 * "How it was read" (a tab of the letter's page): one reading of the letter — when, how long, what
 * Claude was asked and what it cost, then every step as a waterfall (text layer, transcription,
 * extraction and its repair, each quote checked on the page, each date the rules engine computed, how
 * the sender, thread and contract were linked, what happened to each to-do). A letter read more than
 * once can show an earlier reading and what the newer one decided differently.
 *
 * Only steps, numbers and ids are kept (`src/ordnung/trace`) — the names shown are the records' names
 * now; the letter's text never is.
 */
import { type RefObject, useEffect, useRef, useState } from "react";
import { format as formatClock } from "date-fns";
import { GitCompareArrows, History, RotateCw } from "lucide-react";
import { ApiError } from "@/api/client";
import { useDocumentTrace, useHealth, useParties, useReprocessDocument, useRules, useTraceComparison } from "@/api/hooks";
import { seedJob } from "@/api/sse";
import type { Document, DocumentDetail, DocumentTrace, TraceComparison, TraceRun } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { KindBadge } from "@/components/ui/KindBadge";
import { LoadError } from "@/components/ui/LoadError";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { LoadingLabel, SkeletonCard } from "@/components/ui/Skeleton";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { formatCompact, formatUsd } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { cn, plural } from "@/lib/utils";
import { isStaticDemo } from "@/mocks/mode";
import { LetterTitle, NotReadYet, detailTitleSize } from "../HeldCard";
import { changeText, compareBase, exportCommand, formatMs, runResult, runTitle } from "./copy";
import { Waterfall } from "./Waterfall";

/** One figure of the summary: its label, value and sub-line sit on shared rows, so a label that wraps
 * never pushes its value below its neighbours'. */
function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="row-span-3 grid min-w-0 grid-rows-subgrid gap-y-1 rounded-xl bg-surface-2/60 px-3 py-2.5">
      <dt className="self-end text-[12px] font-medium leading-4 text-muted">{label}</dt>
      <dd className="text-[17px] font-semibold tabular-nums leading-6 text-ink">{value}</dd>
      {sub ? <dd className="text-[12px] leading-4 text-muted">{sub}</dd> : null}
    </div>
  );
}

const busyReading = (doc: Document) => doc.status === "queued" || doc.status === "processing";

/** "Read again", for a letter Claude may read: asks Claude again (a real call; the demo replays its
 * recorded answers) and reports the job. `cost` says which. The online demo can't read a letter
 * again (it has no Claude), so it never offers to. */
function useReadAgain(doc: Document) {
  const reprocess = useReprocessDocument();
  const health = useHealth();
  const allowed = !doc.ai_private && !busyReading(doc) && !isStaticDemo();
  const cost = health.data?.demo
    ? "In the demo, reading it again replays Claude's recorded answers."
    : "Reading it again asks Claude again, with your Claude account.";
  const start = (onStarted?: () => void, onFailed?: () => void) =>
    reprocess.mutate(doc.id, {
      onSuccess: (job) => {
        seedJob({ job_id: job.id, doc_id: doc.id, stage: "intake", progress: 0, status: "running" });
        onStarted?.();
      },
      onError: () => onFailed?.(),
    });
  return { allowed, start, pending: reprocess.isPending, cost };
}

/** Keyboard focus was dropped (a pressed button went away) — or is still on one of `ours` (the
 * button pressed, busy; a heading we put it on), so moving it takes nothing from the reader. */
function focusIsFree(...ours: (Element | null | undefined)[]): boolean {
  const active = document.activeElement;
  return !active || active === document.body || ours.some((element) => element != null && element === active);
}

/** When, how long, what it cost; the reading picker, "Compare" and "Read again and compare". */
function RunSummary({
  doc,
  trace,
  run,
  comparing,
  onPick,
  onCompare,
  onReadAgain,
  titleRef,
}: {
  doc: Document;
  trace: DocumentTrace;
  run: TraceRun;
  comparing: boolean;
  onPick: (traceId: string) => void;
  onCompare: () => void;
  /** Reading again has started (`pressed`: the button, busy until it goes away). */
  onReadAgain: (pressed: HTMLButtonElement | null) => void;
  /** The summary's heading (focus goes there when what the reader pressed goes away). */
  titleRef: RefObject<HTMLHeadingElement | null>;
}) {
  const several = trace.runs.length > 1;
  const readAgainButton = useRef<HTMLButtonElement>(null);
  /** Reading again failed: back to the button once it is no longer busy (a disabled one can't take focus). */
  const refocus = useRef(false);
  const result = runResult(run);
  const before = compareBase(trace.runs, run);
  const recorded = run.timing === "recorded";
  const readAgain = useReadAgain(doc);
  useEffect(() => {
    if (readAgain.pending || !refocus.current) return;
    refocus.current = false;
    if (focusIsFree(readAgainButton.current)) readAgainButton.current?.focus();
  }, [readAgain.pending]);
  const tokensIn = run.input_tokens + run.cache_read_tokens + run.cache_creation_tokens;
  const callsSub = [run.repairs ? plural(run.repairs, "repair") : null, run.cache_hits ? `${run.cache_hits} from the cache` : null].filter(Boolean).join(" · ");
  return (
    <section aria-labelledby="trace-run-title" className="@container card p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2 id="trace-run-title" ref={titleRef} tabIndex={-1} className="card-title outline-none">
            {runTitle(run, several)}
          </h2>
          <p className="mt-0.5 text-[13px] leading-5 text-muted">
            Started at <time dateTime={run.started_at}>{formatClock(new Date(run.started_at), "HH:mm")}</time>
          </p>
        </div>
        <Badge tone={result.tone} size="md" className="max-w-full">
          {result.text}
        </Badge>
      </div>
      {/* four across when the panel is wide (a phone or tablet, a very wide screen); else two by two */}
      <dl className="mt-4 grid grid-cols-2 gap-2 @lg:grid-cols-4">
        <Stat
          label={recorded ? "Time (recorded)" : "Time"}
          value={formatMs(run.duration_ms)}
          sub={run.model_ms ? `${formatMs(run.model_ms)} waiting for Claude` : "No call to Claude"}
        />
        <Stat label="Calls to Claude" value={String(run.model_calls)} sub={callsSub || undefined} />
        <Stat label="Tokens" value={formatCompact(tokensIn + run.output_tokens)} sub={`${formatCompact(tokensIn)} in · ${formatCompact(run.output_tokens)} out`} />
        <Stat label="API-equivalent cost" value={formatUsd(run.cost_usd)} />
      </dl>
      {several || readAgain.allowed ? (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {several ? (
            <span className="flex items-center gap-2">
              {/* phones show the readings' numbers only: say what they are */}
              <span aria-hidden className="text-[13px] font-medium text-muted sm:hidden">
                Reading
              </span>
              <SegmentedControl
                label="Reading"
                size="sm"
                value={run.trace_id}
                onChange={onPick}
                options={[...trace.runs].reverse().map((r) => ({
                  value: r.trace_id,
                  label: `Reading ${r.reading}`,
                  shortLabel: String(r.reading),
                }))}
              />
            </span>
          ) : null}
          {before ? (
            // a toggle keeps its name; whether it is on is aria-pressed
            // and on, it takes the accent tint, so sighted people see it too
            <Button
              size="sm"
              variant={comparing ? "soft" : "secondary"}
              icon={GitCompareArrows}
              aria-pressed={comparing}
              aria-controls={comparing ? "trace-compare" : undefined}
              onClick={onCompare}
            >
              Compare with reading {before.reading}
            </Button>
          ) : null}
          {readAgain.allowed ? (
            <Button
              ref={readAgainButton}
              size="sm"
              variant="ghost"
              icon={RotateCw}
              loading={readAgain.pending}
              // busy, the button is disabled and loses focus: back to it when reading again fails
              onClick={() =>
                readAgain.start(
                  () => onReadAgain(readAgainButton.current),
                  () => (refocus.current = true),
                )
              }
            >
              Read again and compare
            </Button>
          ) : null}
        </div>
      ) : null}
      <p role="status" className="sr-only">
        {comparing && before ? `What reading ${run.reading} decided differently from reading ${before.reading} is shown below.` : ""}
      </p>
      {recorded ? (
        <p className="mt-3 text-[12.5px] leading-5 text-muted">
          In the demo, Claude's answers are replayed{readAgain.allowed ? " (also when it is read again)" : ""}: their times are the recorded ones, and the steps of code
          show no time.
        </p>
      ) : readAgain.allowed ? (
        <p className="mt-3 text-[12.5px] leading-5 text-muted">{readAgain.cost}</p>
      ) : isStaticDemo() && !doc.ai_private ? (
        <p className="mt-3 text-[12.5px] leading-5 text-muted">In your own Ordnung, “Read again and compare” asks Claude again and shows what changed.</p>
      ) : null}
    </section>
  );
}

function Comparison({
  docId,
  base,
  head,
  titleRef,
}: {
  docId: string;
  base: TraceRun;
  head: TraceRun;
  /** The heading (focus goes there when a reading asked for arrives compared). */
  titleRef: RefObject<HTMLHeadingElement | null>;
}) {
  const q = useTraceComparison(docId, base.trace_id, head.trace_id);
  return (
    <section id="trace-compare" aria-labelledby="trace-compare-title" className="card p-4 sm:p-5" aria-busy={q.isPending}>
      <h2 id="trace-compare-title" ref={titleRef} tabIndex={-1} className="card-title outline-none">
        What reading {head.reading} decided differently from reading {base.reading}
      </h2>
      {q.isPending ? (
        <LoadingLabel>Comparing the two readings…</LoadingLabel>
      ) : q.isError ? (
        <LoadError
          size="sm"
          variant="plain"
          what="the comparison"
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
          headingLevel={3}
          className="mt-2"
        />
      ) : (
        <ChangeList comparison={q.data} />
      )}
    </section>
  );
}

/** The changes, one entry per step (a step can change in several ways). */
function ChangeList({ comparison }: { comparison: TraceComparison }) {
  const today = useTodayISO();
  if (!comparison.changes.length) {
    return <p className="mt-1.5 text-[13.5px] leading-5 text-muted">Both readings decided the same.</p>;
  }
  const steps: { key: string; what: string; details: string[] }[] = [];
  for (const c of comparison.changes) {
    const text = changeText(c, today);
    const last = steps[steps.length - 1];
    if (last && last.key === c.key) last.details.push(text.detail);
    else steps.push({ key: c.key, what: text.what, details: [text.detail] });
  }
  return (
    <ul className="mt-3 space-y-2">
      {steps.map((step, i) => (
        <li key={`${step.key}|${i}`} className="rounded-lg border border-line px-3 py-2 text-[13.5px] leading-5">
          <span className="block font-medium text-ink hyphens-auto [overflow-wrap:anywhere]">{step.what}</span>
          {step.details.map((detail, j) => (
            <span key={j} className="block text-muted hyphens-auto [overflow-wrap:anywhere]">
              {detail}
            </span>
          ))}
        </li>
      ))}
    </ul>
  );
}

function TraceSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true">
      <LoadingLabel>Loading how this letter was read…</LoadingLabel>
      <SkeletonCard lines={3} />
      <SkeletonCard lines={6} />
    </div>
  );
}

/**
 * The tab's heading: the letter's title, as the letter tab's verdict card (or waiting card) shows it — the
 * same size, in a card of the same padding under a row as tall as its badges, so switching tabs doesn't move
 * it (UI audit round 2: 25 px left, 65 px up and smaller).
 */
function TraceHeader({ detail }: { detail: DocumentDetail }) {
  const doc = detail.document;
  const title = doc.title ?? doc.filename;
  return (
    <header className="card px-5 pb-5 pt-5 sm:px-6 sm:pt-6">
      {doc.status === "held" ? (
        <NotReadYet />
      ) : (
        <div className="flex min-h-7 flex-wrap items-center gap-1.5">
          <KindBadge docKind={detail.advice?.kind === "operating_costs" ? "operating_costs" : doc.kind} />
          {doc.ai_private ? <Badge tone="neutral">Private — not read by Claude</Badge> : null}
        </div>
      )}
      <h1
        id="trace-title"
        tabIndex={-1}
        className={cn("display mt-3 scroll-mt-24 font-semibold text-ink outline-none wrap-break-word hyphens-manual", detailTitleSize(title))}
      >
        <LetterTitle title={doc.title} filename={doc.filename} />
      </h1>
      <p className="mt-2.5 text-base leading-5 text-muted">How Ordnung read it: what Claude was asked, what code checked, and what was filed.</p>
    </header>
  );
}

export function TracePanel({ detail }: { detail: DocumentDetail }) {
  return (
    <div className="space-y-4">
      <TraceHeader detail={detail} />
      <TraceBody detail={detail} />
    </div>
  );
}

/** No reading kept: say why, and offer to read the letter again when Claude may read it. */
function NoReading({ doc }: { doc: Document }) {
  const readAgain = useReadAgain(doc);
  if (busyReading(doc)) {
    return (
      <EmptyState
        illustration="search"
        headingLevel={2}
        title="Being read right now"
        description="Every step appears here once Ordnung has finished reading the letter."
      />
    );
  }
  if (doc.ai_private) {
    return (
      <EmptyState
        illustration="search"
        headingLevel={2}
        title="No reading kept for this letter"
        description="It is kept private, so Claude never reads it. Ordnung keeps how a letter was read from the next time it reads it."
      />
    );
  }
  if (!readAgain.allowed) {
    // the online demo: it can't read a letter again
    return (
      <EmptyState
        illustration="search"
        headingLevel={2}
        title="No reading kept for this letter"
        description="Ordnung keeps how a letter was read from the next time it reads it. In your own Ordnung, “Read it again” fills this in."
      />
    );
  }
  return (
    <EmptyState
      illustration="search"
      headingLevel={2}
      title="No reading kept for this letter"
      description={`Ordnung keeps how a letter was read from the next time it reads it. ${readAgain.cost}`}
      action={
        <Button variant="primary" icon={RotateCw} loading={readAgain.pending} onClick={() => readAgain.start()}>
          Read it again
        </Button>
      }
    />
  );
}

/** The command that exports the reading shown (with the data folder, so it works for the demo and
 * any other folder), or — in the online demo, which has no install — where it would be run. */
function ExportReading({ doc, trace, run }: { doc: Document; trace: DocumentTrace; run: TraceRun }) {
  const health = useHealth();
  const reading = run.trace_id === trace.runs[0]?.trace_id ? null : run.reading;
  if (isStaticDemo()) {
    return (
      <p className="text-[13px] leading-5 text-muted">
        In your own Ordnung,{" "}
        <code className="font-mono text-[12.5px] text-ink">
          ordnung trace &lt;letter&gt; <span className="whitespace-nowrap">--otel</span>
        </code>{" "}
        exports a reading for an OpenTelemetry viewer.
      </p>
    );
  }
  return (
    <>
      <p className="text-[13px] leading-5 text-muted">To look at this reading in an OpenTelemetry viewer:</p>
      <CopyCommand command={exportCommand(doc.id, { reading, dataDir: health.data?.data_dir ?? null })} label="export this reading" />
    </>
  );
}

function TraceBody({ detail }: { detail: DocumentDetail }) {
  const doc = detail.document;
  const [picked, setPicked] = useState<string | null>(null);
  const [comparing, setComparing] = useState(false);
  /** "Read again and compare": the newest reading when it was asked for; the newer one opens compared. */
  const [awaiting, setAwaiting] = useState<number | null>(null);
  const q = useDocumentTrace(doc.id, picked);
  const rules = useRules();
  const parties = useParties();
  const partyName = (id: string) => parties.data?.find((p) => p.id === id)?.name ?? null;
  const newestReading = q.data?.runs[0]?.reading ?? 0;
  const gone = q.error instanceof ApiError && q.error.status === 404 && picked !== null;
  const showNewest = useRef<HTMLButtonElement>(null);
  const runTitle = useRef<HTMLHeadingElement>(null);
  const compareTitle = useRef<HTMLHeadingElement>(null);
  /** Where focus goes once it is shown, after the button pressed went away: the comparison a "Read
   * again and compare" waits for, or the newest reading ("Show the newest reading"). */
  const focusNext = useRef<"compare" | "run" | null>(null);
  /** The heading focus was put on while waiting (moving on from it is not taking focus away). */
  const placed = useRef<Element | null>(null);

  // the reading asked for has arrived: show it, compared with the one before (state set while
  // rendering, as React does for state that follows data)
  if (awaiting !== null && newestReading > awaiting) {
    setAwaiting(null);
    setPicked(null);
    setComparing(true);
  }
  // the reading picked is gone: its radio went with it, so focus goes to the way back
  useEffect(() => {
    if (gone) showNewest.current?.focus();
  }, [gone]);
  // after every render: the view focus waits for is there — move focus to its heading, unless the
  // reader has moved on meanwhile
  useEffect(() => {
    const target = focusNext.current === "compare" ? compareTitle.current : focusNext.current === "run" ? runTitle.current : null;
    if (!target) return;
    focusNext.current = null;
    if (focusIsFree(placed.current)) target.focus();
    placed.current = null;
  });

  if (q.isPending) return <TraceSkeleton />;
  if (q.isError) {
    return gone ? (
      <EmptyState
        illustration="search"
        headingLevel={2}
        title="That reading isn't kept any more"
        description="Ordnung keeps the last five readings of a letter."
        action={
          <Button
            ref={showNewest}
            variant="primary"
            icon={History}
            onClick={() => {
              focusNext.current = "run";
              setPicked(null);
            }}
          >
            Show the newest reading
          </Button>
        }
      />
    ) : (
      <LoadError what="how this letter was read" error={q.error} onRetry={() => void q.refetch()} retrying={q.isFetching} />
    );
  }
  const trace = q.data;
  const run = trace.run;
  if (!run) return <NoReading doc={doc} />;
  const before = compareBase(trace.runs, run);
  return (
    <div className="space-y-4">
      {busyReading(doc) ? (
        <p role="status" className="rounded-xl border border-line bg-surface-2/60 px-4 py-3 text-[13.5px] leading-5 text-ink">
          Being read again — the new reading appears here when it's done.
        </p>
      ) : null}
      <RunSummary
        doc={doc}
        trace={trace}
        run={run}
        comparing={comparing && Boolean(before)}
        onPick={(id) => {
          setPicked(id === trace.runs[0]?.trace_id ? null : id);
          setComparing(false);
        }}
        onCompare={() => setComparing((c) => !c)}
        onReadAgain={(pressed) => {
          setComparing(false);
          setAwaiting(newestReading);
          // the button is going away while the letter is read: wait on the summary's heading
          focusNext.current = "compare";
          if (focusIsFree(pressed) && runTitle.current) {
            runTitle.current.focus();
            placed.current = runTitle.current;
          }
        }}
        titleRef={runTitle}
      />
      {comparing && before ? <Comparison docId={doc.id} base={before} head={run} titleRef={compareTitle} /> : null}
      {run.error ? (
        <p role="note" className="rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-[13.5px] leading-5 text-warn-ink">
          {run.error}
        </p>
      ) : null}
      <Waterfall key={run.trace_id} spans={trace.spans} recorded={run.timing === "recorded"} items={detail.items} rules={rules.data ?? []} partyName={partyName} />
      <section aria-labelledby="trace-privacy-title" className="space-y-2 px-1">
        <h2 id="trace-privacy-title" className="eyebrow">
          What is kept
        </h2>
        <p className="text-[13px] leading-5 text-muted">
          Only the steps, their numbers and the ids of what they found — never the letter's text. Ordnung keeps the last five readings; deleting the letter deletes them.
        </p>
        <ExportReading doc={doc} trace={trace} run={run} />
      </section>
    </div>
  );
}
