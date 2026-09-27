/**
 * In-memory mock database: a deep copy of the sample life that mutations modify, plus the
 * computed views the real API derives (dashboard, timeline, lanes, search).
 */
import type {
  AreaStatus,
  Case,
  ChatMessage,
  Contract,
  Dashboard,
  Document,
  Draft,
  Evidence,
  Item,
  Lane,
  LaneBar,
  MailTrayItem,
  Party,
  Suggestion,
  TimelineEntry,
  TimelineMarker,
  TourState,
  Activity,
  Profile,
  AppSettings,
  Health,
  Area,
} from "@/api/types";
import { addDays, differenceInCalendarDays, parseISO, format } from "date-fns";
import { PARTIES, TRAY_ONLY_PARTIES } from "./data/parties";
import { CASES, DOCUMENTS, TRAY_CASES, TRAY_DOCUMENTS } from "./data/documents";
import { ITEMS, TRAY_ITEMS } from "./data/items";
import { CONTRACTS } from "./data/contracts";
import { SUGGESTIONS, TRAY_SUGGESTIONS } from "./data/suggestions";
import { DRAFTS } from "./data/drafts";
import { ACTIVITY, HEALTH, MAIL_TRAY, PROFILE, SETTINGS, TOUR, TRAY_DOC } from "./data/system";
import { LETTERS } from "./data/letters";
import { renderLetter, type RenderedLetter } from "./pages";
import { TODAY } from "./data/constants";

const clone = <T>(v: T): T => (typeof structuredClone === "function" ? structuredClone(v) : JSON.parse(JSON.stringify(v)));

const rendered = new Map<string, RenderedLetter>();

/** Rendered page images + layout for a document (cached). */
export function letterFor(docId: string): RenderedLetter | null {
  if (rendered.has(docId)) return rendered.get(docId)!;
  const spec = LETTERS[docId];
  if (!spec) return null;
  const r = renderLetter(spec);
  rendered.set(docId, r);
  return r;
}

/** Fill page + boxes of evidence by locating the quote on the rendered letter. */
function resolveEvidence(e: Evidence): Evidence {
  const letter = letterFor(e.doc_id);
  if (!letter) return e;
  const hit = letter.locate(e.quote, e.page);
  if (!hit) return { ...e, grounding: e.grounding === "user" ? "user" : "unverified", boxes: [], score: 0.4 };
  return { ...e, page: hit.page, boxes: hit.boxes };
}

function resolveAll<T extends { evidence: Evidence[] }>(rows: T[]): T[] {
  return rows.map((r) => ({ ...r, evidence: r.evidence.map(resolveEvidence) }));
}

function resolveDoc(d: Document): Document {
  return { ...d, key_facts: d.key_facts.map((f) => (f.evidence ? { ...f, evidence: resolveEvidence(f.evidence) } : f)) };
}

const daysFrom = (a: string, b: string) => differenceInCalendarDays(parseISO(a), parseISO(b));
const iso = (d: Date) => format(d, "yyyy-MM-dd");
const nowTs = () => new Date().toISOString().replace(/\.\d+Z$/, "Z");

export interface MockState {
  health: Health;
  profile: Profile;
  settings: AppSettings;
  parties: Party[];
  cases: Case[];
  documents: Document[];
  items: Item[];
  contracts: Contract[];
  suggestions: Suggestion[];
  drafts: Draft[];
  activity: Activity[];
  chat: ChatMessage[];
  tray: MailTrayItem[];
  tour: TourState;
  lastCalendarExport: string;
  /** documents uploaded in this session (for page images of unknown files) */
  uploads: Record<string, { name: string; objectUrl?: string }>;
}

export class MockDb {
  state: MockState;

  constructor() {
    this.state = {
      health: clone(HEALTH),
      profile: clone(PROFILE),
      settings: clone(SETTINGS),
      parties: clone(PARTIES.filter((p) => !TRAY_ONLY_PARTIES.has(p.id))),
      cases: clone(CASES),
      documents: clone(DOCUMENTS).map(resolveDoc),
      items: resolveAll(clone(ITEMS)),
      contracts: resolveAll(clone(CONTRACTS)),
      suggestions: clone(SUGGESTIONS),
      drafts: clone(DRAFTS),
      activity: clone(ACTIVITY),
      chat: [],
      tray: clone(MAIL_TRAY),
      tour: clone(TOUR),
      lastCalendarExport: "2026-09-20T16:00:00Z",
      uploads: {},
    };
  }

