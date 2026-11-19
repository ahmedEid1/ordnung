import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Building2, Search } from "lucide-react";
import type { ListedLetter, Party } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Field, Input, Select, Textarea } from "@/components/ui/Field";
import { partyKindLabel } from "@/lib/copy";
import {
  mayBeCourt,
} from "./logic";
import {
  SCHUFA_ADDRESS,
  sortForTemplate,
  type TemplateConfig,
} from "./templates";
import { OptionRow, ListSkeleton, DocOption, LIST_PREVIEW, ChoiceList } from "./ComposerOptions";

/** `docs` with the letters of `kinds` first, each group in its own order. */
export function fittingFirst(docs: ListedLetter[], kinds: readonly ListedLetter["kind"][] | undefined): ListedLetter[] {
  if (!kinds?.length) return docs;
  const fits = (d: ListedLetter) => kinds.includes(d.kind);
  return [...docs.filter(fits), ...docs.filter((d) => !fits(d))];
}

/** Recipient step of a template letter: a letter it answers, a person or organisation, or a typed address. */
export function TemplateRecipient({
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
  docs: ListedLetter[];
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
  const byId = useMemo(() => new Map(parties.map((p) => [p.id, p])), [parties]);
  // the letters whose kind fits the template come first (a withdrawal's orders and contracts, a statement's
  // statements), the rest after them: any letter can still be chosen; the letter
  // the composer was opened for is always shown (ChoiceList)
  const incoming = useMemo(
    () =>
      fittingFirst(
        docs.filter((d) => d.direction !== "outgoing"),
        config.letterKinds,
      ),
    [docs, config.letterKinds],
  );
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return incoming;
    return incoming.filter((d) => [d.title, d.filename, byId.get(d.party_id ?? "")?.name].some((s) => s?.toLowerCase().includes(q)));
  }, [incoming, filter, byId]);
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

  // no search box and no list for an install without letters, no picker without people
  const hasLetters = letters && incoming.length > 0;
  return (
    <div className="space-y-3">
      {letters ? (
        <>
          {hasLetters && (incoming.length > LIST_PREVIEW + 1 || filter) ? (
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a letter…" aria-label="Find a letter" className="pl-9" />
            </div>
          ) : null}
          {hasLetters && config.letterHint ? <p className="text-[12.5px] leading-5 text-muted">{config.letterHint}</p> : null}
          {loading ? (
            <ListSkeleton />
          ) : hasLetters ? (
            <ChoiceList
              items={shown}
              selectedId={docId}
              labelledBy="cmp-which"
              noun="letters"
              emptyText={filter ? `No letters match “${filter}”.` : null}
              render={(d) => (
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
              )}
            />
          ) : null}
          {notice ? (
            <div ref={noticeRef} className="scroll-mb-4">
              {notice}
            </div>
          ) : null}
          {claimant ? (
            <Field
              label="The claimant (Antragsteller)"
              hint="The court order names who claims the money — type their name and address as the order shows them. The letter goes to them, not to the court."
              // the court is no claimant: the server refuses an offer to it
              error={mayBeCourt(typed) ? "That's a court — type the claimant the order names as the Antragsteller." : undefined}
            >
              <Textarea
                data-claimant-recipient
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                rows={4}
                className="min-h-24"
                placeholder={"Claimant's name\nStreet and number\nPostcode and town"}
              />
            </Field>
          ) : null}
          {/* only when the letter can be answered this way, and never next to the claimant's box (both would
              write the same text) */}
          {unknownSender && !claimant && !notice ? (
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
      {sorted.length ? (
        <Field label={hasLetters ? "Or write to someone without a letter" : "Recipient"} optional={hasLetters}>
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
      ) : null}
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
