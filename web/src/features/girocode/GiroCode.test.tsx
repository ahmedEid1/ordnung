/**
 * The GiroCode block of the pay panels: the code (drawn from the server's payload), folded on
 * Today, the comparison with the paper letter for details read from a photo, why there is no
 * code — and the same on the static demo's letters (utility statement, parking fine, scam).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DocumentDetail, GiroCode } from "@/api/types";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { createMockServer } from "@/mocks/server";
import { GIROCODES } from "@/mocks/data/girocodes";
import { DocumentView } from "@/features/document/DocumentView";
import { TodayView } from "@/features/today/TodayView";
import { GIROCODE_HINT, GiroCodeSection, giroCodeLabel } from "./GiroCode";
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

describe("details read from a photo", () => {
  it("asks to compare them with the paper letter, then shows the code", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderSection(GIROCODES.itm_parking);
    const section = screen.getByRole("region", { name: "GiroCode (EPC-QR)" });
    expect(section).toHaveTextContent("the amount, the IBAN and the reference were read by AI from a photo");
    expect(within(section).queryByRole("img")).toBeNull();
    await user.click(within(section).getByRole("button", { name: "These match the letter" }));
    const call = calls.find((c) => c.method === "POST");
    expect(call).toEqual({
      method: "POST",
      path: "/items/itm_parking/girocode/confirm",
      body: { payee: "Stadtkasse Musterstadt", iban: "DE51123456000000100017", reference: "OA-VW-2026-55012", amount: 30 },
    });
    expect(await screen.findByText("GiroCode ready")).toBeInTheDocument();
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
    expect(within(panel).getByRole("img", { name: /^GiroCode: transfer €184\.30 to Wohnbau Musterstadt eG, reference MV-2025-0412 NK 2025$/ })).toBeInTheDocument();
  });

  it("the photographed parking fine asks for the paper letter first, and then shows the code", async () => {
    useMockApi();
    const user = userEvent.setup();
    const { client } = renderWithProviders(
      <>
        <DocumentView detail={await detail("doc_parking")} />
        <Toaster />
      </>,
    );
    client.setQueryData(["documents", "detail", "doc_parking"], await detail("doc_parking"));
    await user.click(screen.getByRole("button", { name: /^Pay €30\.00/ }));
    const panel = await screen.findByRole("dialog", { name: "Pay" });
    await user.click(within(panel).getByRole("button", { name: "These match the letter" }));
    expect(await screen.findByText("GiroCode ready")).toBeInTheDocument();
    await waitFor(() =>
      expect((client.getQueryData(["documents", "detail", "doc_parking"]) as DocumentDetail).girocodes.find((g) => g.item_id === "itm_parking")).toMatchObject({ status: "ready", checked: true }),
    );
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
