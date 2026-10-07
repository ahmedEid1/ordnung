/**
 * API contract: the web app, the in-memory mock backend (`?mock=1` and the static demo) and the
 * backend's OpenAPI schema (`web/openapi.json`, generated from FastAPI by `make openapi`) agree.
 *
 * Every `api.*` function is called against the mock server; each request is checked against the
 * OpenAPI operation it targets (path, method, query parameters and their bounds, JSON body or
 * multipart field names) and each mock response against that operation (status code, response
 * schema — strictly, so a mock that adds or drops a field fails). Every mock route must exist in
 * the API, and every API operation must be used by the web app (or be listed as not needed).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import openapiText from "../../openapi.json?raw";
import { createMockServer, MOCK_ROUTES, type MockServer } from "@/mocks/server";
import { classifyPhoneRequest, phoneScopeFromOpenApi } from "@/mocks/phone";
import { SchemaChecker, type OpenApiDoc, type Operation, type Schema } from "@/test/jsonSchema";
import { ApiError } from "./client";
import { api, type Api } from "./endpoints";
import { PHONE_ERROR_CODES, type StreamEvent } from "./types";

const doc = JSON.parse(openapiText) as OpenApiDoc;
const strict = new SchemaChecker(doc, true);
const loose = new SchemaChecker(doc);

// ------------------------------------------------------------------------------------------------
// Matching requests to operations
// ------------------------------------------------------------------------------------------------

const paramCount = (template: string) => template.match(/\{/g)?.length ?? 0;
const literalLength = (template: string) => template.replace(/\{[^}]+\}/g, "").length;
const templateRegex = (template: string) =>
  new RegExp(`^${template.replace(/[.]/g, "\\.").replace(/\{[^}]+\}/g, "[^/]+")}$`);

/** The OpenAPI operation serving `method pathname` (the most specific template wins). */
function operationFor(method: string, pathname: string): { key: string; op: Operation } | null {
  const templates = Object.keys(doc.paths)
    .filter((template) => templateRegex(template).test(pathname))
    .sort((a, b) => paramCount(a) - paramCount(b) || literalLength(b) - literalLength(a));
  for (const template of templates) {
    const op = doc.paths[template]?.[method.toLowerCase()];
    if (op) return { key: `${method.toUpperCase()} ${template}`, op };
  }
  return null;
}

function schemaTypes(schema: Schema): string[] {
  const resolved = loose.resolve(schema);
  const own = resolved.type === undefined ? [] : Array.isArray(resolved.type) ? (resolved.type as string[]) : [resolved.type as string];
  const nested = ((resolved.anyOf ?? resolved.oneOf ?? []) as Schema[]).flatMap(schemaTypes);
  return [...own, ...nested];
}

/** A query string value as FastAPI parses it for this parameter schema. */
function parseQueryValue(raw: string, schema: Schema): unknown {
  const types = schemaTypes(schema);
  if (types.includes("boolean") && (raw === "true" || raw === "false")) return raw === "true";
  if ((types.includes("integer") || types.includes("number")) && raw.trim() !== "" && !Number.isNaN(Number(raw))) return Number(raw);
  return raw;
}

function requestProblems(op: Operation, url: URL, body: unknown): string[] {
  const problems: string[] = [];
  const query = (op.parameters ?? []).filter((p) => p.in === "query");
  for (const [name, raw] of url.searchParams) {
    const param = query.find((p) => p.name === name);
    if (!param) problems.push(`query “${name}” is not a parameter of this operation`);
    else problems.push(...loose.check(parseQueryValue(raw, param.schema), param.schema, `query.${name}`));
  }
  const content = op.requestBody?.content ?? {};
  if (body instanceof FormData) {
    const form = content["multipart/form-data"]?.schema;
    if (!form) problems.push("sends multipart form data, the API expects none");
    else {
      const fields = (loose.resolve(form).properties ?? {}) as Record<string, Schema>;
      for (const name of new Set(body.keys())) if (!(name in fields)) problems.push(`form field “${name}” is not declared`);
    }
  } else if (body !== undefined) {
    const json = content["application/json"]?.schema;
    if (!json) problems.push("sends a JSON body, the API expects none");
    else problems.push(...loose.check(body, json, "body"));
  } else if ((op.requestBody as { required?: boolean } | undefined)?.required) {
    problems.push("sends no body, the API requires one");
  }
  return problems;
}

