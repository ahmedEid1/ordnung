/**
 * "How this was read" in the mock backend: every letter's readings, built from the mock ledger the
 * way the pipeline records them (`src/ordnung/trace`, what each step keeps: `facts.py`) — the text
 * layer, a photo's pages transcribed at the same time, the extraction call (and a repair call when
 * its first answer did not validate), one check per quote, the dates the rules engine computed, how
 * the sender, thread and contract were linked, and what planning did with each to-do.
 *
 * Steps keep only counts, codes, scores, dates and ids; like `ordnung/trace/view.py`, the view adds
 * the name each record has now (`label`). Durations and token counts are made up but stable (seeded
 * by the letter's id) and in the range the recorded demo shows.
 *
 * Readings: a letter that was read has one (when it was read). The parking fine has two: on arrival the
 * extraction's first answer did not validate and a repair call fixed it; read again after a prompt
 * update it did not need one — so "Compare" has something to show. "Read again" in the session adds
 * one; every reading is built from the letter as it is now.
 */
import type {
  Case,
  Contract,
  DateSpec,
  Document,
  DocumentTrace,
  Item,
  LLMCallRecord,
  Party,
  RefLink,
  SpanKind,
  TraceChange,
  TraceComparison,
  TraceExport,
  TraceRun,
  TraceSpan,
} from "@/api/types";

type SpanRecord = TraceExport["spans"][number];

/** One reading of a letter: when, by which job, and what went differently. */
export interface ReadingSeed {
  reading: number;
  trigger: TraceRun["trigger"];
  started_at: string;
  job_id: string;
  /** The extraction's first answer did not validate; a repair call retried it. */
  repair?: boolean;
  /** Version of the extraction prompt (`system.user.text`). */
  prompt_version?: string;
}

/** The mock ledger a reading is built from. */
export interface TraceLedger {
  documents: Document[];
  items: Item[];
  parties: Party[];
  cases: Case[];
  contracts: Contract[];
}

const EXTRACT_VERSION = "8.7.1";
const EARLIER_EXTRACT_VERSION = "8.6.1";
const TRANSCRIBE_VERSION = "1.1";

// ------------------------------------------------------------------------------------------------
// Stable "random" numbers
// ------------------------------------------------------------------------------------------------

function hash32(text: string, seed = 0x811c9dc5): number {
  let h = seed;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193);
  return h >>> 0;
}

const hex16 = (text: string) => hash32(text).toString(16).padStart(8, "0") + hash32(text, 0x9747b28c).toString(16).padStart(8, "0");
/** A number between `lo` and `hi`, the same every time for `key`. */
const between = (key: string, lo: number, hi: number) => lo + ((hash32(key) % 10_000) / 10_000) * (hi - lo);
const whole = (key: string, lo: number, hi: number) => Math.round(between(key, lo, hi));

export const traceIdFor = (docId: string, reading: number) => `trc_${hex16(`${docId}|${reading}`)}`;
const spanIdFor = (traceId: string, key: string) => `spn_${hex16(`${traceId}|${key}`)}`;

// ------------------------------------------------------------------------------------------------
// Seeds
// ------------------------------------------------------------------------------------------------

const PARKING_READ_AGAIN = "2026-09-25T17:48:00Z";

/**
 * The readings a letter has before anything happened in the session: none while it waits to be read,
 * else one when it was read (see the module comment for the parking fine's two).
 */
export function defaultReadings(doc: Document): ReadingSeed[] {
  const when = doc.ai_processed_at ?? (doc.ai_private ? (doc.processed_at ?? doc.created_at) : null);
  if (!when || doc.status === "queued" || doc.status === "processing") return [];
  const first: ReadingSeed = {
    reading: 1,
    trigger: "read",
    started_at: when,
    job_id: `job_${hex16(doc.id).slice(0, 12)}`,
  };
  if (doc.id !== "doc_parking") return [first];
  return [
    { ...first, repair: true, prompt_version: EARLIER_EXTRACT_VERSION },
    {
      reading: 2,
      trigger: "read_again",
      started_at: PARKING_READ_AGAIN,
      job_id: "job_parking_again",
    },
  ];
}

