/**
 * "Needs your attention" — the watched folder, calendar sync or the morning notification stopped working
 * (`features/settings/attention.ts`). One quiet card on Today, each line linking to its Settings section;
 * nothing when all is well.
 */
import { Link } from "react-router";
import { motion } from "motion/react";
import { TriangleAlert } from "lucide-react";
import { useBackgroundProblems } from "@/features/settings/attention";
import { fadeUp } from "./motion";

export function AttentionCard() {
  const problems = useBackgroundProblems();
  if (!problems.length) return null;
  return (
    <motion.section
      variants={fadeUp}
      aria-labelledby="attention-card-title"
      data-testid="attention-card"
      className="rounded-[var(--radius-card)] border border-warn/30 bg-warn-soft/60 p-4 sm:p-5"
    >
      <h2 id="attention-card-title" className="flex items-center gap-2 text-[15px] font-semibold leading-snug text-warn-ink">
        <TriangleAlert className="size-4 shrink-0" aria-hidden />
        Needs your attention
      </h2>
      <ul className="mt-2 flex flex-col gap-2">
        {problems.map((p) => (
          <li key={p.section} className="text-[13.5px] leading-snug text-ink/85 [overflow-wrap:anywhere]">
            <span className="font-medium text-ink">{p.title}.</span> {p.detail}{" "}
            <Link
              to={`/settings?section=${p.section}`}
              className="inline-block min-h-6 whitespace-nowrap rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
            >
              Open Settings
            </Link>
          </li>
        ))}
      </ul>
    </motion.section>
  );
}
