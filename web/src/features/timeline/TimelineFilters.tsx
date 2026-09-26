/**
 * Filters above the month-by-month list — kind, life area, person/organisation — and "Show past".
 * The kind, area and person filter the lanes above too.
 */
import { X } from "lucide-react";
import type { Area, TimelineType } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Select, Switch } from "@/components/ui/Field";
import { activeFilterCount, NO_FILTERS, type FilterOption, type TimelineFilters as Filters } from "./model";

/** Phones: two columns (the person's full width), one column below 360 px; from sm each select as wide as its words. */
const selectCls = "min-w-0 sm:w-auto sm:min-w-44 sm:max-w-72";

function FilterSelect<V extends string>({
  id,
  label,
  all,
  value,
  options,
  onChange,
  className,
}: {
  id: string;
  label: string;
  all: string;
  value: V | null;
  options: FilterOption<V>[];
  onChange: (v: V | null) => void;
  className?: string;
}) {
  const chosen = options.find((o) => o.value === value);
  return (
    <>
      <label className="sr-only" htmlFor={id}>
        {label}
      </label>
      <Select
        id={id}
        className={className ?? selectCls}
        title={chosen?.label ?? all}
        value={value ?? ""}
        onChange={(e) => onChange((e.target.value || null) as V | null)}
      >
        <option value="">{all}</option>
        {options.map((o) => (
          // the count is for choosing — the closed menu shows just the name, so it never gets cut
          <option key={o.value} value={o.value} disabled={o.count === 0 && o.value !== value}>
            {o.value === value ? o.label : `${o.label} (${o.count})`}
          </option>
        ))}
      </Select>
    </>
  );
}

export function TimelineFilters({
  filters,
  onChange,
  options,
}: {
  filters: Filters;
  onChange: (f: Filters) => void;
  options: { types: FilterOption<TimelineType>[]; areas: FilterOption<Area>[]; parties: FilterOption[] };
}) {
  const active = activeFilterCount(filters);
  return (
    // from sm one wrapping row: menus, then "Show past" at the end of whichever line it lands on —
    // never floating between two lines of menus
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-2">
      <div className="grid grid-cols-2 gap-2 max-[360px]:grid-cols-1 sm:contents">
        <FilterSelect id="tl-type" label="Kind" all="All kinds" value={filters.type} options={options.types} onChange={(type) => onChange({ ...filters, type })} />
        <FilterSelect id="tl-area" label="Life area" all="All areas" value={filters.area} options={options.areas} onChange={(area) => onChange({ ...filters, area })} />
        <FilterSelect
          id="tl-party"
          label="People & organisations"
          all="All people & organisations"
          value={filters.party}
          options={options.parties}
          onChange={(party) => onChange({ ...filters, party })}
          className={`col-span-2 max-[360px]:col-span-1 ${selectCls}`}
        />
      </div>
      <div className="flex min-h-9 flex-wrap items-center gap-x-4 gap-y-2 sm:ml-auto sm:pl-2">
        <Switch
          checked={filters.showPast}
          onCheckedChange={(v) => onChange({ ...filters, showPast: v })}
          label={<span className="whitespace-nowrap text-sm">Show past</span>}
          className="items-center gap-2.5"
        />
        {active ? (
          <Button variant="ghost" size="sm" icon={X} onClick={() => onChange(NO_FILTERS)}>
            Clear filters
          </Button>
        ) : null}
      </div>
    </div>
  );
}
