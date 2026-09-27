import { Fragment, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { ArrowRight, Plus, RotateCw, Search, SearchX, TriangleAlert, X } from "lucide-react";
import { SEARCH_LIMIT, useDocuments, useParties, useSearchDocuments } from "@/api/hooks";
import type { Document } from "@/api/types";
import { cn, plural } from "@/lib/utils";
import { useDebounced, useHotkey } from "@/lib/hooks";
import { DOCUMENT_STATUS_COPY, documentKindLabel } from "@/lib/copy";
import { KindIcon } from "@/components/ui/KindBadge";
import { DateText } from "@/components/ui/DateText";
import { Kbd } from "@/components/ui/Kbd";
import { Spinner } from "@/components/ui/Spinner";
import { Button, IconButton } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useAddLetters } from "./AddLetters";

/** The search starts at this many characters. */
const MIN_CHARS = 2;
/** Letters the phone search sheet lists before anything is typed. */
const RECENT_COUNT = 5;

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** `text` with every word of `query` (2+ characters, any case) in the highlighter. */
export function Highlight({ text, query }: { text: string; query: string }) {
  const words = query
    .trim()
    .split(/\s+/)
    .filter((w) => w.length >= MIN_CHARS)
    .sort((a, b) => b.length - a.length);
  if (!words.length) return <>{text}</>;
  const parts = text.split(new RegExp(`(${words.map(escapeRegExp).join("|")})`, "gi"));
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="marker text-inherit">
            {part}
          </mark>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}

interface ComboProps {
  autoFocus?: boolean;
  /** Called after the search took the person somewhere (a letter, the Inbox, the file picker). */
  onNavigate?: () => void;
  /** Render results inline (the phone sheet) instead of in a dropdown. */
  inline?: boolean;
  className?: string;
}

/** A calm one-line message in the results panel (hint, searching, nothing found, error). */
function PanelMessage({ icon, tone = "muted", children, action }: { icon?: ReactNode; tone?: "muted" | "danger"; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start gap-3 px-4 py-3 text-base">
      {icon ? <span className={cn("mt-0.5 grid size-4 shrink-0 place-items-center", tone === "danger" ? "text-danger" : "text-muted")}>{icon}</span> : null}
      <div className="min-w-0 flex-1 text-pretty text-muted [overflow-wrap:anywhere]">
        {children}
        {action ? <div className="mt-2.5 flex flex-wrap gap-2">{action}</div> : null}
      </div>
    </div>
  );
}

/**
 * Search combobox over letters (`GET /api/documents?q=`), keyboard navigable. Every state says
 * what is going on: a hint, "Searching…", the matches (the query highlighted, a link to all of
 * them in the Inbox when there are more), nothing found, no letters at all, or an error with
 * "Try again". The number found is announced.
 */
