import { Fragment, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Download, Landmark } from "lucide-react";
import type { Document } from "@/api/types";
import { useDocuments, useParties } from "@/api/hooks";
import { Page, PageHeader } from "@/components/shell/Page";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { Field, Select } from "@/components/ui/Field";
import { LoadError } from "@/components/ui/LoadError";
import { ModelText } from "@/components/ui/ModelText";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { MarkedGerman } from "@/features/document/Explained";
import { englishInline } from "@/features/document/fact-text";
import { ExportLettersDialog, EXPORT_IN_DEMO } from "@/features/export/ExportLettersDialog";
import { LettersList } from "@/features/inbox/LettersList";
import type { OpenSummary } from "@/features/inbox/filters";
import { usePhoneCompanion } from "@/features/phone/client";
import { ComputerOnly, OnYourComputer } from "@/features/phone/ComputerOnly";
import { EXPORT_ON_COMPUTER } from "@/features/phone/copy";
import { TAX_SEASON_SENTENCE, defaultTaxYear, earlyStatements, inTaxSeason, parseTaxYear, taxGroups, taxLetters, taxYears, undatedTaxLetters } from "@/features/taxes/taxYear";
import { isStaticDemo } from "@/mocks/mode";
import { useStickyError } from "@/lib/hooks";
import { useTodayISO } from "@/lib/today";
import { plural } from "@/lib/utils";

const DESCRIPTION =
  "Letters that could matter for your tax return — payslips, insurance, receipts for work or study costs — by the date on the letter. Claude marks them when it reads a letter.";
const NO_TO_DOS = new Map<string, OpenSummary>();

/** Under each letter: Claude's note on why it could matter for taxes ("Marked for taxes." without one). */
function TaxNote({ doc }: { doc: Document }) {
  return (
    <span className="flex items-start gap-1.5 text-k-expiry-ink">
      <Landmark className="mt-[3px] size-3.5 shrink-0" aria-hidden />
      {doc.tax_note ? (
        <span className="min-w-0 [overflow-wrap:anywhere] hyphens-auto">
          <span className="font-medium">For your tax return: </span>
          <ModelText text={doc.tax_note}>
            <MarkedGerman text={englishInline(doc.tax_note)} />
          </ModelText>
        </span>
      ) : (
        <span>Marked for taxes.</span>
      )}
    </span>
  );
}

/** "1 letter for taxes has no date, so it isn't in any year: “Laptop receipt”." — each title a link. */
function UndatedLine({ docs }: { docs: Document[] }) {
  const one = docs.length === 1;
  return (
    <p className="mt-6 text-sm leading-6 text-muted [overflow-wrap:anywhere]">
      {`${plural(docs.length, "letter")} for taxes ${one ? "has" : "have"} no date, so ${one ? "it isn't" : "they aren't"} in any year: `}
      {docs.map((d, i) => (
        <Fragment key={d.id}>
          {i ? ", " : null}“
          <Link to={`/documents/${d.id}`} className="font-medium text-accent underline underline-offset-2 hover:no-underline">
            {d.title ?? d.filename}
          </Link>
          ”
        </Fragment>
      ))}
      .
    </p>
  );
}

/**
 * `/inbox/taxes?year=YYYY` — a year's letters for taxes, grouped by kind, each with its tax note, then the next
 * year's January–May statements; Export (computer only, not in the online demo) takes what the page shows.
 */