function sseEvents(text: string): unknown[] {
  return text
    .split(/\n\n/)
    .map((block) =>
      block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n"),
    )
    .filter(Boolean)
    .map((data) => JSON.parse(data) as unknown);
}

async function responseProblems(op: Operation, res: Response): Promise<string[]> {
  const declared = op.responses[String(res.status)];
  if (!declared) return [`status ${res.status} is not declared (API: ${Object.keys(op.responses).join(", ")})`];
  const text = await res.text();
  if (res.status >= 400) {
    const body = JSON.parse(text) as { detail?: unknown };
    return typeof body.detail === "string" ? [] : [`error body without a “detail” message: ${text.slice(0, 120)}`];
  }
  const content = declared.content ?? {};
  if (content["text/event-stream"]) {
    const schema = content["text/event-stream"].schema;
    const events = sseEvents(text);
    if (!events.length) return ["the event stream is empty"];
    if (text.includes("\nevent:") || text.startsWith("event:")) return ["the API sends default `message` events (type inside the data)"];
    return schema ? events.flatMap((event, i) => strict.check(event, schema, `event[${i}]`)) : [];
  }
  const schema = content["application/json"]?.schema;
  // a file download (the encrypted backup): the declared media type, not JSON
  const file = Object.keys(content).find((type) => type !== "application/json");
  if (!schema && file) return res.headers.get("content-type")?.startsWith(file) ? [] : [`expected a ${file} file, got ${res.headers.get("content-type")}`];
  if (!schema) return text ? [`unexpected body for a ${res.status} without JSON content`] : [];
  if (!text) return ["empty body, the API returns JSON"];
  return strict.check(JSON.parse(text), schema, "response");
}

// ------------------------------------------------------------------------------------------------
// Every endpoint function, called against the mock server
// ------------------------------------------------------------------------------------------------

interface Exchange {
  method: string;
  url: URL;
  body: unknown;
  response: Response;
}

interface Ids {
  doc: string;
  otherDoc: string;
  item: string;
  otherItem: string;
  contract: string;
  party: string;
  case: string;
  draft: string;
  suggestion: string;
  mail: string;
  thread: string;
  /** letters waiting for the person (from the watched folder) */
  held: string;
  otherHeld: string;
  /** a letter that was sent (proof belongs to sent letters) */
  sentDraft: string;
  proof: string;
  call: string;
}

interface Case {
  run: (ids: Ids) => unknown;
  /** Expected status when not a success (e.g. 409: the demo can't do this). */
  status?: number;
  /** Returns a URL for `<img>`/`<a>` instead of calling fetch. */
  asset?: true;
}

async function drain(stream: AsyncGenerator<StreamEvent>): Promise<StreamEvent[]> {
  const out: StreamEvent[] = [];
  for await (const ev of stream) out.push(ev);
  return out;
}

const pdf = () => new File(["%PDF-1.4\n%demo\n"], "letter.pdf", { type: "application/pdf" });
const photo = () => new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], "zustellung.jpg", { type: "image/jpeg" });

