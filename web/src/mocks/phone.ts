/**
 * Phone access in the mock, as `src/ordnung/api/routes/phone.py` and the phone listener's gate answer it.
 *
 * - **The computer's side** ({@link MockPhoneAccess}): Settings → Phone turns it on at one of
 *   {@link PHONE_ADDRESSES}, makes pairing codes, lists and removes phones, starts over. `?mock=1` pretends a
 *   phone can reach it; the static demo can't ({@link PHONE_STATIC_MESSAGE}).
 * - **A phone's side**: a mock server made with a `phoneScope` is the phone listener (`createMockServer` in
 *   `./server`). {@link phoneGate} answers every request first, as the API's gate does: without a paired phone
 *   only pairing works (401 `phone_not_paired`); a request outside the phone's allow-list (`x-ordnung-phone` in
 *   `openapi.json`, read by {@link phoneScopeFromOpenApi}) gets 403 `computer_only` and is listed in
 *   `srv.refused`. Health then says `client: "phone"` ({@link phoneHealth}) and the numbers show only their last
 *   4 characters ({@link maskNumbers}).
 * - **What a test drives**: a phone opening the pairing page ({@link MockPhoneAccess.opened}), pairing with the
 *   open code ({@link MockPhoneAccess.pair}, {@link MockPhoneAccess.code}), a phone paired before
 *   ({@link MockPhoneAccess.addPhone}), problems, notices and the demo's refusal.
 *
 * Its times are the real clock's, as the API's are (`clock.real_now_iso`): a code's countdown runs against
 * `Date.now()`, so fake timers move it.
 */
import { addDays, format, parseISO } from "date-fns";
import type {
  AddressChoice,
  Health,
  MyNumber,
  MyNumbers,
  PairRequest,
  PhoneAccessChange,
  PhoneDevice,
  PhoneErrorCode,
  PhoneNotice,
  PhoneNoticeCode,
  PhonePairing,
  PhoneProblem,
  PhoneProblemCode,
  PhoneStatus,
  Profile,
} from "@/api/types";
import type { MockDb } from "./db";
import {
  CERTIFICATE_DAYS,
  CHECK_ADJECTIVES,
  CHECK_NOUNS,
  CODE_ALPHABET,
  CODE_LENGTH,
  CODE_USED_MESSAGE,
  COMPUTER_ONLY_MESSAGE,
  INVALID_ADDRESS_MESSAGE,
  INVALID_PORT_MESSAGE,
  MAX_PHONES,
  NO_NETWORK_MESSAGE,
  NO_SUCH_PHONE_MESSAGE,
  NOT_LISTENING_MESSAGE,
  NOTICE_MS,
  PAIRING_TRIES_PER_CLIENT,
  PAIRING_TRIES_TOTAL,
  PAIRING_TTL_MS,
  PHONE_ADDRESSES,
  PHONE_DEFAULT_PORT,
  PHONE_DEMO_MESSAGE,
  PHONE_NOT_PAIRED_MESSAGE,
  PHONE_OFF_MESSAGE,
  PHONE_PLATFORM,
  PHONE_STATIC_MESSAGE,
  THIS_PHONE_ADDRESS,
  THIS_PHONE_NAME,
  TOO_MANY_PHONES_MESSAGE,
  TOO_MANY_TRIES_MESSAGE,
  WRONG_CODE_MESSAGE,
  noticeDetail,
  problemDetail,
} from "./data/phone";

// ------------------------------------------------------------------------------------------------
// The phone's allow-list (read from openapi.json by the tests; the app's bundle never carries it)
// ------------------------------------------------------------------------------------------------

/** One API operation and whether a paired phone may call it. */
export interface PhoneOperation {
  method: string;
  /** The OpenAPI path template (`/api/items/{item_id}.ics`). */
  template: string;
  phone: boolean;
}

/** The phone's allow-list: every API operation, each marked as the API marks it (`x-ordnung-phone`). */
export interface PhoneScope {
  operations: readonly PhoneOperation[];
}

