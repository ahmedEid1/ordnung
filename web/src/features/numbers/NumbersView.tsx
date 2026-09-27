/**
 * My numbers: every number forms, portals and hotlines ask for, read from the letters and sorted by
 * whose it is (`GET /api/numbers`, `ordnung/numbers.py`): About you (with your identity documents),
 * Open cases and a call sheet per organisation. Values are hidden until "Show"; Copy works either way.
 * URL state: `?tab=you|cases|organisations`.
 */
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { IdCard, Lock, Plus, Search, UserRound } from "lucide-react";
import { useNumbers } from "@/api/hooks";
import type { MyNumbers } from "@/api/types";
import { PageHeader } from "@/components/shell/Page";
import { useAddLetters } from "@/components/shell/AddLetters";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Field";
import { LoadError } from "@/components/ui/LoadError";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { Tabs, type TabItem } from "@/components/ui/Tabs";
import { plural } from "@/lib/utils";
import { CallSheetCard, DocumentCard, OpenCaseCard } from "./cards";
import { NumberRow } from "./NumberRow";

export type NumbersTab = "you" | "cases" | "organisations";
const TABS: NumbersTab[] = ["you", "cases", "organisations"];
const DESCRIPTION =
  "The numbers forms, portals and hotlines ask for — read from your letters and sorted by whose they are. Hidden on screen until you choose Show.";

/** Cards side by side as the column allows, each at least 20rem (never wider than a phone). */
const CARD_GRID = "grid grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))] items-start gap-4";

/** Search the call sheets: the organisation's name or any number on its sheet. */
export function matchesSheet(sheet: MyNumbers["organisations"][number], query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const flat = q.replace(/[\s./-]+/g, "");
  const values = [...sheet.numbers, ...sheet.their_numbers, ...sheet.open_cases.flatMap((c) => c.references)];
  return (
    sheet.name.toLowerCase().includes(q) ||
    values.some((n) => n.label.toLowerCase().includes(q) || (flat.length >= 3 && n.value.toLowerCase().replace(/[\s./-]+/g, "").includes(flat)))
  );
}

function NumbersSkeleton() {
  return (
    <div aria-busy="true">
      <LoadingLabel>Loading your numbers…</LoadingLabel>
      <div className="mb-6 flex gap-4" aria-hidden>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-8 w-28 rounded-lg" />
        ))}
      </div>
      <div className="card divide-y divide-line px-4 sm:px-5" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3 py-4">
            <div className="flex-1">
              <Skeleton className="h-3 w-40" />
              <Skeleton className="mt-2 h-5 w-52" />
            </div>
            <Skeleton className="h-8 w-32 rounded-lg" />
          </div>
        ))}
      </div>
      <div className={`${CARD_GRID} mt-6`} aria-hidden>
        {[0, 1].map((i) => (
          <div key={i} className="card p-4 sm:p-5">
            <SkeletonText lines={3} />
          </div>
        ))}
      </div>
    </div>
  );
}

function FirstRun() {
  const { openPicker, uploading } = useAddLetters();
  return (
    <EmptyState
      illustration="letter"
      title="No numbers yet"
      description="Your Steuer-ID, social insurance number, customer numbers and case references appear here as soon as a letter shows them."
      action={
        <Button variant="primary" icon={Plus} onClick={openPicker} loading={uploading}>
          Add letters
        </Button>
      }
    >
      <p className="mt-5 inline-flex items-center gap-1.5 text-sm text-muted">
        <Lock className="size-3.5 shrink-0" aria-hidden /> Your files stay on this computer.
      </p>
    </EmptyState>
  );
}

