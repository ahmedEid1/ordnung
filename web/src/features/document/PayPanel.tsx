/**
 * "Pay" — Ordnung never pays for you. It lays out exactly what to type into your banking app
 * (payee, IBAN, reference, amount) with copy buttons, the GiroCode to scan when the server offers
 * one (or why there is none), and lets you mark the payment as done.
 */
import { Check, Copy, Landmark, ShieldAlert } from "lucide-react";
import type { Document, GiroCode, Item } from "@/api/types";
import { formatIban, formatMoney } from "@/lib/format";
import { Button } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { GiroCodeSection, ibanFailsCheck } from "@/features/girocode/GiroCode";
import { useIsTabletUp, useMediaQuery } from "@/lib/hooks";
import { paymentReference } from "@/lib/payments";
import { cn } from "@/lib/utils";
import { copyText } from "./actions";

function Row({ label, value, copy, mono }: { label: string; value: string; copy?: string; mono?: boolean }) {
  return (
    <div className="flex items-center gap-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="text-[11.5px] font-medium uppercase tracking-[0.06em] text-muted">{label}</div>
        {/* every character of a name or reference matters: long ones wrap, never overflow */}
        <div className={cn("mt-0.5 text-[14px] font-medium text-ink wrap-anywhere", mono && "font-ident")}>{value}</div>
      </div>
      {copy ? (
        <button
          type="button"
          onClick={() => void copyText(copy, label)}
          className="grid size-8 shrink-0 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-ink"
          aria-label={`Copy ${label.toLowerCase()}`}
          title={`Copy ${label.toLowerCase()}`}
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
  const p = doc.payment;
  const reference = p?.reference ? paymentReference(p.reference) : null;
  const amount = item.amount != null ? formatMoney(item.amount, { currency: item.currency }) : null;
  // a phone can't scan its own screen — upright or turned sideways: there the code waits behind "Show code"
  const narrow = !useIsTabletUp();
  const touch = useMediaQuery("(hover: none) and (pointer: coarse)");
  return (
    <div>
      <div className="flex items-center gap-2.5">
        <span className="grid size-8 place-items-center rounded-lg bg-k-payment-soft text-k-payment">
          <Landmark className="size-4" aria-hidden />
        </span>
        <div>
          <p className="text-[15px] font-semibold text-ink">Pay {amount ?? "this bill"}</p>
          {item.due_date ? <Countdown date={item.due_date} prefix="by" className="text-[12.5px]" /> : null}
        </div>
      </div>

      {p && (p.iban || p.payee) ? (
        <div className="mt-3 divide-y divide-line rounded-lg border border-line px-3">
          {p.payee ? <Row label="To" value={p.payee} /> : null}
          {p.iban ? <Row label="IBAN" value={formatIban(p.iban)} copy={p.iban.replace(/\s+/g, "")} mono /> : null}
          {reference ? <Row label="Reference" value={reference} copy={reference} /> : null}
          {amount ? <Row label="Amount" value={amount} copy={item.amount!.toFixed(2).replace(".", ",")} /> : null}
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

      <GiroCodeSection code={code} docId={doc.id} collapsible={narrow || touch} canReadAgain={!doc.ai_private && doc.status !== "processing" && doc.status !== "queued"} className="mt-3" />

      <p className="mt-3 text-[12.5px] leading-5 text-muted">
        Ordnung never pays for you — use your banking app. Compare the IBAN with an earlier letter from this sender.
      </p>
      {/*
        stays in view at the bottom of the panel however tall the code makes it (as on Today) — but
        not on a screen too short to spare it (a phone turned sideways)
      */}
      <div
        data-sticky-footer=""
        className={cn(
          "sticky -bottom-4 -mb-4 mt-3 flex justify-end gap-2 border-t border-line bg-surface py-3 [@media(max-height:500px)]:static",
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
