/**
 * Contracts page body (SPEC §14.5): fixed costs, "Decide by" callouts, the contracts-only life
 * lanes (term bars, hatched notice windows, send-by diamonds, today line) and a card per contract.
 * URL state: `?status=active|cancelled|ended|all` and `?contract=ID` (selects + scrolls to a card;
 * every in-app link uses it via `contractHref`). The older `?focus=ID` is accepted and rewritten.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { Lock, Plus, Signature, TriangleAlert } from "lucide-react";
import { useContracts, useParties } from "@/api/hooks";
import type { Contract, Lane, Party } from "@/api/types";
import { useAddLetters } from "@/components/shell/AddLetters";
import { PageHeader } from "@/components/shell/Page";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EmptyState } from "@/components/ui/EmptyState";
import { KindIcon } from "@/components/ui/KindBadge";
import { LoadError } from "@/components/ui/LoadError";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton, SkeletonCard } from "@/components/ui/Skeleton";
import { Tabs, type TabItem } from "@/components/ui/Tabs";
import { useTodayISO } from "@/lib/today";
import { plural, prefersReducedMotion } from "@/lib/utils";
import { formatMoney } from "@/lib/format";
import { LanesChart, defaultLaneRange, nextOnLane, type LaneSelection } from "@/features/lanes";
import { ContractCard } from "./ContractCard";
import { CostSummary, SUMMARY_GRID } from "./CostSummary";
import { DecideBy } from "./DecideBy";
import {
  contractLaneNote,
  contractLanes,
  contractMonthlyCost,
  decideBy,
  filterByStatus,
  fixedCosts,
  sortContracts,
  type StatusFilter,
} from "./model";

const STATUSES: StatusFilter[] = ["active", "cancelled", "ended", "all"];
const STATUS_LABEL: Record<StatusFilter, string> = { active: "Active", cancelled: "Cancelled", ended: "Ended", all: "All" };
const DESCRIPTION = "Every contract with what it costs, how it can end — in plain words — and the dates to act by.";

/**
 * Cards side by side as the content column allows (not the window: the sidebar takes its share),
 * each at least 22rem wide — and never wider than the column on a phone.
 */
const CARD_GRID = "grid grid-cols-[repeat(auto-fill,minmax(min(100%,22rem),1fr))] gap-4";

/** First run: no contract known yet — ask for the letter that has one. */
function FirstRun() {
  const { openPicker, uploading } = useAddLetters();
  return (
    <EmptyState
      illustration="contract"
      title="No contracts yet"
      // (the dash stays at the end of its line, never starts the next one)
      description={"Add a contract, a price change or a cancellation letter — Ordnung works out the notice period and the dates to act by."}
      action={
        <Button variant="primary" icon={Plus} onClick={openPicker} loading={uploading}>
          Add a contract letter
        </Button>
      }
    >
      <p className="mt-5 inline-flex items-center gap-1.5 text-sm text-muted">
        <Lock className="size-3.5 shrink-0" aria-hidden /> Your files stay on this computer.
      </p>
    </EmptyState>
  );
}

