/**
 * People & organisations: the letters timeline (their letters and yours, newest first, grouped by
 * year) and small helpers for the drawer.
 */
import type { Document, Draft } from "@/api/types";
import { BUNDESLAENDER } from "@/features/onboarding/options";

export interface TimelineLetter {
  id: string;
  date: string | null;
  title: string;
  /** e.g. the German subject of your letter */
  subtitle?: string;
  direction: "in" | "out";
  href: string;
  /** letter kind (incoming) or draft kind (outgoing) — mapped to copy by the UI */
  docKind?: Document["kind"];
  draftKind?: Draft["kind"];
  status?: Draft["status"];
}

const OUT_TITLE: Record<Draft["kind"], string> = {
  cancellation: "Your cancellation",
  objection: "Your objection",
  general_reply: "Your reply",
  withdrawal: "Your withdrawal",
  extension_request: "Your request for more time",
  payment_plan: "Your instalment request",
  defect_notice: "Your defect notice",
  data_access: "Your data request",
  receipts_inspection: "Your receipts request",
  deposit_return: "Your deposit request",
  address_change: "Your new address",
};

/** Their letters and the letters you wrote to them, newest first (undated last). */
export function letterTimeline(documents: Document[], drafts: Draft[]): TimelineLetter[] {
  const inbound: TimelineLetter[] = documents
    .filter((d) => !d.deleted_at)
    .map((d) => ({
      id: d.id,
      date: d.doc_date ?? d.received_date ?? d.created_at.slice(0, 10),
      title: d.title ?? d.filename,
      direction: d.direction === "outgoing" ? "out" : "in",
      href: `/documents/${d.id}`,
      docKind: d.kind,
    }));
  const outbound: TimelineLetter[] = drafts.map((d) => ({
    id: d.id,
    date: (d.sent_at ?? d.created_at).slice(0, 10),
    title: OUT_TITLE[d.kind],
    subtitle: d.subject || undefined,
    direction: "out",
    href: `/letters/${d.id}`,
    draftKind: d.kind,
    status: d.status,
  }));
  return [...inbound, ...outbound].sort((a, b) => (b.date ?? "").localeCompare(a.date ?? ""));
}

/** Group by year, keeping order. */
export function byYear(entries: TimelineLetter[]): { year: string; entries: TimelineLetter[] }[] {
  const out: { year: string; entries: TimelineLetter[] }[] = [];
  for (const e of entries) {
    const year = e.date?.slice(0, 4) ?? "Undated";
    const last = out[out.length - 1];
    if (last?.year === year) last.entries.push(e);
    else out.push({ year, entries: [e] });
  }
  return out;
}

/** "North Rhine-Westphalia" for "NW"; null when unknown. */
export function regionName(code: string | null | undefined): string | null {
  if (!code) return null;
  const b = BUNDESLAENDER.find((x) => x.code === code.toUpperCase());
  return b ? (b.en ?? b.name) : null;
}

/** Normalise a website value to an https URL (null for anything that isn't a plain host/path). */
/**
 * A `mailto:` link for a sender's e-mail address, or `null` when it isn't a plain address (it comes from
 * a letter, so `?cc=…&body=…` or other tricks must not end up in the person's mail program).
 */
export function mailtoUrl(email: string | null | undefined): string | null {
  const address = email?.trim() ?? "";
  if (!/^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$/i.test(address)) return null;
  return `mailto:${address}`;
}

export function websiteUrl(site: string | null | undefined): string | null {
  if (!site) return null;
  const host = site.trim().replace(/^https?:\/\//i, "");
  if (!/^[a-z0-9.-]+\.[a-z]{2,}(\/[^\s]*)?$/i.test(host)) return null;
  return `https://${host}`;
}
