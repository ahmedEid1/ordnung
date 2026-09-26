import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { useReducedMotion } from "motion/react";
import {
  ArrowDownLeft,
  ArrowUpRight,
  AtSign,
  Check,
  ChevronRight,
  Copy,
  ExternalLink,
  FolderOpen,
  Globe,
  Landmark,
  MapPin,
  MessagesSquare,
  PenLine,
  Phone,
  Repeat,
  RotateCw,
  StickyNote,
  TriangleAlert,
} from "lucide-react";
import { ApiError } from "@/api/client";
import { useDrafts, useParty } from "@/api/hooks";
import type { Contract, Document, Item, ItemAside, Party } from "@/api/types";
import { Button, buttonVariants } from "@/components/ui/Button";
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
import { isIncomingMoney } from "@/lib/payments";
import { usePartyDrawer } from "@/lib/party-drawer";
import { useToday } from "@/lib/today";
import { cn } from "@/lib/utils";
import { contractHref } from "@/features/contracts/links";
import { isRollingContract } from "@/features/contracts/model";
import { actionDate, asideNote, countdownMode, dateRole, identifierDisplay, identifierStyle, keepNumbersTogether, looksAbroad, partyTodos, repeatsLabel } from "./model";
import { byYear, letterTimeline, mailtoUrl, regionName, websiteUrl } from "./timeline";

/** To-dos listed before "Show N more". */
const FIRST_TODOS = 6;

function Section({ title, count, children, id }: { title: string; count?: number; children: ReactNode; id: string }) {
  return (
    <section aria-labelledby={id} className="mt-7 first:mt-0">
      {/* focus target of the jump links (tabIndex -1: not a Tab stop) */}
      <h3 id={id} tabIndex={-1} className="mb-2.5 scroll-mt-4 text-[12px] font-semibold uppercase tracking-[0.07em] text-muted outline-none">
        {title}
        {count !== undefined ? <span className="ml-1 font-medium text-muted">· {count}</span> : null}
      </h3>
      {children}
    </section>
  );
}

// ------------------------------------------------------------------------------------------------
// Numbers & bank accounts
// ------------------------------------------------------------------------------------------------

interface Copier {
  copy: (text: string, id: string) => Promise<boolean>;
  copied: string | null;
}

/**
 * One identifier: the label above the value in a narrow drawer, beside it from 384 px; the copy
 * button sits in the value (`dd`), so the list stays a valid `dl`. Codes in the monospace face,
 * register entries ("Amtsgericht Musterstadt HRB 4711") in the text face; neither breaks mid-word.
 */
