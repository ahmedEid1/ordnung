/**
 * Settings → Profile & address → "I moved": a move is told only by the person, only next to an address they
 * changed (the first address is no move), with the day they moved in; saving lists who needs the new address on
 * Today. While a move stands, one line says so, links to the checklist and stops it (with Undo).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { refreshMovingIdeas } from "@/mocks/moving";
import SettingsPage from "@/pages/SettingsPage";

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
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const OLD = "Beispielweg 5\n12345 Musterstadt";
const NEW = "Neue Allee 7\n54321 Beispielstadt";

async function openProfile() {
  const user = userEvent.setup();
  renderWithProviders(
    <>
      <SettingsPage />
      <Toaster />
    </>,
    { route: "/settings?section=profile" },
  );
  const address = await screen.findByLabelText("Postal address");
  return { user, address };
}

const moveBox = () => screen.queryByRole("checkbox", { name: /I moved — list who needs my new address/ });

describe("I moved", () => {
  it("is offered only next to a changed address that was saved before", async () => {
    useMockApi();
    const { user, address } = await openProfile();
    expect(moveBox()).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/^Phone/), "9"); // another field: no move
    expect(moveBox()).not.toBeInTheDocument();
    await user.clear(address);
    await user.type(address, NEW);
    expect(moveBox()).toBeInTheDocument();
    expect(moveBox()).not.toBeChecked();
    expect(screen.getByText("Bürgeramt")).toHaveAttribute("lang", "de");
    // the address typed back as it was: no move
    await user.clear(address);
    await user.type(address, OLD);
    expect(moveBox()).not.toBeInTheDocument();
  });

  it("is not offered for the first address ever entered", async () => {
    const { srv } = useMockApi();
    srv.db.state.profile.address = "";
    const { user, address } = await openProfile();
    await user.type(address, NEW);
    expect(moveBox()).not.toBeInTheDocument();
  });

  it("saves the day moved in and the address before, and says Today lists who needs the new one", async () => {
    const { calls } = useMockApi();
    const { user, address } = await openProfile();
    await user.clear(address);
    await user.type(address, NEW);
    await user.click(moveBox()!);
    const day = screen.getByLabelText("Moved in on");
    expect(day).toHaveValue("2026-09-28"); // today, to start with
    expect(day).toHaveAttribute("min", "2026-04-01");
    expect(day).toHaveAttribute("max", "2026-12-27");
    await user.clear(day);
    await user.type(day, "2026-09-21");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT" && c.path === "/profile")?.body).toMatchObject({
        address: NEW,
        moved_on: "2026-09-21",
        old_address: OLD,
      }),
    );
    expect(await screen.findByText("Today lists who needs your new address.")).toBeInTheDocument();
    // the move now stands: its line replaces the box
    expect(await screen.findByText(/You moved in on Mon 21 Sep\./)).toBeInTheDocument();
    expect(moveBox()).not.toBeInTheDocument();
  });

  it("without the box ticked, a new address is saved and no move is told", async () => {
    const { calls } = useMockApi();
    const { user, address } = await openProfile();
    await user.clear(address);
    await user.type(address, NEW);
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const body = calls.find((c) => c.method === "PUT")!.body as Record<string, unknown>;
    expect(body).not.toHaveProperty("moved_on");
    expect(body).not.toHaveProperty("old_address");
    expect(await screen.findByText("New letters use this name and address.")).toBeInTheDocument();
  });

  it("points to a day outside the last six months or the next three instead of saving", async () => {
    const { calls } = useMockApi();
    const { user, address } = await openProfile();
    await user.clear(address);
    await user.type(address, NEW);
    await user.click(moveBox()!);
    const day = screen.getByLabelText("Moved in on");
    await user.clear(day);
    await user.type(day, "2026-01-15");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(day).toHaveAccessibleDescription(/last six months or the next three/);
    await waitFor(() => expect(day).toHaveFocus());
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("while a move stands, says so, links to the checklist, and stops it with Undo", async () => {
    const { srv, calls } = useMockApi();
    srv.db.state.profile = { ...srv.db.state.profile, address: NEW, moved_on: "2026-09-21", old_address: OLD };
    refreshMovingIdeas(srv.db);
    const { user, address } = await openProfile();
    const line = (await screen.findByText(/You moved in on Mon 21 Sep\./)).closest("p")!;
    expect(within(line).getByRole("link", { name: "Open your moving checklist" })).toHaveAttribute("href", "/#moving-checklist");
    await user.click(within(line).getByRole("button", { name: "Stop the checklist" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ moved_on: "", old_address: "" }));
    const toast = await screen.findByText("Moving checklist stopped");
    await waitFor(() => expect(screen.queryByText(/You moved in on/)).not.toBeInTheDocument());
    await waitFor(() => expect(address).toHaveFocus());
    await user.click(within(toast.closest("[data-toast]") as HTMLElement).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({ moved_on: "2026-09-21", old_address: OLD }));
    expect(await screen.findByText(/You moved in on Mon 21 Sep\./)).toBeInTheDocument();
  });

  it("once everyone on the checklist has the new address, says so instead of linking to it", async () => {
    const { srv } = useMockApi();
    srv.db.state.profile = { ...srv.db.state.profile, address: NEW, moved_on: "2026-09-21", old_address: OLD };
    refreshMovingIdeas(srv.db);
    const rows = srv.db.state.suggestions.filter((s) => s.rule_id === "moved_house");
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) row.status = "done";
    await openProfile();
    const line = (await screen.findByText(/You moved in on Mon 21 Sep\./)).closest("p")!;
    expect(await within(line).findByText("Everyone on your moving checklist has your new address.")).toBeInTheDocument();
    expect(within(line).queryByRole("link", { name: "Open your moving checklist" })).toBeNull();
    expect(within(line).getByRole("button", { name: "Stop the checklist" })).toBeInTheDocument();
  });

  it("says nothing of a move more than six months ago", async () => {
    const { srv } = useMockApi();
    srv.db.state.profile = { ...srv.db.state.profile, moved_on: "2026-01-02", old_address: OLD };
    await openProfile();
    expect(screen.queryByText(/You moved in on/)).not.toBeInTheDocument();
  });
});
