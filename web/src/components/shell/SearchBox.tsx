import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router";
import { Search, SearchX, X } from "lucide-react";
import { useParties, useSearchDocuments } from "@/api/hooks";
import type { Document } from "@/api/types";
import { cn } from "@/lib/utils";
import { useDebounced, useHotkey } from "@/lib/hooks";
import { documentKindLabel } from "@/lib/copy";
import { KindIcon } from "@/components/ui/KindBadge";
import { DateText } from "@/components/ui/DateText";
import { Kbd } from "@/components/ui/Kbd";
import { Spinner } from "@/components/ui/Spinner";
import { IconButton } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";

interface ComboProps {
  autoFocus?: boolean;
  onNavigate?: () => void;
  /** Render results inline (mobile dialog) instead of in a dropdown. */
  inline?: boolean;
  className?: string;
}

/** Search combobox over letters (`GET /api/documents?q=`), keyboard navigable. */
function SearchCombobox({ autoFocus, onNavigate, inline, className }: ComboProps) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [focused, setFocused] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounced = useDebounced(q, 160);
  const { data, isFetching } = useSearchDocuments(debounced);
  const { data: parties } = useParties();
  const partyName = useMemo(() => new Map((parties ?? []).map((p) => [p.id, p.name])), [parties]);
  const listId = useId();
  const results: Document[] = debounced.trim().length >= 2 ? (data ?? []) : [];
  // a boolean, so the combobox always states aria-expanded (ARIA requires it)
  const open = Boolean(focused || inline) && q.trim().length > 0;
  const panelId = `${listId}-panel`;

  useHotkey(
    (e) => (e.key === "/" && !e.metaKey && !e.ctrlKey) || (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)),
    (e) => {
      if (inline) return;
      e.preventDefault();
      inputRef.current?.focus();
    },
  );

  const go = (d: Document) => {
    navigate(`/documents/${d.id}`);
    setQ("");
    setActive(0);
    inputRef.current?.blur();
    onNavigate?.();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, Math.max(0, results.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      const d = results[active];
      if (d) {
        e.preventDefault();
        go(d);
      }
    } else if (e.key === "Escape") {
      if (q) setQ("");
      else inputRef.current?.blur();
    }
  };

  const activeId = results[active] ? `${listId}-opt-${active}` : undefined;

  const panel = (
    <div
      id={panelId}
      className={cn(
        inline
          ? "mt-3"
          : "absolute right-0 top-[calc(100%+6px)] z-40 w-[min(30rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-line bg-surface shadow-[var(--shadow-pop)]",
      )}
    >
      {debounced.trim().length < 2 ? (
        <p className="px-4 py-3 text-base text-muted">Keep typing — search senders, subjects, amounts or reference numbers.</p>
      ) : results.length === 0 && !isFetching ? (
        <div className="flex items-center gap-3 px-4 py-4 text-base text-muted">
          <SearchX className="size-4 shrink-0" aria-hidden />
          No letters match “{debounced.trim()}”.
        </div>
      ) : (
        <ul id={listId} role="listbox" aria-label="Matching letters" className="max-h-[min(60vh,420px)] overflow-y-auto p-1.5 scrollbar-thin">
          {results.map((d, i) => (
            <li
              key={d.id}
              id={`${listId}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => {
                e.preventDefault();
                go(d);
              }}
              className={cn("flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2", i === active ? "bg-surface-2" : "")}
            >
              <KindIcon docKind={d.kind} size="sm" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-base font-medium text-ink">{d.title ?? d.filename}</span>
                <span className="block truncate text-[12.5px] text-muted">
                  {[d.party_id ? partyName.get(d.party_id) : null, documentKindLabel(d.kind)].filter(Boolean).join(" · ")}
                </span>
              </span>
              <DateText date={d.doc_date ?? d.received_date} style="day" className="shrink-0 text-[12px] text-muted" />
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  return (
    <div className={cn("relative", className)}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <input
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          aria-activedescendant={open ? activeId : undefined}
          aria-autocomplete="list"
          aria-label="Search your letters"
          placeholder="Search letters…"
          autoFocus={autoFocus}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
          }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={onKeyDown}
          className={cn(
            "h-9 w-full rounded-lg border border-line bg-surface/70 pl-9 pr-10 text-base text-ink shadow-[inset_0_1px_1px_rgb(0_0_0/0.03)] outline-none transition-[border-color,box-shadow,background-color]",
            "placeholder:text-muted hover:border-line-strong focus:border-accent focus:bg-surface focus:ring-3 focus:ring-accent/15 [&::-webkit-search-cancel-button]:hidden",
          )}
        />
        <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2">
          {isFetching && q ? <Spinner className="size-3.5 text-muted" /> : !q && !inline ? <Kbd>/</Kbd> : null}
        </span>
        {q && !isFetching ? (
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              setQ("");
              inputRef.current?.focus();
            }}
            className="absolute right-2 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded text-muted hover:text-ink"
            aria-label="Clear search"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        ) : null}
      </div>
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
