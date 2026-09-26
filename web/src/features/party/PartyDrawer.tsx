import { useMemo, type ReactNode } from "react";
import { Link } from "react-router";
import {
  ArrowDownLeft,
  ArrowUpRight,
  AtSign,
  Check,
  Copy,
  ExternalLink,
  FolderOpen,
  Globe,
  Landmark,
  MapPin,
  MessagesSquare,
  PenLine,
  Phone,
  StickyNote,
  TriangleAlert,
} from "lucide-react";
import { useDrafts, useParty } from "@/api/hooks";
import type { Contract, Item, Party } from "@/api/types";
import { Avatar } from "@/components/ui/Avatar";
import { buttonVariants } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { Drawer } from "@/components/ui/Drawer";
import { EmptyState } from "@/components/ui/EmptyState";
import { KindBadge, KindIcon } from "@/components/ui/KindBadge";
import { Money } from "@/components/ui/Money";
import { Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { StatusPill } from "@/components/ui/StatusPill";
import { Tooltip } from "@/components/ui/Tooltip";
import { useClipboard } from "@/features/today/clipboard";
import { CONTRACT_CATEGORY_COPY, copyFor, DRAFT_KIND_COPY, documentKindLabel, partyKindLabel } from "@/lib/copy";
import { formatIban } from "@/lib/format";
import { usePartyDrawer } from "@/lib/party-drawer";
import { cn } from "@/lib/utils";
import { byYear, letterTimeline, mailtoUrl, regionName, websiteUrl } from "./timeline";
import { contractHref } from "@/features/contracts/links";

function Section({ title, count, children, id }: { title: string; count?: number; children: ReactNode; id: string }) {
  return (
    <section aria-labelledby={id} className="mt-7 first:mt-0">
      <h3 id={id} className="mb-2.5 text-[12px] font-semibold uppercase tracking-[0.07em] text-muted">
        {title}
        {count !== undefined ? <span className="ml-1 font-medium text-muted">· {count}</span> : null}
      </h3>
      {children}
    </section>
  );
}

function CopyRow({ label, value, display, mono = true }: { label: string; value: string; display?: string; mono?: boolean }) {
  const { copy, copied } = useClipboard();
  const done = copied === value;
  return (
    <div className="flex items-center gap-3 px-3 py-2.5">
      <dt className="w-[7.5rem] shrink-0 text-[12.5px] leading-4 text-muted">{label}</dt>
      <dd className={cn("min-w-0 flex-1 text-[13px] text-ink wrap-anywhere", mono && "font-ident")}>{display ?? value}</dd>
      <button
        type="button"
        onClick={() => void copy(value)}
        aria-label={done ? `${label} copied` : `Copy ${label}`}
        title={done ? "Copied" : `Copy ${label}`}
        className={cn(
          "grid size-8 shrink-0 place-items-center rounded-lg transition-colors",
          done ? "bg-ok-soft text-ok-ink" : "text-muted hover:bg-surface-2 hover:text-ink",
        )}
      >
        {done ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
      </button>
    </div>
  );
}

function ItemRow({ item }: { item: Item }) {
  const date = item.send_by ?? item.due_date;
  const inner = (
    <>
      <KindIcon kind={item.kind} size="sm" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13.5px] font-medium text-ink">{item.title}</span>
        <span className="mt-0.5 flex items-center gap-2 text-[12.5px] text-muted">
          {date ? <DateText date={date} /> : "No date"}
          {item.amount != null ? <Money amount={item.amount} className="font-normal text-muted" /> : null}
        </span>
      </span>
      {date ? <Countdown date={date} variant="pill" /> : null}
    </>
  );
  const cls = "-mx-2 flex items-center gap-3 rounded-lg px-2 py-2";
  return item.doc_id ? (
    <Link to={`/documents/${item.doc_id}`} className={cn(cls, "transition-colors hover:bg-surface-2")}>
      {inner}
    </Link>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

function ContractRow({ c }: { c: Contract }) {
  const sendBy = c.status === "active" ? c.computed?.send_by : null;
  return (
    <Link to={contractHref(c.id)} className="flex items-center gap-3 rounded-xl border border-line bg-surface px-3 py-2.5 transition-colors hover:border-line-strong">
      <KindIcon category={c.category} size="sm" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13.5px] font-medium text-ink">{c.name}</span>
        <span className="flex flex-wrap items-center gap-x-2 text-[12.5px] text-muted">
          {copyFor(CONTRACT_CATEGORY_COPY, c.category).label}
          {c.status !== "active" ? <StatusPill of="contract" status={c.status} /> : sendBy ? <Countdown date={sendBy} prefix="cancel by" className="text-[12.5px]" /> : null}
        </span>
      </span>
      {c.cost_amount != null ? <Money amount={c.cost_amount} interval={c.cost_interval} className="shrink-0 text-[13px]" /> : null}
    </Link>
  );
}

function Header({ party }: { party: Party }) {
  const region = regionName(party.region);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <KindBadge partyKind={party.kind} size="md" label={partyKindLabel(party.kind)} />
      <Tooltip content={region ? `Deadlines with them skip the public holidays of ${region}.` : "Their state isn't known, so only nationwide holidays count — the safer, earlier date."}>
        <span tabIndex={0} className="inline-flex cursor-help items-center gap-1 rounded-full text-[12.5px] text-muted underline decoration-muted/40 decoration-dotted underline-offset-[3px]">
          <MapPin className="size-3.5" aria-hidden />
          {region ? `Holidays: ${region}` : "Holidays: nationwide"}
        </span>
      </Tooltip>
    </div>
  );
}

/**
 * People & organisations drawer, opened from any party chip (`?party=pty_x`): identifiers with
 * copy buttons, contact details, the bank accounts they used, open to-dos & dates, contracts, a
 * timeline of their letters and yours, and threads.
 */
export function PartyDrawer() {
  const { partyId, close } = usePartyDrawer();
  const { data, isLoading, isError } = useParty(partyId);
  const drafts = useDrafts();
  const party = data?.party;

  const open = useMemo(() => (data?.items ?? []).filter((i) => i.status === "open").sort((a, b) => ((a.send_by ?? a.due_date ?? "9") < (b.send_by ?? b.due_date ?? "9") ? -1 : 1)), [data?.items]);
  const theirDrafts = useMemo(() => (drafts.data ?? []).filter((d) => d.party_id && d.party_id === partyId), [drafts.data, partyId]);
  const timeline = useMemo(() => byYear(letterTimeline(data?.documents ?? [], theirDrafts)), [data?.documents, theirDrafts]);
  const docsPerCase = useMemo(() => {
    const m = new Map<string, number>();
    for (const d of data?.documents ?? []) if (d.case_id) m.set(d.case_id, (m.get(d.case_id) ?? 0) + 1);
    return m;
  }, [data?.documents]);
  const site = websiteUrl(party?.website);
  const letters = data?.documents.length ?? 0;

  return (
    <Drawer
      open={Boolean(partyId)}
      onClose={close}
      eyebrow="People & organisations"
      title={party?.name ?? (isLoading ? "Loading…" : "Not found")}
      headerExtra={party ? <Header party={party} /> : null}
      footer={
        party ? (
          <div className="flex gap-2">
            <Link
              to={`/letters?kind=general_reply&to=${encodeURIComponent(party.id)}`}
              className={buttonVariants({ variant: "secondary", size: "md", className: "flex-1" })}
            >
              <PenLine aria-hidden />
              Write to them
            </Link>
            <Link
              to={`/ask?q=${encodeURIComponent(`What do I have open with ${party.name}?`)}`}
              className={buttonVariants({ variant: "secondary", size: "md", className: "flex-1" })}
            >
              <MessagesSquare aria-hidden />
              Ask about them
            </Link>
          </div>
        ) : null
      }
    >
      {isLoading ? (
        <div className="space-y-4" aria-busy="true">
          <Skeleton className="h-16 w-full rounded-xl" />
          <SkeletonText lines={4} />
          <Skeleton className="h-24 w-full rounded-xl" />
        </div>
      ) : isError || !data || !party ? (
        <EmptyState illustration="search" variant="plain" title="We couldn't find this contact" description="It may have been merged with another one or deleted." />
      ) : (
        <div>
          <div className="flex items-center gap-3 rounded-xl border border-line bg-surface p-3">
            <Avatar name={party.name} kind={party.kind} size="lg" />
            <div className="min-w-0 text-[13.5px] leading-5">
              <p className="text-ink">
                {letters} {letters === 1 ? "letter" : "letters"} · {open.length} open {open.length === 1 ? "to-do" : "to-dos"}
                {data.contracts.length ? ` · ${data.contracts.length} ${data.contracts.length === 1 ? "contract" : "contracts"}` : ""}
              </p>
              {party.aliases.length ? <p className="truncate text-muted">Also known as {party.aliases.join(", ")}</p> : null}
            </div>
          </div>

          {party.identifiers.length ? (
            <Section title="Your numbers with them" id="pty-ids">
              <dl className="divide-y divide-line rounded-xl border border-line bg-surface">
                {party.identifiers.map((id) => (
                  <CopyRow key={id.label + id.value} label={id.label} value={id.value} />
                ))}
              </dl>
              <p className="mt-1.5 px-1 text-[12px] text-muted">Quote these when you write or call.</p>
            </Section>
          ) : null}

          {party.ibans.length ? (
            <Section title={party.ibans.length === 1 ? "Bank account they use" : "Bank accounts they used"} id="pty-ibans">
              <dl className="divide-y divide-line rounded-xl border border-line bg-surface">
                {party.ibans.map((iban, i) => (
                  <CopyRow key={iban} label={party.ibans.length > 1 ? `IBAN ${i + 1}` : "IBAN"} value={iban.replace(/\s+/g, "")} display={formatIban(iban)} />
                ))}
              </dl>
              {party.ibans.length > 1 ? (
                <p className="mt-2 flex items-start gap-2 rounded-lg bg-warn-soft px-3 py-2 text-[12.5px] leading-5 text-warn-ink">
                  <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  They used more than one account. Before paying, check the IBAN on the letter matches one you know.
                </p>
              ) : (
                <p className="mt-1.5 flex items-center gap-1.5 px-1 text-[12px] text-muted">
                  <Landmark className="size-3.5" aria-hidden /> Seen on their letters. Ordnung warns you if a letter asks you to pay somewhere else.
                </p>
              )}
            </Section>
          ) : null}

          {party.address || party.email || party.phone || site ? (
            <Section title="Contact" id="pty-contact">
              <ul className="space-y-2 text-[13.5px]">
                {party.address ? (
                  <li className="flex items-start gap-2.5">
                    <MapPin className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
                    <span className="text-ink">{party.address}</span>
                  </li>
                ) : null}
                {party.email ? (
                  <li className="flex items-center gap-2.5">
                    <AtSign className="size-4 shrink-0 text-muted" aria-hidden />
                    {mailtoUrl(party.email) ? (
                      <a href={mailtoUrl(party.email) ?? undefined} className="truncate text-accent hover:underline">
                        {party.email}
                      </a>
                    ) : (
                      <span className="truncate text-ink">{party.email}</span>
                    )}
                  </li>
                ) : null}
                {party.phone ? (
                  <li className="flex items-center gap-2.5">
                    <Phone className="size-4 shrink-0 text-muted" aria-hidden />
                    <a href={`tel:${party.phone.replace(/[^\d+]/g, "")}`} className="text-accent hover:underline">
                      {party.phone}
                    </a>
                  </li>
                ) : null}
                {site ? (
                  <li className="flex items-center gap-2.5">
                    <Globe className="size-4 shrink-0 text-muted" aria-hidden />
                    <a href={site} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-accent hover:underline">
                      {party.website?.replace(/^https?:\/\//, "")} <ExternalLink className="size-3" aria-hidden />
                      <span className="sr-only">(opens in a new tab)</span>
                    </a>
                  </li>
                ) : null}
              </ul>
            </Section>
          ) : null}

          {party.notes ? (
            <Section title="Notes" id="pty-notes">
              <p className="flex gap-2.5 rounded-xl bg-surface-2/70 px-3 py-2.5 text-[13.5px] leading-relaxed text-ink/90">
                <StickyNote className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
                {party.notes}
              </p>
            </Section>
          ) : null}

          {open.length ? (
            <Section title="To-dos & dates" count={open.length} id="pty-items">
              <div className="flex flex-col">
                {open.slice(0, 6).map((i) => (
                  <ItemRow key={i.id} item={i} />
                ))}
              </div>
              {open.length > 6 ? <p className="mt-1 text-[12.5px] text-muted">and {open.length - 6} more on your Timeline.</p> : null}
            </Section>
          ) : null}

          {data.contracts.length ? (
            <Section title="Contracts" count={data.contracts.length} id="pty-contracts">
              <ul className="space-y-2">
                {data.contracts.map((c) => (
                  <li key={c.id}>
                    <ContractRow c={c} />
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}

          {timeline.length ? (
            <Section title="Letters" count={timeline.reduce((n, g) => n + g.entries.length, 0)} id="pty-letters">
              <div className="space-y-4">
                {timeline.map((g) => (
                  <div key={g.year}>
                    <p className="mb-1 text-[12px] font-semibold tabular-nums text-muted">{g.year}</p>
                    <ol className="relative ml-[13px] border-l border-line">
                      {g.entries.map((e) => (
                        <li key={e.id} className="relative">
                          <Link to={e.href} className="group -ml-px flex items-start gap-3 rounded-r-lg py-2 pl-5 pr-2 transition-colors hover:bg-surface-2/70">
                            <span
                              className={cn(
                                "absolute -left-[9px] top-2.5 grid size-[18px] place-items-center rounded-full ring-4 ring-canvas",
                                e.direction === "in" ? "bg-surface-3 text-muted" : "bg-accent-soft text-accent",
                              )}
                              aria-hidden
                            >
                              {e.direction === "in" ? <ArrowDownLeft className="size-3" /> : <ArrowUpRight className="size-3" />}
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-[13.5px] font-medium text-ink group-hover:text-accent">{e.title}</span>
                              <span className="flex min-w-0 items-center gap-1.5 text-[12.5px] text-muted">
                                <span className="shrink-0">{e.direction === "in" ? "From them" : "From you"}</span>
                                <span aria-hidden>·</span>
                                <span className="truncate" lang={e.subtitle ? "de" : undefined}>
                                  {e.subtitle ?? (e.docKind ? documentKindLabel(e.docKind) : e.draftKind ? copyFor(DRAFT_KIND_COPY, e.draftKind).label : "")}
                                </span>
                              </span>
                            </span>
                            {e.date ? <DateText date={e.date} style="day" className="mt-0.5 shrink-0 text-[12.5px] text-muted" /> : null}
                          </Link>
                        </li>
                      ))}
                    </ol>
                  </div>
                ))}
              </div>
            </Section>
          ) : null}

          {data.cases.length ? (
            <Section title="Threads" count={data.cases.length} id="pty-threads">
              <ul className="space-y-2">
                {data.cases.map((c) => (
                  <li key={c.id} className="flex items-start gap-2.5 rounded-xl border border-line bg-surface px-3 py-2.5 text-[13.5px]">
                    <FolderOpen className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium text-ink">{c.title}</span>
                      {c.summary ? <span className="mt-0.5 block text-[12.5px] leading-5 text-muted">{c.summary}</span> : null}
                      <span className="mt-1 block text-[12px] text-muted">
                        {c.status === "open" ? "Open" : "Closed"}
                        {docsPerCase.get(c.id) ? ` · ${docsPerCase.get(c.id)} ${docsPerCase.get(c.id) === 1 ? "letter" : "letters"}` : ""}
                        {c.reference ? ` · Ref. ${c.reference}` : ""}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}
        </div>
      )}
    </Drawer>
  );
}
