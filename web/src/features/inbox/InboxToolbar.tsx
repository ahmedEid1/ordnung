/**
 * Inbox filters: All · Please check · Private, a search box, a kind picker, a year picker (by the date on the
 * letter) and, when the household has people, a *For* picker (whose letters).
 *
 * Phones: the tabs share the first row ("Check" for "Please check", no "0" counts), then the
 * search gets a whole row, so typed words stay in view; then the kind and the year share a row, and
 * *For* gets a row of its own (only with people). From `sm` the pickers sit next to the search,
 * together, and go under it as one group when they don't fit; from `xl` everything fits one row,
 * the pickers again under the search when the row is too narrow.
 */
import { Search, X } from "lucide-react";
import type { DocumentKind } from "@/api/types";
import { Tabs } from "@/components/ui/Tabs";
import { Input, Select } from "@/components/ui/Field";
import type { ForOption } from "@/features/household/logic";
import type { InboxFilter } from "./filters";

export function InboxToolbar({
  filter,
  onFilter,
  counts,
  kind,
  onKind,
  kinds,
  year,
  onYear,
  years,
  who = "",
  onWho,
  whoOptions = [],
  query,
  onQuery,
}: {
  filter: InboxFilter;
  onFilter: (f: InboxFilter) => void;
  /** Letters per tab, within the current kind, year, whose letters and search. */
  counts: Record<InboxFilter, number>;
  kind: DocumentKind | null;
  onKind: (k: DocumentKind | null) => void;
  kinds: { value: DocumentKind; label: string; count: number }[];
  /** The year chosen (by the date on the letter, else the day it arrived), or null: all years. */
  year: number | null;
  onYear: (y: number | null) => void;
  /** Each year with letters, newest first (`yearOptions`). */
  years: { value: number; count: number }[];
  /** Whose letters: "" (Everyone), "me" (You) or a person's id (`?for=`). */
  who?: string;
  onWho?: (who: string | null) => void;
  /** The *For* picker's options (`forOptions`); none: the household has no people, and the picker isn't shown. */
  whoOptions?: ForOption[];
  query: string;
  onQuery: (q: string) => void;
}) {
  return (
    <div className="flex flex-col gap-3 xl:flex-row xl:items-start">
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
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:flex-wrap xl:flex-1 xl:justify-end">
        <div className="relative min-w-0 sm:flex-[1_1_17.5rem] xl:max-w-80">
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
        {/* the pickers stay together: kind and year share a row on a phone, For gets its own */}
        <div data-inbox-pickers className="flex min-w-0 flex-wrap gap-3 sm:flex-nowrap">
          <label className="sr-only" htmlFor="inbox-kind">
            Kind of letter
          </label>
          <Select
            id="inbox-kind"
            value={kind ?? ""}
            onChange={(e) => onKind((e.target.value || null) as DocumentKind | null)}
            className="flex-1 sm:w-48 sm:flex-none"
          >
            <option value="">All kinds</option>
            {kinds.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label} ({k.count})
              </option>
            ))}
          </Select>
          <label className="sr-only" htmlFor="inbox-year">
            Year, by the date on the letter
          </label>
          <Select
            id="inbox-year"
            value={year == null ? "" : String(year)}
            onChange={(e) => onYear(e.target.value ? Number(e.target.value) : null)}
            className="flex-1 sm:w-32 sm:flex-none"
          >
            <option value="">All years</option>
            {years.map((y) => (
              <option key={y.value} value={y.value}>
                {y.value} ({y.count})
              </option>
            ))}
          </Select>
          {whoOptions.length ? (
            <>
              <label className="sr-only" htmlFor="inbox-for">
                Whose letters
              </label>
              <Select id="inbox-for" value={who} onChange={(e) => onWho?.(e.target.value || null)} className="basis-full sm:w-48 sm:basis-auto">
                {whoOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
