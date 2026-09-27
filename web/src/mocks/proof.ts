/**
 * Mock API for proof of sending, "Waiting for" and call notes: the same answers the server works out
 * (`src/ordnung/drafts/sent.py`, `secretary/waiting.py`, `secretary/calls.py`), from the in-memory
 * database. Proof files uploaded in the demo stay in the browser tab (an object URL), like any upload.
 */
import { addDays, format, parseISO } from "date-fns";
import type { CallNote, CallNoteCreate, Document, Draft, Proof, ProofEntry, ProofEvent, ProofKind, ProofOverview, TrackingInfo, WaitingEntry, WaitingStatus } from "@/api/types";
import { PROOF_KINDS } from "@/api/types";
import { checkTracking, displayTracking } from "@/lib/tracking";
import type { MockDb } from "./db";
import { CHANNEL_WORDS, MISSING, PROOF_CAVEAT, PROOF_TEXTS, WAITING_FOR, followupIdFor, receiptSvg, RECEIPT_DOC_ID } from "./data/proof";
import { doc as makeDoc } from "./data/helpers";
import { renderLetter, svgDataUrl } from "./pages";

/** The request as the mock server hands it to a handler (see `server.ts`). */
interface ProofCtx {
  db: MockDb;
  params: Record<string, string>;
  query: URLSearchParams;
  body: unknown;
}

/** How a handler answers: a value (200), `created` (201), `empty` (204), or `fail` (an error). */
export interface ProofReplies {
  fail: (status: number, message: string) => never;
  created: (body: unknown) => unknown;
  empty: () => unknown;
}

const nowTs = () => new Date().toISOString().replace(/\.\d+Z$/, "Z");
let seq = 0;
const newId = (prefix: string) => `${prefix}_${Date.now().toString(36)}${(++seq).toString(36).padStart(3, "0")}`;
const day = (value: string | null | undefined) => (value ? value.slice(0, 10) : null);
const words = (iso: string) => format(parseISO(iso), "EEE d MMM");

/** A photo the person added, shown from this tab's memory (no URL where the environment can't make one). */
function objectUrl(file: File): string | undefined {
  if (!file.type.startsWith("image/")) return undefined;
  try {
    return URL.createObjectURL(file);
  } catch {
    return undefined;
  }
}

// ------------------------------------------------------------------------------------------------
// reading
// ------------------------------------------------------------------------------------------------

function trackingInfo(number: string | null): TrackingInfo | null {
  if (!number) return null;
  const read = checkTracking(number);
  if (read.state !== "valid") return { number, display: number, format: "domestic", checked: false, note: read.state === "invalid" ? read.message : null };
  return { number: read.number, display: displayTracking(read.number), format: read.checked ? "s10" : "domestic", checked: read.checked, note: read.note };
}

function liveProofs(db: MockDb, draftId: string): Proof[] {
  return db.state.proofs.filter((p) => p.draft_id === draftId && (!p.doc_id || db.document(p.doc_id)));
}

/** The letter that answered a sent one: incoming, in its thread, dated on or after the sending day. */
function replyTo(db: MockDb, d: Draft): Document | null {
  const sent = day(d.sent_at);
  if (d.status !== "sent" || !sent || !d.case_id) return null;
  const found = db
    .liveDocuments()
    .filter((x) => x.direction === "incoming" && x.id !== d.doc_id && x.case_id === d.case_id && (x.doc_date ?? x.received_date ?? x.created_at.slice(0, 10)) >= sent)
    .sort((a, b) => ((a.doc_date ?? a.created_at) < (b.doc_date ?? b.created_at) ? -1 : 1));
  return found[0] ?? null;
}

function missing(d: Draft, kinds: string[], answered: boolean): string[] {
  if (d.status !== "sent") return [];
  const arrived = answered || kinds.some((k) => PROOF_TEXTS[k as ProofKind]?.arrival);
  const out: string[] = [];
  switch (d.sent_channel) {
    case "registered_letter":
      if (!d.tracking_number) out.push(MISSING.tracking);
      if (!kinds.includes("posting_receipt")) out.push(MISSING.posting);
      if (!arrived) out.push(MISSING.delivery);
      break;
    case "fax":
      if (!kinds.includes("fax_report") && !answered) out.push(MISSING.fax);
      break;
    case "email":
      if (!kinds.includes("sent_email")) out.push(MISSING.email);
      break;
    case "online_button":
      if (!kinds.includes("cancel_confirmation")) out.push(MISSING.button);
      break;
    case "letter":
    case "in_person":
    case "portal":
      if (!kinds.length && !answered) out.push(MISSING[d.sent_channel]);
      break;
  }
  return out;
}

