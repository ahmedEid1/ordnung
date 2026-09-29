import { lazy, Suspense, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import {
  Activity as ActivityIcon,
  Ban,
  CalendarPlus,
  ChevronRight,
  FileText,
  HardDrive,
  Lock,
  MessagesSquare,
  Send,
  ShieldCheck,
  Sparkles,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useActivity, useDocuments, useUsage } from "@/api/hooks";
import type { LLMCallRecord } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { PRIVACY_STATEMENT } from "@/features/onboarding/options";
import { formatCompact, formatDateTime, formatFileSize, formatPercent, formatUsd } from "@/lib/format";
import { useMediaQuery } from "@/lib/hooks";
import { cn, plural } from "@/lib/utils";
import {
  activityHref,
  askChecksMessage,
  cacheRate,
  groupActivity,
  modelFamily,
  purposeLabel,
  purposeRows,
  sentSummary,
  type AskChecks,
  type PurposeRow,
} from "./logic";
import { SectionHeading, SettingsCard } from "./SettingsCard";

// recharts is only needed here — load it with this section, not with the whole Settings page
const UsageChart = lazy(() => import("./UsageChart").then((m) => ({ default: m.UsageChart })));

/** Letters a call names before "+N more". */
const DOCS_SHOWN = 2;
/** Activity rows before "Show … older". */
const ACTIVITY_SHOWN = 10;
/** Calls listed before "Show all … calls". */
const CALLS_SHOWN = 8;

/**
 * One figure of the usage summary (a term/definition pair inside the summary's `<dl>`). Its label,
 * value and note sit on the rows of the grid (subgrid), so a label that wraps keeps the values of
 * that row on one line.
 */
function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="row-span-3 grid min-w-0 grid-rows-subgrid gap-y-0 rounded-xl border border-line bg-surface px-4 py-3.5">
      <dt className="text-sm leading-snug text-muted">{label}</dt>
      <dd className="mt-1 text-[22px] font-semibold leading-tight tabular-nums text-ink">{value}</dd>
      {sub ? <dd className="mt-0.5 text-xs leading-snug text-muted">{sub}</dd> : null}
    </div>
  );
}

const ACTIVITY_ICONS: [RegExp, LucideIcon][] = [
  [/^document/, FileText],
  [/^draft/, Send],
  [/^calendar/, CalendarPlus],
  [/review|suggestion|idea/, Sparkles],
  [/^ask|answer|chat/, MessagesSquare],
  [/private/, Lock],
];

function activityIcon(kind: string): LucideIcon {
  return ACTIVITY_ICONS.find(([re]) => re.test(kind))?.[1] ?? ActivityIcon;
}

/**
 * Under a row that folds Ask's checks ("Checked 12 answers in Ask"): what the checks did, behind a
 * disclosure lined up with the row's text.
 */
