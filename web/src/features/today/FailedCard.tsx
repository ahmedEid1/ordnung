/**
 * "2 letters couldn't be read — Try again": letters whose reading failed (Claude missing or signed out, an
 * answer Ordnung couldn't use). They are in no other part of Today: until they are read, Ordnung doesn't
 * know what they ask or by when — so Today says so instead of "All clear" (UX U2: Today said "All clear"
 * three times while the Inbox said "Please check 2"). "Try again" reads each of them again; a letter's own
 * page says why its reading failed.
 */
import { Link } from "react-router";
import { motion } from "motion/react";
import { ArrowRight, RotateCw, TriangleAlert } from "lucide-react";
import type { Document } from "@/api/types";
import { useReprocessDocuments } from "@/api/hooks";
import { Button, buttonVariants } from "@/components/ui/Button";
import { plural } from "@/lib/utils";
import { fadeUp } from "./motion";

/** "2 letters couldn't be read" — the card's heading, and what Top 3 says instead of "All clear". */
export function failedTitle(count: number): string {
  return `${plural(count, "letter")} couldn't be read`;
}

export function FailedCard({ docs }: { docs: Document[] }) {
  const retry = useReprocessDocuments();
  if (!docs.length) return null;
  const one = docs.length === 1;
  const ids = docs.map((d) => d.id);
  return (
    <motion.section
      variants={fadeUp}
      aria-labelledby="failed-card-title"
      className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-[var(--radius-card)] border border-warn/30 bg-warn-soft/60 p-4 sm:p-5"
    >
      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-surface text-warn shadow-[var(--shadow-card)]">
        <TriangleAlert className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 basis-44">
        <h2 id="failed-card-title" className="text-[15px] font-semibold leading-snug text-warn-ink">
          {failedTitle(docs.length)}
        </h2>
        <p className="mt-0.5 text-[13.5px] leading-snug text-ink/80">
          Ordnung can't tell you what {one ? "it asks" : "they ask"} or by when until {one ? "it's" : "they're"} read.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2 max-sm:w-full">
        {/* not disabled while it works: a disabled button would drop keyboard focus (UX U4) */}
        <Button
          variant="primary"
          size="sm"
          icon={RotateCw}
          aria-disabled={retry.isPending || undefined}
          aria-busy={retry.isPending || undefined}
          onClick={() => {
            if (!retry.isPending) retry.mutate(ids);
          }}
          className="max-sm:flex-1"
        >
          Try again
        </Button>
        <Link
          to={one ? `/documents/${encodeURIComponent(docs[0]!.id)}` : "/inbox?filter=check"}
          className={buttonVariants({ variant: "ghost", size: "sm", className: "max-sm:flex-1" })}
        >
          {one ? "Open it" : "See them"}
          <ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>
    </motion.section>
  );
}
