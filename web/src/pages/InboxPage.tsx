import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";
import { FileUp, Lock, Plus } from "lucide-react";
import type { DocumentKind } from "@/api/types";
import { useDocuments, useItems, useParties } from "@/api/hooks";
import { dismissJob } from "@/api/sse";
import { useDebounced, useMediaQuery, useStickyError } from "@/lib/hooks";
import { useTodayISO } from "@/lib/today";
import { documentKindLabel } from "@/lib/copy";
import { Page, PageHeader } from "@/components/shell/Page";
import { useAddLetters } from "@/components/shell/AddLetters";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel, SkeletonText, Skeleton } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { MailTray, focusMailEnvelope } from "@/features/inbox/MailTray";
import { WaitingFromFolder } from "@/features/inbox/WaitingFromFolder";
import { LettersList } from "@/features/inbox/LettersList";
import { InboxToolbar } from "@/features/inbox/InboxToolbar";
import { BatchRecapDialog } from "@/features/inbox/BatchRecap";
import { useReadingBatch } from "@/features/inbox/useReadingBatch";
import { MIN_SEARCH, emptyCopy, isNarrowed, resultLine, type InboxView } from "@/features/inbox/status";
import { useTrayByDoc } from "@/features/tour/newMail";
import { filterCounts, filterDocuments, groupLetters, isHeld, kindOptions, openItemsByDoc, parseFilter, type InboxFilter } from "@/features/inbox/filters";

/**
 * `/inbox` — every letter, filters, search, the demo's New-mail tray, the letters from the watched
 * folder that wait for the person, and the batch recap.
 */
