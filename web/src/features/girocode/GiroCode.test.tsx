/**
 * The GiroCode block of the pay panels: the code (drawn from the server's payload), folded on
 * Today, the comparison with the letter for details read from a photo, why there is no code, what a
 * phone does instead of scanning itself, a code without a reference — and the same on the static
 * demo's letters (utility statement, parking fine, scam).
 */
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DocumentDetail, GiroCode } from "@/api/types";
import { useDocument } from "@/api/hooks";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders, TEST_HEALTH } from "@/test/render";
import { qk } from "@/api/hooks";
import { createQueryClient } from "@/app/queryClient";
import { useMockApi } from "@/test/mockFetch";
import { createMockServer } from "@/mocks/server";
import { GIROCODES } from "@/mocks/data/girocodes";
import { DocumentView } from "@/features/document/DocumentView";
import { TodayView } from "@/features/today/TodayView";
import { PayPanel } from "@/features/document/PayPanel";
import {
  GIROCODE_CHECKED,
  GIROCODE_HINT,
  GIROCODE_MISMATCH,
  GIROCODE_MISMATCH_DETAILS,
  GIROCODE_NO_REFERENCE,
  GIROCODE_ON_PHONE,
  GIROCODE_READING_AGAIN,
  GiroCodeSection,
  canReadLetterAgain,
  giroCodeLabel,
  modulePixels,
} from "./GiroCode";
import { plainText } from "@/lib/glue";
import { qrMatrix, qrPath } from "./qr";

const NK = "BCD\n002\n1\nSCT\n\nWohnbau Musterstadt eG\nDE05123456000004455660\nEUR184.3\n\n\nMV-2025-0412 NK 2025";
const ready: GiroCode = { status: "ready", item_id: "itm_nk", payload: NK, checked: false };

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

function renderSection(code: GiroCode | undefined, collapsible = false) {
  return renderWithProviders(
    <>
      <GiroCodeSection code={code} docId="doc_nebenkosten" collapsible={collapsible} />
      <Toaster />
    </>,
  );
}

