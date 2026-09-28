import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, makeTestQueryClient } from "@/test/render";
import { toast } from "@/components/ui/Toast";
import { HIGH_STAKES_KINDS } from "@/api/types";
import { DOCUMENT_KIND_COPY } from "@/lib/copy";
import { KindPicker } from "./KindPicker";

let fetchSpy: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchSpy = vi.fn(async () => new Response(JSON.stringify({ id: "doc_1", kind: "court_payment_order" }), { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchSpy);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

async function refile() {
  const success = vi.spyOn(toast, "success");
  renderWithProviders(<KindPicker doc={{ id: "doc_1", kind: "dunning" }} />, { client: makeTestQueryClient() });
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Change what kind of letter this is" }));
  await user.selectOptions(screen.getByLabelText(/Kind of letter/), "court_payment_order");
  const note = screen.queryByText(/In this online demo the kind is saved/);
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(success).toHaveBeenCalled());
  const description = String(success.mock.calls[0]![1]!.description);
  success.mockRestore();
  return { note, description };
}

describe("KindPicker", () => {
  it("says the installed app works the new kind's dates out again", async () => {
    const { note, description } = await refile();
    expect(note).toBeNull();
    expect(description).toBe("Its dates and to-dos were worked out again.");
    const [url, init] = fetchSpy.mock.calls[0]! as [string, RequestInit];
    expect(url).toBe("/api/documents/doc_1");
    expect(JSON.parse(String(init.body))).toEqual({ kind: "court_payment_order" });
  });

  it("never claims the online demo worked the dates out again (review round 1: it has no rules engine)", async () => {
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    const { note, description } = await refile();
    expect(note).not.toBeNull();
    expect(description).toMatch(/online demo the new kind's dates and deadlines aren't worked out/);
    expect(description).not.toMatch(/were worked out again/);
  });

  it("says what each letter kind with legal deadlines changes, its German name marked German (R2-ui-foundations-5)", async () => {
    renderWithProviders(<KindPicker doc={{ id: "doc_1", kind: "operating_costs" }} />, { client: makeTestQueryClient() });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Change what kind of letter this is" }));
    const select = screen.getByLabelText(/Kind of letter/);
    const hintOf = () => document.getElementById(select.getAttribute("aria-describedby")!.split(" ")[0]!)!;
    // more than the bare German word: what the kind changes
    const soft = /\u00ad/g;
    expect(hintOf().textContent!.replace(soft, "")).toMatch(/^Betriebskostenabrechnung: twelve months from its arrival to object; .*back-payment/);
    const term = hintOf().querySelector('[lang="de"]')!;
    expect(term.textContent!.replace(soft, "")).toBe("Betriebskostenabrechnung");
    // only the German word: the English rest is read in the page's language
    expect(term.textContent).not.toMatch(/twelve/);
    for (const kind of HIGH_STAKES_KINDS) {
      await user.selectOptions(select, kind);
      const hint = hintOf();
      expect(hint.textContent!.replace(soft, "")).toBe(DOCUMENT_KIND_COPY[kind].hint);
      const german = hint.querySelector('[lang="de"]')!.textContent!.replace(soft, "");
      expect(DOCUMENT_KIND_COPY[kind].hint!.startsWith(german), kind).toBe(true);
      expect(german, kind).toMatch(/^[A-ZÄÖÜ]\p{Ll}+$/u);
    }
  });
});
