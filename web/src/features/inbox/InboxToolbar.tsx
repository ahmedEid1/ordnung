/**
 * Inbox filters: All · Please check · Private, a search box and a kind picker.
 *
 * Phones: the tabs share the first row ("Check" for "Please check", no "0" counts), then the
 * search and the kind picker each get a whole row, so typed words stay in view. From `sm` the
 * search and the picker share the second row; from `xl` everything fits one row.
 */
import { Search, X } from "lucide-react";
import type { DocumentKind } from "@/api/types";
import { Tabs } from "@/components/ui/Tabs";
import { Input, Select } from "@/components/ui/Field";
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
  /** Letters per tab, within the current kind and search. */
  counts: Record<InboxFilter, number>;
  kind: DocumentKind | null;
  onKind: (k: DocumentKind | null) => void;
  kinds: { value: DocumentKind; label: string; count: number }[];
  query: string;
  onQuery: (q: string) => void;
}) {
  return (
    <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
      <Tabs<InboxFilter>
        id="inbox-filter"
        label="Filter letters"
        variant="pill"
        value={filter}
        onChange={onFilter}
        fill
        hideZero
        className="xl:shrink-0"
        items={[
          { value: "all", label: "All", count: counts.all },
          { value: "check", label: "Please check", shortLabel: "Check", count: counts.check },
          { value: "private", label: "Private", count: counts.private },
        ]}
      />
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row xl:flex-1 xl:justify-end">
        <div className="relative min-w-0 sm:flex-1 xl:max-w-80">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
          <label htmlFor="inbox-search" className="sr-only">
            Search letters
          </label>
          <Input
            id="inbox-search"
            type="search"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder="Search sender, title, amount…"
            enterKeyHint="search"
            className="pl-9 pr-9 [&::-webkit-search-cancel-button]:hidden"
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
        <label className="sr-only" htmlFor="inbox-kind">
          Kind of letter
        </label>
        <Select
          id="inbox-kind"
          value={kind ?? ""}
          onChange={(e) => onKind((e.target.value || null) as DocumentKind | null)}
          className="sm:w-48 sm:shrink-0"
        >
          <option value="">All kinds</option>
          {kinds.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label} ({k.count})
            </option>
          ))}
        </Select>
      </div>
    </div>
  );
}