describe("a ready code", () => {
  it("draws the payload's QR code dark on white, labelled with what it pays", () => {
    renderSection(ready);
    const section = screen.getByRole("region", { name: "GiroCode (EPC-QR)" });
    expect(within(section).getByText(GIROCODE_HINT)).toBeInTheDocument();
    const code = within(section).getByRole("img", { name: "GiroCode: transfer €184.30 to Wohnbau Musterstadt eG, reference MV-2025-0412 NK 2025" });
    expect(code.tagName.toLowerCase()).toBe("svg");
    expect(code.querySelector("path")!.getAttribute("d")).toBe(qrPath(qrMatrix(NK).modules));
    // scanners need dark on white in both themes, whatever the page's colours
    expect(code.querySelector("rect")!.getAttribute("fill")).toBe("#ffffff");
    expect(code.querySelector("path")!.getAttribute("fill")).toBe("#000000");
    expect(code.getAttribute("class")).toContain("[forced-color-adjust:none]");
    expect(code.getAttribute("shape-rendering")).toBe("crispEdges");
    expect(within(section).queryByText(/You compared these details/)).toBeNull();
  });

  it("says when the person compared the details with the letter", () => {
    renderSection({ ...ready, checked: true });
    expect(screen.getByText("You compared these details with the letter.")).toBeInTheDocument();
  });

  it("says when it carries no reference, which the letter may name after all", () => {
    const { unmount } = renderSection(ready);
    expect(screen.queryByText(GIROCODE_NO_REFERENCE)).toBeNull();
    unmount();
    // folded on Today too: the line is for copying by hand as well
    renderSection({ ...ready, payload: "BCD\n002\n1\nSCT\n\nMuster Telecom GmbH\nDE05123456000004455660\nEUR49.99" }, true);
    const section = screen.getByRole("region", { name: "GiroCode (EPC-QR)" });
    expect(within(section).getByText(GIROCODE_NO_REFERENCE)).toBeInTheDocument();
    expect(screen.getByText(GIROCODE_NO_REFERENCE).className).toContain("text-warn-ink");
  });

  it("tells a phone, which can't scan its own screen, what to do instead", () => {
    // jsdom has no media queries: phone-sized
    const { unmount } = renderSection(ready, true);
    expect(within(screen.getByRole("region", { name: "GiroCode (EPC-QR)" })).getByText(GIROCODE_ON_PHONE)).toBeInTheDocument();
    unmount();
    const media = (matches: (q: string) => boolean) => (query: string) => ({ matches: matches(query), media: query, addEventListener() {}, removeEventListener() {} });
    // a computer (Today folds the code there too): no such line
    vi.stubGlobal("matchMedia", media((q) => q.includes("min-width: 768px")));
    const { unmount: unmountDesktop } = renderSection(ready, true);
    expect(screen.queryByText(GIROCODE_ON_PHONE)).toBeNull();
    unmountDesktop();
    // a tablet: wide, but it can't scan itself either
    vi.stubGlobal("matchMedia", media((q) => q.includes("min-width: 768px") || q.includes("pointer: coarse")));
    renderSection(ready, true);
    expect(screen.getByText(GIROCODE_ON_PHONE)).toBeInTheDocument();
  });

  it("starts folded on Today and opens with “Show code”", async () => {
    const user = userEvent.setup();
    renderSection(ready, true);
    const toggle = screen.getByRole("button", { name: "Show code" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("img", { name: /^GiroCode:/ })).toBeNull();
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Hide code" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("img", { name: /^GiroCode: transfer €184\.30/ })).toBeInTheDocument();
  });

  it("shows the code when the panel stops folding it (unlocked a render after the answer arrived)", () => {
    const { rerender } = renderWithProviders(<GiroCodeSection code={ready} docId="doc_nebenkosten" collapsible />);
    expect(screen.queryByRole("img", { name: /^GiroCode:/ })).toBeNull();
    rerender(<GiroCodeSection code={ready} docId="doc_nebenkosten" collapsible={false} />);
    expect(screen.getByRole("img", { name: /^GiroCode: transfer €184\.30/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /code$/ })).toBeNull();
  });

  it("draws every module a whole number of pixels, at least three, whatever the code's size", () => {
    renderSection(ready);
    const code = screen.getByRole("img", { name: /^GiroCode:/ });
    const modules = Number(code.getAttribute("data-qr-modules"));
    expect(Number(code.getAttribute("width"))).toBe(modules * 3);
    expect(code.getAttribute("width")).toBe(code.getAttribute("height"));
    // version 1 up to version 13 (the standard's largest): from 5 px down to 3 px, never less
    expect([29, 49, 73, 77].map(modulePixels)).toEqual([5, 3, 3, 3]);
    const long = `BCD\n002\n1\nSCT\n\n${"Stadtwerke Musterstadt Versorgungs- und Verkehrsgesellschaft mbH".slice(0, 70)}\nDE05123456000004455660\nEUR1234.56\n\n\n${"Kassenzeichen 5126 0184 5122 ".repeat(5).slice(0, 140)}`;
    const { container } = renderSection({ ...ready, payload: long });
    const svg = container.querySelector("svg[data-qr-modules]")!;
    expect(Number(svg.getAttribute("data-qr-version"))).toBeGreaterThanOrEqual(10);
    expect(Number(svg.getAttribute("width")) / Number(svg.getAttribute("data-qr-modules"))).toBe(3);
  });

  it("labels a code without an amount or reference plainly", () => {
    expect(giroCodeLabel("BCD\n002\n1\nSCT\n\nStadtkasse\nDE05123456000004455660")).toBe("GiroCode: transfer to Stadtkasse");
  });
});

describe("no code", () => {
  it("wraps a long name in its reason inside the block", () => {
    const payee = "Zahlungsabwicklungsgesellschaftfürrundfunkbeitragsangelegenheiten GmbH";
    renderSection({ status: "blocked", item_id: "x", reason: "scam", message: `No code: the money would go to “${payee}”.`, to_check: [], values: null });
    expect(screen.getByText(/the money would go to/).className).toContain("wrap-break-word");
  });

  it("says why, loudly for a scam", () => {
    renderSection(GIROCODES.itm_scam_demand);
    const section = screen.getByRole("region", { name: "GiroCode (EPC-QR)" });
    expect(section).toHaveTextContent("No code: this IBAN is not the one Beitragsservice Musterstadt used before.");
    expect(section.className).toContain("bg-danger-soft");
    expect(within(section).queryByRole("img")).toBeNull();
    expect(within(section).queryByRole("button")).toBeNull();
  });

  it("stays quiet where the pay panel already explains it", () => {
    for (const reason of ["no_iban", "incoming", "settled", "invalid_iban"] as const) {
      const { container, unmount } = renderSection({ status: "blocked", item_id: "x", reason, message: "No code: …", to_check: [], values: null });
      expect(container.querySelector("[data-girocode]")).toBeNull();
      unmount();
    }
    const { container } = renderSection(undefined);
    expect(container.querySelector("[data-girocode]")).toBeNull();
  });
});

/** The parking fine's code as the letter's detail has it (refetched after the check), folded as on Today. */
function LiveParkingCode() {
  const detail = useDocument("doc_parking");
  return <GiroCodeSection code={detail.data?.girocodes.find((g) => g.item_id === "itm_parking")} docId="doc_parking" collapsible />;
}

describe("details read from a photo", () => {
  it("asks to compare them with the paper letter, then shows the code unfolded, says so and moves focus to it", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<LiveParkingCode />);
    const section = await screen.findByRole("region", { name: "GiroCode (EPC-QR)" });
    expect(section).toHaveTextContent("the amount, the IBAN and the reference were read by AI from a photo");
    expect(within(section).queryByRole("img")).toBeNull();
    await user.click(within(section).getByRole("button", { name: "These match the letter" }));
    expect(calls.find((c) => c.method === "POST")).toEqual({
      method: "POST",
      path: "/items/itm_parking/girocode/confirm",
      body: { payee: "Stadtkasse Musterstadt", iban: "DE51123456000000100017", reference: "OA-VW-2026-55012", amount: 30 },
    });
    // unlocked: shown right away (not folded), with the person's check, announced, focus on its heading
    expect(await screen.findByRole("img", { name: "GiroCode: transfer €30.00 to Stadtkasse Musterstadt, reference OA-VW-2026-55012" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show code" })).toBeNull();
    expect(screen.getByText(GIROCODE_CHECKED)).toBeInTheDocument();
    expect(screen.getByText(`GiroCode ready. ${GIROCODE_CHECKED}`)).toHaveAttribute("aria-live", "polite");
    await waitFor(() => expect(screen.getByRole("heading", { name: "GiroCode (EPC-QR)" })).toHaveFocus());
  });

  it("focuses the unlocked code's heading without scrolling, then scrolls the code into view", async () => {
    useMockApi();
    const user = userEvent.setup();
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    try {
      renderWithProviders(<LiveParkingCode />);
      await user.click(await screen.findByRole("button", { name: "These match the letter" }));
      await screen.findByText(GIROCODE_CHECKED);
      const heading = screen.getByRole("heading", { name: "GiroCode (EPC-QR)" });
      await waitFor(() => expect(heading).toHaveFocus());
      // a focus() that scrolls cancels the smooth scroll to the code (Chromium)
      const onHeading = focus.mock.calls.filter((_, i) => focus.mock.contexts[i] === heading);
      expect(onHeading).toEqual([[{ preventScroll: true }]]);
      expect(scroll).toHaveBeenCalledWith({ block: "nearest", behavior: "smooth" });
      expect(focus.mock.invocationCallOrder[focus.mock.contexts.indexOf(heading)]!).toBeLessThan(scroll.mock.invocationCallOrder.at(-1)!);
    } finally {
      focus.mockRestore();
      delete (Element.prototype as Partial<Element>).scrollIntoView;
    }
  });

  it("scrolls without animation when the person asked for reduced motion", async () => {
    useMockApi();
    const user = userEvent.setup();
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), media: query, addEventListener() {}, removeEventListener() {} }));
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    try {
      renderWithProviders(<LiveParkingCode />);
      await user.click(await screen.findByRole("button", { name: "These match the letter" }));
      await screen.findByText(GIROCODE_CHECKED);
      await waitFor(() => expect(scroll).toHaveBeenCalledWith({ block: "nearest", behavior: "auto" }));
    } finally {
      delete (Element.prototype as Partial<Element>).scrollIntoView;
    }
  });

  it("shows the server's refusal in the block, gives focus back and shows the details as they are now", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    // the app's client: no toast (it would wait behind a phone's sheet) — the block says it
    const client = createQueryClient();
    client.setQueryData(qk.health, TEST_HEALTH);
    renderWithProviders(
      <>
        <LiveParkingCode />
        <Toaster />
      </>,
      { client },
    );
    const button = await screen.findByRole("button", { name: "These match the letter" });
    // the amount changes elsewhere (another tab) after the details were shown
    srv.db.state.items.find((i) => i.id === "itm_parking")!.amount = 35;
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    await user.click(button);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Not confirmed: The payment details changed since you looked at them. Please compare them again.");
    expect(screen.queryByText("Couldn't confirm the payment details")).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "These match the letter" })).toHaveFocus());
    // below the buttons: brought clear of the panel's sticky footer (a short Today popover hides it)
    await waitFor(() => expect(scroll.mock.contexts).toContain(alert));
    delete (Element.prototype as Partial<Element>).scrollIntoView;
    // refetched: comparing again compares the new amount
    await user.click(screen.getByRole("button", { name: "These match the letter" }));
    expect(await screen.findByRole("img", { name: /^GiroCode: transfer €35\.00 to Stadtkasse Musterstadt/ })).toBeInTheDocument();
    expect(srv.db.state.activity.filter((a) => a.kind === "payment.checked")).toHaveLength(1);
  });

  it("“They don't match” says to type the details from the letter, and can read the letter again", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    renderWithProviders(<GiroCodeSection code={GIROCODES.itm_parking} docId="doc_parking" canReadAgain />);
    const toggle = screen.getByRole("button", { name: "They don't match" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(GIROCODE_MISMATCH)).not.toBeVisible();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(GIROCODE_MISMATCH)).toBeVisible();
    // the answer opens below the button: it is brought into the panel's view
    expect(scroll.mock.contexts).toContain(screen.getByText(GIROCODE_MISMATCH).parentElement);
    delete (Element.prototype as Partial<Element>).scrollIntoView;
    await user.click(screen.getByRole("button", { name: "Read the letter again" }));
    expect(calls.some((c) => c.method === "POST" && c.path === "/documents/doc_parking/reprocess")).toBe(true);
    expect(await screen.findByText(GIROCODE_READING_AGAIN)).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/girocode/confirm"))).toBe(false);
  });

  it("“Read the letter again” keeps focus on its button, which stays while the letter is read", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    function Panel() {
      const [canReadAgain, setCanReadAgain] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setCanReadAgain(false)}>
            The letter is being read
          </button>
          <GiroCodeSection code={GIROCODES.itm_parking} docId="doc_parking" canReadAgain={canReadAgain} />
        </>
      );
    }
    renderWithProviders(<Panel />);
    await user.click(screen.getByRole("button", { name: "They don't match" }));
    const button = screen.getByRole("button", { name: "Read the letter again" });
    await user.click(button);
    expect(await screen.findByText(GIROCODE_READING_AGAIN)).toBeInTheDocument();
    // not disabled (a disabled button drops focus to the page): marked, and a second press asks nothing
    await waitFor(() => expect(button).toHaveFocus());
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    await user.keyboard("{Enter}");
    expect(calls.filter((c) => c.path === "/documents/doc_parking/reprocess")).toHaveLength(1);
    // the letter is being read now, so the panel stops offering it: the answer stays
    // (a click event without moving focus, as the server's answer would)
    fireEvent.click(screen.getByRole("button", { name: "The letter is being read" }));
    expect(screen.getByText(GIROCODE_READING_AGAIN)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read the letter again" })).toHaveFocus();
  });

  it("says in the block why the letter couldn't be read again — no toast behind the sheet — and keeps focus", async () => {
    // the online demo reads no letters: its answer stands in for any refusal (Claude paused, a break …)
    useMockApi({ staticDemo: true });
    const user = userEvent.setup();
    const client = createQueryClient();
    client.setQueryData(qk.health, TEST_HEALTH);
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    try {
      renderWithProviders(
        <>
          <GiroCodeSection code={GIROCODES.itm_parking} docId="doc_parking" canReadAgain />
          <Toaster />
        </>,
        { client },
      );
      await user.click(screen.getByRole("button", { name: "They don't match" }));
      const button = screen.getByRole("button", { name: "Read the letter again" });
      await user.click(button);
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/^Couldn't read the letter again: Install Ordnung to try this/);
      expect(screen.queryByText("Not available in the online demo")).toBeNull();
      await waitFor(() => expect(button).toHaveFocus());
      expect(button).not.toHaveAttribute("aria-disabled");
      // below the button: brought clear of the panel's footer
      expect(scroll.mock.contexts).toContain(alert);
    } finally {
      delete (Element.prototype as Partial<Element>).scrollIntoView;
    }
  });

  it("offers reading again only where it can work", () => {
    const letter = { ai_private: false, status: "processed" as const };
    expect(canReadLetterAgain(letter)).toBe(true);
    expect(canReadLetterAgain({ ...letter, ai_private: true })).toBe(false);
    expect(canReadLetterAgain({ ...letter, status: "processing" })).toBe(false);
    expect(canReadLetterAgain({ ...letter, status: "queued" })).toBe(false);
    expect(canReadLetterAgain(undefined)).toBe(false);
    // the online demo reads no letters: the button would only fail
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    try {
      expect(canReadLetterAgain(letter)).toBe(false);
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("offers no reading again for a private letter", async () => {
    const user = userEvent.setup();
    renderSection(GIROCODES.itm_parking);
    await user.click(screen.getByRole("button", { name: "They don't match" }));
    expect(screen.getByText(GIROCODE_MISMATCH)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Read the letter again" })).toBeNull();
  });
});

describe("the pay panel", () => {
  it("warns once about an IBAN failing its check (not again in a grey GiroCode box)", async () => {
    const d = await detail("doc_nebenkosten");
    const item = d.items.find((i) => i.kind === "payment")!;
    const doc = { ...d.document, payment: { ...d.document.payment!, iban_valid: null } };
    const code: GiroCode = { status: "blocked", item_id: item.id, reason: "invalid_iban", message: "No code: DE05 … is not a valid IBAN.", to_check: [], values: null };
    renderWithProviders(<PayPanel item={item} doc={doc} code={code} onPaid={() => {}} />);
    expect(screen.getAllByText(/fails its checksum|not a valid IBAN/)).toHaveLength(1);
    expect(screen.getByText(/fails its checksum/)).toBeInTheDocument();
    expect(document.querySelector("[data-girocode]")).toBeNull();
  });

  it("shows and copies the reference without its label, as the code carries it", async () => {
    const d = await detail("doc_parking");
    const item = d.items.find((i) => i.kind === "payment")!;
    const doc = { ...d.document, payment: { ...d.document.payment!, reference: "Kassenzeichen: 5126 0184 5122" } };
    renderWithProviders(<PayPanel item={item} doc={doc} onPaid={() => {}} />);
    expect(screen.getByText("5126 0184 5122")).toBeInTheDocument();
    expect(screen.queryByText(/Kassenzeichen/)).toBeNull();
  });

  it("turns its copy buttons off while the details are said not to match the letter", async () => {
    useMockApi();
    const user = userEvent.setup();
    const d = await detail("doc_parking");
    const item = d.items.find((i) => i.kind === "payment")!;
    renderWithProviders(<PayPanel item={item} doc={d.document} code={GIROCODES.itm_parking} onPaid={() => {}} />);
    expect(screen.getByRole("button", { name: "Copy IBAN" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "They don't match" }));
    // the person just said these are wrong: none of them is one tap away, and the panel says why
    expect(screen.queryByRole("button", { name: /^Copy / })).toBeNull();
    expect(screen.getByText(GIROCODE_MISMATCH_DETAILS)).toBeInTheDocument();
    expect(screen.getByText(GIROCODE_MISMATCH)).not.toHaveTextContent(/this code/);
    await user.click(screen.getByRole("button", { name: "They don't match" }));
    expect(screen.getByRole("button", { name: "Copy IBAN" })).toBeInTheDocument();
  });

  it("wraps a long payee and reference instead of widening the panel", async () => {
    const d = await detail("doc_parking");
    const item = d.items.find((i) => i.kind === "payment")!;
    const doc = { ...d.document, payment: { ...d.document.payment!, payee: "Zahlungsabwicklungsgesellschaftfürrundfunkbeitragsangelegenheiten", reference: "VWG-2026-0000000000000000000000000000055012" } };
    renderWithProviders(<PayPanel item={item} doc={doc} onPaid={() => {}} />);
    // (a reference is shown with non-breaking hyphens: it breaks anywhere only where it can't fit whole)
    for (const text of [doc.payment.payee, doc.payment.reference]) {
      expect(screen.getByText((_, el) => el?.tagName === "DD" && plainText(el.textContent ?? "") === text).className).toContain("wrap-anywhere");
    }
  });
});

// ------------------------------------------------------------------------------------------------
// In the app, on the static demo's data
// ------------------------------------------------------------------------------------------------

async function detail(id: string): Promise<DocumentDetail> {
  const srv = createMockServer({ staticDemo: false, latency: 0 });
  srv.openAllMail();
  return (await (await srv.handle("GET", `/documents/${id}`, new URLSearchParams(), undefined)).json()) as DocumentDetail;
}

describe("on a letter", () => {
  it("the utility statement's Pay panel shows its code", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<DocumentView detail={await detail("doc_nebenkosten")} />);
    await user.click(screen.getByRole("button", { name: /^Pay €184\.30/ }));
    const panel = await screen.findByRole("dialog", { name: "Pay" });
    // jsdom is phone-sized: a phone can't scan its own screen, so the code waits behind "Show code"
    await user.click(within(panel).getByRole("button", { name: "Show code" }));
    expect(within(panel).getByRole("img", { name: /^GiroCode: transfer €184\.30 to Wohnbau Musterstadt eG, reference MV-2025-0412 NK 2025$/ })).toBeInTheDocument();
  });

  it("the photographed parking fine asks for the paper letter first", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<DocumentView detail={await detail("doc_parking")} />);
    await user.click(screen.getByRole("button", { name: /^Pay €30\.00/ }));
    const panel = await screen.findByRole("dialog", { name: "Pay" });
    const section = within(panel).getByRole("region", { name: "GiroCode (EPC-QR)" });
    expect(within(section).getByRole("button", { name: "These match the letter" })).toBeInTheDocument();
    // "Mark as paid" stays in view below the taller panel
    expect(within(panel).getByRole("button", { name: "Mark as paid" }).parentElement!.className).toMatch(/\bsticky\b/);
  });

  it("the scam letter's bank details say why there is no code", async () => {
    renderWithProviders(<DocumentView detail={await detail("doc_scam")} />);
    const facts = screen.getByRole("region", { name: "Key facts" });
    expect(within(facts).getByText(/No code: this IBAN is not the one Beitragsservice Musterstadt used before/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Pay/ })).toBeNull();
  });
});

describe("on Today", () => {
  it("the TechMarkt reminder's Pay panel folds its code behind “Show code”", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<TodayView />);
    const top = await screen.findByRole("region", { name: "Top 3 this week" });
    await user.click(await within(top).findByRole("button", { name: "Pay: TechMarkt reminder" }));
    const panel = await screen.findByRole("dialog", { name: "Pay: TechMarkt reminder" });
    await user.click(await within(panel).findByRole("button", { name: "Show code" }));
    expect(within(panel).getByRole("img", { name: /^GiroCode: transfer €94\.99 to TechMarkt Online GmbH, reference RE-2026-084213$/ })).toBeInTheDocument();
  });
});