function timeline(db: MockDb, d: Draft, tracking: TrackingInfo | null, proofs: Proof[], reply: Document | null): ProofEvent[] {
  const sent = day(d.sent_at);
  const created = d.created_at.slice(0, 10);
  const events: (ProofEvent & { order: number })[] = [];
  if (!sent || created <= sent) events.push({ date: created, kind: "created", label: "Letter drafted", detail: null, ref: null, order: 0 });
  if (sent && d.status === "sent") {
    events.push({ date: sent, kind: "sent", label: `Sent by ${CHANNEL_WORDS[d.sent_channel ?? ""] ?? "post"}`, detail: null, ref: null, order: 1 });
    if (tracking) events.push({ date: sent, kind: "tracking", label: `Tracking number ${tracking.display}`, detail: tracking.checked ? "check digit correct" : "not checked", ref: null, order: 2 });
  }
  for (const p of proofs) {
    const text = PROOF_TEXTS[p.kind];
    const delivered = text.arrival && p.kind !== "cancel_confirmation" && Boolean(p.on_date);
    events.push({
      date: p.on_date ?? p.created_at.slice(0, 10),
      kind: delivered ? "delivered" : "proof",
      label: delivered ? `Delivered — ${text.label.toLowerCase()}` : text.label,
      detail: p.note,
      ref: p.doc_id ? { type: "document", id: p.doc_id } : null,
      order: delivered ? 4 : 3,
    });
  }
  if (reply) {
    events.push({ date: reply.doc_date ?? reply.created_at.slice(0, 10), kind: "answered", label: `Answer received: “${reply.title ?? reply.filename}”`, detail: null, ref: { type: "document", id: reply.id }, order: 5 });
  }
  void db;
  return events.sort((a, b) => (a.date === b.date ? a.order - b.order : a.date < b.date ? -1 : 1)).map(({ order: _order, ...e }) => e);
}

function status(expected: string | null, today: string, answered: boolean, closed: boolean): WaitingStatus {
  if (closed) return "closed";
  if (answered) return "answered";
  return expected && expected < today ? "overdue" : "waiting";
}

function letterEntry(db: MockDb, d: Draft): WaitingEntry | null {
  const title = WAITING_FOR[d.kind] ?? null;
  if (d.status !== "sent" || !title) return null;
  const followup = db.state.items.find((i) => i.id === followupIdFor(d.id)) ?? null;
  const reply = replyTo(db, d);
  const st = status(followup?.due_date ?? null, db.today, Boolean(reply), !followup || followup.status === "done" || followup.status === "dismissed");
  const sent = day(d.sent_at);
  const how = d.sent_channel ? ` by ${CHANNEL_WORDS[d.sent_channel] ?? d.sent_channel}` : "";
  const sentWords = sent ? `Sent ${words(sent)}${how}` : `Sent${how}`;
  const tracking = trackingInfo(d.tracking_number);
  const delivered = liveProofs(db, d.id)
    .filter((p) => PROOF_TEXTS[p.kind].arrival && p.on_date)
    .map((p) => p.on_date!)
    .sort()[0];
  const extra = `${delivered ? ` Your proof shows it was delivered on ${words(delivered)}.` : ""}${tracking ? ` Tracking number ${tracking.display}.` : ""}`;
  const note =
    st === "answered" && reply
      ? `Their letter “${reply.title ?? reply.filename}”${reply.doc_date ? ` of ${words(reply.doc_date)}` : ""} is in the same thread. Check that it answers yours, then close this.`
      : st === "closed"
        ? `${sentWords}. You closed the follow-up.`
        : st === "overdue"
          ? `${sentWords}; nothing linked to it has arrived since.${extra} Send a short reminder or call them — and note what they say.`
          : `${sentWords}.${extra}${followup?.due_date ? ` Ordnung reminds you on ${words(followup.due_date)} if nothing has come.` : ""}`;
  const contract = db.state.contracts.find((c) => c.id === d.contract_id);
  return {
    id: `draft:${d.id}`,
    source: "letter",
    status: st,
    title,
    about: d.subject || "Your letter",
    note,
    since: sent,
    expected_by: followup?.due_date ?? null,
    party_id: d.party_id,
    party_name: db.party(d.party_id)?.name ?? null,
    amount: null,
    currency: null,
    area: contract?.area ?? db.document(d.doc_id ?? "")?.area ?? "other",
    ref: { type: "draft", id: d.id },
    answered_by: reply ? { type: "document", id: reply.id } : null,
    answered_on: reply ? (reply.doc_date ?? reply.created_at.slice(0, 10)) : null,
    followup_item_id: followup?.id ?? null,
    doc_id: d.doc_id && db.document(d.doc_id) ? d.doc_id : null,
  };
}

