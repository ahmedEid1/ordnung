/**
 * Mock API for proof of sending, "Waiting for" and call notes: the same answers the server works out
 * (`src/ordnung/drafts/sent.py`, `secretary/waiting.py`, `secretary/calls.py`), from the in-memory
 * database. Proof files uploaded in the demo stay in the browser tab (an object URL), like any upload.
 */
import { addDays, addMonths, format, parseISO } from "date-fns";
import type { CallNote, CallNoteCreate, Document, Draft, Proof, ProofEntry, ProofEvent, ProofKind, ProofOverview, TrackingInfo, WaitingEntry, WaitingStatus } from "@/api/types";
import { PROOF_KINDS } from "@/api/types";
import { checkTracking, displayTracking } from "@/lib/tracking";
import type { MockDb } from "./db";
import {
  CHANNEL_WORDS,
  DELIVERY_DAY_KINDS,
  MISSING,
  NOT_FROM_AN_AUTHORITY,
  PROOF_CAVEAT,
  PROOF_TEXTS,
  SENDING_DAY_KINDS,
  WAITING_CONTEXT,
  WAITING_FOR,
  followupIdFor,
  receiptSvg,
  RECEIPT_DOC_ID,
} from "./data/proof";
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

/** A timestamp on the demo's day (the real demo stamps its pinned day, `clock.now_iso`), so an undated proof is
 * never "added" after the demo's today. */
const nowTs = (db: MockDb) => `${db.today}T${new Date().toISOString().slice(11, 19)}Z`;
let seq = 0;
const newId = (prefix: string) => `${prefix}_${Date.now().toString(36)}${(++seq).toString(36).padStart(3, "0")}`;
const day = (value: string | null | undefined) => (value ? value.slice(0, 10) : null);
const words = (iso: string) => format(parseISO(iso), "EEE d MMM");
const longWords = (iso: string) => format(parseISO(iso), "EEE d MMM yyyy");
/** The server groups a number with no-break spaces, so it never breaks inside (drafts/tracking.py). */
const grouped = (number: string) => displayTracking(number).replace(/ /g, "\u00a0");
const letterDay = (x: Document) => x.doc_date ?? x.received_date ?? x.created_at.slice(0, 10);

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
  if (read.state !== "valid") return { number, display: number, format: "unknown", checked: false, note: read.state === "invalid" ? read.message : null };
  return { number: read.number, display: grouped(read.number), format: read.format, checked: read.checked, note: read.note };
}

function liveProofs(db: MockDb, draftId: string): Proof[] {
  return db.state.proofs.filter((p) => p.draft_id === draftId && (!p.doc_id || db.document(p.doc_id)));
}

const after = (d: Draft) => (x: Document) => x.direction === "incoming" && x.id !== d.doc_id && letterDay(x) >= (day(d.sent_at) ?? "9999");
const earliest = (docs: Document[]) => [...docs].sort((a, b) => (letterDay(a) < letterDay(b) ? -1 : 1))[0] ?? null;

/** A letter that *may* answer a sent one: incoming, in its thread (or confirming the cancellation), on or after the sending day. */
function replyTo(db: MockDb, d: Draft): Document | null {
  if (d.status !== "sent" || !d.sent_at) return null;
  return earliest(db.liveDocuments().filter((x) => after(d)(x) && ((d.case_id && x.case_id === d.case_id) || isConfirmation(d, x))));
}

function isConfirmation(d: Draft, x: Document): boolean {
  return d.kind === "cancellation" && x.kind === "cancellation_confirmation" && Boolean(d.party_id) && x.party_id === d.party_id;
}

/** The confirmed answer (drafts/proof.py policy 3): the person's word, else a confirmation of the cancellation. */
function answerOf(db: MockDb, d: Draft): { day: string; doc: Document | null; how: "letter" | "noted" | "confirmation" } | null {
  if (d.status !== "sent") return null;
  if (d.answered_on) {
    const named = d.answer_doc_id ? db.document(d.answer_doc_id) : null;
    return named ? { day: letterDay(named), doc: named, how: "letter" } : { day: d.answered_on.slice(0, 10), doc: null, how: "noted" };
  }
  const confirmation = earliest(db.liveDocuments().filter((x) => after(d)(x) && isConfirmation(d, x)));
  return confirmation ? { day: letterDay(confirmation), doc: confirmation, how: "confirmation" } : null;
}

