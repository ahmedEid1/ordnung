/**
 * Settings → Profile & address → "Your household" (computer only): add, edit and remove people, each refusal under
 * the field it is about, Undo of a removal (the same person, the same id, so their letters are filed again), the
 * reload when another window changed the list, and an add not pressed yet counting as unsaved.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Household } from "@/api/types";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi, type FetchCall } from "@/test/mockFetch";
import SettingsPage from "@/pages/SettingsPage";
import { HouseholdCard } from "./HouseholdCard";

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

const ALEX = { id: "hhm_000000000001", name: "Alex Rivera", signs: true };
const MIA = { id: "hhm_000000000002", name: "Mia Rivera", signs: false };

const card = () => screen.getByRole("region", { name: "Your household" });
const people = () => within(card()).queryAllByRole("listitem");
const addField = () => within(screen.getByRole("form", { name: "Add someone to your household" })).getByRole("textbox", { name: "Name" });
const puts = (calls: FetchCall[]) => calls.filter((c) => c.method === "PUT" && c.path === "/household");

type MockApi = ReturnType<typeof useMockApi>;

/** The card on its own, on the mock API, with the household as given. */
function renderCard(api: MockApi, household?: Partial<MockApi["srv"]["db"]["state"]["household"]>) {
  if (household) api.srv.db.state.household = { format: 1, members: [], links: {}, ...household };
  const user = userEvent.setup();
  renderWithProviders(
    <>
      <HouseholdCard />
      <Toaster />
    </>,
  );
  return { ...api, user };
}

