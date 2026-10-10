/**
 * "Export letters": the person chooses a year, a sender and whether only letters for taxes go in; the dialog says
 * how many letters the ZIP will hold and warns that it isn't encrypted. The download is a real link (the browser
 * streams the ZIP to disk), so nothing happens until the person clicks it — and nothing is written in Ordnung.
 */
import { useState, type RefObject } from "react";
import { Download } from "lucide-react";
import type { Document } from "@/api/types";
import { api } from "@/api/endpoints";
import { useDocuments, useParties } from "@/api/hooks";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { Checkbox, Field, Select } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { isStaticDemo } from "@/mocks/mode";
import { useTodayISO } from "@/lib/today";
import { plural } from "@/lib/utils";
import { earlyUntil, exportQuery, exportable, letterYear, selectForExport, zipName, type ExportChoice } from "./selection";

/** Where the dialog starts: a year, only letters for taxes, a sender, and the next year's early statements (`early`). */
export type ExportPreset = ExportChoice & { early?: boolean };

/** Shown where an Export button is in the online demo, which has no files to export. */
export const EXPORT_IN_DEMO = "Exporting isn't available in the online demo — it keeps no files. Install Ordnung to export your own letters.";
/** The warning before every download. */
export const NOT_ENCRYPTED =
  "The ZIP isn't encrypted. Anyone who has it can read these letters — keep it safe and share it only with people you trust, like your tax adviser.";

/** "Also the 3 letters for taxes dated January–May 2026" ("the letter" for one). */
export function earlyLabel(count: number, year: number): string {
  return `Also ${count === 1 ? "the letter" : `the ${count} letters`} for taxes dated January–May ${year + 1}`;
}

export function ExportLettersDialog({
  open,
  onClose,
  preset,
  returnFocus,
}: {
  open: boolean;
  onClose: () => void;
  preset?: ExportPreset;
  returnFocus?: RefObject<HTMLElement | null>;
}) {
  const today = useTodayISO();
  const all = useDocuments({}, { enabled: open });
  const parties = useParties();
  const [choice, setChoice] = useState<ExportPreset>(preset ?? {});
  // each opening starts from the preset again
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setChoice(preset ?? {});
  }

  // (the React Compiler memoizes these)
  const docs = (all.data ?? []).filter(exportable);
  const { year = null, party_id = null, tax = false } = choice;
  // every year with a letter to export, each counted under the rest of the choice (the early statements are named on their own box)
  const yearCounts = countBy(selectForExport(docs, { tax, party_id }), (d) => letterYear(d));
  const years = new Set(docs.map((d) => letterYear(d)));
  if (year != null) years.add(year);
  // the next year's statements a tax year may take: only for a year's letters for taxes, and only those that exist
  const earlyCount =
    year != null && tax ? selectForExport(docs, { year, until: earlyUntil(year), tax, party_id }).filter((d) => letterYear(d) === year + 1).length : 0;
  const until = year != null && earlyCount && choice.early ? earlyUntil(year) : null;
  const effective: ExportChoice = { year, tax, party_id, until };
  const count = selectForExport(docs, effective).length;
  // senders with their letters under the rest of the choice
  const senderCounts = countBy(selectForExport(docs, { year, tax, until }), (d) => d.party_id);
  const withLetters = new Set(docs.map((d) => d.party_id));
  const senders = (parties.data ?? []).filter((p) => withLetters.has(p.id)).sort((a, b) => a.name.localeCompare(b.name));

  const staticDemo = isStaticDemo();
  const name = zipName(effective, today);
  const loading = open && all.isPending;
  const set = (patch: Partial<ExportPreset>) => setChoice((c) => ({ ...c, ...patch }));
  const downloaded = () => {
    onClose();
    toast.success("Your letters are downloading", { description: `Your browser saves ${name}. It isn't encrypted.` });
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="md"
      title="Export letters"
      description="Your letters as their original files, in folders by year and sender, with a list of them (index.csv) that opens in a spreadsheet."
      returnFocus={returnFocus}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          {count && !staticDemo && !loading ? (
            <a href={api.lettersZipUrl(exportQuery(effective))} download={name} onClick={downloaded} className={buttonVariants({ variant: "primary" })}>
              <Download aria-hidden />
              Download ZIP
            </a>
          ) : (
            <Button variant="primary" icon={Download} disabled>
              Download ZIP
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-[12.5px] leading-5 text-muted [overflow-wrap:anywhere]">
          For example: <span lang="de">2025 / Finanzamt Musterstadt / 2025-03-14 Steuerbescheid 2025.pdf</span>
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Year">
            <Select value={year ?? ""} onChange={(e) => set({ year: e.target.value ? Number(e.target.value) : null })}>
              <option value="">All years</option>
              {[...years]
                .filter((y): y is number => y != null)
                .sort((a, b) => b - a)
                .map((y) => (
                  <option key={y} value={y}>
                    {`${y} · ${plural(yearCounts.get(y) ?? 0, "letter")}`}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label="Sender">
            <Select value={party_id ?? ""} onChange={(e) => set({ party_id: e.target.value || null })}>
              <option value="">Every sender</option>
              {senders.map((p) => (
                <option key={p.id} value={p.id}>
                  {`${p.name} · ${plural(senderCounts.get(p.id) ?? 0, "letter")}`}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Checkbox label="Only letters for taxes" checked={tax} onChange={(e) => set({ tax: e.target.checked })} />
        {year != null && earlyCount ? (
          <Checkbox
            label={earlyLabel(earlyCount, year)}
            description={`Yearly statements for ${year} often arrive then.`}
            checked={Boolean(choice.early)}
            onChange={(e) => set({ early: e.target.checked })}
          />
        ) : null}
        <p role="status" className="text-sm font-medium text-ink">
          {loading ? "Counting your letters…" : count ? `${plural(count, "letter")} will be in the ZIP.` : "No letters match. Choose another year or sender."}
        </p>
        <Callout tone="warn">{NOT_ENCRYPTED}</Callout>
        {staticDemo ? (
          <p className="rounded-lg bg-surface-2/70 px-3 py-2 text-[12.5px] leading-5 text-muted" role="note">
            {EXPORT_IN_DEMO}
          </p>
        ) : null}
        <p className="text-[12.5px] leading-5 text-muted">Letters you wrote in Ordnung aren't included — download each one's PDF under Letters.</p>
      </div>
    </Dialog>
  );
}

/** How many of `docs` share each key (letters with a null key counted under null). */
function countBy<K>(docs: readonly Document[], key: (d: Document) => K): Map<K, number> {
  const counts = new Map<K, number>();
  for (const d of docs) counts.set(key(d), (counts.get(key(d)) ?? 0) + 1);
  return counts;
}
