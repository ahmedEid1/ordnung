/**
 * "How this was read" (a tab of the letter's page): one reading of the letter — when, how long, what
 * Claude was asked and what it cost, then every step as a waterfall (text layer, transcription,
 * extraction and its repair, each quote checked on the page, each date the rules engine computed, how
 * the sender, thread and contract were linked, what happened to each to-do). A letter read more than
 * once can show an earlier reading and what the newer one decided differently.
 *
 * Only steps, numbers and ids are kept (`src/ordnung/trace`) — the names shown are the records' names
 * now; the letter's text never is.
 */
import { useState } from "react";
import { GitCompareArrows, History } from "lucide-react";
import { ApiError } from "@/api/client";
import { useDocumentTrace, useParties, useRules, useTraceComparison } from "@/api/hooks";
import type { DocumentDetail, DocumentTrace, TraceComparison, TraceRun } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { LoadingLabel, SkeletonCard } from "@/components/ui/Skeleton";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { formatCompact, formatDateTime, formatUsd } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { plural } from "@/lib/utils";
import { changeText, formatMs, runResult, runTitle } from "./copy";
import { Waterfall } from "./Waterfall";

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-0 rounded-xl bg-surface-2/60 px-3 py-2.5">
      <dt className="text-[12px] font-medium leading-4 text-muted">{label}</dt>
      <dd className="mt-1 text-[17px] font-semibold tabular-nums leading-6 text-ink">{value}</dd>
      {sub ? <dd className="text-[12px] leading-4 text-muted">{sub}</dd> : null}
    </div>
  );
}

/** When, how long, what it cost; the reading picker and "Compare" when there are several. */
function RunSummary({
  trace,
  run,
  comparing,
  onPick,
  onCompare,
}: {
  trace: DocumentTrace;
  run: TraceRun;
  comparing: boolean;
  onPick: (traceId: string) => void;
  onCompare: () => void;
}) {
  const several = trace.runs.length > 1;
  const result = runResult(run);
  const before = trace.runs.find((r) => r.reading < run.reading);
  const recorded = run.timing === "recorded";
  const tokensIn = run.input_tokens + run.cache_read_tokens + run.cache_creation_tokens;
  const callsSub = [run.repairs ? plural(run.repairs, "repair") : null, run.cache_hits ? `${run.cache_hits} from the cache` : null].filter(Boolean).join(" · ");
  return (
    <section aria-labelledby="trace-run-title" className="@container card p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2 id="trace-run-title" className="card-title">
            {runTitle(run, several)}
          </h2>
          <p className="mt-0.5 text-[13px] leading-5 text-muted">
            Started <time dateTime={run.started_at}>{formatDateTime(run.started_at)}</time>
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
      {several ? (
        <div className="mt-4 flex flex-wrap items-center gap-2">
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
          {before ? (
            <Button size="sm" icon={GitCompareArrows} aria-pressed={comparing} onClick={onCompare}>
              {comparing ? "Hide the comparison" : `Compare with reading ${before.reading}`}
            </Button>
          ) : null}
        </div>
      ) : null}
      {recorded ? (
        <p className="mt-3 text-[12.5px] leading-5 text-muted">
          In the demo, Claude's answers are replayed: their times are the recorded ones, and the steps of code show no time.
        </p>
      ) : null}
    </section>
  );
}