function SearchCombobox({ autoFocus, onNavigate, inline, className }: ComboProps) {
  const navigate = useNavigate();
  const { openPicker } = useAddLetters();
  const [q, setQ] = useState("");
  const [focused, setFocused] = useState(false);
  /** The highlighted option (-1: none — the phone sheet's recent letters wait for the arrow keys). */
  const [active, setActive] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  /** Set by the arrow keys: the new active option is scrolled into view (not on mouse hover). */
  const revealActive = useRef(false);
  const debounced = useDebounced(q, 160);
  const term = q.trim();
  const dterm = debounced.trim();
  const searching = term.length >= MIN_CHARS;
  const search = useSearchDocuments(debounced);
  const { data: parties } = useParties();
  const partyName = useMemo(() => new Map((parties ?? []).map((p) => [p.id, p.name])), [parties]);
  const listId = useId();
  const panelId = `${listId}-panel`;

  // a boolean, so the combobox always states aria-expanded (ARIA requires it); the phone sheet is always open
  const open = inline ? true : focused && q.length > 0;
  const matches: Document[] = dterm.length >= MIN_CHARS && searching ? (search.data ?? []) : [];
  const results = matches.slice(0, SEARCH_LIMIT);
  const hasMore = matches.length > SEARCH_LIMIT;
  const settled = dterm === term && !search.isFetching;
  const noMatches = searching && settled && !search.isError && results.length === 0;
  const showRecent = Boolean(inline) && term.length === 0;
  // recent letters for the empty phone sheet; the same list tells "no letters match" from "no letters yet"
  const recent = useDocuments({ limit: RECENT_COUNT }, { enabled: open && (showRecent || noMatches) });
  const options = showRecent ? (recent.data ?? []) : results;
  const activeIndex = Math.min(active, Math.max(0, options.length - 1));
  const activeId = open && options[activeIndex] ? `${listId}-opt-${activeIndex}` : undefined;

  useHotkey(
    (e) => (e.key === "/" && !e.metaKey && !e.ctrlKey) || (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)),
    (e) => {
      if (inline) return;
      e.preventDefault();
      inputRef.current?.focus();
    },
  );

  useEffect(() => {
    if (!revealActive.current || !activeId) return;
    revealActive.current = false;
    document.getElementById(activeId)?.scrollIntoView?.({ block: "nearest" });
  }, [activeId]);

  const reset = () => {
    setQ("");
    setActive(-1);
  };

  const go = (d: Document) => {
    navigate(`/documents/${d.id}`);
    reset();
    inputRef.current?.blur();
    onNavigate?.();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!options.length) return;
      revealActive.current = true;
      setActive(e.key === "ArrowDown" ? Math.min(activeIndex + 1, options.length - 1) : Math.max(activeIndex - 1, 0));
    } else if (e.key === "Enter") {
      const d = options[activeIndex];
      if (open && d) {
        e.preventDefault();
        go(d);
      }
    } else if (e.key === "Escape") {
      if (q) {
        // the first Escape only clears the query: the sheet (or anything else listening) stays open
        e.preventDefault();
        e.stopPropagation();
        e.nativeEvent.stopImmediatePropagation();
        reset();
      }
      // with nothing typed: the phone sheet closes (its dialog handles the key); on the top bar
      // focus stays in the field — there is nothing left to close
    }
  };

  const optionRow = (d: Document, i: number) => {
    const title = d.title ?? d.filename;
    const sender = d.party_id ? partyName.get(d.party_id) : undefined;
    // a letter waiting from the watched folder has no kind or date read yet: it says so, with the day it came
    const waiting = d.status === "held";
    const date = waiting ? d.created_at.slice(0, 10) : (d.doc_date ?? d.received_date);
    const kind = waiting ? DOCUMENT_STATUS_COPY.held.label : documentKindLabel(d.kind);
    const isActive = i === activeIndex;
    return (
      <li
        key={d.id}
        id={`${listId}-opt-${i}`}
        role="option"
        aria-selected={isActive}
        title={title}
        onMouseMove={() => {
          if (!isActive) setActive(i);
        }}
        onMouseDown={(e) => {
          e.preventDefault();
          go(d);
        }}
        className={cn(
          "flex cursor-pointer items-start gap-3 rounded-lg px-2 py-2",
          // the phone sheet's field sticks over the list: an option scrolled up to stops below it
          inline ? "scroll-mt-10" : "",
          isActive ? "bg-accent-soft ring-1 ring-inset ring-accent" : "",
        )}
      >
        {/* on phones the kind is the icon's name: the meta line keeps its room for the date and the sender */}
        <KindIcon docKind={d.kind} size="sm" className="mt-0.5" title={inline ? kind : undefined} />
        <span className="min-w-0 flex-1">
          <span className="line-clamp-2 text-base font-medium leading-snug text-ink [overflow-wrap:anywhere]">
            <Highlight text={title} query={dterm} />
          </span>
          <span className="mt-0.5 flex min-w-0 items-baseline gap-1 text-sm text-muted">
            {inline ? (
              <>
                {date ? <DateText date={date} style="day" className="shrink-0" /> : null}
                {date ? <span aria-hidden>·</span> : null}
                <span className="min-w-0 truncate" title={sender}>
                  {sender ? <Highlight text={sender} query={dterm} /> : kind}
                </span>
              </>
            ) : (
              <>
                {sender ? (
                  <span className="min-w-0 truncate" title={sender}>
                    <Highlight text={sender} query={dterm} />
                  </span>
                ) : null}
                {sender ? <span aria-hidden>·</span> : null}
                <span className="shrink-0 whitespace-nowrap">{kind}</span>
              </>
            )}
          </span>
        </span>
        {!inline ? <DateText date={date} style="day" className="mt-0.5 shrink-0 text-xs text-muted" /> : null}
      </li>
    );
  };

  const listbox = (label: string) => (
    <ul
      id={listId}
      role="listbox"
      aria-label={label}
      className={cn(inline ? "-mx-2 space-y-0.5 py-1" : "max-h-[min(60vh,420px)] space-y-0.5 overflow-y-auto p-1.5 scrollbar-thin")}
    >
      {options.map(optionRow)}
    </ul>
  );

  let body: ReactNode;
  let announcement = "";
  if (showRecent) {
    body = (
      <>
        <p className="py-2 text-sm text-muted">Search senders, subjects, amounts or reference numbers.</p>
        {options.length ? (
          <>
            <p className="eyebrow mt-3 pb-1">Recent letters</p>
            {listbox("Recent letters")}
          </>
        ) : null}
      </>
    );
  } else if (!searching) {
    body = <PanelMessage>Keep typing — search senders, subjects, amounts or reference numbers.</PanelMessage>;
  } else if (results.length) {
    announcement = hasMore ? `More than ${plural(SEARCH_LIMIT, "letter")} found` : `${plural(results.length, "letter")} found`;
    body = (
      <>
        {listbox("Matching letters")}
        {hasMore ? (
          <Link
            to={`/inbox?q=${encodeURIComponent(dterm)}`}
            onClick={() => {
              reset();
              inputRef.current?.blur();
              onNavigate?.();
            }}
            className={cn(
              "flex min-h-10 items-center gap-2 border-t border-line text-sm font-semibold text-accent transition-colors hover:bg-accent-soft",
              inline ? "-mx-2 mt-1 rounded-b-lg px-2 py-2" : "px-4 py-2.5",
            )}
          >
            <span className="min-w-0 flex-1 truncate" title={`See all letters matching “${dterm}”`}>
              See all letters matching “{dterm}”
            </span>
            <ArrowRight className="size-4 shrink-0" aria-hidden />
          </Link>
        ) : null}
      </>
    );
  } else if (search.isError && settled) {
    announcement = "Couldn't search";
    body = (
      <PanelMessage
        tone="danger"
        icon={<TriangleAlert className="size-4" aria-hidden />}
        action={
          <Button size="sm" icon={RotateCw} onClick={() => void search.refetch()}>
            Try again
          </Button>
        }
      >
        <span className="font-medium text-ink">Couldn't search — Ordnung isn't answering.</span>
      </PanelMessage>
    );
  } else if (noMatches && recent.data?.length === 0) {
    announcement = "You haven't added any letters yet";
    body = (
      <PanelMessage
        icon={<SearchX className="size-4" aria-hidden />}
        action={
          <Button
            size="sm"
            variant="primary"
            icon={Plus}
            onClick={() => {
              reset();
              onNavigate?.();
              openPicker();
            }}
          >
            Add letters
          </Button>
        }
      >
        <span className="font-medium text-ink">You haven't added any letters yet.</span> Add a PDF or a phone photo, and search finds it by sender,
        subject, amount or reference number.
      </PanelMessage>
    );
  } else if (noMatches) {
    announcement = `No letters match “${dterm}”`;
    body = (
      <PanelMessage icon={<SearchX className="size-4" aria-hidden />}>
        <span className="font-medium text-ink">No letters match “{dterm}”.</span> Try a sender, a reference number or an amount.
      </PanelMessage>
    );
  } else {
    body = (
      <div className="flex items-center gap-3 px-4 py-3 text-base text-muted">
        <Spinner className="size-4 shrink-0" />
        Searching…
      </div>
    );
  }

  const panel = (
    <div
      id={panelId}
      data-search-panel=""
      // clicks on the panel's text keep focus in the field (links and buttons take it themselves)
      onMouseDown={(e) => {
        if (!(e.target as HTMLElement).closest("a, button")) e.preventDefault();
      }}
      className={cn(
        inline
          ? "pt-1"
          : "absolute right-0 top-[calc(100%+6px)] z-40 min-w-full overflow-hidden rounded-xl border border-line bg-surface shadow-[var(--shadow-pop)] dark:border-line-strong",
        !inline && (results.length ? "w-[min(30rem,calc(100vw-2rem))]" : "w-full"),
      )}
    >
      {body}
    </div>
  );

  return (
    <div
      className={cn("relative", className)}
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        // focus moving to the panel's own link or button keeps it open
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false);
      }}
    >
      <div className={cn("relative", inline && "sticky top-0 z-10 -mt-3 bg-surface pb-2 pt-3")}>
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <input
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={open}
          // the popup it controls: the list of letters, else the panel with its message
          aria-controls={open ? (options.length ? listId : panelId) : undefined}
          aria-activedescendant={activeId}
          aria-autocomplete="list"
          aria-keyshortcuts={inline ? undefined : "/ Control+K Meta+K"}
          aria-label="Search your letters"
          placeholder="Search letters…"
          autoComplete="off"
          enterKeyHint="search"
          autoFocus={autoFocus}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            // the best match is ready for Enter
            setActive(e.target.value.trim() ? 0 : -1);
          }}
          onKeyDown={onKeyDown}
          className={cn(
            "h-9 w-full rounded-lg border border-line bg-surface/70 pl-9 pr-10 text-base text-ink shadow-[inset_0_1px_1px_rgb(0_0_0/0.03)] outline-none transition-[border-color,box-shadow,background-color]",
            "placeholder:text-muted hover:border-line-strong focus:border-accent focus:bg-surface focus:ring-2 focus:ring-accent/60 [&::-webkit-search-cancel-button]:hidden",
          )}
        />
        <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2" aria-hidden>
          {search.isFetching && searching ? <Spinner className="size-3.5 text-muted" /> : !q && !inline && !focused ? <Kbd>/</Kbd> : null}
        </span>
        {q && !(search.isFetching && searching) ? (
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              reset();
              inputRef.current?.focus();
            }}
            className="absolute right-1.5 top-1/2 grid size-7 -translate-y-1/2 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
            aria-label="Clear search"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        ) : null}
      </div>
      <p role="status" className="sr-only">
        {open ? announcement : ""}
      </p>
      {open ? panel : null}
    </div>
  );
}

/** Top-bar search: inline input from md up, an icon that opens a search sheet on phones. */
export function SearchBox() {
  const [mobileOpen, setMobileOpen] = useState(false);
  return (
    <>
      <SearchCombobox className="hidden w-56 md:block lg:w-72" />
      <IconButton icon={Search} label="Search letters" className="md:hidden" onClick={() => setMobileOpen(true)} />
      <Dialog open={mobileOpen} onClose={() => setMobileOpen(false)} title="Search letters" size="lg" align="top">
        <SearchCombobox inline autoFocus onNavigate={() => setMobileOpen(false)} className="pb-3" />
      </Dialog>
    </>
  );
}