function AboutYou({ data }: { data: MyNumbers }) {
  if (!data.about_you.length && !data.documents.length) {
    return (
      <EmptyState
        headingLevel={3}
        size="sm"
        illustration="letter"
        title="Nothing about you yet"
        description="Your Steuer-ID, social insurance and student numbers, and your passport and residence permit, appear here once a letter shows them."
      />
    );
  }
  return (
    <div className="flex flex-col gap-8">
      {data.about_you.length ? (
        <section aria-labelledby="numbers-you-title">
          <SectionHeader id="numbers-you-title" level={3} icon={UserRound} title="Your numbers" count={data.about_you.length} />
          <Card padding="none" className="px-4 sm:px-5">
            <ul className="divide-y divide-line">
              {data.about_you.map((n) => (
                <li key={n.key}>
                  <NumberRow number={n} showParty />
                </li>
              ))}
            </ul>
          </Card>
        </section>
      ) : null}
      {data.documents.length ? (
        <section aria-labelledby="numbers-docs-title">
          <SectionHeader id="numbers-docs-title" level={3} icon={IdCard} title="Your documents" count={data.documents.length} />
          <ul className={CARD_GRID}>
            {data.documents.map((doc) => (
              <li key={doc.key} className="flex min-w-0">
                <DocumentCard doc={doc} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function OpenCases({ data }: { data: MyNumbers }) {
  if (!data.open_cases.length) {
    return (
      <EmptyState
        headingLevel={3}
        size="sm"
        illustration="clear"
        title="No open cases"
        description="A case reference (Aktenzeichen, Kassenzeichen, invoice number) shows here while its letter has something left to do."
      />
    );
  }
  return (
    <ul className={CARD_GRID} aria-label={plural(data.open_cases.length, "open case")}>
      {data.open_cases.map((found) => (
        <li key={found.key} className="flex min-w-0">
          <OpenCaseCard found={found} />
        </li>
      ))}
    </ul>
  );
}

function Organisations({ data }: { data: MyNumbers }) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => data.organisations.filter((s) => matchesSheet(s, query)), [data.organisations, query]);
  if (!data.organisations.length) {
    return (
      <EmptyState
        headingLevel={3}
        size="sm"
        illustration="contract"
        title="No organisations yet"
        description="Customer, contract and member numbers appear here, with each organisation's phone and e-mail, once a letter shows them."
      />
    );
  }
  return (
    <div>
      <div className="relative mb-4 max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <label htmlFor="numbers-search" className="sr-only">
          Find an organisation or a number
        </label>
        <Input
          id="numbers-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find an organisation or a number…"
          enterKeyHint="search"
          className="pl-9"
        />
      </div>
      <p className="sr-only" aria-live="polite">
        {query ? `${plural(shown.length, "organisation")} found` : ""}
      </p>
      {shown.length ? (
        <ul className={CARD_GRID} aria-label={plural(shown.length, "organisation")}>
          {shown.map((sheet) => (
            <li key={sheet.party_id} className="flex min-w-0">
              <CallSheetCard sheet={sheet} />
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          headingLevel={3}
          size="sm"
          illustration="search"
          title="No organisation matches"
          description={`Nothing on your call sheets matches “${query.trim()}”.`}
          action={
            <Button variant="secondary" onClick={() => setQuery("")}>
              Clear search
            </Button>
          }
        />
      )}
    </div>
  );
}

export function NumbersView() {
  const q = useNumbers();
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab") as NumbersTab | null;
  const tab: NumbersTab = raw && TABS.includes(raw) ? raw : "you";
  const setTab = (next: NumbersTab) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next === "you") p.delete("tab");
        else p.set("tab", next);
        return p;
      },
      { replace: true, preventScrollReset: true },
    );

  // a retry of a failed load starts over as "pending": keep the message on screen meanwhile
  const [lastError, setLastError] = useState<unknown>(null);
  if (q.error && q.error !== lastError) setLastError(q.error);
  else if (q.data && lastError !== null) setLastError(null);
  const failed = !q.data && (q.isError || lastError !== null);

  const header = <PageHeader title="My numbers" description={DESCRIPTION} />;
  if (failed) {
    return (
      <>
        {header}
        <LoadError what="your numbers" error={q.error ?? lastError} onRetry={() => void q.refetch()} retrying={q.isFetching} />
      </>
    );
  }
  if (!q.data) {
    return (
      <>
        {header}
        <NumbersSkeleton />
      </>
    );
  }
  const data = q.data;
  if (!data.about_you.length && !data.documents.length && !data.organisations.length && !data.open_cases.length) {
    return (
      <>
        {header}
        <FirstRun />
      </>
    );
  }

  const items: TabItem<NumbersTab>[] = [
    { value: "you", label: "About you", shortLabel: "You", count: data.about_you.length + data.documents.length },
    { value: "cases", label: "Open cases", shortLabel: "Cases", count: data.open_cases.length },
    { value: "organisations", label: "Organisations", count: data.organisations.length },
  ];
  return (
    <>
      {header}
      <Tabs id="numbers" label="Which numbers" items={items} value={tab} onChange={setTab} fill className="mb-6" />
      {/* no tabindex: the panel's first control (a Show button) takes the focus after the tabs */}
      <div role="tabpanel" id={`numbers-panel-${tab}`} aria-labelledby={`numbers-tab-${tab}`}>
        {tab === "you" ? <AboutYou data={data} /> : tab === "cases" ? <OpenCases data={data} /> : <Organisations data={data} />}
      </div>
    </>
  );
}
