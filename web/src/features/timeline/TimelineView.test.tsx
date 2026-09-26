import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { qk } from "@/api/hooks";
import type { Item, Lane, Profile, TimelineEntry } from "@/api/types";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { createMockServer } from "@/mocks/server";
import { makeTestQueryClient, renderWithProviders, TEST_TODAY } from "@/test/render";
import { defaultLaneRange } from "@/features/lanes/scale";
import { TimelineView } from "./TimelineView";

async function seededClient() {
  const srv = createMockServer({ staticDemo: false, latency: 0 });
  srv.openAllMail();
  const get = async <T,>(path: string, q = "") => (await (await srv.handle("GET", path, new URLSearchParams(q), undefined)).json()) as T;
  const { from, to } = defaultLaneRange(TEST_TODAY);
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.lanes(from, to), await get<Lane[]>("/lanes", `from=${from}&to=${to}`));
  qc.setQueryData(qk.timeline(from, to), await get<TimelineEntry[]>("/timeline", `from=${from}&to=${to}`));
  qc.setQueryData(qk.items.list({}), await get<Item[]>("/items"));
  qc.setQueryData(qk.profile, await get<Profile>("/profile"));
  return qc;
}

describe("Timeline page", () => {
  it("shows the life lanes and every date month by month, without raw enum values", async () => {
    const client = await seededClient();
    const { container } = renderWithProviders(<TimelineView />, { client, route: "/timeline" });

    expect(screen.getByRole("heading", { level: 1, name: "Timeline" })).toBeInTheDocument();
    const lanesRegion = screen.getByRole("region", { name: "Your year ahead" });
    expect(lanesRegion).toHaveAttribute("data-tour", "timeline-lanes");
    const lanes = within(within(lanesRegion).getByRole("list", { name: "Lanes" })).getAllByRole("listitem").map((l) => l.getAttribute("aria-label"));
    expect(lanes).toEqual(expect.arrayContaining(["Residence", "Passport", "Tax", "Phone · FunkNetz", "Study", "Money"]));
    expect(within(lanesRegion).getByRole("button", { name: /^Residence permit\..*Opens the letter/ })).toBeInTheDocument();
    expect(within(lanesRegion).getByText(/Not legal advice/)).toBeInTheDocument();

    const list = screen.getByRole("region", { name: "Every date" });
    expect(within(list).getByRole("heading", { name: /September 2026/ })).toBeInTheDocument();
    expect(within(list).getByLabelText(/^Today, Monday, 28 September 2026/)).toBeInTheDocument();
    // items open the letter they came from; contracts open the contract
    expect(within(list).getByRole("link", { name: /Pay the parking fine/ })).toHaveAttribute("href", expect.stringMatching(/^\/documents\//));
    expect(within(list).getByRole("link", { name: /FunkNetz Allnet L: current term ends/ })).toHaveAttribute("href", "/contracts?contract=ctr_phone");
    expect(screen.getByRole("button", { name: "Add to my calendar" })).toBeInTheDocument();

    assertNoRawEnumsInElement(container);
  });

  it("filters by area from the URL (Today's area tiles link here) — lanes and list", async () => {
    const client = await seededClient();
    renderWithProviders(<TimelineView />, { client, route: "/timeline?area=residence" });
    const lanesRegion = screen.getByRole("region", { name: "Your year ahead" });
    expect(within(within(lanesRegion).getByRole("list", { name: "Lanes" })).getAllByRole("listitem").map((l) => l.getAttribute("aria-label"))).toEqual(["Residence", "Passport"]);
    expect(within(lanesRegion).getByText(/showing Residence only/)).toBeInTheDocument();
    const list = screen.getByRole("region", { name: "Every date" });
    expect(within(list).getByRole("combobox", { name: "Life area" })).toHaveValue("residence");
    expect(within(list).queryByText("Rent for October")).not.toBeInTheDocument();
    expect(within(list).getByText("Ausländerbehörde: extend residence permit")).toBeInTheDocument();

    fireEvent.click(within(lanesRegion).getByRole("button", { name: "Show all areas" }));
    expect(within(within(lanesRegion).getByRole("list", { name: "Lanes" })).getAllByRole("listitem").length).toBeGreaterThan(5);
  });

  it("hides past dates with the switch", async () => {
    const client = await seededClient();
    renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    const list = screen.getByRole("region", { name: "Every date" });
    const before = within(list).getAllByRole("listitem").length;
    fireEvent.click(within(list).getByRole("switch", { name: "Show past" }));
    const after = within(list).getAllByRole("listitem").length;
    expect(after).toBeLessThan(before);
    expect(within(list).queryByRole("heading", { name: /June 2026/ })).not.toBeInTheDocument();
  });

  it("jumps from a lane marker without a page of its own to its entry in the list", async () => {
    const client = await seededClient();
    const { container } = renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    const lanesRegion = screen.getByRole("region", { name: "Your year ahead" });
    fireEvent.click(within(lanesRegion).getByRole("button", { name: /^Rent · Mon 5 Oct.*Shows it in the list below/ }));
    const row = container.querySelector("[data-date='2026-10-05'] > *");
    expect(row?.className).toMatch(/bg-marker/);
  });

  it("opens the calendar guide after downloading the calendar file", async () => {
    const client = await seededClient();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    fireEvent.click(screen.getByRole("button", { name: "Add to my calendar" }));
    expect(click).toHaveBeenCalledTimes(1);
    const dialog = await screen.findByRole("dialog", { name: "Add your dates to your calendar" });
    expect(within(dialog).getByText(/calendar\.google\.com/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("radio", { name: "Outlook" }));
    expect(within(dialog).getByText(/Upload from file/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Reminders: 14, 7, 3 and 1 days/)).toBeInTheDocument();
    click.mockRestore();
  });
});
