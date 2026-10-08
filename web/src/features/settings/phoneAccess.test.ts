/**
 * Settings → Phone's small rules: the code as people read it, the countdown, the line under the switch, when a new
 * certificate is news, the firewall's narrowest rules, and the phones the trust step is offered on.
 */
import { describe, expect, it } from "vitest";
import type { PhoneDevice } from "@/api/types";
import {
  accessLine,
  certificateNewsFor,
  computerOs,
  countdown,
  fingerprintParts,
  firewallCommands,
  formatPairingCode,
  homeSubnet,
  newDevice,
  nextPort,
  trustStepPlatform,
} from "./phoneAccess";

const device = (fields: Partial<PhoneDevice> = {}): PhoneDevice => ({
  id: "phn_1",
  name: "Anna's iPhone",
  platform: "iPhone · Safari",
  check_words: "amber tulip",
  paired_at: "2026-10-01T08:00:00Z",
  last_seen_at: null,
  last_address: null,
  active: false,
  recent_changes: 0,
  ...fields,
});

const UA = {
  iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1",
  iphoneChrome: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/138.0.7204.156 Mobile/15E148 Safari/604.1",
  ipadDesktop: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15",
  androidChrome: "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36",
  samsung: "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/27.0 Chrome/125.0.0.0 Mobile Safari/537.36",
  firefoxAndroid: "Mozilla/5.0 (Android 15; Mobile; rv:140.0) Gecko/140.0 Firefox/140.0",
  webview: "Mozilla/5.0 (Linux; Android 15; Pixel 8; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/138.0.0.0 Mobile Safari/537.36",
  windows: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
  linux: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
};

describe("Settings → Phone's words", () => {
  it("shows the code in two halves joined by a hyphen that never breaks", () => {
    expect(formatPairingCode("K7QM2XD9PA")).toBe("K7QM2‑XD9PA");
    expect(formatPairingCode("k7qm2-xd9pa")).toBe("K7QM2‑XD9PA");
    expect(formatPairingCode("K7QM")).toBe("K7QM");
  });

  it("counts down in minutes and seconds, never below zero", () => {
    expect(countdown(600_000)).toBe("10:00");
    expect(countdown(581_200)).toBe("9:42");
    expect(countdown(4_001)).toBe("0:05");
    expect(countdown(-3_000)).toBe("0:00");
  });

  it("splits a fingerprint into the 8 bytes to compare and the rest", () => {
    const fp = "F2 08 81 E8 3C 51 9A 0B 11 22 33 44";
    expect(fingerprintParts(fp)).toEqual({ head: "F2 08 81 E8 3C 51 9A 0B", rest: "11 22 33 44" });
    expect(fingerprintParts("AA BB")).toEqual({ head: "AA BB", rest: "" });
  });

  it("says on, paused or off, where, and which phones are paired and active", () => {
    const base = { enabled: true, listening: true, url: "https://192.168.178.23:8767", address: "192.168.178.23", port: 8767, devices: [] };
    expect(accessLine(base)).toBe("On · https://192.168.178.23:8767 · no phone paired yet");
    expect(accessLine({ ...base, devices: [device({ active: true })] })).toBe("On · https://192.168.178.23:8767 · 1 phone paired, Anna's iPhone active now");
    expect(accessLine({ ...base, devices: [device({ active: true }), device({ id: "phn_2", active: true })] })).toBe(
      "On · https://192.168.178.23:8767 · 2 phones paired, 2 active now",
    );
    // paused: the saved address, and nobody is "active" on a listener that doesn't answer
    expect(accessLine({ ...base, listening: false, url: null, devices: [device({ active: true })] })).toBe("Paused · https://192.168.178.23:8767 · 1 phone paired");
    expect(accessLine({ ...base, enabled: false, listening: false, url: null })).toBe("Off");
    expect(accessLine({ ...base, enabled: false, listening: false, url: null, devices: [device(), device({ id: "phn_2" })] })).toBe("Off · 2 phones paired");
  });

  it("finds the phone a code paired: one that wasn't there when it was made", () => {
    const anna = device();
    const ben = device({ id: "phn_2", name: "Ben's phone" });
    expect(newDevice([anna, ben], new Set(["phn_1"]))).toBe(ben);
    expect(newDevice([anna], new Set(["phn_1"]))).toBeNull();
  });

  it("calls a new certificate news only to phones paired before it, for a week", () => {
    const now = Date.parse("2026-10-07T12:00:00Z");
    const changed = { certificate_changed_at: "2026-10-05T08:00:00Z" };
    expect(certificateNewsFor({ ...changed, devices: [device({ paired_at: "2026-10-01T08:00:00Z" })] }, now)).toBe(true);
    expect(certificateNewsFor({ ...changed, devices: [device({ paired_at: "2026-10-06T08:00:00Z" })] }, now)).toBe(false);
    expect(certificateNewsFor({ ...changed, devices: [] }, now)).toBe(false);
    expect(certificateNewsFor({ certificate_changed_at: "2026-09-20T08:00:00Z", devices: [device({ paired_at: "2026-09-01T08:00:00Z" })] }, now)).toBe(false);
    expect(certificateNewsFor({ certificate_changed_at: null, devices: [device()] }, now)).toBe(false);
  });

  it("offers the next port, and the address's /24 when the network isn't known", () => {
    expect(nextPort(8767)).toBe(8768);
    expect(nextPort(65535)).toBe(1024);
    expect(homeSubnet({ subnet: "192.168.0.0/23", address: "192.168.1.5" })).toBe("192.168.0.0/23");
    expect(homeSubnet({ subnet: null, address: "192.168.178.23" })).toBe("192.168.178.0/24");
    expect(homeSubnet({ subnet: null, address: null })).toBeNull();
  });
});

