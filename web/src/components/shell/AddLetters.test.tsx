/**
 * Adding letters (audit round 1, bucket "shell-b"): the dialog says what happens in the mode the
 * switch is in ("Keep private — no AI" never promises Claude reads), files are rows with an icon,
 * a middle-truncated name, type and size and a way to take one out, every file and page can be
 * reached, pages can be put in order and seen larger, skipped files are named, and the drop
 * overlay is opaque.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import { TEST_HEALTH, makeTestQueryClient, renderWithProviders } from "@/test/render";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import type { Health } from "@/api/types";
import { ACCEPTED_SHORT, AddLettersProvider, FileName, addDescription, claudeNotReady, fileKind, useAddLetters } from "./AddLetters";
import { DropZone } from "./DropZone";

let fetchSpy: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchSpy = vi.fn(async () =>
    new Response(JSON.stringify({ documents: [], jobs: [], duplicates: [], errors: [] }), { status: 201, headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fetchSpy);
  // jsdom has no object URLs (the page thumbnails use them)
  URL.createObjectURL = () => "blob:test";
  URL.revokeObjectURL = () => {};
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const pdf = (name: string, bytes = 2048) => new File([new Uint8Array(bytes)], name, { type: "application/pdf" });
const photo = (name: string) => new File([new Uint8Array(10)], name, { type: "image/jpeg" });

function Adder({ files }: { files: File[] }) {
  const { addFiles } = useAddLetters();
  return (
    <button type="button" onClick={() => addFiles(files)}>
      Add them
    </button>
  );
}

function renderAdder(files: File[], health: Health = TEST_HEALTH) {
  const client = makeTestQueryClient();
  client.setQueryData(qk.health, health);
  renderWithProviders(
    <AddLettersProvider>
      <Adder files={files} />
      <Toaster />
    </AddLettersProvider>,
    { client },
  );
  return userEvent.setup();
}

/** The upload's FormData (the last request). */
function sentForm(): FormData {
  const [, init] = fetchSpy.mock.calls.at(-1)! as [string, RequestInit];
  return init.body as FormData;
}

describe("Keep private — no AI: the dialog follows the switch", () => {
  it("stops promising that Claude reads the letters, and locks the button", async () => {
    const user = renderAdder([pdf("mietvertrag.pdf")]);
    await user.click(screen.getByRole("button", { name: "Add them" }));
    const dialog = await screen.findByRole("dialog", { name: "Add this letter?" });
    expect(dialog).toHaveAccessibleDescription(/Claude reads it through your Claude account/);
    expect(within(dialog).getByRole("button", { name: "Add letter" }).querySelector("svg")).toHaveClass("lucide-upload");

    await user.click(within(dialog).getByRole("switch", { name: /Keep private/ }));
    expect(dialog).toHaveAccessibleDescription(/Stored on this computer only and searchable by its text\. Claude never reads it/);
    expect(dialog).not.toHaveAccessibleDescription(/Claude reads it/);
    expect(within(dialog).getByRole("button", { name: "Store privately" }).querySelector("svg")).toHaveClass("lucide-lock");
  });

  it("the combine question stops promising reading across pages", async () => {
    const user = renderAdder([photo("seite1.jpg"), photo("seite2.jpg")]);
    await user.click(screen.getByRole("button", { name: "Add them" }));
    const dialog = await screen.findByRole("dialog", { name: "Are these pages of one letter?" });
    expect(dialog).toHaveAccessibleDescription(/read together, so dates and amounts are found across pages/);
    await user.click(within(dialog).getByRole("switch", { name: /Keep private/ }));
    expect(dialog).toHaveAccessibleDescription(/kept as one letter with its pages in this order — on this computer only/);
    expect(dialog).not.toHaveAccessibleDescription(/read together/);
  });
});