/** One case per endpoint function (the type makes adding an endpoint without a case a compile error). */
const CASES = {
  health: { run: () => api.health() },
  probeHealth: { run: () => api.probeHealth() },
  profile: { run: () => api.profile() },
  updateProfile: { run: () => api.updateProfile({ name: "Sam Rivera", postal_buffer_days: 3 }) },
  settings: { run: () => api.settings() },
  updateSettings: { run: () => api.updateSettings({ llm_brief: true, models: { brief: "haiku" } }) },
  onboarding: { run: () => api.onboarding({ profile: { region: "NW" }, skip_ai: false }) },
  deleteEverything: { run: () => api.deleteEverything(), status: 409 },

  documents: { run: () => api.documents({ q: "Rechnung", status: "processed", limit: 20, offset: 0 }) },
  uploadDocuments: { run: () => api.uploadDocuments([pdf()], { combine: false, private: false }) },
  document: { run: (ids) => api.document(ids.doc) },
  updateDocument: { run: (ids) => api.updateDocument(ids.doc, { title: "Renamed letter", tags: ["kept"] }) },
  deleteDocument: { run: (ids) => api.deleteDocument(ids.otherDoc) },
  reprocessDocument: { run: (ids) => api.reprocessDocument(ids.doc) },
  fileUrl: { run: (ids) => api.fileUrl(ids.doc), asset: true },
  pageUrl: { run: (ids) => api.pageUrl(ids.doc, 1), asset: true },
  thumbnailUrl: { run: (ids) => api.thumbnailUrl(ids.doc), asset: true },
  folder: { run: () => api.folder() },
  readHeld: { run: (ids) => api.readHeld([ids.held, "doc_gone"]) },
  keepHeldPrivate: { run: (ids) => api.keepHeldPrivate([ids.otherHeld]) },
  waitAgain: { run: (ids) => api.waitAgain([ids.otherHeld]) }, // after keepHeldPrivate: undoes it
  documentTrace: { run: (ids) => api.documentTrace(ids.doc) },
  // the parking fine was read twice (mocks/data/traces.ts)
  traceComparison: { run: () => api.traceComparison("doc_parking") },
  traces: { run: () => api.traces() },

  items: { run: () => api.items({ status: "open", from: "2026-09-01", to: "2026-12-31", include_undated: true, limit: 50 }) },
  createItem: { run: () => api.createItem({ kind: "task", title: "Call the bank", due_date: "2026-10-05", area: "money" }) },
  updateItem: { run: (ids) => api.updateItem(ids.item, { status: "done" }) },
  deleteItem: { run: (ids) => api.deleteItem(ids.otherItem) },
  confirmItem: { run: (ids) => api.confirmItem(ids.item) },
  // the photographed parking fine waits for the person to compare it with the paper letter
  confirmGiroCode: {
    run: () => api.confirmGiroCode("itm_parking", { payee: "Stadtkasse Musterstadt", iban: "DE51123456000000100017", reference: "OA-VW-2026-55012", amount: 30 }),
  },
  itemIcsUrl: { run: (ids) => api.itemIcsUrl(ids.item), asset: true },

  contracts: { run: () => api.contracts({ status: "active" }) },
  updateContract: { run: (ids) => api.updateContract(ids.contract, { cost_amount: 19.99, cost_interval: "monthly" }) },
  parties: { run: () => api.parties() },
  party: { run: (ids) => api.party(ids.party) },
  updateParty: { run: (ids) => api.updateParty(ids.party, { region: "NW" }) },
  case: { run: (ids) => api.case(ids.case) },

  timeline: { run: () => api.timeline("2026-09-01", "2026-12-31") },
  lanes: { run: () => api.lanes() },
  dashboard: { run: () => api.dashboard() },
  numbers: { run: () => api.numbers() },
  week: { run: () => api.week() },
  weekDone: { run: () => api.weekDone() },
  weekDismiss: { run: () => api.weekDismiss() },

  suggestions: { run: () => api.suggestions({ limit: 20 }) },
  updateSuggestion: { run: (ids) => api.updateSuggestion(ids.suggestion, { status: "snoozed", snoozed_until: "2026-10-05" }) },
  runReview: { run: () => api.runReview() },
  brief: { run: () => api.brief() },
  regenerateBrief: { run: () => api.regenerateBrief() },

  ask: { run: () => drain(api.ask({ question: "When can I cancel my phone contract?", thread_id: null })) },
  chat: { run: (ids) => api.chat(ids.thread) },

  drafts: { run: () => api.drafts() },
  createDraft: { run: (ids) => api.createDraft({ kind: "cancellation", contract_id: ids.contract, language: "de" }) },
  draft: { run: (ids) => api.draft(ids.draft) },
  updateDraft: { run: (ids) => api.updateDraft(ids.draft, { subject: "Kündigung", enclosures: [] }) },
  deleteDraft: { run: (ids) => api.deleteDraft(ids.draft) },
  translateDraft: { run: (ids) => api.translateDraft(ids.draft), status: 409 },
  draftPdfUrl: { run: (ids) => api.draftPdfUrl(ids.draft), asset: true },
  draftPreviewUrl: { run: (ids) => api.draftPreviewUrl(ids.draft), asset: true },
  markDraftSent: { run: (ids) => api.markDraftSent(ids.draft, { channel: "registered_letter", date: "2026-09-28", tracking_number: "RT 123 456 785 DE" }) },

  draftProof: { run: (ids) => api.draftProof(ids.sentDraft) },
  setTracking: { run: (ids) => api.setTracking(ids.sentDraft, { tracking_number: "0034 0434 1234" }) },
  addProof: { run: (ids) => api.addProof(ids.sentDraft, { file: photo(), kind: "delivery_record", onDate: "2026-09-24", note: "Copy from Deutsche Post" }) },
  updateProof: { run: (ids) => api.updateProof(ids.sentDraft, ids.proof, { on_date: "2026-09-22", note: "Filiale Mitte" }) },
  removeProof: { run: (ids) => api.removeProof(ids.sentDraft, ids.proof) },
  proofPdfUrl: { run: (ids) => api.proofPdfUrl(ids.sentDraft), asset: true },
  markAnswered: { run: (ids) => api.markAnswered(ids.sentDraft, null) },
  unmarkAnswered: { run: (ids) => api.unmarkAnswered(ids.sentDraft) },
  waiting: { run: () => api.waiting() },
  calls: { run: (ids) => api.calls({ party_id: ids.party }) },
  createCall: {
    run: (ids) =>
      api.createCall({ party_id: ids.party, called_on: "2026-09-25", contact: "Frau Weber", summary: "Asked about my letter.", promise: "Call back", promise_due: "2026-10-02", promise_amount: null }),
  },
  updateCall: { run: (ids) => api.updateCall(ids.call, { kept: true }) },
  deleteCall: { run: (ids) => api.deleteCall(ids.call) },

  calendarIcsUrl: { run: () => api.calendarIcsUrl(), asset: true },
  calendarExported: { run: () => api.calendarExported() },
  calendarSync: { run: () => api.calendarSync() },
  calendarSyncPreview: { run: () => api.calendarSyncPreview("full") },
  discoverCalendars: { run: () => api.discoverCalendars({ url: "https://cloud.example.org/", username: "sam", password: "abcd-efgh-ijkl-mnop" }) },
  connectCalendarSync: {
    run: () => api.connectCalendarSync({ url: "https://cloud.example.org/remote.php/dav/calendars/sam/ordnung/", username: "sam", password: "abcd-efgh-ijkl-mnop", mode: "discreet" }),
  },
  runCalendarSync: { run: () => api.runCalendarSync() },
  disconnectCalendarSync: { run: () => api.disconnectCalendarSync(true) },

  desktopReminders: { run: () => api.desktopReminders() },
  testDesktopNotification: { run: () => api.testDesktopNotification("full") },
  backupInfo: { run: () => api.backupInfo() },
  downloadBackup: { run: () => api.downloadBackup("correct horse battery staple") },

  // phone access, in this order: on, a code, closed, a phone paired earlier removed, start over
  phone: { run: () => api.phone() },
  updatePhone: { run: () => api.updatePhone({ enabled: true, address: "192.168.178.23", port: 8767, home_network: false }) },
  createPhonePairing: { run: () => api.createPhonePairing() },
  cancelPhonePairing: { run: () => api.cancelPhonePairing() },
  removePhone: { run: () => api.removePhone(srv.phone.addPhone({ name: "Anna's iPhone" }).id) },
  resetPhone: { run: () => api.resetPhone() },
  // pairing is the phone's: the computer's own listener answers 404 not_phone (the phone listener: below)
  pairPhone: { run: () => api.pairPhone({ code: "K7QM2-XD9PA", name: "Sam's iPhone" }), status: 404 },

  activity: { run: () => api.activity(50) },
  usage: { run: () => api.usage() },
  rules: { run: () => api.rules() },
  jobs: { run: () => api.jobs(true) },

  tour: { run: () => api.tour() },
  updateTour: { run: () => api.updateTour({ step: 1, active: true }) },
  mailTray: { run: () => api.mailTray() },
  demoQuestions: { run: () => api.demoQuestions() },
  openMail: { run: (ids) => api.openMail(ids.mail) },
} satisfies Record<keyof Api, Case>;

