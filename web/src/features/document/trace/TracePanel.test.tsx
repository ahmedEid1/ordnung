import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import type { DocumentDetail, DocumentTrace } from "@/api/types";
import { DocumentView } from "../DocumentView";
import { TracePanel } from "./TracePanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

async function detailOf(srv: ReturnType<typeof useMockApi>["srv"], id: string): Promise<DocumentDetail> {
  const res = await srv.handle("GET", `/documents/${id}`, new URLSearchParams(), undefined);
  return (await res.json()) as DocumentDetail;
}

const steps = () => screen.getByRole("list", { name: "Steps of this reading" });

describe("How this was read", () => {
  it("is a tab of the letter's page, kept in the address, with the letter's title as its heading", async () => {
    const { srv } = useMockApi();
    const detail = await detailOf(srv, "doc_nebenkosten");
    const { router } = renderWithProviders(<DocumentView detail={detail} />, { route: "/documents/doc_nebenkosten" });
    const tab = screen.getByRole("tab", { name: "How this was read" });
    expect(tab).toHaveAttribute("aria-selected", "false");
    await userEvent.click(tab);
    expect(router.state.location.search).toBe("?view=trace");
    expect(screen.getByRole("tab", { name: "How this was read" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { level: 1, name: "Utility cost statement 2025" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: /^Read on 11 Sep 2026/ })).toBeInTheDocument();
    // the letter's verdict and the rest of the panel are not shown under this tab
    expect(screen.queryByRole("article")).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "The letter" }));
    expect(router.state.location.search).toBe("");
  });

  it("shows the reading's summary and one row per stage, in the order they ran", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_nebenkosten")} />);
    await screen.findByRole("heading", { level: 2, name: /^Read on/ });
    const summary = screen.getByRole("region", { name: /^Read on/ });
    expect(within(summary).getByText("Calls to Claude")).toBeInTheDocument();
    expect(within(summary).getByText("API-equivalent cost")).toBeInTheDocument();
    expect(within(summary).getByText("Filed")).toBeInTheDocument();
    const rows = within(steps())
      .getAllByRole("button", { expanded: false })
      .map((b) => b.textContent ?? "");
    expect(rows[0]).toMatch(/^Text layer/);
    expect(rows[1]).toMatch(/^Claude reads the letter/);
    expect(rows[2]).toMatch(/^Quotes checked on the page/);
    expect(rows.some((r) => r.startsWith("Wohnbau Musterstadt eG") && /Sender · Known/.test(r))).toBe(true);
    expect(rows.some((r) => /^Dates computed/.test(r))).toBe(true);
    expect(rows[rows.length - 1]).toMatch(/^To-dos filed/);
    // never the letter's text: the quotes' wording is nowhere in the panel
    expect(document.body.textContent).not.toMatch(/Bitte überweisen/);
  });

  it("opens a model step to its prompt, tokens and cost, and a date to the rules engine's receipt", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_nebenkosten")} />);
    const claude = await within(await screen.findByRole("list", { name: "Steps of this reading" })).findByRole("button", { name: /^Claude reads the letter/ });
    await userEvent.click(claude);
    expect(claude).toHaveAttribute("aria-expanded", "true");
    const panel = document.getElementById(claude.getAttribute("aria-controls")!)!;
    expect(within(panel).getByText("Prompt")).toBeInTheDocument();
    expect(within(panel).getByText(/^extract, version/)).toBeInTheDocument();
    expect(within(panel).getByText("Tokens")).toBeInTheDocument();
    expect(within(panel).getByText("API-equivalent cost")).toBeInTheDocument();

    await userEvent.click(within(steps()).getByRole("button", { name: /^Dates computed/ }));
    const dates = screen.getByRole("list", { name: /^Steps of “Dates computed”/ });
    const date = within(dates).getAllByRole("button")[0]!;
    expect(date.textContent).toMatch(/→ Fri 9 Oct/);
    await userEvent.click(date);
    expect(within(dates).getByText("What the letter says")).toBeInTheDocument();
    expect(within(dates).getByText("A fixed date: 9 Oct 2026")).toBeInTheDocument();
  });

  it("links a date's step to the same “Why this date?” receipt the letter shows", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_parking")} />);
    await userEvent.click(await within(await screen.findByRole("list", { name: "Steps of this reading" })).findByRole("button", { name: /^Dates computed/ }));
    const dates = screen.getByRole("list", { name: /^Steps of “Dates computed”/ });
    const date = within(dates).getByRole("button", { name: /^Pay the parking fine/ });
    expect(date.textContent).toMatch(/Please check/);
    await userEvent.click(date);
    expect(within(dates).getByText("1 week after the day it reached you")).toBeInTheDocument();
    await userEvent.click(within(dates).getByRole("button", { name: /Why this date\?/ }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("shows a repair call linked to the call it retried, and what a later reading decided differently", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_parking")} />);
    expect(await screen.findByRole("heading", { level: 2, name: /^Reading 2 · read again on 25 Sep 2026/ })).toBeInTheDocument();
    // reading 1: the first answer didn't fit, the repair fixed it (opened: worth seeing first)
    await userEvent.click(screen.getByRole("radio", { name: "Reading 1" }));
    expect(await screen.findByRole("heading", { level: 2, name: /^Reading 1 · read on/ })).toBeInTheDocument();
    expect(within(steps()).getByText("Answer didn't fit — asked again")).toBeInTheDocument();
    const repair = within(steps()).getByRole("button", { name: /^Claude, asked again/ });
    await userEvent.click(repair);
    const retried = screen.getByRole("button", { name: "the call above" });
    await userEvent.click(retried);
    await waitFor(() => expect(within(steps()).getByRole("button", { name: /^Claude reads the letter/ })).toHaveAttribute("aria-expanded", "true"));
    // no earlier reading to compare reading 1 with
    expect(screen.queryByRole("button", { name: /^Compare with reading/ })).toBeNull();

    await userEvent.click(screen.getByRole("radio", { name: "Reading 2" }));
    const compare = await screen.findByRole("button", { name: "Compare with reading 1" });
    await userEvent.click(compare);
    expect(compare).toHaveAttribute("aria-pressed", "true");
    const changes = await screen.findByRole("region", { name: "What reading 2 decided differently from reading 1" });
    await waitFor(() => expect(within(changes).getByText("Answer: didn't fit → usable")).toBeInTheDocument());
    expect(within(changes).getByText(/^Prompt version: 8\.6\.1 → 8\.7\.1/)).toBeInTheDocument();
    expect(within(changes).getByText("Claude, asked again")).toBeInTheDocument();
    expect(within(changes).getByText("Only in the earlier reading")).toBeInTheDocument();
  });

  it("shows a photo's pages transcribed by Claude", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_passport")} />);
    const photo = await within(await screen.findByRole("list", { name: "Steps of this reading" })).findByRole("button", { name: /^Read from the photo/ });
    await userEvent.click(photo);
    const pages = screen.getByRole("list", { name: /^Steps of “Read from the photo”/ });
    expect(within(pages).getByRole("button", { name: /^Page 1 read by Claude/ })).toBeInTheDocument();
    expect(within(steps()).getByText(/^No text layer — 1 page to read from the photo/)).toBeInTheDocument();
  });

  it("says so when no reading is kept, and when loading fails", async () => {
    const { srv } = useMockApi();
    const detail = await detailOf(srv, "doc_lease");
    const empty: DocumentTrace = { doc_id: "doc_lease", run: null, runs: [], spans: [] };
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(empty), { status: 200, headers: { "Content-Type": "application/json" } }));
    const first = renderWithProviders(<TracePanel detail={detail} />);
    expect(await screen.findByRole("heading", { name: "No reading kept for this letter" })).toBeInTheDocument();
    first.unmount();

    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ detail: "boom" }), { status: 500, headers: { "Content-Type": "application/json" } }));
    renderWithProviders(<TracePanel detail={detail} />);
    expect(await screen.findByRole("heading", { name: "Couldn't load how this letter was read" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    // the tab keeps its heading in every state
    expect(screen.getByRole("heading", { level: 1, name: "Rental agreement — Beispielweg 5" })).toBeInTheDocument();
  });

  it("offers the OpenTelemetry export command for this letter", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_nebenkosten")} />);
    expect(await screen.findByRole("button", { name: /Copy command to export this reading: ordnung trace doc_nebenkosten --otel -o trace\.json/ })).toBeInTheDocument();
    // a long option never breaks after its dashes on a narrow screen ("--" / "otel")
    expect(screen.getByText("--otel")).toHaveClass("whitespace-nowrap");
  });
});
