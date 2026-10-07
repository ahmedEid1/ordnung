/**
 * Settings on a paired phone (`useMockApi({ client: "phone" })`, the phone's allow-list from openapi.json): it says
 * settings are on the computer before asking for any of them — no settings query, nothing refused — and offers the
 * step that stops the certificate warning only where the phone keeps the certificate to the computer's address.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import SettingsPage from "@/pages/SettingsPage";
import { useMockApi } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/render";
import { AFTER_TRUST_WARNING, CERTIFICATE_PATH, INSTALL_STEPS, REMOVE_STEPS } from "./phoneAccess";
import { PHONE_SETTINGS_TEXT, PhoneSettingsNotice } from "./PhoneSettingsNotice";

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", RO);
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1";
const ANDROID_CHROME = "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36";
const SAMSUNG = "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/27.0 Chrome/125.0.0.0 Mobile Safari/537.36";

describe("Settings on a paired phone", () => {
  it("says settings are on the computer, whatever section the link names, and asks for none of them", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(IPHONE);
    const { srv, calls } = useMockApi({ client: "phone" });
    renderWithProviders(<SettingsPage />, { route: "/settings?section=data" });
    expect(await screen.findByRole("heading", { level: 1, name: "Settings are on your computer" })).toBeInTheDocument();
    expect(screen.getByText(PHONE_SETTINGS_TEXT)).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Settings sections" })).toBeNull();
    expect(screen.queryByRole("heading", { level: 2, name: "Data" })).toBeNull();
    // let the page settle: nothing it would ask for may be asked
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([]);
    expect(srv.refused).toEqual([]);
    // an iPhone is offered the trust step
    expect(screen.getByRole("region", { name: /Stop the security warning/ })).toBeInTheDocument();
  });

  it("on an iPhone: recommends trusting the certificate, step by step, and says what a warning means afterwards", () => {
    renderWithProviders(<PhoneSettingsNotice browser={{ userAgent: IPHONE, maxTouchPoints: 5 }} />);
    const card = screen.getByRole("region", { name: /Stop the security warning/ });
    expect(within(card).getByText("Recommended")).toBeInTheDocument();
    expect(within(card).getByText(/It vouches for your computer's address only — never for your router, another device or any website\./)).toBeInTheDocument();
    const steps = within(card).getAllByRole("listitem").map((li) => li.textContent);
    expect(steps).toEqual(INSTALL_STEPS.ios);
    expect(within(card).getByRole("link", { name: "Download the certificate" })).toHaveAttribute("href", CERTIFICATE_PATH);
    expect(within(card).getByText(AFTER_TRUST_WARNING)).toBeInTheDocument();
    expect(within(card).getByText(`iPhone and iPad: ${REMOVE_STEPS.ios}`)).toBeInTheDocument();
  });

  it("on Android in Chrome: the Android steps", () => {
    renderWithProviders(<PhoneSettingsNotice browser={{ userAgent: ANDROID_CHROME, maxTouchPoints: 5 }} />);
    const card = screen.getByRole("region", { name: /Stop the security warning/ });
    expect(within(card).getAllByRole("listitem").map((li) => li.textContent)).toEqual(INSTALL_STEPS.android);
    expect(within(card).getByText(`Android: ${REMOVE_STEPS.android}`)).toBeInTheDocument();
  });

  it("elsewhere: no certificate to install — the warning stays, and how to check it", () => {
    renderWithProviders(<PhoneSettingsNotice browser={{ userAgent: SAMSUNG, maxTouchPoints: 5 }} />);
    expect(screen.queryByRole("region", { name: /Stop the security warning/ })).toBeNull();
    const card = screen.getByRole("region", { name: "The security warning" });
    expect(within(card).getByText(/doesn't offer to install one here/)).toBeInTheDocument();
    expect(within(card).getByText(/fingerprint matches the one in Settings → Phone on your computer/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Download the certificate" })).toBeNull();
  });

  it("never says “this computer” (it isn't one) or names a terminal command", () => {
    for (const userAgent of [IPHONE, ANDROID_CHROME, SAMSUNG]) {
      const { container, unmount } = renderWithProviders(<PhoneSettingsNotice browser={{ userAgent, maxTouchPoints: 5 }} />);
      expect(container.textContent).not.toMatch(/this computer|ordnung serve|ordnung demo/i);
      unmount();
    }
  });
});
