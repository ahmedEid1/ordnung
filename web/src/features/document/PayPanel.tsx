/**
 * "Pay" — Ordnung never pays for you. It lays out exactly what to type into your banking app
 * (recipient, IBAN, amount, reference) with copy buttons, the GiroCode to scan when the server offers
 * one (or why there is none), and lets you mark the payment as paid — with the same details, names
 * and footer as Today's Pay panel (`features/pay`).
 */
import { useState } from "react";
import { Landmark } from "lucide-react";
import type { Document, GiroCode, Item } from "@/api/types";
import { daysUntil, formatMoney } from "@/lib/format";
import { useIsTabletUp, useMediaQuery } from "@/lib/hooks";
import { isTransfer } from "@/lib/payments";
import { useToday } from "@/lib/today";
import { Button } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { GiroCodeSection, canReadLetterAgain } from "@/features/girocode/GiroCode";
import { IbanCheck, PayFooter, TransferDetails, hasTransferDetails } from "@/features/pay/TransferDetails";

/**
 * Once paid, the to-do leaves the verdict and its Pay button with it: keyboard focus goes on to the
 * verdict's heading (brought into view), never to the page's <body> — on the next frame, after the
 * panel handed it back to the Pay button.
 */
export function focusVerdictAfterPaying(): void {
  requestAnimationFrame(() => {
    const title = document.getElementById("verdict-title");
    if (!title) return;
    title.focus({ preventScroll: true });
    title.scrollIntoView?.({ block: "nearest" });
  });
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

      {hasTransferDetails(p) ? (
        <TransferDetails payment={p} amount={item.amount} currency={item.currency} mismatch={mismatch} className="mt-3" />
      ) : (
        <p className="mt-3 rounded-lg bg-surface-2 px-3 py-2.5 text-sm leading-5 text-muted">
          No bank details were found in this letter. Check the letter (or an earlier one from the same sender) for where to pay.
        </p>
      )}
      <IbanCheck ibanValid={p?.iban_valid} code={code} />

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
      {/* in view however far the details scroll — but not pinned on a screen too short to spare it (a phone turned sideways) */}
      <PayFooter
        className="mt-3 [@media(max-height:500px)]:static"
        secondary={
          close ? (
            // a sheet has its own Close
            <Button size="sm" variant="ghost" onClick={close} className="in-sheet:hidden">
              Close
            </Button>
          ) : null
        }
        onPaid={() => {
          onPaid();
          close?.();
          focusVerdictAfterPaying();
        }}
      />
    </div>
  );
}
