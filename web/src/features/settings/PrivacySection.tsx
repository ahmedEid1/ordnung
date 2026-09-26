import { lazy, Suspense, useMemo, type ReactNode } from "react";
import { Link } from "react-router";
import {
  Activity as ActivityIcon,
  Ban,
  CalendarPlus,
  Database,
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
import type { Activity, LLMCallRecord } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { PRIVACY_STATEMENT } from "@/features/onboarding/options";
import { formatCompact, formatDateTime, formatFileSize, formatPercent, formatUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { cacheRate, modelFamily, purposeLabel, purposeRows, sentSummary } from "./logic";
import { SectionHeading, SettingsCard } from "./SettingsCard";

// recharts is only needed here — load it with this section, not with the whole Settings page
const UsageChart = lazy(() => import("./UsageChart").then((m) => ({ default: m.UsageChart })));

/** One figure of the usage summary (a term/definition pair inside the summary's `<dl>`). */
function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3.5">
      <dt className="text-[12.5px] text-muted">{label}</dt>
      <dd className="mt-1 text-[22px] font-semibold leading-tight text-ink">{value}</dd>
      {sub ? <dd className="mt-0.5 text-[12px] text-muted">{sub}</dd> : null}
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

function activityHref(a: Activity): string | null {
  if (!a.ref_id) return null;
  if (a.ref_type === "document") return `/documents/${a.ref_id}`;
  if (a.ref_type === "draft") return `/letters/${a.ref_id}`;
  return null;
}

function Statement() {
  const cols: { icon: LucideIcon; title: string; body: string; tone: string }[] = [
    { icon: HardDrive, title: "Stays on this computer", body: "Your files, the database, your profile and every date Ordnung computes.", tone: "text-ok" },
    { icon: Send, title: "Sent to Anthropic", body: "The text or image of a letter when Claude reads it — through your own Claude account.", tone: "text-accent" },
    { icon: Ban, title: "Never", body: "No Ordnung server, no telemetry, no tracking. Ordnung never sees your credentials.", tone: "text-muted" },
  ];
  return (
    <SettingsCard>
      <div className="flex gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
          <ShieldCheck className="size-5" aria-hidden />
        </span>
        <blockquote className="display text-[17px] font-medium leading-snug text-ink sm:text-[18px]">{PRIVACY_STATEMENT}</blockquote>
      </div>
      <ul className="mt-5 grid gap-3 sm:grid-cols-3">
        {cols.map((c) => (
          <li key={c.title} className="rounded-xl bg-surface-2/60 p-3.5">
            <p className="flex items-center gap-2 text-[13.5px] font-semibold text-ink">
              <c.icon className={cn("size-4", c.tone)} aria-hidden />
              {c.title}
            </p>
            <p className="mt-1 text-[12.5px] leading-5 text-muted">{c.body}</p>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-[12.5px] leading-5 text-muted">
        Letters you mark <strong className="font-medium text-ink">“Keep private — no AI”</strong> are stored and searchable, but never sent to Claude.
      </p>
    </SettingsCard>
  );
}

function CallRow({ c, docTitle }: { c: LLMCallRecord; docTitle: (id: string) => string }) {
  const tokens = c.input_tokens + c.output_tokens;
  return (
    <tr className="align-top">
      <td className="whitespace-nowrap py-3 pl-5 pr-3 text-muted sm:pl-6">{formatDateTime(c.ts)}</td>
      <td className="py-3 pr-3">
        <span className="font-medium text-ink">{purposeLabel(c.purpose)}</span>
        <span className="block text-[12px] text-muted">{modelFamily(c.model)}</span>
      </td>
      <td className="py-3 pr-3">
        <span className="text-ink/85">{sentSummary(c, formatFileSize)}</span>
        {c.doc_ids.length ? (
          <span className="mt-0.5 block text-[12px]">
            {c.doc_ids.map((id, i) => (
              <span key={id}>
                {i ? ", " : ""}
                <Link to={`/documents/${id}`} className="text-accent hover:underline">
                  {docTitle(id)}
                </Link>
              </span>
            ))}
          </span>
        ) : null}
      </td>
      <td className="whitespace-nowrap py-3 pr-3 text-right tabular-nums text-ink/85">
        {formatCompact(tokens)}
        <span className="block text-[12px] text-muted">
          {formatCompact(c.input_tokens)} in · {formatCompact(c.output_tokens)} out
        </span>
      </td>
      <td className="whitespace-nowrap py-3 pr-5 text-right tabular-nums sm:pr-6">
        {c.cache_hit ? (
          <Badge tone="ok" icon={Zap}>
            Cache
          </Badge>
        ) : (
          <span className="text-ink">{formatUsd(c.cost_usd)}</span>
        )}
        {!c.ok ? (
          // the demo only replays recordings: a question it has none for isn't a failure
          c.backend === "replay" || /^no recorded response/i.test(c.error ?? "") ? (
            <span className="block text-[12px] text-muted">Not recorded (demo)</span>
          ) : (
            <span className="block text-[12px] text-danger-ink">Failed</span>
          )
        ) : null}
      </td>
    </tr>
  );
}

/** "Privacy & AI usage": the honest privacy statement, what was sent per call, totals, activity. */
export function PrivacySection() {
  const usage = useUsage();
  const activity = useActivity(60);
  const docs = useDocuments();
  const rows = useMemo(() => purposeRows(usage.data), [usage.data]);
  const titles = useMemo(() => new Map((docs.data ?? []).map((d) => [d.id, d.title ?? d.filename])), [docs.data]);
  const docTitle = (id: string) => titles.get(id) ?? "a letter";
  const u = usage.data;
  const rate = cacheRate(u);

  return (
    <section aria-labelledby="set-privacy">
      <SectionHeading id="set-privacy" title="Privacy & AI usage" description="Exactly what leaves this computer, when, and what it would cost on the API." />
      <div className="space-y-5">
        <Statement />

        <SettingsCard
          title="AI usage"
          id="set-usage"
          description="API-equivalent cost is what these calls would cost on Anthropic's API. With a Claude subscription you don't pay per call — it counts towards your plan's limits."
        >
          {usage.isPending ? (
            <div className="grid gap-3 sm:grid-cols-4" aria-busy="true">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 rounded-xl" />
              ))}
            </div>
          ) : !u || !u.calls ? (
            <EmptyState size="sm" variant="plain" illustration="clear" title="No calls to Claude yet" description="When Claude reads a letter or answers a question, you'll see it here." />
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Stat label="Calls to Claude" value={u.calls.toLocaleString("en-GB")} />
                <Stat label="From the cache" value={rate === null ? "—" : formatPercent(rate)} sub={`${u.cache_hits} calls not repeated`} />
                <Stat label="Tokens" value={formatCompact(u.input_tokens + u.output_tokens)} sub={`${formatCompact(u.input_tokens)} in · ${formatCompact(u.output_tokens)} out`} />
                <Stat label="API-equivalent cost" value={formatUsd(u.cost_usd)} sub="Not billed with a subscription" />
              </dl>

              <h4 className="mb-2 mt-6 text-[12.5px] font-semibold uppercase tracking-[0.07em] text-muted">Cost by purpose</h4>
              <Suspense fallback={<Skeleton className="h-60 w-full rounded-lg" />}>
                <UsageChart rows={rows} />
              </Suspense>
              <table className="sr-only">
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
            </>
          )}
        </SettingsCard>

        <section aria-labelledby="set-calls" className="card overflow-hidden">
          <div className="px-5 pb-3 pt-5 sm:px-6">
            <h3 id="set-calls" className="text-[15px] font-semibold text-ink">
              What was sent, call by call
            </h3>
            <p className="mt-1 text-[13.5px] text-muted">Only counts and sizes are logged — never the content itself.</p>
          </div>
          {usage.isPending ? (
            <SkeletonText lines={5} className="px-6 pb-6" />
          ) : u?.recent.length ? (
            <div className="overflow-x-auto scrollbar-thin">
              <table className="w-full min-w-[640px] text-left text-[13px]">
                <thead className="border-y border-line bg-surface-2/50 text-[12px] text-muted">
                  <tr>
                    <th scope="col" className="py-2 pl-5 pr-3 font-medium sm:pl-6">
                      When
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      For
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      What was sent
                    </th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">
                      Tokens
                    </th>
                    <th scope="col" className="py-2 pr-5 text-right font-medium sm:pr-6">
                      Cost
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {u.recent.map((c) => (
                    <CallRow key={c.id} c={c} docTitle={docTitle} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="px-6 pb-6 text-base text-muted">No calls yet.</p>
          )}
        </section>

        <SettingsCard title="Activity" id="set-activity" description="Everything Ordnung did on its own — reading letters, reviews, exports.">
          {activity.isPending ? (
            <SkeletonText lines={6} />
          ) : activity.data?.length ? (
            <ol className="relative space-y-0.5">
              {activity.data.map((a) => {
                const Icon = activityIcon(a.kind);
                const href = activityHref(a);
                const body = (
                  <>
                    <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
                      <Icon className="size-3.5" aria-hidden />
                    </span>
                    <span className="min-w-0 flex-1 text-[13.5px] leading-5 text-ink">{a.message}</span>
                    <time dateTime={a.ts} className="shrink-0 whitespace-nowrap text-[12px] text-muted">
                      {formatDateTime(a.ts)}
                    </time>
                  </>
                );
                return (
                  <li key={a.id}>
                    {href ? (
                      <Link to={href} className="-mx-2 flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-surface-2/70">
                        {body}
                      </Link>
                    ) : (
                      <div className="-mx-2 flex items-center gap-3 px-2 py-2">{body}</div>
                    )}
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="flex items-center gap-2 text-base text-muted">
              <Database className="size-4" aria-hidden /> Nothing yet.
            </p>
          )}
        </SettingsCard>
      </div>
    </section>
  );
}
