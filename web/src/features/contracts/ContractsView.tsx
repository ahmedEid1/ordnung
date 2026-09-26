/**
 * Contracts page body (SPEC §14.5): fixed costs, "Decide by" callouts, the contracts-only life
 * lanes (term bars, hatched notice windows, send-by diamonds, today line) and a card per contract.
 * URL state: `?status=active|cancelled|ended|all` and `?contract=ID` (selects + scrolls to a card;
 * every in-app link uses it via `contractHref`). The older `?focus=ID` is accepted and rewritten.
 */
import { useCallback, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router";
import { Signature } from "lucide-react";
import { useContracts, useParties } from "@/api/hooks";
import type { Contract, Lane, Party } from "@/api/types";
import { PageHeader } from "@/components/shell/Page";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EmptyState } from "@/components/ui/EmptyState";
import { KindIcon } from "@/components/ui/KindBadge";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton, SkeletonCard } from "@/components/ui/Skeleton";
import { Tabs } from "@/components/ui/Tabs";
import { useTodayISO } from "@/lib/today";
import { plural, prefersReducedMotion } from "@/lib/utils";
import { formatMoney } from "@/lib/format";
import { LanesChart, defaultLaneRange, nextOnLane, type LaneSelection } from "@/features/lanes";
import { ContractCard } from "./ContractCard";
import { CostSummary } from "./CostSummary";
import { DecideBy } from "./DecideBy";
import { contractLanes, contractMonthlyCost, decideBy, filterByStatus, fixedCosts, sortContracts, type StatusFilter } from "./model";

const STATUSES: StatusFilter[] = ["active", "cancelled", "ended", "all"];

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

  // A selected contract (from the chart, Today's Ideas or the Timeline) scrolls into view.
  const selectedShown = Boolean(selectedId && shown.some((c) => c.id === selectedId));
  useEffect(() => {
    if (!selectedId || !selectedShown) return;
    const el = document.getElementById(`contract-${selectedId}`);
    el?.scrollIntoView?.({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [selectedId, selectedShown]);
  // …even when it is filtered out by the status tabs (show it rather than nothing).
  const selected = selectedId ? byId.get(selectedId) : undefined;
  const hiddenSelected = selected && !selectedShown ? selected : null;

  const describeLane = useCallback(
    (lane: Lane) => {
      const c = byId.get(lane.id);
      if (!c) return undefined;
      const monthly = contractMonthlyCost(c);
      const hasNext = nextOnLane(lane, today) !== null;
      return {
        icon: <KindIcon category={c.category} size="sm" />,
        sublabel: hasNext ? undefined : (
          <span className="text-muted">{monthly !== null ? `${formatMoney(monthly)} per month` : partyById.get(c.party_id ?? "")?.name ?? "No dates coming up"}</span>
        ),
      };
    },
    [byId, today, partyById],
  );

  const onSelect = useCallback((sel: LaneSelection) => select(sel.lane.id), [select]);

  const loading = contractsQ.isPending;

  return (
    <>
      <PageHeader
        title="Contracts"
        description="Every contract with what it costs, how it can end — in plain words — and the dates to act by."
      />

      {contractsQ.isError && !contractsQ.data ? (
        <Callout
          tone="danger"
          title="Couldn't load your contracts"
          className="mb-6"
          action={
            <Button size="sm" onClick={() => void contractsQ.refetch()}>
              Try again
            </Button>
          }
        >
          Your letters are safe — the app just couldn't reach its local server.
        </Callout>
      ) : null}

      {loading ? (
        <div className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-4" aria-hidden>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 rounded-[var(--radius-card)]" />
          ))}
        </div>
      ) : all.length ? (
        <CostSummary costs={costs} active={counts.active} inactive={counts.cancelled + counts.ended} next={decisions[0] ?? null} today={today} />
      ) : null}

      <DecideBy contracts={decisions} partyById={partyById} today={today} />

      {!loading && !all.length ? (
        <EmptyState
          illustration="contract"
          title="No contracts yet"
          description="When you add a contract, price change or cancellation letter, Ordnung works out notice periods and the dates to act by."
        />
      ) : (
        <section aria-labelledby="all-contracts-title">
          <SectionHeader
            id="all-contracts-title"
            icon={Signature}
            title="Your contracts"
            count={loading ? undefined : shown.length}
            action={
              <Tabs<StatusFilter>
                id="contract-status"
                label="Show contracts"
                variant="pill"
                value={status}
                onChange={setStatus}
                items={[
                  { value: "active", label: "Active", count: counts.active },
                  { value: "cancelled", label: "Cancelled", count: counts.cancelled },
                  { value: "ended", label: "Ended", count: counts.ended },
                  { value: "all", label: "All", count: counts.all },
                ]}
              />
            }
            className="flex-wrap"
          />

          {/* the filtered chart and cards are the panel of the "Show contracts" tabs */}
          <div role="tabpanel" id={`contract-status-panel-${status}`} aria-labelledby={`contract-status-tab-${status}`}>
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
              description="When each contract can end — and the hatched window in which to cancel."
              describeLane={describeLane}
              onSelect={onSelect}
              resolveTarget={() => ({ hint: "Shows the contract below" })}
              empty={
                <EmptyState
                  size="sm"
                  variant="plain"
                  headingLevel={3}
                  illustration="search"
                  title={`No ${status === "all" ? "" : `${status} `}contracts`}
                  description="Try another filter."
                />
              }
              footer={<Disclaimer />}
            />

            {loading ? (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {[0, 1, 2].map((i) => (
                  <SkeletonCard key={i} lines={4} />
                ))}
              </div>
            ) : (
              <>
                {hiddenSelected ? (
                  <Callout tone="info" className="mb-4" title={`${hiddenSelected.name} isn't in this list`}>
                    It is {hiddenSelected.status === "active" ? "active" : hiddenSelected.status === "cancelled" ? "cancelled" : "ended"}.{" "}
                    <Button variant="link" size="sm" onClick={() => setStatus("all")}>
                      Show all contracts
                    </Button>
                  </Callout>
                ) : null}
                {shown.length ? (
                  <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label={plural(shown.length, "contract")}>
                    {shown.map((c: Contract) => (
                      <li key={c.id} className="flex">
                        <ContractCard
                          contract={c}
                          party={c.party_id ? partyById.get(c.party_id) : undefined}
                          today={today}
                          selected={c.id === selectedId}
                        />
                      </li>
                    ))}
                  </ul>
                ) : null}
              </>
            )}
          </div>
        </section>
      )}
    </>
  );
}