describe("the firewall's rules", () => {
  it("let in only this address and port, only from the home network, on Windows only on a private network", () => {
    const { windows, linux } = firewallCommands("192.168.178.23", 8767, "192.168.178.0/24");
    expect(windows).toBe(
      'New-NetFirewallRule -DisplayName "Ordnung phone access" -Direction Inbound -Protocol TCP -LocalAddress 192.168.178.23 -LocalPort 8767 -RemoteAddress LocalSubnet -Profile Private -Action Allow',
    );
    expect(linux).toBe("sudo ufw allow in from 192.168.178.0/24 to 192.168.178.23 port 8767 proto tcp");
    // never "any", never every private network
    expect(`${windows} ${linux}`).not.toMatch(/\bany\b|192\.168\.0\.0\/16|-Profile (Any|Public)/i);
  });

  it("knows which computer it is from its browser", () => {
    expect(computerOs(UA.windows)).toBe("windows");
    expect(computerOs(UA.ipadDesktop)).toBe("mac");
    expect(computerOs(UA.linux)).toBe("linux");
  });
});

describe("where the trust step is offered", () => {
  it("on iOS and iPadOS (every browser there uses the system's checks) and Chrome on Android", () => {
    expect(trustStepPlatform(UA.iphone)).toBe("ios");
    expect(trustStepPlatform(UA.iphoneChrome)).toBe("ios");
    expect(trustStepPlatform(UA.ipadDesktop, 5)).toBe("ios");
    expect(trustStepPlatform(UA.androidChrome)).toBe("android");
  });

  it("nowhere else: a Mac, other Android browsers and in-app browsers, computers", () => {
    expect(trustStepPlatform(UA.ipadDesktop, 0)).toBeNull();
    expect(trustStepPlatform(UA.samsung)).toBeNull();
    expect(trustStepPlatform(UA.firefoxAndroid)).toBeNull();
    expect(trustStepPlatform(UA.webview)).toBeNull();
    expect(trustStepPlatform(UA.windows)).toBeNull();
    expect(trustStepPlatform("")).toBeNull();
  });
});
