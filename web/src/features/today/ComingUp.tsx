import { useMemo } from "react";
import { Link } from "react-router";
import { motion } from "motion/react";
import { ArrowRight } from "lucide-react";
import type { Party } from "@/api/types";
import { KindIcon } from "@/components/ui/KindBadge";
import { Money } from "@/components/ui/Money";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { formatTime, formatTotals } from "@/lib/format";
import { cn } from "@/lib/utils";
import { format, parseISO } from "date-fns";
import { fadeUp } from "./motion";
import { groupByWeek, isOutgoingPayment, type TodayAction } from "./selection";
import { actionHref } from "./useTodayData";

const ROLE_LABEL: Partial<Record<TodayAction["dateRole"], string>> = {
  send_by: "Send by",
  transfer_by: "Transfer by",
  collected: "Collected",
  decide_by: "Decide by",
  expires: "Expires",
};

/** Calendar-leaf date: "THU" over a big "8". */
function DateLeaf({ date, overdue }: { date: string; overdue: boolean }) {
  const d = parseISO(date);
  return (
    <time
      dateTime={date}
      className={cn(
        "flex w-11 shrink-0 flex-col items-center rounded-lg border py-1 leading-none",
        overdue ? "border-danger/30 bg-danger-soft text-danger-ink" : "border-line bg-surface-2/70 text-ink",
      )}
    >
      <span className={cn("text-[10px] font-semibold uppercase tracking-[0.08em]", overdue ? "text-danger-ink" : "text-muted")}>{format(d, "EEE")}</span>
      <span className="display mt-0.5 text-[18px] font-semibold tabular-nums">{format(d, "d")}</span>
      <span className="sr-only">{format(d, "MMMM")}</span>
    </time>
  );
}

function Row({ action, party }: { action: TodayAction; party: Party | undefined }) {
  const role = ROLE_LABEL[action.dateRole];
  const meta = [
    role ? `${role} ${format(parseISO(action.actionDate), "EEE d MMM")}` : null,
    action.time ? formatTime(action.time) : null,
    party?.name ?? null,
  ].filter(Boolean);
  return (
    <li>
      <Link
        to={actionHref(action)}
        className="group -mx-2 flex items-center gap-3 rounded-xl px-2 py-2 outline-none transition-colors hover:bg-surface-2/80 focus-visible:ring-2 focus-visible:ring-accent"
      >
        <DateLeaf date={action.actionDate} overdue={action.daysLeft < 0} />
        {action.kind === "contract" ? <KindIcon category={action.contract?.category ?? "other"} size="sm" /> : <KindIcon kind={action.kind} size="sm" />}
        <span className="min-w-0 flex-1">
          <span className="line-clamp-2 text-[14px] font-medium leading-snug text-ink sm:line-clamp-1">{action.title}</span>
          {meta.length ? <span className="block truncate text-[12.5px] text-muted">{meta.join(" · ")}</span> : null}
        </span>
        {action.amount ? <Money amount={action.amount} currency={action.currency} className="text-[13.5px]" /> : null}
      </Link>
    </li>
  );
}

/**
 * "Coming up · next 30 days": everything not in Top 3, grouped by week (Monday first), with
 * kind icons, amounts and a payment total per week.
 */
export function ComingUp({
  actions,
  all,
  partyById,
  today,
}: {
  actions: TodayAction[];
  /** Every action, Top 3 included — the week's "To pay" counts those payments too. */
  all?: TodayAction[];
  partyById: Map<string, Party>;
  today: string;
}) {
  const groups = useMemo(() => {
    const entry = (a: TodayAction) => ({ date: a.actionDate, amount: a.amount, currency: a.currency, outgoing: isOutgoingPayment(a), action: a });
    const listed = groupByWeek(actions.map(entry), today, 30);
    if (!all) return listed;
    const totals = new Map(groupByWeek(all.map(entry), today, 30).map((g) => [g.key, g.totals]));
    return listed.map((g) => ({ ...g, totals: totals.get(g.key) ?? g.totals }));
  }, [actions, all, today]);
  const count = groups.reduce((n, g) => n + g.entries.length, 0);

  return (
    <motion.section variants={fadeUp} aria-labelledby="coming-up-title">
      <SectionHeader
        id="coming-up-title"
        title="Coming up · next 30 days"
        action={
          <Link to="/timeline" className="inline-flex items-center gap-1 rounded text-[13px] font-medium text-accent hover:underline">
            Timeline <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        }
      />
      {count ? (
        <div className="card divide-y divide-line">
          {groups.map((g) => (
            <div key={g.key} className="px-4 py-3 sm:px-5">
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <h3 className="text-[13px] font-semibold text-ink">
                  {g.label}
                  {g.range ? <span className="ml-2 inline-block whitespace-nowrap font-normal text-muted">{g.range}</span> : null}
                </h3>
                {Object.keys(g.totals).length ? (
                  <span className="shrink-0 text-[12px] text-muted">
                    To pay <span className="font-medium tabular-nums text-ink">{formatTotals(g.totals)}</span>
                  </span>
                ) : null}
              </div>
              <ul>
                {g.entries.map((e) => (
                  <Row key={e.action.key} action={e.action} party={e.action.partyId ? partyById.get(e.action.partyId) : undefined} />
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : (
        <p className="card px-5 py-6 text-center text-sm text-muted">Nothing else in the next 30 days.</p>
      )}
    </motion.section>
  );
}
