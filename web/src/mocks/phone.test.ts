/**
 * Phone access in the mock behaves as the API describes it (routes/phone.py, the phone listener's gate and the
 * design's amendments): off by default, a code that pairs one phone once, one answer for every wrong code, a
 * reused code unpairing both, lockouts, problems, notices, the demo's refusal — so Settings → Phone and the
 * pairing page can be built and tested against it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MyNumbers, PairResult, PhonePairing, PhoneStatus } from "@/api/types";
import { openApiPhoneScope } from "@/test/mockFetch";
import { createMockServer, type MockServer } from "./server";
import { checkWords, maskNumbers, maskValue, normalizeCode } from "./phone";
import {
  CODE_ALPHABET,
  PAIRING_TRIES_TOTAL,
  PHONE_ADDRESSES,
  PHONE_DEMO_MESSAGE,
  PHONE_STATIC_MESSAGE,
  THIS_PHONE_NAME,
  WRONG_CODE_MESSAGE,
} from "./data/phone";

afterEach(() => vi.useRealTimers());

const computer = (staticDemo = false) => createMockServer({ staticDemo, latency: 0 });
const phoneListener = () => createMockServer({ staticDemo: false, latency: 0, phoneScope: openApiPhoneScope() });

async function call<T>(srv: MockServer, method: string, path: string, body?: unknown): Promise<{ status: number; body: T }> {
  const res = await srv.handle(method, path, new URLSearchParams(path.split("?")[1] ?? ""), body);
  const text = await res.text();
  return { status: res.status, body: (text ? JSON.parse(text) : null) as T };
}
const status = async (srv: MockServer) => (await call<PhoneStatus>(srv, "GET", "/phone")).body;
const turnOn = (srv: MockServer, body: Record<string, unknown> = {}) => call<PhoneStatus>(srv, "PUT", "/phone", { enabled: true, ...body });
const newCode = async (srv: MockServer) => (await call<PhonePairing>(srv, "POST", "/phone/pairing")).body;

describe("Settings → Phone in the mock", () => {
  it("is off until turned on, then listens at the recommended address with a certificate of its own", async () => {
    const srv = computer();
    expect(await status(srv)).toMatchObject({
      available: true,
      unavailable_reason: null,
      enabled: false,
      listening: false,
      url: null,
      port: 8767,
      addresses: PHONE_ADDRESSES,
      problem: null,
      notice: null,
      fingerprint: null,
      pairing: null,
      devices: [],
    });
    const on = await turnOn(srv);
    expect(on.status).toBe(200);
    expect(on.body).toMatchObject({ enabled: true, listening: true, url: "https://192.168.178.23:8767", address: "192.168.178.23", subnet: "192.168.178.0/24" });
    expect(on.body.fingerprint).toMatch(/^([0-9A-F]{2} ){31}[0-9A-F]{2}$/);
    expect(on.body.ca_fingerprint).not.toBe(on.body.fingerprint);
    expect(on.body.certificate_until! > srv.db.today).toBe(true);
    expect(srv.db.state.activity[0]).toMatchObject({ kind: "phone.enabled", message: "Phone access turned on at https://192.168.178.23:8767" });

    const off = await call<PhoneStatus>(srv, "PUT", "/phone", { enabled: false });
    expect(off.body).toMatchObject({ enabled: false, listening: false, url: null, address: "192.168.178.23" });
  });

  it("refuses an address that isn't this computer's, a port out of range, and a code while off", async () => {
    const srv = computer();
    expect(await call(srv, "POST", "/phone/pairing")).toMatchObject({ status: 409, body: { code: "not_listening" } });
    expect(await turnOn(srv, { address: "10.8.0.6" })).toMatchObject({ status: 422, body: { code: "invalid" } });
    expect(await turnOn(srv, { port: 80 })).toMatchObject({ status: 422, body: { code: "invalid" } });
    expect((await turnOn(srv, { address: "192.168.0.40", port: 8800 })).body).toMatchObject({ url: "https://192.168.0.40:8800" });
  });

  it("makes a code for the QR code that pairs one phone once, and shows each step on the computer", async () => {
    const srv = computer();
    await turnOn(srv);
    const pairing = await newCode(srv);
    expect(pairing.code).toMatch(new RegExp(`^[${CODE_ALPHABET}]{10}$`));
    expect(pairing.url).toBe(`https://192.168.178.23:8767/pair#${pairing.code}`);
    expect((await status(srv)).pairing).toMatchObject({ expires_at: pairing.expires_at, opened_at: null, wrong_tries: 0, wrong_from: [] });
    expect(Date.parse(pairing.expires_at) - Date.now()).toBeGreaterThan(9 * 60_000);

    // the phone opens the page, then pairs (as it would through the phone listener)
    srv.phone.opened("192.168.178.31");
    expect((await status(srv)).pairing).toMatchObject({ opened_from: "192.168.178.31", opened_at: expect.any(String) });
    const device = srv.phone.pair({ code: pairing.code, name: "Anna's iPhone" }, "192.168.178.31");
    expect(device.check_words).toBe(checkWords(device.id));
    expect(device.check_words).toMatch(/^[a-z]+ [a-z]+$/);
    const after = await status(srv);
    expect(after.pairing).toBeNull();
    expect(after.devices).toEqual([expect.objectContaining({ id: device.id, name: "Anna's iPhone", platform: "iPhone · Safari", last_address: "192.168.178.31", recent_changes: 0 })]);
    expect(srv.db.state.activity[0]).toMatchObject({ kind: "phone.paired", data: { device: device.id, address: "192.168.178.31" } });
    // closing the dialog cancels a code; the next dialog makes a new one
    const again = await newCode(srv);
    expect(await call(srv, "DELETE", "/phone/pairing")).toEqual({ status: 204, body: null });
    expect(srv.phone.code).toBeNull();
    expect(again.code).not.toBe(pairing.code);
  });

  it("lets a code expire after ten minutes: the same answer as a wrong code", async () => {
    vi.useFakeTimers({ now: new Date("2026-10-07T08:00:00Z") });
    const srv = computer();
    await turnOn(srv);
    const { code, expires_at } = await newCode(srv);
    expect(expires_at).toBe("2026-10-07T08:10:00Z");
    vi.advanceTimersByTime(10 * 60_000);
    expect((await status(srv)).pairing).toBeNull();
    expect(() => srv.phone.pair({ code, name: "Late" })).toThrow(WRONG_CODE_MESSAGE);
  });

  it("cancels the code after many wrong ones and tells the computer where they came from", async () => {
    const srv = computer();
    await turnOn(srv);
    await newCode(srv);
    for (let i = 0; i < PAIRING_TRIES_TOTAL; i++) {
      expect(() => srv.phone.pair({ code: "AAAAAAAAAA", name: "x" }, `192.168.178.${100 + (i % 25)}`)).toThrow(WRONG_CODE_MESSAGE);
      if (i === 3) expect((await status(srv)).pairing).toMatchObject({ wrong_tries: 4, wrong_from: ["192.168.178.100", "192.168.178.101", "192.168.178.102", "192.168.178.103"] });
    }
    const after = await status(srv);
    expect(after.pairing).toBeNull();
    expect(after.notice).toMatchObject({ code: "pairing_stopped", addresses: expect.arrayContaining(["192.168.178.100", "192.168.178.124"]) });
    expect(after.notice!.detail).toMatch(/192\.168\.178\.100/);
  });

  it("removes a phone, renames a second one with the same name, strips invisible characters, and starts over", async () => {
    const srv = computer();
    await turnOn(srv);
    const anna = srv.phone.pair({ code: (await newCode(srv)).code, name: "Anna\u202e's iPhone\u0007" });
    const twin = srv.phone.pair({ code: (await newCode(srv)).code, name: "Anna's iPhone" });
    expect([anna.name, twin.name]).toEqual(["Anna's iPhone", "Anna's iPhone (2)"]);
    const removed = await call<PhoneStatus>(srv, "DELETE", `/phone/devices/${anna.id}`);
    expect(removed.body.devices.map((d) => d.id)).toEqual([twin.id]);
    expect(await call(srv, "DELETE", `/phone/devices/${anna.id}`)).toMatchObject({ status: 404 });
    const reset = await call<PhoneStatus>(srv, "POST", "/phone/reset");
    expect(reset.body).toMatchObject({ enabled: false, listening: false, devices: [], fingerprint: null, address: null });
    expect(srv.db.state.activity.map((a) => a.kind)).toContain("phone.removed");
  });

  it("forgets the phones when the address or port changes: their sign-in belonged to the old one", async () => {
    const srv = computer();
    const first = (await turnOn(srv)).body;
    srv.phone.addPhone({ name: "Anna's iPhone" });
    const moved = (await turnOn(srv, { address: "192.168.0.40" })).body;
    expect(moved.devices).toEqual([]);
    expect(moved.ca_fingerprint).not.toBe(first.ca_fingerprint);
    srv.phone.addPhone({ name: "Anna's iPhone" });
    expect((await turnOn(srv, { port: 8768 })).body.devices).toEqual([]);
    srv.phone.addPhone({ name: "Anna's iPhone" });
    expect((await turnOn(srv)).body.devices).toHaveLength(1); // the same address and port keep them
  });

  it("pauses on a problem and listens again once it is dealt with", async () => {
    const srv = computer();
    await turnOn(srv);
    srv.phone.setProblem("port_busy");
    expect(await status(srv)).toMatchObject({ enabled: true, listening: false, url: null, problem: { code: "port_busy", detail: "Another program uses port 8767." } });
    expect((await turnOn(srv, { port: 8768 })).body).toMatchObject({ listening: true, problem: null, port: 8768 });

    srv.phone.setProblem("other_network");
    expect((await turnOn(srv)).body.listening).toBe(false);
    expect((await turnOn(srv, { home_network: true })).body).toMatchObject({ listening: true, problem: null });

    srv.phone.setProblem("address_gone");
    const gone = await status(srv);
    expect(gone.addresses.map((a) => a.address)).toEqual(["192.168.0.40"]);
    expect((await turnOn(srv, { address: "192.168.0.40" })).body).toMatchObject({ listening: true, url: "https://192.168.0.40:8768" });

    srv.phone.setProblem("no_network");
    expect(await turnOn(srv)).toMatchObject({ status: 409, body: { code: "no_network" } });
  });

  it("can't be turned on in the demo, nor in the online demo", async () => {
    const online = computer(true);
    expect(await status(online)).toMatchObject({ available: false, unavailable_reason: PHONE_STATIC_MESSAGE, addresses: [] });
    expect(await turnOn(online)).toMatchObject({ status: 409, body: { code: "unavailable", detail: PHONE_STATIC_MESSAGE } });
    const demo = computer();
    demo.phone.makeUnavailable();
    expect(await status(demo)).toMatchObject({ available: false, unavailable_reason: PHONE_DEMO_MESSAGE });
    for (const [method, path] of [
      ["PUT", "/phone"],
      ["POST", "/phone/pairing"],
      ["POST", "/phone/reset"],
    ] as const) {
      expect(await call(demo, method, path, { enabled: true })).toMatchObject({ status: 409, body: { code: "unavailable", detail: PHONE_DEMO_MESSAGE } });
    }
  });

  it("goes with Delete everything", async () => {
    const srv = computer();
    srv.db.state.health = { ...srv.db.state.health, demo: false };
    await turnOn(srv);
    srv.phone.addPhone();
    expect(await call(srv, "DELETE", "/data", { confirm: "DELETE" })).toMatchObject({ status: 200, body: { removed: expect.arrayContaining(["phone"]) } });
    expect(await status(srv)).toMatchObject({ enabled: false, devices: [], fingerprint: null });
  });

  it("answers pairing on the computer's own listener with not_phone", async () => {
    expect(await call(computer(), "POST", "/phone/pair", { code: "K7QM2XD9PA", name: "x" })).toMatchObject({ status: 404, body: { code: "not_phone" } });
  });
});

describe("the phone listener in the mock", () => {
  it("answers its paired phone, and refuses the computer's operations, listing them", async () => {
    const srv = phoneListener();
    expect(srv.phone.thisPhone()?.name).toBe(THIS_PHONE_NAME);
    expect((await call(srv, "GET", "/dashboard")).status).toBe(200);
    for (const [method, path] of [
      ["GET", "/settings"],
      ["GET", "/folder"],
      ["DELETE", "/documents/doc_tax"],
      ["GET", "/documents/doc_tax/file"],
      ["POST", "/backup"],
      ["GET", "/phone"],
      ["GET", "/activity"],
      ["GET", "/openapi.json"],
    ] as const) {
      expect(await call(srv, method, path), `${method} ${path}`).toMatchObject({ status: 403, body: { code: "computer_only" } });
    }
    expect(srv.refused).toEqual([
      "GET /api/settings",
      "GET /api/folder",
      "DELETE /api/documents/doc_tax",
      "GET /api/documents/doc_tax/file",
      "POST /api/backup",
      "GET /api/phone",
      "GET /api/activity",
      "GET /api/openapi.json",
    ]);
    // undoing "answered" is a phone's; deleting a letter you wrote isn't
    const sent = srv.db.state.drafts.find((d) => d.status === "sent")!.id;
    expect((await call(srv, "DELETE", `/drafts/${sent}/answered`)).status).not.toBe(403);
    expect((await call(srv, "DELETE", `/drafts/${sent}`)).status).toBe(403);
    expect(srv.refused.slice(-1)).toEqual([`DELETE /api/drafts/${sent}`]);
  });

  it("lets a phone that isn't paired do nothing but pair, then signs it in", async () => {
    const srv = phoneListener();
    srv.phone.removeThisPhone();
    expect(await call(srv, "GET", "/health")).toMatchObject({ status: 401, body: { code: "phone_not_paired" } });
    expect(await call(srv, "POST", "/phone/pair", { code: "nothing-open", name: "x" })).toMatchObject({ status: 422, body: { code: "wrong_code", detail: WRONG_CODE_MESSAGE } });
    const { code } = srv.phone.startPairing();
    const paired = await call<PairResult>(srv, "POST", "/phone/pair", { code: code.toLowerCase(), name: "Sam's Pixel" });
    expect(paired).toEqual({ status: 200, body: { name: "Sam's Pixel", check_words: expect.stringMatching(/^[a-z]+ [a-z]+$/) } });
    expect(srv.phone.thisPhone()?.check_words).toBe(paired.body.check_words);
    expect((await call(srv, "GET", "/health")).status).toBe(200);
    expect(srv.refused).toEqual([]);
  });

  it("shows only the last 4 characters of your numbers and of the IBAN", async () => {
    const srv = phoneListener();
    srv.db.state.profile = { ...srv.db.state.profile, iban: "DE89 3704 0044 0532 0130 00" };
    const numbers = (await call<MyNumbers>(srv, "GET", "/numbers")).body;
    expect(numbers.masked).toBe(true);
    expect(numbers.about_you.length).toBeGreaterThan(0);
    for (const n of numbers.about_you) expect(n.value === n.display && n.value === n.copy_value && /^(•••• )?\S{1,4}$/.test(n.value)).toBe(true);
    expect((await call<{ iban: string }>(srv, "GET", "/profile")).body.iban).toBe("•••• 3000");
    // the computer sees them whole
    const full = (await call<MyNumbers>(computer(), "GET", "/numbers")).body;
    expect(full.masked).toBe(false);
    expect(maskNumbers(full).about_you.map((n) => n.value)).toEqual(numbers.about_you.map((n) => n.value));
  });
});

describe("helpers", () => {
  it("reads a typed code as the API does, and masks a number to its last 4 characters", () => {
    expect(normalizeCode("k7qm2\u2011xd9pa")).toBe("K7QM2XD9PA");
    expect(normalizeCode("K7QM2 - XD9PA")).toBe("K7QM2XD9PA");
    expect(normalizeCode("OIL")).toBe("011");
    expect(maskValue("12 345 678 901")).toBe("•••• 8901");
    expect(maskValue("123")).toBe("123");
  });
});
