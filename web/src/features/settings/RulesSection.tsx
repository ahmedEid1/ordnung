import { useMemo, useRef, useState } from "react";
import { BookOpen, Calculator, ExternalLink, ScanText, Search, X } from "lucide-react";
import { useRules, useRulesLastChecked } from "@/api/hooks";
import type { RuleInfo } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { ADVICE_LINKS, Disclaimer } from "@/components/ui/Disclaimer";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Field";
import { LoadError } from "@/components/ui/LoadError";
import { SkeletonText } from "@/components/ui/Skeleton";
import { formatDate } from "@/lib/format";
import { cn, plural, prefersReducedMotion } from "@/lib/utils";
import { groupRules, matchesRule, splitCitation } from "./logic";
import { SectionHeading, SettingsCard } from "./SettingsCard";

const topicId = (i: number) => `rules-topic-${i}`;

/** One rule: title, each legal source as its own chip (they wrap, never clip), summary, link. */
function Rule({ r }: { r: RuleInfo }) {
  return (
    <li className="py-4 first:pt-3 last:pb-1">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h4 className="mr-0.5 text-md font-semibold leading-snug text-ink">{r.title}</h4>
        {splitCitation(r.citation).map((c) => (
          <span key={c} className="max-w-full rounded-md bg-surface-2 px-1.5 py-px text-xs font-medium text-ink/75 wrap-anywhere">
            {c}
          </span>
        ))}
      </div>
      <p className="mt-1 max-w-2xl text-base leading-relaxed text-muted">{r.summary}</p>
      {r.effective_from || r.url ? (
        <p className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
          {r.effective_from ? <span>In force since {formatDate(r.effective_from, { style: "medium" })}</span> : null}
          {r.url ? (
            <a href={r.url} target="_blank" rel="noreferrer noopener" className="inline-flex min-h-6 items-center gap-1 font-medium text-accent hover:underline">
              <BookOpen className="size-3.5 shrink-0" aria-hidden />
              Read the law <span className="sr-only">on “{r.title}” (opens in a new tab)</span>
              <ExternalLink className="size-3 shrink-0" aria-hidden />
            </a>
          ) : null}
        </p>
      ) : null}
    </li>
  );
}

/** "How dates are computed": the principle, then every rule by topic with its citations and official link. */
export function RulesSection() {
  const rules = useRules();
  const lastChecked = useRulesLastChecked();
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const total = rules.data?.length ?? 0;
  const searching = q.trim() !== "";
  const list = useMemo(() => (rules.data ?? []).filter((r) => matchesRule(r, q)), [rules.data, q]);
  const groups = useMemo(() => groupRules(list), [list]);

  const clear = () => {
    setQ("");
    inputRef.current?.focus();
  };
  const jumpTo = (i: number) => {
    const h = listRef.current?.querySelector<HTMLElement>(`#${topicId(i)}`);
    if (!h) return;
    h.scrollIntoView?.({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
    h.focus({ preventScroll: true });
  };

  const count = searching ? `${list.length} of ${plural(total, "rule")}` : plural(total, "rule");

  return (
    <section aria-labelledby="set-rules">
      <SectionHeading
        id="set-rules"
        title="How dates are computed"
        description="The AI never decides a date. It reads what the letter says; tested rules turn that into a date — and every date shows its reasons under “Why this date?”."
      />
      <div className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="card flex gap-3 p-4">
            <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
              <ScanText className="size-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-base font-semibold text-ink">1 · Claude reads</p>
              <p className="mt-0.5 text-sm leading-5 text-muted">“within one month of delivery” — with the exact sentence, found on the page.</p>
            </div>
          </div>
          <div className="card flex gap-3 p-4">
            <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
              <Calculator className="size-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-base font-semibold text-ink">2 · The rules compute</p>
              <p className="mt-0.5 text-sm leading-5 text-muted">Delivery days, month ends, weekends and your state's holidays — the earlier date when unsure.</p>
            </div>
          </div>
        </div>

        <SettingsCard>
          {rules.isError ? (
            <LoadError what="the rules" error={rules.error} onRetry={() => void rules.refetch()} retrying={rules.isFetching} headingLevel={3} variant="plain" size="sm" />
          ) : (
            <>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <p className="flex-1 text-sm text-muted" aria-hidden={searching || undefined}>
                  {rules.data ? count : "Rules"}
                  {lastChecked && !searching ? ` · checked against the law on ${formatDate(lastChecked, { style: "medium" })}` : null}
                </p>
                {/* the count while searching, for screen readers (the line above shows it) */}
                <p role="status" className="sr-only">
                  {searching && rules.data ? (list.length ? `${count} match “${q.trim()}”` : `No rule matches “${q.trim()}”`) : ""}
                </p>
                <div className="relative sm:w-64">
                  <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
                  <Input
                    ref={inputRef}
                    type="search"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Escape" && q) {
                        e.preventDefault();
                        setQ("");
                      }
                    }}
                    placeholder="Find a rule or §…"
                    aria-label="Find a rule"
                    enterKeyHint="search"
                    className="pl-9 pr-9 [&::-webkit-search-cancel-button]:hidden"
                  />
                  {q ? (
                    <button
                      type="button"
                      onClick={clear}
                      className="absolute right-1.5 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
                      aria-label="Clear search"
                    >
                      <X className="size-3.5" aria-hidden />
                    </button>
                  ) : null}
                </div>
              </div>

              {groups.length > 1 ? (
                <nav aria-label="Rule topics" className="mt-4">
                  <ul className="flex flex-wrap gap-1.5">
                    {groups.map((g, i) => (
                      <li key={g.topic} className="min-w-0 max-w-full">
                        <button
                          type="button"
                          onClick={() => jumpTo(i)}
                          aria-label={`${g.topic}, ${plural(g.rules.length, "rule")}`}
                          className="inline-flex min-h-7 max-w-full items-center gap-1.5 rounded-full border border-line px-2.5 py-0.5 text-left text-sm text-muted transition-colors hover:bg-surface-2 hover:text-ink"
                        >
                          <span className="min-w-0 wrap-anywhere">{g.topic}</span>
                          <span className="shrink-0 rounded-full bg-surface-2 px-1.5 text-xs font-medium tabular-nums text-muted">{g.rules.length}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </nav>
              ) : null}

              {rules.isPending ? (
                <SkeletonText lines={8} className="mt-4" />
              ) : list.length ? (
                <div ref={listRef} className="mt-2">
                  {groups.map((g, i) => (
                    <section key={g.topic} aria-labelledby={topicId(i)} className={cn("pt-4", i > 0 && "mt-2 border-t border-line")}>
                      <h3 id={topicId(i)} tabIndex={-1} className="eyebrow rounded-sm">
                        {g.topic}
                      </h3>
                      <ul className="divide-y divide-line">
                        {g.rules.map((r) => (
                          <Rule key={r.id} r={r} />
                        ))}
                      </ul>
                    </section>
                  ))}
                </div>
              ) : (
                <EmptyState
                  size="sm"
                  variant="plain"
                  illustration="search"
                  headingLevel={3}
                  title={`No rule matches “${q.trim()}”`}
                  description="Try a word from the letter (“objection”, “notice”) or a § number."
                  action={
                    <Button size="sm" icon={X} onClick={clear}>
                      Clear search
                    </Button>
                  }
                  className="mt-2"
                />
              )}
            </>
          )}
        </SettingsCard>

        <Disclaimer advice={[...ADVICE_LINKS.consumer, ...ADVICE_LINKS.tax]} className="px-1" />
      </div>
    </section>
  );
}