export default function InboxPage() {
  const navigate = useNavigate();
  const today = useTodayISO();
  const { openPicker } = useAddLetters();
  const touch = useMediaQuery("(pointer: coarse)");
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const filter = parseFilter(params.get("filter"));
  const kind = (params.get("kind") || null) as DocumentKind | null;

  // ---- the search lives in the field and in the URL (?q=), so Back to the Inbox keeps it -------
  const urlQuery = params.get("q") ?? "";
  const [query, setQuery] = useState(urlQuery);
  const typed = query.trim();
  const q = useDebounced(typed, 200);
  const searching = q.length >= MIN_SEARCH;
  // A navigation this page didn't make (its own carry `state.inboxQuery`: the words they left in
  // the URL) — the top bar's "See all letters matching …" — puts its words in the field.
  const own = (location.state as { inboxQuery?: string } | null)?.inboxQuery === urlQuery;
  const [seenLocation, setSeenLocation] = useState(location.key);
  if (location.key !== seenLocation) {
    setSeenLocation(location.key);
    if (!own && urlQuery !== typed) setQuery(urlQuery);
  }
  const latestUrlQuery = useRef(urlQuery);
  useEffect(() => {
    latestUrlQuery.current = urlQuery;
  });
  // typed words go into the URL once they settle (replacing the entry: no history per keystroke) —
  // only when they change: `setParams` changes with every URL, which must not re-send old words
  const sentQuery = useRef(q);
  useEffect(() => {
    if (q === sentQuery.current) return;
    sentQuery.current = q;
    if (q === latestUrlQuery.current) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (q) next.set("q", q);
        else next.delete("q");
        return next;
      },
      { replace: true, preventScrollReset: true, state: { inboxQuery: q } },
    );
  }, [q, setParams]);

  const all = useDocuments();
  const search = useDocuments({ q }, { enabled: searching });
  const items = useItems({ status: "open" });
  const parties = useParties();
  const trayByDoc = useTrayByDoc();

  // A retry of a load that failed starts over as "pending" (and forgets the error), so remember
  // the last error: the message stays on screen, worded the same, while "Try again" runs.
  const lastError = useStickyError(all.error, Boolean(all.data));
  const failedToLoad = !all.data && (all.isError || Boolean(lastError));

  // ---- where focus goes when the tray (or the recap's opener) is gone: the letters just read ----
  const lettersRef = useRef<HTMLDivElement>(null);
  const focusLetters = useCallback(
    () => lettersRef.current?.querySelector<HTMLElement>("a[href^='/documents/']") ?? document.querySelector<HTMLElement>("main"),
    [],
  );
  const recapReturn = useMemo<RefObject<HTMLElement | null>>(
    () => ({
      get current() {
        return focusLetters();
      },
    }),
    [focusLetters],
  );

  // ---- live reading: one New-mail letter → open it; several → recap -----------------------
  /** documents opened from New mail → their sender */
  const fromTray = useRef(new Map<string, string>());
  const [recap, setRecap] = useState<{ ids: string[]; failed: string[] } | null>(null);
  // "Couldn't read the letter from Finanzamt Musterstadt": the sender (New mail) or the title
  const known = useRef({ trayByDoc, docs: all.data });
  useEffect(() => {
    known.current = { trayByDoc, docs: all.data };
  });
  useReadingBatch(
    useCallback(
      (ids: string[], failed: string[]) => {
        const ok = ids.filter((id) => !failed.includes(id));
        if (ids.length > 1) {
          // the recap lists the ones that couldn't be read too ("I read 2 of 3 letters")
          setRecap({ ids, failed });
          ok.forEach((id) => dismissJob(id));
          return;
        }
        if (ok.length === 1 && fromTray.current.has(ok[0]!)) {
          dismissJob(ok[0]!);
          navigate(`/documents/${ok[0]}`);
        }
        const id = failed[0];
        if (id) {
          const onTray = fromTray.current.has(id);
          const sender = fromTray.current.get(id) ?? known.current.trayByDoc.get(id)?.sender;
          const title = known.current.docs?.find((d) => d.id === id)?.title;
          toast.error(`Couldn't read ${sender ? `the letter from ${sender}` : title ? `“${title}”` : "a letter"}`, {
            action: onTray
              ? { label: "Show", onClick: () => void (focusMailEnvelope(id) || navigate(`/documents/${id}`)) }
              : { label: "Open", onClick: () => void navigate(`/documents/${id}`) },
          });
        }
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
      // a filter leaves the words in the URL as they were: not a new search
      { replace: true, preventScrollReset: true, state: { inboxQuery: urlQuery } },
    );

  const docs = useMemo(() => all.data ?? [], [all.data]);
  const kinds = useMemo(() => kindOptions(docs), [docs]);
  const partyMap = useMemo(() => new Map((parties.data ?? []).map((p) => [p.id, p])), [parties.data]);
  const openMap = useMemo(() => openItemsByDoc(items.data ?? [], today), [items.data, today]);
  // the words and the kind narrow the list first; the tabs count within that
  const narrowed = useMemo(() => filterDocuments(searching ? (search.data ?? []) : docs, { filter: "all", kind }), [searching, search.data, docs, kind]);
  const counts = useMemo(() => filterCounts(narrowed), [narrowed]);
  const visible = useMemo(() => filterDocuments(narrowed, { filter }), [narrowed, filter]);
  const groups = useMemo(() => groupLetters(visible, today), [visible, today]);
  const total = useMemo(() => filterCounts(docs).all, [docs]);
  const waiting = useMemo(() => docs.filter(isHeld), [docs]);

  // the settled words (not every keystroke): "Type one more letter" waits for a pause
  const view: InboxView = { filter, kindLabel: kind ? documentKindLabel(kind) : null, typed: q, q: searching ? q : "" };
  const pendingSearch = searching && search.isPending;
  const line = resultLine(view, visible.length, total, pendingSearch);
  const empty = emptyCopy(view);
  const onlySearch = Boolean(view.q) && filter === "all" && !kind;
  const clearSearch = () => setQuery("");
  const clearAll = () => {
    setQuery("");
    setParams(new URLSearchParams(), { replace: true, state: { inboxQuery: "" } });
  };

  return (
    <Page title="Inbox">
      <PageHeader
        title="Inbox"
        description="Every letter you added — read, explained and filed, with the sentence behind every date."
      />

      <MailTray onOpened={(opened) => opened.forEach(({ docId, sender }) => fromTray.current.set(docId, sender))} focusFallback={focusLetters} />

      {failedToLoad ? (
        <LoadError
          what="your letters"
          error={all.error ?? lastError}
          onRetry={() => void all.refetch()}
          retrying={all.isFetching}
        />
      ) : all.isPending ? (
        <div aria-busy="true">
          <LoadingLabel>Loading your letters…</LoadingLabel>
          {/* shaped like the toolbar: the tabs, then the search and the kind picker */}
          <div className="mb-6 flex flex-col gap-3 xl:flex-row xl:items-center">
            <Skeleton className="h-9 w-full rounded-xl sm:w-72" />
            <div className="flex flex-col gap-3 sm:flex-row xl:flex-1 xl:justify-end">
              <Skeleton className="h-9 rounded-lg sm:flex-1 xl:max-w-80" />
              <Skeleton className="h-9 rounded-lg sm:w-48" />
            </div>
          </div>
          <div className="card divide-y divide-line">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="flex items-center gap-3.5 px-4 py-3.5 sm:px-5">
                <Skeleton className="h-[54px] w-10 shrink-0 rounded-[4px]" />
                <SkeletonText lines={2} className="min-w-0 flex-1" />
              </div>
            ))}
          </div>
        </div>
      ) : !docs.length ? (
        <EmptyState
          illustration="inbox"
          title="No letters yet"
          description="Add a PDF, a phone photo or a saved e-mail of a letter. Ordnung reads it with your own Claude, explains it and files every date and amount."
          action={
            <Button variant="primary" icon={Plus} onClick={openPicker}>
              Add letters
            </Button>
          }
        />
      ) : (
        <>
          {/* the letters the folder brought in wait above the list (they're in no group or filter of it) */}
          <WaitingFromFolder docs={docs} onAnswered={() => focusLetters()?.focus({ preventScroll: true })} />
          {total || !waiting.length ? (
            <>
              <div className="mb-6 flex flex-col gap-3">
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
                {/* what the list shows now — announced, and on screen unless an empty state says it */}
                <p role="status" className="sr-only">
                  {line.text}
                </p>
                {line.visible ? (
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
                    <p aria-hidden>{line.text}</p>
                    {isNarrowed(view) && visible.length ? (
                      <Button variant="link" size="sm" onClick={onlySearch ? clearSearch : clearAll}>
                        {onlySearch ? "Clear search" : "Clear filters"}
                      </Button>
                    ) : null}
                  </div>
                ) : null}
              </div>
              <div
                ref={lettersRef}
                role="tabpanel"
                id={`inbox-filter-panel-${filter}`}
                aria-labelledby={`inbox-filter-tab-${filter}`}
                aria-busy={searching && search.isFetching}
              >
                {groups.length ? (
                  <LettersList groups={groups} parties={partyMap} open={openMap} />
                ) : pendingSearch ? null : (
                  <EmptyState
                    size="sm"
                    illustration={empty.illustration}
                    title={empty.title}
                    description={empty.description}
                    action={
                      empty.action === "clear-search" ? (
                        <Button size="sm" onClick={clearSearch}>
                          Clear search
                        </Button>
                      ) : empty.action === "clear-filters" ? (
                        <Button size="sm" onClick={clearAll}>
                          Clear filters
                        </Button>
                      ) : empty.action === "add" ? (
                        <Button size="sm" icon={Plus} onClick={openPicker}>
                          Add letters
                        </Button>
                      ) : undefined
                    }
                  />
                )}
              </div>

              {/* not under an empty state: that one says what to do */}
              {groups.length ? (
                <button
                  type="button"
                  onClick={openPicker}
                  className="mt-8 flex w-full items-center gap-3 rounded-2xl border border-dashed border-line-strong px-4 py-4 text-left transition-colors hover:border-accent/60 hover:bg-accent-soft/40 sm:px-5"
                >
                  <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
                    <FileUp className="size-5" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-base font-medium text-ink">
                      {touch ? "Add letters — PDFs or phone photos" : "Drop letters anywhere on this page, or choose files"}
                    </span>
                    <span className="mt-0.5 flex items-start gap-1.5 text-sm leading-5 text-muted">
                      <Lock className="mt-1 size-3 shrink-0" aria-hidden />
                      {touch ? "Your files stay on this device." : "PDFs and phone photos. Your files stay on this computer."}
                    </span>
                  </span>
                </button>
              ) : null}
            </>
          ) : null}
        </>
      )}

      <BatchRecapDialog docIds={recap?.ids ?? null} failedIds={recap?.failed} onClose={() => setRecap(null)} returnFocus={recapReturn} />
    </Page>
  );
}