  get today(): string {
    return this.state.health.today ?? TODAY;
  }

  // ---------------------------------------------------------------------------------------------
  // lookups
  // ---------------------------------------------------------------------------------------------

  party(id: string | null | undefined): Party | null {
    return this.state.parties.find((p) => p.id === id) ?? null;
  }
  document(id: string): Document | null {
    return this.state.documents.find((d) => d.id === id && !d.deleted_at) ?? null;
  }
  liveDocuments(): Document[] {
    return this.state.documents.filter((d) => !d.deleted_at);
  }

  /** Apply the processed result of a New-mail tray letter (docs, items, ideas, parties). */
  applyTrayDocument(docId: string): Document | null {
    const full = TRAY_DOCUMENTS[docId];
    if (!full) return null;
    if (full.party_id && !this.party(full.party_id)) {
      const p = PARTIES.find((x) => x.id === full.party_id);
      if (p) this.state.parties.push(clone(p));
    }
    for (const c of TRAY_CASES) if (c.id === full.case_id && !this.state.cases.some((x) => x.id === c.id)) this.state.cases.push(clone(c));
    const now = nowTs();
    const processed = resolveDoc({ ...clone(full), created_at: now, updated_at: now, processed_at: now, ai_processed_at: now });
    this.upsertDocument(processed);
    for (const it of resolveAll(clone(TRAY_ITEMS[docId] ?? []))) {
      if (!this.state.items.some((x) => x.id === it.id)) this.state.items.push({ ...it, created_at: now, updated_at: now });
    }
    for (const s of clone(TRAY_SUGGESTIONS[docId] ?? [])) {
      if (!this.state.suggestions.some((x) => x.id === s.id)) this.state.suggestions.unshift({ ...s, created_at: now, updated_at: now });
    }
    if (docId === "doc_power_price") {
      const c = this.state.contracts.find((x) => x.id === "ctr_power");
      if (c?.computed) {
        c.computed = {
          ...c.computed,
          cancel_by: "2026-10-31",
          send_by: "2026-10-27",
          safe_date: "2026-10-30",
          warnings: ["Price increase from 1 Nov: €55.00/month (+€84/year). Special right to cancel until 31 Oct."],
        };
        c.updated_at = now;
      }
    }
    this.log("document.processed", `Read “${processed.title}” (${processed.pages} ${processed.pages === 1 ? "page" : "pages"})`, "document", docId);
    return processed;
  }

  upsertDocument(d: Document) {
    const i = this.state.documents.findIndex((x) => x.id === d.id);
    if (i >= 0) this.state.documents[i] = d;
    else this.state.documents.unshift(d);
  }

  log(kind: string, message: string, ref_type: string | null = null, ref_id: string | null = null, data: Record<string, unknown> = {}) {
    const id = Math.max(0, ...this.state.activity.map((a) => a.id)) + 1;
    this.state.activity.unshift({ id, ts: nowTs(), kind, message, ref_type, ref_id, data });
  }

  trayDocFor(mailId: string): string | undefined {
    return TRAY_DOC[mailId];
  }

  // ---------------------------------------------------------------------------------------------
  // views
  // ---------------------------------------------------------------------------------------------

  /** Effective date for sorting: send-by first, else due date. */
  private eff(i: Item): string | null {
    return i.send_by ?? i.due_date;
  }

  openItems(): Item[] {
    const today = this.today;
    return this.state.items.filter(
      (i) => i.status === "open" || (i.status === "snoozed" && (!i.snoozed_until || i.snoozed_until <= today)),
    );
  }

