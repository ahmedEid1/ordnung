/**
 * Settings → Data → *Text in pictures* (ADR 0024): the person's switch for reading the words in photos and scans
 * Claude isn't reading, and a line from `health.picture_text` that says what this computer does — in the doctor's
 * words, code set as code. `ORDNUNG_OCR=off` wins over the switch (a callout says so); a save says what changed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AppSettings, Health, PictureTextStatus } from "@/api/types";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { SETTINGS } from "@/mocks/data/system";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { qk } from "@/api/hooks";
import SettingsPage from "@/pages/SettingsPage";
import { PHONE_SETTINGS_TEXT } from "./PhoneSettingsNotice";
import { PICTURE_TEXT_COPY as COPY, PictureTextCard } from "./PictureTextCard";

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
  vi.unstubAllEnvs();
  act(() => __clearToasts());
});

/** The doctor's rows for each state, as `ordnung.doctor.picture_text_status` gives them on Linux. */
const LINUX_INSTALL =
  "To find photos and scans Claude doesn't read by their words, install Tesseract: `sudo apt install tesseract-ocr " +
  "tesseract-ocr-deu` (Fedora: `sudo dnf install tesseract tesseract-langpack-deu`), then restart Ordnung.";
const STATES: Record<PictureTextStatus["state"], PictureTextStatus> = {
  reading: {
    state: "reading",
    detail: "Tesseract 5.3.4 (German and English): photos and scans Claude doesn't read are found by their words, not checked",
    fix: null,
  },
  not_installed: { state: "not_installed", detail: "Not installed (optional)", fix: LINUX_INSTALL },
  not_usable: {
    state: "not_usable",
    detail: "Tesseract 5.3.4 has no German language data: words with ä, ö, ü or ß are often misread",
    fix: "Install the German language data: `sudo apt install tesseract-ocr-deu` (Fedora: `sudo dnf install tesseract-langpack-deu`), then restart Ordnung.",
  },
  off: { state: "off", detail: "Off (Settings → Data → Text in pictures)", fix: null },
  off_by_variable: { state: "off_by_variable", detail: "Turned off (ORDNUNG_OCR=off)", fix: null },
};

function show(state: PictureTextStatus["state"], read = state !== "off") {
  const health: Health = { ...TEST_HEALTH, picture_text: STATES[state] };
  const settings: AppSettings = { ...SETTINGS, read_picture_text: read };
  const client = makeTestQueryClient();
  client.setQueryData(qk.health, health);
  return renderWithProviders(
    <>
      <PictureTextCard settings={settings} />
      <Toaster />
    </>,
    { client },
  );
}

const card = () => screen.getByRole("region", { name: COPY.title });
const status = () => within(card()).queryByTestId("picture-text-status");
// its label holds its description too
const theSwitch = () => within(card()).getByRole("switch", { name: (name) => name.startsWith(COPY.switchLabel) });

