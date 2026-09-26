/**
 * Plain text that may mention ledger records by id ("doc_0b2t88kqsf2n describes the fee increase…",
 * written by the weekly review): every id becomes the record's title, linked to it. Ids never show
 * (SPEC §14 copy rule; `findRawEnums` flags them in tests).
 */
import { Fragment } from "react";
import { Link } from "react-router";
import { usePartyDrawer } from "@/lib/party-drawer";
import { RECORD_ID_RE, RECORD_TYPES, splitRecordIds } from "@/lib/copy";
import { useRefResolver } from "./refs";

const MAX_TITLE = 48;

function short(title: string): string {
  return title.length > MAX_TITLE ? `${title.slice(0, MAX_TITLE - 1).trimEnd()}…` : title;
}

export function RefText({ text }: { text: string }) {
  // the ledger lists are only needed (and fetched) when the text mentions a record
  return RECORD_ID_RE.test(text) ? <Resolved text={text} /> : <>{text}</>;
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
        const label = `“${short(info.title)}”`;
        const cls = "font-medium text-ink underline decoration-line-strong underline-offset-2 hover:decoration-accent";
        if (info.href) {
          return (
            <Link key={i} to={info.href} className={cls} title={info.title}>
              {label}
            </Link>
          );
        }
        if (type === "party") {
          return (
            <button key={i} type="button" onClick={() => drawer.open(part.id)} className={cls} title={info.title}>
              {short(info.title)}
            </button>
          );
        }
        return <Fragment key={i}>{label}</Fragment>;
      })}
    </>
  );
}