/** `kept` with one more reading (Read again); Ordnung keeps a letter's newest five. */
export function addReading(kept: ReadingSeed[], reading: Omit<ReadingSeed, "reading">): ReadingSeed[] {
  const next = Math.max(0, ...kept.map((s) => s.reading)) + 1;
  return [...kept, { ...reading, reading: next }].slice(-5);
}

// ------------------------------------------------------------------------------------------------
// Building one reading
// ------------------------------------------------------------------------------------------------

interface Node {
  kind: SpanKind;
  name: string;
  key: string;
  stage: string | null;
  /** How long the step itself took (a parent also spans its children). */
  ms: number;
  parallel?: boolean;
  attributes: Record<string, unknown>;
  ref?: RefLink | null;
  label?: string | null;
  call?: LLMCallRecord;
  children: Node[];
}

function node(parent: Node | null, kind: SpanKind, name: string, label: string, ms: number, attributes: Record<string, unknown> = {}, extra: Partial<Node> = {}): Node {
  const n: Node = {
    kind,
    name,
    key: parent ? `${parent.key}/${kind}:${label}` : label,
    stage: extra.stage ?? parent?.stage ?? null,
    ms,
    attributes,
    children: [],
    ...extra,
  };
  parent?.children.push(n);
  return n;
}

const SPEC_FIELDS = ["type", "date", "time", "anchor", "anchor_date", "amount", "unit", "delivery_rule", "shift_rule", "nature"] as const;
const specStructure = (spec: DateSpec) => Object.fromEntries(SPEC_FIELDS.map((f) => [f, spec[f] ?? null]));
const digitGroups = (quote: string) => quote.match(/\d+/g)?.length ?? 0;
const REFERENCE_KINDS: [RegExp, string][] = [
  [/kunden/i, "kundennummer"],
  [/mieter|vertrag/i, "vertragsnummer"],
  [/aktenzeichen|az\b|vorgang/i, "aktenzeichen"],
  [/rechnung/i, "rechnungsnummer"],
  [/steuer/i, "steuernummer"],
  [/mitglied/i, "mitgliedsnummer"],
];
const referenceKind = (label: string | undefined) => (label ? (REFERENCE_KINDS.find(([re]) => re.test(label))?.[1] ?? "other") : null);

function modelCall(
  ctx: { doc: Document; seed: ReadingSeed; traceId: string },
  key: string,
  c: {
    purpose: string;
    prompt: string;
    version: string;
    ms: number;
    output: number;
    pages?: number;
    bytes: number;
    outcome: LLMCallRecord["outcome"];
    repairOf?: number | null;
    stage: string;
  },
): LLMCallRecord {
  const cacheRead = c.purpose === "extract" ? 6_755 : 0;
  const creation = whole(`${key}|cc`, 2_400, 5_800);
  const cost = Math.round(((c.output * 15 + creation * 3.75 + cacheRead * 0.3) / 1_000_000) * 1_000_000) / 1_000_000;
  return {
    id: 4_000 + (hash32(`${ctx.traceId}|${key}`) % 5_000),
    ts: ctx.seed.started_at,
    purpose: c.purpose,
    model: "sonnet",
    backend: "claude-cli",
    duration_ms: Math.round(c.ms),
    input_tokens: 2,
    output_tokens: c.output,
    cache_read_tokens: cacheRead,
    cache_creation_tokens: creation,
    cost_usd: cost,
    ok: true,
    error: null,
    cache_hit: false,
    doc_ids: [ctx.doc.id],
    pages_sent: c.pages ?? 0,
    bytes_sent: c.bytes,
    request_key: hex16(`${key}|request`) + hex16(`${key}|request2`) + hex16(`${key}|request3`) + hex16(`${key}|request4`),
    prompt_name: c.prompt,
    prompt_version: c.version,
    served_model: "sonnet",
    job_id: ctx.seed.job_id,
    stage: c.stage,
    span_id: spanIdFor(ctx.traceId, key),
    repair_of: c.repairOf ?? null,
    outcome: c.outcome,
  };
}