function Comparison({ docId, base, head }: { docId: string; base: TraceRun; head: TraceRun }) {
  const q = useTraceComparison(docId, base.trace_id, head.trace_id);
  return (
    <section aria-labelledby="trace-compare-title" className="card p-4 sm:p-5" aria-busy={q.isPending}>
      <h3 id="trace-compare-title" className="card-title">
        What reading {head.reading} decided differently from reading {base.reading}
      </h3>
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

function ChangeList({ comparison }: { comparison: TraceComparison }) {
  const today = useTodayISO();
  if (!comparison.changes.length) {
    return <p className="mt-1.5 text-[13.5px] leading-5 text-muted">Both readings decided the same — only how long the steps took differs.</p>;
  }
  return (
    <ul className="mt-3 space-y-2">
      {comparison.changes.map((c, i) => {
        const text = changeText(c, today);
        return (
          <li key={`${c.key}|${c.field}|${i}`} className="rounded-lg border border-line px-3 py-2 text-[13.5px] leading-5">
            <span className="block break-words font-medium text-ink">{text.what}</span>
            <span className="block break-words text-muted">{text.detail}</span>
          </li>
        );
      })}
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

/** The tab's heading: the letter's title (the letter tab's heading is its verdict card's). */
function TraceHeader({ title }: { title: string }) {
  return (
    <header>
      <h1
        id="trace-title"
        tabIndex={-1}
        className="display text-[24px] font-semibold leading-[1.15] text-ink outline-none [overflow-wrap:anywhere] hyphens-auto sm:text-[26px]"
      >
        {title}
      </h1>
      <p className="mt-1.5 text-[14px] leading-5 text-muted">How Ordnung read it: what Claude was asked, what code checked, and what was filed.</p>
    </header>
  );
}

export function TracePanel({ detail }: { detail: DocumentDetail }) {
  return (
    <div className="space-y-4">
      <TraceHeader title={detail.document.title ?? detail.document.filename} />
      <TraceBody detail={detail} />
    </div>
  );
}

function TraceBody({ detail }: { detail: DocumentDetail }) {
  const doc = detail.document;
  const [picked, setPicked] = useState<string | null>(null);
  const [comparing, setComparing] = useState(false);
  const q = useDocumentTrace(doc.id, picked);
  const rules = useRules();
  const parties = useParties();
  const partyName = (id: string) => parties.data?.find((p) => p.id === id)?.name ?? null;

  if (q.isPending) return <TraceSkeleton />;
  if (q.isError) {
    const gone = q.error instanceof ApiError && q.error.status === 404 && picked !== null;
    return gone ? (
      <EmptyState
        illustration="search"
        headingLevel={2}
        title="That reading isn't kept any more"
        description="Ordnung keeps the last five readings of a letter."
        action={
          <Button variant="primary" icon={History} onClick={() => setPicked(null)}>
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
  if (!run) {
    const reading = doc.status === "queued" || doc.status === "processing";
    return (
      <EmptyState
        illustration="search"
        headingLevel={2}
        title={reading ? "Being read right now" : "No reading kept for this letter"}
        description={
          reading
            ? "Every step appears here once Ordnung has finished reading the letter."
            : "Ordnung keeps how a letter was read from the next time it reads it. “Read again” (below the letter) shows every step here."
        }
      />
    );
  }
  const before = trace.runs.find((r) => r.reading < run.reading);
  return (
    <div className="space-y-4">
      <RunSummary
        trace={trace}
        run={run}
        comparing={comparing && Boolean(before)}
        onPick={(id) => {
          setPicked(id === trace.runs[0]?.trace_id ? null : id);
          setComparing(false);
        }}
        onCompare={() => setComparing((c) => !c)}
      />
      {comparing && before ? <Comparison docId={doc.id} base={before} head={run} /> : null}
      {run.error ? (
        <p role="note" className="rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-[13.5px] leading-5 text-warn-ink">
          {run.error}
        </p>
      ) : null}
      <Waterfall key={run.trace_id} spans={trace.spans} recorded={run.timing === "recorded"} items={detail.items} rules={rules.data ?? []} partyName={partyName} />
      <section aria-labelledby="trace-privacy-title" className="space-y-2 px-1">
        <h3 id="trace-privacy-title" className="eyebrow">
          What is kept
        </h3>
        <p className="text-[13px] leading-5 text-muted">
          Only the steps, their numbers and the ids of what they found — never the letter's text. Ordnung keeps the last five readings; deleting the letter deletes them.
          To look at this reading in an OpenTelemetry viewer:
        </p>
        <CopyCommand command={`ordnung trace ${doc.id} --otel -o trace.json`} label="export this reading" />
      </section>
    </div>
  );
}