/** The OpenAPI extension the API marks each phone operation with (`ordnung.phone.scope.OPENAPI_MARK`). */
export const PHONE_MARK = "x-ordnung-phone";

const HTTP_METHODS = new Set(["get", "put", "post", "delete", "patch", "head", "options", "trace"]);

/** The allow-list from an OpenAPI document (`web/openapi.json`). */
export function phoneScopeFromOpenApi(doc: { paths: Record<string, Record<string, unknown>> }): PhoneScope {
  const operations: PhoneOperation[] = [];
  for (const [template, ops] of Object.entries(doc.paths)) {
    for (const [method, op] of Object.entries(ops)) {
      if (!HTTP_METHODS.has(method)) continue;
      operations.push({ method: method.toUpperCase(), template, phone: (op as Record<string, unknown> | null)?.[PHONE_MARK] === true });
    }
  }
  return { operations };
}

const compiled = new WeakMap<PhoneScope, { method: string; re: RegExp; phone: boolean }[]>();

function templateRegex(template: string): RegExp {
  const parts = template.split(/(\{[^}]+\})/).map((part) => (part.startsWith("{") ? "[^/]+" : part.replace(/[.*+?^$()|[\]\\]/g, "\\$&")));
  return new RegExp(`^${parts.join("")}$`);
}

/**
 * How the API's gate sorts a request (`ordnung.phone.scope.classify`): HEAD counts as GET; a path several
 * operations match (`/api/items/x.ics`) is a phone request only when every one of them is; none is "unknown".
 * `path` is the `/api/…` path without the query.
 */
export function classifyPhoneRequest(scope: PhoneScope, method: string, path: string): "phone" | "computer" | "unknown" {
  let ops = compiled.get(scope);
  if (!ops) {
    ops = scope.operations.map((op) => ({ method: op.method, re: templateRegex(op.template), phone: op.phone }));
    compiled.set(scope, ops);
  }
  const wanted = method.toUpperCase() === "HEAD" ? "GET" : method.toUpperCase();
  const found = ops.filter((op) => op.method === wanted && op.re.test(path)).map((op) => op.phone);
  if (!found.length) return "unknown";
  return found.every(Boolean) ? "phone" : "computer";
}

// ------------------------------------------------------------------------------------------------
// What a phone gets that the computer doesn't
// ------------------------------------------------------------------------------------------------

/** `/api/health` on a phone: `client: "phone"`, never the data folder, Claude's path or the checks — and never the demo. */
export function phoneHealth(health: Health): Health {
  return { ...health, client: "phone", demo: false, data_dir: "", claude: { ...health.claude, path: null }, checks: [] };
}

/** A number on a phone: only its last 4 characters ("•••• 3000"); the full one is on the computer. */
export function maskValue(value: string): string {
  const compact = value.replace(/\s+/g, "");
  return compact.length <= 4 ? compact : `•••• ${compact.slice(-4)}`;
}

function maskNumber(n: MyNumber): MyNumber {
  const shown = maskValue(n.value);
  return { ...n, value: shown, display: shown, copy_value: shown };
}

/** *My numbers* on a phone: your numbers masked (an organisation's own registry and bank numbers stay). */
export function maskNumbers(numbers: MyNumbers): MyNumbers {
  const references = <T extends { references: MyNumber[] }>(x: T): T => ({ ...x, references: x.references.map(maskNumber) });
  return {
    ...numbers,
    masked: true,
    about_you: numbers.about_you.map(maskNumber),
    documents: numbers.documents.map((d) => ({ ...d, number: d.number ? maskNumber(d.number) : d.number })),
    organisations: numbers.organisations.map((o) => ({ ...o, numbers: o.numbers.map(maskNumber), open_cases: o.open_cases.map(references) })),
    open_cases: numbers.open_cases.map(references),
  };
}

/** The profile on a phone: the IBAN masked (the address stays, letters written on the phone need it). */
export function maskProfile(profile: Profile): Profile {
  return profile.iban ? { ...profile, iban: maskValue(profile.iban) } : profile;
}

