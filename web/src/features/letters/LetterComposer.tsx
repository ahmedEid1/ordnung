import { useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { Check, FileX, Languages, Mail, Scale, Search, Sparkles, type LucideIcon } from "lucide-react";
import { useContracts, useCreateDraft, useDocuments, useParties } from "@/api/hooks";
import type { Contract, Document, DraftKind, Party } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { Dialog } from "@/components/ui/Dialog";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Glossary } from "@/components/ui/Glossary";
import { KindIcon } from "@/components/ui/KindBadge";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { Avatar } from "@/components/ui/Avatar";
import { CONTRACT_CATEGORY_COPY, copyFor, documentKindLabel, partyKindLabel } from "@/lib/copy";
import { cn } from "@/lib/utils";
import { offersEndingLetter } from "@/features/contracts/links";
import { cancellableContracts, objectionCheck, objectionDocuments, usableDocuments, type ComposerPrefill } from "./logic";

interface KindOption {
  kind: DraftKind;
  title: string;
  description: ReactNode;
  icon: LucideIcon;
}

const KIND_OPTIONS: KindOption[] = [
  { kind: "cancellation", title: "Cancel a contract", description: <>End a contract — <Glossary term="Kündigung" translate={false} />: phone, gym, electricity…</>, icon: FileX },
  {
    kind: "objection",
    title: "Object to a decision",
    description: (
      <>
        <Glossary term="Einspruch" translate={false} /> or <Glossary term="Widerspruch" translate={false} /> against an official decision
      </>
    ),
    icon: Scale,
  },
  { kind: "general_reply", title: "Reply to a letter", description: "Answer, ask a question or send a document", icon: Mail },
];

const PLACEHOLDER: Record<DraftKind, string> = {
  cancellation: "e.g. Please confirm by email. I'm moving abroad at the end of the year.",
  objection: "e.g. My laptop is used mainly for work — my employer can confirm this.",
  general_reply: "e.g. Ask for the receipts behind the utility bill and suggest paying in two instalments.",
};

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

export interface LetterComposerProps {
  open: boolean;
  onClose: () => void;
  prefill: ComposerPrefill | null;
}

/**
 * "New letter": what (cancel / object / reply) → which contract or letter → optional wishes →
 * language → `POST /api/drafts` → opens the editor. Objections are only offered for decisions
 * whose instructions allow an Einspruch or Widerspruch.
 */
export function LetterComposer({ open, onClose, prefill }: LetterComposerProps) {
  // A new session (fresh form) whenever the composer is opened with a different pre-fill; closing
  // keeps the session so the dialog can animate out with its content.
  const sig = prefill ? JSON.stringify(prefill) : null;
  const [session, setSession] = useState({ sig, prefill, n: 0 });
  if (sig !== null && sig !== session.sig) setSession({ sig, prefill, n: session.n + 1 });
  return <ComposerDialog key={session.n} open={open && sig !== null} onClose={onClose} prefill={session.prefill} />;
}

