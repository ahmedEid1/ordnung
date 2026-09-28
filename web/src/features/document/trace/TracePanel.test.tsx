import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { qk } from "@/api/hooks";
import { handleServerEvent } from "@/api/sse";
import { useMockApi } from "@/test/mockFetch";
import type { DocumentDetail, DocumentTrace, TraceRun } from "@/api/types";
import { DocumentView } from "../DocumentView";
import { TracePanel } from "./TracePanel";

const mode = vi.hoisted(() => ({ staticDemo: false }));
vi.mock("@/mocks/mode", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/mocks/mode")>()), isStaticDemo: () => mode.staticDemo }));

beforeEach(() => {
  mode.staticDemo = false;
});

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
    const tab = screen.getByRole("tab", { name: "How it was read" });
    expect(tab).toHaveAttribute("aria-selected", "false");
    await userEvent.click(tab);
    expect(router.state.location.search).toBe("?view=trace");
    expect(screen.getByRole("tab", { name: "How it was read" })).toHaveAttribute("aria-selected", "true");
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
    const rows = [...steps().children].map((li) => li.textContent ?? "");
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
    expect(compare).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(compare);
    // a toggle keeps its name: pressed says whether the comparison is shown
    expect(compare).toHaveAttribute("aria-pressed", "true");
    expect(compare).toHaveAccessibleName("Compare with reading 1");
    expect(compare).toHaveAttribute("aria-controls", "trace-compare");
    expect(screen.getByRole("status")).toHaveTextContent("What reading 2 decided differently from reading 1 is shown below.");
    const changes = await screen.findByRole("region", { name: "What reading 2 decided differently from reading 1" });
    expect(changes.id).toBe("trace-compare");
    expect(within(changes).getByRole("heading", { level: 2 })).toBeInTheDocument();
    await waitFor(() => expect(within(changes).getByText("Answer: didn't fit → usable")).toBeInTheDocument());
    expect(within(changes).getByText(/^Prompt version: 8\.6\.1 → 8\.7\.1/)).toBeInTheDocument();
    expect(within(changes).getByText("Claude, asked again")).toBeInTheDocument();
    expect(within(changes).getByText("Only in the earlier reading")).toBeInTheDocument();
    // one entry per step, however many ways it changed
    const entries = within(changes).getAllByRole("listitem");
    const extract = entries.filter((li) => li.firstElementChild?.textContent === "Claude reads the letter");
    expect(extract).toHaveLength(1);
    expect(extract[0]!.textContent).toMatch(/Answer: didn't fit → usable/);
    expect(extract[0]!.textContent).toMatch(/Prompt version: 8\.6\.1 → 8\.7\.1/);
    await userEvent.click(compare);
    expect(compare).toHaveAttribute("aria-pressed", "false");
    expect(compare).toHaveAccessibleName("Compare with reading 1");
    expect(screen.queryByRole("region", { name: /decided differently/ })).toBeNull();
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
    // the way to fill it is right here, and it says what that does (the test server is a demo: it replays)
    expect(screen.getByText(/reading it again replays Claude's recorded answers/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read it again" })).toBeInTheDocument();
    expect(screen.queryByText(/below the letter/)).toBeNull();
    first.unmount();

    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ detail: "boom" }), { status: 500, headers: { "Content-Type": "application/json" } }));
    renderWithProviders(<TracePanel detail={detail} />);
    expect(await screen.findByRole("heading", { name: "Couldn't load how this letter was read" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    // the tab keeps its heading in every state
    expect(screen.getByRole("heading", { level: 1, name: "Rental agreement — Beispielweg 5" })).toBeInTheDocument();
  });

  it("offers the OpenTelemetry export command for the reading shown, in the server's data folder", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_parking")} />);
    // the demo keeps its data in its own folder: `ordnung trace` needs it to find the letter
    expect(
      await screen.findByRole("button", { name: `Copy command to export this reading: ordnung trace doc_parking --otel -o trace.json --data-dir "${TEST_HEALTH.data_dir}"` }),
    ).toBeInTheDocument();
    // a long option never breaks after its dashes on a narrow screen ("--" / "otel")
    expect(screen.getByText("--otel")).toHaveClass("whitespace-nowrap");
    // an older reading: the command exports that one, not the newest
    await userEvent.click(screen.getByRole("radio", { name: "Reading 1" }));
    expect(
      await screen.findByRole("button", {
        name: `Copy command to export this reading: ordnung trace doc_parking --reading 1 --otel -o trace.json --data-dir "${TEST_HEALTH.data_dir}"`,
      }),
    ).toBeInTheDocument();
  });

  it("the online demo has no install: it says where the export is, without a command to copy", async () => {
    mode.staticDemo = true;
    const { srv } = useMockApi({ staticDemo: true });
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_nebenkosten")} />);
    expect(await screen.findByText(/exports a reading for an OpenTelemetry viewer/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Copy command/ })).toBeNull();
    // the option never breaks after its dashes on a phone ("--" / "otel")
    expect(screen.getByText("--otel")).toHaveClass("whitespace-nowrap");
  });

  it("the online demo can't read a letter again, so it never offers to", async () => {
    mode.staticDemo = true;
    const { srv } = useMockApi({ staticDemo: true });
    const detail = await detailOf(srv, "doc_parking");
    const first = renderWithProviders(<TracePanel detail={detail} />);
    expect(await screen.findByRole("button", { name: "Compare with reading 1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read again and compare" })).toBeNull();
    expect(screen.queryByText(/replays Claude's recorded answers/)).toBeNull();
    expect(screen.getByText("In your own Ordnung, “Read again and compare” asks Claude again and shows what changed.")).toBeInTheDocument();
    first.unmount();

    const empty: DocumentTrace = { doc_id: "doc_parking", run: null, runs: [], spans: [] };
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(empty), { status: 200, headers: { "Content-Type": "application/json" } }));
    renderWithProviders(<TracePanel detail={detail} />);
    expect(await screen.findByRole("heading", { name: "No reading kept for this letter" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read it again" })).toBeNull();
    expect(screen.queryByText(/replays Claude's recorded answers/)).toBeNull();
  });
});

describe("How this was read — what it links to and offers", () => {
  it("offers a date step's receipt only while the to-do still has that date; else says it changed", async () => {
    const { srv } = useMockApi();
    const detail = await detailOf(srv, "doc_parking");
    const fine = detail.items.find((i) => i.title === "Pay the parking fine")!;
    // the person moved the date after this reading
    const moved = { ...fine, due_date: "2026-10-07", due_date_source: "manual" as const, computation: { ...fine.computation!, due_date: "2026-10-07", send_by: "2026-10-06" } };
    renderWithProviders(<TracePanel detail={{ ...detail, items: detail.items.map((i) => (i.id === fine.id ? moved : i)) }} />);
    await userEvent.click(await within(await screen.findByRole("list", { name: "Steps of this reading" })).findByRole("button", { name: /^Dates computed/ }));
    const dates = screen.getByRole("list", { name: /^Steps of “Dates computed”/ });
    await userEvent.click(within(dates).getByRole("button", { name: /^Pay the parking fine/ }));
    expect(within(dates).queryByText("The rules engine's receipt for this date:")).toBeNull();
    expect(within(dates).getByText(/The to-do's date has changed since this reading — it is now Wed 7 Oct \(you set it yourself\)/)).toBeInTheDocument();
    expect(within(dates).queryByRole("button", { name: /^Why this date\?/ })).toBeNull();
    await userEvent.click(within(dates).getByRole("button", { name: /^Why the date is Wed 7 Oct now/ }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("makes a step with nothing more to show a plain row, not a button that opens to nothing", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_nebenkosten")} />);
    const list = await screen.findByRole("list", { name: "Steps of this reading" });
    const sender = [...list.children].find((li) => /Sender · Known/.test(li.textContent ?? ""))!;
    expect(within(sender as HTMLElement).queryByRole("button")).toBeNull();
    expect(within(list).getByRole("button", { name: /^Claude reads the letter/ })).toHaveAttribute("aria-expanded", "false");
  });

  it("compares with the newest earlier reading that was done, not a paused attempt", async () => {
    const { srv } = useMockApi();
    const detail = await detailOf(srv, "doc_parking");
    const res = await srv.handle("GET", "/documents/doc_parking/trace", new URLSearchParams(), undefined);
    const trace = (await res.json()) as DocumentTrace;
    const [second, first] = trace.runs as [TraceRun, TraceRun];
    const paused: TraceRun = { ...second, trace_id: "trc_paused", reading: 2, status: "error", ended: "paused", error: "Paused: Claude's usage limit was reached." };
    const newest: TraceRun = { ...second, reading: 3 };
    const shown: DocumentTrace = { ...trace, run: newest, runs: [newest, paused, first] };
    const handle = srv.handle.bind(srv);
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const path = url.pathname.replace(/^\/api/, "");
      if (path.endsWith("/trace")) return new Response(JSON.stringify(shown), { status: 200, headers: { "Content-Type": "application/json" } });
      return handle("GET", path, url.searchParams, undefined);
    });
    renderWithProviders(<TracePanel detail={detail} />);
    expect(await screen.findByRole("button", { name: "Compare with reading 1" })).toBeInTheDocument();
  });

  it("offers to read the letter again and compare, and says when a new reading is on its way", async () => {
    const { srv, calls } = useMockApi();
    const detail = await detailOf(srv, "doc_nebenkosten");
    const first = renderWithProviders(<TracePanel detail={detail} />);
    const readAgain = await screen.findByRole("button", { name: "Read again and compare" });
    readAgain.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/documents/doc_nebenkosten/reprocess")).toBe(true));
    // the button is busy, then gone: focus waits on the reading's heading, never on the page's body
    await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: /^Read on/ })).toHaveFocus());
    // the new reading, when it is there (the server says so), opens compared with the one before
    await waitFor(async () => expect((await detailOf(srv, "doc_nebenkosten")).document.status).not.toBe("processing"));
    handleServerEvent(first.client, { type: "document.processed", data: { doc_id: "doc_nebenkosten", status: "processed" } });
    expect(await screen.findByRole("region", { name: "What reading 2 decided differently from reading 1" }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: /^Reading 2 · read again on/ })).toBeInTheDocument();
    // and moves on to what changed
    await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: "What reading 2 decided differently from reading 1" })).toHaveFocus());
    first.unmount();

    renderWithProviders(<TracePanel detail={{ ...detail, document: { ...detail.document, status: "processing" } }} />);
    expect(await screen.findByText("Being read again — the new reading appears here when it's done.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read again and compare" })).toBeNull();
  });

  it("says reading again asks Claude again, outside the demo", async () => {
    const { srv } = useMockApi();
    const client = makeTestQueryClient();
    client.setQueryData(qk.health, { ...TEST_HEALTH, demo: false });
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_nebenkosten")} />, { client });
    expect(await screen.findByText("Reading it again asks Claude again, with your Claude account.")).toBeInTheDocument();
  });

  it("gives a private letter its own words, with no Read again it doesn't have", async () => {
    const { srv } = useMockApi();
    const detail = await detailOf(srv, "doc_lease");
    const empty: DocumentTrace = { doc_id: "doc_lease", run: null, runs: [], spans: [] };
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(empty), { status: 200, headers: { "Content-Type": "application/json" } }));
    renderWithProviders(<TracePanel detail={{ ...detail, document: { ...detail.document, ai_private: true } }} />);
    expect(await screen.findByText(/It is kept private, so Claude never reads it/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read it again" })).toBeNull();
  });

  it("moves focus to the way back when the reading picked is no longer kept", async () => {
    const { srv } = useMockApi();
    const detail = await detailOf(srv, "doc_parking");
    renderWithProviders(<TracePanel detail={detail} />);
    const reading1 = await screen.findByRole("radio", { name: "Reading 1" });
    const handle = srv.handle.bind(srv);
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.searchParams.get("run")) return new Response(JSON.stringify({ detail: "gone" }), { status: 404, headers: { "Content-Type": "application/json" } });
      return handle("GET", url.pathname.replace(/^\/api/, ""), url.searchParams, undefined);
    });
    await userEvent.click(reading1);
    const back = await screen.findByRole("button", { name: "Show the newest reading" });
    await waitFor(() => expect(back).toHaveFocus());
    // the way back goes away when pressed: focus goes to the newest reading, not the page's body
    await userEvent.keyboard("{Enter}");
    const newest = await screen.findByRole("heading", { level: 2, name: /^Reading 2 · read again on/ });
    await waitFor(() => expect(newest).toHaveFocus());
  });

  it("never lists the rules a date step only checked as applied", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_parking")} />);
    await userEvent.click(await within(await screen.findByRole("list", { name: "Steps of this reading" })).findByRole("button", { name: /^Dates computed/ }));
    const dates = screen.getByRole("list", { name: /^Steps of “Dates computed”/ });
    await userEvent.click(within(dates).getByRole("button", { name: /^Pay the parking fine/ }));
    expect(within(dates).getByRole("button", { name: /Why this date\?/ })).toBeInTheDocument();
    expect(screen.queryByText("Rules applied")).toBeNull();
    expect(screen.queryByText(/§ 187 Abs\. 1 BGB/)).toBeNull();
  });

  it("names the law of a deadline the law adds", async () => {
    // the dismissal is in the New-mail tray: open it
    const { srv } = useMockApi({ full: true });
    renderWithProviders(<TracePanel detail={await detailOf(srv, "doc_dismissal")} />);
    await userEvent.click(await within(await screen.findByRole("list", { name: "Steps of this reading" })).findByRole("button", { name: /^To-dos filed/ }));
    const filed = screen.getByRole("list", { name: /^Steps of “To-dos filed”/ });
    const law = within(filed).getAllByRole("button").find((b) => /Deadline the law adds/.test(b.textContent ?? ""))!;
    await userEvent.click(law);
    expect(within(filed).getByText("The law")).toBeInTheDocument();
    expect(within(filed).getByText(/^§ 4 S\. 1 KSchG; § 7 KSchG$|^§ 38 Abs\. 1 SGB III/)).toBeInTheDocument();
  });
});

describe("The letter tab", () => {
  it("controls every part of the letter: its verdict and, after the pages, the rest", async () => {
    const { srv } = useMockApi();
    const detail = await detailOf(srv, "doc_nebenkosten");
    renderWithProviders(<DocumentView detail={detail} />, { route: "/documents/doc_nebenkosten" });
    const tab = screen.getByRole("tab", { name: "The letter" });
    const ids = (tab.getAttribute("aria-controls") ?? "").split(" ");
    expect(ids).toHaveLength(2);
    const panels = ids.map((id) => document.getElementById(id)!);
    for (const panel of panels) {
      expect(panel).toHaveAttribute("role", "tabpanel");
      expect(panel).toHaveAccessibleName("The letter");
    }
    // the explanation, the to-dos and the footer are inside the tab's panels
    expect(panels[1]!.querySelector("footer")).not.toBeNull();
  });
});
