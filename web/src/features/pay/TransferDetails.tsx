/**
 * What both Pay panels — Today's and the letter's — show the same way: the transfer details under one
 * set of names, in the order a German bank form asks for them (Recipient, IBAN, Amount, Reference),
 * each in full with a copy button that says "Copied" in place; the IBAN's check; and the footer with
 * "Mark as paid" (UI audit round 2: "To" / "I've paid it" on one page, "Recipient" / "Mark as paid"
 * on the other). A copy says so on its button, not in a toast: a toast covered the popover's footer
 * and waited unseen behind a phone's sheet.
 */
import type { ReactNode } from "react";
import { Check, CircleCheck, Copy, ShieldAlert, TriangleAlert } from "lucide-react";
import type { GiroCode, PaymentDetails } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { ibanFailsCheck, GIROCODE_MISMATCH_DETAILS } from "@/features/girocode/GiroCode";
import { useClipboard } from "@/features/today/clipboard";
import { formatIban, formatMoney } from "@/lib/format";
import { protectRefs } from "@/lib/glue";
import { paymentReference } from "@/lib/payments";
import { cn } from "@/lib/utils";

/** An amount as a German banking app wants it typed: 94.99 → "94,99", 1234.5 → "1234,50". */
export function amountForTransfer(amount: number): string {
  return amount.toFixed(2).replace(".", ",");
}

/** An IBAN in groups of four that never split: the line breaks only between groups (UI audit round 1: "…2130 0" / "0"). */
export function IbanGroups({ iban }: { iban: string }) {
  const groups = formatIban(iban).split(" ");
  return (
    <>
      {groups.map((g, i) => (
        <span key={i}>
          <span className="whitespace-nowrap">{g}</span>
          {i < groups.length - 1 ? " " : null}
        </span>
      ))}
    </>
  );
}

interface Detail {
  id: "payee" | "iban" | "amount" | "reference";
  /** The row's label ("Recipient"). */
  label: string;
  /** The detail as a sentence names it: "Copy recipient", "IBAN copied". */
  what: string;
  /** What the button copies. */
  value: string;
  display: ReactNode;
  ident?: boolean;
}

/** Whether there are bank details to list (an amount alone is not). */
export function hasTransferDetails(payment: Pick<PaymentDetails, "payee" | "iban" | "reference"> | null | undefined): boolean {
  return Boolean(payment && (payment.payee || payment.iban || payment.reference));
}

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/**
 * The transfer details: label, the full value (wrapped, never cut — every character of an IBAN or a
 * reference matters) and a copy button, icon-only in a narrow panel. Copied, the button shows a check
 * and "Copied" and the change is announced; a blocked clipboard says so under the list. While the
 * person says the details don't match the letter (`mismatch`), the list says so and has no copy buttons.
 */
