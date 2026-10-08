/**
 * The pairing page (`/pair`, a phone's first page): the code comes from the QR link's fragment and leaves the address
 * at once, or is typed; health says whether this is a phone to pair, a phone paired already or the computer; every
 * refusal says why in the API's words; a paired phone shows the two words to compare with the computer's, then
 * opens Ordnung with a full page load. `?removed=…` says why the phone is here again.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { routes } from "@/app/router";
import { PHONE_UNREACHABLE } from "@/api/client";
import { clientKind } from "@/api/clientKind";
import { makeTestQueryClient } from "@/test/render";
import { stubShellGlobals } from "@/test/app";
import { useMockApi } from "@/test/mockFetch";
import { CODE_USED_MESSAGE, MAX_PHONES, PHONE_OFF_MESSAGE, THIS_PHONE_ADDRESS, TOO_MANY_PHONES_MESSAGE, TOO_MANY_TRIES_MESSAGE, WRONG_CODE_MESSAGE } from "@/mocks/data/phone";
import type { MockServer } from "@/mocks/server";
import { pageLoad } from "@/features/phone/platform";
import { CODE_REUSED_NOTE, COMPUTER_NOTE, PAIR_TITLE, REMOVED_NOTE, TOKEN_REUSE_NOTE, UNUSED_NOTE, codeFromHash, compactCode, formatCode, removedNote } from "./PairPage";

const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";

let replace: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  stubShellGlobals();
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(IPHONE);
  replace = vi.spyOn(pageLoad, "replace").mockImplementation(() => {});
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** A phone that isn't paired yet, and a code open on the computer. */
function useUnpairedPhone(): { srv: MockServer; code: string } {
  const api = useMockApi({ client: "phone", paired: false });
  const { code } = api.srv.phone.startPairing();
  return { srv: api.srv, code };
}

function openPair(path: string) {
  const client = makeTestQueryClient({ client: "computer" }); // nothing known yet: the page asks
  client.removeQueries(); // no health seeded: the pairing page asks the server itself
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, client, user: userEvent.setup() };
}

describe("the code", () => {
  it("comes from the link's fragment, which leaves the address at once", async () => {
    const { code } = useUnpairedPhone();
    const { router } = openPair(`/pair#${code}`);
    await screen.findByRole("heading", { level: 1, name: PAIR_TITLE });
    expect(screen.getByText(formatCode(code))).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.hash).toBe(""));
    expect(router.state.location.pathname).toBe("/pair");
    // only the phone listener refuses like this: the tab now knows it is a phone
    expect(clientKind()).toBe("phone");
  });

  it("keeps `?removed=1` while the fragment goes", async () => {
    const { code } = useUnpairedPhone();
    const { router } = openPair(`/pair?removed=1#${code}`);
    await screen.findByText(REMOVED_NOTE);
    await waitFor(() => expect(router.state.location.hash).toBe(""));
    expect(router.state.location.search).toBe("?removed=1");
  });

  it("is typed when there is no link: upper case, grouped 5 + 5 with a hyphen that never breaks", async () => {
    useUnpairedPhone();
    const { user } = openPair("/pair");
    const input = await screen.findByRole("textbox", { name: "Code from your computer" });
    expect(input).toHaveAttribute("autocapitalize", "characters");
    expect(input).toHaveAttribute("autocomplete", "one-time-code");
    await user.type(input, "k7qm2 xd9pa-zz");
    expect(input).toHaveValue("K7QM2‑XD9PA");
  });

  it("can be typed instead of the link's", async () => {
    const { code } = useUnpairedPhone();
    const { user } = openPair(`/pair#${code}`);
    await user.click(await screen.findByRole("button", { name: "Type a code instead" }));
    expect(screen.getByRole("textbox", { name: "Code from your computer" })).toHaveValue("");
    expect(screen.queryByText(formatCode(code))).toBeNull();
  });

  it("reads and normalises like the API", () => {
    expect(codeFromHash("#K7QM2XD9PA")).toBe("K7QM2XD9PA");
    expect(codeFromHash("#k7qm2-xd9pa")).toBe("K7QM2XD9PA");
    expect(codeFromHash("#K7QM2%E2%80%91XD9PA")).toBe("K7QM2XD9PA");
    expect(codeFromHash("#main")).toBeNull();
    expect(codeFromHash("")).toBeNull();
    expect(codeFromHash("#%E0%A4%A")).toBeNull();
    expect(compactCode("k7qm2 ‑ xd9pa")).toBe("K7QM2XD9PA");
    expect(formatCode("K7QM2")).toBe("K7QM2");
  });
});

