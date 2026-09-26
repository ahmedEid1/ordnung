/**
 * "I read 3 letters: 1 deadline, 55 €/month fixed costs, 1 needs you now, 1 possible scam" —
 * the recap after several letters were read at once, with links to where each thing lives, and
 * every letter of the batch (the ones that couldn't be read too: "I read 2 of 3 letters").
 */
import type { ReactNode, RefObject } from "react";
import { Link } from "react-router";
import { useQueries } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, Hourglass, Repeat, ShieldAlert, Signature, TriangleAlert, type LucideIcon } from "lucide-react";
import { api } from "@/api/endpoints";
import { qk } from "@/api/hooks";
import type { DocumentDetail } from "@/api/types";
import { cn } from "@/lib/utils";
import { formatMoney } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { TONES, type Tone } from "@/lib/copy";
import { Button } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { Dialog } from "@/components/ui/Dialog";
import { KindIcon } from "@/components/ui/KindBadge";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusPill } from "@/components/ui/StatusPill";
import { dueSoon, recapFindings, recapTitle, summarizeBatch } from "./recap";

/** A lone tile in the last row of the two-column grid takes the whole row. */
const TILE_GRID = "grid gap-2.5 sm:grid-cols-2 sm:[&>*:last-child:nth-child(odd)]:col-span-2";

function Stat({ to, icon: Icon, tone, value, label, onNavigate }: { to: string; icon: LucideIcon; tone: Tone; value: ReactNode; label: string; onNavigate: () => void }) {
  const t = TONES[tone];
  return (
    <li>
      <Link
        to={to}
        onClick={onNavigate}
        className="group flex h-full items-center gap-3 rounded-xl border border-line bg-surface px-3.5 py-3 transition-[border-color,box-shadow] hover:border-line-strong hover:shadow-[var(--shadow-card)]"
      >
        <span className={cn("grid size-9 shrink-0 place-items-center rounded-lg", t.soft, t.icon)}>
          <Icon className="size-[18px]" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[18px] font-semibold leading-tight tabular-nums text-ink">{value}</span>
          <span className="block text-sm leading-5 text-muted">{label}</span>
        </span>
        <ArrowRight
          className="size-4 shrink-0 text-muted opacity-60 transition-[opacity,transform] group-hover:translate-x-0.5 group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none"
          aria-hidden
        />
      </Link>
    </li>
  );
}

function findingsText(parts: string[]): string {
  if (!parts.length) return "Nothing needs you right now — everything is filed.";
  const list = parts.length === 1 ? parts[0]! : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  return `Here's what I found: ${list}.`;
}

export function BatchRecapDialog({
  docIds,
  failedIds = [],
  onClose,
  returnFocus,
}: {
  /** Every letter of the batch (null: closed). */
  docIds: string[] | null;
  /** The ones that couldn't be read. */
  failedIds?: string[];
  onClose: () => void;
  /** Where focus goes on close — the tray and its buttons are gone by then. */
  returnFocus?: RefObject<HTMLElement | null>;
}) {
  const today = useTodayISO();
  const ids = docIds ?? [];
  const results = useQueries({
    queries: ids.map((id) => ({ queryKey: qk.documents.detail(id), queryFn: () => api.document(id), staleTime: 0 })),
  });
  const loading = results.some((r) => r.isPending);
  const details = results.map((r) => r.data).filter((d): d is DocumentDetail => Boolean(d));
  const recap = !loading ? summarizeBatch(details, today) : null;
  const failed = failedIds.filter((id) => ids.includes(id)).length;

  return (
    <Dialog
      open={Boolean(docIds)}
      onClose={onClose}
      size="lg"
      returnFocus={returnFocus}
      title={recapTitle(ids.length, failed)}
      description={recap ? findingsText(recapFindings(recap)) : "Putting it all together…"}
      footer={
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      }
    >
      {!recap ? (
        <div className={TILE_GRID} aria-hidden>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[62px] rounded-xl" />
          ))}
        </div>
      ) : (
        <div aria-live="polite">
          <ul className={TILE_GRID}>
            {recap.scams ? (
              <Stat
                to={recap.scamDocId ? `/documents/${recap.scamDocId}` : "/inbox?filter=check"}
                icon={ShieldAlert}
                tone="danger"
                value={recap.scams}
                label={recap.scams === 1 ? "possible scam — don't pay" : "possible scams — don't pay"}
                onNavigate={onClose}
              />
            ) : null}
            {recap.needYou ? (
              <Stat to="/inbox?filter=check" icon={TriangleAlert} tone="warn" value={recap.needYou} label={recap.needYou === 1 ? "needs you now" : "need you now"} onNavigate={onClose} />
            ) : null}
            {recap.dueSoon ? (
              <Stat to="/timeline" icon={CalendarClock} tone="deadline" value={recap.dueSoon} label="due within 2 weeks" onNavigate={onClose} />
            ) : null}
            {recap.deadlines ? (
              <Stat to="/timeline" icon={Hourglass} tone="deadline" value={recap.deadlines} label={recap.deadlines === 1 ? "deadline on your timeline" : "deadlines on your timeline"} onNavigate={onClose} />
            ) : null}
            {recap.contracts ? (
              <Stat to="/contracts" icon={Signature} tone="contract" value={recap.contracts} label={recap.contracts === 1 ? "contract" : "contracts"} onNavigate={onClose} />
            ) : null}
            {recap.fixedCostsMonthly > 0 ? (
              <Stat
                to="/contracts"
                icon={Repeat}
                tone="payment"
                value={formatMoney(recap.fixedCostsMonthly, { decimals: "auto" })}
                label="per month in fixed costs"
                onNavigate={onClose}
              />
            ) : null}
          </ul>
          <h3 className="eyebrow mb-2 mt-5">The letters</h3>
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line">
            {details.map((d) => {
              const title = d.document.title ?? d.document.filename;
              const check = d.document.status === "needs_review" || d.document.status === "failed";
              const due = check ? null : dueSoon(d, today);
              return (
                <li key={d.document.id}>
                  <Link
                    to={`/documents/${d.document.id}`}
                    onClick={onClose}
                    // the list clips its corners: the focus ring goes inside the row
                    className="flex items-center gap-3 px-3.5 py-2.5 transition-colors hover:bg-surface-2/60 focus-visible:-outline-offset-2"
                  >
                    <KindIcon docKind={d.document.kind} size="sm" />
                    <span className="line-clamp-2 min-w-0 flex-1 text-pretty text-base font-medium leading-5 text-ink [overflow-wrap:anywhere]" title={title}>
                      {title}
                    </span>
                    {check ? <StatusPill of="document" status={d.document.status} /> : null}
                    {due ? <Countdown date={due} variant="pill" /> : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Dialog>
  );
}
