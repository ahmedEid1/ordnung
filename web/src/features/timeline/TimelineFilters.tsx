/** Filters above the month-by-month list: kind, life area, person/organisation and "Show past". */
import { X } from "lucide-react";
import type { Area, TimelineType } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Select, Switch } from "@/components/ui/Field";
import { activeFilterCount, NO_FILTERS, type FilterOption, type TimelineFilters as Filters } from "./model";

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
  const selectCls = "min-w-0 sm:w-44";
  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
      <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center">
        <label className="sr-only" htmlFor="tl-type">
          Kind
        </label>
        <Select
          id="tl-type"
          className={selectCls}
          value={filters.type ?? ""}
          onChange={(e) => onChange({ ...filters, type: (e.target.value || null) as TimelineType | null })}
        >
          <option value="">All kinds</option>
          {options.types.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label} ({o.count})
            </option>
          ))}
        </Select>
        <label className="sr-only" htmlFor="tl-area">
          Life area
        </label>
        <Select
          id="tl-area"
          className={selectCls}
          value={filters.area ?? ""}
          onChange={(e) => onChange({ ...filters, area: (e.target.value || null) as Area | null })}
        >
          <option value="">All areas</option>
          {options.areas.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label} ({o.count})
            </option>
          ))}
        </Select>
        <label className="sr-only" htmlFor="tl-party">
          People &amp; organisations
        </label>
        <Select
          id="tl-party"
          className="col-span-2 min-w-0 sm:w-56"
          value={filters.party ?? ""}
          onChange={(e) => onChange({ ...filters, party: e.target.value || null })}
        >
          <option value="">All people &amp; organisations</option>
          {options.parties.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label} ({o.count})
            </option>
          ))}
        </Select>
      </div>
      <div className="flex items-center gap-3 lg:ml-auto">
        <Switch
          checked={filters.showPast}
          onCheckedChange={(v) => onChange({ ...filters, showPast: v })}
          label={<span className="whitespace-nowrap text-[13px]">Show past</span>}
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