export function ContractsView() {
  const today = useTodayISO();
  const contractsQ = useContracts();
  const partiesQ = useParties();
  const [params, setParams] = useSearchParams();
  const rawStatus = params.get("status") as StatusFilter | null;
  const status: StatusFilter = rawStatus && STATUSES.includes(rawStatus) ? rawStatus : "active";
  const selectedId = params.get("contract") || params.get("focus");

  // `?focus=ID` (older links) → `?contract=ID`, so selecting another contract replaces it cleanly
  useEffect(() => {
    const focus = params.get("focus");
    if (!focus) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("focus");
        if (!next.get("contract")) next.set("contract", focus);
        return next;
      },
      { replace: true, preventScrollReset: true },
    );
  }, [params, setParams]);

  const all = useMemo(() => contractsQ.data ?? [], [contractsQ.data]);
  const partyById = useMemo(() => new Map<string, Party>((partiesQ.data ?? []).map((p) => [p.id, p])), [partiesQ.data]);
  const byId = useMemo(() => new Map(all.map((c) => [c.id, c])), [all]);
  const range = useMemo(() => defaultLaneRange(today), [today]);
  const shown = useMemo(() => sortContracts(filterByStatus(all, status), today), [all, status, today]);
  const lanes = useMemo(() => contractLanes(shown, range, today), [shown, range, today]);
  const costs = useMemo(() => fixedCosts(all), [all]);
  const decisions = useMemo(() => decideBy(all, today), [all, today]);
  const counts = useMemo(
    () => ({
      active: all.filter((c) => c.status === "active").length,
      cancelled: all.filter((c) => c.status === "cancelled").length,
      ended: all.filter((c) => c.status === "ended").length,
      all: all.length,
    }),
    [all],
  );
  // a tab that would show nothing isn't offered ("Cancelled 0") — unless a link asked for it
  const tabs: TabItem<StatusFilter>[] = STATUSES.filter((s) => s === "active" || s === "all" || s === status || counts[s] > 0).map((s) => ({
    value: s,
    label: STATUS_LABEL[s],
    count: counts[s],
  }));

  const setStatus = (s: StatusFilter) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (s === "active") next.delete("status");
        else next.set("status", s);
        return next;
      },
      { replace: true, preventScrollReset: true },
    );

  const select = useCallback(
    (id: string) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("contract", id);
          return next;
        },
        { replace: true, preventScrollReset: true },
      ),
    [setParams],
  );

  // A selected contract (from the chart, Today's Ideas or the Timeline) scrolls into view; one
  // picked in the chart also takes the keyboard focus along (it would stay on an off-screen bar).
  const selectedShown = Boolean(selectedId && shown.some((c) => c.id === selectedId));
  /** the contract just picked in the chart, until its card has the focus */
  const focusNext = useRef<string | null>(null);
  /** counts picks, so picking the selected contract again scrolls back to it */
  const [picks, setPicks] = useState(0);
  useEffect(() => {
    if (!selectedId || !selectedShown) return;
    const el = document.getElementById(`contract-${selectedId}`);
    el?.scrollIntoView?.({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
    if (focusNext.current === selectedId) {
      focusNext.current = null;
      el?.focus({ preventScroll: true });
    }
  }, [selectedId, selectedShown, picks]);
  // …even when it is filtered out by the status tabs (show it rather than nothing).
  const selected = selectedId ? byId.get(selectedId) : undefined;
  const hiddenSelected = selected && !selectedShown ? selected : null;

  const describeLane = useCallback(
    (lane: Lane) => {
      const c = byId.get(lane.id);
      if (!c) return undefined;
      const icon = <KindIcon category={c.category} size="sm" />;
      const note = contractLaneNote(c, today);
      if (note) {
        return {
          icon,
          sublabel:
            note.tone === "warn" ? (
              <span className="text-warn-ink">
                <TriangleAlert className="mr-1 inline size-3 align-[-2px]" aria-hidden />
                {note.text}
              </span>
            ) : (
              <span className="text-muted">{note.text}</span>
            ),
        };
      }
      if (nextOnLane(lane, today) !== null) return { icon };
      const monthly = contractMonthlyCost(c);
      return {
        icon,
        sublabel: (
          <span className="text-muted">{monthly !== null ? `${formatMoney(monthly)} per month` : partyById.get(c.party_id ?? "")?.name ?? "No dates coming up"}</span>
        ),
      };
    },
    [byId, today, partyById],
  );

  const onSelect = useCallback(
    (sel: LaneSelection) => {
      focusNext.current = sel.lane.id;
      setPicks((n) => n + 1);
      select(sel.lane.id);
    },
    [select],
  );

  // A retry of a failed load may start over as "pending": remember the error, so the message stays
  // on screen, worded the same, while "Try again" runs.
  const loaded = Boolean(contractsQ.data);
  const [lastError, setLastError] = useState<unknown>(null);
  if (contractsQ.error && contractsQ.error !== lastError) setLastError(contractsQ.error);
  else if (loaded && lastError !== null) setLastError(null);
  const failed = !loaded && (contractsQ.isError || lastError !== null);
  const loading = !loaded && !failed;

  if (failed) {
    return (
      <>
        <PageHeader title="Contracts" description={DESCRIPTION} />
        <LoadError what="your contracts" error={contractsQ.error ?? lastError} onRetry={() => void contractsQ.refetch()} retrying={contractsQ.isFetching} />
      </>
    );
  }

  if (loaded && !all.length) {
    return (
      <>
        <PageHeader title="Contracts" description={DESCRIPTION} />
        <FirstRun />
      </>
    );
  }

  const emptyFilter = !loading && !shown.length;
  const panel = (
    <>
      {hiddenSelected ? (
        <Callout tone="info" className="mb-4" title={`${hiddenSelected.name} isn't in this list`}>
          It is {hiddenSelected.status === "active" ? "active" : hiddenSelected.status === "cancelled" ? "cancelled" : "ended"}.{" "}
          <Button variant="link" size="sm" onClick={() => setStatus("all")}>
            Show all contracts
          </Button>
        </Callout>
      ) : null}
      {emptyFilter ? (
        // nothing to draw: one empty state, not an empty chart with its legend and disclaimer
        <EmptyState
          headingLevel={3}
          illustration="contract"
          title={`No ${status === "all" ? "" : `${status} `}contracts`}
          description={status === "active" ? "Every contract in your letters is cancelled or has ended." : "Contracts you cancel, or that run out, show up here."}
          action={
            <Button variant="secondary" onClick={() => setStatus(status === "active" || !counts.active ? "all" : "active")}>
              {status === "active" || !counts.active ? "Show all contracts" : "Show active contracts"}
            </Button>
          }
        />
      ) : (
        <>
          <LanesChart
            className="mb-6"
            lanes={lanes}
            from={range.from}
            to={range.to}
            today={today}
            loading={loading}
            labelHeading="Contract"
            ariaLabel="Contract terms and notice windows"
            title="Terms & notice windows"
            headingLevel={3}
            description="When each contract can end — and the hatched window in which to cancel."
            describeLane={describeLane}
            onSelect={onSelect}
            resolveTarget={() => ({ hint: "Shows the contract below" })}
            footer={<Disclaimer />}
          />
          {loading ? (
            <div className={CARD_GRID} aria-hidden>
              {[0, 1, 2].map((i) => (
                <SkeletonCard key={i} lines={4} />
              ))}
            </div>
          ) : (
            <ul className={CARD_GRID} aria-label={plural(shown.length, "contract")}>
              {shown.map((c: Contract) => (
                <li key={c.id} className="flex min-w-0">
                  <ContractCard contract={c} party={c.party_id ? partyById.get(c.party_id) : undefined} today={today} selected={c.id === selectedId} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </>
  );

  return (
    <>
      <PageHeader title="Contracts" description={DESCRIPTION} />

      {loading ? (
        <div className="@container mb-8" aria-hidden>
          <div className={`${SUMMARY_GRID} gap-3`}>
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-24 rounded-[var(--radius-card)]" />
            ))}
          </div>
        </div>
      ) : (
        <CostSummary costs={costs} active={counts.active} inactive={counts.cancelled + counts.ended} next={decisions[0] ?? null} today={today} />
      )}

      <DecideBy contracts={decisions} partyById={partyById} today={today} />

      <section aria-labelledby="all-contracts-title" aria-busy={loading || undefined}>
        <SectionHeader id="all-contracts-title" icon={Signature} title="Your contracts" count={loading ? undefined : shown.length} />
        {loading ? (
          // no tabs (and no "Active 0") until the counts are known
          <div>{panel}</div>
        ) : (
          <>
            {/* their own row: on a phone the tabs share its whole width */}
            <Tabs<StatusFilter> id="contract-status" label="Show contracts" variant="pill" fill value={status} onChange={setStatus} items={tabs} className="mb-4" />
            {/* the filtered chart and cards are the panel of the "Show contracts" tabs */}
            <div role="tabpanel" id={`contract-status-panel-${status}`} aria-labelledby={`contract-status-tab-${status}`}>
              {panel}
            </div>
          </>
        )}
      </section>
    </>
  );
}
