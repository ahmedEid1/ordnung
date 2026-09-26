import { Link } from "react-router";
import { motion } from "motion/react";
import type { AreaStatus } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Countdown } from "@/components/ui/Countdown";
import { KindIcon } from "@/components/ui/KindBadge";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { AREA_STATUS_COPY, areaLabel, copyFor } from "@/lib/copy";
import { fadeUp, stagger } from "./motion";

function AreaTile({ area }: { area: AreaStatus }) {
  const status = copyFor(AREA_STATUS_COPY, area.status);
  const label = areaLabel(area.area);
  // "Needs attention" / "Urgent" in words and an icon, not only a colour (WCAG 1.4.1); an area
  // that is fine says so to screen readers and stays quiet on screen
  const flagged = area.status !== "ok";
  return (
    <motion.li variants={fadeUp}>
      <Link
        to={`/timeline?area=${encodeURIComponent(area.area)}`}
        className="card group flex h-full flex-col p-3.5 outline-none transition-[box-shadow,border-color,transform] duration-200 hover:-translate-y-px hover:border-line-strong hover:shadow-[var(--shadow-pop)] focus-visible:ring-2 focus-visible:ring-accent motion-reduce:hover:translate-y-0 sm:p-4"
      >
        <span className="flex items-center gap-2">
          <KindIcon area={area.area} size="sm" />
          <span className="min-w-0 flex-1 text-[14px] font-semibold leading-tight text-ink [overflow-wrap:anywhere]">{label}</span>
          {flagged ? null : <span className="sr-only">{status.label}</span>}
        </span>
        {flagged ? (
          <Badge tone={status.tone} icon={status.icon} className="mt-2 self-start" data-status={area.status}>
            {status.label}
          </Badge>
        ) : null}
        <span className="mt-2.5 line-clamp-2 text-[13px] leading-snug text-ink/85" title={area.headline}>
          {area.headline}
        </span>
        {area.next_date ? <Countdown date={area.next_date} className="mt-auto pt-2 text-[12px]" /> : null}
      </Link>
    </motion.li>
  );
}

/** "Life at a glance": one tile per area of life that has data (status, headline, next date). */
export function LifeAtAGlance({ areas }: { areas: AreaStatus[] }) {
  if (!areas.length) return null;
  return (
    <motion.section variants={fadeUp} aria-labelledby="areas-title">
      <SectionHeader id="areas-title" title="Life at a glance" />
      {/* one column on the smallest phones, where two tiles would squeeze their names */}
      <motion.ul variants={stagger} className="grid grid-cols-1 gap-3 min-[360px]:grid-cols-2 sm:grid-cols-3">
        {areas.map((a) => (
          <AreaTile key={a.area} area={a} />
        ))}
      </motion.ul>
    </motion.section>
  );
}