function moneyEntries(db: MockDb): WaitingEntry[] {
  const today = db.today;
  return db
    .openItems()
    .filter((i) => i.kind === "payment" && i.direction === "in" && !i.recurrence)
    .map((i): WaitingEntry => {
      const d = i.doc_id ? db.document(i.doc_id) : null;
      const st = status(i.due_date, today, false, false);
      const who = db.party(i.party_id)?.name ?? null;
      const sum = i.amount != null ? `€${i.amount.toFixed(2)}` : "The money";
      const source = d ? `Promised in “${d.title ?? d.filename}”${d.doc_date ? ` of ${words(d.doc_date)}` : ""}` : "You noted this";
      const note =
        st === "overdue"
          ? `${source}; it was due on ${words(i.due_date!)}. If it hasn't arrived, ask ${who ?? "them"} about it.`
          : `${source}: ${sum}${i.due_date ? ` by ${words(i.due_date)}` : ""}. Ordnung can't see your bank account — mark it received when it arrives.`;
      return {
        id: `item:${i.id}`,
        source: "money",
        status: st,
        title: i.title,
        about: d ? (d.title ?? d.filename) : "Added by you",
        note,
        since: d?.doc_date ?? i.created_at.slice(0, 10),
        expected_by: i.due_date,
        party_id: i.party_id,
        party_name: who,
        amount: i.amount,
        currency: i.currency,
        area: i.area,
        ref: { type: "item", id: i.id },
        answered_by: null,
        answered_on: null,
        followup_item_id: i.id,
        doc_id: d?.id ?? null,
      };
    });
}

function callEntry(db: MockDb, c: CallNote): WaitingEntry | null {
  if (!c.promise || !c.promise_due) return null;
  const answer = c.case_id
    ? db.liveDocuments().find((x) => x.direction === "incoming" && x.case_id === c.case_id && (x.doc_date ?? x.created_at.slice(0, 10)) >= c.called_on) ?? null
    : null;
  const st = status(c.promise_due, db.today, Boolean(answer), Boolean(c.promise_kept_on));
  const who = c.contact || db.party(c.party_id)?.name || "They";
  const said = `${who} promised this on the phone on ${words(c.called_on)}, by ${words(c.promise_due)}.`;
  const note =
    st === "answered" && answer
      ? `Their letter “${answer.title ?? answer.filename}” arrived after the call — check whether it keeps the promise.`
      : st === "overdue"
        ? `${said} Call them again and note what they say.`
        : st === "closed"
          ? `Kept on ${words(c.promise_kept_on!)}.`
          : said;
  return {
    id: `call:${c.id}`,
    source: "call",
    status: st,
    title: c.promise,
    about: c.contact ? `Call with ${c.contact}` : "Phone call",
    note,
    since: c.called_on,
    expected_by: c.promise_due,
    party_id: c.party_id,
    party_name: db.party(c.party_id)?.name ?? null,
    amount: c.promise_amount,
    currency: null,
    area: "other",
    ref: { type: "call", id: c.id },
    answered_by: answer ? { type: "document", id: answer.id } : null,
    answered_on: answer ? (answer.doc_date ?? answer.created_at.slice(0, 10)) : null,
    followup_item_id: null,
    doc_id: null,
  };
}