const callFacts = (call: LLMCallRecord) => ({
  call_id: call.id,
  purpose: call.purpose,
  prompt: call.prompt_name,
  prompt_version: call.prompt_version,
  request_model: call.model,
  served_model: call.served_model,
  cache_hit: call.cache_hit,
  outcome: call.outcome,
  repair_of: call.repair_of,
});

const needsCheck = (i: Item) =>
  i.status === "open" && (i.grounding === "unverified" || i.evidence.some((e) => e.value_consistent === false) || i.computation?.confidence === "low");

function buildTree(ledger: TraceLedger, doc: Document, seed: ReadingSeed, traceId: string): Node {
  const ctx = { doc, seed, traceId };
  const items = ledger.items.filter((i) => i.doc_id === doc.id && (i.origin === "extracted" || i.origin === "rule"));
  const extracted = items.filter((i) => i.origin === "extracted");
  const party = ledger.parties.find((p) => p.id === doc.party_id) ?? null;
  const thread = ledger.cases.find((c) => c.id === doc.case_id) ?? null;
  const contract = ledger.contracts.find((c) => c.source_doc_id === doc.id) ?? null;
  const vision = doc.text_mode === "vision";
  const again = seed.trigger === "read_again";
  const root = node(null, "run", "Read letter", "run", 0, {
    reading: seed.reading,
    trigger: seed.trigger,
    private: doc.ai_private,
    timing: "measured",
    result: doc.status,
    text_mode: doc.ai_private ? "text" : doc.text_mode,
    pages: doc.pages,
    items: items.length,
    needs_check: items.filter(needsCheck).length,
    warnings: doc.warnings.length,
  });

  const words = vision ? 0 : whole(`${doc.id}|words`, 170, 260) * doc.pages;
  node(
    root,
    "ocr",
    "Text layer",
    "text",
    25 + 38 * doc.pages + between(`${doc.id}|text`, 0, 30),
    {
      pages: doc.pages,
      text_pages: vision ? 0 : doc.pages,
      to_transcribe: vision ? doc.pages : 0,
      words,
      hidden_text: doc.hidden_text,
    },
    { stage: "text" },
  );
  if (doc.ai_private) return root;

  if (vision) {
    const group = node(root, "ocr", "Transcribe", "transcribe", 0, { pages: doc.pages }, { stage: "transcribe", parallel: true });
    for (let page = 1; page <= doc.pages; page++) {
      const key = `${group.key}/model:page:${page}`;
      const ms = between(`${doc.id}|p${page}|${seed.reading}`, 11_200, 17_400);
      const call = modelCall(ctx, key, {
        purpose: "transcribe",
        prompt: "transcribe",
        version: TRANSCRIBE_VERSION,
        ms,
        output: whole(`${key}|out`, 1_250, 1_900),
        pages: 1,
        bytes: whole(`${key}|b`, 180_000, 262_000),
        outcome: "ok",
        stage: "transcribe",
      });
      node(
        group,
        "model",
        `Page ${page}`,
        `page:${page}`,
        ms,
        {
          ...callFacts(call),
          page,
          legible: true,
          chars: whole(`${key}|chars`, 1_700, 2_600),
          empty: false,
        },
        { call },
      );
    }
  }

  const version = seed.prompt_version ?? EXTRACT_VERSION;
  const extractKey = `${root.key}/model:extract`;
  const extractMs = between(`${doc.id}|extract|${seed.reading}`, 24_000, 58_000);
  const bytes = vision ? whole(`${doc.id}|tb`, 2_200, 3_600) * doc.pages : Math.round(words * 7.2);
  const first = modelCall(ctx, extractKey, {
    purpose: "extract",
    prompt: "extract",
    version,
    ms: extractMs,
    output: Math.round(extractMs / 9.2),
    bytes,
    outcome: seed.repair ? "invalid" : "ok",
    stage: "extract",
  });
  node(root, "model", "Extract", "extract", extractMs, { ...callFacts(first), ...(seed.repair ? { problems: 2 } : {}) }, { stage: "extract", call: first });
  if (seed.repair) {
    const key = `${root.key}/model:extract_repair`;
    const ms = between(`${doc.id}|repair`, 16_000, 24_000);
    const repair = modelCall(ctx, key, {
      purpose: "extract",
      prompt: "extract_repair",
      version: `${version}.r1`,
      ms,
      output: Math.round(ms / 9.5),
      bytes: bytes + 640,
      outcome: "repaired",
      repairOf: first.id,
      stage: "extract",
    });
    node(root, "model", "Extract · repair", "extract_repair", ms, callFacts(repair), { stage: "extract", call: repair });
  }

  // verify: one step per quote
  const quotes = node(root, "verify", "Check quotes", "quotes", 0, {}, { stage: "verify" });
  const groundings: string[] = [];
  const quoteStep = (label: string, target: string, index: number, e: Item["evidence"][number], extra: Record<string, unknown>, ref: RefLink, name: string | null) => {
    groundings.push(e.grounding);
    const consistent = e.value_consistent !== false;
    const score = e.grounding === "unverified" ? whole(`${doc.id}|${label}|s`, 58, 84) : 100;
    node(
      quotes,
      "verify",
      "Quote",
      label,
      between(`${doc.id}|${label}|ms`, 1.5, 9),
      {
        target,
        index,
        grounding: e.grounding,
        page: e.grounding === "unverified" ? null : (e.page ?? 1),
        score,
        best_score: score,
        digit_groups: digitGroups(e.quote),
        digits_matched: e.grounding !== "unverified",
        boxes: e.boxes.length,
        consistent,
        reasons: consistent ? [] : ["date_not_in_quote"],
        ...extra,
      },
      { ref, label: name },
    );
  };
  extracted.forEach((i, index) => {
    const e = i.evidence[0];
    if (e) quoteStep(`item:${i.slot_key}`, "item", index, e, { slot_key: i.slot_key }, { type: "item", id: i.id }, i.title);
  });
  doc.key_facts.forEach((f, index) => {
    if (f.evidence) quoteStep(`key_fact:${index}`, "key_fact", index, f.evidence, {}, { type: "document", id: doc.id }, f.label);
  });
  if (doc.remedy?.quote)
    quoteStep(
      "remedy:0",
      "remedy",
      0,
      {
        doc_id: doc.id,
        page: 1,
        quote: doc.remedy.quote,
        grounding: vision ? "model_read" : "verified",
        value_consistent: true,
        score: 1,
        boxes: [],
      },
      {},
      { type: "document", id: doc.id },
      "How to object",
    );
  quotes.attributes = {
    quotes: groundings.length,
    verified: groundings.filter((g) => g === "verified").length,
    model_read: groundings.filter((g) => g === "model_read").length,
    unverified: groundings.filter((g) => g === "unverified").length,
    needs_check: extracted.filter(needsCheck).length,
  };

  // the sender
  const earlier = ledger.documents.filter((d) => d.party_id && d.party_id === doc.party_id && d.id !== doc.id && d.created_at < doc.created_at);
  const known = Boolean(party) && (earlier.length > 0 || again);
  const reference = doc.references[0];
  const others = ledger.parties.filter((p) => p.id !== party?.id).slice(0, 12);
  const candidates = others
    .map((p) => ({
      party_id: p.id,
      score: Math.round(between(`${doc.id}|${p.id}`, 22, 71) * 10) / 10,
    }))
    .sort((a, b) => b.score - a.score)
    .slice(0, known ? 0 : 2);
  node(
    root,
    "link",
    "Sender",
    "sender",
    between(`${doc.id}|sender`, 2, 7),
    {
      decision: !party ? "none" : known ? (reference ? "identifier" : "name") : "new",
      party_id: party?.id ?? null,
      score: null,
      reference_kind: known && reference ? referenceKind(reference.label) : null,
      candidates: party ? candidates : [],
    },
    {
      stage: "link",
      ref: party ? { type: "party", id: party.id } : null,
      label: party?.name ?? null,
    },
  );

  // the rules engine: one step per dated to-do
  const dated = extracted.filter((i) => i.date_spec && (i.date_spec.type !== "none" || i.computation));
  const dates = node(root, "rules", "Compute dates", "dates", 0, { items: extracted.length, dated: dated.length }, { stage: "compute" });
  dated.forEach((i) => {
    const r = i.computation;
    node(
      dates,
      "rules",
      "Date",
      `item:${i.slot_key}`,
      between(`${i.id}|rules`, 0.6, 3.5),
      {
        index: extracted.indexOf(i),
        spec: specStructure(i.date_spec!),
        source: i.due_date_source,
        due_date: r?.due_date ?? i.due_date,
        send_by: r?.send_by ?? i.send_by,
        safe_date: r?.safe_date ?? null,
        rule_ids: r?.rule_ids ?? [],
        confidence: r?.confidence ?? null,
        warnings: r?.warnings.length ?? 0,
        holiday_calendar: r?.holiday_calendar ?? null,
        slot_key: i.slot_key,
      },
      { ref: { type: "item", id: i.id }, label: i.title },
    );
  });

  // thread, contract, payment check, reminder
  const links = node(root, "link", "Thread & contract", "links", 0, {}, { stage: "link" });
  if (doc.payment) {
    const scam = doc.id === "doc_scam";
    const knownIban = ledger.documents.some((d) => d.id !== doc.id && d.party_id === doc.party_id && d.payment?.iban === doc.payment?.iban);
    node(links, "link", "Payment check", "payment", between(`${doc.id}|pay`, 1, 4), {
      finding: scam ? "iban_changed" : null,
      iban_valid: doc.payment.iban ? doc.payment.iban_valid : null,
      iban_known: knownIban,
      iban_added: !scam && !knownIban && Boolean(doc.payment.iban_valid),
    });
  }
  if (thread) {
    const threadKnown = thread.created_at < doc.created_at || again;
    node(
      links,
      "link",
      "Thread",
      "thread",
      between(`${doc.id}|thread`, 1, 3),
      {
        decision: threadKnown ? (reference ? "reference" : "same_thread") : "new",
        case_id: thread.id,
        reference_kind: referenceKind(reference?.label),
      },
      { ref: { type: "case", id: thread.id }, label: thread.title },
    );
  }
  if (contract) {
    node(
      links,
      "link",
      "Contract",
      "contract",
      between(`${doc.id}|contract`, 2, 6),
      {
        decision: again ? "refreshed" : "created",
        contract_id: contract.id,
        change: null,
      },
      { ref: { type: "contract", id: contract.id }, label: contract.name },
    );
  }
  if (doc.kind === "dunning") node(links, "link", "Payment reminder", "reminder", 1.2, { invoices: 1 });

  // planning: what happened to each to-do
  const plan = node(root, "plan", "Plan to-dos", "plan", 0, {}, { stage: "plan" });
  extracted.forEach((i, index) => {
    const action = !again ? "created" : i.user_modified ? "kept_edited" : i.recurrence ? "kept_later_date" : "updated";
    node(
      plan,
      "plan",
      "To-do",
      `item:${i.slot_key}`,
      between(`${i.id}|plan`, 2, 9),
      {
        index,
        item_id: i.id,
        slot_key: i.slot_key,
        action,
        moved: false,
        due_date: i.due_date,
        status: i.status,
      },
      { ref: { type: "item", id: i.id }, label: i.title },
    );
  });
  for (const i of items.filter((x) => x.origin === "rule")) {
    const r = i.computation;
    const rule = i.slot_key?.replace(/^rule:/, "") ?? i.id;
    node(
      plan,
      "rules",
      "Deadline the law adds",
      `law:${rule}`,
      between(`${i.id}|law`, 0.8, 2.4),
      {
        rule_id: rule,
        due_date: r?.due_date ?? i.due_date,
        send_by: r?.send_by ?? i.send_by,
        rule_ids: r?.rule_ids ?? [],
        confidence: r?.confidence ?? null,
        filed: true,
        reason: "filed",
        item_id: i.id,
      },
      { ref: { type: "item", id: i.id }, label: i.title },
    );
  }
  plan.attributes = {
    removed: 0,
    status: doc.status,
    needs_check: items.filter(needsCheck).length,
    ...(extracted.some((i) => i.recurrence) ? { rolled_forward: true } : {}),
  };
  return root;
}

