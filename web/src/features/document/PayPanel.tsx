/**
 * "Pay" — Ordnung never pays for you. It lays out exactly what to type into your banking app
 * (payee, IBAN, reference, amount) with copy buttons, the GiroCode to scan when the server offers
 * one (or why there is none), and lets you mark the payment as done.
 */
import { useState, type ReactNode } from "react";
import { Check, Copy, Landmark, ShieldAlert, TriangleAlert } from "lucide-react";
import type { Document, GiroCode, Item } from "@/api/types";
import { daysUntil, formatIban, formatMoney } from "@/lib/format";
import { useIsTabletUp, useMediaQuery } from "@/lib/hooks";
import { isTransfer, paymentReference } from "@/lib/payments";
import { useToday } from "@/lib/today";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { GIROCODE_MISMATCH_DETAILS, GiroCodeSection, canReadLetterAgain, ibanFailsCheck } from "@/features/girocode/GiroCode";
import { copyText } from "./actions";

/** An IBAN in groups of four that never split: the line breaks only between groups (UI audit round 1: "…2130 0" / "0"). */
function IbanGroups({ iban }: { iban: string }) {
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

/**
 * One transfer detail. `copy` is what the button copies; `what` names it as written in a sentence ("Copy IBAN",
 * "Copy reference" and "Reference copied" — UI audit round 1: "Copy iban"), the label by default.
 */
function Row({ label, children, copy, what, className }: { label: string; children: ReactNode; copy?: string; what?: string; className?: string }) {
  const name = what ?? label;
  return (
    <div className="flex items-center gap-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="eyebrow">{label}</div>
        {/* every character of a name or reference matters: long ones wrap, never overflow */}
        <div className={cn("mt-0.5 text-[14px] font-medium text-ink", className)}>{children}</div>
      </div>
      {copy ? (
        <button
          type="button"
          onClick={() => void copyText(copy, name.charAt(0).toUpperCase() + name.slice(1))}
          className="grid size-8 shrink-0 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-ink"
          aria-label={`Copy ${name}`}
          title={`Copy ${name}`}
        >
          <Copy className="size-4" aria-hidden />
        </button>
      ) : null}
    </div>
  );
}

export function PayPanel({
  item,
  doc,
  code,
  onPaid,
  close,
}: {
  item: Item;
  doc: Document;
  /** The payment's GiroCode, or why there is none (`DocumentDetail.girocodes`). */
  code?: GiroCode;
  onPaid: () => void;
  close?: () => void;
}) {
  const today = useToday();
  const p = doc.payment;
  const reference = p?.reference ? paymentReference(p.reference) : null;
  const amount = item.amount != null ? formatMoney(item.amount, { currency: item.currency }) : null;
  const due = item.due_date;
  // a transfer has to go out a day or so before it must arrive: that day leads while it is ahead, as in the verdict
  const transferBy =
    isTransfer(item) && item.send_by && item.send_by !== due && daysUntil(item.send_by, today) >= 0 ? item.send_by : null;
  // a phone can't scan its own screen — upright or turned sideways: there the code waits behind "Show code"
  const narrow = !useIsTabletUp();
  const touch = useMediaQuery("(hover: none) and (pointer: coarse)");
  // "They don't match": the details shown are the ones the person says are wrong — no copy buttons
  const [mismatch, setMismatch] = useState(false);
  const copyable = !mismatch;
  return (
    <div>
      <div className="flex items-start gap-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-k-payment-soft text-k-payment">
          <Landmark className="size-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="text-[15px] font-semibold text-ink">Pay {amount ?? "this bill"}</p>
          {transferBy ? (
            <p className="text-[12.5px] leading-5">
              <Countdown date={transferBy} prefix="Transfer by" />
              {due ? (
                <span className="text-muted">
                  {" "}
                  (must arrive <DateText date={due} />)
                </span>
              ) : null}
            </p>
          ) : due ? (
            <Countdown date={due} prefix="by" className="text-[12.5px]" />
          ) : null}
        </div>
      </div>

      {p && (p.iban || p.payee) && mismatch ? (
        <p role="status" className="mt-3 flex gap-2 text-[13px] leading-5 text-warn-ink">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          {GIROCODE_MISMATCH_DETAILS}
        </p>
      ) : null}
      {p && (p.iban || p.payee) ? (
        <div className="mt-3 divide-y divide-line rounded-lg border border-line px-3">
          {p.payee ? (
            <Row label="To" className="wrap-anywhere">
              {p.payee}
            </Row>
          ) : null}
          {p.iban ? (
            <Row label="IBAN" copy={copyable ? p.iban.replace(/\s+/g, "") : undefined} className="font-ident">
              <IbanGroups iban={p.iban} />
            </Row>
          ) : null}
          {reference ? (
            <Row label="Reference" what="reference" copy={copyable ? reference : undefined} className="font-ident wrap-anywhere">
              {reference}
            </Row>
          ) : null}
          {amount ? (
            <Row label="Amount" what="amount" copy={copyable ? item.amount!.toFixed(2).replace(".", ",") : undefined}>
              {amount}
            </Row>
          ) : null}
        </div>
      ) : (
        <p className="mt-3 rounded-lg bg-surface-2 px-3 py-2.5 text-[13px] leading-5 text-muted">
          No bank details were found in this letter. Check the letter (or an earlier one from the same sender) for where to pay.
        </p>
      )}

      {ibanFailsCheck(p?.iban_valid, code) ? (
        <p className="mt-3 flex gap-2 rounded-lg bg-danger-soft px-3 py-2.5 text-[13px] leading-5 text-danger-ink">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          This IBAN fails its checksum. Don't pay until you've confirmed the account with the sender.
        </p>
      ) : null}

      <GiroCodeSection
        code={code}
        docId={doc.id}
        collapsible={narrow || touch}
        canReadAgain={canReadLetterAgain(doc)}
        onMismatch={setMismatch}
        className="mt-3"
      />

      <p className="mt-3 text-[12.5px] leading-5 text-muted">
        Ordnung never pays for you — use your banking app. Compare the IBAN with an earlier letter from this sender.
      </p>
      {/*
        stays in view at the bottom of the panel, however far its details scroll or however tall the code makes it
        (as in Today's Pay panel): it covers the panel's bottom padding (a sticky box stops at the padding edge, so it
        is pulled down by it) — but not on a screen too short to spare it (a phone turned sideways)
      */}
      <div
        data-sticky-footer=""
        className={cn(
          "sticky -bottom-4 z-10 -mb-4 mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-line bg-surface py-3 [@media(max-height:500px)]:static",
          "in-sheet:bottom-[calc(-1.25rem-env(safe-area-inset-bottom))] in-sheet:mb-[calc(-1.25rem-env(safe-area-inset-bottom))] in-sheet:pb-[calc(0.75rem+env(safe-area-inset-bottom))]",
        )}
      >
        {close ? (
          <Button size="sm" variant="ghost" onClick={close} className="in-sheet:hidden">
            Close
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="primary"
          icon={Check}
          onClick={() => {
            onPaid();
            close?.();
          }}
        >
          I've paid it
        </Button>
      </div>
    </div>
  );
}