const ORDER: Record<WaitingStatus, number> = { overdue: 0, waiting: 1, answered: 2, closed: 3 };

/** `GET /api/waiting`: overdue first, then by expected day (undated last), then answered. */
export function waitingFor(db: MockDb): WaitingEntry[] {
  const entries = [
    ...db.state.drafts.map((d) => letterEntry(db, d)),
    ...moneyEntries(db),
    ...db.state.calls.map((c) => callEntry(db, c)),
  ].filter((e): e is WaitingEntry => e !== null && e.status !== "closed");
  return entries.sort((a, b) => ORDER[a.status] - ORDER[b.status] || (a.expected_by ?? "9999") .localeCompare(b.expected_by ?? "9999") || a.id.localeCompare(b.id));
}

/** `GET /api/drafts/{id}/proof`. */
export function proofOverview(db: MockDb, d: Draft): ProofOverview {
  const proofs = liveProofs(db, d.id);
  const tracking = trackingInfo(d.tracking_number);
  const reply = replyTo(db, d);
  const entries: ProofEntry[] = proofs.map((p) => ({
    proof: p,
    document: p.doc_id ? db.document(p.doc_id) : null,
    label: PROOF_TEXTS[p.kind].label,
    shows: PROOF_TEXTS[p.kind].shows,
    does_not_show: PROOF_TEXTS[p.kind].doesNotShow,
  }));
  return {
    draft_id: d.id,
    sent: d.status === "sent",
    channel: d.sent_channel,
    tracking,
    proofs: entries,
    timeline: timeline(db, d, tracking, proofs, reply),
    missing: missing(
      d,
      proofs.map((p) => p.kind),
      Boolean(reply),
    ),
    waiting: letterEntry(db, d),
    caveat: PROOF_CAVEAT,
  };
}

// ------------------------------------------------------------------------------------------------
// files the pages show
// ------------------------------------------------------------------------------------------------

/** The picture of a seeded proof file, or the Nachweis page of a sent letter (`null`: not ours). */
export function resolveProofAsset(db: MockDb, path: string): string | null {
  if (/^\/documents\/doc_gym_receipt\/(?:pages\/1\.jpg|thumbnail\.jpg|file)$/.test(path)) {
    const p = db.state.proofs.find((x) => x.doc_id === RECEIPT_DOC_ID);
    const d = db.state.drafts.find((x) => x.id === "drf_gym");
    return svgDataUrl(receiptSvg(trackingInfo(d?.tracking_number ?? null)?.display ?? "RT 123 456 785 DE", p?.on_date ? format(parseISO(p.on_date), "dd.MM.yyyy") : "22.09.2026", p?.note ?? null));
  }
  const m = /^\/drafts\/([^/]+)\/proof\.pdf$/.exec(path);
  if (!m) return null;
  const d = db.state.drafts.find((x) => x.id === decodeURIComponent(m[1]!));
  if (!d) return null;
  const overview = proofOverview(db, d);
  const r = renderLetter({
    brand: { name: "Versandnachweis", color: "#1f1d1a", mark: "none", tagline: "Proof of sending — a summary of what the sender recorded" },
    senderLine: d.sender_block.split("\n").slice(0, 3).join(" · "),
    recipient: d.recipient_block.split("\n"),
    info: [["Sendungsnummer", overview.tracking?.display ?? "—"]],
    pages: [
      {
        subject: d.subject,
        blocks: [
          ...overview.timeline.map((e) => `${format(parseISO(e.date), "dd.MM.yyyy")} — ${e.label}${e.detail ? ` (${e.detail})` : ""}`),
          "In the installed app this PDF also holds the letter as sent and every proof file.",
          PROOF_CAVEAT,
        ],
      },
    ],
  });
  return svgDataUrl(r.pages[0]!);
}

// ------------------------------------------------------------------------------------------------
// routes
// ------------------------------------------------------------------------------------------------

type Route = [string, string, (ctx: ProofCtx) => unknown];