function ComposerDialog({ open, prefill, onClose }: { open: boolean; prefill: ComposerPrefill | null; onClose: () => void }) {
  const navigate = useNavigate();
  const docsQ = useDocuments();
  const contractsQ = useContracts();
  const partiesQ = useParties();
  const create = useCreateDraft();

  const [kind, setKind] = useState<DraftKind | null>(prefill?.kind ?? null);
  const [contractId, setContractId] = useState<string | null>(prefill?.contractId ?? null);
  const [docId, setDocId] = useState<string | null>(prefill?.docId ?? null);
  const [partyId, setPartyId] = useState<string | null>(prefill?.partyId ?? null);
  const [instructions, setInstructions] = useState("");
  const [language, setLanguage] = useState<"de" | "en">("de");
  const [filter, setFilter] = useState("");

  const parties = useMemo(() => new Map((partiesQ.data ?? []).map((p) => [p.id, p])), [partiesQ.data]);
  const docs = useMemo(() => usableDocuments(docsQ.data ?? []), [docsQ.data]);
  const objectable = useMemo(() => objectionDocuments(docsQ.data ?? []), [docsQ.data]);
  const contracts = useMemo(() => cancellableContracts(contractsQ.data ?? []), [contractsQ.data]);
  const doc = docId ? (docsQ.data ?? []).find((d) => d.id === docId) ?? null : null;
  // "Draft cancellation" from a letter: find the contract that letter belongs to
  const inferredContractId = useMemo(() => {
    const from = prefill?.docId;
    if (kind !== "cancellation" || contractId || !from) return null;
    return (contractsQ.data ?? []).find((c) => c.source_doc_id === from || c.evidence.some((e) => e.doc_id === from))?.id ?? null;
  }, [kind, contractId, prefill?.docId, contractsQ.data]);
  const effContractId = contractId ?? inferredContractId;
  const contract = effContractId ? (contractsQ.data ?? []).find((c) => c.id === effContractId) ?? null : null;
  const check = objectionCheck(doc);
  const objectionBlocked = kind === "objection" && Boolean(doc) && !check.ok;
  const noObjectable = !docsQ.isPending && objectable.length === 0;

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

  const ready =
    kind === "cancellation"
      ? Boolean(contract) && !contractBlocked
      : kind === "objection"
        ? Boolean(doc) && check.ok
        : kind === "general_reply"
          ? Boolean(doc || partyId)
          : false;

  const pickKind = (k: DraftKind) => {
    setKind(k);
    if (k === "cancellation") setDocId(null);
    if (k !== "cancellation") setContractId(null);
    if (k === "objection" && doc && !objectionCheck(doc).ok) setDocId(null);
  };

  const submit = () => {
    if (!kind || !ready) return;
    create.mutate(
      {
        kind,
        contract_id: kind === "cancellation" ? effContractId : null,
        doc_id: kind === "cancellation" ? (contract?.source_doc_id ?? null) : docId,
        party_id: recipientId,
        case_id: (kind === "cancellation" ? contract?.case_id : doc?.case_id) ?? null,
        instructions: instructions.trim() || undefined,
        language,
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

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="New letter"
      description="Ordnung writes the legally important sentences from fixed templates. Claude only adds polite wording and the English translation."
      footer={
        <>
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
          <div role="radiogroup" aria-labelledby="cmp-kind" className="grid gap-2 sm:grid-cols-3">
            {KIND_OPTIONS.map((o) => {
              const disabled = o.kind === "objection" && noObjectable && !(doc && check.ok);
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
                  <input type="radio" name="letter-kind" value={o.kind} checked={selected} disabled={disabled} onChange={() => pickKind(o.kind)} className="sr-only" />
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
        </section>

        {/* 2 · which */}
        {kind ? (
          <section aria-labelledby="cmp-which">
            <StepLabel n={2} id="cmp-which">
              {kind === "cancellation" ? "Which contract?" : kind === "objection" ? "Which decision?" : "Which letter are you answering?"}
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
                <p className="text-sm text-muted">No active contracts yet. Add the contract letter to your inbox first.</p>
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
                      Unsure? Ask{" "}
                      {check.advice.map((a, i) => (
                        <span key={a.href}>
                          {i > 0 ? " or " : ""}
                          <a href={a.href} target="_blank" rel="noreferrer noopener" className="font-medium text-accent underline-offset-2 hover:underline">
                            {a.label}
                            <span className="sr-only"> (opens in a new tab)</span>
                          </a>
                        </span>
                      ))}
                      .
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
                        <OptionRow key={d.id} name="letter-doc" value={d.id} selected={docId === d.id} onSelect={() => setDocId(d.id)}>
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
                  <p className="text-sm text-muted">None of your letters is a decision with instructions on how to object.</p>
                )}
                {doc && check.ok ? (
                  <p className="mt-2.5 text-[13px] leading-relaxed text-muted">
                    The letter allows an <Glossary term={check.term} />
                    {check.remedy.addressee ? <> to {check.remedy.addressee}</> : null}. It's free, a short letter is enough and reasons can follow later.
                    {check.remedy.period_text ? (
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
                    {!replyDocs.length ? <p className="px-1 py-2 text-sm text-muted">No letters match “{filter}”.</p> : null}
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

            {recipient && !objectionBlocked ? (
              <div className="mt-3 flex items-center gap-2.5 rounded-xl bg-surface-2/70 px-3 py-2.5 text-[13px]">
                <span className="text-muted">To</span>
                <Avatar name={recipient.name} kind={recipient.kind} size="sm" />
                <span className="min-w-0 flex-1 truncate font-medium text-ink">
                  {recipient.name}
                  {recipient.address ? <span className="font-normal text-muted"> · {recipient.address}</span> : null}
                </span>
              </div>
            ) : null}
          </section>
        ) : null}

        {/* 3 · wishes + language */}
        {kind && !objectionBlocked ? (
          <section aria-labelledby="cmp-extra" className="space-y-4">
            <StepLabel n={3} id="cmp-extra">
              Anything to add?
            </StepLabel>
            <Field label="Your wishes, in any language" optional hint="Claude turns this into polite wording. The legal sentences stay as they are.">
              <Textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder={PLACEHOLDER[kind]} rows={3} className="min-h-20" />
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