function AskChecksDetails({ checks }: { checks: AskChecks }) {
  return (
    <details className="group mb-1.5 ml-10">
      <summary className="inline-flex min-h-6 cursor-pointer list-none items-center gap-1 rounded-md text-[12.5px] font-medium text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 shrink-0 transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden />
        What the checks did
      </summary>
      <ul className="mt-1 space-y-1.5 text-[13px] leading-5 text-muted">
        {checks.done.map((d) => (
          <li key={d.what} className="flex gap-2">
            <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-current" />
            <span className="min-w-0 wrap-anywhere">
              {d.what}
              {"\u00a0· "}
              <span className="whitespace-nowrap tabular-nums">{plural(d.answers, "answer")}</span>
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function Statement() {
  const cols: { icon: LucideIcon; title: string; body: string; tone: string }[] = [
    { icon: HardDrive, title: "Stays on this computer", body: "Your files, the database, your profile and every date Ordnung computes.", tone: "text-ok" },
    { icon: Send, title: "Sent to Anthropic", body: "The text or image of a letter when Claude reads it — through your own Claude account.", tone: "text-accent" },
    { icon: Ban, title: "Never", body: "No Ordnung server, no telemetry, no tracking. Ordnung never sees your credentials.", tone: "text-muted" },
  ];
  return (
    <SettingsCard className="@container">
      {/* phones: the shield above the statement, so the text has the card's whole width */}
      <div className="flex flex-col gap-3 @md:flex-row">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
          <ShieldCheck className="size-5" aria-hidden />
        </span>
        <p className="min-w-0 text-md font-medium leading-relaxed text-ink">{PRIVACY_STATEMENT}</p>
      </div>
      <ul className="mt-5 grid gap-3 @xl:grid-cols-3">
        {cols.map((c) => (
          <li key={c.title} className="min-w-0 rounded-xl bg-surface-2/60 p-3.5">
            <p className="flex items-start gap-2 text-base font-semibold leading-snug text-ink">
              <c.icon className={cn("mt-px size-4 shrink-0", c.tone)} aria-hidden />
              {c.title}
            </p>
            <p className="mt-1 text-sm leading-5 text-muted">{c.body}</p>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-sm leading-5 text-muted">
        Letters you mark <strong className="font-medium text-ink">“Keep private — no AI”</strong> are stored and searchable, but never sent to Claude.
      </p>
    </SettingsCard>
  );
}

/** Phones: cost by purpose as rows (label and value above a full-width bar) — the chart has no room. */
function UsageBars({ rows }: { rows: PurposeRow[] }) {
  const max = Math.max(0, ...rows.map((r) => r.cost));
  return (
    // hidden from assistive tech: the table below has the same numbers
    <ul aria-hidden className="space-y-3">
      {rows.map((r) => (
        <li key={r.purpose}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 text-ink wrap-anywhere">{r.label}</span>
            <span className="shrink-0 font-medium tabular-nums text-ink">{formatUsd(r.cost)}</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-accent" style={{ width: `${max > 0 ? Math.max((r.cost / max) * 100, r.cost > 0 ? 1.5 : 0) : 0}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** The letters a call sent: the first two, then "+13 more" to show the rest. */
function DocLinks({ ids, docTitle }: { ids: string[]; docTitle: (id: string) => string }) {
  const [all, setAll] = useState(false);
  if (!ids.length) return null;
  const shown = all ? ids : ids.slice(0, DOCS_SHOWN);
  return (
    <ul className="mt-0.5 text-sm">
      {shown.map((id) => (
        <li key={id} className="min-w-0">
          <Link to={`/documents/${id}`} className="inline-flex min-h-6 items-center text-accent wrap-anywhere hover:underline">
            {docTitle(id)}
          </Link>
        </li>
      ))}
      {ids.length > DOCS_SHOWN ? (
        <li>
          <button type="button" aria-expanded={all} onClick={() => setAll(!all)} className="inline-flex min-h-6 items-center font-medium text-muted hover:text-ink hover:underline">
            {all ? (
              "Show fewer"
            ) : (
              <>
                +{ids.length - DOCS_SHOWN} more <span className="sr-only">letters</span>
              </>
            )}
          </button>
        </li>
      ) : null}
    </ul>
  );
}

/** A call's cost — or "Cache" — and whether it failed. */
function CallCost({ c }: { c: LLMCallRecord }) {
  return (
    <>
      {c.cache_hit ? (
        <Badge tone="ok" icon={Zap}>
          Cache
        </Badge>
      ) : (
        <span className="font-medium tabular-nums text-ink">{formatUsd(c.cost_usd)}</span>
      )}
      {!c.ok ? (
        // the demo only replays recordings: a question it has none for isn't a failure
        c.backend === "replay" || /^no recorded response/i.test(c.error ?? "") ? (
          <span className="block whitespace-normal text-xs text-muted">Not recorded (demo)</span>
        ) : (
          <span className="block text-xs text-danger-ink">Failed</span>
        )
      ) : null}
    </>
  );
}

/**
 * Every prompt token counts as "in", those read from or written to the prompt cache too — as the letter's
 * "How it was read" and the totals above count them (walkthrough of phase 2: "2 in" beside the trace's "20k in").
 */
const tokensIn = (c: Pick<LLMCallRecord, "input_tokens" | "cache_read_tokens" | "cache_creation_tokens">) =>
  c.input_tokens + (c.cache_read_tokens ?? 0) + (c.cache_creation_tokens ?? 0);
const tokensOf = (c: LLMCallRecord) => formatCompact(tokensIn(c) + c.output_tokens);

/** Wide panes: one table row per call (the day above the time, so "What was sent" gets the room). */
function CallRow({ c, docTitle }: { c: LLMCallRecord; docTitle: (id: string) => string }) {
  const when = formatDateTime(c.ts);
  const cut = when.lastIndexOf(", ");
  return (
    <tr className="align-top">
      <td className="whitespace-nowrap py-3 pl-5 pr-4 text-muted sm:pl-6">
        <time dateTime={c.ts}>
          {cut > 0 ? (
            <>
              {when.slice(0, cut)}
              <span className="sr-only">, </span>
              <span className="block text-xs">{when.slice(cut + 2)}</span>
            </>
          ) : (
            when
          )}
        </time>
      </td>
      <td className="whitespace-nowrap py-3 pr-4">
        <span className="font-medium text-ink">{purposeLabel(c.purpose)}</span>
        <span className="block text-xs text-muted">{modelFamily(c.model)}</span>
      </td>
      <td className="py-3 pr-4">
        <span className="text-ink/85">{sentSummary(c, formatFileSize)}</span>
        <DocLinks ids={c.doc_ids} docTitle={docTitle} />
      </td>
      <td className="whitespace-nowrap py-3 pr-5 text-right sm:pr-6">
        <CallCost c={c} />
        <span className="block text-xs tabular-nums text-muted">
          {tokensOf(c)} tokens<span className="sr-only">: {formatCompact(tokensIn(c))} in, {formatCompact(c.output_tokens)} out</span>
        </span>
      </td>
    </tr>
  );
}

/** Narrow panes: one stacked entry per call. */
function CallItem({ c, docTitle }: { c: LLMCallRecord; docTitle: (id: string) => string }) {
  return (
    <li className="px-5 py-3.5 text-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 text-base leading-snug">
          <span className="font-medium text-ink">{purposeLabel(c.purpose)}</span> <span className="text-muted">· {modelFamily(c.model)}</span>
        </p>
        <div className="shrink-0 text-right text-base">
          <CallCost c={c} />
        </div>
      </div>
      <p className="mt-0.5 flex flex-wrap justify-between gap-x-3 text-xs text-muted">
        <time dateTime={c.ts}>{formatDateTime(c.ts)}</time>
        <span className="tabular-nums">{tokensOf(c)} tokens</span>
      </p>
      <p className="mt-1.5 text-ink/85">{sentSummary(c, formatFileSize)}</p>
      <DocLinks ids={c.doc_ids} docTitle={docTitle} />
    </li>
  );
}

/** "Privacy & AI usage": the honest privacy statement, what was sent per call, totals, activity. */
export function PrivacySection() {
  const usage = useUsage();
  const activity = useActivity(60);
  const docs = useDocuments();
  const roomForChart = useMediaQuery("(min-width: 640px)");
  const [allActivity, setAllActivity] = useState(false);
  const [allCalls, setAllCalls] = useState(false);
  const rows = useMemo(() => purposeRows(usage.data), [usage.data]);
  const titles = useMemo(() => new Map((docs.data ?? []).map((d) => [d.id, d.title ?? d.filename])), [docs.data]);
  const docTitle = (id: string) => titles.get(id) ?? "a letter";
  const activityRows = useMemo(() => groupActivity(activity.data ?? []), [activity.data]);
  const shownActivity = allActivity ? activityRows : activityRows.slice(0, ACTIVITY_SHOWN);
  const u = usage.data;
  const rate = cacheRate(u);
  const recent = u?.recent ?? [];
  const shownCalls = allCalls ? recent : recent.slice(0, CALLS_SHOWN);

  return (
    <section aria-labelledby="set-privacy">
      <SectionHeading id="set-privacy" title="Privacy & AI usage" description="Exactly what leaves this computer, when, and what it would cost on the API." />
      <div className="space-y-5">
        <Statement />

        <SettingsCard
          title="AI usage"
          id="set-usage"
          className="@container"
          description="API-equivalent cost is what these calls would cost on Anthropic's API. With a Claude subscription you don't pay per call — it counts towards your plan's limits."
        >
          {usage.isPending ? (
            <div className="grid grid-cols-2 gap-3 @2xl:grid-cols-4" aria-busy="true">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 rounded-xl" />
              ))}
            </div>
          ) : usage.isError ? (
            <LoadError what="the usage figures" error={usage.error} onRetry={() => void usage.refetch()} retrying={usage.isFetching} headingLevel={3} variant="plain" size="sm" />
          ) : !u || !u.calls ? (
            <EmptyState size="sm" variant="plain" headingLevel={4} illustration="clear" title="No calls to Claude yet" description="When Claude reads a letter or answers a question, you'll see it here." />
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-3 @2xl:grid-cols-4">
                <Stat label="Calls to Claude" value={u.calls.toLocaleString("en-GB")} />
                <Stat label="From the cache" value={rate === null ? "—" : formatPercent(rate)} sub={`${u.cache_hits.toLocaleString("en-GB")} of ${plural(u.calls, "call")}`} />
                <Stat label="Tokens" value={formatCompact(u.input_tokens + u.output_tokens)} sub={`${formatCompact(u.input_tokens)} in · ${formatCompact(u.output_tokens)} out`} />
                <Stat label="API-equivalent cost" value={formatUsd(u.cost_usd)} sub="Not billed with a subscription" />
              </dl>

              <h4 className="eyebrow mb-2 mt-6">Cost by purpose</h4>
              {roomForChart ? (
                <Suspense fallback={<Skeleton className="h-60 w-full rounded-lg" />}>
                  <UsageChart rows={rows} />
                </Suspense>
              ) : (
                <UsageBars rows={rows} />
              )}
              {/* a table can't be `sr-only` itself: it keeps its content width and widens the page */}
              <div className="sr-only">
                <table>
                  <caption>API-equivalent cost by purpose</caption>
                  <thead>
                    <tr>
                      <th scope="col">Purpose</th>
                      <th scope="col">Calls</th>
                      <th scope="col">Tokens</th>
                      <th scope="col">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.purpose}>
                        <th scope="row">{r.label}</th>
                        <td>{r.calls}</td>
                        <td>{formatCompact(r.tokens)}</td>
                        <td>{formatUsd(r.cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </SettingsCard>

        {/* only when there is something to list — the card above already says "no calls yet" */}
        {usage.isPending || u?.recent.length ? (
          // overflow-clip, not -hidden: the table's header stays in view under the top bar (sticky)
          <section aria-labelledby="set-calls" className="card overflow-clip @container">
            <div className="px-5 pb-3 pt-5 sm:px-6">
              <h3 id="set-calls" className="card-title">
                What was sent, call by call
              </h3>
              <p className="mt-1 text-[13.5px] text-muted">
                Only counts and sizes are logged — never the content itself.{u?.recent.length ? ` The latest ${plural(u.recent.length, "call")}.` : null}
              </p>
            </div>
            {usage.isPending || !u ? (
              <SkeletonText lines={5} className="px-5 pb-6 sm:px-6" />
            ) : (
              <>
                <ul className="divide-y divide-line border-t border-line @2xl:hidden">
                  {shownCalls.map((c) => (
                    <CallItem key={c.id} c={c} docTitle={docTitle} />
                  ))}
                </ul>
                <table className="hidden w-full text-left text-sm @2xl:table">
                  <thead className="text-xs text-muted [&_th]:sticky [&_th]:top-14 [&_th]:z-[1] [&_th]:bg-surface-2 [&_th]:py-2 [&_th]:font-medium [&_th]:shadow-[inset_0_1px_0_var(--color-line),inset_0_-1px_0_var(--color-line)]">
                    <tr>
                      <th scope="col" className="pl-5 pr-4 sm:pl-6">
                        When
                      </th>
                      <th scope="col" className="pr-4">
                        For
                      </th>
                      <th scope="col" className="pr-4">
                        What was sent
                      </th>
                      <th scope="col" className="pr-5 text-right sm:pr-6">
                        Cost
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {shownCalls.map((c) => (
                      <CallRow key={c.id} c={c} docTitle={docTitle} />
                    ))}
                  </tbody>
                </table>
                {recent.length > CALLS_SHOWN ? (
                  <div className="border-t border-line px-5 py-2.5 sm:px-6">
                    <button
                      type="button"
                      aria-expanded={allCalls}
                      onClick={() => setAllCalls(!allCalls)}
                      className="inline-flex min-h-6 items-center text-sm font-medium text-accent hover:underline"
                    >
                      {allCalls ? "Show fewer" : `Show all ${plural(recent.length, "call")}`}
                    </button>
                  </div>
                ) : null}
              </>
            )}
          </section>
        ) : null}

        <SettingsCard title="Activity" id="set-activity" className="@container" description="Everything Ordnung did on its own — reading letters, reviews, exports.">
          {activity.isPending ? (
            <SkeletonText lines={6} />
          ) : activity.isError ? (
            <LoadError what="the activity" error={activity.error} onRetry={() => void activity.refetch()} retrying={activity.isFetching} headingLevel={3} variant="plain" size="sm" />
          ) : activityRows.length ? (
            <>
              <ol className="space-y-0.5">
                {shownActivity.map(({ entry: a, count, askChecks }) => {
                  const Icon = activityIcon(a.kind);
                  const href = activityHref(a);
                  const body = (
                    <>
                      <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
                        <Icon className="size-3.5" aria-hidden />
                      </span>
                      <span className="flex min-w-0 flex-1 flex-col gap-x-4 gap-y-0.5 pt-1 @lg:flex-row @lg:items-baseline">
                        <span className="min-w-0 flex-1 text-base leading-5 text-ink wrap-anywhere">
                          {askChecks ? askChecksMessage(askChecks.answers) : a.message}
                          {count > 1 && !askChecks ? (
                            <>
                              {" "}
                              <span className="ml-0.5 inline-block whitespace-nowrap rounded-full bg-surface-2 px-1.5 text-xs font-medium tabular-nums text-muted">
                                <span aria-hidden>×{count}</span>
                                <span className="sr-only">({count} times)</span>
                              </span>
                            </>
                          ) : null}
                        </span>
                        <time dateTime={a.ts} className="shrink-0 whitespace-nowrap text-xs text-muted">
                          {formatDateTime(a.ts)}
                        </time>
                      </span>
                    </>
                  );
                  return (
                    <li key={a.id}>
                      {href ? (
                        <Link to={href} className="-mx-2 flex items-start gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-surface-2/70">
                          {body}
                        </Link>
                      ) : (
                        <div className="-mx-2 flex items-start gap-3 px-2 py-2">{body}</div>
                      )}
                      {askChecks ? <AskChecksDetails checks={askChecks} /> : null}
                    </li>
                  );
                })}
              </ol>
              {activityRows.length > ACTIVITY_SHOWN ? (
                <button
                  type="button"
                  aria-expanded={allActivity}
                  onClick={() => setAllActivity(!allActivity)}
                  className="mt-2 inline-flex min-h-6 items-center text-sm font-medium text-accent hover:underline"
                >
                  {allActivity ? "Show fewer" : `Show ${plural(activityRows.length - ACTIVITY_SHOWN, "older entry", "older entries")}`}
                </button>
              ) : null}
            </>
          ) : (
            <EmptyState size="sm" variant="plain" headingLevel={4} illustration="clear" title="Nothing yet" description="Letters Ordnung reads, reviews and exports will show up here." />
          )}
        </SettingsCard>
      </div>
    </section>
  );
}