export function TransferDetails({
  payment,
  amount,
  currency,
  mismatch = false,
  className,
}: {
  payment: Pick<PaymentDetails, "payee" | "iban" | "reference"> | null | undefined;
  amount?: number | null;
  currency?: string | null;
  mismatch?: boolean;
  className?: string;
}) {
  const { copy, copied, failed } = useClipboard();
  if (!payment || !hasTransferDetails(payment)) return null;
  const reference = payment.reference ? paymentReference(payment.reference) : null;
  const rows: Detail[] = [];
  if (payment.payee) rows.push({ id: "payee", label: "Recipient", what: "recipient", value: payment.payee, display: payment.payee });
  if (payment.iban) rows.push({ id: "iban", label: "IBAN", what: "IBAN", value: payment.iban.replace(/\s+/g, ""), display: <IbanGroups iban={payment.iban} />, ident: true });
  if (amount != null) {
    rows.push({ id: "amount", label: "Amount", what: "amount", value: amountForTransfer(amount), display: formatMoney(amount, { currency: currency ?? undefined }) });
  }
  // a reference never breaks at its hyphens ("TM-2026-" / "0048213"); the button copies it as written
  if (reference) rows.push({ id: "reference", label: "Reference", what: "reference", value: reference, display: protectRefs(reference), ident: true });
  const done = rows.find((r) => r.id === copied);
  return (
    <div className={className}>
      {mismatch ? (
        <p role="status" className="mb-3 flex gap-2 text-sm leading-5 text-warn-ink">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          {GIROCODE_MISMATCH_DETAILS}
        </p>
      ) : null}
      <dl className="@container divide-y divide-line rounded-lg border border-line px-3">
        {rows.map((r) => {
          const isDone = copied === r.id;
          return (
            <div key={r.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 py-2">
              <dt className="text-xs font-medium text-muted">{r.label}</dt>
              <dd className={cn("col-start-1 text-base text-ink wrap-anywhere", r.ident && "font-ident")}>{r.display}</dd>
              <dd className="col-start-2 row-span-2 row-start-1" hidden={mismatch}>
                <button
                  type="button"
                  onClick={() => void copy(r.value, r.id)}
                  className="inline-flex h-7 min-w-7 items-center justify-center gap-1 rounded-md px-2 text-xs font-medium text-accent transition-colors hover:bg-accent-soft"
                  // the visible word is part of the name: "Copy IBAN", then "IBAN copied"
                  aria-label={isDone ? `${capital(r.what)} copied` : `Copy ${r.what}`}
                >
                  {isDone ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
                  <span aria-hidden className="hidden @[17rem]:inline">
                    {isDone ? "Copied" : "Copy"}
                  </span>
                </button>
              </dd>
            </div>
          );
        })}
      </dl>
      {/* always in the page, so the change is announced */}
      <p className="sr-only" aria-live="polite">
        {done ? `${capital(done.what)} copied` : ""}
      </p>
      {failed ? (
        <p role="alert" className="mt-2 text-sm leading-5 text-warn-ink">
          Couldn't copy — your browser blocked the clipboard. Select the text and copy it by hand.
        </p>
      ) : null}
    </div>
  );
}

/**
 * Under the details: a red warning when the IBAN fails its checksum (the letter's reading says so, or
 * the GiroCode was refused for it), a quiet green line when its check digits are valid.
 */
export function IbanCheck({ ibanValid, code, className }: { ibanValid: boolean | null | undefined; code: GiroCode | undefined; className?: string }) {
  if (ibanFailsCheck(ibanValid, code)) {
    return (
      <p className={cn("mt-3 flex gap-2 rounded-lg bg-danger-soft px-3 py-2.5 text-sm leading-5 text-danger-ink", className)}>
        <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
        This IBAN fails its checksum. Don't pay until you've confirmed the account with the sender.
      </p>
    );
  }
  if (ibanValid === true) {
    return (
      <p className={cn("mt-2 flex items-start gap-1.5 text-xs leading-5 text-ok-ink", className)}>
        <CircleCheck className="mt-[3px] size-3.5 shrink-0" aria-hidden />
        The IBAN's check digits are valid — that only rules out typos, not fraud.
      </p>
    );
  }
  return null;
}

/**
 * The panel's footer: the page's own second action (`secondary`: "Open letter" on Today, "Close" on the
 * letter) and "Mark as paid". It stays in view at the bottom of the panel however far its details scroll:
 * it covers the panel's bottom padding (a sticky box stops at the padding edge, so it is pulled down by it).
 */
export function PayFooter({
  secondary,
  onPaid,
  pending,
  className,
}: {
  secondary?: ReactNode;
  /** Absent: nothing to mark (a payment without a to-do). */
  onPaid?: () => void;
  pending?: boolean;
  className?: string;
}) {
  return (
    <div
      data-sticky-footer=""
      className={cn(
        "sticky -bottom-4 z-10 -mb-4 mt-4 flex flex-wrap items-center gap-2 border-t border-line bg-surface py-3",
        "in-sheet:bottom-[calc(-1.25rem-env(safe-area-inset-bottom))] in-sheet:mb-[calc(-1.25rem-env(safe-area-inset-bottom))] in-sheet:pb-[calc(0.75rem+env(safe-area-inset-bottom))]",
        className,
      )}
    >
      {secondary}
      {onPaid ? (
        // on the right, also when the second action is hidden (a sheet has its own Close)
        <Button variant="primary" size="sm" icon={Check} onClick={onPaid} loading={pending} className="ml-auto">
          Mark as paid
        </Button>
      ) : null}
    </div>
  );
}
