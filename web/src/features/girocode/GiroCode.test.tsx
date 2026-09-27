/**
 * The GiroCode block of the pay panels: the code (drawn from the server's payload), folded on
 * Today, the comparison with the paper letter for details read from a photo, why there is no
 * code — and the same on the static demo's letters (utility statement, parking fine, scam).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
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
import { GIROCODE_CHECKED, GIROCODE_HINT, GiroCodeSection, giroCodeLabel } from "./GiroCode";
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

  it("says when the person compared the details with the paper letter", () => {
    renderSection({ ...ready, checked: true });
    expect(screen.getByText("You compared these details with the paper letter.")).toBeInTheDocument();
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

  it("labels a code without an amount or reference plainly", () => {
    expect(giroCodeLabel("BCD\n002\n1\nSCT\n\nStadtkasse\nDE05123456000004455660")).toBe("GiroCode: transfer to Stadtkasse");
  });
});

describe("no code", () => {
  it("says why, loudly for a scam", () => {
    renderSection(GIROCODES.itm_scam_demand);
    const section = screen.getByRole("region", { name: "GiroCode (EPC-QR)" });
    expect(section).toHaveTextContent("No code: this IBAN is not the one Beitragsservice Musterstadt used before.");
    expect(section.className).toContain("bg-danger-soft");
    expect(within(section).queryByRole("img")).toBeNull();
    expect(within(section).queryByRole("button")).toBeNull();
  });

  it("stays quiet where the pay panel already explains it", () => {
    for (const reason of ["no_iban", "incoming", "settled"] as const) {
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

  it("shows the server's refusal when the details changed meanwhile", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    // the app's client: a failed change says what failed and why (a toast)
    const client = createQueryClient();
    client.setQueryData(qk.health, TEST_HEALTH);
    renderWithProviders(
      <>
        <GiroCodeSection code={{ ...(GIROCODES.itm_parking as Extract<GiroCode, { status: "blocked" }>), values: { payee: "Stadtkasse Musterstadt", iban: "DE51123456000000100017", reference: "OA-VW-2026-55012", amount: 35 } }} docId="doc_parking" />
        <Toaster />
      </>,
      { client },
    );
    await user.click(screen.getByRole("button", { name: "These match the letter" }));
    expect(await screen.findByText("Couldn't confirm the payment details")).toBeInTheDocument();
    expect(screen.getByText("The payment details changed since you looked at them. Please compare them again.")).toBeInTheDocument();
    expect(srv.db.state.activity.some((a) => a.kind === "payment.checked")).toBe(false);
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
    // "I've paid it" stays in view below the taller panel
    expect(within(panel).getByRole("button", { name: "I've paid it" }).parentElement!.className).toMatch(/\bsticky\b/);
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
