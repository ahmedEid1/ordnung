/**
 * Key facts (label, value, where it was found — click to see it on the page), reference numbers
 * and bank details, with copy buttons. For a suspected scam the bank account is flagged, and says
 * why there is no GiroCode to scan.
 *
 * All three share one grid (UI audit round 1: references and IBANs were cut to "RE-2…" and "DE51 /
 * 1234 / …" on phones): below `sm` the label sits above its value, from `sm` in a 10rem column,
 * with the same gap everywhere so the columns line up. Values wrap — a reference or an IBAN is never
 * cut; an IBAN breaks only between its groups of four. A reference already shown as a key fact isn't
 * listed twice (the fact gets the copy button). Labels read in English with the letter's German in
 * brackets ("Valid from (Gültig ab)"), values in the app's format (`fact-text.ts`).
 */
import type { ReactNode } from "react";
import { Copy, Hash, Landmark, QrCode, ShieldAlert, Sparkle } from "lucide-react";
import type { Document, DocumentKind, GiroCode, Grounding } from "@/api/types";
import { cn } from "@/lib/utils";
import { GROUNDING_COPY, TONES, copyFor } from "@/lib/copy";
import { formatIban } from "@/lib/format";
import { EvidenceChip } from "./EvidenceChip";
import { useEvidence } from "./EvidenceContext";
import { GlossaryText } from "./Explained";
import { PanelSection } from "./PanelSection";
import { copyText } from "./actions";
import { bracketed, factLabel, factValue, sameNumber, unbrokenNumber } from "./fact-text";

function CopyButton({ value, what }: { value: string; what: string }) {
  return (
    <button
      type="button"
      onClick={() => void copyText(value, what)}
      className="-my-0.5 grid size-7 shrink-0 place-items-center rounded-md text-muted opacity-70 transition-[opacity,background-color] hover:bg-surface-2 hover:text-ink hover:opacity-100 focus-visible:opacity-100"
      aria-label={`Copy ${what}`}
      title={`Copy ${what}`}
    >
      <Copy className="size-3.5" aria-hidden />
    </button>
  );
}

/** "Valid from (Gültig ab)": the English first, the letter's German after it; German alone marked as German. */
export function FactLabelText({ label }: { label: string }) {
  const { en, de } = factLabel(label);
  if (en && de) {
    return (
      <>
        {en}{" "}
        <span lang="de">
          (<GlossaryText text={bracketed(de)} explained />)
        </span>
      </>
    );
  }
  if (de) {
    return (
      <span lang="de">
        <GlossaryText text={de} />
      </span>
    );
  }
  return <GlossaryText text={en ?? label} />;
}

/** The label a person reads (for "Copy …" and "show … on the page"). */
const labelName = (label: string) => factLabel(label).en ?? label;

/** One row of the key-facts grid: label above the value on phones, beside it from `sm`. */
function Row({ label, children, className, ...hover }: { label: ReactNode; children: ReactNode; className?: string; onMouseEnter?: () => void; onMouseLeave?: () => void }) {
  return (
    <div className={cn("grid gap-x-4 gap-y-0.5 px-4 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)] sm:px-5", className)} {...hover}>
      <dt className="text-[13px] leading-5 text-muted sm:pt-0.5">{label}</dt>
      {children}
    </div>
  );
}

