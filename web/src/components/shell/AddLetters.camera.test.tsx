/**
 * Adding a letter on a paired phone (design §13.4): "Add letters" asks how — Photograph a letter (the rear camera,
 * through a file input with `capture`) or Choose files. Each photo becomes a page of "Pages of one letter", named
 * `photo-<day>-<time>-p<n>` by its place; pages can be reordered, removed and seen larger; "Add letter" sends them
 * as one letter in that order. Sending says how far it got and can be stopped, the dialog stays until the photos
 * are on the computer, and closing asks before photos that exist nowhere else are thrown away. The computer's
 * "Add letters" is as it was.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setClientKind } from "@/api/clientKind";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { AddLettersProvider, SEND_STOPPED, cameraDescription, photoName, photoStamp, useAddLetters } from "./AddLetters";

const UPLOADED = { documents: [{ id: "doc_new", title: null }], jobs: [{ id: "job_new", doc_id: "doc_new" }], duplicates: [], errors: [] };

/** `XMLHttpRequest` as the phone's upload uses it: the test answers it, reports progress or sees it stopped. */
class FakeXhr {
  static all: FakeXhr[] = [];
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  statusText = "";
  responseText = "";
  withCredentials = false;
  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: FormData | null = null;
  aborted = false;
  private responseType = "";
  constructor() {
    FakeXhr.all.push(this);
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  getResponseHeader(name: string) {
    return name.toLowerCase() === "content-type" ? this.responseType : null;
  }
  send(body: FormData) {
    this.body = body;
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }
  respond(status: number, body: unknown) {
    this.status = status;
    this.statusText = status === 201 ? "Created" : "Error";
    this.responseText = JSON.stringify(body);
    this.responseType = "application/json";
    this.onload?.();
  }
  static get last(): FakeXhr {
    return FakeXhr.all.at(-1)!;
  }
}

let fetchSpy: ReturnType<typeof vi.fn>;
beforeEach(() => {
  FakeXhr.all = [];
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  fetchSpy = vi.fn(async () => new Response(JSON.stringify(UPLOADED), { status: 201, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchSpy);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  // the photos' names carry the minute the first page was taken (only Date is faked: the dialogs' frames run)
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 7, 8, 14));
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

function Opener() {
  const { openPicker, uploading } = useAddLetters();
  return (
    <button type="button" onClick={openPicker} aria-busy={uploading || undefined}>
      Add letters
    </button>
  );
}

function renderAdder({ phone = true } = {}) {
  setClientKind(phone ? "phone" : "computer");
  renderWithProviders(
    <AddLettersProvider>
      <Opener />
      <Toaster />
    </AddLettersProvider>,
  );
  return userEvent.setup();
}

const camera = () => document.querySelector<HTMLInputElement>("input[data-camera]")!;
const shot = (name = "image.jpg") => new File([new Uint8Array(12)], name, { type: "image/jpeg" });

/** Photograph a letter: the chooser, then `pages` photos one after another. */
async function photograph(user: ReturnType<typeof userEvent.setup>, pages = 2) {
  await user.click(screen.getByRole("button", { name: "Add letters" }));
  const chooser = await screen.findByRole("dialog", { name: "Add a letter" });
  await user.click(within(chooser).getByRole("button", { name: "Photograph a letter" }));
  await user.upload(camera(), shot());
  const dialog = await screen.findByRole("dialog", { name: "Pages of one letter" });
  for (let i = 1; i < pages; i++) {
    await user.click(within(dialog).getByRole("button", { name: "Take another page" }));
    await user.upload(camera(), shot());
  }
  return dialog;
}

/** The pages in the dialog, in order, by their names. */
function pageNames(dialog: HTMLElement): string[] {
  return within(within(dialog).getByRole("list", { name: "Pages, in order" }))
    .getAllByRole("button", { name: /^Page \d+:/ })
    .map((b) => /^Page \d+: (\S+)/.exec(b.getAttribute("aria-label") ?? "")![1]!);
}

describe("the chooser", () => {
  it("asks how to add a letter: photograph it, or choose files", async () => {
    const user = renderAdder();
    const fileInput = document.querySelector<HTMLInputElement>("input[type=file][multiple]")!;
    const pickFiles = vi.spyOn(fileInput, "click");
    const takePhoto = vi.spyOn(camera(), "click");
    await user.click(screen.getByRole("button", { name: "Add letters" }));
    const chooser = await screen.findByRole("dialog", { name: "Add a letter" });
    expect(chooser).toHaveAccessibleDescription(/Your files stay on your computer\./);
    await user.click(within(chooser).getByRole("button", { name: "Photograph a letter" }));
    expect(takePhoto).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add a letter" })).toBeNull());

    await user.click(screen.getByRole("button", { name: "Add letters" }));
    await user.click(within(await screen.findByRole("dialog", { name: "Add a letter" })).getByRole("button", { name: "Choose files" }));
    expect(pickFiles).toHaveBeenCalledTimes(1);
  });

  it("the camera is a file input for photos from the rear camera — no camera permission is ever held", () => {
    renderAdder();
    const input = camera();
    expect(input).toHaveAttribute("type", "file");
    expect(input).toHaveAttribute("accept", "image/*");
    expect(input).toHaveAttribute("capture", "environment");
    expect(input).not.toHaveAttribute("multiple");
    expect(input).toHaveAttribute("aria-hidden", "true");
    expect(input).toHaveAttribute("tabindex", "-1");
    // with the dialogs, never inside the app a dialog makes inert
    expect(input.closest("#overlay-root")).not.toBeNull();
  });
});

describe("pages of one letter", () => {
  it("one photo is a page already: the dialog shows it, named for the minute it was taken", async () => {
    const user = renderAdder();
    const dialog = await photograph(user, 1);
    expect(dialog).toHaveAccessibleDescription(cameraDescription(1, false));
    expect(dialog).toHaveAccessibleDescription(/^1 page\. Photograph the next page, or add the letter\. The photos go to your computer and stay there\.$/);
    expect(pageNames(dialog)).toEqual(["photo-2026-10-07-0814-p1.jpg"]);
    expect(within(dialog).queryByRole("button", { name: "Separate letters" })).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Add letter" })).toBeInTheDocument();
  });

  it("each page is named by its place, also after it is moved or removed", async () => {
    expect(photoStamp(new Date(2026, 0, 2, 3, 4))).toBe("2026-01-02-0304");
    expect(photoName("2026-10-07-0814", 3, new File([], "IMG_1.HEIC", { type: "image/heic" }))).toBe("photo-2026-10-07-0814-p3.heic");
    const user = renderAdder();
    // three photos told apart by their size (1, 2 and 3 bytes), all named "image.jpg" by the phone
    await user.click(screen.getByRole("button", { name: "Add letters" }));
    await user.click(within(await screen.findByRole("dialog", { name: "Add a letter" })).getByRole("button", { name: "Photograph a letter" }));
    await user.upload(camera(), new File([new Uint8Array(1)], "image.jpg", { type: "image/jpeg" }));
    const dialog = await screen.findByRole("dialog", { name: "Pages of one letter" });
    for (const size of [2, 3]) {
      await user.click(within(dialog).getByRole("button", { name: "Take another page" }));
      await user.upload(camera(), new File([new Uint8Array(size)], "image.jpg", { type: "image/jpeg" }));
    }
    expect(dialog).toHaveAccessibleDescription(/^3 pages\./);
    expect(pageNames(dialog)).toEqual(["photo-2026-10-07-0814-p1.jpg", "photo-2026-10-07-0814-p2.jpg", "photo-2026-10-07-0814-p3.jpg"]);
    // the last photo moved to the front: it is page 1 now, and named so
    await user.click(within(dialog).getByRole("button", { name: "Move page 3 earlier" }));
    await user.click(within(dialog).getByRole("button", { name: "Move page 2 earlier" }));
    expect(pageNames(dialog)).toEqual(["photo-2026-10-07-0814-p1.jpg", "photo-2026-10-07-0814-p2.jpg", "photo-2026-10-07-0814-p3.jpg"]);
    // the first photo taken (now page 2) taken out
    await user.click(within(dialog).getByRole("button", { name: "Remove page 2" }));
    expect(pageNames(dialog)).toEqual(["photo-2026-10-07-0814-p1.jpg", "photo-2026-10-07-0814-p2.jpg"]);
    expect(dialog).toHaveAccessibleDescription(/^2 pages\./);
    await user.click(within(dialog).getByRole("button", { name: "Add letter" }));
    const sent = FakeXhr.last.body!.getAll("files") as File[];
    expect(sent.map((f) => [f.name, f.size])).toEqual([
      ["photo-2026-10-07-0814-p1.jpg", 3],
      ["photo-2026-10-07-0814-p2.jpg", 2],
    ]);
  });

  it("Add letter sends one letter, its pages in the order shown", async () => {
    const user = renderAdder();
    const a = new File([new Uint8Array(1)], "image.jpg", { type: "image/jpeg" });
    const b = new File([new Uint8Array(2)], "image.jpg", { type: "image/jpeg" });
    await user.click(screen.getByRole("button", { name: "Add letters" }));
    await user.click(within(await screen.findByRole("dialog", { name: "Add a letter" })).getByRole("button", { name: "Photograph a letter" }));
    await user.upload(camera(), a);
    const dialog = await screen.findByRole("dialog", { name: "Pages of one letter" });
    await user.click(within(dialog).getByRole("button", { name: "Take another page" }));
    await user.upload(camera(), b);
    // the second photo first
    await user.click(within(dialog).getByRole("button", { name: "Move page 2 earlier" }));
    await user.click(within(dialog).getByRole("button", { name: "Add letter" }));

    const xhr = FakeXhr.last;
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/documents");
    expect(xhr.headers["X-Ordnung-Client"]).toBe("web");
    expect(xhr.withCredentials).toBe(true);
    const sent = xhr.body!.getAll("files") as File[];
    expect(sent.map((f) => f.name)).toEqual(["photo-2026-10-07-0814-p1.jpg", "photo-2026-10-07-0814-p2.jpg"]);
    expect(sent.map((f) => f.size)).toEqual([2, 1]);
    expect(xhr.body!.get("combine")).toBe("true");
    expect(xhr.body!.get("private")).toBe("false");
    expect(fetchSpy).not.toHaveBeenCalled();

    // the dialog stays until the photos are on the computer
    expect(screen.getByRole("dialog", { name: "Pages of one letter" })).toBeInTheDocument();
    act(() => xhr.respond(201, UPLOADED));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Pages of one letter" })).toBeNull());
  });

  it("Separate letters (from two pages) sends each photo as a letter of its own", async () => {
    const user = renderAdder();
    const dialog = await photograph(user, 2);
    await user.click(within(dialog).getByRole("button", { name: "Separate letters" }));
    expect(FakeXhr.last.body!.get("combine")).toBe("false");
  });

  it("Keep private sends it private, and says where the photos go", async () => {
    const user = renderAdder();
    const dialog = await photograph(user, 1);
    await user.click(within(dialog).getByRole("switch", { name: /Keep private/ }));
    expect(dialog).toHaveAccessibleDescription(/The photos go to your computer only, and Claude never reads them\./);
    expect(within(dialog).getByText("Store and search it on your computer only; Claude never sees it.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Store privately" }));
    expect(FakeXhr.last.body!.get("private")).toBe("true");
  });

  it("closing asks before photos that exist nowhere else are thrown away", async () => {
    const user = renderAdder();
    const dialog = await photograph(user, 2);
    await user.keyboard("{Escape}");
    const ask = await screen.findByRole("dialog", { name: "Discard 2 photos?" });
    expect(ask).toHaveAccessibleDescription("They haven't been sent.");
    await user.click(within(ask).getByRole("button", { name: "Keep them" }));
    expect(screen.getByRole("dialog", { name: "Pages of one letter" })).toBe(dialog);
    expect(pageNames(dialog)).toHaveLength(2);

    await user.click(within(dialog).getByRole("button", { name: /^Close/ }));
    await user.click(within(await screen.findByRole("dialog", { name: "Discard 2 photos?" })).getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Pages of one letter" })).toBeNull());
    expect(FakeXhr.all).toHaveLength(0);
  });
});

describe("sending from a phone", () => {
  it("says how far it got, and Cancel stops it — the photos stay", async () => {
    const user = renderAdder();
    const dialog = await photograph(user, 3);
    await user.click(within(dialog).getByRole("button", { name: "Add letter" }));
    const xhr = FakeXhr.last;
    expect(within(dialog).getByText("Sending 3 pages… 0%")).toBeInTheDocument();
    act(() => xhr.progress(45, 100));
    expect(within(dialog).getByText("Sending 3 pages… 45%")).toBeInTheDocument();
    expect(within(dialog).getByRole("progressbar", { name: "Sending 3 pages" })).toHaveAttribute("aria-valuenow", "45");
    // nothing else to choose meanwhile, and the dialog doesn't close by itself
    expect(within(dialog).queryByRole("button", { name: "Add letter" })).toBeNull();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: /Discard/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Add letters" })).toHaveAttribute("aria-busy", "true");

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(xhr.aborted).toBe(true);
    expect(await within(dialog).findByText(SEND_STOPPED)).toBeInTheDocument();
    expect(pageNames(dialog)).toHaveLength(3);
    expect(within(dialog).getByRole("button", { name: "Add letter" })).toBeInTheDocument();
  });

  it("a refusal shows in the dialog, in the API's words; the photos stay to try again", async () => {
    const user = renderAdder();
    const dialog = await photograph(user, 1);
    await user.click(within(dialog).getByRole("button", { name: "Add letter" }));
    act(() => FakeXhr.last.respond(413, { detail: "These files are larger than Ordnung takes at once (200 MB).", code: "too_large" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Not sent: These files are larger than Ordnung takes at once (200 MB).");
    await user.click(within(dialog).getByRole("button", { name: "Add letter" }));
    expect(FakeXhr.all).toHaveLength(2);
  });

  it("the computer not answering is said as the phone says it", async () => {
    const user = renderAdder();
    const dialog = await photograph(user, 1);
    await user.click(within(dialog).getByRole("button", { name: "Add letter" }));
    act(() => FakeXhr.last.onerror?.());
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/Can't reach your computer/);
  });

  it("files chosen on the phone go the same way", async () => {
    const user = renderAdder();
    const fileInput = document.querySelector<HTMLInputElement>("input[type=file][multiple]")!;
    await user.upload(fileInput, new File([new Uint8Array(3)], "Mietvertrag.pdf", { type: "application/pdf" }));
    const dialog = await screen.findByRole("dialog", { name: "Add this letter?" });
    expect(dialog).toHaveAccessibleDescription(/Your files stay on your computer\./);
    await user.click(within(dialog).getByRole("button", { name: "Add letter" }));
    expect(within(dialog).getByText("Sending 1 file… 0%")).toBeInTheDocument();
    act(() => FakeXhr.last.respond(201, UPLOADED));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add this letter?" })).toBeNull());
    expect((FakeXhr.last.body!.getAll("files") as File[]).map((f) => f.name)).toEqual(["Mietvertrag.pdf"]);
  });
});

describe("the computer's Add letters is as it was", () => {
  it("opens the file picker at once, has no camera, and sends with fetch", async () => {
    const user = renderAdder({ phone: false });
    expect(camera()).toBeNull();
    const fileInput = document.querySelector<HTMLInputElement>("input[type=file][multiple]")!;
    expect(fileInput.closest("#overlay-root")).toBeNull();
    const pick = vi.spyOn(fileInput, "click");
    await user.click(screen.getByRole("button", { name: "Add letters" }));
    expect(pick).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "Add a letter" })).toBeNull();

    await user.upload(fileInput, [shot("seite1.jpg"), shot("seite2.jpg")]);
    const dialog = await screen.findByRole("dialog", { name: "Are these pages of one letter?" });
    expect(pageNames(dialog)).toEqual(["seite1.jpg", "seite2.jpg"]);
    await user.click(within(dialog).getByRole("button", { name: "Combine into one letter" }));
    // the dialog closes at once (no progress in it); the upload is one fetch
    expect(within(dialog).queryByText(/^Sending/)).toBeNull();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Are these pages of one letter?" })).toBeNull());
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    expect(FakeXhr.all).toHaveLength(0);
  });
});
