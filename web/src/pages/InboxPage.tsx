import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { FileUp, Lock, Plus } from "lucide-react";
import type { DocumentKind } from "@/api/types";
import { useDocuments, useItems, useParties } from "@/api/hooks";
import { dismissJob } from "@/api/sse";
import { useDebounced } from "@/lib/hooks";
import { useTodayISO } from "@/lib/today";
import { Page, PageHeader } from "@/components/shell/Page";
import { useAddLetters } from "@/components/shell/AddLetters";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingLabel, SkeletonText, Skeleton } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { MailTray } from "@/features/inbox/MailTray";
import { LettersList } from "@/features/inbox/LettersList";
import { InboxToolbar } from "@/features/inbox/InboxToolbar";
import { BatchRecapDialog } from "@/features/inbox/BatchRecap";
import { useReadingBatch } from "@/features/inbox/useReadingBatch";
import { filterCounts, filterDocuments, groupLetters, kindOptions, openItemsByDoc, parseFilter, type InboxFilter } from "@/features/inbox/filters";

/** `/inbox` — every letter, filters, search, the demo's New-mail tray and the batch recap. */
export default function InboxPage() {
  const navigate = useNavigate();
  const today = useTodayISO();
  const { openPicker } = useAddLetters();
  const [params, setParams] = useSearchParams();
  const filter = parseFilter(params.get("filter"));
  const kind = (params.get("kind") || null) as DocumentKind | null;
  // "See all letters matching …" in the top-bar search opens /inbox?q=…: the words move into the
  // search field (and out of the URL, so the field stays the one place the search lives)
  const urlQuery = params.get("q");
  const [query, setQuery] = useState(urlQuery ?? "");
  if (urlQuery !== null && urlQuery !== query) setQuery(urlQuery);
  useEffect(() => {
    if (urlQuery === null) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("q");
        return next;
      },
      { replace: true, preventScrollReset: true },
    );
  }, [urlQuery, setParams]);
  const q = useDebounced(query.trim(), 200);
  const searching = q.length >= 2;

  const all = useDocuments();
  const search = useDocuments({ q }, { enabled: searching });
  const items = useItems({ status: "open" });
  const parties = useParties();

  // ---- live reading: one New-mail letter → open it; several → recap -----------------------
  const fromTray = useRef(new Set<string>());
  const [recap, setRecap] = useState<string[] | null>(null);
  useReadingBatch(
    useCallback(
      (ids: string[], failed: string[]) => {
        const ok = ids.filter((id) => !failed.includes(id));
        if (ids.length > 1) {
          setRecap(ok);
          ok.forEach((id) => dismissJob(id));
        } else if (ok.length === 1 && fromTray.current.has(ok[0]!)) {
          dismissJob(ok[0]!);
          navigate(`/documents/${ok[0]}`);
        }
        if (failed.length) toast.error(failed.length === 1 ? "One letter couldn't be read" : `${failed.length} letters couldn't be read`);
      },
      [navigate],
    ),
  );

  const setParam = (key: string, value: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true, preventScrollReset: true },
    );

  const docs = useMemo(() => all.data ?? [], [all.data]);
  const counts = useMemo(() => filterCounts(docs), [docs]);
  const kinds = useMemo(() => kindOptions(docs), [docs]);
  const partyMap = useMemo(() => new Map((parties.data ?? []).map((p) => [p.id, p])), [parties.data]);
  const openMap = useMemo(() => openItemsByDoc(items.data ?? [], today), [items.data, today]);
  const visible = useMemo(
    () => filterDocuments(searching ? (search.data ?? []) : docs, { filter, kind }),
    [searching, search.data, docs, filter, kind],
  );
  const groups = useMemo(() => groupLetters(visible, today), [visible, today]);
  const filtered = filter !== "all" || Boolean(kind) || searching;
  const clearAll = () => {
    setQuery("");
    setParams(new URLSearchParams(), { replace: true });
  };

  return (
    <Page title="Inbox">
      <PageHeader
        title="Inbox"
        description="Every letter you added — read, explained and filed, with the sentence behind every date."
      />

      <MailTray onOpened={(ids) => ids.forEach((id) => fromTray.current.add(id))} />

      {all.isPending ? (
        <div aria-busy="true">
          <LoadingLabel>Loading your letters…</LoadingLabel>
          <Skeleton className="mb-6 h-10 w-80 rounded-xl" />
          <div className="card divide-y divide-line">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="flex items-center gap-3.5 px-5 py-3.5">
                <Skeleton className="h-[54px] w-10 rounded-[4px]" />
                <SkeletonText lines={2} className="flex-1" />
              </div>
            ))}
          </div>
        </div>
      ) : !docs.length ? (
        <EmptyState
          illustration="inbox"
          title="No letters yet"
          description="Add a PDF or a phone photo of a letter. Ordnung reads it with your own Claude, explains it and files every date and amount."
          action={
            <Button variant="primary" icon={Plus} onClick={openPicker}>
              Add letters
            </Button>
          }
        />
      ) : (
        <>
          <InboxToolbar
            filter={filter}
            onFilter={(f: InboxFilter) => setParam("filter", f === "all" ? null : f)}
            counts={counts}
            kind={kind}
            onKind={(k) => setParam("kind", k)}
            kinds={kinds}
            query={query}
            onQuery={setQuery}
          />
          <div role="tabpanel" id={`inbox-filter-panel-${filter}`} aria-labelledby={`inbox-filter-tab-${filter}`} aria-busy={searching && search.isFetching}>
            {groups.length ? (
              <LettersList groups={groups} parties={partyMap} open={openMap} />
            ) : searching && search.isPending ? (
              <p className="px-1 text-base text-muted">Searching…</p>
            ) : filter === "check" && !kind && !searching ? (
              <EmptyState
                size="sm"
                illustration="clear"
                title="Nothing to check"
                description="Every date and amount was found in its letter. Ordnung asks here when something doesn't add up."
              />
            ) : (
              <EmptyState
                size="sm"
                illustration="search"
                title={searching ? `No letters match “${q}”` : "No letters here"}
                description={filtered ? "Try another filter or search word." : undefined}
                action={
                  filtered ? (
                    <Button size="sm" onClick={clearAll}>
                      Clear filters
                    </Button>
                  ) : undefined
                }
              />
            )}
          </div>

          <button
            type="button"
            onClick={openPicker}
            className="mt-8 flex w-full items-center gap-3 rounded-2xl border border-dashed border-line-strong px-5 py-4 text-left transition-colors hover:border-accent/60 hover:bg-accent-soft/40"
          >
            <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
              <FileUp className="size-5" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[14px] font-medium text-ink">Drop letters anywhere on this page, or choose files</span>
              <span className="mt-0.5 flex items-center gap-1.5 text-[12.5px] text-muted">
                <Lock className="size-3" aria-hidden /> PDFs and phone photos. Your files stay on this computer.
              </span>
            </span>
          </button>
        </>
      )}

      <BatchRecapDialog docIds={recap} onClose={() => setRecap(null)} />
    </Page>
  );
}
