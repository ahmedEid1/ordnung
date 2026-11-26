/**
 * The letters' buttons that change something take one press at a time: two presses before the button is drawn busy
 * (a double click, Enter twice) send one request — "Write the letter" wrote two letters — and a failed one takes the
 * next press.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { expectOnePressAtATime } from "@/test/busyButton";
import { holdRequests, useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { PageMetaProvider } from "@/components/shell/page-meta";
import LetterPage from "@/pages/LetterPage";
import ProofFilePage from "@/pages/ProofFilePage";
import LettersPage from "@/pages/LettersPage";

function renderLetter(id: string) {
  const router = createMemoryRouter(
    [
      { path: "/letters/:id", element: <LetterPage /> },
      { path: "*", element: <p>elsewhere</p> },
    ],
    { initialEntries: [`/letters/${id}`] },
  );
  render(
    <QueryClientProvider client={makeTestQueryClient()}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  );
}

/** Two presses in one go (before React draws anything) send one request. */
async function twoPressesSendOne(button: HTMLElement, held: { count: number; fail(): void }) {
  const before = held.count;
  act(() => {
    button.click();
    button.click();
  });
  await waitFor(() => expect(held.count).toBe(before + 1));
  await act(async () => {});
  expect(held.count).toBe(before + 1);
  await act(async () => held.fail());
}

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

describe("the composer", () => {
  it("“Write the letter” takes one press at a time, and the next once it failed", async () => {
    useMockApi({ full: true });
    const held = holdRequests((call) => call.method === "POST" && call.path === "/drafts");
    renderWithProviders(
      <>
        <LettersPage />
        <Toaster />
      </>,
      { route: "/letters?kind=objection&doc=doc_tax" },
    );
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    const write = () => within(dialog).getByRole("button", { name: /Write the letter|Writing…/ });
    await waitFor(() => expect(write()).toBeEnabled());
    await expectOnePressAtATime({ user: userEvent.setup(), button: write, held });
  });
});

describe("a letter", () => {
  beforeEach(() => localStorage.clear());

  it("“Save” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/drafts/drf_phone");
    renderLetter("drf_phone");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Letter text (German)"), " Danke.");
    await expectOnePressAtATime({ user, button: () => screen.getByRole("button", { name: "Save" }), held });
  });

  it("“Re-translate” takes one press at a time, and the next once it failed", async () => {
    const { srv } = useMockApi();
    srv.db.state.health.backend = "claude";
    const held = holdRequests((call) => call.method === "POST" && call.path === "/drafts/drf_phone/translate");
    renderLetter("drf_phone");
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1, name: "Cancellation to FunkNetz Mobil GmbH" });
    await user.click(screen.getByLabelText("Letter text (German)"));
    await user.keyboard("{Control>}{End}{/Control}{Enter}Ich ziehe um.");
    await user.click(screen.getByRole("radio", { name: "In English" }));
    await expectOnePressAtATime({ user, button: () => screen.getByRole("button", { name: /Re-translate|Translating…/ }), held });
  });

  it("“Mark as sent” in its dialog takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/drafts/drf_phone/sent");
    renderLetter("drf_phone");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Mark as sent" }));
    const dialog = await screen.findByRole("dialog", { name: "Mark as sent" });
    await user.click(within(dialog).getAllByRole("radio")[0]!);
    await expectOnePressAtATime({ user, button: () => within(dialog).getByRole("button", { name: "Mark as sent" }), held });
  });

  it("“Mark as ready to send” sends one request for two presses in one go", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/drafts/drf_phone");
    renderLetter("drf_phone");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "More actions" }));
    await twoPressesSendOne(screen.getByRole("menuitem", { name: "Mark as ready to send" }), held);
  });

  it("“Delete” in its dialog takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "DELETE" && call.path.startsWith("/drafts/drf_phone"));
    renderLetter("drf_phone");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete this letter" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete this letter?" });
    await expectOnePressAtATime({ user, button: () => within(dialog).getByRole("button", { name: "Delete" }), held });
  });
});

describe("proof of sending", () => {
  it("“Add proof” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/drafts/drf_gym/proofs");
    renderLetter("drf_gym");
    const user = userEvent.setup();
    const proof = await screen.findByRole("region", { name: "Proof of sending" });
    await user.click(await within(proof).findByRole("button", { name: "Add proof" }));
    const dialog = await screen.findByRole("dialog", { name: "Add proof" });
    await user.upload(within(dialog).getByLabelText("File"), new File(["%PDF-1.4"], "Auslieferungsbeleg.pdf", { type: "application/pdf" }));
    await user.type(within(dialog).getByLabelText(/Delivered on/), "2026-09-24");
    await expectOnePressAtATime({ user, button: () => within(dialog).getByRole("button", { name: "Add proof" }), held });
  });

  it("“Remove” on the proof's own page takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "DELETE" && call.path === "/drafts/drf_gym/proofs/prf_gym_receipt");
    const router = createMemoryRouter(
      [
        {
          path: "/letters/:id/proofs/:docId",
          element: (
            <PageMetaProvider>
              <ProofFilePage />
              <Toaster />
            </PageMetaProvider>
          ),
        },
        { path: "*", element: <p>elsewhere</p> },
      ],
      { initialEntries: ["/letters/drf_gym/proofs/doc_gym_receipt"] },
    );
    render(
      <QueryClientProvider client={makeTestQueryClient()}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Remove this proof" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove the posting receipt (Einlieferungsbeleg)?" });
    await expectOnePressAtATime({ user, button: () => within(dialog).getByRole("button", { name: "Remove" }), held });
  });
});
