import { useMemo, useState } from "react";
import { BookOpen, Calculator, ExternalLink, ScanText, Search } from "lucide-react";
import { useRules, useRulesLastChecked } from "@/api/hooks";
import { ADVICE_LINKS, Disclaimer } from "@/components/ui/Disclaimer";
import { Input } from "@/components/ui/Field";
import { SkeletonText } from "@/components/ui/Skeleton";
import { formatDate } from "@/lib/format";
import { SectionHeading, SettingsCard } from "./SettingsCard";

/** "How dates are computed": the principle, then every rule with its citation and official link. */
export function RulesSection() {
  const rules = useRules();
  const lastChecked = useRulesLastChecked();
  const [q, setQ] = useState("");
  const list = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const all = rules.data ?? [];
    if (!needle) return all;
    return all.filter((r) => [r.title, r.citation, r.summary].some((s) => s.toLowerCase().includes(needle)));
  }, [rules.data, q]);

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
            <div>
              <p className="text-[14px] font-semibold text-ink">1 · Claude reads</p>
              <p className="mt-0.5 text-[13px] leading-5 text-muted">“within one month of delivery” — with the exact sentence, found on the page.</p>
            </div>
          </div>
          <div className="card flex gap-3 p-4">
            <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
              <Calculator className="size-4" aria-hidden />
            </span>
            <div>
              <p className="text-[14px] font-semibold text-ink">2 · The rules compute</p>
              <p className="mt-0.5 text-[13px] leading-5 text-muted">Delivery days, month ends, weekends and your state's holidays — the earlier date when unsure.</p>
            </div>
          </div>
        </div>

        <SettingsCard>
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
            <p className="flex-1 text-[13px] text-muted">
              {rules.data ? `${rules.data.length} rules` : "Rules"}
              {lastChecked ? ` · checked against the law on ${formatDate(lastChecked, { style: "medium" })}` : null}
            </p>
            <div className="relative sm:w-64">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a rule or §…" aria-label="Find a rule" className="pl-9" />
            </div>
          </div>
          {rules.isPending ? (
            <SkeletonText lines={8} />
          ) : list.length ? (
            <ul className="divide-y divide-line">
              {list.map((r) => (
                <li key={r.id} className="py-4 first:pt-1 last:pb-1">
                  <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                    <h3 className="text-[14.5px] font-semibold text-ink">{r.title}</h3>
                    <span className="whitespace-nowrap rounded-md bg-surface-2 px-1.5 py-px text-[12px] font-medium text-ink/75">{r.citation}</span>
                  </div>
                  <p className="mt-1 max-w-2xl text-[13.5px] leading-relaxed text-muted">{r.summary}</p>
                  <p className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-muted">
                    {r.effective_from ? <span>In force since {formatDate(r.effective_from, { style: "medium" })}</span> : null}
                    {r.url ? (
                      <a href={r.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                        <BookOpen className="size-3.5" aria-hidden />
                        Read the law
                        <ExternalLink className="size-3" aria-hidden />
                        <span className="sr-only">(opens in a new tab)</span>
                      </a>
                    ) : null}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-4 text-sm text-muted">No rule matches “{q}”.</p>
          )}
        </SettingsCard>

        <Disclaimer advice={[...ADVICE_LINKS.consumer, ...ADVICE_LINKS.tax]} className="px-1" />
      </div>
    </section>
  );
}