describe("Text in pictures: the card", () => {
  it("names the switch and says what it does", () => {
    show("reading");
    expect(within(card()).getByText(COPY.description)).toBeInTheDocument();
    expect(theSwitch()).toHaveAttribute("aria-checked", "true");
    expect(within(card()).getByText(COPY.switchDescription)).toBeInTheDocument();
  });

  it.each([
    ["reading", "muted", STATES.reading.detail],
    ["not_installed", "info", `${COPY.notInstalled} ${LINUX_INSTALL.replaceAll("`", "")}`],
    ["not_usable", "warn", `${STATES.not_usable.detail}. ${STATES.not_usable.fix!.replaceAll("`", "")}`],
  ] as const)("%s: the line under the switch, in its tone, code set as code", (state, tone, text) => {
    show(state);
    const line = status();
    expect(line).not.toBeNull();
    expect(line).toHaveAttribute("data-tone", tone);
    expect(line!.textContent).toBe(text);
    // the commands are code, never literal backticks
    expect(line!.textContent).not.toContain("`");
    if (state !== "reading") expect(within(line!).getAllByText(/^sudo /, { selector: "code" }).length).toBeGreaterThan(0);
  });

  it("off: no line (the switch says it)", () => {
    show("off");
    expect(theSwitch()).toHaveAttribute("aria-checked", "false");
    expect(status()).toBeNull();
  });

  it("turned off by the variable: a callout above the switch; the switch stays usable and shows the saved choice", async () => {
    show("off_by_variable", true);
    const note = within(card()).getByTestId("picture-text-variable");
    expect(note.textContent).toBe(COPY.variable.replaceAll("`", ""));
    expect(within(note).getByText("ORDNUNG_OCR=off", { selector: "code" })).toBeInTheDocument();
    expect(status()).toBeNull();
    expect(theSwitch()).toHaveAttribute("aria-checked", "true");
    expect(theSwitch()).toBeEnabled();
    // the callout comes before the switch
    expect(note.compareDocumentPosition(theSwitch()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("Text in pictures: saving", () => {
  /** Flip the switch from `from` and save, on a mock computer whose Text in pictures is `computer`. */
  async function saveFrom({ srv, calls }: ReturnType<typeof useMockApi>, computer: PictureTextStatus["state"], from: boolean) {
    srv.db.state.health = { ...srv.db.state.health, picture_text: STATES[computer] };
    srv.db.state.settings = { ...srv.db.state.settings, read_picture_text: from };
    const health: Health = { ...TEST_HEALTH, picture_text: from || computer === "off_by_variable" ? STATES[computer] : STATES.off };
    const client = makeTestQueryClient();
    client.setQueryData(qk.health, health);
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <PictureTextCard settings={{ ...SETTINGS, read_picture_text: from }} />
        <Toaster />
      </>,
      { client },
    );
    await user.click(theSwitch());
    await user.click(within(card()).getByRole("button", { name: "Save changes" }));
    const puts = calls.filter((c) => c.method === "PUT" && c.path === "/settings");
    return { puts, srv, client };
  }

  it("turned off: sends the switch alone, and the toast says the words read are deleted", async () => {
    const { puts, srv, client } = await saveFrom(useMockApi(), "reading", true);
    expect(await screen.findByText(COPY.toastOff[0])).toBeInTheDocument();
    expect(screen.getByText(COPY.toastOff[1])).toBeInTheDocument();
    expect(puts.map((c) => c.body)).toEqual([{ read_picture_text: false }]);
    expect(srv.db.state.settings.read_picture_text).toBe(false);
    // the line follows: health is asked again
    await vi.waitFor(() => expect(client.getQueryData<Health>(qk.health)?.picture_text?.state).toBe("off"));
  });

  it("turned on where Tesseract reads: the toast says pictures are read one page at a time", async () => {
    await saveFrom(useMockApi(), "reading", false);
    expect(await screen.findByText(COPY.toastOn[1])).toBeInTheDocument();
    expect(screen.getByText(COPY.toastOn[0])).toBeInTheDocument();
  });

  it("turned on where Tesseract isn't installed: the toast points to the line under the switch", async () => {
    await saveFrom(useMockApi(), "not_installed", false);
    expect(await screen.findByText(COPY.toastInstall[1])).toBeInTheDocument();
  });

  it("saved while the variable turns it off: the toast says when it counts", async () => {
    const { puts } = await saveFrom(useMockApi(), "off_by_variable", true);
    expect(await screen.findByText(COPY.toastVariable[1])).toBeInTheDocument();
    expect(screen.getByText(COPY.toastVariable[0])).toBeInTheDocument();
    expect(puts.map((c) => c.body)).toEqual([{ read_picture_text: false }]);
  });

  it("toast copy, word for word", () => {
    expect(COPY.toastOff).toEqual([
      "Text in pictures is off.",
      "The words Ordnung had read in pictures are deleted. Search finds those letters by their name.",
    ]);
    expect(COPY.toastOn).toEqual(["Text in pictures is on.", "Ordnung reads the pictures of letters Claude isn't reading, one page at a time."]);
    expect(COPY.toastInstall).toEqual(["Text in pictures is on.", "Install Tesseract to have pictures read (see the line under the switch)."]);
    expect(COPY.toastVariable).toEqual(["Saved.", "It counts once ORDNUNG_OCR is unset."]);
  });
});

describe("Text in pictures: where it is", () => {
  it("Settings → Data has it right after Where your data lives; a paired phone has no such card", async () => {
    useMockApi();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=data" });
    const where = await screen.findByRole("region", { name: "Where your data lives" });
    const pictures = await screen.findByRole("region", { name: COPY.title });
    const regions = screen.getAllByRole("region");
    expect(regions.indexOf(pictures)).toBe(regions.indexOf(where) + 1);
  });

  it("a paired phone's Settings has no card", async () => {
    useMockApi({ client: "phone" });
    renderWithProviders(<SettingsPage />, { route: "/settings?section=data" });
    expect(await screen.findByText(PHONE_SETTINGS_TEXT)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: COPY.title })).toBeNull();
  });
});

describe("Text in pictures: the static demo", () => {
  it("has a working switch, and the line says where Ordnung tells whether Tesseract is installed", () => {
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    show("not_installed");
    expect(status()!.textContent).toBe(COPY.staticDemo);
    expect(COPY.staticDemo).toBe("In Ordnung on your computer, this line says whether Tesseract is installed there.");
    expect(theSwitch()).toBeEnabled();
  });
});
