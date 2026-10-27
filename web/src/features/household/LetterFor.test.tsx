/**
 * Who a letter is for, on its page (ADR 0023): the question *Is this letter for Alex Rivera?* for a letter whose
 * addressee names one person of the household, the *Change* popover, and *Add Alex Rivera to your household* with its
 * visible *Also file* box. Nothing is filed without a press; one press files; every toast's Undo puts back exactly
 * the answer before (also "not answered"). A paired phone files but never edits the household; nothing shows while
 * the letter is being read.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useDocument } from "@/api/hooks";
import type { HouseholdMember } from "@/api/types";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { ADDRESSEES } from "@/mocks/data/documents";
import { renderWithProviders } from "@/test/render";
import { useMockApi, type FetchCall } from "@/test/mockFetch";
import { VerdictCard } from "@/features/document/VerdictCard";
import { selectPrimaryItem } from "@/features/document/verdict";

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
  for (const id of Object.keys(ADDRESSEES)) delete ADDRESSEES[id];
});

const ALEX: HouseholdMember = { id: "hhm_000000000001", name: "Alex Rivera", signs: true };
const MIA: HouseholdMember = { id: "hhm_000000000002", name: "Mia Rivera", signs: false };

function Letter({ id }: { id: string }) {
  const doc = useDocument(id);
  return doc.data ? <VerdictCard detail={doc.data} primary={selectPrimaryItem(doc.data.items, doc.data.set_aside)} /> : null;
}

const patches = (calls: FetchCall[]) => calls.filter((c) => c.method === "PATCH" && c.path === "/household").map((c) => c.body);
const puts = (calls: FetchCall[]) => calls.filter((c) => c.method === "PUT" && c.path === "/household").map((c) => c.body);
const header = () => screen.getByRole("article").querySelector("header")!;
const toastOf = async (title: string) => (await screen.findByText(title)).closest("[data-toast]") as HTMLElement;

/** A demo letter addressed to `addressee`, the household as given, the letter's page on screen. */
type MockApi = ReturnType<typeof useMockApi>;

async function openLetter(api: MockApi, addressee: string | null, members: HouseholdMember[], links: Record<string, string> = {}, opts: { status?: string } = {}) {
  const doc = api.srv.db.liveDocuments().find((d) => d.direction === "incoming" && d.status === "processed")!;
  if (opts.status) (doc as { status: string }).status = opts.status;
  if (addressee) ADDRESSEES[doc.id] = addressee;
  api.srv.db.state.household = { format: 1, members, links: Object.fromEntries(Object.entries(links).map(([k, v]) => [k === "this" ? doc.id : k, v])) };
  const user = userEvent.setup();
  renderWithProviders(
    <>
      <Letter id={doc.id} />
      <Toaster />
    </>,
  );
  await screen.findByRole("article");
  return { ...api, user, id: doc.id };
}