  dashboard(): Dashboard {
    const today = this.today;
    const open = this.openItems().filter((i) => this.eff(i));
    const needsReviewDocs = new Set(this.liveDocuments().filter((d) => d.status === "needs_review").map((d) => d.id));
    const score = (i: Item) => {
      const days = daysFrom(this.eff(i)!, today);
      const pr = { low: 0, normal: 1, high: 2, critical: 3 }[i.priority];
      return days - pr * 2 - (i.doc_id && needsReviewDocs.has(i.doc_id) ? 3 : 0);
    };
    const attention = open
      .filter((i) => {
        const days = daysFrom(this.eff(i)!, today);
        return days <= 7 || (i.priority !== "normal" && i.priority !== "low" && days <= 12);
      })
      .sort((a, b) => score(a) - score(b));
    const attentionIds = new Set(attention.map((i) => i.id));
    const upcoming = open
      .filter((i) => !attentionIds.has(i.id) && daysFrom(i.due_date ?? this.eff(i)!, today) <= 30)
      .sort((a, b) => (this.eff(a)! < this.eff(b)! ? -1 : 1));
    const decisions = this.state.contracts.filter((c) => c.status === "active" && c.computed?.send_by && daysFrom(c.computed.send_by, today) >= 0 && daysFrom(c.computed.send_by, today) <= 60);
    const in30 = iso(addDays(parseISO(today), 30));
    const payments = open.filter((i) => i.kind === "payment" && i.direction !== "in" && i.due_date && i.due_date <= in30).sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1));
    const byCat: Record<string, number> = {};
    const otherCurrencies: Record<string, number> = {}; // like the API: fixed costs in euros, other currencies apart
    let fixed = 0;
    for (const c of this.state.contracts) {
      if (c.status !== "active" || c.cost_amount == null || !c.cost_interval || c.cost_interval === "once") continue;
      const m = Math.round(c.cost_amount * { monthly: 1, quarterly: 1 / 3, yearly: 1 / 12 }[c.cost_interval] * 100) / 100;
      const currency = (c.cost_currency || "EUR").toUpperCase();
      if (currency !== "EUR") {
        otherCurrencies[currency] = Math.round(((otherCurrencies[currency] ?? 0) + m) * 100) / 100;
        continue;
      }
      fixed += m;
      byCat[c.category] = Math.round(((byCat[c.category] ?? 0) + m) * 100) / 100;
    }
    const evidence = [...this.state.items.flatMap((i) => i.evidence), ...this.state.contracts.flatMap((c) => c.evidence)];
    const verified = evidence.filter((e) => e.grounding === "verified" || e.grounding === "user").length;
    return {
      today,
      greeting_name: this.state.profile.name.split(" ")[0] ?? "",
      simulated: Boolean(this.state.health.simulated_today),
      attention,
      upcoming,
      decisions,
      money: {
        due_this_month: Math.round(payments.reduce((s, i) => s + (i.amount ?? 0), 0) * 100) / 100,
        fixed_costs_monthly: Math.round(fixed * 100) / 100,
        fixed_costs_monthly_other_currencies: otherCurrencies,
        upcoming_payments: payments.slice(0, 6),
        by_category: byCat,
      },
      areas: this.areas(),
      suggestions: this.state.suggestions.filter((s) => s.status === "new").sort((a, b) => prio(b.priority) - prio(a.priority)),
      recent_documents: [...this.liveDocuments()].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)).slice(0, 6),
      stats: {
        documents: this.liveDocuments().length,
        open_items: this.openItems().length,
        contracts: this.state.contracts.filter((c) => c.status === "active").length,
        parties: this.state.parties.length,
        verified_ratio: evidence.length ? Math.round((verified / evidence.length) * 100) / 100 : 0,
      },
    };
  }

  areas(): AreaStatus[] {
    const today = this.today;
    const labels: Partial<Record<Area, string>> = {
      residence: "Residence",
      home: "Home",
      money: "Money",
      study: "Study",
      work: "Work",
      health: "Health",
      mobility: "Getting around",
      insurance: "Insurance",
      tax: "Tax",
      leisure: "Leisure",
    };
    const out: AreaStatus[] = [];
    for (const area of Object.keys(labels) as Area[]) {
      const items = this.openItems()
        .filter((i) => i.area === area && i.due_date)
        .sort((a, b) => (this.eff(a)! < this.eff(b)! ? -1 : 1));
      const hasData = items.length || this.liveDocuments().some((d) => d.area === area);
      if (!hasData) continue;
      const next = items[0];
      const days = next ? daysFrom(this.eff(next)!, today) : 999;
      const status: AreaStatus["status"] = days <= 3 ? "urgent" : days <= 14 ? "attention" : "ok";
      out.push({
        area,
        label: labels[area]!,
        status,
        headline: next ? next.title : "Nothing coming up",
        next_date: next ? this.eff(next) : null,
        count: items.length,
      });
    }
    return out;
  }

  timeline(from?: string | null, to?: string | null): TimelineEntry[] {
    const today = this.today;
    const out: TimelineEntry[] = [];
    for (const i of this.state.items) {
      if (!i.due_date || i.status === "dismissed") continue;
      const p = this.party(i.party_id);
      out.push({
        id: `tl_${i.id}`,
        date: i.due_date,
        time: i.due_time,
        type: i.kind,
        title: i.title,
        subtitle: i.send_by ? `Send by ${format(parseISO(i.send_by), "EEE d MMM")}` : p?.name ?? null,
        status: i.status === "open" && i.due_date < today ? "missed" : i.status,
        priority: i.priority,
        area: i.area,
        ref: { type: "item", id: i.id },
        party_name: p?.name ?? null,
        amount: i.amount,
        currency: i.currency,
        past: i.due_date < today,
      });
    }
    for (const d of this.liveDocuments()) {
      const date = d.received_date ?? d.doc_date;
      if (!date) continue;
      const p = this.party(d.party_id);
      out.push({
        id: `tl_${d.id}`,
        date,
        time: null,
        type: "document",
        title: d.title ?? d.filename,
        subtitle: p ? `Letter from ${p.name}` : "Letter",
        status: d.status,
        priority: d.urgency ?? "normal",
        area: d.area ?? "other",
        ref: { type: "document", id: d.id },
        party_name: p?.name ?? null,
        amount: null,
        currency: null,
        past: date < today,
      });
    }
    for (const c of this.state.contracts) {
      const p = this.party(c.party_id);
      if (c.computed?.current_term_end && c.category !== "employment") {
        out.push({
          id: `tl_${c.id}_term`,
          date: c.computed.current_term_end,
          time: null,
          type: "contract",
          title: `${c.name}: current term ends`,
          subtitle: c.computed.cancel_by && c.computed.cancel_by > today ? `Cancel by ${format(parseISO(c.computed.cancel_by), "d MMM")}` : "Renews automatically",
          status: c.status,
          priority: "normal",
          area: c.area,
          ref: { type: "contract", id: c.id },
          party_name: p?.name ?? null,
          amount: c.cost_amount,
          currency: c.cost_currency,
          past: c.computed.current_term_end < today,
        });
      }
    }
    for (const d of this.state.drafts) {
      if (d.status !== "sent" || !d.sent_at) continue;
      const p = this.party(d.party_id);
      const date = d.sent_at.slice(0, 10);
      out.push({
        id: `tl_${d.id}`,
        date,
        time: null,
        type: "draft",
        title: `You sent: ${d.subject}`,
        subtitle: p?.name ?? null,
        status: "sent",
        priority: "normal",
        area: "other",
        ref: { type: "draft", id: d.id },
        party_name: p?.name ?? null,
        amount: null,
        currency: null,
        past: date < today,
      });
    }
    return out
      .filter((e) => (!from || e.date >= from) && (!to || e.date <= to))
      .sort((a, b) => (a.date === b.date ? (a.time ?? "") < (b.time ?? "") ? -1 : 1 : a.date < b.date ? -1 : 1));
  }

  lanes(from?: string | null, to?: string | null): Lane[] {
    const today = this.today;
    const has = (id: string) => this.state.items.some((i) => i.id === id);
    const statusFor = (end: string): LaneBar["status"] => {
      const d = daysFrom(end, today);
      if (d < 0) return "past";
      if (d <= 21) return "urgent";
      if (d <= 75) return "attention";
      return "ok";
    };
    const m = (date: string, label: string, kind: TimelineMarker["kind"]): TimelineMarker => ({ date, label, kind });
    const bar = (b: Omit<LaneBar, "status" | "markers" | "ref"> & Partial<LaneBar>): LaneBar => ({
      status: b.status ?? statusFor(b.end),
      markers: [],
      ref: null,
      ...b,
    });

    const lanes: Lane[] = [
      {
        id: "lane_residence",
        label: "Residence",
        area: "residence",
        bars: [
          bar({ id: "bar_permit", label: "Residence permit", start: "2024-12-01", end: "2026-11-30", kind: "validity", ref: { type: "document", id: "doc_abh" }, markers: [m("2026-10-14", "Appointment 10:30", "appointment"), m("2026-11-30", "Permit expires", "expiry")] }),
        ],
        markers: [],
      },
      {
        id: "lane_passport",
        label: "Passport",
        area: "residence",
        bars: [bar({ id: "bar_passport", label: "Passport valid", start: "2017-02-11", end: "2027-02-10", kind: "validity", ref: { type: "document", id: "doc_passport" }, markers: [m("2027-02-10", "Passport expires", "expiry")] })],
        markers: [],
      },
      {
        id: "lane_home",
        label: "Home",
        area: "home",
        bars: [bar({ id: "bar_lease", label: "Lease Beispielweg 5 (open-ended)", start: "2025-10-01", end: "2027-12-31", kind: "contract", status: "ok", ref: { type: "contract", id: "ctr_rent" } })],
        markers: [m("2026-10-05", "Rent", "payment"), m("2026-10-09", "Utility back payment €184.30", "payment"), m("2026-11-15", "Broadcasting fee", "payment")],
      },
      {
        id: "lane_phone",
        label: "Phone · FunkNetz",
        area: "home",
        bars: [
          bar({ id: "bar_phone_term", label: "Minimum term", start: "2024-11-15", end: "2026-11-14", kind: "contract", ref: { type: "contract", id: "ctr_phone" }, markers: [m("2026-11-14", "Minimum term ends", "renewal")] }),
          bar({ id: "bar_phone_notice", label: "Time to cancel", start: "2026-08-15", end: "2026-10-14", kind: "notice_window", ref: { type: "contract", id: "ctr_phone" }, markers: [m("2026-10-08", "Send by", "send_by"), m("2026-10-14", "Cancel by", "cancel_by")] }),
          bar({ id: "bar_phone_after", label: "Month to month", start: "2026-11-15", end: "2027-12-31", kind: "contract", status: "ok", ref: { type: "contract", id: "ctr_phone" } }),
        ],
        markers: [],
      },
      {
        id: "lane_power",
        label: "Electricity · Stadtwerke",
        area: "home",
        bars: [
          bar({ id: "bar_power", label: "MusterStrom Natur", start: "2025-10-01", end: "2027-12-31", kind: "contract", status: "ok", ref: { type: "contract", id: "ctr_power" } }),
          ...(has("itm_power_cancel")
            ? [bar({ id: "bar_power_right", label: "Special right to cancel", start: "2026-09-28", end: "2026-10-31", kind: "notice_window", ref: { type: "document", id: "doc_power_price" }, markers: [m("2026-10-27", "Send by (post)", "send_by"), m("2026-10-31", "Cancel by", "cancel_by")] })]
            : []),
        ],
        markers: has("itm_power_new") ? [m("2026-11-01", "Price rises (+€84/year)", "other")] : [],
      },
      {
        id: "lane_insurance",
        label: "Liability insurance",
        area: "insurance",
        bars: [
          bar({ id: "bar_liab_2026", label: "Insurance year", start: "2025-12-01", end: "2026-11-30", kind: "contract", status: "ok", ref: { type: "contract", id: "ctr_liability" } }),
          bar({ id: "bar_liab_2027", label: "Insurance year (renewed)", start: "2026-12-01", end: "2027-11-30", kind: "contract", status: "ok", ref: { type: "contract", id: "ctr_liability" }, markers: [m("2026-12-01", "Renews · €59.90", "renewal")] }),
          bar({ id: "bar_liab_notice", label: "Time to cancel", start: "2027-06-01", end: "2027-08-31", kind: "notice_window", ref: { type: "contract", id: "ctr_liability" }, markers: [m("2027-08-25", "Send by", "send_by"), m("2027-08-31", "Cancel by", "cancel_by")] }),
        ],
        markers: [],
      },
      {
        id: "lane_study",
        label: "Study",
        area: "study",
        bars: [
          bar({ id: "bar_ws", label: "Winter semester 2026/27", start: "2026-10-01", end: "2027-03-31", kind: "period", status: "ok", ref: { type: "document", id: "doc_uni" } }),
          bar({ id: "bar_ss", label: "Summer semester 2027", start: "2027-04-01", end: "2027-09-30", kind: "period", status: "ok", ref: { type: "document", id: "doc_uni" } }),
        ],
        markers: [m("2026-12-15", "Scholarship report", "deadline"), m("2027-01-15", "Semester fee €312.40", "payment")],
      },
      {
        id: "lane_work",
        label: "Work · Muster Tech",
        area: "work",
        bars: [bar({ id: "bar_job", label: "Werkstudent contract", start: "2025-04-01", end: "2027-03-31", kind: "contract", ref: { type: "contract", id: "ctr_job" }, markers: [m("2027-03-31", "Contract ends", "expiry")] })],
        markers: [],
      },
      {
        id: "lane_money",
        label: "Money",
        area: "money",
        bars: [],
        markers: [m("2026-09-30", "TechMarkt €94.99", "payment"), m("2026-11-30", "Bank fee decision", "deadline"), m("2026-12-01", "Liability €59.90", "payment")],
      },
    ];
    if (has("itm_tax_objection")) {
      lanes.splice(2, 0, {
        id: "lane_tax",
        label: "Tax",
        area: "tax",
        bars: [bar({ id: "bar_tax_objection", label: "Objection period (Einspruch)", start: "2026-09-21", end: "2026-10-21", kind: "notice_window", ref: { type: "document", id: "doc_tax" }, markers: [m("2026-10-15", "Send by", "send_by"), m("2026-10-21", "Deadline", "deadline")] })],
        markers: [],
      });
    }
    if (!from && !to) return lanes;
    const f = from ?? "0000-01-01";
    const t = to ?? "9999-12-31";
    return lanes
      .map((l) => ({
        ...l,
        bars: l.bars.filter((b) => b.end >= f && b.start <= t),
        markers: l.markers.filter((mk) => mk.date >= f && mk.date <= t),
      }))
      .filter((l) => l.bars.length || l.markers.length);
  }

  search(q: string): Document[] {
    const needle = q.trim().toLowerCase();
    if (!needle) return this.liveDocuments();
    const words = needle.split(/\s+/);
    const scored = this.liveDocuments()
      .map((d) => {
        const party = this.party(d.party_id)?.name ?? "";
        const text = [d.title, d.summary, d.filename, party, d.kind?.replace(/_/g, " "), ...d.key_facts.map((f) => `${f.label} ${f.value}`), letterFor(d.id)?.pageText(1) ?? ""]
          .join(" ")
          .toLowerCase();
        const title = (d.title ?? "").toLowerCase();
        let score = 0;
        for (const w of words) {
          if (!text.includes(w)) return { d, score: 0 };
          score += title.includes(w) ? 3 : party.toLowerCase().includes(w) ? 2 : 1;
        }
        return { d, score };
      })
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score);
    return scored.map((x) => x.d);
  }

  /** Items dated after the last calendar export (drives the "N new dates" Idea). */
  newDatesSinceExport(): Item[] {
    return this.openItems().filter((i) => i.due_date && i.created_at > this.state.lastCalendarExport);
  }
}

function prio(p: string): number {
  return { low: 0, normal: 1, high: 2, critical: 3 }[p as "low"] ?? 1;
}

export { daysFrom, iso as isoDate, nowTs };