describe("Your household (Settings)", () => {
  it("says who it is for and that Claude never sees it, and starts with no one", async () => {
    renderCard(useMockApi());
    expect(await screen.findByText("No one yet.")).toBeInTheDocument();
    expect(card()).toHaveTextContent(
      "The people whose letters come to you too — a partner, your children. Ordnung asks before it files a letter for one of them. Claude never sees this list.",
    );
    expect(addField()).not.toHaveAttribute("placeholder");
    const signs = within(card()).getByRole("checkbox", { name: /Signs their own letters/ });
    expect(signs).toBeChecked();
    expect(card()).toHaveTextContent("Untick for a child: a reply to their letter then goes out in your name.");
  });

  it("adds a person as typed, says so, and is ready for the next one", async () => {
    const { user, calls } = renderCard(useMockApi());
    await user.type(await screen.findByRole("textbox", { name: "Name" }), "  Alex   Rivera ");
    await user.click(within(card()).getByRole("button", { name: "Add to household" }));
    expect(await screen.findByText("Added Alex Rivera")).toBeInTheDocument();
    expect(puts(calls).at(-1)?.body).toEqual({ base: "4f53cda18c2baa0c", members: [{ id: null, name: "Alex Rivera", signs: true }], also_file: [] });
    await waitFor(() => expect(people()).toHaveLength(1));
    expect(people()[0]).toHaveTextContent("Alex Rivera");
    expect(people()[0]).toHaveTextContent("Signs their own letters · No letters yet");
    expect(addField()).toHaveValue("");
    expect(addField()).toHaveFocus();
  });

  it("adds someone who doesn't sign their letters", async () => {
    const { user, calls } = renderCard(useMockApi());
    await user.type(await screen.findByRole("textbox", { name: "Name" }), "Mia Rivera");
    await user.click(within(card()).getByRole("checkbox", { name: /Signs their own letters/ }));
    await user.click(within(card()).getByRole("button", { name: "Add to household" }));
    await waitFor(() => expect(people()).toHaveLength(1));
    expect(puts(calls).at(-1)?.body).toMatchObject({ members: [{ id: null, name: "Mia Rivera", signs: false }] });
    expect(people()[0]).toHaveTextContent("Doesn't sign letters · No letters yet");
  });

  it.each([
    ["", "Type a name."],
    ["x".repeat(121), "Use at most 120 characters."],
    ["Sam Rivera", "That's your own name. Your household is the other people your letters come for."],
    ["Alex und Mia Rivera", "Add one person at a time."],
    ["Juergen Mueller", "Jürgen Müller is already in your household."],
    ["1234", "Type a name with letters in it."],
  ])("refuses %j under the name field: %s", async (typed, refusal) => {
    const { user } = renderCard(useMockApi(), { members: [{ id: "hhm_000000000003", name: "Jürgen Müller", signs: true }] });
    await screen.findByText("Jürgen Müller");
    if (typed) await user.type(addField(), typed);
    await user.click(within(card()).getByRole("button", { name: "Add to household" }));
    expect(await within(card()).findByText(refusal)).toBeInTheDocument();
    expect(addField()).toHaveAttribute("aria-invalid", "true");
    expect(addField()).toHaveAccessibleDescription(refusal);
    expect(people()).toHaveLength(1);
  });

  it("refuses a thirteenth person", async () => {
    const twelve = Array.from({ length: 12 }, (_, n) => ({ id: `hhm_0000000000${String(n + 10)}`, name: `Person ${String.fromCharCode(65 + n)}`, signs: true }));
    const { user } = renderCard(useMockApi(), { members: twelve });
    await screen.findByText("Person L");
    await user.type(addField(), "One More");
    await user.click(within(card()).getByRole("button", { name: "Add to household" }));
    expect(await within(card()).findByText("Your household can have at most 12 people.")).toBeInTheDocument();
  });

  it("edits a person in place: a new name and whether they sign, the same id", async () => {
    const { user, calls } = renderCard(useMockApi(), { members: [ALEX] });
    await user.click(await screen.findByRole("button", { name: "Edit Alex Rivera" }));
    const row = people()[0]!;
    const name = within(row).getByRole("textbox", { name: "Name" });
    expect(name).toHaveValue("Alex Rivera");
    await user.clear(name);
    await user.type(name, "Alexandra Rivera");
    await user.click(within(row).getByRole("checkbox", { name: /Signs their own letters/ }));
    await user.click(within(row).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(puts(calls).at(-1)?.body).toMatchObject({ members: [{ id: ALEX.id, name: "Alexandra Rivera", signs: false }] });
    await waitFor(() => expect(people()[0]).toHaveTextContent("Doesn't sign letters"));
    expect(screen.getByRole("button", { name: "Edit Alexandra Rivera" })).toHaveFocus();
  });

  it("cancels an edit without saving, and shows an edit's mistake under its own field", async () => {
    const { user, calls } = renderCard(useMockApi(), { members: [ALEX, MIA] });
    await user.click(await screen.findByRole("button", { name: "Edit Mia Rivera" }));
    const row = people()[1]!;
    const name = within(row).getByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "A. Rivera");
    await user.click(within(row).getByRole("button", { name: "Save" }));
    expect(await within(row).findByText("Alex Rivera is already in your household.")).toBeInTheDocument();
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(addField()).not.toHaveAttribute("aria-invalid");
    await user.click(within(row).getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Edit Mia Rivera" })).toHaveFocus();
    expect(puts(calls).filter((c) => (c.body as { members: { name: string }[] }).members.some((m) => m.name === "A. Rivera"))).toHaveLength(1);
  });

  it("removes someone without letters at once, with Undo", async () => {
    const { user, srv } = renderCard(useMockApi(), { members: [ALEX] });
    await user.click(await screen.findByRole("button", { name: "Remove Alex Rivera" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    const toast = (await screen.findByText("Removed Alex Rivera")).closest("[data-toast]") as HTMLElement;
    expect(toast).not.toHaveTextContent("in your own letters again");
    await waitFor(() => expect(screen.getByText("No one yet.")).toBeInTheDocument());
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(srv.db.state.household.members).toEqual([ALEX]));
  });

  it("after a removal the keyboard goes on from the next person's Edit, not a text field, so Alt+N reaches the Undo", async () => {
    const { user } = renderCard(useMockApi(), { members: [ALEX, MIA] });
    await user.click(await screen.findByRole("button", { name: "Remove Alex Rivera" }));
    await screen.findByText("Removed Alex Rivera");
    await waitFor(() => expect(screen.getByRole("button", { name: "Edit Mia Rivera" })).toHaveFocus());
    // the last one gone: the card's heading
    await user.click(screen.getByRole("button", { name: "Remove Mia Rivera" }));
    await screen.findByText("Removed Mia Rivera");
    await waitFor(() => expect(document.getElementById("set-household")).toHaveFocus());
    expect(addField()).not.toHaveFocus();
  });

  it("a later change takes the earlier Undo away: only the newest one is offered, and it works", async () => {
    const { user, srv } = renderCard(useMockApi(), { members: [ALEX, MIA] });
    await user.click(await screen.findByRole("button", { name: "Remove Alex Rivera" }));
    await screen.findByText("Removed Alex Rivera");
    await waitFor(() => expect(people()).toHaveLength(1));
    await user.click(screen.getByRole("button", { name: "Remove Mia Rivera" }));
    const toast = (await screen.findByText("Removed Mia Rivera")).closest("[data-toast]") as HTMLElement;
    expect(screen.queryByText("Removed Alex Rivera")).toBeNull();
    expect(screen.getAllByRole("button", { name: "Undo" })).toHaveLength(1);
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(srv.db.state.household.members).toEqual([MIA]));
    expect(screen.queryByText(/changed in another window/)).toBeNull();
    // an edit or an add takes it away too
    await user.click(await screen.findByRole("button", { name: "Remove Mia Rivera" }));
    await screen.findByText("Removed Mia Rivera");
    await user.type(addField(), "Kim Rivera");
    await user.click(within(card()).getByRole("button", { name: "Add to household" }));
    expect(await screen.findByText("Added Kim Rivera")).toBeInTheDocument();
    expect(screen.queryByText("Removed Mia Rivera")).toBeNull();
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
  });

  it("asks before removing someone with letters, and Undo files their letters again", async () => {
    const api = useMockApi();
    const [one, two] = api.srv.db.liveDocuments().map((d) => d.id);
    api.srv.db.state.household = { format: 1, members: [ALEX, MIA], links: { [one!]: ALEX.id, [two!]: ALEX.id } };
    const user = userEvent.setup();
    renderWithProviders(
    <>
      <HouseholdCard />
      <Toaster />
    </>,
  );
    const row = (await screen.findByText("Alex Rivera")).closest("li")!;
    const letters = within(row).getByRole("link", { name: "2 letters" });
    expect(letters).toHaveAttribute("href", `/inbox?for=${ALEX.id}`);
    expect(row).toHaveTextContent("Signs their own letters · 2 letters");
    await user.click(within(row).getByRole("button", { name: "Remove Alex Rivera" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove Alex Rivera?" });
    expect(dialog).toHaveTextContent("Their 2 letters are in your own letters again. Nothing is deleted.");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    const toast = (await screen.findByText("Removed Alex Rivera")).closest("[data-toast]") as HTMLElement;
    expect(toast).toHaveTextContent("Their 2 letters are in your own letters again.");
    await waitFor(() => expect(people()).toHaveLength(1));
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect((api.srv.db.state.household.members ?? []).map((m) => m.id)).toEqual([ALEX.id, MIA.id]));
    const back = (await act(async () => (await api.srv.handle("GET", "/household", new URLSearchParams(), undefined)).json())) as Household;
    expect(back.filed).toEqual({ [one!]: ALEX.id, [two!]: ALEX.id });
  });

  it("keeps someone when the removal is cancelled", async () => {
    const api = useMockApi();
    const [one] = api.srv.db.liveDocuments().map((d) => d.id);
    api.srv.db.state.household = { format: 1, members: [ALEX], links: { [one!]: ALEX.id } };
    const user = userEvent.setup();
    renderWithProviders(
    <>
      <HouseholdCard />
      <Toaster />
    </>,
  );
    await user.click(await screen.findByRole("button", { name: "Remove Alex Rivera" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove Alex Rivera?" });
    expect(dialog).toHaveTextContent("Their 1 letter is in your own letters again. Nothing is deleted.");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(api.srv.db.state.household.members).toEqual([ALEX]);
  });

  it("reloads the list when another window changed it, and says so", async () => {
    const { user, srv } = renderCard(useMockApi(), { members: [ALEX] });
    await screen.findByText("Alex Rivera");
    srv.db.state.household = { format: 1, members: [ALEX, MIA], links: {} }; // another window added Mia
    await user.type(addField(), "Kim Rivera");
    await user.click(within(card()).getByRole("button", { name: "Add to household" }));
    expect(await screen.findByText("Your household changed in another window. Look again, then try once more.")).toBeInTheDocument();
    await waitFor(() => expect(people()).toHaveLength(2));
    expect(addField()).toHaveValue("Kim Rivera"); // nothing typed is lost
  });
});

describe("Your household on the Settings page", () => {
  it("is the second card of Profile & address, and a name typed but not added counts as unsaved", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <SettingsPage />
        <Toaster />
      </>,
      { route: "/settings?section=profile" },
    );
    const name = await screen.findByRole("textbox", { name: "Name" });
    expect(document.getElementById("set-household")).toHaveTextContent("Your household");
    await user.type(name, "Alex Rivera");
    await user.click(within(screen.getByRole("navigation", { name: "Settings sections" })).getByRole("link", { name: "Reminders" }));
    const dialog = await screen.findByRole("dialog", { name: "Save your changes?" });
    await user.click(within(dialog).getByRole("button", { name: "Save and go" }));
    await waitFor(() => expect(puts(calls).at(-1)?.body).toMatchObject({ members: [{ id: null, name: "Alex Rivera", signs: true }] }));
    expect(await screen.findByRole("heading", { level: 2, name: "Reminders" }, { timeout: 5_000 })).toBeInTheDocument();
  });
});
