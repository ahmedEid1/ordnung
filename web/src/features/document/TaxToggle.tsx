/**
 * "For taxes" on a letter's page (D3): one press marks the letter for taxes, or takes one Claude marked off them —
 * private letters too, and on a paired phone. The choice is the person's own, kept apart from Claude's reading
 * (`tax_choice`; `secretary.tax_choice` on the server): it counts over Claude's mark both ways and stays when the
 * letter is read again. The Tax year page, the export's "Only letters for taxes" and the tax-season Idea follow it.
 *
 * Nothing changes without a press: the toggle or its toast's Undo, which sends exactly the choice shown before the
 * press (`null` when there was none, which brings Claude's mark back). A line under the footer says who decided,
 * when that adds something. Hidden where no choice can be made: a letter waiting from the folder, one being read,
 * one in the trash, a proof file (`taxToggleShown`).
 */
import { Link } from "react-router";
import { Landmark } from "lucide-react";
import type { Document, DocumentDetail } from "@/api/types";
import { useUpdateDocument } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { forTaxes, letterYear } from "@/features/export/selection";
import { focusWhenReady } from "@/features/today/focus";

/** The toggle's id, and its line's (`aria-describedby`). */
const toggleId = (docId: string) => `tax-toggle-${docId}`;
const stateId = (docId: string) => `tax-state-${docId}`;

/** Whether the toggle shows: not for a letter waiting from the folder, one being read, one in the trash or a proof file. */
export function taxToggleShown(doc: Document): boolean {
  if (doc.deleted_at || doc.source === "proof") return false;
  return doc.status !== "held" && doc.status !== "queued" && doc.status !== "processing";
}

/**
 * Who decided, when that adds something: the person (either way), or Claude when it marked the letter without a note
 * of its own (with a note, "Explained simply" says it and links the year). `null`: no line.
 */
export function taxStateLine(doc: Document, choice: boolean | null): string | null {
  if (choice === true) return "You marked this letter for taxes.";
  if (choice === false) return doc.tax_relevant ? "You took this letter off your letters for taxes. Claude had marked it." : null;
  return doc.tax_relevant && !doc.tax_note ? "Claude marked this letter for taxes when it read it." : null;
}

/** The line under the footer's actions, with a link to the letter's tax year while it counts for taxes. */
export function TaxState({ detail }: { detail: DocumentDetail }) {
  const doc = detail.document;
  const choice = detail.tax_choice ?? null;
  const line = taxToggleShown(doc) ? taxStateLine(doc, choice) : null;
  if (!line) return null;
  const year = forTaxes({ tax_relevant: doc.tax_relevant, tax_choice: choice }) ? letterYear(doc) : null;
  return (
    <p id={stateId(doc.id)} className="mt-2 text-[12px] leading-5 text-muted">
      {line}
      {year != null ? (
        <>
          {" "}
          <Link to={`/inbox/taxes?year=${year}`} className="font-medium whitespace-nowrap text-accent underline underline-offset-2 hover:no-underline">
            All letters for taxes from {year}
          </Link>
        </>
      ) : null}
    </p>
  );
}

/** What the toast says after a press: the year's page it is now on (or no longer on), or that an undated letter is in none. */
function pressedToast(on: boolean, year: number | null): { title: string; description?: string } {
  if (on) return { title: "Marked for taxes", description: year != null ? `It's on your Tax year ${year} page.` : "It has no date, so it isn't in any tax year." };
  return year != null ? { title: "Not marked for taxes", description: `It's no longer on your Tax year ${year} page.` } : { title: "Not marked for taxes" };
}

/** The "For taxes" toggle (`aria-pressed`), for the footer's action row. */
export function TaxToggle({ detail }: { detail: DocumentDetail }) {
  const doc = detail.document;
  const update = useUpdateDocument();
  if (!taxToggleShown(doc)) return null;
  const choice = detail.tax_choice ?? null;
  const on = forTaxes({ tax_relevant: doc.tax_relevant, tax_choice: choice });
  const described = taxStateLine(doc, choice) ? stateId(doc.id) : undefined;

  const press = () => {
    const before = choice; // exactly what was shown: Undo puts it back, null included
    const next = !on;
    const said = pressedToast(next, letterYear(doc));
    update.mutateAsync({ id: doc.id, patch: { tax_choice: next } }).then(
      () =>
        toast.success(said.title, {
          description: said.description,
          // a second press replaces this toast: only the newest Undo is offered
          id: `tax-choice-${doc.id}`,
          undo: () =>
            update.mutateAsync({ id: doc.id, patch: { tax_choice: before } }).then(
              // back to the toggle when focus was in the toast or nowhere (never pulled from where the person went)
              () =>
                focusWhenReady(() => {
                  const el = document.getElementById(toggleId(doc.id));
                  return el instanceof HTMLButtonElement && !el.disabled ? el : null;
                }),
              () => undefined, // the hook's toast says it couldn't be saved
            ),
        }),
      () => undefined, // the hook's toast says it couldn't be saved
    );
  };

  return (
    <Button
      id={toggleId(doc.id)}
      size="sm"
      // a toggle keeps its name; whether it is on is aria-pressed, and the accent tint shows it
      variant={on ? "soft" : "secondary"}
      icon={Landmark}
      aria-pressed={on}
      aria-describedby={described}
      loading={update.isPending}
      onClick={press}
    >
      For taxes
    </Button>
  );
}
