import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { makeTestQueryClient } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import LetterPage from "@/pages/LetterPage";

function renderLetter(id: string) {
  const router = createMemoryRouter([{ path: "/letters/:id", element: <LetterPage /> }], { initialEntries: [`/letters/${id}`] });
  return render(
    <QueryClientProvider client={makeTestQueryClient()}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
  localStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  act(() => __clearToasts());
});

async function editGermanLetter(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("heading", { level: 1, name: "Cancellation to FunkNetz Mobil GmbH" });
  const body = screen.getByLabelText("Letter text (German)");
  await user.click(body);
  await user.keyboard("{Control>}{End}{/Control}{Enter}Ich ziehe um.");
  await user.click(screen.getByRole("radio", { name: "In English" }));
}

describe("Re-translate after editing the German letter", () => {
  it("saves the edit, translates the letter as it now stands and clears the warning", async () => {
    const { srv, calls } = useMockApi();
    srv.db.state.health.backend = "claude"; // a live backend (the demo can only replay)
    const user = userEvent.setup();
    renderLetter("drf_phone");
    await editGermanLetter(user);

    expect(screen.getByText(/this translation still shows the original draft/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Re-translate" }));

    expect(await screen.findByText("Translation updated")).toBeInTheDocument();
    const patch = calls.findIndex((c) => c.method === "PATCH" && c.path === "/drafts/drf_phone");
    const post = calls.findIndex((c) => c.method === "POST" && c.path === "/drafts/drf_phone/translate");
    expect(patch).toBeGreaterThanOrEqual(0);
    expect(post).toBeGreaterThan(patch); // the edit is saved first
    await waitFor(() => expect(screen.queryByText(/this translation still shows the original draft/)).not.toBeInTheDocument());
    // the new translation covers the edit (both panes are on the page; the card's width decides which show)
    expect(within(document.querySelector<HTMLElement>("[data-pane=english]")!).getByText(/Ich ziehe um\./)).toBeInTheDocument();
    expect(localStorage.getItem("ordnung.letters.edited") ?? "[]").not.toContain("drf_phone");
  });

  it("the demo explains that it can't translate edits", async () => {
    useMockApi(); // the demo backend replays recordings
    const user = userEvent.setup();
    renderLetter("drf_phone");
    await editGermanLetter(user);
    await user.click(screen.getByRole("button", { name: "Re-translate" }));

    const toast = await screen.findByText("Not available in the demo");
    expect(toast.closest("li")).toHaveTextContent(/can't translate your changes/);
    expect(screen.getByText(/this translation still shows the original draft/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-translate" })).toBeEnabled();
  });
});