/** What would make the proof stronger (drafts/proof.py `missing`): the person's word that it was answered ("noted")
 * closes the wait but shows nothing about arrival. */
function missing(d: Draft, kinds: string[], answer: { how: "letter" | "noted" | "confirmation" } | null, today: string): string[] {
  if (d.status !== "sent") return [];
  const answered = Boolean(answer);
  const arrived = (answer !== null && answer.how !== "noted") || kinds.some((k) => PROOF_TEXTS[k as ProofKind]?.arrival);
  const sent = day(d.sent_at);
  const obtainable = !sent || today <= format(addMonths(parseISO(sent), 15), "yyyy-MM-dd");
  const out: string[] = [];
  switch (d.sent_channel) {
    case "registered_letter": {
      const tracking = trackingInfo(d.tracking_number);
      const online = tracking?.format === "online_stamp";
      if (!tracking) out.push(MISSING.tracking);
      if (online && !kinds.includes("posting_receipt") && !kinds.includes("other")) out.push(MISSING.onlineStamp);
      else if (!online && !kinds.includes("posting_receipt")) out.push(MISSING.posting);
      if (!arrived && obtainable) out.push(MISSING.delivery);
      else if (!arrived && !answered) out.push(MISSING.deliveryLate);
      break;
    }
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

/** The conflicts between proof days and the sending day (drafts/proof.py `conflicts`). */
function conflicts(d: Draft, proofs: Proof[]): string[] {
  const sent = day(d.sent_at);
  if (d.status !== "sent" || !sent) return [];
  return proofs.flatMap((p) => {
    const label = PROOF_TEXTS[p.kind].label.toLowerCase();
    if (p.on_date && SENDING_DAY_KINDS.includes(p.kind) && p.on_date !== sent)
      return [`Your ${label} says ${longWords(p.on_date)}, but the letter is marked as sent on ${longWords(sent)} — correct one of them, so your records agree.`];
    if (p.on_date && DELIVERY_DAY_KINDS.includes(p.kind) && p.on_date < sent)
      return [`Your ${label} says it was delivered on ${longWords(p.on_date)}, before the day the letter is marked as sent (${longWords(sent)}) — correct one of them, so your records agree.`];
    return [];
  });
}

/** Why a sent letter can't be marked as sent on `date`: a delivery its proof records before it (drafts/compose.py). */
export function deliveredBefore(db: MockDb, d: Draft, date: string): string | null {
  if (d.status !== "sent") return null;
  const early = db.state.proofs.find((p) => p.draft_id === d.id && DELIVERY_DAY_KINDS.includes(p.kind) && p.on_date && p.on_date < date);
  if (!early) return null;
  const label = PROOF_TEXTS[early.kind].label.toLowerCase();
  return `Your ${label} says it was delivered on ${longWords(early.on_date!)} — a letter can't be sent after it was delivered. Correct the ${label}'s day first, or choose an earlier day.`;
}

type Ordered = ProofEvent & { order: number };
const event = (e: Omit<ProofEvent, "detail" | "ref" | "added_on"> & Partial<ProofEvent> & { order: number }): Ordered => ({ detail: null, ref: null, added_on: null, ...e });

function timeline(db: MockDb, d: Draft, tracking: TrackingInfo | null, proofs: Proof[]): ProofEvent[] {
  const sent = day(d.sent_at);
  const created = d.created_at.slice(0, 10);
  const events: Ordered[] = [];
  const undated: Ordered[] = [];
  if (!sent || created <= sent) events.push(event({ date: created, kind: "created", label: "Letter drafted", order: 0 }));
  if (sent && d.status === "sent") {
    events.push(event({ date: sent, kind: "sent", label: `Sent by ${CHANNEL_WORDS[d.sent_channel ?? ""] ?? "post"}`, order: 1 }));
    if (tracking) events.push(event({ date: sent, kind: "tracking", label: `Tracking number ${tracking.display}`, detail: tracking.checked ? "check digit correct" : "not checked", order: 2 }));
  }
  for (const p of proofs) {
    const text = PROOF_TEXTS[p.kind];
    const ref = p.doc_id ? { type: "document", id: p.doc_id } : null;
    if (!p.on_date) {
      undated.push(event({ date: null, kind: "proof", label: text.label, detail: p.note, ref, added_on: p.created_at.slice(0, 10), order: 3 }));
      continue;
    }
    const delivered = text.arrival && p.kind !== "cancel_confirmation";
    events.push(event({ date: p.on_date, kind: delivered ? "delivered" : "proof", label: delivered ? `Delivered — ${text.label.toLowerCase()}` : text.label, detail: p.note, ref, order: delivered ? 4 : 3 }));
  }
  const answer = answerOf(db, d);
  const possible = replyTo(db, d);
  if (answer) {
    const title = answer.doc ? `“${answer.doc.title ?? answer.doc.filename}”` : "";
    const label = answer.how === "noted" ? "You marked it as answered" : answer.how === "confirmation" ? `Cancellation confirmed: ${title}` : `Answer received: ${title}`;
    events.push(event({ date: answer.day, kind: "answered", label, ref: answer.doc ? { type: "document", id: answer.doc.id } : null, order: 5 }));
  } else if (possible) {
    events.push(
      event({
        date: letterDay(possible),
        kind: "possible_answer",
        label: `Their letter “${possible.title ?? possible.filename}” arrived — is it the answer?`,
        detail: "Not confirmed as the answer: open it, and if it answers yours, say so.",
        ref: { type: "document", id: possible.id },
        order: 6,
      }),
    );
  }
  const strip = ({ order: _order, ...e }: Ordered): ProofEvent => e;
  const dated = events.sort((a, b) => (a.date === b.date ? a.order - b.order : a.date! < b.date! ? -1 : 1));
  return [...dated, ...undated.sort((a, b) => ((a.added_on ?? "") < (b.added_on ?? "") ? -1 : 1))].map(strip);
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
  const closed = !followup || followup.status === "done" || followup.status === "dismissed" || Boolean(d.answered_on);
  const st = status(followup?.due_date ?? null, db.today, Boolean(reply), closed);
  const sent = day(d.sent_at);
  const how = d.sent_channel ? ` by ${CHANNEL_WORDS[d.sent_channel] ?? d.sent_channel}` : "";
  const sentWords = sent ? `Sent ${words(sent)}${how}` : `Sent${how}`;
  const tracking = trackingInfo(d.tracking_number);
  const delivered = liveProofs(db, d.id)
    .filter((p) => PROOF_TEXTS[p.kind].arrival && p.on_date)
    .map((p) => p.on_date!)
    .sort()[0];
  const answers = d.doc_id ? db.document(d.doc_id) : null;
  const why = d.kind === "objection" && answers?.kind && NOT_FROM_AN_AUTHORITY.includes(answers.kind) ? null : WAITING_CONTEXT[d.kind];
  const context = why ? ` ${why}` : "";
  const extra = `${delivered ? ` Your proof shows it was delivered on ${words(delivered)}.` : ""}${tracking ? ` Tracking number ${tracking.display}.` : ""}${context}`;
  const link = reply && isConfirmation(d, reply) ? "confirms the cancellation" : "is in the same thread";
  const note =
    st === "answered" && reply
      ? `Their letter “${reply.title ?? reply.filename}”${reply.doc_date ? ` of ${words(reply.doc_date)}` : ""} ${link}. Check that it answers yours, then close this.`
      : st === "closed"
        ? d.answered_on
          ? `${sentWords}. You marked it as answered on ${words(d.answered_on)}.`
          : `${sentWords}. You closed the follow-up.`
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
    case_id: d.case_id,
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
        case_id: null,
      };
    });
}

