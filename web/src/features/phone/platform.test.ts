// @vitest-environment-options {"url": "https://192.168.178.23:8767/pair"}
/**
 * The phone's side of the browser: a first name for the phone from its User-Agent (never the User-Agent itself),
 * and knowing it is a phone before the server could say so — the page came over HTTPS, which only the phone
 * listener speaks (this file runs at `https://192.168.178.23:8767`).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { setClientKind } from "@/api/clientKind";
import { DEFAULT_PHONE_NAME, guessDeviceName, servedToPhone } from "./platform";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("a first name for the phone", () => {
  it.each([
    ["Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1", 5, "iPhone"],
    ["Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0 Mobile/15E148 Safari/604.1", 5, "iPhone"],
    ["Mozilla/5.0 (iPad; CPU OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1", 5, "iPad"],
    // an iPad asks for the desktop site: a Mac with a touch screen
    ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15", 5, "iPad"],
    ["Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36", 5, "Android phone"],
    ["Mozilla/5.0 (Linux; Android 14; SAMSUNG SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile Safari/537.36", 5, "Android phone"],
    ["Mozilla/5.0 (Linux; Android 13; SM-X200) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36", 5, "Android tablet"],
    ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15", 0, DEFAULT_PHONE_NAME],
    ["Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0", 0, DEFAULT_PHONE_NAME],
  ])("%s → %s", (ua, touch, name) => {
    expect(guessDeviceName(ua, touch)).toBe(name);
  });
});

describe("this tab is a phone's", () => {
  it("when the server said so", () => {
    setClientKind("phone");
    expect(servedToPhone()).toBe(true);
  });

  it("before it could: the page came over HTTPS (the computer's own listener is plain HTTP on 127.0.0.1)", () => {
    expect(window.location.protocol).toBe("https:");
    setClientKind("computer");
    expect(servedToPhone()).toBe(true);
  });

  it("never in the online demo, which is HTTPS without a computer behind it", () => {
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    expect(servedToPhone()).toBe(false);
  });
});