function IdRow({ label, value, kind, copier }: { label: string; value: string; kind: "iban" | "code" | "text"; copier: Copier }) {
  const id = `${label}\n${value}`;
  const done = copier.copied === id;
  return (
    <div className="grid grid-cols-1 gap-y-0.5 px-3 py-2 @sm:grid-cols-[7.5rem_minmax(0,1fr)] @sm:items-center @sm:gap-x-3">
      <dt className="break-words text-[12.5px] leading-4 text-muted">{label}</dt>
      <dd className="flex min-w-0 items-center gap-2">
        <span className={cn("min-w-0 flex-1 break-words text-[13px] leading-5 text-ink", kind !== "text" && "font-mono tracking-tight")}>
          {identifierDisplay(value, kind)}
        </span>
        <button
          type="button"
          onClick={() => void copier.copy(value, id)}
          aria-label={`Copy ${label}`}
          title={done ? "Copied" : `Copy ${label}`}
          className={cn(
            "inline-flex h-8 min-w-8 shrink-0 items-center justify-center gap-1 rounded-lg text-[12px] font-medium transition-colors",
            done ? "bg-ok-soft px-2 text-ok-ink" : "text-muted hover:bg-surface-2 hover:text-ink",
          )}
        >
          {done ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
          {done ? <span aria-hidden>Copied</span> : null}
        </button>
      </dd>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
// To-dos & dates
// ------------------------------------------------------------------------------------------------

/** The kind icon; money that comes to you gets the green "money in" arrow, not the bill's euro. */
function ItemIcon({ item, className }: { item: Item; className?: string }) {
  if (!isIncomingMoney(item)) return <KindIcon kind={item.kind} size="sm" className={className} />;
  return (
    <span aria-hidden className={cn("inline-grid size-7 shrink-0 place-items-center rounded-md bg-ok-soft text-ok [&>svg]:size-3.5", className)}>
      <ArrowDownLeft />
    </span>
  );
}

/**
 * Parts of a meta line joined by " · ". Each part stays whole and the dot stays with the part
 * before it, so a wrapped line starts with a part, never with a dot.
 */
function Dotted({ parts, className }: { parts: ReactNode[]; className?: string }) {
  return (
    <span className={cn("block text-[12.5px] leading-5 text-muted", className)}>
      {parts.map((p, i) => (
        <Fragment key={i}>
          {i > 0 ? <span aria-hidden>{"\u00a0· "}</span> : null}
          <span className="whitespace-nowrap">{p}</span>
        </Fragment>
      ))}
    </span>
  );
}

/** "Transfer by Thu 8 Oct · €184.30", "Every month · +€450.00 to you", "No fixed date". */
function ItemMeta({ item, plainDate }: { item: Item; plainDate?: boolean }) {
  const date = plainDate ? (item.due_date ?? item.send_by) : actionDate(item);
  const repeats = repeatsLabel(item.recurrence);
  const incoming = isIncomingMoney(item);
  const parts: ReactNode[] = [];
  if (date)
    parts.push(
      <>
        {plainDate ? null : `${dateRole(item)} `}
        <DateText date={date} />
      </>,
    );
  if (repeats)
    parts.push(
      <>
        <Repeat className="mr-1 inline size-3 align-[-1px]" aria-hidden />
        {repeats}
      </>,
    );
  if (!date && !repeats) parts.push("No fixed date");
  if (item.amount != null)
    parts.push(
      incoming ? (
        <>
          <Money amount={item.amount} currency={item.currency} signed tone="in" /> to you
        </>
      ) : (
        <Money amount={item.amount} currency={item.currency} className="font-normal text-muted" />
      ),
    );
  else if (incoming) parts.push("Money in");
  return <Dotted parts={parts} className="mt-0.5" />;
}

/**
 * A to-do row. From 384 px of list width the countdown pill sits on the right; narrower, it moves
 * under the date line, so it never covers the date or the amount.
 */
function ItemRow({ item }: { item: Item }) {
  const date = actionDate(item);
  const inner = (
    <>
      <ItemIcon item={item} className="mt-0.5" />
      <span className="min-w-0">
        <span className="line-clamp-2 break-words text-[13.5px] font-medium leading-snug text-ink" title={item.title}>
          {item.title}
        </span>
        <ItemMeta item={item} />
      </span>
      {date ? (
        <Countdown date={date} mode={countdownMode(item)} variant="pill" className="col-start-2 justify-self-start @sm:col-start-3 @sm:row-start-1 @sm:self-center" />
      ) : null}
    </>
  );
  const cls = "-mx-2 grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-1 rounded-lg px-2 py-2 @sm:grid-cols-[auto_minmax(0,1fr)_auto]";
  return item.doc_id ? (
    <Link to={`/documents/${item.doc_id}`} className={cn(cls, "transition-colors hover:bg-surface-2")}>
      {inner}
    </Link>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

/** A to-do that is not one to act on: muted, no countdown, with the reason in one line. */
function AsideRow({ item, note }: { item: Item; note: string }) {
  const inner = (
    <>
      <ItemIcon item={item} className="mt-0.5 opacity-70" />
      <span className="min-w-0">
        <span className="line-clamp-2 break-words text-[13.5px] font-medium leading-snug text-ink/80" title={item.title}>
          {item.title}
        </span>
        <ItemMeta item={item} plainDate />
        <span className="mt-0.5 block text-[12.5px] leading-5 text-muted">{note}</span>
      </span>
    </>
  );
  const cls = "-mx-2 grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 rounded-lg px-2 py-2";
  return item.doc_id ? (
    <Link to={`/documents/${item.doc_id}`} className={cn(cls, "transition-colors hover:bg-surface-2")}>
      {inner}
    </Link>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

function Todos({ items, setAside, documents }: { items: Item[]; setAside: ItemAside[]; documents: Document[] }) {
  const today = useToday();
  const { open, aside } = useMemo(() => partyTodos(items, setAside), [items, setAside]);
  const [all, setAll] = useState(false);
  const shown = all ? open : open.slice(0, FIRST_TODOS);
  return (
    <Section title="To-dos & dates" count={open.length} id="pty-items">
      {open.length ? (
        <ul className="@container flex flex-col">
          {shown.map((i) => (
            <li key={i.id}>
              <ItemRow item={i} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted">Nothing to do for them right now.</p>
      )}
      {open.length > FIRST_TODOS ? (
        <button
          type="button"
          aria-expanded={all}
          onClick={() => setAll((v) => !v)}
          className="mt-1 inline-flex min-h-6 items-center rounded-md text-[12.5px] font-medium text-accent hover:underline"
        >
          {all ? "Show fewer" : `Show ${open.length - FIRST_TODOS} more`}
        </button>
      ) : null}
      {aside.length ? (
        <details className="group mt-2">
          <summary className="inline-flex min-h-6 cursor-pointer list-none items-center gap-1 rounded-md text-[12.5px] font-medium text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
            <ChevronRight className="size-3.5 transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden />
            Older or replaced · {aside.length}
          </summary>
          <ul className="mt-1 flex flex-col">
            {aside.map(({ item, aside: why }) => (
              <li key={item.id}>
                <AsideRow item={item} note={asideNote(why, documents, today)} />
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </Section>
  );
}

// ------------------------------------------------------------------------------------------------
// Contracts, header, jump links
// ------------------------------------------------------------------------------------------------

/**
 * A contract: its name wraps to two lines (full name on hover), the cost beside it from 384 px and
 * under it below. A rolling contract ("cancel any time") gets no countdown — nothing runs out.
 */
function ContractRow({ c }: { c: Contract }) {
  const sendBy = c.status === "active" && !isRollingContract(c) ? c.computed?.send_by : null;
  return (
    <Link
      to={contractHref(c.id)}
      className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-0.5 rounded-xl border border-line bg-surface px-3 py-2.5 transition-colors hover:border-line-strong @sm:grid-cols-[auto_minmax(0,1fr)_auto]"
    >
      <KindIcon category={c.category} size="sm" className="mt-0.5" />
      <span className="min-w-0">
        <span className="line-clamp-2 break-words text-[13.5px] font-medium leading-snug text-ink" title={c.name}>
          {c.name}
        </span>
        {c.status !== "active" ? (
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px] leading-5 text-muted">
            {copyFor(CONTRACT_CATEGORY_COPY, c.category).label}
            <StatusPill of="contract" status={c.status} />
          </span>
        ) : (
          <Dotted
            className="mt-0.5"
            parts={[
              copyFor(CONTRACT_CATEGORY_COPY, c.category).label,
              ...(sendBy
                ? [
                    <>
                      Post by <DateText date={sendBy} className="text-ink/85" />
                    </>,
                    <Countdown key="in" date={sendBy} className="text-[12.5px]" />,
                  ]
                : isRollingContract(c)
                  ? ["Cancel any time"]
                  : []),
            ]}
          />
        )}
      </span>
      {c.cost_amount != null ? (
        <Money amount={c.cost_amount} currency={c.cost_currency} interval={c.cost_interval} className="col-start-2 justify-self-start text-[13px] @sm:col-start-3 @sm:row-start-1 @sm:justify-self-end" />
      ) : null}
    </Link>
  );
}

function Header({ party }: { party: Party }) {
  const region = regionName(party.region);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <KindBadge partyKind={party.kind} size="md" label={partyKindLabel(party.kind)} />
      {looksAbroad(party) ? null : (
        <Tooltip content={region ? `Deadlines with them skip the public holidays of ${region}.` : "Their state isn't known, so only nationwide holidays count — the safer, earlier date."}>
          <button
            type="button"
            className="inline-flex min-h-6 cursor-help items-center gap-1 rounded-md text-[12.5px] text-muted underline decoration-muted/40 decoration-dotted underline-offset-[3px] hover:text-ink"
          >
            <MapPin className="size-3.5 shrink-0" aria-hidden />
            {region ? `Deadlines: ${region} holidays` : "Deadlines: nationwide holidays"}
          </button>
        </Tooltip>
      )}
    </div>
  );
}

/** Chips that scroll the drawer to a section and move focus to its heading. */
function JumpLinks({ links }: { links: { id: string; label: string }[] }) {
  const reduced = useReducedMotion();
  if (!links.length) return null;
  const jump = (id: string) => {
    const heading = document.getElementById(id);
    heading?.scrollIntoView?.({ behavior: reduced ? "auto" : "smooth", block: "start" });
    heading?.focus({ preventScroll: true });
  };
  return (
    <nav aria-label="Sections" className="mb-6">
      <ul className="flex flex-wrap gap-2">
        {links.map((l) => (
          <li key={l.id}>
            <button
              type="button"
              onClick={() => jump(l.id)}
              className="inline-flex h-7 items-center rounded-full border border-line bg-surface px-3 text-[12.5px] font-medium text-ink transition-colors hover:border-line-strong hover:bg-surface-2"
            >
              {l.label}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

// ------------------------------------------------------------------------------------------------
// The drawer
// ------------------------------------------------------------------------------------------------

/**
 * People & organisations drawer, opened from any party chip (`?party=pty_x`): identifiers with
 * copy buttons, contact details, the bank accounts they used, open to-dos & dates (older and
 * replaced ones set apart), contracts, a timeline of their letters and yours, and threads.
 */
export function PartyDrawer() {
  const { partyId, close } = usePartyDrawer();
  const { data, isLoading, isError, error, refetch, isFetching } = useParty(partyId);
  const drafts = useDrafts();
  const { copy, copied } = useClipboard();
  const party = data?.party;

  const todos = useMemo(() => partyTodos(data?.items ?? [], data?.set_aside ?? []), [data?.items, data?.set_aside]);
  const theirDrafts = useMemo(() => (drafts.data ?? []).filter((d) => d.party_id && d.party_id === partyId), [drafts.data, partyId]);
  const timeline = useMemo(() => byYear(letterTimeline(data?.documents ?? [], theirDrafts)), [data?.documents, theirDrafts]);
  const docsPerCase = useMemo(() => {
    const m = new Map<string, number>();
    for (const d of data?.documents ?? []) if (d.case_id) m.set(d.case_id, (m.get(d.case_id) ?? 0) + 1);
    return m;
  }, [data?.documents]);
  const site = websiteUrl(party?.website);
  const mailto = mailtoUrl(party?.email);
  const letters = timeline.reduce((n, g) => n + g.entries.length, 0);
  const notFound = error instanceof ApiError && error.status === 404;
  const copiedLabel = copied ? copied.slice(0, copied.indexOf("\n")) : null;

  const jumps = data
    ? [
        todos.open.length || todos.aside.length ? { id: "pty-items", label: plural(todos.open.length, "to-do", "to-dos") } : null,
        data.contracts.length ? { id: "pty-contracts", label: plural(data.contracts.length, "contract", "contracts") } : null,
        letters ? { id: "pty-letters", label: plural(letters, "letter", "letters") } : null,
        data.cases.length ? { id: "pty-threads", label: plural(data.cases.length, "thread", "threads") } : null,
      ].filter((j): j is { id: string; label: string } => j !== null)
    : [];

  return (
    <Drawer
      open={Boolean(partyId)}
      onClose={close}
      size="lg"
      eyebrow="People & organisations"
      title={party?.name ?? "Contact"}
      headerExtra={party ? <Header party={party} /> : null}
      footer={
        party ? (
          // two equal buttons; on the narrowest phones the labels shorten to "Write" and "Ask" (the
          // accessible names stay whole and start with the visible words)
          <div className="grid grid-cols-2 gap-2">
            <Link
              to={`/letters?kind=general_reply&to=${encodeURIComponent(party.id)}`}
              aria-label="Write to them"
              className={buttonVariants({ variant: "secondary", size: "md", className: "min-w-0 px-3" })}
            >
              <PenLine aria-hidden />
              <span>
                Write<span className="max-[359px]:hidden"> to them</span>
              </span>
            </Link>
            <Link
              to={`/ask?q=${encodeURIComponent(`What do I have open with ${party.name}?`)}`}
              aria-label="Ask about them"
              className={buttonVariants({ variant: "secondary", size: "md", className: "min-w-0 px-3" })}
            >
              <MessagesSquare aria-hidden />
              <span>
                Ask<span className="max-[359px]:hidden"> about them</span>
              </span>
            </Link>
          </div>
        ) : null
      }
    >
      {/* one polite announcement for every copy button */}
      <p role="status" aria-live="polite" className="sr-only">
        {copiedLabel ? `${copiedLabel} copied` : ""}
      </p>
      {isLoading ? (
        <div className="space-y-4" aria-busy="true">
          <Skeleton className="h-16 w-full rounded-xl" />
          <SkeletonText lines={4} />
          <Skeleton className="h-24 w-full rounded-xl" />
        </div>
      ) : isError && !notFound ? (
        <EmptyState
          illustration="error"
          variant="plain"
          title="Couldn't load this contact"
          description="Your letters are safe — Ordnung didn't answer. Is it still running?"
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="primary" icon={RotateCw} loading={isFetching} onClick={() => void refetch()}>
                Try again
              </Button>
              <Button onClick={close}>Close</Button>
            </div>
          }
        />
      ) : !data || !party ? (
        <EmptyState
          illustration="search"
          variant="plain"
          title="We couldn't find this contact"
          description="It may have been merged with another one or deleted."
          action={<Button onClick={close}>Close</Button>}
        />
      ) : (
        <div>
          <JumpLinks links={jumps} />
          {party.aliases.length ? <p className="-mt-3 mb-6 break-words text-[13px] leading-5 text-muted">Also known as {party.aliases.join(", ")}</p> : null}

          {party.identifiers.length ? (
            <Section title="Your numbers with them" id="pty-ids">
              <dl className="@container divide-y divide-line rounded-xl border border-line bg-surface">
                {party.identifiers.map((id) => (
                  <IdRow key={id.label + id.value} label={id.label} value={id.value} kind={identifierStyle(id.value)} copier={{ copy, copied }} />
                ))}
              </dl>
              <p className="mt-1.5 px-1 text-[12px] text-muted">Quote these when you write or call.</p>
            </Section>
          ) : null}

          {party.ibans.length ? (
            <Section title={party.ibans.length === 1 ? "Bank account they use" : "Bank accounts they used"} id="pty-ibans">
              <dl className="@container divide-y divide-line rounded-xl border border-line bg-surface">
                {party.ibans.map((iban, i) => (
                  <IdRow key={iban} label={party.ibans.length > 1 ? `IBAN ${i + 1}` : "IBAN"} value={iban.replace(/\s+/g, "")} kind="iban" copier={{ copy, copied }} />
                ))}
              </dl>
              {party.ibans.length > 1 ? (
                <p className="mt-2 flex items-start gap-2 rounded-lg bg-warn-soft px-3 py-2 text-[12.5px] leading-5 text-warn-ink">
                  <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  They used more than one account. Before paying, check the IBAN on the letter matches one you know.
                </p>
              ) : (
                <p className="mt-1.5 flex items-start gap-1.5 px-1 text-[12px] leading-[18px] text-muted">
                  <Landmark className="mt-0.5 size-3.5 shrink-0" aria-hidden /> Seen on their letters. Ordnung warns you if a letter asks you to pay somewhere else.
                </p>
              )}
            </Section>
          ) : null}

          {party.address || party.email || party.phone || site ? (
            <Section title="Contact" id="pty-contact">
              <ul className="space-y-1.5 text-[13.5px]">
                {party.address ? (
                  <li className="flex items-start gap-2.5">
                    <MapPin className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
                    <span className="min-w-0 break-words text-ink">{keepNumbersTogether(party.address)}</span>
                  </li>
                ) : null}
                {party.email ? (
                  <li className="flex items-center gap-2.5">
                    <AtSign className="size-4 shrink-0 text-muted" aria-hidden />
                    {mailto ? (
                      <a href={mailto} className="inline-flex min-h-6 min-w-0 items-center text-accent hover:underline">
                        <span className="min-w-0 wrap-anywhere">{party.email}</span>
                      </a>
                    ) : (
                      <span className="min-w-0 wrap-anywhere text-ink">{party.email}</span>
                    )}
                  </li>
                ) : null}
                {party.phone ? (
                  <li className="flex items-center gap-2.5">
                    <Phone className="size-4 shrink-0 text-muted" aria-hidden />
                    <a href={`tel:${party.phone.replace(/[^\d+]/g, "")}`} className="inline-flex min-h-6 items-center text-accent hover:underline">
                      {party.phone}
                    </a>
                  </li>
                ) : null}
                {site ? (
                  <li className="flex items-center gap-2.5">
                    <Globe className="size-4 shrink-0 text-muted" aria-hidden />
                    <a href={site} target="_blank" rel="noreferrer noopener" className="inline-flex min-h-6 min-w-0 items-center gap-1 text-accent hover:underline">
                      <span className="min-w-0 wrap-anywhere">{party.website?.replace(/^https?:\/\//, "")}</span>
                      <ExternalLink className="size-3 shrink-0" aria-hidden />
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
                <span className="min-w-0 break-words">{party.notes}</span>
              </p>
            </Section>
          ) : null}

          {todos.open.length || todos.aside.length ? <Todos items={data.items} setAside={data.set_aside} documents={data.documents} /> : null}

          {data.contracts.length ? (
            <Section title="Contracts" count={data.contracts.length} id="pty-contracts">
              <ul className="@container space-y-2">
                {data.contracts.map((c) => (
                  <li key={c.id}>
                    <ContractRow c={c} />
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}

          {timeline.length ? (
            <Section title="Letters" count={letters} id="pty-letters">
              <div className="space-y-4">
                {timeline.map((g) => (
                  <div key={g.year}>
                    <p className="mb-1 text-[12px] font-semibold tabular-nums text-muted">{g.year}</p>
                    <ol className="relative ml-[13px] border-l border-line">
                      {g.entries.map((e) => (
                        <li key={e.id} className="relative">
                          {/* the dot sits outside the link, so its hover and focus ring never cut through it */}
                          <span
                            className={cn(
                              "pointer-events-none absolute -left-[9px] top-2.5 grid size-[18px] place-items-center rounded-full ring-4 ring-canvas",
                              e.direction === "in" ? "bg-surface-3 text-muted" : "bg-accent-soft text-accent",
                            )}
                            aria-hidden
                          >
                            {e.direction === "in" ? <ArrowDownLeft className="size-3" /> : <ArrowUpRight className="size-3" />}
                          </span>
                          <Link
                            to={e.href}
                            className="group ml-4 flex items-start gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-surface-2/70 focus-visible:outline-offset-0"
                          >
                            <span className="min-w-0 flex-1">
                              <span className="line-clamp-2 break-words text-[13.5px] font-medium leading-snug text-ink group-hover:text-accent" title={e.title}>
                                {e.title}
                              </span>
                              <span className="mt-0.5 block break-words text-[12.5px] leading-5 text-muted">
                                {e.direction === "in" ? "From them" : "From you"}
                                <span aria-hidden> · </span>
                                <span lang={e.subtitle ? "de" : undefined}>
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
                      <span className="block break-words font-medium text-ink">{c.title}</span>
                      {c.summary ? <span className="mt-0.5 block break-words text-[12.5px] leading-5 text-muted">{c.summary}</span> : null}
                      <span className="mt-1 block break-words text-[12px] text-muted">
                        {c.status === "open" ? "Open" : "Closed"}
                        {docsPerCase.get(c.id) ? ` · ${plural(docsPerCase.get(c.id)!, "letter", "letters")}` : ""}
                        {c.reference ? ` · Ref. ${keepNumbersTogether(c.reference)}` : ""}
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
