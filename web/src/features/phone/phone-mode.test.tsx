/**
 * Phone mode across the app: a paired phone opens every everyday page against the phone listener (the mock with
 * the API's allow-list from `openapi.json`) — and no page asks for anything the phone may not do. `srv.refused`
 * (every request the allow-list turned away, 403 `computer_only`) stays empty, and no page offers to delete,
 * download a file or a PDF, or decide about held letters.
 *
 * Settings is P2's (`PhoneSettingsNotice`): its own test makes sure it asks for no settings on a phone.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import { qk } from "@/api/hooks";
import { __clearToasts } from "@/components/ui/Toast";
import { renderAppAt as visit, stubShellGlobals } from "@/test/app";
import { openApiPhoneScope, useMockApi } from "@/test/mockFetch";
import type { MockServer } from "@/mocks/server";
import { classifyPhoneRequest } from "@/mocks/phone";
import { DECIDE_ON_COMPUTER, DECIDE_ONE_ON_COMPUTER, DELETE_ON_COMPUTER, FULL_NUMBER_ON_COMPUTER, PDF_ON_COMPUTER, PROOF_ON_COMPUTER } from "./copy";

beforeEach(stubShellGlobals);
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

/** Links to what never leaves the computer for a phone: original files, PDFs, the traces export, a backup. */
const COMPUTER_FILES = /\/api\/(documents\/[^/]+\/file|drafts\/[^/]+\/(pdf|proof\.pdf)|traces|backup)\b/;
/** Controls a phone never offers (the API would refuse them). */
const COMPUTER_ACTIONS = /^(Delete|Download original|Download PDF|Download Nachweis|Download the file|Remove this proof|Keep private|Read these|Read it|Open the original file|Delete this letter|Delete the note)/;

/** Nothing on the page that only the computer may do. */
function expectNoComputerOnlyControls() {
  for (const a of Array.from(document.querySelectorAll<HTMLAnchorElement>("a[href]"))) {
    expect(a.getAttribute("href"), `link ${a.textContent}`).not.toMatch(COMPUTER_FILES);
  }
  const named = [...screen.queryAllByRole("button"), ...screen.queryAllByRole("link"), ...screen.queryAllByRole("menuitem")];
  for (const el of named) {
    const name = (el.getAttribute("aria-label") ?? el.textContent ?? "").trim();
    expect(name, "a control only the computer offers").not.toMatch(COMPUTER_ACTIONS);
  }
}

/** Every request the phone made is on its allow-list (the mock refused none) — and the page made some. */
function expectNothingRefused(srv: MockServer, calls: { method: string; path: string }[]) {
  expect(srv.refused).toEqual([]);
  expect(calls.length).toBeGreaterThan(0);
  const scope = openApiPhoneScope();
  for (const c of calls) expect(classifyPhoneRequest(scope, c.method, `/api${c.path}`), `${c.method} ${c.path}`).toBe("phone");
}

function ids(srv: MockServer) {
  const st = srv.db.state;
  const letter = st.documents.find((d) => d.status === "processed" && d.pages > 0 && !d.ai_private && d.source !== "proof" && !d.deleted_at)!;
  const held = st.documents.find((d) => d.status === "held")!;
  const draft = st.drafts.find((d) => d.status !== "sent")!;
  const sent = st.drafts.find((d) => d.status === "sent" && st.proofs.some((p) => p.draft_id === d.id))!;
  const proof = st.proofs.find((p) => p.draft_id === sent.id && p.doc_id)!;
  const party = st.parties.find((p) => p.kind !== "person") ?? st.parties[0]!;
  return { letter, held, draft, sent, proof, party };
}