/** The mock routes of this feature (`server.ts` adds them to its own). */
export function proofRoutes({ fail, created, empty }: ProofReplies): Route[] {
  const sentDraft = (db: MockDb, id: string): Draft => {
    const d = db.state.drafts.find((x) => x.id === id) ?? fail(404, "Unknown letter.");
    if (d.status !== "sent") fail(422, "Mark the letter as sent first — proof belongs to a letter that went out.");
    return d;
  };
  const checkedDay = (db: MockDb, value: unknown): string | null => {
    if (value == null || value === "") return null;
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return fail(422, `“${String(value)}” is not a date; use the form YYYY-MM-DD.`);
    if (value > db.today) fail(422, "The day a proof shows can't be in the future.");
    return value;
  };
  const touched = (db: MockDb, d: Draft) => {
    d.updated_at = nowTs();
    return proofOverview(db, d);
  };

  return [
    [
      "GET",
      "/drafts/:id/proof",
      ({ db, params }) => proofOverview(db, db.state.drafts.find((x) => x.id === params.id) ?? fail(404, "Unknown letter.")),
    ],
    [
      "PUT",
      "/drafts/:id/tracking",
      ({ db, params, body }) => {
        const d = sentDraft(db, params.id!);
        const text = (body as { tracking_number?: string | null } | null)?.tracking_number ?? null;
        const read = checkTracking(text ?? "");
        if (read.state === "invalid") fail(422, read.message);
        d.tracking_number = read.state === "valid" ? read.number : null;
        db.log("draft.tracking", `Tracking number ${d.tracking_number ? "saved" : "removed"} for “${d.subject}”`, "draft", d.id);
        return touched(db, d);
      },
    ],
    [
      "POST",
      "/drafts/:id/proofs",
      ({ db, params, body }) => {
        const d = sentDraft(db, params.id!);
        const form = body instanceof FormData ? body : null;
        const file = form?.get("file");
        const kind = String(form?.get("kind") ?? "");
        if (!(file instanceof File)) return fail(422, "Choose the file to add as proof.");
        if (!(PROOF_KINDS as readonly string[]).includes(kind)) fail(422, "Choose what the proof is (posting receipt, delivery record …).");
        const onDate = checkedDay(db, form?.get("on_date"));
        const note = String(form?.get("note") ?? "").trim() || null;
        if (note && note.length > 500) fail(422, "Keep the note under 500 characters.");
        const id = newId("doc");
        db.state.uploads[id] = { name: file.name, objectUrl: objectUrl(file) };
        const now = nowTs();
        db.upsertDocument(
          makeDoc({
            id,
            filename: file.name,
            title: file.name,
            mime: file.type || "application/octet-stream",
            direction: "outgoing",
            source: "proof",
            kind: null,
            area: null,
            ai_private: true,
            ai_processed_at: null,
            urgency: null,
            language: null,
            created_at: now,
            updated_at: now,
          }),
        );
        db.state.proofs.push({ id: newId("prf"), draft_id: d.id, kind: kind as ProofKind, doc_id: id, on_date: onDate, note, created_at: now, updated_at: now });
        db.log("draft.proof", `Added proof to “${d.subject}”: ${PROOF_TEXTS[kind as ProofKind].label} · kept private, not sent to AI`, "draft", d.id);
        return created(touched(db, d));
      },
    ],
    [
      "PATCH",
      "/drafts/:id/proofs/:proof",
      ({ db, params, body }) => {
        const d = db.state.drafts.find((x) => x.id === params.id) ?? fail(404, "Unknown letter.");
        const p = db.state.proofs.find((x) => x.id === params.proof && x.draft_id === d.id) ?? fail(404, "This record doesn't exist (any more).");
        const patch = (body ?? {}) as { kind?: string; on_date?: string | null; note?: string | null };
        if (patch.kind !== undefined) {
          if (!(PROOF_KINDS as readonly string[]).includes(patch.kind)) fail(422, "Choose what the proof is (posting receipt, delivery record …).");
          p.kind = patch.kind as ProofKind;
        }
        if ("on_date" in patch) p.on_date = checkedDay(db, patch.on_date);
        if (patch.note !== undefined) p.note = patch.note?.trim() || null;
        p.updated_at = nowTs();
        return touched(db, d);
      },
    ],
    [
      "DELETE",
      "/drafts/:id/proofs/:proof",
      ({ db, params }) => {
        const d = db.state.drafts.find((x) => x.id === params.id) ?? fail(404, "Unknown letter.");
        const p = db.state.proofs.find((x) => x.id === params.proof && x.draft_id === d.id) ?? fail(404, "This record doesn't exist (any more).");
        db.state.proofs = db.state.proofs.filter((x) => x.id !== p.id);
        if (p.doc_id && !db.state.proofs.some((x) => x.doc_id === p.doc_id)) db.state.documents = db.state.documents.filter((x) => x.id !== p.doc_id);
        db.log("draft.proof_removed", "Removed a proof and its file", "draft", d.id);
        return touched(db, d);
      },
    ],
    ["GET", "/waiting", ({ db }) => waitingFor(db)],
    [
      "GET",
      "/calls",
      ({ db, query }) =>
        db.state.calls
          .filter((c) => (!query.get("party_id") || c.party_id === query.get("party_id")) && (!query.get("case_id") || c.case_id === query.get("case_id")))
          .sort((a, b) => (a.called_on === b.called_on ? (a.created_at < b.created_at ? 1 : -1) : a.called_on < b.called_on ? 1 : -1)),
    ],
    [
      "POST",
      "/calls",
      ({ db, body }) => {
        const b = (body ?? {}) as CallNoteCreate;
        const partyId = b.party_id ?? (b.case_id ? (db.state.cases.find((c) => c.id === b.case_id)?.party_id ?? null) : null);
        if (!partyId && !b.case_id) fail(422, "Choose who you spoke to.");
        if (partyId && !db.party(partyId)) fail(422, "That person or organisation isn't in Ordnung any more.");
        if (!b.called_on || !/^\d{4}-\d{2}-\d{2}$/.test(b.called_on)) fail(422, "When was the call? Use the form YYYY-MM-DD.");
        if (b.called_on > db.today) fail(422, "The call can't be in the future.");
        const summary = (b.summary ?? "").trim();
        if (!summary) fail(422, "Write down what was said.");
        const promise = b.promise?.replace(/\s+/g, " ").trim() || null;
        if ((b.promise_due || b.promise_amount != null) && !promise) fail(422, "Say what they promised, too.");
        if (b.promise_due && b.promise_due < b.called_on) fail(422, "The promised day is before the call.");
        const now = nowTs();
        const note: CallNote = {
          id: newId("cal"),
          party_id: partyId,
          case_id: b.case_id ?? null,
          called_on: b.called_on,
          contact: b.contact?.replace(/\s+/g, " ").trim() || null,
          summary,
          promise,
          promise_due: b.promise_due ?? null,
          promise_amount: b.promise_amount ?? null,
          promise_kept_on: null,
          created_at: now,
          updated_at: now,
        };
        db.state.calls.push(note);
        db.log("call.noted", `Noted a call on ${note.called_on}${note.contact ? ` with ${note.contact}` : ""}`, "party", note.party_id);
        return created(note);
      },
    ],
    [
      "PATCH",
      "/calls/:id",
      ({ db, params, body }) => {
        const c = db.state.calls.find((x) => x.id === params.id) ?? fail(404, "This call note doesn't exist (any more).");
        if (!c.promise) fail(422, "This call has no promise to keep.");
        const kept = Boolean((body as { kept?: boolean } | null)?.kept);
        c.promise_kept_on = kept ? db.today : null;
        c.updated_at = nowTs();
        return c;
      },
    ],
    [
      "DELETE",
      "/calls/:id",
      ({ db, params }) => {
        if (!db.state.calls.some((x) => x.id === params.id)) fail(404, "This call note doesn't exist (any more).");
        db.state.calls = db.state.calls.filter((x) => x.id !== params.id);
        return empty();
      },
    ],
  ];
}

/** When a letter is marked sent in the demo: its follow-up to-do's id and due day, and the checked number. */
export function sentFollowup(d: Draft, date: string): { id: string; due: string } {
  return { id: followupIdFor(d.id), due: format(addDays(parseISO(date), d.kind === "data_access" ? 35 : 21), "yyyy-MM-dd") };
}