describe("the letter's question", () => {
  it("asks whether a letter addressed to one person of the household is for them, and files nothing by itself", async () => {
    const { calls } = await openLetter(useMockApi(), "Frau Alex Rivera", [ALEX]);
    const question = await screen.findByRole("group", { name: "Is this letter for Alex Rivera?" });
    expect(within(question).getByRole("button", { name: "Yes" })).toBeInTheDocument();
    expect(within(question).getByRole("button", { name: "No, it's mine" })).toBeInTheDocument();
    expect(within(question).queryByRole("button", { name: /Someone else/ })).toBeNull(); // one person only
    expect(within(header()).queryByText(/^For /)).toBeNull();
    expect(patches(calls)).toEqual([]);
  });

  it("Yes files it with one press, then the Change button takes the question's place; Undo asks again", async () => {
    const { user, calls, id } = await openLetter(useMockApi(), "Alex Rivera", [ALEX]);
    await user.click(within(await screen.findByRole("group", { name: "Is this letter for Alex Rivera?" })).getByRole("button", { name: "Yes" }));
    const toast = await toastOf("Filed for Alex Rivera");
    expect(patches(calls)).toEqual([{ letters: { [id]: ALEX.id } }]);
    const change = await screen.findByRole("button", { name: "Change who this letter is for" });
    await waitFor(() => expect(change).toHaveFocus());
    expect(header()).toHaveTextContent("For Alex Rivera");
    expect(screen.queryByRole("group", { name: /Is this letter for/ })).toBeNull();
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(patches(calls).at(-1)).toEqual({ letters: { [id]: null } }));
    expect(await screen.findByRole("group", { name: "Is this letter for Alex Rivera?" })).toBeInTheDocument();
  });

  it("“No, it's mine” files it as the person's own; Undo forgets the answer", async () => {
    const { user, calls, id } = await openLetter(useMockApi(), "Alex Rivera", [ALEX]);
    await user.click(within(await screen.findByRole("group", { name: "Is this letter for Alex Rivera?" })).getByRole("button", { name: "No, it's mine" }));
    const toast = await toastOf("Filed as yours");
    expect(patches(calls)).toEqual([{ letters: { [id]: "me" } }]);
    await waitFor(() => expect(header()).toHaveTextContent("For you"));
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(patches(calls).at(-1)).toEqual({ letters: { [id]: null } }));
  });

  it("“Someone else…” opens the choices when the household has two people or more", async () => {
    const { user, calls, id } = await openLetter(useMockApi(), "Alex Rivera", [ALEX, MIA]);
    await user.click(within(await screen.findByRole("group", { name: "Is this letter for Alex Rivera?" })).getByRole("button", { name: "Someone else…" }));
    const choices = await screen.findByRole("dialog", { name: "Who is this letter for?" });
    expect(choices).toHaveTextContent("Its dates, reminders and numbers stay in your Ordnung either way.");
    const buttons = within(choices).getAllByRole("button").filter((b) => b.hasAttribute("aria-pressed"));
    expect(buttons.map((b) => b.textContent)).toEqual(["You Sam Rivera", "Alex Rivera", "Mia Rivera"]);
    expect(buttons.every((b) => b.getAttribute("aria-pressed") === "false")).toBe(true);
    await user.click(within(choices).getByRole("button", { name: "Mia Rivera" }));
    await toastOf("Filed for Mia Rivera");
    expect(patches(calls)).toEqual([{ letters: { [id]: MIA.id } }]);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Who is this letter for?" })).toBeNull());
  });
});