describe("a paired phone asks only for what it may", () => {
  const pages: [string, string, RegExp | string | undefined][] = [
    ["Today", "/", undefined],
    ["Inbox", "/inbox", "Inbox"],
    ["Timeline", "/timeline", "Timeline"],
    ["Contracts", "/contracts", "Contracts"],
    ["My numbers", "/numbers", "My numbers"],
    ["Letters", "/letters", "Letters"],
    ["Waiting for", "/letters/waiting", undefined],
    ["Weekly review", "/week", undefined],
    ["Ask", "/ask", undefined],
  ];
  it.each(pages)("%s", async (_name, path, heading) => {
    const { srv, calls } = useMockApi({ client: "phone" });
    await visit(path, heading);
    expectNothingRefused(srv, calls);
    expectNoComputerOnlyControls();
  });

  it("a letter: its pages and what it says, without Delete or Download original", async () => {
    const { srv, calls } = useMockApi({ client: "phone" });
    const { letter } = ids(srv);
    await visit(`/documents/${letter.id}`);
    await screen.findByText(DELETE_ON_COMPUTER);
    expectNothingRefused(srv, calls);
    expectNoComputerOnlyControls();
    expect(screen.getByRole("button", { name: "Read again" })).toBeInTheDocument();
  });

  it("a letter from the watched folder: what it is, and that the computer decides whether Claude reads it", async () => {
    const { srv, calls } = useMockApi({ client: "phone" });
    const { held } = ids(srv);
    await visit(`/documents/${held.id}`);
    await screen.findByText(DECIDE_ONE_ON_COMPUTER);
    expect(screen.getByText(/It is stored on your computer and has not been sent to Claude/)).toBeInTheDocument();
    expectNothingRefused(srv, calls);
    expectNoComputerOnlyControls();
  });

  it("the Inbox lists the folder's letters, answered on the computer (no folder status asked)", async () => {
    const { srv, calls } = useMockApi({ client: "phone" });
    await visit("/inbox", "Inbox");
    const group = await screen.findByRole("region", { name: /From your folder/ });
    expect(within(group).getByText(DECIDE_ON_COMPUTER)).toBeInTheDocument();
    expect(within(group).queryByRole("link", { name: "Watched folder settings" })).toBeNull();
    expect(calls.some((c) => c.path === "/folder")).toBe(false);
    expectNothingRefused(srv, calls);
  });

  it("a letter being written: writing and sending stay, the PDF is downloaded on the computer", async () => {
    const { srv, calls } = useMockApi({ client: "phone" });
    const { draft } = ids(srv);
    await visit(`/letters/${draft.id}`);
    await screen.findByText(PDF_ON_COMPUTER);
    expect(screen.getByRole("button", { name: "Mark as sent" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open the PDF/ })).toBeNull();
    await act(async () => screen.getByRole("button", { name: "More actions" }).click());
    expect(screen.queryByRole("menuitem", { name: /Delete this letter/ })).toBeNull();
    expectNothingRefused(srv, calls);
    expectNoComputerOnlyControls();
  });

  it("a sent letter's proof: add a proof here, download and remove it on the computer", async () => {
    const { srv, calls } = useMockApi({ client: "phone" });
    const { sent } = ids(srv);
    await visit(`/letters/${sent.id}`);
    await screen.findByText(PROOF_ON_COMPUTER);
    expect(screen.getByRole("button", { name: "Add proof" })).toBeInTheDocument();
    for (const actions of screen.queryAllByRole("button", { name: /^Actions for / })) {
      await act(async () => actions.click());
      expect(screen.queryByRole("menuitem", { name: "Remove this proof" })).toBeNull();
    }
    expectNothingRefused(srv, calls);
    expectNoComputerOnlyControls();
  });

  it("a proof opened on its own: shown, not downloaded or removed", async () => {
    const { srv, calls } = useMockApi({ client: "phone" });
    const { sent, proof } = ids(srv);
    await visit(`/letters/${sent.id}/proofs/${proof.doc_id}`);
    await screen.findByText(PROOF_ON_COMPUTER);
    expectNothingRefused(srv, calls);
    expectNoComputerOnlyControls();
  });

  it("the people & organisations drawer: call notes are added, not deleted; your numbers come masked", async () => {
    const { srv, calls } = useMockApi({ client: "phone" });
    const { party } = ids(srv);
    await visit(`/?party=${party.id}`);
    const drawer = await screen.findByRole("dialog");
    await within(drawer).findAllByText(party.name);
    await waitFor(() => expect(calls.some((c) => c.path === "/calls")).toBe(true));
    expectNothingRefused(srv, calls);
    expectNoComputerOnlyControls();
  });

  it("My numbers shows your numbers masked, with the full ones on the computer", async () => {
    const { srv, calls } = useMockApi({ client: "phone" });
    const { client } = await visit("/numbers", "My numbers");
    expect(client.getQueryData(qk.health)).toMatchObject({ client: "phone" });
    expect(screen.getByText(/your numbers show only their last 4 characters/)).toBeInTheDocument();
    expect(screen.getAllByText(FULL_NUMBER_ON_COMPUTER).length).toBeGreaterThan(0);
    // nothing to show or copy: the value is masked already
    expect(screen.queryByRole("button", { name: /^Show / })).toBeNull();
    expectNothingRefused(srv, calls);
  });
});
