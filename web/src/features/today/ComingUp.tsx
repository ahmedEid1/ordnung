import { useMemo } from "react";
import { Link } from "react-router";
import { motion } from "motion/react";
import { ArrowRight } from "lucide-react";
import type { Party } from "@/api/types";
import { DateLeaf } from "@/components/ui/DateLeaf";
import { KindIcon } from "@/components/ui/KindBadge";
import { Money } from "@/components/ui/Money";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { formatMoney, formatTotals } from "@/lib/format";
import { fadeUp } from "./motion";
import { comingUpMeta } from "./helpers";
import { groupByWeek, isOutgoingPayment, type TodayAction } from "./selection";
import { actionHref } from "./useTodayData";

/**
 * One date: the calendar leaf, then the title (up to two lines) and what/who (up to two lines),
 * each with its full text on hover. A roomy card adds the kind icon and puts the amount in its
 * own column; a phone-sized one leads the second line with the amount instead, so the title keeps
 * the width.
 */
function Row({ action, party }: { action: TodayAction; party: Party | undefined }) {
  const meta = comingUpMeta(action, party);
  const money = action.amount ? formatMoney(action.amount, { currency: action.currency }) : null;
  const full = [money, meta].filter(Boolean).join(" · ");
  return (
    <li>
      <Link
        to={actionHref(action)}
        data-part="coming-row"
        className="group -mx-2 flex items-center gap-3 rounded-xl px-2 py-2 outline-none transition-colors hover:bg-surface-2/80 focus-visible:ring-2 focus-visible:ring-accent"
      >
        <DateLeaf date={action.actionDate} size="md" tone={action.daysLeft < 0 ? "danger" : "default"} />
        <span className="hidden @md:contents">
          {action.kind === "contract" ? (
            <KindIcon category={action.contract?.category ?? "other"} size="sm" />
          ) : (
            <KindIcon kind={action.kind} direction={action.item?.direction} size="sm" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span title={action.title} className="line-clamp-2 break-words text-base font-medium leading-snug text-ink">
            {action.title}
          </span>
          {full ? (
            <span title={full} data-part="meta" className="mt-0.5 line-clamp-2 break-words text-sm leading-snug text-muted">
              {money ? (
                <span className="font-medium tabular-nums text-ink @md:hidden">
                  {money}
                  {meta ? <span className="font-normal text-muted"> · </span> : null}
                </span>
              ) : null}
              {meta}
            </span>
          ) : null}
        </span>
        {action.amount ? <Money amount={action.amount} currency={action.currency} className="hidden shrink-0 text-base @md:inline" /> : null}
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
  const { groups, anyInWindow } = useMemo(() => {
    const entry = (a: TodayAction) => ({ date: a.actionDate, amount: a.amount, currency: a.currency, outgoing: isOutgoingPayment(a), action: a });
    const listed = groupByWeek(actions.map(entry), today, 30);
    if (!all) return { groups: listed, anyInWindow: listed.length > 0 };
    const allGroups = groupByWeek(all.map(entry), today, 30);
    const totals = new Map(allGroups.map((g) => [g.key, g.totals]));
    return { groups: listed.map((g) => ({ ...g, totals: totals.get(g.key) ?? g.totals })), anyInWindow: allGroups.length > 0 };
  }, [actions, all, today]);
  const count = groups.reduce((n, g) => n + g.entries.length, 0);

  return (
    <motion.section variants={fadeUp} aria-labelledby="coming-up-title">
      <SectionHeader
        id="coming-up-title"
        title="Coming up · next 30 days"
        action={
          <Link
            to="/timeline"
            // 24 px tall to tap, without making the header row taller (the side cards line up with it)
            className="-my-[3px] inline-flex items-center gap-1 rounded py-[3px] text-[13px] font-medium text-accent hover:underline"
          >
            Timeline <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        }
      />
      {count ? (
        <div className="card @container divide-y divide-line">
          {groups.map((g) => (
            <div key={g.key} className="px-4 py-3 sm:px-5">
              {/* the week's total goes to its own line when both don't fit (small phones) */}
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                <h3 className="text-sm font-semibold text-ink">
                  {g.label}
                  {g.range ? (
                    <>
                      {" "}
                      <span className="ml-1 whitespace-nowrap font-normal text-muted">{g.range}</span>
                    </>
                  ) : null}
                </h3>
                {Object.keys(g.totals).length ? (
                  <p className="text-xs text-muted">
                    To pay <span className="font-medium tabular-nums text-ink">{formatTotals(g.totals)}</span>
                  </p>
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
        <p className="card px-5 py-6 text-center text-base text-muted">
          {/* "else" only when Top 3 has something in these 30 days */}
          {anyInWindow ? "Nothing else in the next 30 days." : "Nothing in the next 30 days."}
        </p>
      )}
    </motion.section>
  );
}