// ------------------------------------------------------------------------------------------------
// Refusals
// ------------------------------------------------------------------------------------------------

/** A refusal shaped like the API's: `{detail, code}` with the code's status. */
export class PhoneRefusal extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code: PhoneErrorCode | null,
  ) {
    super(message);
  }
}

const refuse = (status: number, code: PhoneErrorCode | null, message: string) => new PhoneRefusal(status, message, code);

// ------------------------------------------------------------------------------------------------
// Phone access (the computer's side) and pairing (the phone's)
// ------------------------------------------------------------------------------------------------

interface Certificate {
  fingerprint: string;
  ca_fingerprint: string;
  ca_made_at: string;
  certificate_until: string;
  certificate_changed_at: string;
}

interface OpenCode {
  code: string;
  expiresAt: number;
  openedAt: string | null;
  openedFrom: string | null;
  wrongTries: number;
  wrongFrom: string[];
  perClient: Map<string, number>;
}

type DeviceRecord = Omit<PhoneDevice, "recent_changes">;

/** Privacy-log entries about a phone rather than changes it made. */
const ABOUT_A_PHONE = new Set(["phone.paired", "phone.removed"]);

/** Real time, as the API stamps phone access (seconds, `Z`). */
const isoAt = (ms: number) => new Date(ms).toISOString().replace(/\.\d+Z$/, "Z");
const nowIso = () => isoAt(Date.now());

let deviceSeq = 0;
const newDeviceId = () => `phn_${Date.now().toString(36)}${(++deviceSeq).toString(36).padStart(3, "0")}`;