/** Lay the steps out (children one after another; a parallel step's children all at its start). */
function layout(n: Node, start: number, placed: Map<Node, [number, number]>): number {
  let end = start + n.ms;
  let cursor = start;
  for (const child of n.children) {
    const childEnd = layout(child, n.parallel ? start : cursor, placed);
    if (!n.parallel) cursor = childEnd;
    end = Math.max(end, childEnd);
  }
  placed.set(n, [start, end]);
  return end;
}

interface Built {
  run: TraceRun;
  spans: TraceSpan[];
  records: SpanRecord[];
}

const round3 = (n: number) => Math.round(n * 1000) / 1000;
const at = (startedAt: string, ms: number) => new Date(Date.parse(startedAt) + Math.round(ms)).toISOString();

/** One reading of `doc` as the API returns it. */
export function buildReading(ledger: TraceLedger, doc: Document, seed: ReadingSeed): Built {
  const traceId = traceIdFor(doc.id, seed.reading);
  const root = buildTree(ledger, doc, seed, traceId);
  const placed = new Map<Node, [number, number]>();
  const total = layout(root, 0, placed);
  const spans: TraceSpan[] = [];
  const records: SpanRecord[] = [];
  const walk = (n: Node, parent: Node | null, depth: number) => {
    const [start, end] = placed.get(n)!;
    const id = spanIdFor(traceId, n.key);
    const parentId = parent ? spanIdFor(traceId, parent.key) : null;
    spans.push({
      id,
      parent_id: parentId,
      depth,
      key: n.key,
      kind: n.kind,
      name: n.name,
      stage: n.stage,
      start_ms: round3(start),
      duration_ms: round3(end - start),
      status: "ok",
      error: null,
      attributes: n.attributes,
      call: n.call ?? null,
      ref: n.ref ?? null,
      label: n.label ?? null,
    });
    records.push({
      id,
      trace_id: traceId,
      doc_id: doc.id,
      job_id: seed.job_id,
      parent_id: parentId,
      key: n.key,
      seq: records.length,
      kind: n.kind,
      name: n.name,
      stage: n.stage,
      started_at: at(seed.started_at, start),
      ended_at: at(seed.started_at, end),
      status: "ok",
      error: null,
      attributes: n.attributes,
    });
    n.children.forEach((c) => walk(c, n, depth + 1));
  };
  walk(root, null, 0);
  const calls = spans.flatMap((s) => (s.call ? [s.call] : []));
  const run: TraceRun = {
    trace_id: traceId,
    reading: seed.reading,
    job_id: seed.job_id,
    started_at: seed.started_at,
    ended_at: at(seed.started_at, total),
    duration_ms: round3(total),
    status: "ok",
    ended: "done",
    error: null,
    trigger: seed.trigger,
    timing: "measured",
    result: doc.status,
    model_calls: calls.length,
    cache_hits: calls.filter((c) => c.cache_hit).length,
    repairs: calls.filter((c) => c.repair_of !== null).length,
    input_tokens: calls.reduce((s, c) => s + c.input_tokens, 0),
    output_tokens: calls.reduce((s, c) => s + c.output_tokens, 0),
    cache_read_tokens: calls.reduce((s, c) => s + c.cache_read_tokens, 0),
    cache_creation_tokens: calls.reduce((s, c) => s + c.cache_creation_tokens, 0),
    cost_usd: Math.round(calls.reduce((s, c) => s + c.cost_usd, 0) * 1e6) / 1e6,
    model_ms: busyMs(spans.filter((sp) => sp.kind === "model")),
  };
  return { run, spans, records };
}