describe("Change", () => {
  it("shows who the letter is filed for, and one press files it for someone else; Undo puts back the one before", async () => {
    const { user, calls, id } = await openLetter(useMockApi(), "Alex Rivera", [ALEX, MIA], { this: ALEX.id });
    expect(await within(header()).findByText("For Alex Rivera", { exact: false })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Change who this letter is for" }));
    const choices = await screen.findByRole("dialog", { name: "Who is this letter for?" });
    expect(within(choices).getByRole("button", { name: "Alex Rivera" })).toHaveAttribute("aria-pressed", "true");
    expect(within(choices).getByRole("link", { name: "Manage your household" })).toHaveAttribute("href", "/settings?section=profile#set-household");
    await user.click(within(choices).getByRole("button", { name: /^You/ }));
    const toast = await toastOf("Filed as yours");
    expect(patches(calls)).toEqual([{ letters: { [id]: "me" } }]);
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(patches(calls).at(-1)).toEqual({ letters: { [id]: ALEX.id } }));
  });

  it("says “For you” for a letter of the person's own while the household has people, and nothing without them", async () => {
    await openLetter(useMockApi(), "Kim Rivera", [ALEX], { this: "me" });
    expect(await within(header()).findByText("For you", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change who this letter is for" })).toBeInTheDocument();
  });

  it("says nothing new for a letter of the person's own without a household", async () => {
    await openLetter(useMockApi(), null, []);
    await new Promise((r) => setTimeout(r, 50));
    expect(within(header()).queryByText(/^For /)).toBeNull();
    expect(screen.queryByRole("button", { name: "Change who this letter is for" })).toBeNull();
    expect(screen.queryByRole("button", { name: /to your household/ })).toBeNull();
  });

  it("is never offered while the letter is being read", async () => {
    await openLetter(useMockApi(), "Alex Rivera", [ALEX], {}, { status: "processing" });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("group", { name: /Is this letter for/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Change who this letter is for" })).toBeNull();
  });
});

describe("Add … to your household", () => {
  it("adds the addressee with the letter filed for them, the box visible and ticked; Undo removes them again", async () => {
    const { user, calls, id } = await openLetter(useMockApi(), "Frau Alex Rivera", []);
    await user.click(await screen.findByRole("button", { name: "Add Alex Rivera to your household" }));
    const form = await screen.findByRole("dialog", { name: "Add to your household" });
    const name = within(form).getByRole("textbox", { name: "Name" });
    expect(name).toHaveValue("Alex Rivera");
    expect(within(form).getByRole("checkbox", { name: /Signs their own letters/ })).toBeChecked();
    const alsoFile = within(form).getByRole("checkbox", { name: "Also file this letter for Alex Rivera" });
    expect(alsoFile).toBeChecked();
    expect(alsoFile).toBeVisible();
    await user.clear(name);
    await user.type(name, "Alexandra Rivera");
    expect(within(form).getByRole("checkbox", { name: "Also file this letter for Alexandra Rivera" })).toBeChecked();
    await user.click(within(form).getByRole("button", { name: "Add" }));
    const toast = await toastOf("Added Alexandra Rivera to your household");
    expect(toast).toHaveTextContent("This letter is filed for Alexandra Rivera.");
    expect(puts(calls)).toEqual([{ base: "4f53cda18c2baa0c", members: [{ id: null, name: "Alexandra Rivera", signs: true }], also_file: [id] }]);
    await waitFor(() => expect(header()).toHaveTextContent("For Alexandra Rivera"));
    expect(screen.queryByRole("button", { name: /to your household/ })).toBeNull();
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(puts(calls).at(-1)).toMatchObject({ members: [] }));
  });

  it("adds only the person when the box is unticked: the letter then asks", async () => {
    const { user, calls } = await openLetter(useMockApi(), "Alex Rivera", []);
    await user.click(await screen.findByRole("button", { name: "Add Alex Rivera to your household" }));
    const form = await screen.findByRole("dialog", { name: "Add to your household" });
    await user.click(within(form).getByRole("checkbox", { name: "Also file this letter for Alex Rivera" }));
    await user.click(within(form).getByRole("button", { name: "Add" }));
    const toast = await toastOf("Added Alex Rivera to your household");
    expect(toast).toHaveTextContent("Ordnung asks before it files a letter for them.");
    expect(puts(calls).at(-1)).toMatchObject({ also_file: [] });
    expect(patches(calls)).toEqual([]);
    expect(await screen.findByRole("group", { name: "Is this letter for Alex Rivera?" })).toBeInTheDocument();
  });

  it("says why a name can't be added under the field", async () => {
    const { user } = await openLetter(useMockApi(), "Alex Rivera", []);
    await user.click(await screen.findByRole("button", { name: "Add Alex Rivera to your household" }));
    const form = await screen.findByRole("dialog", { name: "Add to your household" });
    const name = within(form).getByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Sam Rivera");
    await user.click(within(form).getByRole("button", { name: "Add" }));
    expect(await within(form).findByText("That's your own name. Your household is the other people your letters come for.")).toBeInTheDocument();
    expect(name).toHaveAttribute("aria-invalid", "true");
  });

  it("is offered beside “For you” when the household has people but none could be the addressee", async () => {
    await openLetter(useMockApi(), "Kim Rivera", [ALEX]);
    expect(await screen.findByRole("button", { name: "Add Kim Rivera to your household" })).toBeInTheDocument();
    expect(header()).toHaveTextContent("For you");
  });
});

describe("on a paired phone", () => {
  it("asks and files, but never offers to edit the household", async () => {
    const { user, calls, id, srv } = await openLetter(useMockApi({ client: "phone" }), "Alex Rivera", [ALEX], {});
    await user.click(within(await screen.findByRole("group", { name: "Is this letter for Alex Rivera?" })).getByRole("button", { name: "Yes" }));
    await toastOf("Filed for Alex Rivera");
    expect(patches(calls)).toEqual([{ letters: { [id]: ALEX.id } }]);
    await user.click(await screen.findByRole("button", { name: "Change who this letter is for" }));
    const choices = await screen.findByRole("dialog", { name: "Who is this letter for?" });
    expect(within(choices).queryByRole("link", { name: "Manage your household" })).toBeNull();
    expect(srv.refused).toEqual([]);
  });

  it("never offers to add someone", async () => {
    await openLetter(useMockApi({ client: "phone" }), "Kim Rivera", [], {});
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("button", { name: /to your household/ })).toBeNull();
  });
});