/** A small string hash (FNV-1a), for the mock's fingerprints and check words. */
function hash(text: string, seed = 0x811c9dc5): number {
  let h = seed >>> 0;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

/** A SHA-256-shaped fingerprint as upper-case byte pairs ("F2 08 81 E8 …"). */
function fakeFingerprint(seed: string): string {
  const bytes: string[] = [];
  let h = hash(seed);
  for (let i = 0; i < 32; i++) {
    h = hash(`${seed}:${i}`, h);
    bytes.push((h & 0xff).toString(16).toUpperCase().padStart(2, "0"));
  }
  return bytes.join(" ");
}

/** The two words both screens show for a phone ("amber tulip"). */
export function checkWords(deviceId: string): string {
  const h = hash(deviceId);
  return `${CHECK_ADJECTIVES[h % CHECK_ADJECTIVES.length]} ${CHECK_NOUNS[(h >>> 8) % CHECK_NOUNS.length]}`;
}

/** A typed code as the API compares it: upper case, O→0, I/L→1, no spaces or dashes. */
export function normalizeCode(raw: string): string {
  return raw
    .toUpperCase()
    .replace(/O/g, "0")
    .replace(/[IL]/g, "1")
    .replace(/[\s\-\u2011]/g, "");
}

function randomCode(): string {
  let code = "";
  for (let i = 0; i < CODE_LENGTH; i++) code += CODE_ALPHABET[Math.floor(Math.random() * CODE_ALPHABET.length)];
  return code;
}

/** A phone's name without control or invisible formatting characters (bidi controls, zero-width). */
function cleanName(raw: string): string {
  return raw.replace(/[\p{Cc}\p{Cf}]/gu, "").replace(/\s+/g, " ").trim().slice(0, 40) || "Phone";
}

/** Settings → Phone and pairing, kept in memory per mock server (`srv.phone`). */
export class MockPhoneAccess {
  /** Whether phone access can be used here, and why not (the demo, the static demo). */
  available: boolean;
  unavailableReason: string | null;
  enabled = false;
  address: string | null = null;
  port = PHONE_DEFAULT_PORT;
  /** This computer's addresses on home networks now. */
  addresses: AddressChoice[];
  problem: PhoneProblem | null = null;
  notice: PhoneNotice | null = null;
  certificate: Certificate | null = null;
  devices: DeviceRecord[] = [];
  /** The phone a phone-listener mock answers for (its device id): null when it isn't paired (any more). */
  self: string | null = null;
  private open: OpenCode | null = null;
  /** Codes that paired a phone, until they would have expired: a second use unpairs both. */
  private consumed = new Map<string, { deviceId: string; until: number }>();

  constructor(
    private readonly db: MockDb,
    opts: { staticDemo: boolean; listener: "computer" | "phone" },
  ) {
    this.available = !opts.staticDemo;
    this.unavailableReason = opts.staticDemo ? PHONE_STATIC_MESSAGE : null;
    this.addresses = opts.staticDemo ? [] : PHONE_ADDRESSES.map((a) => ({ ...a }));
    if (opts.listener === "phone") {
      // the phone listener exists only while phone access is on; its phone paired before the page opened
      this.enabled = true;
      this.address = this.addresses.find((a) => a.recommended)?.address ?? null;
      this.certificate = this.makeCertificate(this.address ?? "");
      this.self = this.addPhone({ name: THIS_PHONE_NAME }).id;
    }
  }

  // -- what Settings → Phone shows ---------------------------------------------------------------

  /** `GET /api/phone`. */
  status(): PhoneStatus {
    this.expire();
    const listening = this.listening;
    const subnet = this.addresses.find((a) => a.address === this.address)?.subnet ?? (this.address ? `${this.address.replace(/\.\d+$/, ".0")}/24` : null);
    const open = listening ? this.open : null;
    return {
      available: this.available,
      unavailable_reason: this.available ? null : (this.unavailableReason ?? PHONE_DEMO_MESSAGE),
      enabled: this.enabled,
      listening,
      url: listening ? this.url : null,
      address: this.address,
      subnet,
      port: this.port,
      addresses: this.available ? this.addresses.map((a) => ({ ...a })) : [],
      problem: this.enabled ? this.problem : null,
      notice: this.notice,
      fingerprint: this.certificate?.fingerprint ?? null,
      ca_fingerprint: this.certificate?.ca_fingerprint ?? null,
      ca_made_at: this.certificate?.ca_made_at ?? null,
      certificate_until: this.certificate?.certificate_until ?? null,
      certificate_changed_at: this.certificate?.certificate_changed_at ?? null,
      pairing: open
        ? {
            expires_at: isoAt(open.expiresAt),
            opened_at: open.openedAt,
            opened_from: open.openedFrom,
            wrong_tries: open.wrongTries,
            wrong_from: [...open.wrongFrom],
          }
        : null,
      devices: this.devices.map((d) => ({ ...d, recent_changes: this.recentChanges(d.id) })),
    };
  }

  /** Phones can reach it now. */
  get listening(): boolean {
    return this.available && this.enabled && !this.problem && this.address !== null;
  }

  /** "https://192.168.178.23:8767". */
  get url(): string {
    return `https://${this.address}:${this.port}`;
  }

  /** The open pairing code (what the QR code carries): a test types it on the phone's side. */
  get code(): string | null {
    this.expire();
    return this.open?.code ?? null;
  }

  // -- the computer's operations -----------------------------------------------------------------

  /** `PUT /api/phone`. */
  change(body: PhoneAccessChange): PhoneStatus {
    if (!this.available) throw refuse(409, "unavailable", this.unavailableReason ?? PHONE_DEMO_MESSAGE);
    if (!body.enabled) {
      if (this.enabled) {
        this.enabled = false;
        this.open = null;
        this.db.log("phone.disabled", "Phone access turned off");
      }
      return this.status();
    }
    const port = body.port ?? this.port;
    if (!Number.isInteger(port) || port < 1024 || port > 65535) throw refuse(422, "invalid", INVALID_PORT_MESSAGE);
    if (!this.addresses.length) throw refuse(409, "no_network", NO_NETWORK_MESSAGE);
    const address = body.address ?? this.address ?? this.addresses.find((a) => a.recommended)?.address ?? this.addresses[0]!.address;
    if (!this.addresses.some((a) => a.address === address)) throw refuse(422, "invalid", INVALID_ADDRESS_MESSAGE);

    const movedAddress = this.address !== null && this.address !== address;
    const movedPort = this.port !== port;
    if (this.problem?.code === "port_busy" && movedPort) this.problem = null;
    if (this.problem?.code === "address_gone" && movedAddress) this.problem = null;
    if (this.problem?.code === "other_network" && body.home_network) this.problem = null;
    // a phone's sign-in belongs to the old address and port: those phones pair again
    if ((movedAddress || movedPort) && this.devices.length) {
      for (const d of this.devices) this.db.log("phone.removed", `Removed ${d.name}: the computer's address changed`, null, null, { device: d.id, by: "address_changed" });
      this.devices = [];
      this.self = null;
    }
    if (movedAddress || movedPort) this.open = null;
    // the certificate (and the authority that issues it) names one address: a new address, a new one
    if (!this.certificate || movedAddress) this.certificate = this.makeCertificate(address);
    const changed = !this.enabled || movedAddress || movedPort;
    this.enabled = true;
    this.address = address;
    this.port = port;
    if (changed) this.db.log("phone.enabled", `Phone access turned on at ${this.url}`, null, null, { address, port });
    return this.status();
  }

  /** `POST /api/phone/pairing`: a new code replaces an open one. */
  startPairing(): PhonePairing {
    if (!this.available) throw refuse(409, "unavailable", this.unavailableReason ?? PHONE_DEMO_MESSAGE);
    if (!this.listening) throw refuse(409, "not_listening", NOT_LISTENING_MESSAGE);
    if (this.devices.length >= MAX_PHONES) throw refuse(409, "too_many_phones", TOO_MANY_PHONES_MESSAGE);
    const code = randomCode();
    const expiresAt = Date.now() + PAIRING_TTL_MS;
    this.open = { code, expiresAt, openedAt: null, openedFrom: null, wrongTries: 0, wrongFrom: [], perClient: new Map() };
    return { url: `${this.url}/pair#${code}`, code, expires_at: isoAt(expiresAt) };
  }

  /** `DELETE /api/phone/pairing`. */
  cancelPairing(): void {
    this.open = null;
  }

  /** `DELETE /api/phone/devices/{id}`: signed out at once. */
  remove(id: string, by: "computer" | "unused" = "computer"): PhoneStatus {
    const device = this.devices.find((d) => d.id === id);
    if (!device) throw refuse(404, null, NO_SUCH_PHONE_MESSAGE);
    this.dropDevice(device, by);
    return this.status();
  }

  /** `POST /api/phone/reset`: off, no phones, a new certificate next time. */
  reset(): PhoneStatus {
    if (!this.available) throw refuse(409, "unavailable", this.unavailableReason ?? PHONE_DEMO_MESSAGE);
    for (const d of [...this.devices]) this.dropDevice(d, "reset");
    if (this.enabled) this.db.log("phone.disabled", "Phone access turned off: it starts over");
    this.forget();
    return this.status();
  }

  /** Delete everything (and `reset`): nothing of phone access stays, no log. */
  forget(): void {
    this.enabled = false;
    this.address = null;
    this.port = PHONE_DEFAULT_PORT;
    this.problem = null;
    this.notice = null;
    this.certificate = null;
    this.devices = [];
    this.self = null;
    this.open = null;
    this.consumed.clear();
  }

  // -- a phone's side ----------------------------------------------------------------------------

  /** A phone that isn't paired opened the pairing page (`GET /pair` as a page load) while a code is open. */
  opened(from = THIS_PHONE_ADDRESS): void {
    this.expire();
    if (!this.open || this.open.openedAt) return;
    this.open.openedAt = nowIso();
    this.open.openedFrom = from;
  }

  /**
   * `POST /api/phone/pair` from a phone at `from`: the open code pairs one phone, once. One answer for a wrong,
   * expired or missing code; a second use of a code unpairs the phone that used it first.
   */
  pair(body: PairRequest, from = THIS_PHONE_ADDRESS, platform = PHONE_PLATFORM): PhoneDevice {
    this.expire();
    if (!this.listening) throw refuse(409, "unavailable", PHONE_OFF_MESSAGE);
    const open = this.open;
    if (open && (open.perClient.get(from) ?? 0) >= PAIRING_TRIES_PER_CLIENT) throw refuse(429, "too_many", TOO_MANY_TRIES_MESSAGE);
    const code = normalizeCode(body.code);
    const used = this.consumed.get(code);
    if (used) {
      this.consumed.delete(code);
      const first = this.devices.find((d) => d.id === used.deviceId);
      if (first) this.dropDevice(first, "code_reused");
      this.notice = { code: "code_reused", detail: noticeDetail("code_reused", []), at: nowIso(), addresses: [...new Set([first?.last_address, from].filter((a): a is string => Boolean(a)))] };
      throw refuse(409, "code_used", CODE_USED_MESSAGE);
    }
    if (!open || code !== open.code) {
      if (open) this.wrongTry(open, from);
      throw refuse(422, "wrong_code", WRONG_CODE_MESSAGE);
    }
    if (this.devices.length >= MAX_PHONES) throw refuse(409, "too_many_phones", TOO_MANY_PHONES_MESSAGE);
    const device = this.addPhone({ name: this.uniqueName(cleanName(body.name)), platform, last_address: from });
    this.consumed.set(code, { deviceId: device.id, until: open.expiresAt });
    this.open = null;
    this.db.log("phone.paired", `Paired ${device.name} (${device.platform}) from ${from}`, null, null, { device: device.id, address: from });
    return device;
  }

  /** A phone paired before (no code): `{name, platform, active, last_seen_at, …}` as given. */
  addPhone(fields: Partial<DeviceRecord> = {}): PhoneDevice {
    const id = fields.id ?? newDeviceId();
    const now = nowIso();
    const record: DeviceRecord = {
      id,
      name: fields.name ?? "Phone",
      platform: fields.platform ?? PHONE_PLATFORM,
      check_words: fields.check_words ?? checkWords(id),
      paired_at: fields.paired_at ?? now,
      last_seen_at: fields.last_seen_at ?? now,
      last_address: fields.last_address ?? THIS_PHONE_ADDRESS,
      active: fields.active ?? false,
    };
    this.devices.push(record);
    return { ...record, recent_changes: this.recentChanges(id) };
  }

  /** The computer removed the phone this phone-listener mock answers for: its next request gets 401. */
  removeThisPhone(): void {
    const me = this.devices.find((d) => d.id === this.self);
    if (me) this.dropDevice(me, "computer");
    this.self = null;
  }

  /** The device the phone listener answers for, while it is paired. */
  thisPhone(): DeviceRecord | null {
    return this.devices.find((d) => d.id === this.self) ?? null;
  }

  // -- what a test sets --------------------------------------------------------------------------

  /** Phone access on but paused (`null`: listening again). `address_gone` and `no_network` take the addresses away too. */
  setProblem(code: PhoneProblemCode | null): void {
    if (!this.available) return;
    this.addresses = PHONE_ADDRESSES.map((a) => ({ ...a }));
    if (code === "no_network") this.addresses = [];
    if (code === "address_gone") this.addresses = this.addresses.filter((a) => a.address !== this.address);
    this.problem = code ? { code, detail: problemDetail(code, this.address, this.port) } : null;
  }

  /** A notice in the danger tone (it goes after {@link NOTICE_MS}). */
  setNotice(code: PhoneNoticeCode, addresses: string[] = [], name?: string): void {
    this.notice = { code, detail: noticeDetail(code, addresses, name), at: nowIso(), addresses };
  }

  /** Phone access can't be used here (`ordnung demo` by default). */
  makeUnavailable(reason = PHONE_DEMO_MESSAGE): void {
    this.available = false;
    this.unavailableReason = reason;
    this.forget();
  }

  // -- inside ------------------------------------------------------------------------------------

  private wrongTry(open: OpenCode, from: string) {
    open.wrongTries += 1;
    open.perClient.set(from, (open.perClient.get(from) ?? 0) + 1);
    if (!open.wrongFrom.includes(from)) open.wrongFrom.push(from);
    if (open.wrongTries < PAIRING_TRIES_TOTAL) return;
    this.open = null;
    this.notice = { code: "pairing_stopped", detail: noticeDetail("pairing_stopped", open.wrongFrom), at: nowIso(), addresses: [...open.wrongFrom] };
    this.db.log("phone.pairing_stopped", `${open.wrongTries} wrong pairing codes were typed on your network; the code was cancelled`, null, null, { addresses: [...open.wrongFrom] });
  }

  private dropDevice(device: DeviceRecord, by: "computer" | "unused" | "reset" | "code_reused" | "token_reuse") {
    this.devices = this.devices.filter((d) => d.id !== device.id);
    if (this.self === device.id) this.self = null;
    const why: Record<typeof by, string> = {
      computer: "",
      unused: ": not used for 30 days",
      reset: ": phone access started over",
      code_reused: ": its pairing code was used twice",
      token_reuse: ": its sign-in was used from two places",
    };
    this.db.log("phone.removed", `Removed ${device.name}${why[by]}`, null, null, { device: device.id, by });
  }

  private uniqueName(name: string): string {
    const taken = new Set(this.devices.map((d) => d.name));
    if (!taken.has(name)) return name;
    let n = 2;
    while (taken.has(`${name} (${n})`)) n += 1;
    return `${name} (${n})`;
  }

  /** A new authority for `address` and the certificate it issues. */
  private makeCertificate(address: string): Certificate {
    const now = nowIso();
    const fingerprint = fakeFingerprint(`leaf:${address}:${now}`);
    this.db.log("phone.certificate", `New certificate for phone access (${fingerprint.split(" ").slice(0, 4).join(" ")} …)`, null, null, { fingerprint, made: "ca" });
    return {
      fingerprint,
      ca_fingerprint: fakeFingerprint(`ca:${address}:${now}`),
      ca_made_at: now,
      certificate_until: format(addDays(new Date(), CERTIFICATE_DAYS), "yyyy-MM-dd"),
      certificate_changed_at: now,
    };
  }

  /** The changes a phone made in the 30 days up to the mock's today (the privacy log's entries naming it). */
  private recentChanges(id: string): number {
    const since = format(addDays(parseISO(this.db.today), -30), "yyyy-MM-dd");
    return this.db.state.activity.filter((a) => a.data?.device === id && a.ts.slice(0, 10) >= since && !ABOUT_A_PHONE.has(a.kind)).length;
  }

  /** A code past its end is gone; a notice goes after ten minutes; a used code is forgotten when it would have ended. */
  private expire() {
    const now = Date.now();
    if (this.open && now >= this.open.expiresAt) this.open = null;
    if (this.notice && now - Date.parse(this.notice.at) >= NOTICE_MS) this.notice = null;
    for (const [code, used] of this.consumed) if (now >= used.until) this.consumed.delete(code);
  }
}

// ------------------------------------------------------------------------------------------------
// The phone listener's gate (before routing)
// ------------------------------------------------------------------------------------------------

/**
 * What the API's gate answers a phone before any route runs (`null`: admitted). `path` is without `/api` and the
 * query, as the mock server routes it; refused requests are added to `refused` as `"GET /api/settings"`.
 */
export function phoneGate(phone: MockPhoneAccess, scope: PhoneScope, method: string, path: string, query: URLSearchParams, refused: string[]): PhoneRefusal | null {
  const m = method.toUpperCase();
  if (m === "POST" && path === "/phone/pair") return null; // the one operation open before pairing
  const me = phone.thisPhone();
  if (!me) return refuse(401, "phone_not_paired", PHONE_NOT_PAIRED_MESSAGE);
  const probe = path === "/health" && query.has("probe");
  if (probe || classifyPhoneRequest(scope, m, `/api${path}`) !== "phone") {
    refused.push(`${m} /api${path}${probe ? `?probe=${query.get("probe")}` : ""}`);
    return refuse(403, "computer_only", COMPUTER_ONLY_MESSAGE);
  }
  me.last_seen_at = nowIso();
  me.last_address = THIS_PHONE_ADDRESS;
  return null;
}
