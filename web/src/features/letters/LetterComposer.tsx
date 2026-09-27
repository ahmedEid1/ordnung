import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { Building2, Check, FileX, Languages, Mail, Scale, Search, Sparkles, type LucideIcon } from "lucide-react";
import { useContracts, useCreateDraft, useDocument, useDocuments, useParties, useProfile, useSuggestions } from "@/api/hooks";
import type { Contract, Document, DraftKind, Party } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { Dialog } from "@/components/ui/Dialog";
import { AdviceLinks, Disclaimer } from "@/components/ui/Disclaimer";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Glossary } from "@/components/ui/Glossary";
import { KindIcon } from "@/components/ui/KindBadge";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { Avatar } from "@/components/ui/Avatar";
import { CONTRACT_CATEGORY_COPY, copyFor, documentKindLabel, partyKindLabel } from "@/lib/copy";
import { useTodayISO } from "@/lib/today";
import { keepCitations } from "@/lib/glue";
import { cn } from "@/lib/utils";
import { offersEndingLetter } from "@/features/contracts/links";
import { canSuspend, cancellableContracts, objectionCheck, objectionDocuments, usableDocuments, type ComposerPrefill } from "./logic";
import {
  SCHUFA_ADDRESS,
  TEMPLATES,
  TEMPLATE_BY_KIND,
  detailsPayload,
  fieldError,
  isTemplateKind,
  joinAnd,
  letterDefaults,
  missingFields,
  sortForTemplate,
  statutoryDeadlines,
  templateRefusal,
  type DetailValues,
  type TemplateConfig,
} from "./templates";
import { TemplateFields } from "./TemplateFields";

interface KindOption {
  kind: DraftKind;
  title: string;
  description: ReactNode;
  icon: LucideIcon;
}

const KIND_OPTIONS: KindOption[] = [
  { kind: "cancellation", title: "Cancel a contract", description: <>End a contract — <Glossary term="Kündigung" translate={false} plain />: phone, gym, electricity…</>, icon: FileX },
  {
    kind: "objection",
    title: "Object to a decision",
    description: (
      <>
        <Glossary term="Einspruch" translate={false} plain /> or <Glossary term="Widerspruch" translate={false} plain /> against a decision or court order
      </>
    ),
    icon: Scale,
  },
  { kind: "general_reply", title: "Reply to a letter", description: "Answer, ask a question or send a document", icon: Mail },
];

const PLACEHOLDER: Record<"cancellation" | "objection" | "general_reply", string> = {
  cancellation: "e.g. Please confirm by email. I'm moving abroad at the end of the year.",
  objection: "e.g. My laptop is used mainly for work — my employer can confirm this.",
  general_reply: "e.g. Ask for the receipts behind the utility bill and suggest paying in two instalments.",
};

/** An objection's example wishes by the kind of letter it answers (a tax example fits only a tax letter). */
const OBJECTION_PLACEHOLDER: Partial<Record<NonNullable<Document["kind"]>, string>> = {
  court_payment_order: "e.g. I cancelled this subscription in 2022 and owe nothing.",
  enforcement_order: "e.g. I never received the payment order this is based on.",
  landlord_notice: "e.g. My child changes school next year, and I have nowhere else to go.",
};

function wishesPlaceholder(kind: DraftKind, letterKind?: Document["kind"] | null): string {
  if (isTemplateKind(kind)) return TEMPLATE_BY_KIND[kind].wishes;
  if (kind === "objection" && letterKind) return OBJECTION_PLACEHOLDER[letterKind] ?? PLACEHOLDER.objection;
  return PLACEHOLDER[kind];
}

function OptionRow({
  selected,
  disabled,
  onSelect,
  children,
  name,
  value,
}: {
  selected: boolean;
  disabled?: boolean;
  onSelect: () => void;
  children: ReactNode;
  name: string;
  value: string;
}) {
  return (
    <label
      className={cn(
        "group relative flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 transition-[border-color,background-color,box-shadow]",
        "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
        selected ? "border-accent/60 bg-accent-soft/50 shadow-[0_0_0_1px_var(--color-accent)]" : "border-line bg-surface hover:border-line-strong",
        disabled && "cursor-not-allowed opacity-55 hover:border-line",
      )}
    >
      <input type="radio" name={name} value={value} checked={selected} disabled={disabled} onChange={onSelect} className="sr-only" />
      {children}
      <span
        className={cn(
          "grid size-5 shrink-0 place-items-center rounded-full border transition-colors",
          selected ? "border-accent bg-accent text-on-accent" : "border-line-strong bg-surface",
        )}
        aria-hidden
      >
        {selected ? <Check className="size-3" strokeWidth={3} /> : null}
      </span>
    </label>
  );
}

