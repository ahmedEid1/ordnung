import { Bar, BarChart, LabelList, Tooltip, XAxis, YAxis } from "recharts";
import { useReducedMotion } from "motion/react";
import { formatCompact, formatUsd } from "@/lib/format";
import type { PurposeRow } from "./logic";

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: PurposeRow }[] }) {
  const row = active ? payload?.[0]?.payload : null;
  if (!row) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-[12.5px] shadow-[var(--shadow-pop)]">
      <p className="font-semibold text-ink">{row.label}</p>
      <p className="mt-0.5 text-muted">
        {row.calls} {row.calls === 1 ? "call" : "calls"} · {formatCompact(row.tokens)} tokens
      </p>
      <p className="font-medium tabular-nums text-ink">{formatUsd(row.cost)} API-equivalent</p>
    </div>
  );
}

/**
 * API-equivalent cost by purpose — one series, so one hue (the accent), thin bars with rounded
 * data ends, values at the bar tips and a per-bar tooltip. The table next to it carries the same
 * numbers for screen readers. From 640 px only: phones get a list of rows (`UsageBars`), since the
 * axis labels would leave the bars no room.
 */
export function UsageChart({ rows }: { rows: PurposeRow[] }) {
  const reduce = useReducedMotion();
  if (!rows.length) return null;
  const height = rows.length * 38 + 8;
  return (
    <div aria-hidden className="w-full">
      {/* hidden from assistive tech (the sr-only table has the numbers), so no keyboard layer either;
          `responsive` sizes it with CSS (ResponsiveContainer measures through a zero-width box) */}
      <BarChart
        responsive
        style={{ width: "100%", height }}
        data={rows}
        layout="vertical"
        margin={{ top: 0, right: 64, bottom: 0, left: 0 }}
        barCategoryGap={10}
        accessibilityLayer={false}
      >
        <XAxis type="number" hide domain={[0, "dataMax"]} />
        <YAxis type="category" dataKey="label" width={168} axisLine={false} tickLine={false} tick={{ fill: "var(--color-muted)", fontSize: 12.5 }} />
        <Tooltip cursor={{ fill: "var(--color-surface-2)" }} content={<ChartTooltip />} isAnimationActive={false} />
        <Bar dataKey="cost" fill="var(--color-accent)" radius={[0, 4, 4, 0]} barSize={16} isAnimationActive={!reduce} minPointSize={2}>
          <LabelList dataKey="cost" position="right" formatter={(v: unknown) => formatUsd(Number(v))} fill="var(--color-ink)" fontSize={12} />
        </Bar>
      </BarChart>
    </div>
  );
}