/** How long at least one of `spans` was under way: the pages of a photo, read at the same time, count once. */
function busyMs(spans: TraceSpan[]): number {
  let total = 0;
  let reach = -Infinity;
  for (const sp of [...spans].sort((a, b) => a.start_ms - b.start_ms)) {
    const end = sp.start_ms + sp.duration_ms;
    if (sp.start_ms > reach) total += sp.duration_ms;
    else if (end > reach) total += end - reach;
    reach = Math.max(reach, end);
  }
  return round3(total);
}

/** `GET /documents/{id}/trace`: the reading `traceId` (default: the newest kept) and every kept reading. */
export function documentTrace(ledger: TraceLedger, doc: Document, seeds: ReadingSeed[], traceId?: string | null): DocumentTrace | null {
  const newestFirst = [...seeds].sort((a, b) => b.reading - a.reading);
  if (!newestFirst.length) return traceId ? null : { doc_id: doc.id, run: null, runs: [], spans: [] };
  const built = newestFirst.map((s) => buildReading(ledger, doc, s));
  const chosen = traceId ? built.find((b) => b.run.trace_id === traceId) : built[0];
  if (!chosen) return null;
  return {
    doc_id: doc.id,
    run: chosen.run,
    runs: built.map((b) => b.run),
    spans: chosen.spans,
  };
}

