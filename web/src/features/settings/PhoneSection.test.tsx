/**
 * Settings → Phone on the computer (mock API, design §13.1 with the security review's amendments): off by default;
 * turning it on asks first, at which address; the pairing dialog's QR code reads back to its link, its countdown
 * runs out, and it follows the phone (reached, paired with its two words, a code used twice, wrong codes); help
 * after a minute with the narrowest firewall rules; removing a phone (and what it changed), starting over (and
 * removing the certificate from phones); pauses with their way on, and the dot on Settings; the demos' words.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import decodeQR from "qr/decode.js";
import type { QueryClient } from "@tanstack/react-query";
import { qk } from "@/api/hooks";
import { __clearToasts, Toaster } from "@/components/ui/Toast";
import { PHONE_DEMO_MESSAGE, PHONE_STATIC_MESSAGE } from "@/mocks/data/phone";
import type { MockServer } from "@/mocks/server";
import SettingsPage from "@/pages/SettingsPage";
import { useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { PHONE_CERTIFICATE_GONE } from "./DataSection";
import { REMOVE_STEPS } from "./phoneAccess";

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
  vi.useRealTimers();
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const renderPhone = (route = "/settings?section=phone") =>
  renderWithProviders(
    <>
      <SettingsPage />
      <Toaster />
    </>,
    { route },
  );

/**
 * What the dialog's next poll brings (it asks every 2 s while open, `PHONE_POLL_MS`; the countdown's own test,
 * `PairPhoneDialog.test.tsx`, lets the clock run).
 */
const poll = (client: QueryClient) => act(() => client.refetchQueries({ queryKey: qk.phone }));

/** The QR code drawn on screen, read back by an independent decoder (`qr`, as the GiroCode's test does). */
function readQr(svg: Element): string {
  const size = Number(svg.getAttribute("data-qr-modules"));
  const modules = Array.from({ length: size }, () => Array<boolean>(size).fill(false));
  for (const [, x, y, length] of (svg.querySelector("path")?.getAttribute("d") ?? "").matchAll(/M(\d+) (\d+)h(\d+)v1h-\3z/g)) {
    for (let i = 0; i < Number(length); i++) modules[Number(y)]![Number(x) + i] = true;
  }
  const scale = 4;
  const width = size * scale;
  const data = new Uint8ClampedArray(width * width * 4);
  for (let py = 0; py < width; py++) {
    for (let px = 0; px < width; px++) {
      const at = (py * width + px) * 4;
      data.fill(modules[Math.floor(py / scale)]![Math.floor(px / scale)] ? 0 : 255, at, at + 3);
      data[at + 3] = 255;
    }
  }
  return decodeQR({ width, height: width, data });
}

/** Phone access on at the recommended address (192.168.178.23:8767), as if turned on before. */
function turnedOn(srv: MockServer) {
  srv.phone.change({ enabled: true });
}

async function openPairing(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Pair a phone" }));
  const dialog = await screen.findByRole("dialog", { name: "Pair a phone" });
  await within(dialog).findByText(/Valid for/);
  return dialog;
}

