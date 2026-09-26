/** Inbox filters: All · Please check · Private, a kind picker and a search box. */
import { Search, X } from "lucide-react";
import type { DocumentKind } from "@/api/types";
import { Tabs } from "@/components/ui/Tabs";
import { Select } from "@/components/ui/Field";
import type { InboxFilter } from "./filters";

export function InboxToolbar({
  filter,
  onFilter,
  counts,
  kind,
  onKind,
  kinds,
  query,
  onQuery,
}: {
  filter: InboxFilter;
  onFilter: (f: InboxFilter) => void;
  counts: Record<InboxFilter, number>;
  kind: DocumentKind | null;
  onKind: (k: DocumentKind | null) => void;
  kinds: { value: DocumentKind; label: string; count: number }[];
  query: string;
  onQuery: (q: string) => void;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 lg:flex-row lg:items-center">
      <Tabs<InboxFilter>
        id="inbox-filter"
        label="Filter letters"
        variant="pill"
        value={filter}
        onChange={onFilter}
        className="self-start"
        items={[
          { value: "all", label: "All", count: counts.all },
          { value: "check", label: "Please check", count: counts.check },
          { value: "private", label: "Private", count: counts.private },
        ]}
      />
      <div className="flex min-w-0 flex-1 gap-2 lg:justify-end">
        <label className="sr-only" htmlFor="inbox-kind">
          Kind of letter
        </label>
        <Select
          id="inbox-kind"
          value={kind ?? ""}
          onChange={(e) => onKind((e.target.value || null) as DocumentKind | null)}
          className="w-[46%] min-w-0 shrink-0 sm:w-48"
        >
          <option value="">All kinds</option>
          {kinds.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label} ({k.count})
            </option>
          ))}
        </Select>
        <div className="relative min-w-0 flex-1 lg:max-w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
          <label htmlFor="inbox-search" className="sr-only">
            Search letters
          </label>
          <input
            id="inbox-search"
            type="search"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder="Search sender, title, amount…"
            className="h-9 w-full rounded-lg border border-line-strong/80 bg-surface pl-9 pr-8 text-sm text-ink shadow-[inset_0_1px_1px_rgb(0_0_0/0.03)] placeholder:text-muted/70 hover:border-line-strong focus-visible:border-accent focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-accent/20 [&::-webkit-search-cancel-button]:hidden"
          />
          {query ? (
            <button
              type="button"
              onClick={() => onQuery("")}
              className="absolute right-1.5 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
              aria-label="Clear search"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
