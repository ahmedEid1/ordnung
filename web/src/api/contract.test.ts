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
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import openapiText from "../../openapi.json?raw";
import { createMockServer, MOCK_ROUTES, type MockServer } from "@/mocks/server";
import { SchemaChecker, type OpenApiDoc, type Operation, type Schema } from "@/test/jsonSchema";
import { api, type Api } from "./endpoints";
import type { StreamEvent } from "./types";

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

  items: { run: () => api.items({ status: "open", from: "2026-09-01", to: "2026-12-31", include_undated: true, limit: 50 }) },
  createItem: { run: () => api.createItem({ kind: "task", title: "Call the bank", due_date: "2026-10-05", area: "money" }) },
  updateItem: { run: (ids) => api.updateItem(ids.item, { status: "done" }) },
  deleteItem: { run: (ids) => api.deleteItem(ids.otherItem) },
  confirmItem: { run: (ids) => api.confirmItem(ids.item) },
  itemIcsUrl: { run: (ids) => api.itemIcsUrl(ids.item), asset: true },

  contracts: { run: () => api.contracts({ status: "active" }) },
  updateContract: { run: (ids) => api.updateContract(ids.contract, { cost_amount: 19.99, cost_interval: "monthly" }) },
  parties: { run: () => api.parties() },
  party: { run: (ids) => api.party(ids.party) },
  case: { run: (ids) => api.case(ids.case) },

  timeline: { run: () => api.timeline("2026-09-01", "2026-12-31") },
  lanes: { run: () => api.lanes() },
  dashboard: { run: () => api.dashboard() },

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
  markDraftSent: { run: (ids) => api.markDraftSent(ids.draft, { channel: "registered_letter", date: "2026-09-28" }) },

  calendarIcsUrl: { run: () => api.calendarIcsUrl(), asset: true },
  calendarExported: { run: () => api.calendarExported() },

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
  "markDraftSent",
  "translateDraft",
  ...(Object.keys(CASES) as (keyof Api)[]).filter(
    (name) => !["ask", "chat", "markDraftSent", "translateDraft", "deleteDraft", "deleteDocument", "deleteItem", "deleteEverything"].includes(name),
  ),
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