function StepLabel({ n, children, id }: { n: number; children: ReactNode; id?: string }) {
  return (
    <h3 id={id} className="mb-2.5 flex items-center gap-2 text-[13px] font-semibold text-ink">
      <span className="grid size-5 place-items-center rounded-full bg-surface-3 text-[11px] font-bold text-muted">{n}</span>
      {children}
    </h3>
  );
}

function ListSkeleton() {
  return (
    <div className="space-y-2" aria-hidden>
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-14 w-full rounded-xl" />
      ))}
    </div>
  );
}

function ContractOption({ c, party }: { c: Contract; party?: Party }) {
  const sendBy = c.computed?.send_by;
  return (
    <>
      <KindIcon category={c.category} size="md" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14px] font-medium text-ink">{c.name}</span>
        <span className="block truncate text-[12.5px] text-muted">
          {[party?.name, copyFor(CONTRACT_CATEGORY_COPY, c.category).label].filter(Boolean).join(" · ")}
        </span>
      </span>
      {sendBy ? <Countdown date={sendBy} prefix="send by" variant="pill" className="hidden sm:inline-flex" /> : null}
    </>
  );
}

function DocOption({ d, party, extra }: { d: Document; party?: Party; extra?: ReactNode }) {
  return (
    <>
      <KindIcon docKind={d.kind} size="md" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14px] font-medium text-ink">{d.title ?? d.filename}</span>
        <span className="flex min-w-0 items-center gap-1.5 truncate text-[12.5px] text-muted">
          <span className="truncate">{party?.name ?? documentKindLabel(d.kind)}</span>
          {d.doc_date ? (
            <>
              <span aria-hidden>·</span>
              <DateText date={d.doc_date} style="day" />
            </>
          ) : null}
        </span>
      </span>
      {extra}
    </>
  );
}


/** Why an objection is possible when the law, not the letter's instructions, gives it. */
function StatutoryNote({ kind, term }: { kind: Document["kind"]; term: "Einspruch" | "Widerspruch" }) {
  if (kind === "landlord_notice") {
    return (
      <>
        If moving out would be a real hardship for you or your family, the law lets you object — a <Glossary term={term} /> (§{"\u00a0"}574 BGB). Text form is
        enough, so e-mail counts; a signed letter by Einwurf-Einschreiben is the safest proof. A tenants' association can check your reasons first.
      </>
    );
  }
  if (kind === "enforcement_order") {
    return (
      <>
        The law gives you an <Glossary term={term} /> against an enforcement order (§{"\u00a0"}700 ZPO). It goes to the court that sent it; reasons can follow. The
        order can still be enforced while your objection is pending — tick below to ask the court to suspend it.
      </>
    );
  }
  return (
    <>
      The law gives you a <Glossary term={term} /> against a court payment order (§{"\u00a0"}694 ZPO). It goes to the court that sent it — no reasons needed. This
      letter objects to the whole claim. To object to only part of it (only the interest or the costs, say), use the form that came with the order and
      tick how much you object to — send the form or this letter, not both.
    </>
  );
}