export default function TaxYearPage() {
  const today = useTodayISO();
  const staticDemo = isStaticDemo();
  const phone = usePhoneCompanion();
  const [params, setParams] = useSearchParams();
  const all = useDocuments();
  const parties = useParties();
  const [exportOpen, setExportOpen] = useState(false);
  const exportButton = useRef<HTMLButtonElement>(null);
  const lastError = useStickyError(all.error, Boolean(all.data));

  const docs = useMemo(() => all.data ?? [], [all.data]);
  const years = useMemo(() => taxYears(docs), [docs]);
  const undated = useMemo(() => undatedTaxLetters(docs), [docs]);
  const asked = parseTaxYear(params.get("year"));
  const year = asked ?? defaultTaxYear(today, years.map((y) => y.year));
  const letters = useMemo(() => (year != null ? taxLetters(docs, year) : []), [docs, year]);
  const early = useMemo(() => (year != null ? earlyStatements(docs, year, today) : []), [docs, year, today]);
  const groups = useMemo(() => (year != null ? taxGroups(docs, year, today) : []), [docs, year, today]);
  const partyMap = useMemo(() => new Map((parties.data ?? []).map((p) => [p.id, p])), [parties.data]);
  // the year asked for stays a choice even when it has no letters
  const options = year != null && !years.some((y) => y.year === year) ? [...years, { year, count: 0 }].sort((a, b) => b.year - a.year) : years;
  const none = !years.length && !undated.length;
  // while the letters load, the year asked for (a link from the tax Idea) already names the page
  const shown = all.data ? (none ? null : year) : asked;
  const title = shown != null ? `Tax year ${shown}` : "Letters for taxes";

  const chooseYear = (value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("year", value);
        return next;
      },
      { replace: true, preventScrollReset: true },
    );

  // on a paired phone no action at all (an empty one would still take the header's gap)
  const exportAction =
    year != null && !none && !phone ? (
      <Button ref={exportButton} icon={Download} onClick={() => setExportOpen(true)} disabled={staticDemo}>
        Export these letters…
      </Button>
    ) : null;

  return (
    <Page title={title}>
      <PageHeader title={title} description={DESCRIPTION} actions={all.data ? exportAction : null} />

      {!all.data && (all.isError || lastError) ? (
        <LoadError what="your letters" error={all.error ?? lastError} onRetry={() => void all.refetch()} retrying={all.isFetching} />
      ) : all.isPending ? (
        <div aria-busy="true">
          <LoadingLabel>Loading your letters…</LoadingLabel>
          <Skeleton className="mb-6 h-9 w-full rounded-lg sm:w-56" />
          <div className="card divide-y divide-line">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-3.5 px-4 py-3.5 sm:px-5">
                <Skeleton className="h-[54px] w-10 shrink-0 rounded-[4px]" />
                <SkeletonText lines={2} className="min-w-0 flex-1" />
              </div>
            ))}
          </div>
        </div>
      ) : none ? (
        <EmptyState
          illustration="letter"
          title="No letters for taxes yet"
          description="When Claude reads a letter that could matter for your tax return — a payslip, an insurance statement, a receipt for work or study costs — it shows here, by year."
          action={
            <Link to="/inbox" className={buttonVariants({ size: "sm" })}>
              Go to the Inbox
            </Link>
          }
        />
      ) : (
        <>
          {year != null ? (
            <div className="mb-6 space-y-3">
              <Field label="Year" className="w-full sm:max-w-56">
                <Select value={year} onChange={(e) => chooseYear(e.target.value)}>
                  {options.map((y) => (
                    <option key={y.year} value={y.year}>
                      {`${y.year} · ${plural(y.count, "letter")}`}
                    </option>
                  ))}
                </Select>
              </Field>
              <p role="status" className="text-sm leading-6 text-ink/85">
                {`${plural(letters.length, "letter")} dated ${year}.`}
                {inTaxSeason(today, year) ? ` ${TAX_SEASON_SENTENCE}` : null}
              </p>
              {letters.length || early.length ? (
                <ComputerOnly what="Export these letters" fallback={<OnYourComputer>{EXPORT_ON_COMPUTER}</OnYourComputer>}>
                  {staticDemo ? (
                    <p className="rounded-lg bg-surface-2/70 px-3 py-2 text-[12.5px] leading-5 text-muted" role="note">
                      {EXPORT_IN_DEMO}
                    </p>
                  ) : null}
                </ComputerOnly>
              ) : null}
            </div>
          ) : null}

          {year != null && early.length ? (
            <Callout title={`Papers for ${year} that come in ${year + 1}`} className="mb-6">
              Yearly statements — your <span lang="de">Lohnsteuerbescheinigung</span>, and those from insurers and banks — usually arrive between January and May
              and carry the new year's date.{" "}
              {early.length === 1
                ? `The letter for taxes dated January–May ${year + 1} is listed below too; check which year it is for.`
                : `The ${early.length} letters for taxes dated January–May ${year + 1} are listed below too; check which year each is for.`}
            </Callout>
          ) : null}

          {groups.length ? (
            <LettersList groups={groups} parties={partyMap} open={NO_TO_DOS} note={(d) => <TaxNote doc={d} />} />
          ) : year != null ? (
            <EmptyState size="sm" illustration="search" title={`No letters for taxes dated ${year}`} description="Choose another year above." />
          ) : null}

          {undated.length ? <UndatedLine docs={undated} /> : null}
        </>
      )}

      {year != null ? (
        <ExportLettersDialog
          open={exportOpen}
          onClose={() => setExportOpen(false)}
          preset={{ year, tax: true, early: true }}
          returnFocus={exportButton}
        />
      ) : null}
    </Page>
  );
}
