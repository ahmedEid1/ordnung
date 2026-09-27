/**
 * Key facts (label, value, where it was found — click to see it on the page), reference numbers
 * and bank details, with copy buttons. For a suspected scam the bank account is flagged, and says
 * why there is no GiroCode to scan.
 */
import { Copy, Hash, Landmark, QrCode, ShieldAlert, Sparkle } from "lucide-react";
import type { Document, GiroCode } from "@/api/types";
import { cn } from "@/lib/utils";
import { formatFactValue, formatIban } from "@/lib/format";
import { EvidenceChip } from "./EvidenceChip";
import { useEvidence } from "./EvidenceContext";
import { PanelSection } from "./PanelSection";
import { copyText } from "./actions";

function CopyButton({ value, what }: { value: string; what: string }) {
  return (
    <button
      type="button"
      onClick={() => void copyText(value, what)}
      className="grid size-7 shrink-0 place-items-center rounded-md text-muted opacity-70 transition-[opacity,background-color] hover:bg-surface-2 hover:text-ink hover:opacity-100 focus-visible:opacity-100"
      aria-label={`Copy ${what}`}
      title={`Copy ${what}`}
    >
      <Copy className="size-3.5" aria-hidden />
    </button>
  );
}

export function KeyFacts({ doc, scam, girocodes = [] }: { doc: Document; scam: boolean; girocodes?: GiroCode[] }) {
  const { hover, selected, hovered } = useEvidence();
  // a scam letter has no Pay button: its bank details say why there is no code to scan
  const scamCode = scam ? girocodes.find((g) => g.status === "blocked" && g.reason === "scam") : undefined;
  const facts = doc.key_facts;
  const p = doc.payment;
  const hasPayment = Boolean(p && (p.iban || p.payee));
  if (!facts.length && !doc.references.length && !hasPayment) return null;

  return (
    <PanelSection id="facts" title="Key facts" icon={Sparkle}>
      <div className="card overflow-hidden">
        {facts.length ? (
          <dl className="divide-y divide-line">
            {facts.map((f, i) => {
              const ev = f.evidence && f.evidence.doc_id === doc.id ? f.evidence : null;
              const id = ev ? `fact:${i}` : null;
              const active = id !== null && (hovered === id || selected === id);
              return (
                <div
                  key={`${f.label}-${i}`}
                  onMouseEnter={() => id && hover(id)}
                  onMouseLeave={() => id && hover(null)}
                  className={cn(
                    "grid gap-x-4 gap-y-1 px-4 py-3 transition-colors sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)] sm:px-5",
                    active && "bg-[color-mix(in_srgb,var(--color-marker)_22%,transparent)]",
                  )}
                >
                  <dt className="text-[13px] leading-6 text-muted">{f.label}</dt>
                  <dd className="min-w-0">
                    <span className="text-[14.5px] font-medium leading-6 text-ink [overflow-wrap:anywhere]">{formatFactValue(f.value)}</span>
                    <div className="mt-1">
                      {ev ? (
                        <EvidenceChip grounding={ev.grounding} page={ev.page} anchorId={id} what={f.label} compact />
                      ) : (
                        <span className="text-[12px] text-muted">No source sentence</span>
                      )}
                    </div>
                  </dd>
                </div>
              );
            })}
          </dl>
        ) : null}

        {doc.references.length ? (
          <div className={cn("px-4 py-3 sm:px-5", facts.length && "border-t border-line")}>
            <h3 className="mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold text-muted">
              <Hash className="size-3.5" aria-hidden /> Reference numbers — quote them when you reply
            </h3>
            <ul className="space-y-0.5">
              {doc.references.map((r) => (
                <li key={`${r.label}-${r.value}`} className="flex items-center gap-3">
                  <span lang="de" className="w-40 shrink-0 truncate text-[13px] text-muted">
                    {r.label}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-ident text-[13px] text-ink">{r.value}</span>
                  <CopyButton value={r.value} what={r.label} />
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {hasPayment && p ? (
          <div className={cn("px-4 py-3 sm:px-5", (facts.length || doc.references.length) && "border-t border-line", scam && "bg-danger-soft/60")}>
            <h3 className={cn("mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold", scam ? "text-danger-ink" : "text-muted")}>
              {scam ? <ShieldAlert className="size-3.5" aria-hidden /> : <Landmark className="size-3.5" aria-hidden />}
              {scam ? "Bank details in this letter — don't pay to this account" : "Bank details"}
            </h3>
            <ul className="space-y-0.5">
              {p.payee ? (
                <li className="flex items-center gap-3">
                  <span className="w-40 shrink-0 text-[13px] text-muted">Payee</span>
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">{p.payee}</span>
                  <span className="size-7 shrink-0" aria-hidden />
                </li>
              ) : null}
              {p.iban ? (
                <li className="flex items-center gap-3">
                  <span className="w-40 shrink-0 text-[13px] text-muted">IBAN</span>
                  <span className={cn("min-w-0 flex-1 font-ident text-[13px] wrap-anywhere", scam ? "font-semibold text-danger-ink" : "text-ink")}>
                    {formatIban(p.iban)}
                  </span>
                  {scam ? <span className="size-7 shrink-0" aria-hidden /> : <CopyButton value={p.iban.replace(/\s+/g, "")} what="IBAN" />}
                </li>
              ) : null}
              {p.reference ? (
                <li className="flex items-center gap-3">
                  <span className="w-40 shrink-0 text-[13px] text-muted">Reference</span>
                  <span className="min-w-0 flex-1 truncate font-ident text-[13px] text-ink">{p.reference}</span>
                  <CopyButton value={p.reference} what="Reference" />
                </li>
              ) : null}
            </ul>
            {scamCode?.status === "blocked" ? (
              <p className="mt-2 flex items-start gap-1.5 text-[12.5px] leading-5 text-danger-ink">
                <QrCode className="mt-[3px] size-3.5 shrink-0" aria-hidden />
                <span className="min-w-0 wrap-break-word">
                  <span className="font-semibold">GiroCode (EPC-QR): </span>
                  {scamCode.message}
                </span>
              </p>
            ) : null}
            {p.iban_valid === false ? (
              <p className={cn("mt-2 text-[12.5px] font-medium", scam ? "text-danger-ink" : "text-warn-ink")}>
                This IBAN doesn't pass the bank check — most likely a misprint. Compare it with the paper letter before you pay.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </PanelSection>
  );
}