/** An IBAN in groups of four that never split: the line breaks only between groups. */
function IbanText({ iban }: { iban: string }) {
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

/** Documents nobody replies to quote numbers from (a passport, a certificate, a payslip). */
const NO_REPLY_KINDS: ReadonlySet<DocumentKind> = new Set<DocumentKind>(["identity_document", "certificate", "receipt", "payslip"]);

function referencesHeading(doc: Document, scam: boolean): string {
  if (scam) return "Numbers in this letter";
  if (doc.kind && NO_REPLY_KINDS.has(doc.kind)) return "Numbers on this document";
  return "Reference numbers — quote them when you reply";
}

/** The grounding every fact shares (so it is said once), or null when they differ or only one fact has one. */
function sharedGrounding(groundings: Grounding[]): Grounding | null {
  if (groundings.length < 2) return null;
  return groundings.every((g) => g === groundings[0]) ? groundings[0]! : null;
}

const SHARED_NOTE: Record<Grounding, string> = {
  verified: "Every fact below was found in the letter.",
  model_read: "Every fact below was read by AI from the photo — worth a glance.",
  unverified: "None of these could be found in the letter — please check them.",
  user: "You confirmed every fact below.",
};

export function KeyFacts({ doc, scam, girocodes = [] }: { doc: Document; scam: boolean; girocodes?: GiroCode[] }) {
  const { hover, selected, hovered } = useEvidence();
  // a scam letter has no Pay button: its bank details say why there is no code to scan
  const scamCode = scam ? girocodes.find((g) => g.status === "blocked" && g.reason === "scam") : undefined;
  const facts = doc.key_facts;
  const p = doc.payment;
  const hasPayment = Boolean(p && (p.iban || p.payee));
  // a number already shown as a key fact isn't listed again under the references
  const references = doc.references.filter((r) => !facts.some((f) => sameNumber(f.value, r.value)));
  if (!facts.length && !references.length && !hasPayment) return null;

  const grounded = facts.map((f) => (f.evidence && f.evidence.doc_id === doc.id ? f.evidence : null));
  // said once only when it is true of every fact (one without a source sentence says so itself)
  const shared = grounded.every(Boolean) ? sharedGrounding(grounded.flatMap((ev) => (ev ? [ev.grounding] : []))) : null;
  const sharedCopy = shared ? copyFor(GROUNDING_COPY, shared) : null;

  return (
    <PanelSection id="facts" title="Key facts" icon={Sparkle}>
      <div className="card overflow-hidden">
        {facts.length ? (
          <>
            {shared && sharedCopy ? (
              <p className="flex items-start gap-2 border-b border-line px-4 py-2.5 text-[12.5px] leading-5 text-muted sm:px-5">
                <sharedCopy.icon className={cn("mt-0.5 size-3.5 shrink-0", TONES[sharedCopy.tone].icon)} aria-hidden />
                <span>
                  {SHARED_NOTE[shared]} Select the icon after a value to see where it is on the page.
                </span>
              </p>
            ) : null}
            <dl className="divide-y divide-line">
              {facts.map((f, i) => {
                const ev = grounded[i];
                const id = ev ? `fact:${i}` : null;
                const active = id !== null && (hovered === id || selected === id);
                const value = factValue(f.value);
                const reference = doc.references.find((r) => sameNumber(f.value, r.value));
                const name = labelName(f.label);
                return (
                  <Row
                    key={`${f.label}-${i}`}
                    label={<FactLabelText label={f.label} />}
                    onMouseEnter={() => id && hover(id)}
                    onMouseLeave={() => id && hover(null)}
                    className={cn("py-3 transition-colors", active && "bg-[color-mix(in_srgb,var(--color-marker)_22%,transparent)]")}
                  >
                    <dd className="min-w-0">
                      <div className="flex items-start gap-2">
                        <span className="min-w-0 flex-1 text-[14.5px] font-medium leading-6 text-ink [overflow-wrap:anywhere] hyphens-auto">
                          <span lang={value.german ? "de" : undefined}>{value.text}</span>
                          {ev && shared ? (
                            <>
                              {" "}
                              <EvidenceChip grounding={ev.grounding} page={ev.page} pages={doc.pages} anchorId={id} what={name} iconOnly className="-my-1 ml-0.5" />
                            </>
                          ) : null}
                        </span>
                        {reference ? <CopyButton value={reference.value} what={name} /> : null}
                      </div>
                      {ev && !shared ? (
                        <div className="mt-1">
                          <EvidenceChip grounding={ev.grounding} page={ev.page} pages={doc.pages} anchorId={id} what={name} compact />
                        </div>
                      ) : !ev ? (
                        <p className="mt-0.5 text-[12px] leading-5 text-muted">No source sentence</p>
                      ) : null}
                    </dd>
                  </Row>
                );
              })}
            </dl>
          </>
        ) : null}

        {references.length ? (
          <div className={cn("py-3", facts.length && "border-t border-line")}>
            <h3 className="mb-1.5 flex items-center gap-1.5 px-4 text-[12px] font-semibold text-muted sm:px-5">
              <Hash className="size-3.5 shrink-0" aria-hidden /> {referencesHeading(doc, scam)}
            </h3>
            <dl className="space-y-2 sm:space-y-1">
              {references.map((r) => (
                <Row key={`${r.label}-${r.value}`} label={<FactLabelText label={r.label} />}>
                  <dd className="flex min-w-0 items-start gap-2">
                    <span className="min-w-0 flex-1 font-ident text-[13.5px] leading-6 text-ink [overflow-wrap:anywhere]">{unbrokenNumber(r.value)}</span>
                    <CopyButton value={r.value} what={labelName(r.label)} />
                  </dd>
                </Row>
              ))}
            </dl>
          </div>
        ) : null}

        {hasPayment && p ? (
          <div className={cn("py-3", (facts.length || references.length) && "border-t border-line", scam && "bg-danger-soft/60")}>
            <h3 className={cn("mb-1.5 flex items-center gap-1.5 px-4 text-[12px] font-semibold sm:px-5", scam ? "text-danger-ink" : "text-muted")}>
              {scam ? <ShieldAlert className="size-3.5 shrink-0" aria-hidden /> : <Landmark className="size-3.5 shrink-0" aria-hidden />}
              {scam ? "Bank details in this letter — don't pay to this account" : "Bank details"}
            </h3>
            <dl className="space-y-2 sm:space-y-1">
              {p.payee ? (
                <Row label="Payee">
                  <dd className="min-w-0 text-[13.5px] font-medium leading-6 text-ink [overflow-wrap:anywhere]">{p.payee}</dd>
                </Row>
              ) : null}
              {p.iban ? (
                <Row label="IBAN">
                  <dd className="flex min-w-0 items-start gap-2">
                    <span className={cn("min-w-0 flex-1 font-ident text-[13.5px] leading-6", scam ? "font-semibold text-danger-ink" : "text-ink")}>
                      <IbanText iban={p.iban} />
                    </span>
                    {/* nothing to copy for a transfer that must not be made */}
                    {scam ? null : <CopyButton value={p.iban.replace(/\s+/g, "")} what="IBAN" />}
                  </dd>
                </Row>
              ) : null}
              {p.reference ? (
                <Row label="Reference">
                  <dd className="flex min-w-0 items-start gap-2">
                    <span className="min-w-0 flex-1 font-ident text-[13.5px] leading-6 text-ink [overflow-wrap:anywhere]">{unbrokenNumber(p.reference)}</span>
                    {scam ? null : <CopyButton value={p.reference} what="Reference" />}
                  </dd>
                </Row>
              ) : null}
            </dl>
            {scamCode?.status === "blocked" ? (
              <p className="mt-2 flex items-start gap-1.5 px-4 text-[12.5px] leading-5 text-danger-ink sm:px-5">
                <QrCode className="mt-[3px] size-3.5 shrink-0" aria-hidden />
                <span className="min-w-0 wrap-break-word">
                  <span className="font-semibold">GiroCode (EPC-QR): </span>
                  {scamCode.message}
                </span>
              </p>
            ) : null}
            {p.iban_valid === false ? (
              <p className={cn("mt-2 px-4 text-[12.5px] font-medium sm:px-5", scam ? "text-danger-ink" : "text-warn-ink")}>
                This IBAN doesn't pass the bank check — most likely a misprint. Compare it with the paper letter before you pay.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </PanelSection>
  );
}