describe("who is asking", () => {
  it("a phone paired already goes on to Today", async () => {
    useMockApi({ client: "phone" });
    const { router } = openPair("/pair");
    await waitFor(() => expect(router.state.location.pathname).toBe("/"), { timeout: 8_000 });
    expect(screen.queryByRole("heading", { name: PAIR_TITLE })).toBeNull();
  });

  it("the computer's own tab is told pairing is for phones", async () => {
    useMockApi();
    openPair("/pair");
    await screen.findByRole("heading", { level: 1, name: "Pairing is for phones" });
    expect(screen.getByText(COMPUTER_NOTE)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open Settings → Phone/ })).toHaveAttribute("href", "/settings?section=phone");
  });

  it("the computer's tab without its session isn't offered the form (pairing can't sign it in)", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ version: "test", authenticated: false }), { status: 200, headers: { "Content-Type": "application/json" } }));
    openPair("/pair");
    await screen.findByRole("heading", { level: 1, name: "Pairing can't start" });
    expect(screen.getByRole("alert")).toHaveTextContent(/isn't signed in to Ordnung any more/);
    expect(screen.queryByRole("textbox", { name: "Code from your computer" })).toBeNull();
  });

  it("a computer that doesn't answer: what to check, and Try again", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("Failed to fetch");
    });
    openPair("/pair");
    await screen.findByRole("heading", { level: 1, name: "Can't reach your computer" });
    expect(screen.getByText(/same Wi‑Fi/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("pairing", () => {
  it("names the phone from its browser, pairs with the link's code and shows the two words the computer shows", async () => {
    const { srv, code } = useUnpairedPhone();
    const { user } = openPair(`/pair#${code}`);
    const name = await screen.findByRole("textbox", { name: "This phone's name" });
    expect(name).toHaveValue("iPhone");
    await user.clear(name);
    await user.type(name, "Anna's iPhone");
    await user.click(screen.getByRole("button", { name: "Pair this phone" }));

    await screen.findByRole("heading", { level: 1, name: "Paired" });
    const device = srv.phone.status().devices.find((d) => d.name === "Anna's iPhone")!;
    expect(device).toBeTruthy();
    expect(document.querySelector("[data-check-words]")).toHaveTextContent(device.check_words);
    expect(screen.getByRole("heading", { level: 1, name: "Paired" })).toHaveFocus();
    expect(replace).not.toHaveBeenCalled(); // the person compares the words first
    await user.click(screen.getByRole("button", { name: "Open Ordnung" }));
    expect(replace).toHaveBeenCalledWith("/");
  });

  it("an 11th character typed at the end is dropped: the code it shows is the code it sends (UX review)", async () => {
    const { srv, code } = useUnpairedPhone();
    const { user } = openPair("/pair");
    const input = await screen.findByRole("textbox", { name: "Code from your computer" });
    await user.type(input, `${code}Z`);
    expect(input).toHaveValue(formatCode(code));
    await user.click(screen.getByRole("button", { name: "Pair this phone" }));
    await screen.findByRole("heading", { level: 1, name: "Paired" });
    expect(screen.queryByText(/The code has 10 characters/)).toBeNull();
    expect(srv.phone.status().devices).toHaveLength(1);
  });

  it("a backspace after an extra character removes the code's last character: the extra one was never kept", async () => {
    useUnpairedPhone();
    const { user } = openPair("/pair");
    const input = await screen.findByRole("textbox", { name: "Code from your computer" });
    await user.type(input, "K7QM2XD9PAZ{Backspace}");
    expect(input).toHaveValue("K7QM2‑XD9P");
  });

  it("pairs with a typed code", async () => {
    const { srv, code } = useUnpairedPhone();
    const { user } = openPair("/pair");
    await user.type(await screen.findByRole("textbox", { name: "Code from your computer" }), code.toLowerCase());
    await user.click(screen.getByRole("button", { name: "Pair this phone" }));
    await screen.findByRole("heading", { level: 1, name: "Paired" });
    expect(srv.phone.status().devices.some((d) => d.name === "iPhone")).toBe(true);
  });

  it("asks for a whole code and a name before it sends anything", async () => {
    const { srv } = useUnpairedPhone();
    const { user } = openPair("/pair");
    const code = await screen.findByRole("textbox", { name: "Code from your computer" });
    await user.type(code, "K7QM");
    await user.clear(screen.getByRole("textbox", { name: "This phone's name" }));
    await user.click(screen.getByRole("button", { name: "Pair this phone" }));
    expect(code).toHaveAccessibleDescription(/The code has 10 characters/);
    expect(code).toHaveFocus();
    expect(srv.phone.status().devices).toHaveLength(0);
  });
});

describe("each refusal says why", () => {
  async function pairWith(code: string, path = "/pair") {
    const { user } = openPair(path);
    await user.type(await screen.findByRole("textbox", { name: "Code from your computer" }), code);
    await user.click(screen.getByRole("button", { name: "Pair this phone" }));
    return { user, alert: await screen.findByRole("alert") };
  }

  it("a wrong, expired or missing code: one answer", async () => {
    useUnpairedPhone();
    const { alert } = await pairWith("AAAAABBBBB");
    expect(alert).toHaveTextContent(WRONG_CODE_MESSAGE);
  });

  it("a code another device used first: neither is paired", async () => {
    const { srv, code } = useUnpairedPhone();
    srv.phone.pair({ code, name: "Someone" }, "192.168.178.66");
    const { alert } = await pairWith(code);
    expect(alert).toHaveTextContent(CODE_USED_MESSAGE);
    expect(srv.phone.status().devices).toHaveLength(0);
    expect(srv.phone.status().notice?.code).toBe("code_reused");
  });

  it("too many wrong codes from this phone", async () => {
    const { srv } = useUnpairedPhone();
    for (let i = 0; i < 5; i++) expect(() => srv.phone.pair({ code: "AAAAABBBBB", name: "x" }, THIS_PHONE_ADDRESS)).toThrow();
    const { alert } = await pairWith("CCCCCDDDDD");
    expect(alert).toHaveTextContent(TOO_MANY_TRIES_MESSAGE);
  });

  it("the most phones are paired", async () => {
    const { srv, code } = useUnpairedPhone();
    for (let i = 0; i < MAX_PHONES; i++) srv.phone.addPhone({ name: `Phone ${i + 1}` });
    const { alert } = await pairWith(code);
    expect(alert).toHaveTextContent(TOO_MANY_PHONES_MESSAGE);
  });

  it("phone access was turned off meanwhile", async () => {
    const { srv, code } = useUnpairedPhone();
    srv.phone.change({ enabled: false, home_network: false });
    const { alert } = await pairWith(code);
    expect(alert).toHaveTextContent(PHONE_OFF_MESSAGE);
  });

  it("the computer stopped answering", async () => {
    const { code } = useUnpairedPhone();
    const { user } = openPair(`/pair#${code}`);
    await screen.findByRole("heading", { level: 1, name: PAIR_TITLE });
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("Failed to fetch");
    });
    await user.click(screen.getByRole("button", { name: "Pair this phone" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(PHONE_UNREACHABLE);
  });

  it("a refusal can be answered by typing another code (the link's may have expired)", async () => {
    const { code } = useUnpairedPhone();
    const { user } = openPair(`/pair#AAAAABBBBB`);
    await user.click(await screen.findByRole("button", { name: "Pair this phone" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(WRONG_CODE_MESSAGE);
    await user.click(screen.getByRole("button", { name: "Type a code instead" }));
    expect(screen.queryByRole("alert")).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "Code from your computer" }), code);
    await user.click(screen.getByRole("button", { name: "Pair this phone" }));
    await screen.findByRole("heading", { level: 1, name: "Paired" });
  });
});

describe("why the phone is here again", () => {
  it("?removed=1: removed on the computer", async () => {
    useUnpairedPhone();
    openPair("/pair?removed=1");
    expect(await screen.findByText(REMOVED_NOTE)).toBeInTheDocument();
  });

  it("?removed=token_reuse: its sign-in was used from two places", async () => {
    useUnpairedPhone();
    openPair("/pair?removed=token_reuse");
    const note = await screen.findByText(TOKEN_REUSE_NOTE);
    expect(note.closest("div.rounded-xl")).toHaveClass("bg-danger-soft");
  });

  it("?removed=code_reused: another device used its pairing code (UX review: it said only 'removed')", async () => {
    useUnpairedPhone();
    openPair("/pair?removed=code_reused");
    const note = await screen.findByText(CODE_REUSED_NOTE);
    expect(note.closest("div.rounded-xl")).toHaveClass("bg-danger-soft");
  });

  it("?removed=unused: forgotten after 30 days", async () => {
    useUnpairedPhone();
    openPair("/pair?removed=unused");
    expect(await screen.findByText(UNUSED_NOTE)).toBeInTheDocument();
  });

  it("each reason the phone listener gives has its words; anything else is 'removed'", () => {
    const note = (removed: string) => removedNote(new URLSearchParams({ removed }));
    expect(note("token_reuse")).toEqual({ tone: "danger", text: TOKEN_REUSE_NOTE });
    expect(note("code_reused")).toEqual({ tone: "danger", text: CODE_REUSED_NOTE });
    expect(note("unused")).toEqual({ tone: "warn", text: UNUSED_NOTE });
    expect(note("1")).toEqual({ tone: "warn", text: REMOVED_NOTE });
    expect(note("<script>")).toEqual({ tone: "warn", text: REMOVED_NOTE });
    expect(removedNote(new URLSearchParams())).toBeNull();
  });

  it("no note on a first pairing", async () => {
    useUnpairedPhone();
    openPair("/pair");
    await screen.findByRole("heading", { level: 1, name: PAIR_TITLE });
    expect(screen.queryByText(REMOVED_NOTE)).toBeNull();
    expect(screen.queryByText(TOKEN_REUSE_NOTE)).toBeNull();
  });
});

describe("a second QR code scanned while the page is open", () => {
  it("replaces the code (the browser only changes the fragment)", async () => {
    const { srv, code } = useUnpairedPhone();
    const { router } = openPair(`/pair#${code}`);
    await screen.findByText(formatCode(code));
    const next = srv.phone.startPairing().code;
    await act(() => router.navigate(`/pair#${next}`));
    const form = screen.getByRole("form", { name: PAIR_TITLE });
    expect(within(form).getByText(formatCode(next))).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.hash).toBe(""));
  });
});