describe("Claude isn't ready: store now, read later", () => {
  const health = (claude: Partial<Health["claude"]>, backend = "claude"): Health => ({
    ...TEST_HEALTH,
    backend,
    claude: { ...TEST_HEALTH.claude, installed: false, ok: null, ...claude },
  });

  it("says so, keeps Keep private off and stores the letter to be read once Claude is connected", async () => {
    const user = renderAdder([pdf("mietvertrag.pdf")], health({ installed: false, ok: false }));
    await user.click(screen.getByRole("button", { name: "Add them" }));
    const dialog = await screen.findByRole("dialog", { name: "Add this letter?" });
    expect(dialog).toHaveAccessibleDescription(/^Claude isn't installed yet, so Ordnung stores it now and reads it as soon as Claude is connected/);
    expect(within(dialog).getByRole("switch", { name: /Keep private/ })).not.toBeChecked();
    const store = within(dialog).getByRole("button", { name: "Store now, read later" });
    expect(store).toHaveFocus();
    await user.click(store);
    expect(sentForm().get("private")).toBe("false");
  });

  it("names signing in, and leaves a session that doesn't use Claude as it was", () => {
    expect(claudeNotReady(health({ installed: true, ok: false }))).toBe("signed_out");
    expect(claudeNotReady(health({ installed: true, ok: null }))).toBeNull(); // not checked yet: the first letter tells
    expect(claudeNotReady(health({ installed: false }, "replay"))).toBeNull();
    expect(claudeNotReady(undefined)).toBeNull();
    expect(addDescription(false, true, "signed_out")).toMatch(/^Claude isn't signed in yet, so Ordnung stores them now and reads them/);
    expect(addDescription(true, false, "missing")).toMatch(/^Stored on this computer only/);
  });
});

describe("the files about to be added", () => {
  it("are rows with an icon, the whole name (on hover and read out), type and size", async () => {
    const long = "Einkommensteuerbescheid_2025_Finanzamt_Musterstadt_Steuernummer_123-456-78901_Seite1.pdf";
    const user = renderAdder([pdf(long, 250_000), photo("brief.jpg")]);
    await user.click(screen.getByRole("button", { name: "Add them" }));
    const list = await screen.findByRole("list", { name: "Files to add" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByTitle(long)).toBeInTheDocument();
    expect(within(rows[0]!).getByText(long)).toHaveClass("sr-only");
    expect(rows[0]).toHaveTextContent("PDF · 244 KB");
    expect(rows[1]).toHaveTextContent("Photo · 10 B");
    expect(rows[0]!.querySelector("svg")).toHaveClass("lucide-file-text");
    expect(rows[1]!.querySelector("svg")).toHaveClass("lucide-file-image");
  });

  it("can lose one file before anything is sent; focus stays on the list", async () => {
    const user = renderAdder([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")]);
    await user.click(screen.getByRole("button", { name: "Add them" }));
    await screen.findByRole("dialog", { name: "Add 3 letters?" });
    await user.click(screen.getByRole("button", { name: "Remove b.pdf" }));
    expect(screen.getByRole("dialog", { name: "Add 2 letters?" })).toBeInTheDocument();
    // the row that moved up into its place has focus
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove c.pdf" })).toHaveFocus());
    await user.click(screen.getByRole("button", { name: "Add letters" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    expect(sentForm().getAll("files").map((f) => (f as File).name)).toEqual(["a.pdf", "c.pdf"]);
  });

  it("lists every file on request", async () => {
    const files = Array.from({ length: 11 }, (_, i) => pdf(`brief-${i + 1}.pdf`));
    const user = renderAdder(files);
    await user.click(screen.getByRole("button", { name: "Add them" }));
    const list = await screen.findByRole("list", { name: "Files to add" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(8);
    await user.click(screen.getByRole("button", { name: "Show all 11 files" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(11);
  });
});

describe("photos as pages of one letter", () => {
  it("can all be reached, put in order and seen larger — and are sent in that order", async () => {
    const photos = Array.from({ length: 10 }, (_, i) => photo(`seite-${i + 1}.jpg`));
    const user = renderAdder(photos);
    await user.click(screen.getByRole("button", { name: "Add them" }));
    const pages = await screen.findByRole("list", { name: "Pages, in order" });
    // a grid that wraps (no page cut off by a sideways scroller)
    expect(pages).toHaveClass("grid");
    expect(within(pages).getAllByRole("button", { name: /show larger/ })).toHaveLength(8);
    await user.click(within(pages).getByRole("button", { name: /\+2 more/ }));
    expect(within(pages).getAllByRole("button", { name: /show larger/ })).toHaveLength(10);

    // page 1 has no "earlier", the last page no "later"
    expect(screen.queryByRole("button", { name: "Move page 1 earlier" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Move page 10 later" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Move page 1 later" }));
    // the moved page keeps focus on the same arrow
    await waitFor(() => expect(screen.getByRole("button", { name: "Move page 2 later" })).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Page 1: seite-2.jpg — show larger" }));
    const preview = await screen.findByRole("dialog", { name: "Page 1 of 10" });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(preview).not.toBeInTheDocument());
    expect(screen.getByRole("dialog", { name: "Are these pages of one letter?" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Combine into one letter" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const names = sentForm().getAll("files").map((f) => (f as File).name);
    expect(names.slice(0, 3)).toEqual(["seite-2.jpg", "seite-1.jpg", "seite-3.jpg"]);
  });
});

describe("files Ordnung can't read", () => {
  it("are named in the warning, with every type it does read (WEBP and e-mails too)", async () => {
    const user = renderAdder([new File(["x"], "notizen.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" })]);
    await user.click(screen.getByRole("button", { name: "Add them" }));
    const warning = await screen.findByText("1 file skipped");
    const toast = warning.closest("li")!;
    expect(toast).toHaveTextContent("notizen.docx isn't a file Ordnung reads");
    expect(toast).toHaveTextContent("JPG, PNG, WEBP, HEIC");
    // "e‑mail" with a non-breaking hyphen (U+2011): it never splits over two lines
    expect(toast).toHaveTextContent("saved e\u2011mails (.eml)");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("takes a saved e-mail and a text file like the watched folder does", async () => {
    const user = renderAdder([
      new File(["From: a@example.org\r\nSubject: Rechnung\r\n\r\nHallo"], "rechnung.eml", { type: "" }),
      new File(["Notiz"], "notiz.txt", { type: "text/plain" }),
    ]);
    await user.click(screen.getByRole("button", { name: "Add them" }));
    expect(screen.queryByText(/skipped/)).toBeNull();
    const dialog = await screen.findByRole("dialog");
    // each row says honestly what the file is (not "PDF" for everything that isn't a photo)
    const rows = within(within(dialog).getByRole("list", { name: "Files to add" })).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("E\u2011mail ·");
    expect(rows[1]).toHaveTextContent("Text file ·");
  });
});

describe("fileKind", () => {
  const file = (name: string, type: string) => new File(["x"], name, { type });
  it("names a photo, a saved e-mail, a text file and a PDF — by type or by extension", () => {
    expect(fileKind(file("seite-1.jpg", "image/jpeg")).label).toBe("Photo");
    expect(fileKind(file("scan.HEIC", "")).label).toBe("Photo");
    expect(fileKind(file("Rechnung.eml", "message/rfc822")).label).toBe("E\u2011mail");
    expect(fileKind(file("Rechnung.eml", "")).label).toBe("E\u2011mail");
    expect(fileKind(file("notiz.txt", "text/plain")).label).toBe("Text file");
    expect(fileKind(file("notiz.TXT", "")).label).toBe("Text file");
    expect(fileKind(file("Bescheid.pdf", "application/pdf")).label).toBe("PDF");
  });

  it("the short wording names saved e-mails, unbroken", () => {
    expect(ACCEPTED_SHORT).toBe("PDFs, phone photos or saved e\u2011mails");
  });
});

describe("drop overlay", () => {
  it("is an opaque card on a nearly opaque veil (the page doesn't show through its text)", () => {
    renderWithProviders(
      <AddLettersProvider>
        <DropZone />
      </AddLettersProvider>,
    );
    const drag = new Event("dragenter", { bubbles: true }) as DragEvent;
    Object.defineProperty(drag, "dataTransfer", { value: { types: ["Files"] } });
    act(() => {
      fireEvent(window, drag);
    });
    const title = screen.getByText("Drop to add letters");
    const card = title.parentElement!;
    expect(card).toHaveClass("bg-surface");
    expect(card.className).not.toMatch(/bg-surface\/\d+/);
    expect(card.parentElement).toHaveClass("bg-canvas/90");
  });
});

describe("FileName", () => {
  it("keeps the end of a long name (number and extension) and cuts the middle", () => {
    const name = "Kontoauszug_2026_09_Musterbank_IBAN_DE12345678901234567890.pdf";
    renderWithProviders(<FileName name={name} />);
    const shown = screen.getByTitle(name).querySelector("[aria-hidden]")!;
    const [head, tail] = Array.from(shown.children);
    expect(head).toHaveClass("text-ellipsis", "overflow-hidden");
    expect(tail).toHaveClass("shrink-0");
    expect(tail!.textContent).toBe("1234567890.pdf");
    expect(head!.textContent! + tail!.textContent!).toBe(name);
  });
});