function callEntry(db: MockDb, c: CallNote): WaitingEntry | null {
  if (!c.promise || !c.promise_due) return null;
  const answer = c.case_id
    ? db.liveDocuments().find((x) => x.direction === "incoming" && x.case_id === c.case_id && (x.doc_date ?? x.created_at.slice(0, 10)) >= c.called_on) ?? null
    : null;
  const st = status(c.promise_due, db.today, Boolean(answer), Boolean(c.promise_kept_on));
  // who it was is the entry's "about": the sentence doesn't repeat it (secretary/waiting.py)
  const said = `On the phone on ${words(c.called_on)}, they promised this by ${words(c.promise_due)}.`;
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
    case_id: c.case_id,
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
    timeline: timeline(db, d, tracking, proofs),
    missing: missing(
      d,
      proofs.map((p) => p.kind),
      answerOf(db, d),
      db.today,
    ),
    conflicts: conflicts(d, proofs),
    waiting: letterEntry(db, d),
    caveat: PROOF_CAVEAT,
    notice: null,
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
    return svgDataUrl(receiptSvg(d?.tracking_number ? displayTracking(d.tracking_number) : "RT 123 456 785 DE", p?.on_date ? format(parseISO(p.on_date), "dd.MM.yyyy") : "22.09.2026", p?.note ?? null));
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
    info: [["Sendungsnummer", overview.tracking ? displayTracking(overview.tracking.number) : "—"]],
    pages: [
      {
        subject: d.subject,
        blocks: [
          // like the Nachweis: a possible answer is left out, proofs without a day are listed apart
          ...overview.timeline
            .filter((e) => e.kind !== "possible_answer")
            .map((e) =>
              e.date
                ? `${format(parseISO(e.date), "dd.MM.yyyy")} — ${e.label}${e.detail ? ` (${e.detail})` : ""}`
                : `ohne Datum — ${e.label}, no day given (added on ${format(parseISO(e.added_on ?? db.today), "dd.MM.yyyy")})`,
            ),
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
  const checkedDay = (db: MockDb, value: unknown, kind?: ProofKind, d?: Draft): string | null => {
    if (value == null || value === "") return null;
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return fail(422, `“${String(value)}” is not a date; use the form YYYY-MM-DD.`);
    if (value > db.today) fail(422, "The day a proof shows can't be in the future.");
    const sent = d ? day(d.sent_at) : null;
    if (kind && DELIVERY_DAY_KINDS.includes(kind) && sent && value < sent)
      fail(422, `A delivery can't be before the letter was sent (${format(parseISO(sent), "d MMMM yyyy")}) — check the day, or the day you marked the letter as sent.`);
    return value;
  };
  const touched = (db: MockDb, d: Draft) => {
    d.updated_at = nowTs(db);
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
        if (read.state === "valid" && d.sent_channel !== "registered_letter") fail(422, "Only a registered letter (Einschreiben) has a tracking number.");
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
        const onDate = checkedDay(db, form?.get("on_date"), kind as ProofKind, d);
        const note = String(form?.get("note") ?? "").trim() || null;
        if (note && note.length > 500) fail(422, "Keep the note under 500 characters.");
        const id = newId("doc");
        db.state.uploads[id] = { name: file.name, objectUrl: objectUrl(file) };
        const now = nowTs(db);
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
        if ("on_date" in patch) p.on_date = checkedDay(db, patch.on_date, p.kind, d);
        else if (p.on_date) checkedDay(db, p.on_date, p.kind, d);
        if (patch.note !== undefined) p.note = patch.note?.trim() || null;
        p.updated_at = nowTs(db);
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
    [
      "POST",
      "/drafts/:id/answered",
      ({ db, params, body }) => {
        const d = sentDraft(db, params.id!);
        const docId = (body as { doc_id?: string | null } | null)?.doc_id ?? null;
        if (docId && !db.liveDocuments().some((x) => x.id === docId && x.direction === "incoming")) fail(422, "That letter isn't in Ordnung any more — close this without naming it.");
        d.answered_on = db.today;
        d.answer_doc_id = docId;
        const followup = db.state.items.find((i) => i.id === followupIdFor(d.id));
        if (followup && followup.status === "open") followup.status = "done";
        db.log("draft.answered", `Marked “${d.subject}” as answered`, "draft", d.id);
        return touched(db, d);
      },
    ],
    [
      "DELETE",
      "/drafts/:id/answered",
      ({ db, params }) => {
        const d = sentDraft(db, params.id!);
        d.answered_on = null;
        d.answer_doc_id = null;
        const followup = db.state.items.find((i) => i.id === followupIdFor(d.id));
        if (followup && followup.status === "done") followup.status = "open";
        db.log("draft.answered", `“${d.subject}” is waiting for an answer again`, "draft", d.id);
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
        if (b.promise_amount != null && !(b.promise_amount >= 0 && b.promise_amount <= 1_000_000)) fail(422, "Type an amount between 0 and 1.000.000 euros.");
        const now = nowTs(db);
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
        c.updated_at = nowTs(db);
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