describe("Settings → Phone", () => {
  it("is off by default: what it is, three facts, the switch — nothing to pair, no certificate", async () => {
    useMockApi();
    renderPhone();
    expect(await screen.findByRole("heading", { level: 2, name: "Phone" })).toBeInTheDocument();
    const access = await screen.findByRole("region", { name: "Use Ordnung on your phone" });
    expect(within(access).getByText(/Your letters stay on this computer; the phone only shows them/)).toBeInTheDocument();
    for (const fact of ["Only phones you pair here", "Home network only — nothing goes over the internet", "Settings, backups and deleting stay on this computer"]) {
      expect(within(access).getByText(fact)).toBeInTheDocument();
    }
    expect(within(access).getByRole("switch", { name: "Phone access" })).toHaveAttribute("aria-checked", "false");
    expect(within(access).getByText("Off")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pair a phone" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Certificate" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Paired phones" })).toBeNull();
    // its place in Settings' list
    expect(screen.getByRole("link", { name: "Phone" })).toHaveAttribute("aria-current", "page");
  });

  it("asks before turning on: at which address (the recommended first), the warning, the firewall", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderPhone();
    await user.click(await screen.findByRole("switch", { name: "Phone access" }));
    const dialog = await screen.findByRole("dialog", { name: "Turn on phone access?" });
    expect(within(dialog).getByText("https://192.168.178.23:8767")).toBeInTheDocument();
    const choices = within(dialog).getByRole("group", { name: "Which network do your phones use?" });
    const radios = within(choices).getAllByRole("radio");
    expect(radios.map((r) => (r as HTMLInputElement).value)).toEqual(["192.168.178.23", "192.168.0.40"]);
    expect(radios[0]).toBeChecked();
    expect(within(choices).getAllByText("Recommended")).toHaveLength(1);
    expect(within(choices).getByText("en0 · network 192.168.178.0/24")).toBeInTheDocument();
    expect(within(dialog).getByText(/Ordnung made its own certificate, so no company vouches for it/)).toBeInTheDocument();
    expect(within(dialog).getByText(/allow it on private networks only/)).toBeInTheDocument();
    expect(within(dialog).getByText(/not a café's, a hotel's or a VPN/)).toBeInTheDocument();

    await user.click(radios[1]!);
    expect(within(dialog).getByText("https://192.168.0.40:8767")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Turn on phone access?" })).toBeNull());
    expect(calls.find((c) => c.method === "PUT" && c.path === "/phone")?.body).toEqual({ enabled: true, address: "192.168.0.40" });
    expect(await screen.findByText("Phone access is on")).toBeInTheDocument();
    const access = screen.getByRole("region", { name: "Use Ordnung on your phone" });
    expect(within(access).getByRole("switch", { name: "Phone access" })).toHaveAttribute("aria-checked", "true");
    expect(within(access).getByText("On · https://192.168.0.40:8767 · no phone paired yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pair a phone" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Paired phones" })).toHaveTextContent("No phone is paired yet.");
    const certificate = screen.getByRole("region", { name: "Certificate" });
    expect(within(certificate).getByText("This computer's certificate (SHA‑256)")).toBeInTheDocument();
    expect(within(certificate).getByText(/Made on .* for 192\.168\.0\.40 only\./)).toBeInTheDocument();
  });

  it("turns off at once, keeping the paired phones", async () => {
    const { srv, calls } = useMockApi();
    turnedOn(srv);
    srv.phone.addPhone({ name: "Anna's iPhone" });
    const user = userEvent.setup();
    renderPhone();
    await user.click(await screen.findByRole("switch", { name: "Phone access" }));
    expect(await screen.findByText("Phone access is off")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "PUT" && c.path === "/phone").map((c) => c.body)).toEqual([{ enabled: false }]);
    expect(screen.getByText(/Paired phones stay paired/)).toBeInTheDocument();
    expect(await screen.findByText("Off · 1 phone paired")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Paired phones" })).toHaveTextContent("Anna's iPhone");
  });

  it("moves to another address of this computer on request, offering the other one first", async () => {
    const { srv, calls } = useMockApi();
    turnedOn(srv);
    const user = userEvent.setup();
    renderPhone();
    await user.click(await screen.findByRole("button", { name: "Use another address…" }));
    const dialog = await screen.findByRole("dialog", { name: "Use another address?" });
    expect(within(dialog).getByRole("radio", { name: /192\.168\.0\.40/ })).toBeChecked();
    // nothing about the certificate warning or the firewall again: that was said when it was turned on
    expect(within(dialog).queryByText(/firewall/)).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Use this address" }));
    expect(await screen.findByText("Phone access moved")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ enabled: true, address: "192.168.0.40" });
    // a new address, a new certificate authority: phones that trusted the old one should drop it
    expect(screen.getByText("New address, new certificate")).toBeInTheDocument();
  });

  it("pairs a phone: a QR code that reads back to the link, the code, the phone reaching it, then its two words", async () => {
    const { srv } = useMockApi();
    turnedOn(srv);
    const user = userEvent.setup();
    const { client } = renderPhone();
    const dialog = await openPairing(user);
    const link = dialog.querySelector("[data-pairing-url]")!.getAttribute("data-pairing-url")!;
    const code = srv.phone.code!;
    expect(link).toBe(`https://192.168.178.23:8767/pair#${code}`);
    expect(readQr(within(dialog).getByRole("img", { name: /Pairing code as a QR code/ }))).toBe(link);
    expect(within(dialog).getByText(`${code.slice(0, 5)}‑${code.slice(5)}`)).toBeInTheDocument();
    expect(within(dialog).getByText("10:00")).toBeInTheDocument();
    expect(within(dialog).getByText("Waiting for your phone…")).toBeInTheDocument();
    // the steps: the warning page and the fingerprint to compare on it; typing the address instead
    const fingerprint = srv.phone.status().fingerprint!.split(" ").slice(0, 8).join(" ");
    expect(within(dialog).getByText(fingerprint)).toBeInTheDocument();
    expect(within(dialog).getByText(/Show Details/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("tab", { name: "Android" }));
    expect(within(dialog).getByText("Proceed to 192.168.178.23")).toBeInTheDocument();
    expect(within(dialog).getByText(/^Can't scan\?/)).toHaveTextContent("Can't scan? On the phone, open https://192.168.178.23:8767/pair and type the code.");

    // the phone opens the page (from its address), a neighbour types a wrong code
    srv.phone.opened("192.168.178.31");
    expect(() => srv.phone.pair({ code: "AAAAAAAAAA", name: "x" }, "192.168.178.66")).toThrow();
    await poll(client);
    expect(await within(dialog).findByText(/Your phone reached this computer — finish on the phone\./)).toBeInTheDocument();
    expect(within(dialog).getByText("From 192.168.178.31.")).toBeInTheDocument();
    expect(within(dialog).getByText("1 wrong code typed so far, from 192.168.178.66.")).toBeInTheDocument();

    // it pairs: no more QR code, its name, browser and address, and the words it shows
    const anna = srv.phone.pair({ code, name: "Anna's iPhone" }, "192.168.178.31");
    await poll(client);
    expect(await within(dialog).findByText("Paired: Anna's iPhone")).toBeInTheDocument();
    expect(within(dialog).getByText("iPhone · Safari · from 192.168.178.31")).toBeInTheDocument();
    expect(within(dialog).getByText(`Your phone should show “${anna.check_words}”`)).toBeInTheDocument();
    expect(within(dialog).queryByRole("img", { name: /QR code/ })).toBeNull();
    expect(within(dialog).getByText(`Paired: Anna's iPhone. Your phone should show ${anna.check_words}.`)).toHaveAttribute("role", "status");
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const phones = screen.getByRole("region", { name: "Paired phones" });
    expect(within(phones).getByText("Anna's iPhone")).toBeInTheDocument();
    expect(within(phones).getByText(`“${anna.check_words}”`)).toBeInTheDocument();
  });

  it("“Not you? Remove” signs a phone out at once and offers a new code", async () => {
    const { srv } = useMockApi();
    turnedOn(srv);
    const user = userEvent.setup();
    const { client } = renderPhone();
    const dialog = await openPairing(user);
    srv.phone.pair({ code: srv.phone.code!, name: "iPhone" }, "192.168.178.66");
    await poll(client);
    await within(dialog).findByText("Paired: iPhone");
    await user.click(within(dialog).getByRole("button", { name: "Not you? Remove" }));
    expect(await within(dialog).findByText("Removed iPhone")).toBeInTheDocument();
    expect(srv.phone.devices).toEqual([]);
    const first = srv.phone.code;
    await user.click(within(dialog).getByRole("button", { name: "Make a new code" }));
    await within(dialog).findByText("10:00");
    expect(srv.phone.code).not.toBeNull();
    expect(srv.phone.code).not.toBe(first);
  });

  it("a code used twice: neither phone stays paired, and the danger notice names the addresses", async () => {
    const { srv } = useMockApi();
    turnedOn(srv);
    const user = userEvent.setup();
    const { client } = renderPhone();
    const dialog = await openPairing(user);
    const code = srv.phone.code!;
    srv.phone.pair({ code, name: "iPhone" }, "192.168.178.66");
    expect(() => srv.phone.pair({ code, name: "iPhone" }, "192.168.178.31")).toThrow(/already used/);
    await poll(client);
    expect(await within(dialog).findByText("A pairing code was used twice")).toBeInTheDocument();
    expect(within(dialog).getByText("Two devices used the same code, so neither is paired. Someone else may have seen your screen.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Make a new code" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const notice = screen.getByRole("alert");
    expect(within(notice).getByText("A pairing code was used twice")).toBeInTheDocument();
    expect(within(notice).getByText("Addresses involved: 192.168.178.66, 192.168.178.31.")).toBeInTheDocument();
    // the section is marked in Settings' list
    expect(await screen.findByRole("link", { name: "Phone, needs your attention" })).toBeInTheDocument();
    await user.click(within(notice).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("too many wrong codes cancel the code, and say from where", async () => {
    const { srv } = useMockApi();
    turnedOn(srv);
    const user = userEvent.setup();
    const { client } = renderPhone();
    const dialog = await openPairing(user);
    // 5 tries per device, 100 on the network
    for (let i = 0; i < 100; i++) {
      expect(() => srv.phone.pair({ code: "AAAAAAAAAA", name: "x" }, `192.168.178.${100 + Math.floor(i / 5)}`)).toThrow();
    }
    await poll(client);
    expect(await within(dialog).findByText("A pairing code was cancelled")).toBeInTheDocument();
    // shown, and said to a screen reader (the dialog's status line)
    expect(within(dialog).getAllByText(/100 wrong pairing codes were typed on your network, so the code was cancelled\. They came from 192\.168\.178\.100,/)).toHaveLength(2);
  });

  it("closing cancels a code nobody used", async () => {
    const { srv, calls } = useMockApi();
    turnedOn(srv);
    const user = userEvent.setup();
    renderPhone();
    const dialog = await openPairing(user);
    expect(srv.phone.code).not.toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/phone/pairing")).toBe(true));
    expect(srv.phone.code).toBeNull();
  });

  it("removes a phone after saying what it changed in the last 30 days, linking to its privacy log", async () => {
    const { srv, calls } = useMockApi();
    turnedOn(srv);
    const anna = srv.phone.addPhone({ name: "Anna's iPhone", active: true, last_address: "192.168.178.31" });
    srv.db.log("item.done", "Marked “Pay the rent” done on Anna's iPhone", null, null, { device: anna.id });
    srv.db.log("document.added", "Added “photo-p1.jpg” from your phone", "document", "doc_x", { device: anna.id });
    const user = userEvent.setup();
    renderPhone();
    const phones = await screen.findByRole("region", { name: "Paired phones" });
    expect(within(phones).getByText("Active now")).toBeInTheDocument();
    expect(within(phones).getByText(/Paired .* · last used just now from 192\.168\.178\.31/)).toBeInTheDocument();
    expect(within(phones).getByRole("link", { name: "2 changes in the last 30 days from Anna's iPhone" })).toHaveAttribute("href", `/settings?section=privacy&device=${anna.id}`);
    await user.click(within(phones).getByRole("button", { name: "Remove Anna's iPhone…" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove Anna's iPhone?" });
    expect(within(dialog).getByText("It is signed out at once. Letters it sent stay in Ordnung.")).toBeInTheDocument();
    expect(within(dialog).getByText(/2 changes from this phone in the last 30 days/)).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "see what it changed" })).toHaveAttribute("href", `/settings?section=privacy&device=${anna.id}`);
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(await screen.findByText("Removed Anna's iPhone")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE" && c.path === `/phone/devices/${anna.id}`)).toBe(true);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(within(phones).getByText("No phone is paired yet.")).toBeInTheDocument();
  });

  it("the privacy log shows only what one phone did, and everything again", async () => {
    const { srv } = useMockApi();
    turnedOn(srv);
    const anna = srv.phone.addPhone({ name: "Anna's iPhone" });
    srv.db.log("item.done", "Marked “Pay the rent” done on Anna's iPhone", null, null, { device: anna.id });
    const user = userEvent.setup();
    renderPhone(`/settings?section=privacy&device=${anna.id}`);
    const activity = await screen.findByRole("region", { name: "Activity" });
    expect(await within(activity).findByText("Anna's iPhone")).toBeInTheDocument();
    expect(await within(activity).findByText("Marked “Pay the rent” done on Anna's iPhone")).toBeInTheDocument();
    expect(within(activity).getAllByRole("listitem")).toHaveLength(1);
    await user.click(within(activity).getByRole("button", { name: "Show everything" }));
    await waitFor(() => expect(within(activity).getAllByRole("listitem").length).toBeGreaterThan(1));
    expect(within(activity).queryByText(/Only what/)).toBeNull();
  });

  it("starts over after asking, then says how to remove the certificate from a phone", async () => {
    const { srv, calls } = useMockApi();
    turnedOn(srv);
    srv.phone.addPhone({ name: "Anna's iPhone" });
    const user = userEvent.setup();
    renderPhone();
    const certificate = await screen.findByRole("region", { name: "Certificate" });
    await user.click(within(certificate).getByRole("button", { name: "Start over…" }));
    const dialog = await screen.findByRole("dialog", { name: "Start over with phone access?" });
    expect(within(dialog).getByText(/Phones that trust the old certificate should remove it\./)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Start over" }));
    expect(await screen.findByText("Phone access started over")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/phone/reset")).toBe(true);
    expect(screen.getByText(REMOVE_STEPS.ios)).toBeInTheDocument();
    await waitFor(() => expect(document.activeElement?.id).toBe("phone-certificate-advice"));
    expect(screen.getByRole("switch", { name: "Phone access" })).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByRole("region", { name: "Certificate" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Paired phones" })).toBeNull();
  });
});

describe("Settings → Phone when phones can't reach it", () => {
  it("another address: asks first (phones pair again), then says to remove the old certificate", async () => {
    const { srv, calls } = useMockApi();
    turnedOn(srv);
    srv.phone.addPhone({ name: "Anna's iPhone" });
    srv.phone.setProblem("address_gone");
    const user = userEvent.setup();
    renderPhone();
    expect(await screen.findByText("Paused: this computer isn't on 192.168.178.23 any more.")).toBeInTheDocument();
    expect(screen.getByText("Paused · https://192.168.178.23:8767 · 1 phone paired")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Phone, needs your attention" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pair a phone" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Use 192.168.0.40 instead" }));
    const dialog = await screen.findByRole("dialog", { name: "Use another address?" });
    expect(within(dialog).getByText("https://192.168.0.40:8767")).toBeInTheDocument();
    expect(within(dialog).getByText(/The phone paired at 192\.168\.178\.23 will need to pair again at the new address/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Use this address" }));
    expect(await screen.findByText("New address, new certificate")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "PUT" && c.path === "/phone").map((c) => c.body)).toEqual([{ enabled: true, address: "192.168.0.40" }]);
    expect(screen.getByText("On · https://192.168.0.40:8767 · no phone paired yet")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("link", { name: "Phone, needs your attention" })).toBeNull());
  });

  it("“Keep waiting” changes nothing and says it starts again by itself", async () => {
    const { srv, calls } = useMockApi();
    turnedOn(srv);
    srv.phone.setProblem("address_gone");
    const user = userEvent.setup();
    renderPhone();
    await user.click(await screen.findByRole("button", { name: "Keep waiting" }));
    expect(screen.getByText("Phone access starts again by itself when this computer is back on 192.168.178.23.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /instead/ })).toBeNull();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("the same address on another network: waits, until the person says it is home", async () => {
    const { srv, calls } = useMockApi();
    turnedOn(srv);
    srv.phone.setProblem("other_network");
    const user = userEvent.setup();
    renderPhone();
    expect(await screen.findByText(/on a different network than before/)).toBeInTheDocument();
    expect(screen.getByText(/perhaps a café's or a friend's network that hands out the same address/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "This is my home network" }));
    expect(await screen.findByText("Phone access is on again")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ enabled: true, home_network: true });
    expect(screen.getByText("On · https://192.168.178.23:8767 · no phone paired yet")).toBeInTheDocument();
  });

  it("a busy port: offers the next one", async () => {
    const { srv, calls } = useMockApi();
    turnedOn(srv);
    srv.phone.setProblem("port_busy");
    const user = userEvent.setup();
    renderPhone();
    expect(await screen.findByText("Another program uses port 8767.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use port 8768" }));
    expect(await screen.findByText("Phone access is on at port 8768")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ enabled: true, port: 8768 });
  });

  it("no home network: waits, and turning on says why it can't", async () => {
    const { srv } = useMockApi();
    turnedOn(srv);
    srv.phone.setProblem("no_network");
    renderPhone();
    expect(await screen.findByText("Waiting for a home network.")).toBeInTheDocument();
    expect(screen.getByText("Phone access starts again by itself when this computer is back on a home network.")).toBeInTheDocument();
  });
});

describe("Delete everything and phone access", () => {
  it("says phone access goes too, and how to remove the certificate from a phone", async () => {
    const { srv } = useMockApi();
    srv.db.state.health.demo = false;
    turnedOn(srv);
    srv.phone.addPhone({ name: "Anna's iPhone" });
    const client = makeTestQueryClient();
    client.setQueryData(qk.health, { ...TEST_HEALTH, demo: false });
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <SettingsPage />
        <Toaster />
      </>,
      { route: "/settings?section=data", client },
    );
    await user.click(await screen.findByRole("button", { name: "Delete everything…" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete everything?" });
    expect(await within(dialog).findByText(/Phone access goes too: 1 paired phone is signed out and its certificate is deleted\./)).toHaveTextContent(REMOVE_STEPS.ios);
    await user.type(within(dialog).getByLabelText("Type DELETE to confirm"), "DELETE");
    await user.click(within(dialog).getByRole("button", { name: "Delete everything" }));
    expect(await screen.findByText(new RegExp(PHONE_CERTIFICATE_GONE.replace(/[()]/g, "\\$&")))).toBeInTheDocument();
    expect(srv.phone.devices).toEqual([]);
  });
});

describe("Settings → Phone in the demos", () => {
  it("ordnung demo: the switch is off and says why", async () => {
    const { srv } = useMockApi();
    srv.phone.makeUnavailable();
    renderPhone();
    const access = await screen.findByRole("region", { name: "Use Ordnung on your phone" });
    expect(within(access).getByRole("switch", { name: "Phone access" })).toBeDisabled();
    expect(within(access).getByRole("note")).toHaveTextContent(PHONE_DEMO_MESSAGE);
    expect(screen.queryByRole("region", { name: "Certificate" })).toBeNull();
  });

  it("the online demo: it can't connect a phone", async () => {
    useMockApi({ staticDemo: true });
    renderPhone();
    const access = await screen.findByRole("region", { name: "Use Ordnung on your phone" });
    expect(within(access).getByRole("switch", { name: "Phone access" })).toBeDisabled();
    expect(within(access).getByRole("note")).toHaveTextContent(PHONE_STATIC_MESSAGE);
  });
});
