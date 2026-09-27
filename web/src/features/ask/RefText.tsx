/**
 * Plain text that may mention ledger records by id ("doc_0b2t88kqsf2n describes the fee increase…",
 * written by the weekly review) and web addresses: every id becomes the record's title, linked to it;
 * ids never show (SPEC §14 copy rule; `findRawEnums` flags them in tests). A record's whole title is
 * shown — it wraps with the text instead of being cut after 48 characters mid-word (UI audit round 1).
 *
 * An address of a site Ordnung itself cites — the law, courts, public and advice services
 * (`secretary/triggers.py`, `rules/catalog.py`) — becomes a short link to its site
 * ("gesetze-im-internet.de ↗") that opens in a new tab. Any other address stays text that wraps: it
 * may have come from a letter, and a link from a letter is how a scam gets its click.
 */
import { Fragment } from "react";
import { Link } from "react-router";
import { ExternalLink } from "lucide-react";
import { usePartyDrawer } from "@/lib/party-drawer";
import { RECORD_ID_RE, RECORD_TYPES, splitRecordIds } from "@/lib/copy";
import { NB_HYPHEN } from "@/lib/glue";
import { useRefResolver } from "./refs";

/** Sites Ordnung's own ideas and rules link to (a host or any of its subdomains). */
const TRUSTED_HOSTS = [
  "gesetze-im-internet.de",
  "dejure.org",
  "justiz.de",
  "justizadressen.nrw.de",
  "online-mahnantrag.de",
  "bundesarbeitsgericht.de",
  "arbeitsagentur.de",
  "studierendenwerke.de",
  "verbraucherzentrale.de",
  "mieterbund.de",
  "meine-schulden.de",
  "dgbrechtsschutz.de",
  "anwaltauskunft.de",
  "deubner-recht.de",
];

const URL_RE = /https?:\/\/[^\s<>"“”„'()]+/g;
/** Display only (selected text is copied without it, `copyWithoutGlue`). */
const protectHyphens = (text: string) => text.replace(/-/g, NB_HYPHEN);
/** Punctuation that ends the sentence, not the address ("… see https://dejure.org."). */
const TRAILING = /[.,;:!?]+$/;

type Part = { kind: "text"; text: string } | { kind: "url"; href: string; host: string } | { kind: "address"; text: string };

/** The host of an https address Ordnung trusts, else null. */
export function trustedHost(href: string): string | null {
  try {
    const url = new URL(href);
    const host = url.hostname.toLowerCase().replace(/^www\./, "");
    if (url.protocol !== "https:") return null;
    return TRUSTED_HOSTS.some((h) => host === h || host.endsWith(`.${h}`)) ? host : null;
  } catch {
    return null;
  }
}

/** `text` split into plain runs, trusted web addresses (links) and other addresses (text) — exported for tests. */
export function splitLinks(text: string): Part[] {
  const parts: Part[] = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    const href = m[0].replace(TRAILING, "");
    const host = trustedHost(href);
    const at = m.index ?? 0;
    if (at > last) parts.push({ kind: "text", text: text.slice(last, at) });
    parts.push(host ? { kind: "url", href, host } : { kind: "address", text: href });
    last = at + href.length;
  }
  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  return parts;
}

export function RefText({ text }: { text: string }) {
  return (
    <>
      {splitLinks(text).map((part, i) =>
        part.kind === "url" ? (
          <a
            key={i}
            href={part.href}
            target="_blank"
            rel="noreferrer noopener"
            title={part.href}
            className="font-medium text-accent underline-offset-2 [overflow-wrap:anywhere] hover:underline"
          >
            {/* a site's name doesn't break at its hyphens ("gesetze-im- / internet.de") unless it has to */}
            {protectHyphens(part.host)}
            <span className="sr-only"> (opens in a new tab)</span>
            {"⁠"}
            <ExternalLink className="ml-0.5 inline size-3 align-[-0.1em]" aria-hidden />
          </a>
        ) : part.kind === "address" ? (
          // a long address breaks anywhere rather than widen the card (UI audit round 1: past the edge at 320 px)
          <span key={i} className="[overflow-wrap:anywhere]">
            {part.text}
          </span>
        ) : // the ledger lists are only needed (and fetched) when the text mentions a record
        RECORD_ID_RE.test(part.text) ? (
          <Resolved key={i} text={part.text} />
        ) : (
          <Fragment key={i}>{part.text}</Fragment>
        ),
      )}
    </>
  );
}

function Resolved({ text }: { text: string }) {
  const { resolve } = useRefResolver();
  const drawer = usePartyDrawer();
  return (
    <>
      {splitRecordIds(text).map((part, i) => {
        if (part.kind === "text") return <Fragment key={i}>{part.text}</Fragment>;
        const type = RECORD_TYPES[part.prefix];
        if (!type) return <Fragment key={i}>a record</Fragment>;
        const info = resolve({ type, id: part.id });
        const label = `“${info.title}”`;
        const cls = "font-medium text-ink underline decoration-line-strong underline-offset-2 [overflow-wrap:anywhere] hover:decoration-accent";
        if (info.href) {
          return (
            <Link key={i} to={info.href} className={cls}>
              {label}
            </Link>
          );
        }
        if (type === "party") {
          return (
            <button key={i} type="button" onClick={() => drawer.open(part.id)} className={cls}>
              {info.title}
            </button>
          );
        }
        return <Fragment key={i}>{label}</Fragment>;
      })}
    </>
  );
}
