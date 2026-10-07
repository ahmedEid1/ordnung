/**
 * My numbers: every number forms, portals and hotlines ask for, read from the letters and sorted by
 * whose it is (`GET /api/numbers`, `ordnung/numbers.py`): About you (with your identity documents),
 * Open cases and a call sheet per organisation. Values are hidden until "Show"; Copy works either way.
 * URL state: `?tab=you|cases|organisations`.
 *
 * On a paired phone the API sends your numbers with only their last 4 characters (`masked`): someone holding the
 * phone can't read them, and the full numbers are on the computer (each row says so, `NumberRow`).
 */
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { IdCard, Lock, Plus, Search, UserRound } from "lucide-react";
import { useNumbers } from "@/api/hooks";
import type { MyNumbers } from "@/api/types";
import { PageHeader } from "@/components/shell/Page";
import { useAddLetters } from "@/components/shell/AddLetters";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Field";
import { LoadError } from "@/components/ui/LoadError";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { Tabs, type TabItem } from "@/components/ui/Tabs";
import { usePhoneCompanion } from "@/features/phone/client";
import { filesStay, NUMBERS_MASKED } from "@/features/phone/copy";
import { plural } from "@/lib/utils";
import { CallSheetCard, DocumentCard, OpenCaseCard } from "./cards";
import { NumberRow } from "./NumberRow";
import { useStickyError } from "@/lib/hooks";

export type NumbersTab = "you" | "cases" | "organisations";
const TABS: NumbersTab[] = ["you", "cases", "organisations"];
const DESCRIPTION =
  "The numbers forms, portals and hotlines ask for — read from your letters and sorted by whose they are. Hidden on screen until you choose Show.";
/** On a paired phone, whose numbers come masked (nothing to show or hide). */
const PHONE_DESCRIPTION = "The numbers forms, portals and hotlines ask for — read from your letters and sorted by whose they are.";

/**
 * Cards side by side as the column allows, each at least 20rem (never wider than a phone). The cards
 * of a row are as tall as its tallest (the grid's default stretch): no ragged gaps, and each card's
 * "From / Latest letter / Last letter" line sits at its foot (`mt-auto`), level with its neighbours'.
 */
export const CARD_GRID = "grid grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))] gap-4";

type Sheet = MyNumbers["organisations"][number];

/**
 * Where a search finds a call sheet: `sheet` (its name, or a number of yours or of an open case),
 * `theirs` (only among the organisation's own numbers, which are folded away — the card opens them) or
 * nowhere (`null`).
 */
export function sheetMatch(sheet: Sheet, query: string): "sheet" | "theirs" | null {
  const q = query.trim().toLowerCase();
  if (!q) return "sheet";
  const flat = q.replace(/[\s./-]+/g, "");
  const hit = (n: Sheet["numbers"][number]) =>
    n.label.toLowerCase().includes(q) || (flat.length >= 3 && n.value.toLowerCase().replace(/[\s./-]+/g, "").includes(flat));
  if (sheet.name.toLowerCase().includes(q) || [...sheet.numbers, ...sheet.open_cases.flatMap((c) => c.references)].some(hit)) return "sheet";
  return sheet.their_numbers.some(hit) ? "theirs" : null;
}

/** Search the call sheets: the organisation's name or any number on its sheet. */
export function matchesSheet(sheet: Sheet, query: string): boolean {
  return sheetMatch(sheet, query) !== null;
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
  const phone = usePhoneCompanion();
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
        <Lock className="size-3.5 shrink-0" aria-hidden /> {filesStay(phone)}
      </p>
    </EmptyState>
  );
}

function AboutYou({ data }: { data: MyNumbers }) {
  if (!data.about_you.length && !data.documents.length) {
    return (
      <EmptyState
        headingLevel={2}
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
          <SectionHeader id="numbers-you-title" icon={UserRound} title="Your numbers" count={data.about_you.length} />
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
          <SectionHeader id="numbers-docs-title" icon={IdCard} title="Your documents" count={data.documents.length} />
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
        headingLevel={2}
        size="sm"
        illustration="clear"
        title="No open cases"
        description="A case reference (Aktenzeichen, Kassenzeichen, invoice number) shows here while its letter has something left to do."
      />
    );
  }
  // the tab names the panel on screen; the h2 puts the cards' h3 titles under a heading of their own
  return (
    <section aria-labelledby="numbers-cases-title">
      <h2 id="numbers-cases-title" className="sr-only">
        Open cases
      </h2>
      <ul className={CARD_GRID} aria-label={plural(data.open_cases.length, "open case")}>
        {data.open_cases.map((found) => (
          <li key={found.key} className="flex min-w-0">
            <OpenCaseCard found={found} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function Organisations({ data }: { data: MyNumbers }) {
  const [query, setQuery] = useState("");
  const shown = useMemo(
    () => data.organisations.map((s) => ({ sheet: s, match: sheetMatch(s, query) })).filter((m) => m.match !== null),
    [data.organisations, query],
  );
  if (!data.organisations.length) {
    return (
      <EmptyState
        headingLevel={2}
        size="sm"
        illustration="contract"
        title="No organisations yet"
        description="Customer, contract and member numbers appear here, with each organisation's phone and e-mail, once a letter shows them."
      />
    );
  }
  return (
    <section aria-labelledby="numbers-orgs-title">
      <h2 id="numbers-orgs-title" className="sr-only">
        Organisations
      </h2>
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
          // whole in a 320 px wide field; the label says it in full
          placeholder="Find an organisation or number…"
          enterKeyHint="search"
          className="pl-9"
        />
      </div>
      <p className="sr-only" aria-live="polite">
        {query ? `${plural(shown.length, "organisation")} found` : ""}
      </p>
      {shown.length ? (
        <ul className={CARD_GRID} aria-label={plural(shown.length, "organisation")}>
          {shown.map(({ sheet, match }) => (
            <li key={sheet.party_id} className="flex min-w-0">
              <CallSheetCard sheet={sheet} openTheirs={match === "theirs"} />
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
    </section>
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
  const lastError = useStickyError(q.error, Boolean(q.data));
  const failed = !q.data && (q.isError || Boolean(lastError));
  // a paired phone gets your numbers masked: the full ones are on the computer
  const phone = usePhoneCompanion();
  const masked = Boolean(q.data?.masked);

  const header = <PageHeader title="My numbers" description={phone ? PHONE_DESCRIPTION : DESCRIPTION} />;
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
    { value: "organisations", label: "Organisations", shortLabel: "Orgs", count: data.organisations.length },
  ];
  return (
    <>
      {header}
      {masked ? (
        <Callout tone="info" icon={Lock} className="mb-6">
          {NUMBERS_MASKED}
        </Callout>
      ) : null}
      <Tabs id="numbers" label="Which numbers" items={items} value={tab} onChange={setTab} fill className="mb-6" />
      {/* no tabindex: the panel's first control (a Show button) takes the focus after the tabs */}
      <div role="tabpanel" id={`numbers-panel-${tab}`} aria-labelledby={`numbers-tab-${tab}`}>
        {tab === "you" ? <AboutYou data={data} /> : tab === "cases" ? <OpenCases data={data} /> : <Organisations data={data} />}
      </div>
    </>
  );
}