/** Step 1: the three everyday letters as cards, then the template letters as compact tiles. */
function KindChooser({ kind, onPick, noObjectable }: { kind: DraftKind | null; onPick: (k: DraftKind) => void; noObjectable: boolean }) {
  return (
    <fieldset className="min-w-0">
      <legend className="sr-only">What do you want to do?</legend>
      <div className="grid gap-2 sm:grid-cols-3">
        {KIND_OPTIONS.map((o) => {
          const disabled = o.kind === "objection" && noObjectable;
          const selected = kind === o.kind;
          return (
            <label
              key={o.kind}
              className={cn(
                "relative grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-0.5 rounded-xl border p-3 transition-[border-color,background-color,box-shadow] sm:flex sm:flex-col sm:items-start sm:gap-2 sm:p-3.5",
                "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                selected ? "border-accent/60 bg-accent-soft/50 shadow-[0_0_0_1px_var(--color-accent)]" : "border-line bg-surface hover:border-line-strong",
                disabled && "cursor-not-allowed opacity-55 hover:border-line",
              )}
            >
              <input type="radio" name="letter-kind" value={o.kind} checked={selected} disabled={disabled} onChange={() => onPick(o.kind)} className="sr-only" />
              <span className={cn("row-span-2 grid size-8 place-items-center rounded-lg", selected ? "bg-accent text-on-accent" : "bg-surface-2 text-muted")}>
                <o.icon className="size-4" aria-hidden />
              </span>
              <span className="text-[14px] font-semibold text-ink">{o.title}</span>
              <span className="col-start-2 text-[12.5px] leading-snug text-muted">
                {disabled ? "None of your letters is a decision you can object to." : o.description}
              </span>
            </label>
          );
        })}
      </div>
      <p id="cmp-more" className="eyebrow mb-2 mt-4">
        More letters from templates
      </p>
      <div role="group" aria-labelledby="cmp-more" className="grid gap-2 min-[480px]:grid-cols-2">
        {TEMPLATES.map((t) => {
          const selected = kind === t.kind;
          return (
            <label
              key={t.kind}
              className={cn(
                "relative flex cursor-pointer items-start gap-2.5 rounded-xl border px-3 py-2.5 transition-[border-color,background-color,box-shadow]",
                "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                selected ? "border-accent/60 bg-accent-soft/50 shadow-[0_0_0_1px_var(--color-accent)]" : "border-line bg-surface hover:border-line-strong",
              )}
            >
              <input type="radio" name="letter-kind" value={t.kind} checked={selected} onChange={() => onPick(t.kind)} className="sr-only" />
              <span className={cn("mt-px grid size-7 shrink-0 place-items-center rounded-lg", selected ? "bg-accent text-on-accent" : "bg-surface-2 text-muted")}>
                <t.icon className="size-3.5" aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block text-[13.5px] font-semibold leading-5 text-ink">{t.title}</span>
                <span className="block text-[12px] leading-snug text-muted">{t.blurb}</span>
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

export interface LetterComposerProps {
  open: boolean;
  onClose: () => void;
  prefill: ComposerPrefill | null;
}

/**
 * "New letter": what (cancel / object / reply, or one of the template letters) → which contract,
 * letter or recipient → the facts a template needs → optional wishes → language →
 * `POST /api/drafts` → opens the editor. Objections are only offered for decisions whose
 * instructions (or the law, for a court order or a landlord's notice) give an Einspruch or Widerspruch.
 */
export function LetterComposer({ open, onClose, prefill }: LetterComposerProps) {
  // A new session (fresh form) whenever the composer is opened with a different pre-fill; closing
  // keeps the session so the dialog can animate out with its content.
  const sig = prefill ? JSON.stringify(prefill) : null;
  const [session, setSession] = useState({ sig, prefill, n: 0 });
  if (sig !== null && sig !== session.sig) setSession({ sig, prefill, n: session.n + 1 });
  return <ComposerDialog key={session.n} open={open && sig !== null} onClose={onClose} prefill={session.prefill} />;
}

/** Recipient step of a template letter: a letter it answers, a person or organisation, or a typed address. */
function TemplateRecipient({
  config,
  docs,
  docId,
  setDocId,
  partyId,
  setPartyId,
  parties,
  loading,
  typed,
  setTyped,
  notice,
  claimant = false,
}: {
  config: TemplateConfig;
  docs: Document[];
  docId: string | null;
  setDocId: (id: string | null) => void;
  partyId: string | null;
  setPartyId: (id: string | null) => void;
  parties: Party[];
  loading: boolean;
  typed: string;
  setTyped: (v: string) => void;
  /** Why the chosen letter can't be answered this way — shown right under the letters, where it was chosen. */
  notice?: ReactNode;
  /** The letter goes to a court order's claimant, typed in (the court is the order's sender). */
  claimant?: boolean;
}) {
  const [filter, setFilter] = useState("");
  // the letter the composer was opened for comes first, so it is in view and never cut off the list
  const [pinned] = useState(docId);
  const byId = useMemo(() => new Map(parties.map((p) => [p.id, p])), [parties]);
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const base = docs.filter((d) => d.direction !== "outgoing");
    if (q) return base.filter((d) => [d.title, d.filename, byId.get(d.party_id ?? "")?.name].some((s) => s?.toLowerCase().includes(q)));
    const first = pinned ? base.find((d) => d.id === pinned) : undefined;
    return first ? [first, ...base.filter((d) => d.id !== pinned).slice(0, 29)] : base.slice(0, 30);
  }, [docs, filter, byId, pinned]);
  const noticeRef = useRef<HTMLDivElement>(null);
  const hasNotice = Boolean(notice);
  useEffect(() => {
    // a refusal is the reason the button stays disabled: bring it into view where the letter was chosen
    if (hasNotice) noticeRef.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [hasNotice, docId]);
  const sorted = useMemo(() => sortForTemplate(parties, config), [parties, config]);
  const letters = config.target === "letter-or-party";
  // a letter whose sender isn't in Ordnung: the person types who it goes to (the server needs a recipient)
  const chosen = letters && docId ? (docs.find((d) => d.id === docId) ?? null) : null;
  const unknownSender = Boolean(chosen && !chosen.party_id);

  return (
    <div className="space-y-3">
      {letters ? (
        <>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
            <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a letter…" aria-label="Find a letter" className="pl-9" />
          </div>
          {loading ? (
            <ListSkeleton />
          ) : (
            <div role="radiogroup" aria-labelledby="cmp-which" className="max-h-56 space-y-2 overflow-y-auto p-0.5 scrollbar-thin">
              {shown.map((d) => (
                <OptionRow
                  key={d.id}
                  name="letter-about"
                  value={d.id}
                  selected={docId === d.id}
                  onSelect={() => {
                    setDocId(d.id);
                    setPartyId(null);
                  }}
                >
                  <DocOption d={d} party={byId.get(d.party_id ?? "")} />
                </OptionRow>
              ))}
              {!shown.length ? <p className="px-1 py-2 text-sm text-muted">{filter ? `No letters match “${filter}”.` : "No letters yet."}</p> : null}
            </div>
          )}
          {notice ? (
            <div ref={noticeRef} className="scroll-mb-4">
              {notice}
            </div>
          ) : null}
          {claimant ? (
            <Field
              label="The claimant (Antragsteller)"
              hint="The court order names who claims the money — type their name and address as the order shows them. The letter goes to them, not to the court."
            >
              <Textarea
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                rows={4}
                className="min-h-24"
                placeholder={"Claimant's name\nStreet and number\nPostcode and town"}
              />
            </Field>
          ) : null}
          {unknownSender ? (
            <Field label="Who is it for?" hint="This letter's sender isn't in Ordnung — type their name and address as the letter shows them.">
              <Textarea
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                rows={4}
                className="min-h-24"
                placeholder={"Company name\nStreet and number\nPostcode and town"}
              />
            </Field>
          ) : null}
        </>
      ) : null}
      <Field label={letters ? "Or write to someone without a letter" : "Recipient"} optional={letters}>
        <Select
          value={docId && letters ? "" : (partyId ?? "")}
          onChange={(e) => {
            setPartyId(e.target.value || null);
            if (e.target.value) {
              setDocId(null);
              setTyped("");
            }
          }}
        >
          <option value="">Choose a person or organisation…</option>
          {sorted.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} — {partyKindLabel(p.kind)}
            </option>
          ))}
        </Select>
      </Field>
      {config.target === "party-or-typed" ? (
        <div className="rounded-xl border border-dashed border-line-strong/80 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[13px] font-medium text-ink">Not in Ordnung yet?</p>
            <Button
              size="sm"
              icon={Building2}
              onClick={() => {
                setTyped(SCHUFA_ADDRESS);
                setPartyId(null);
                setDocId(null);
              }}
            >
              Use SCHUFA's address
            </Button>
          </div>
          <p className="mt-1.5 text-[12.5px] leading-5 text-muted">SCHUFA, Germany's main credit agency, must send you a free copy of the data and scores it holds about you.</p>
          <Field label="Or type their name and address" hint="Every company or office must send you a free first copy of your data (Art. 15(3) GDPR)." className="mt-2">
            <Textarea
              value={typed}
              onChange={(e) => {
                setTyped(e.target.value);
                if (e.target.value.trim()) {
                  setPartyId(null);
                  setDocId(null);
                }
              }}
              rows={4}
              className="min-h-24"
              placeholder={"Company name\nStreet and number\nPostcode and town"}
            />
          </Field>
        </div>
      ) : null}
    </div>
  );
}

function ComposerDialog({ open, prefill, onClose }: { open: boolean; prefill: ComposerPrefill | null; onClose: () => void }) {
  const navigate = useNavigate();
  const today = useTodayISO();
  const docsQ = useDocuments();
  const contractsQ = useContracts();
  const partiesQ = useParties();
  const profileQ = useProfile();
  const suggestionsQ = useSuggestions();
  const create = useCreateDraft();

  const [kind, setKind] = useState<DraftKind | null>(prefill?.kind ?? null);
  const [contractId, setContractId] = useState<string | null>(prefill?.contractId ?? null);
  const [docId, setDocId] = useState<string | null>(prefill?.docId ?? null);
  const [partyId, setPartyId] = useState<string | null>(prefill?.partyId ?? null);
  const [typedRecipient, setTypedRecipient] = useState("");
  // instalments refused for a court order: the letter goes to the order's claimant, typed in
  const [toClaimant, setToClaimant] = useState(false);
  const [values, setValues] = useState<DetailValues>({});
  const [instructions, setInstructions] = useState("");
  // the application to suspend enforcement is a legal sentence: an explicit choice, never read from the wishes
  const [suspend, setSuspend] = useState(false);
  const [language, setLanguage] = useState<"de" | "en">("de");
  const [filter, setFilter] = useState("");
  // opened for a chosen letter ("Withdraw", "Ask for more time" on a letter): start at step 2, not the list of kinds
  const whichRef = useRef<HTMLElement>(null);
  const startAtWhich = Boolean(prefill?.kind);
  useEffect(() => {
    if (!open || !startAtWhich) return;
    const t = window.setTimeout(() => whichRef.current?.scrollIntoView?.({ block: "start" }), 60);
    return () => window.clearTimeout(t);
  }, [open, startAtWhich]);
  const doc = docId ? (docsQ.data ?? []).find((d) => d.id === docId) ?? null : null;
  // the answered letter's own deadline and amount: the server uses them when the fields are left empty;
  // a landlord's notice's card says whether it has a hardship objection at all
  const needsCard = kind === "objection" && doc?.kind === "landlord_notice";
  const needsLetter = kind === "extension_request" || kind === "payment_plan" || needsCard;
  const letterQ = useDocument(needsLetter && docId ? docId : undefined);
  const defaults = useMemo(() => letterDefaults(letterQ.data?.items ?? []), [letterQ.data]);

  const parties = useMemo(() => new Map((partiesQ.data ?? []).map((p) => [p.id, p])), [partiesQ.data]);
  const docs = useMemo(() => usableDocuments(docsQ.data ?? []), [docsQ.data]);
  // letters flagged as a possible scam are never answered with a template (a withdrawal, instalments…)
  const scamDocIds = useMemo(
    () =>
      new Set(
        (suggestionsQ.data ?? [])
          .filter((s) => s.kind === "scam" && s.status !== "dismissed" && s.status !== "expired")
          .flatMap((s) => s.refs.filter((r) => r.type === "document").map((r) => r.id)),
      ),
    [suggestionsQ.data],
  );
  const templateDocs = useMemo(() => docs.filter((d) => !scamDocIds.has(d.id)), [docs, scamDocIds]);
  const objectable = useMemo(() => objectionDocuments(docsQ.data ?? []), [docsQ.data]);
  const contracts = useMemo(() => cancellableContracts(contractsQ.data ?? []), [contractsQ.data]);
  const template = isTemplateKind(kind) ? TEMPLATE_BY_KIND[kind] : null;
  // "Draft cancellation" from a letter: find the contract that letter belongs to
  const inferredContractId = useMemo(() => {
    const from = prefill?.docId;
    if (kind !== "cancellation" || contractId || !from) return null;
    return (contractsQ.data ?? []).find((c) => c.source_doc_id === from || c.evidence.some((e) => e.doc_id === from))?.id ?? null;
  }, [kind, contractId, prefill?.docId, contractsQ.data]);
  const effContractId = contractId ?? inferredContractId;
  const contract = effContractId ? (contractsQ.data ?? []).find((c) => c.id === effContractId) ?? null : null;
  const check = objectionCheck(doc, needsCard ? letterQ.data?.advice : null);
  const objectionBlocked = kind === "objection" && Boolean(doc) && !check.ok;
  const noObjectable = !docsQ.isPending && objectable.length === 0 && !(doc && check.ok);

  const recipientId = kind === "cancellation" ? contract?.party_id ?? null : doc?.party_id ?? partyId;
  const recipient = recipientId ? parties.get(recipientId) ?? null : null;
  const replyDocs = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const base = docs.filter((d) => d.direction !== "outgoing");
    if (!q) return base.slice(0, 30);
    return base.filter((d) => [d.title, d.filename, parties.get(d.party_id ?? "")?.name].some((s) => s?.toLowerCase().includes(q)));
  }, [docs, filter, parties]);

  // e.g. the broadcasting fee (from an old link): nothing to cancel — say why instead
  const contractBlocked = kind === "cancellation" && contract !== null && !offersEndingLetter(contract);
  const resignation = kind === "cancellation" && contract?.category === "employment";

  // what the template form starts with: the contract's name (never a letter's title, which is Ordnung's
  // English summary, not what was ordered), the profile's address
  const templateValues: DetailValues = !template
    ? values
    : {
        ...(template.kind === "withdrawal" ? { subject_matter: contract?.name ?? "" } : {}),
        ...(template.kind === "address_change" ? { new_address: profileQ.data?.address ?? "" } : {}),
        ...values,
      };
  const missing = template ? missingFields(template, templateValues) : [];
  const invalid = template ? template.fields.some((f) => fieldError(f, templateValues, today, defaults)) : false;
  const typedTo = Boolean(typedRecipient.trim());
  const templateTarget = Boolean(
    (doc && (doc.party_id || typedTo)) || partyId || (template?.target === "party-or-typed" && typedTo) || (toClaimant && !doc && typedTo),
  );
  const refusal = template && doc ? templateRefusal(template.kind, doc.kind) : null;
  // a request for more time can't move the deadlines the law sets: say so before it is written
  const lawDeadlines = kind === "extension_request" && !refusal ? statutoryDeadlines(letterQ.data?.items ?? []) : [];

  const ready =
    kind === "cancellation"
      ? Boolean(contract) && !contractBlocked
      : kind === "objection"
        ? Boolean(doc) && check.ok && !(needsCard && letterQ.isPending)
        : kind === "general_reply"
          ? Boolean(doc || partyId)
          : template
            ? templateTarget && !refusal && !missing.length && !invalid
            : false;

  const pickKind = (k: DraftKind) => {
    setKind(k);
    setToClaimant(false);
    if (k === "cancellation") setDocId(null);
    if (k !== "cancellation") setContractId(null);
    if (k === "objection" && doc && !objectionCheck(doc).ok) setDocId(null);
    if (isTemplateKind(k) && TEMPLATE_BY_KIND[k].target === "party" && doc) {
      setPartyId(doc.party_id);
      setDocId(null);
    }
    if (isTemplateKind(k) && doc && scamDocIds.has(doc.id)) setDocId(null);
    setValues({});
  };

  const submit = () => {
    if (!kind || !ready) return;
    const templated = template !== null;
    create.mutate(
      {
        kind,
        contract_id: kind === "cancellation" ? effContractId : templated ? (contract?.id ?? null) : null,
        doc_id: kind === "cancellation" ? (contract?.source_doc_id ?? null) : docId,
        party_id: recipientId,
        case_id: (kind === "cancellation" ? contract?.case_id : doc?.case_id) ?? null,
        instructions: instructions.trim() || undefined,
        language,
        suspend_enforcement: kind === "objection" && canSuspend(doc) ? suspend : undefined,
        details: template ? detailsPayload(template, templateValues, recipientId ? null : typedRecipient) : undefined,
      },
      {
        onSuccess: (draft) => {
          toast.success("Your letter is ready to check", { description: "Read the English translation next to it before you send anything." });
          onClose();
          navigate(`/letters/${draft.id}`);
        },
      },
    );
  };

  const whichLabel =
    kind === "cancellation" ? "Which contract?" : kind === "objection" ? "Which decision?" : template ? template.whichLabel : "Which letter are you answering?";
  const disabledReason = !kind
    ? "Choose what you want to do."
    : kind === "cancellation"
      ? contract
        ? null
        : "Choose the contract to cancel."
      : kind === "objection"
        ? doc
          ? null
          : "Choose the decision you object to."
        : kind === "general_reply"
          ? doc || partyId
            ? null
            : "Choose the letter you're answering, or who to write to."
          : refusal
            ? "This letter can't answer the one you chose — see why under the letters."
            : template && !templateTarget
              ? doc && !doc.party_id
                ? "Type who the letter is for — its sender isn't in Ordnung."
                : toClaimant
                  ? "Type the claimant's name and address."
                  : "Choose who the letter is for."
              : missing.length
              ? `Still needed: ${joinAnd(missing)}.`
              : invalid
                ? "Fix the date or amount marked above."
                : null;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="New letter"
      description="The legal sentences come from fixed templates; Claude only adds polite wording and the translation."
      footer={
        <>
          {/* why the button is disabled — on phones above the buttons (the footer stacks in reverse) */}
          <p
            className={cn(disabledReason && !ready ? "order-last text-[12.5px] leading-snug text-muted sm:order-first sm:mr-auto sm:max-w-[22rem] sm:self-center" : "sr-only")}
            aria-live="polite"
          >
            {disabledReason && !ready ? disabledReason : ""}
          </p>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" icon={Sparkles} onClick={submit} disabled={!ready} loading={create.isPending}>
            {create.isPending ? "Writing…" : "Write the letter"}
          </Button>
        </>
      }
    >
      <div className="space-y-7 pb-2">
        {/* 1 · what */}
        <section aria-labelledby="cmp-kind">
          <StepLabel n={1} id="cmp-kind">
            What do you want to do?
          </StepLabel>
          <KindChooser kind={kind} onPick={pickKind} noObjectable={noObjectable} />
        </section>

        {/* 2 · which */}
        {kind ? (
          <section ref={whichRef} aria-labelledby="cmp-which" className="scroll-mt-2">
            <StepLabel n={2} id="cmp-which">
              {whichLabel}
            </StepLabel>

            {contractBlocked && contract ? (
              <Callout tone="warn" className="mb-3" title={`${contract.name} can't be cancelled`}>
                {contract.cancel_hint ?? "This isn't a contract you can end with a cancellation letter."}
              </Callout>
            ) : resignation && contract?.cancel_hint ? (
              <Callout tone="info" className="mb-3" title="This drafts your resignation">
                {contract.cancel_hint}
              </Callout>
            ) : null}
            {kind === "cancellation" ? (
              contractsQ.isPending ? (
                <ListSkeleton />
              ) : contracts.length ? (
                <div role="radiogroup" aria-labelledby="cmp-which" className="max-h-72 space-y-2 overflow-y-auto p-0.5 scrollbar-thin">
                  {contracts.map((c) => (
                    <OptionRow key={c.id} name="letter-contract" value={c.id} selected={effContractId === c.id} onSelect={() => setContractId(c.id)}>
                      <ContractOption c={c} party={parties.get(c.party_id ?? "")} />
                    </OptionRow>
                  ))}
                </div>
              ) : (
                <p className="text-base text-muted">No active contracts yet. Add the contract letter to your inbox first.</p>
              )
            ) : null}

            {kind === "objection" ? (
              <>
                {objectionBlocked && !check.ok ? (
                  <Callout
                    tone="warn"
                    className="mb-3"
                    title={check.title}
                    action={
                      <Button size="sm" icon={Mail} onClick={() => setKind("general_reply")}>
                        Reply to this letter instead
                      </Button>
                    }
                  >
                    <p>{check.body}</p>
                    <p className="mt-1.5">
                      <AdviceLinks advice={check.advice} />
                    </p>
                  </Callout>
                ) : null}
                {docsQ.isPending ? (
                  <ListSkeleton />
                ) : objectable.length ? (
                  <div role="radiogroup" aria-labelledby="cmp-which" className="max-h-72 space-y-2 overflow-y-auto p-0.5 scrollbar-thin">
                    {objectable.map((d) => {
                      const c = objectionCheck(d);
                      return (
                        <OptionRow
                          key={d.id}
                          name="letter-doc"
                          value={d.id}
                          selected={docId === d.id}
                          onSelect={() => {
                            setDocId(d.id);
                            setSuspend(false);
                          }}
                        >
                          <DocOption
                            d={d}
                            party={parties.get(d.party_id ?? "")}
                            extra={c.ok ? <span className="hidden shrink-0 rounded-full bg-k-expiry-soft px-2 py-0.5 text-[12px] font-medium text-k-expiry-ink sm:inline">{c.term} possible</span> : null}
                          />
                        </OptionRow>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-base text-muted">None of your letters is a decision with instructions on how to object.</p>
                )}
                {doc && check.ok ? (
                  <p className="mt-2.5 text-[13px] leading-relaxed text-muted">
                    {check.statutory ? (
                      <StatutoryNote kind={doc.kind} term={check.term} />
                    ) : (
                      <>
                        The letter allows an <Glossary term={check.term} />
                        {check.remedy?.addressee ? <> to {check.remedy.addressee}</> : null}. It's free, a short letter is enough and reasons can follow later.
                      </>
                    )}
                    {check.remedy?.period_text ? (
                      // the period is quoted as the letter words it — German, so marked as a quote of its own
                      <span className="mt-1 block">
                        The letter says (in German):{" "}
                        <q lang="de" className="italic">
                          {check.remedy.period_text.trim().replace(/[.„“"]+$/, "").replace(/^[„“"]+/, "")}
                        </q>
                      </span>
                    ) : null}
                  </p>
                ) : null}
                {doc && check.ok && canSuspend(doc) ? (
                  <Checkbox
                    label={doc.kind === "enforcement_order" ? "Also ask the court to suspend enforcement for now" : "Also ask to suspend enforcement"}
                    description={
                      doc.kind === "enforcement_order"
                        ? "Adds the application for “einstweilige Einstellung” (§§ 719, 707 ZPO). The court decides; get advice about it."
                        : "Adds the application for “Aussetzung der Vollziehung”. For taxes and other public charges, an objection alone doesn't stop the payment being due."
                    }
                    checked={suspend}
                    onChange={(e) => setSuspend(e.target.checked)}
                    className="mt-3"
                  />
                ) : null}
              </>
            ) : null}

            {kind === "general_reply" ? (
              <>
                <div className="relative mb-2.5">
                  <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
                  <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a letter…" aria-label="Find a letter" className="pl-9" />
                </div>
                {docsQ.isPending ? (
                  <ListSkeleton />
                ) : (
                  <div role="radiogroup" aria-labelledby="cmp-which" className="max-h-64 space-y-2 overflow-y-auto p-0.5 scrollbar-thin">
                    {replyDocs.map((d) => (
                      <OptionRow
                        key={d.id}
                        name="letter-reply"
                        value={d.id}
                        selected={docId === d.id}
                        onSelect={() => {
                          setDocId(d.id);
                          setPartyId(null);
                        }}
                      >
                        <DocOption d={d} party={parties.get(d.party_id ?? "")} />
                      </OptionRow>
                    ))}
                    {!replyDocs.length ? <p className="px-1 py-2 text-base text-muted">No letters match “{filter}”.</p> : null}
                  </div>
                )}
                <div className="mt-3">
                  <Field label="Or write to someone without a letter" optional>
                    <Select
                      value={doc ? "" : (partyId ?? "")}
                      onChange={(e) => {
                        setPartyId(e.target.value || null);
                        if (e.target.value) setDocId(null);
                      }}
                    >
                      <option value="">Choose a person or organisation…</option>
                      {(partiesQ.data ?? []).map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} — {partyKindLabel(p.kind)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                </div>
              </>
            ) : null}

            {template ? (
              <TemplateRecipient
                config={template}
                docs={templateDocs}
                docId={docId}
                setDocId={(id) => {
                  setDocId(id);
                  if (id) setToClaimant(false);
                }}
                partyId={partyId}
                setPartyId={(id) => {
                  setPartyId(id);
                  if (id) setToClaimant(false);
                }}
                parties={partiesQ.data ?? []}
                loading={docsQ.isPending}
                typed={typedRecipient}
                setTyped={setTypedRecipient}
                claimant={toClaimant && !doc}
                notice={
                  refusal ? (
                    <Callout
                      tone="warn"
                      title={refusal.title}
                      action={
                        refusal.toClaimant ? (
                          <Button
                            size="sm"
                            icon={Mail}
                            onClick={() => {
                              setToClaimant(true);
                              setDocId(null);
                              setPartyId(null);
                              setTypedRecipient("");
                            }}
                          >
                            Write to the claimant instead
                          </Button>
                        ) : undefined
                      }
                    >
                      {keepCitations(refusal.body)}
                    </Callout>
                  ) : null
                }
              />
            ) : null}
            {refusal && !template ? (
              <Callout tone="warn" className="mt-3" title={refusal.title}>
                {keepCitations(refusal.body)}
              </Callout>
            ) : lawDeadlines.length ? (
              <Callout tone="info" className="mt-3" title="Deadlines set by law can't be extended by asking">
                {lawDeadlines.length === 1 ? (
                  <>
                    “{lawDeadlines[0]!.title}” (<DateText date={lawDeadlines[0]!.due_date!} style="medium" />) is set by law — meet it anyway.
                  </>
                ) : (
                  <>This letter's objection and legal deadlines are set by law — meet them anyway.</>
                )}{" "}
                Ask for more time only for something the sender set, such as sending documents.
              </Callout>
            ) : null}

            {recipient && !objectionBlocked ? (
              // the whole name and address, wrapped: on a phone an ellipsis would hide where the letter goes
              <div className="mt-3 flex items-center gap-2.5 rounded-xl bg-surface-2/70 px-3 py-2.5 text-[13px]">
                <span className="text-muted">To</span>
                <Avatar name={recipient.name} kind={recipient.kind} size="sm" />
                <span className="min-w-0 flex-1 leading-snug [overflow-wrap:anywhere]">
                  <span className="font-medium text-ink">{recipient.name}</span>
                  {recipient.address ? <span className="block text-[12.5px] text-muted">{recipient.address}</span> : null}
                </span>
              </div>
            ) : null}
          </section>
        ) : null}

        {/* 3 · the facts a template letter needs */}
        {template && !refusal && template.fields.length + (template.kind === "deposit_return" ? 1 : 0) > 0 ? (
          <section aria-labelledby="cmp-details">
            <StepLabel n={3} id="cmp-details">
              The details
            </StepLabel>
            <TemplateFields config={template} values={templateValues} onChange={setValues} today={today} profile={profileQ.data} defaults={defaults} />
          </section>
        ) : null}

        {/* wishes + language */}
        {kind && !objectionBlocked && !refusal ? (
          <section aria-labelledby="cmp-extra" className="space-y-4">
            <StepLabel n={template && template.fields.length + (template.kind === "deposit_return" ? 1 : 0) > 0 ? 4 : 3} id="cmp-extra">
              Anything to add?
            </StepLabel>
            <Field label="Your wishes, in any language" optional hint="Claude turns this into polite wording. The legal sentences stay as they are.">
              <Textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder={wishesPlaceholder(kind, doc?.kind)} rows={3} className="min-h-20" />
            </Field>
            <div>
              <p id="cmp-lang" className="mb-1.5 flex items-center gap-1.5 text-[13px] font-medium text-ink">
                <Languages className="size-4 text-muted" aria-hidden /> Language of the letter
              </p>
              <SegmentedControl
                label="Language of the letter"
                value={language}
                onChange={setLanguage}
                options={[
                  { value: "de", label: "German (recommended)" },
                  { value: "en", label: "English" },
                ]}
              />
              <p className="mt-1.5 text-[12.5px] leading-5 text-muted">
                {language === "de"
                  ? "German offices and companies expect German. You'll see an English translation right next to it."
                  : "Only if you know the recipient reads English — German offices may not accept it."}
              </p>
            </div>
          </section>
        ) : null}

        <Disclaimer />
      </div>
    </Dialog>
  );
}