/** Calls whose effects the later ones depend on run in this order; deletions come last. */
const ORDER: (keyof Api)[] = [
  "ask",
  "chat",
  "updateDraft", // before it is sent: a sent letter's text can't change (409)
  "markDraftSent",
  "translateDraft",
  "confirmGiroCode", // before a later case marks the parking fine paid
  ...(Object.keys(CASES) as (keyof Api)[]).filter(
    (name) =>
      ![
        "ask",
        "chat",
        "updateDraft",
        "markDraftSent",
        "translateDraft",
        "confirmGiroCode",
        "deleteDraft",
        "deleteDocument",
        "deleteItem",
        "deleteEverything",
        "removeProof",
        "deleteCall",
      ].includes(name),
  ),
  "removeProof",
  "deleteCall",
  "deleteDraft",
  "deleteItem",
  "deleteDocument",
  "deleteEverything",
];

/** API operations the web app deliberately doesn't call through `api` (with the reason). */
const NOT_CALLED_BY_API: Record<string, string> = {
  "GET /api/events": "consumed with EventSource in api/sse.ts",
  "GET /api/items/{item_id}": "to-dos come with their letter, list or dashboard",
};

let srv: MockServer;
let exchanges: Exchange[];

beforeEach(() => {
  srv = createMockServer({ staticDemo: false, latency: 0 });
  exchanges = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = undefined;
    if (init?.body instanceof FormData) body = init.body;
    else if (typeof init?.body === "string") body = JSON.parse(init.body) as unknown;
    const response = await srv.handle(method, url.pathname.replace(/^\/api/, ""), url.searchParams, body, init?.signal ?? null);
    exchanges.push({ method, url, body, response: response.clone() });
    return response;
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function ids(): Ids {
  const s = srv.db.state;
  const docs = srv.db.liveDocuments();
  const openItems = s.items.filter((i) => i.status === "open");
  return {
    doc: docs[0]!.id,
    otherDoc: docs[docs.length - 1]!.id,
    item: openItems[0]!.id,
    otherItem: openItems[openItems.length - 1]!.id,
    contract: s.contracts[0]!.id,
    party: s.parties[0]!.id,
    case: s.cases[0]!.id,
    draft: s.drafts[0]!.id,
    suggestion: s.suggestions[0]!.id,
    mail: s.tray.find((t) => !t.opened)!.id,
    thread: "",
    held: docs.find((d) => d.status === "held")!.id,
    otherHeld: docs.filter((d) => d.status === "held").at(-1)!.id,
    sentDraft: s.drafts.find((d) => d.status === "sent" && d.sent_channel === "registered_letter")!.id,
    proof: s.proofs[0]!.id,
    call: s.calls[0]!.id,
  };
}

describe("API contract (web ↔ mock ↔ openapi.json)", () => {
  it("every endpoint function sends what the API expects and the mock answers like the API", async () => {
    const known = ids();
    const problems: string[] = [];
    const called = new Set<string>();
    for (const name of ORDER) {
      const c: Case = CASES[name];
      const before = exchanges.length;
      let result: unknown;
      try {
        result = await c.run(known);
      } catch (err) {
        if (!c.status) problems.push(`${name}: threw ${String(err)}`);
      }
      if (c.asset) {
        const url = new URL(String(result), "http://localhost");
        const match = operationFor("GET", url.pathname);
        if (!match) problems.push(`${name}: ${url.pathname} is not an API route`);
        else called.add(match.key);
        continue;
      }
      if (name === "ask") {
        const done = (result as StreamEvent[]).find((ev) => ev.type === "done");
        known.thread = done?.thread_id ?? "";
        if (!known.thread) problems.push("ask: no done event with a thread id");
      }
      const mine = exchanges.slice(before);
      if (mine.length !== 1) {
        problems.push(`${name}: made ${mine.length} requests`);
        continue;
      }
      const { method, url, body, response } = mine[0]!;
      const match = operationFor(method, url.pathname);
      if (!match) {
        problems.push(`${name}: ${method} ${url.pathname} is not an API route`);
        continue;
      }
      called.add(match.key);
      if (c.status && response.status !== c.status) problems.push(`${name}: expected ${c.status}, the mock answered ${response.status}`);
      if (!c.status && !response.ok) problems.push(`${name}: the mock answered ${response.status} (${await response.clone().text()})`);
      for (const p of [...requestProblems(match.op, url, body), ...(await responseProblems(match.op, response))]) {
        problems.push(`${name} (${match.key}): ${p}`);
      }
    }
    expect(problems).toEqual([]);

    const unused = Object.entries(doc.paths)
      .flatMap(([template, ops]) => Object.keys(ops).map((m) => `${m.toUpperCase()} ${template}`))
      .filter((key) => !called.has(key) && !(key in NOT_CALLED_BY_API));
    expect(unused, "API operations the web app never calls — add an api function or list them in NOT_CALLED_BY_API").toEqual([]);
  });

  it("every mock route is a route of the API", () => {
    const missing = MOCK_ROUTES.filter(([method, pattern]) => !operationFor(method, `/api${pattern.replace(/:(\w+)/g, "x_$1")}`)).map(
      ([method, pattern]) => `${method} ${pattern}`,
    );
    expect(missing).toEqual([]);
  });

  it("the mock streams Ask answers exactly like the API (default message events, checked `done`)", async () => {
    const events = await drain(api.ask({ question: "What did the Finanzamt send me?" }));
    const done = events.at(-1)!;
    expect(done.type).toBe("done");
    expect(done).toMatchObject({ text: expect.any(String), message_id: expect.any(String), thread_id: expect.any(String) });
    expect(done.citations?.every((c) => typeof c.label === "string")).toBe(true);
  });

  it("the schema checker catches drift (sanity check of the checker itself)", () => {
    const docSchema = { $ref: "#/components/schemas/Document" };
    expect(strict.check({ id: "doc_1" }, docSchema).some((p) => p.includes("missing required"))).toBe(true);
    const detail = srv.db.liveDocuments()[0]!;
    expect(strict.check({ ...detail, invented: 1 }, docSchema)).toEqual(["$.invented: not declared by the API"]);
    expect(strict.check({ ...detail, status: "archived" }, docSchema).length).toBeGreaterThan(0);
  });
});

// ------------------------------------------------------------------------------------------------
// The phone listener: the same mock with the phone's allow-list, read from openapi.json
// ------------------------------------------------------------------------------------------------

describe("API contract on a phone (the mock as the phone listener, its allow-list from openapi.json)", () => {
  const scope = phoneScopeFromOpenApi(doc);

  /** Problems of the one request `run` makes, checked against its operation (status `expected`, default a success). */
  async function checked(name: string, run: () => Promise<unknown>, expected?: number): Promise<string[]> {
    const before = exchanges.length;
    await run().catch(() => undefined); // a refusal: its status is checked below
    const mine = exchanges.slice(before);
    if (mine.length !== 1) return [`${name}: made ${mine.length} requests`];
    const { method, url, body, response } = mine[0]!;
    const match = operationFor(method, url.pathname);
    if (!match) return [`${name}: ${method} ${url.pathname} is not an API route`];
    const problems = [...requestProblems(match.op, url, body), ...(await responseProblems(match.op, response))].map((p) => `${name} (${match.key}): ${p}`);
    if (expected !== undefined && response.status !== expected) problems.push(`${name}: expected ${expected}, the mock answered ${response.status}`);
    if (expected === undefined && !response.ok) problems.push(`${name}: the mock answered ${response.status} (${await response.clone().text()})`);
    return problems;
  }

  /** The refusal a call ends with (`null`: it succeeded). */
  async function refusal(run: () => Promise<unknown>): Promise<{ status: number; code: string | null } | null> {
    try {
      await run();
      return null;
    } catch (err) {
      if (err instanceof ApiError) return { status: err.status, code: err.code };
      throw err;
    }
  }

  it("reads the operations the API marks for a phone, and sorts a request like the API's gate", () => {
    const marked = Object.entries(doc.paths).flatMap(([template, ops]) =>
      Object.entries(ops)
        .filter(([, op]) => (op as unknown as Record<string, unknown>)["x-ordnung-phone"] === true)
        .map(([method]) => `${method.toUpperCase()} ${template}`),
    );
    expect(scope.operations.filter((op) => op.phone).map((op) => `${op.method} ${op.template}`)).toEqual(marked);
    expect(marked).toContain("POST /api/phone/pair");
    expect(marked).not.toContain("GET /api/phone");
    // both templates match and both are a phone's: `{item_id}.ics` and `{item_id}`
    expect(classifyPhoneRequest(scope, "GET", "/api/items/itm_1.ics")).toBe("phone");
    expect(classifyPhoneRequest(scope, "HEAD", "/api/documents")).toBe("phone");
    expect(classifyPhoneRequest(scope, "DELETE", "/api/drafts/drf_1/answered")).toBe("phone");
    expect(classifyPhoneRequest(scope, "DELETE", "/api/drafts/drf_1")).toBe("computer");
    expect(classifyPhoneRequest(scope, "GET", "/api/documents/doc_1/file")).toBe("computer");
    expect(classifyPhoneRequest(scope, "GET", "/api/openapi.json")).toBe("unknown");
  });

  it("answers a paired phone like the API: its health and masked numbers; what only the computer may do is refused", async () => {
    srv = createMockServer({ staticDemo: false, latency: 0, phoneScope: scope });
    const problems = [...(await checked("health", () => api.health())), ...(await checked("numbers", () => api.numbers()))];
    expect(problems).toEqual([]);
    expect(await api.health()).toMatchObject({ client: "phone", data_dir: "", demo: false, checks: [] });
    expect((await api.numbers()).masked).toBe(true);

    expect(await refusal(() => api.settings())).toEqual({ status: 403, code: "computer_only" });
    expect(await refusal(() => api.probeHealth())).toEqual({ status: 403, code: "computer_only" });
    expect(await refusal(() => api.deleteDocument("doc_1"))).toEqual({ status: 403, code: "computer_only" });
    expect(await refusal(() => api.phone())).toEqual({ status: 403, code: "computer_only" });
    expect(srv.refused).toEqual(["GET /api/settings", "GET /api/health?probe=true", "DELETE /api/documents/doc_1", "GET /api/phone"]);
  });

  it("pairs a phone like the API, and refuses a wrong, reused or locked-out code with the declared statuses", async () => {
    srv = createMockServer({ staticDemo: false, latency: 0, phoneScope: scope });
    srv.phone.removeThisPhone(); // a phone that isn't paired: only pairing answers
    expect(await refusal(() => api.dashboard())).toEqual({ status: 401, code: "phone_not_paired" });
    expect(await refusal(() => api.health())).toEqual({ status: 401, code: "phone_not_paired" });

    const problems = await checked("pairPhone (wrong code)", () => api.pairPhone({ code: "0000000000", name: "Anna's iPhone" }), 422);
    const code = srv.phone.startPairing().code; // made on the computer, typed here as shown ("K7QM2‑XD9PA")
    const typed = `${code.slice(0, 5)}\u2011${code.slice(5).toLowerCase()}`;
    problems.push(...(await checked("pairPhone", () => api.pairPhone({ code: typed, name: " Anna's\u200b iPhone " }))));
    expect(problems).toEqual([]);
    expect(srv.phone.status().devices.map((d) => d.name)).toContain("Anna's iPhone");
    expect(await refusal(() => api.dashboard())).toBeNull(); // signed in

    // the same code again: neither phone stays paired, and the computer is told
    problems.push(...(await checked("pairPhone (code used)", () => api.pairPhone({ code, name: "Someone" }), 409)));
    expect(await refusal(() => api.dashboard())).toEqual({ status: 401, code: "phone_not_paired" });
    expect(srv.phone.status().notice?.code).toBe("code_reused");

    // five wrong codes from one device lock it out of the open code, even the right one
    const next = srv.phone.startPairing().code;
    for (let i = 0; i < 5; i++) expect(await refusal(() => api.pairPhone({ code: "WRONGWRONG", name: "x" }))).toEqual({ status: 422, code: "wrong_code" });
    problems.push(...(await checked("pairPhone (locked out)", () => api.pairPhone({ code: next, name: "Anna's iPhone" }), 429)));
    expect(problems).toEqual([]);
    expect(srv.refused).toEqual([]);
  });

  it("knows every refusal code of phone access (`ordnung.phone.ERROR_STATUS`; error bodies aren't in the schema)", () => {
    const policy = readFileSync(resolve(__dirname, "../../../src/ordnung/phone/__init__.py"), "utf8");
    const table = /^ERROR_STATUS[^{]*\{([^}]*)\}/m.exec(policy)?.[1] ?? "";
    const codes = [...table.matchAll(/"(\w+)":\s*(\d{3})/g)].map((m) => m[1]);
    expect(codes.length).toBeGreaterThan(10);
    expect([...PHONE_ERROR_CODES].sort()).toEqual(codes.sort());
  });

  it("filters the privacy log by phone on the computer", async () => {
    const anna = srv.phone.addPhone({ name: "Anna's iPhone" });
    srv.db.log("item.done", "Marked “Pay the rent” done on Anna's iPhone", "item", "itm_x", { device: anna.id });
    expect(await checked("activity (one phone)", () => api.activity(20, anna.id))).toEqual([]);
    expect((await api.activity(20, anna.id)).map((a) => a.kind)).toEqual(["item.done"]);
    expect((await api.phone()).devices.find((d) => d.id === anna.id)?.recent_changes).toBe(1);
  });
});