// ------------------------------------------------------------------------------------------------
// Comparing two readings (`ordnung/trace/compare.py`)
// ------------------------------------------------------------------------------------------------

const DECIDED: Record<SpanKind, string[]> = {
  run: ["result", "needs_check", "items"],
  model: ["outcome", "cache_hit", "served_model", "prompt_version", "legible"],
  ocr: ["pages", "text_pages", "to_transcribe", "hidden_text"],
  verify: ["grounding", "page", "digits_matched", "consistent", "reasons"],
  rules: ["due_date", "send_by", "confidence", "rule_ids", "filed"],
  link: ["party_id", "case_id", "contract_id", "change", "finding"],
  plan: ["item_id", "action", "due_date", "removed"],
};
const SAME_ACTION: Record<string, string> = {
  created: "filed",
  updated: "filed",
};

function decided(span: TraceSpan, field: string): unknown {
  const value = span.attributes[field];
  if (span.kind === "plan" && field === "action" && typeof value === "string") return SAME_ACTION[value] ?? value;
  return value;
}

const change = (shown: TraceSpan, field: string, before: unknown, after: unknown): TraceChange => ({
  key: shown.key,
  kind: shown.kind,
  name: shown.name,
  field,
  before: before ?? null,
  after: after ?? null,
  ref: shown.ref,
  label: shown.label,
});

/** What `head` decided differently from `base`, step by step (decisions, never timings). */
export function compareReadings(base: DocumentTrace, head: DocumentTrace): TraceComparison {
  const earlier = new Map(base.spans.map((s) => [s.key, s]));
  const later = new Set(head.spans.map((s) => s.key));
  const changes: TraceChange[] = [];
  for (const span of head.spans) {
    const old = earlier.get(span.key);
    if (!old) {
      changes.push(change(span, "present", false, true));
      continue;
    }
    for (const field of DECIDED[span.kind]) {
      if (JSON.stringify(decided(old, field) ?? null) !== JSON.stringify(decided(span, field) ?? null)) {
        changes.push(change(span, field, old.attributes[field], span.attributes[field]));
      }
    }
  }
  for (const span of base.spans) if (!later.has(span.key)) changes.push(change(span, "present", true, false));
  return { doc_id: head.doc_id, base: base.run!, head: head.run!, changes };
}

/** `GET /traces`: every kept reading of the letters not in the trash, as stored. */
export function exportTraces(ledger: TraceLedger, seeds: Record<string, ReadingSeed[]>): TraceExport {
  const spans: SpanRecord[] = [];
  const calls: LLMCallRecord[] = [];
  for (const doc of ledger.documents) {
    if (doc.deleted_at) continue;
    for (const seed of [...(seeds[doc.id] ?? [])].sort((a, b) => a.reading - b.reading)) {
      const built = buildReading(ledger, doc, seed);
      spans.push(...built.records);
      calls.push(...built.spans.flatMap((s) => (s.call ? [s.call] : [])));
    }
  }
  return { spans, calls: calls.sort((a, b) => a.id - b.id) };
}
