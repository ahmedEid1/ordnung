import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { QueryClient } from "@tanstack/react-query";
import { renderWithProviders } from "@/test/render";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { handleServerEvent, __resetEventsForTests } from "@/api/sse";
import type { DocumentRow, Household, HouseholdFiling, JobProgressEvent } from "@/api/types";
import { createMockServer, type MockServer } from "@/mocks/server";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { makeRow } from "@/features/document/fixtures";
import CASES from "@/features/export/selection-cases.json";
import { taxLetters, taxYears, undatedTaxLetters } from "@/features/taxes/taxYear";
import InboxPage from "@/pages/InboxPage";

let srv: MockServer;
/** Requests answered with HTTP 500 instead of the mock server (`GET /documents` → the list failed). */
let failing: Set<string>;
/** The letter list to answer instead of the mock server's (the shared selection table), or null. */
let listed: DocumentRow[] | null;
/** A household with people (`GET`/`PATCH /household`), as the API works it out, or null: the mock server's (nobody). */
let people: FakeHousehold | null;
/** The bodies of `PATCH /household`. */
let filings: HouseholdFiling["letters"][];

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  srv = createMockServer({ staticDemo: false, latency: 0 });
  failing = new Set();
  listed = null;
  people = null;
  filings = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    const path = url.pathname.replace(/^\/api/, "");
    const method = init?.method ?? "GET";
    if (failing.has(`${method} ${path}`)) return json({ detail: "Internal error" }, 500);
    if (listed && method === "GET" && path === "/documents" && !url.searchParams.get("q")) return json(listed);
    if (people && path === "/household") {
      if (method === "PATCH") {
        const letters = (body as HouseholdFiling).letters;
        filings.push(letters);
        for (const [id, answer] of Object.entries(letters)) {
          if (answer == null) delete people.links[id];
          else people.links[id] = answer;
        }
      }
      return json(householdOf(people));
    }
    return srv.handle(method, path, url.searchParams, body);
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  __resetEventsForTests();
  act(() => __clearToasts());
});

function renderInbox(route = "/inbox") {
  return renderWithProviders(
    <AddLettersProvider>
      <InboxPage />
      <Toaster />
    </AddLettersProvider>,
    { route },
  );
}

/** The household the fake `/household` keeps: its people, each letter's answer, and whom each letter's addressee names. */
interface FakeHousehold {
  members: { id: string; name: string; signs: boolean }[];
  links: Record<string, string>;
  addressed: Record<string, string>;
}

const ALEX = "hhm_alex00000001";
const MIA = "hhm_mia000000001";

/** `GET /api/household` as the API works it out: live filings, the person's own, the unanswered letters' suggestions. */
function householdOf(f: FakeHousehold): Household {
  const ids = new Set(f.members.map((m) => m.id));
  const filed = Object.fromEntries(Object.entries(f.links).filter(([, v]) => ids.has(v)));
  const mine = Object.entries(f.links)
    .filter(([, v]) => v === "me")
    .map(([k]) => k)
    .sort();
  const suggested = Object.fromEntries(Object.entries(f.addressed).filter(([id]) => !(id in filed) && !mine.includes(id)));
  return {
    members: f.members.map((m) => ({ ...m, letters: Object.values(filed).filter((v) => v === m.id).length })),
    filed,
    mine,
    suggested,
    version: "0123456789abcdef",
  };
}

/** Alex has the health insurer's letter filed; the dentist's and the library's are addressed to Alex and not filed; Mia has none. */
function withPeople(): FakeHousehold {
  people = {
    members: [
      { id: ALEX, name: "Alex Rivera", signs: true },
      { id: MIA, name: "Mia Rivera", signs: false },
    ],
    links: { doc_bkk: ALEX, doc_parking: "me" },
    addressed: { doc_dentist: ALEX, doc_library: ALEX },
  };
  return people;
}

const lettersPanel = () => screen.getByRole("tabpanel");
/** The letters the list shows (its month groups; not the card of letters to file above it). */
const listedIds = () =>
  [...lettersPanel().querySelectorAll<HTMLAnchorElement>("section[aria-labelledby^='grp-'] a[href^='/documents/']")].map((a) =>
    a.getAttribute("href")!.slice("/documents/".length),
  );
const optionsOf = (select: HTMLElement) => within(select).getAllByRole("option").map((o) => o.textContent);
/** The words of an element a screen reader reads (its text without what is `aria-hidden`), spaces tidied. */
function spoken(el: HTMLElement): string {
  const copy = el.cloneNode(true) as HTMLElement;
  copy.querySelectorAll("[aria-hidden]").forEach((n) => n.remove());
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

/** A `job.progress` event, as the server sends it while a letter is read. */
function progress(client: QueryClient, doc_id: string, status: JobProgressEvent["status"], error: string | null = null) {
  act(() =>
    handleServerEvent(client, {
      type: "job.progress",
      data: { job_id: `job_${doc_id}`, doc_id, stage: status === "done" ? "done" : "extract", progress: status === "done" ? 1 : 0.4, status, error },
    }),
  );
}

describe("Inbox", () => {
  it("shows the New-mail tray and the letters list with sender, kind, status and to-dos", async () => {
    const { container } = renderInbox();
    const tray = await screen.findByRole("region", { name: /New mail/ });
    expect(within(tray).getAllByRole("button", { name: "Let Ordnung read it" })).toHaveLength(5);
    expect(within(tray).getByText("Finanzamt Musterstadt")).toBeInTheDocument();
    expect(within(tray).getByRole("button", { name: "Read all 5" })).toBeInTheDocument();

    const parking = await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" });
    expect(parking).toHaveAttribute("href", "/documents/doc_parking");
    const row = parking.closest("li")!;
    expect(within(row).getAllByText("Please check").length).toBeGreaterThan(0);
    expect(within(row).getByRole("button", { name: /Ordnungsamt Musterstadt/ })).toBeInTheDocument();
    expect(within(row).getAllByText("1 to-do").length).toBeGreaterThan(0);
    assertNoRawEnumsInElement(container);
  });

  it("stamps each New-mail envelope with the day it arrived, and says it in words (R1-inbox-b-10)", async () => {
    renderInbox();
    const tray = await screen.findByRole("region", { name: /New mail/ });
    const card = within(tray).getByText("Stadtwerke Musterstadt").closest("li")!;
    expect(within(card).getByText("Arrived Mon 28 Sep")).toBeInTheDocument();
    expect(within(card).getByTestId("postmark-date")).toHaveTextContent("28SEP");
    // a letter without a known arrival day gets a postmark without a date, never today's
    const court = within(tray).getByText("Amtsgericht Hagen").closest("li")!;
    expect(within(court).queryByTestId("postmark-date")).toBeNull();
    expect(within(court).queryByText(/^Arrived/)).toBeNull();
  });

  it("links to the letters for taxes from its header while a letter is marked for taxes", async () => {
    renderInbox();
    const link = await screen.findByRole("link", { name: "Letters for taxes" });
    expect(link).toHaveAttribute("href", "/inbox/taxes");
  });

  it("has no link to the letters for taxes when none is marked", async () => {
    for (const d of srv.db.state.documents) d.tax_relevant = false;
    renderInbox();
    await screen.findByRole("link", { name: "Payslip August 2026" });
    expect(screen.queryByRole("link", { name: "Letters for taxes" })).toBeNull();
  });

  it("filters to the letters that need checking", async () => {
    renderInbox();
    await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: /Please check/ }));
    await waitFor(() => expect(screen.queryByRole("link", { name: "Library: overdue books" })).toBeNull());
    expect(screen.getByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
  });

  it("filters by kind from the URL and offers to clear filters when nothing matches", async () => {
    renderInbox("/inbox?kind=tax_assessment");
    expect(await screen.findByText("No letters here")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
  });

  it("takes the words from the top-bar search's 'See all letters matching …' (?q=) and keeps them in the URL", async () => {
    const { router } = renderInbox("/inbox?q=Parking");
    const field = await screen.findByRole("searchbox", { name: "Search letters" });
    expect(field).toHaveValue("Parking");
    expect(await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("link", { name: "Library: overdue books" })).toBeNull());
    // what the list shows, said (and announced) under the toolbar
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 letter matches “Parking”"));
    // typed words settle into the URL, so Back to the Inbox finds the search again
    const user = userEvent.setup();
    await user.clear(field);
    await user.type(field, "Library");
    await waitFor(() => expect(router.state.location.search).toBe("?q=Library"));
    expect(field).toHaveValue("Library");
    // another "See all letters matching …" while the Inbox is open takes over the field
    await act(() => router.navigate("/inbox?q=Parking"));
    await waitFor(() => expect(field).toHaveValue("Parking"));
  });

  it("asks for one more letter instead of ignoring a 1-character search", async () => {
    renderInbox();
    const field = await screen.findByRole("searchbox", { name: "Search letters" });
    await userEvent.setup().type(field, "P");
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Type one more letter to search."));
  });

  it("counts the tabs within the kind picked, and says how many of all letters show", async () => {
    renderInbox("/inbox?kind=dunning");
    await screen.findByRole("link", { name: "Library: overdue books" });
    expect(screen.getByRole("tab", { name: /^All/ })).toHaveTextContent(/^All2$/);
    // no "0" on phones' crowded tabs; "Please check" is the accessible name even where it shows "Check"
    expect(screen.getByRole("tab", { name: "Please check" })).not.toHaveTextContent("0");
    expect(screen.getByRole("status")).toHaveTextContent(/^Showing 2 of \d+ letters$/);
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });

  it("explains Private when it is empty, without a second 'drop letters' box under it", async () => {
    renderInbox("/inbox?filter=private");
    expect(await screen.findByRole("heading", { name: "No private letters" })).toBeInTheDocument();
    expect(screen.getByText(/“Keep private — no AI”.*Claude never reads them/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add letters" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Drop letters|phone photos/ })).toBeNull();
  });

  it("doesn't ask a touch screen to drop letters", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query === "(pointer: coarse)", media: query, addEventListener() {}, removeEventListener() {} }));
    renderInbox();
    expect(await screen.findByRole("button", { name: /^Add letters — PDFs, phone photos or saved e\u2011mails/ })).toBeInTheDocument();
    expect(screen.queryByText(/Drop letters anywhere/)).toBeNull();
  });

  it("offers to clear just the search when only the search found nothing", async () => {
    const { router } = renderInbox("/inbox?q=Quittung%201999");
    const heading = await screen.findByRole("heading", { name: "No letters match “Quittung 1999”" });
    await userEvent.setup().click(within(heading.parentElement!).getByRole("button", { name: "Clear search" }));
    expect(await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("says the letters couldn't be loaded (never 'No letters yet') and tries again", async () => {
    failing.add("GET /documents");
    renderInbox();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("heading", { name: "Couldn't load your letters" })).toBeInTheDocument();
    expect(screen.queryByText("No letters yet")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add letters" })).toBeNull();
    expect(screen.queryByRole("searchbox")).toBeNull();
    // the tray still works
    expect(await screen.findByRole("region", { name: /New mail/ })).toBeInTheDocument();
    failing.clear();
    await userEvent.setup().click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps a New-mail letter that couldn't be read actionable, names it in one alert and keeps focus on it", async () => {
    const { client } = renderInbox();
    const tray = await screen.findByRole("region", { name: /New mail, 5 letters/ });
    const card = within(tray).getByText("Finanzamt Musterstadt").closest("li")!;
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: "Let Ordnung read it" }));
    // the button is gone: its envelope holds focus
    const envelope = within(card).getByRole("group", { name: "Letter from Finanzamt Musterstadt" });
    expect(envelope).toHaveFocus();
    await waitFor(() => expect(srv.db.state.tray.find((t) => t.id === "mail_finanzamt")?.doc_id).toBeTruthy());
    const docId = srv.db.state.tray.find((t) => t.id === "mail_finanzamt")!.doc_id!;
    progress(client, docId, "running");
    progress(client, docId, "failed", "Claude couldn't read this photo — it is too blurry.");

    expect(await within(card).findByText("Claude couldn't read this photo — it is too blurry.")).toBeInTheDocument();
    // one announcement (the toast), not a second alert on the card
    expect(within(card).queryByRole("alert")).toBeNull();
    expect(within(card).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Add a sharper photo" })).toBeInTheDocument();
    const toastItem = (await screen.findByText("Couldn't read the letter from Finanzamt Musterstadt")).closest("li")!;
    await user.click(within(toastItem).getByRole("button", { name: "Show" }));
    expect(envelope).toHaveFocus();

    // taken out of New mail: focus moves to the next envelope, not to the page
    await user.click(within(card).getByRole("button", { name: "Remove from New mail" }));
    await waitFor(() => expect(card).not.toBeInTheDocument());
    expect(within(tray).getByRole("group", { name: "Letter from Stadtwerke Musterstadt" })).toHaveFocus();
    expect(within(tray).getByRole("heading", { name: /New mail, 4 letters/ })).toBeInTheDocument();
  });

  it("recaps a batch with the letters that couldn't be read, the tile's count matching Please check, then returns focus to the letters", async () => {
    const { client } = renderInbox();
    await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" });
    const ids = ["doc_parking", "doc_dentist", "doc_library"];
    ids.forEach((id) => progress(client, id, "running"));
    progress(client, "doc_parking", "done");
    progress(client, "doc_dentist", "done");
    progress(client, "doc_library", "failed", "Couldn't read this letter.");

    const dialog = await screen.findByRole("dialog", { name: "I read 2 of 3 letters" });
    const tile = await within(dialog).findByRole("link", { name: /needs you now/ });
    expect(tile).toHaveAttribute("href", "/inbox?filter=check");
    expect(tile).toHaveTextContent(/^1/); // the parking fine: the one letter Please check lists here
    const letters = within(dialog).getByRole("heading", { name: "The letters" }).nextElementSibling as HTMLElement;
    expect(within(letters).getAllByRole("link")).toHaveLength(3);
    expect(within(letters).getByRole("link", { name: /Parking fine/ })).toHaveTextContent("Please check");

    await userEvent.setup().click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toHaveAttribute("href", expect.stringMatching(/^\/documents\//));
  });

  describe("one year at a time", () => {
    it("?year=2025 lists only letters dated 2025 and Clear filters drops it", async () => {
      const { router } = renderInbox("/inbox?year=2025");
      expect(await screen.findByRole("link", { name: "Rental agreement — Beispielweg 5" })).toBeInTheDocument();
      expect(listedIds().sort()).toEqual(["doc_gym", "doc_job", "doc_lease", "doc_power"]);
      const select = screen.getByRole("combobox", { name: "Year, by the date on the letter" });
      expect(select).toHaveValue("2025");
      // every year with letters, newest first, by the date on the letter (else the day it arrived)
      expect(optionsOf(select)).toEqual(["All years", "2026 (15)", "2025 (4)", "2024 (2)", "2017 (1)"]);
      // every month with its year, this year's too; the groups stay by arrival
      expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
        expect.stringMatching(/^January 2026/),
        expect.stringMatching(/^September 2025/),
      ]);
      expect(screen.getByRole("status")).toHaveTextContent(/^Showing 4 of \d+ letters$/);
      // the tabs count within the year
      expect(screen.getByRole("tab", { name: /^All/ })).toHaveTextContent(/^All4$/);

      await userEvent.setup().click(screen.getByRole("button", { name: "Clear filters" }));
      await waitFor(() => expect(router.state.location.search).toBe(""));
      expect(await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
      expect(select).toHaveValue("");
    });

    it("chooses a year in the URL, keeps the search words, and ignores a year that can't be", async () => {
      const { router } = renderInbox("/inbox?year=20x5&q=Gym");
      await screen.findByRole("link", { name: "Gym price increase — FitWell" });
      const select = screen.getByRole("combobox", { name: "Year, by the date on the letter" });
      expect(select).toHaveValue("");
      await waitFor(() => expect(listedIds().sort()).toEqual(["doc_gym", "doc_gym_price"]));
      await userEvent.setup().selectOptions(select, "2025");
      await waitFor(() => expect(router.state.location.search).toBe("?year=2025&q=Gym"));
      expect(listedIds()).toEqual(["doc_gym"]);
      expect(screen.getByRole("searchbox", { name: "Search letters" })).toHaveValue("Gym");
    });

    it("keeps an asked year with no letters as a choice, and says why it is empty", async () => {
      renderInbox("/inbox?year=2019");
      expect(await screen.findByRole("heading", { name: "No letters dated 2019" })).toBeInTheDocument();
      expect(screen.getByText(/Ordnung files a letter under the year of the date on it, else the day it arrived/)).toBeInTheDocument();
      expect(optionsOf(screen.getByRole("combobox", { name: "Year, by the date on the letter" }))).toContain("2019 (0)");
      await userEvent.setup().click(screen.getByRole("button", { name: "Clear filters" }));
      expect(await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
    });

    it("a row that arrived in another year says “dated 2025”", async () => {
      renderInbox("/inbox?year=2025");
      // added on 12 Jan 2026, dated 2025: under January 2026, with its own year
      const job = (await screen.findByRole("link", { name: "Werkstudent employment contract" })).closest("li")!;
      const [stacked, table] = within(job).getAllByTitle(/^Added Mon 12 Jan/);
      // what a screen reader hears, in both layouts
      expect(spoken(stacked!)).toBe("Added 12 Jan, dated 2025");
      expect(spoken(table!)).toBe("Added 12 Jan, dated 2025");
      // on screen: after the date in stacked rows, on a line of its own in the table's date column
      expect(stacked!.querySelector("[aria-hidden]")).toHaveTextContent(/^· dated 2025$/);
      expect(table!.querySelector("[aria-hidden]")).toHaveTextContent(/^dated 2025$/);
      expect(table!.querySelector("[aria-hidden]")).toHaveClass("block");
      // a letter that arrived in 2025 says nothing more
      const lease = screen.getByRole("link", { name: "Rental agreement — Beispielweg 5" }).closest("li")!;
      expect(within(lease).queryByText(/dated 2025/)).toBeNull();
    });

    it("the Letters for taxes link keeps the chosen year", async () => {
      renderInbox("/inbox?year=2026");
      const link = await screen.findByRole("link", { name: "Letters for taxes" });
      expect(link).toHaveAttribute("href", "/inbox/taxes?year=2026");
      await userEvent.setup().selectOptions(screen.getByRole("combobox", { name: "Year, by the date on the letter" }), "");
      await waitFor(() => expect(link).toHaveAttribute("href", "/inbox/taxes"));
    });

    it("the Inbox and the Tax year page file the shared table's letters under the same years", async () => {
      // the letter list as the API answers it: no trash, no proof files
      const rows = (CASES.docs as Partial<DocumentRow>[])
        .map((fields) => makeRow({ doc_date: null, received_date: null, party_id: null, title: fields.id, ...fields }))
        .filter((d) => !d.deleted_at && d.source !== "proof");
      listed = rows;
      const user = userEvent.setup();
      renderInbox();
      await screen.findByRole("link", { name: "doc_payslip_2025" });
      const select = screen.getByRole("combobox", { name: "Year, by the date on the letter" });
      const years = optionsOf(select)
        .slice(1)
        .map((o) => Number(o!.slice(0, 4)));
      // every year of the Tax year page is a year of the Inbox
      for (const { year } of taxYears(rows)) expect(years).toContain(year);
      for (const year of years) {
        await user.selectOptions(select, String(year));
        await waitFor(() => expect(select).toHaveValue(String(year)));
        const shown = new Set(listedIds());
        const onTaxPage = taxLetters(rows, year).map((d) => d.id);
        // each letter of the year's tax page is in the Inbox's year…
        for (const id of onTaxPage) expect(shown, `${id} in ${year}`).toContain(id);
        // …and no letter for taxes of another year is
        const otherTax = years.filter((y) => y !== year).flatMap((y) => taxLetters(rows, y).map((d) => d.id));
        for (const id of otherTax) expect(shown, `${id} not in ${year}`).not.toContain(id);
        // an undated letter for taxes is in no year
        for (const d of undatedTaxLetters(rows)) expect(shown).not.toContain(d.id);
      }
    });
  });

  describe("whose letters (your household)", () => {
    it("has no For select while the household has no people", async () => {
      renderInbox("/inbox?for=me");
      await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" });
      expect(screen.queryByRole("combobox", { name: "Whose letters" })).toBeNull();
      // ?for= with nobody in the household reads as Everyone
      expect(listedIds()).toContain("doc_parking");
      expect(screen.getByRole("status").textContent).toBe("");
    });

    it("offers Everyone, You and each person with their letters, and narrows before the tabs count", async () => {
      withPeople();
      const { router } = renderInbox();
      const select = await screen.findByRole("combobox", { name: "Whose letters" });
      expect(optionsOf(select)).toEqual(["Everyone", "You", "Alex Rivera (1)", "Mia Rivera (0)"]);
      const user = userEvent.setup();
      await user.selectOptions(select, ALEX);
      await waitFor(() => expect(router.state.location.search).toBe(`?for=${ALEX}`));
      await waitFor(() => expect(listedIds()).toEqual(["doc_bkk"]));
      expect(screen.getByRole("tab", { name: /^All/ })).toHaveTextContent(/^All1$/);
      expect(screen.getByRole("status")).toHaveTextContent(/^Showing 1 of \d+ letters$/);

      await user.selectOptions(select, "me");
      await waitFor(() => expect(router.state.location.search).toBe("?for=me"));
      // You: every letter not filed for someone (the ones addressed to Alex too, until they are filed)
      await waitFor(() => expect(listedIds()).not.toContain("doc_bkk"));
      expect(listedIds()).toEqual(expect.arrayContaining(["doc_parking", "doc_dentist", "doc_library"]));

      await user.click(screen.getByRole("button", { name: "Clear filters" }));
      await waitFor(() => expect(router.state.location.search).toBe(""));
      expect(select).toHaveValue("");
    });

    it("reads an unknown person in ?for= as Everyone", async () => {
      withPeople();
      renderInbox("/inbox?for=hhm_gone00000000");
      const select = await screen.findByRole("combobox", { name: "Whose letters" });
      expect(select).toHaveValue("");
      await waitFor(() => expect(listedIds()).toEqual(expect.arrayContaining(["doc_bkk", "doc_parking"])));
    });

    it("tags a letter filed for someone in the Everyone view only", async () => {
      withPeople();
      renderInbox();
      const bkk = (await screen.findByRole("link", { name: "Health insurance contributions from 1 Oct" })).closest("li")!;
      await waitFor(() => expect(within(bkk).getAllByText("For Alex Rivera").length).toBeGreaterThan(0));
      // only the letters filed for someone: the person's own and unanswered ones have none
      const parking = screen.getByRole("link", { name: "Parking fine (Verwarnungsgeld)" }).closest("li")!;
      expect(within(parking).queryByText(/^For /)).toBeNull();
      const dentist = screen.getByRole("link", { name: "Dentist appointment reminder" }).closest("li")!;
      expect(within(dentist).queryByText(/^For /)).toBeNull();

      await userEvent.setup().selectOptions(screen.getByRole("combobox", { name: "Whose letters" }), ALEX);
      await waitFor(() => expect(listedIds()).toEqual(["doc_bkk"]));
      expect(within(lettersPanel()).queryByText("For Alex Rivera")).toBeNull();
    });

    it("files the letters addressed to someone with one press, exactly those listed, and Undo puts them back", async () => {
      withPeople();
      const user = userEvent.setup();
      renderInbox(`/inbox?for=${ALEX}`);
      const card = await screen.findByRole("region", { name: /Addressed to Alex Rivera, not filed yet/ });
      expect(within(card).getByText("Ordnung read Alex Rivera's name on these letters. They're in your own letters until you file them; their dates and reminders stay yours either way.")).toBeInTheDocument();
      expect(
        within(card)
          .getAllByRole("link")
          .map((a) => a.getAttribute("href")),
      ).toEqual(["/documents/doc_library", "/documents/doc_dentist"]);
      // not in Alex's letters until they are filed
      expect(listedIds()).toEqual(["doc_bkk"]);

      // a kind narrows the card too: the button files exactly what it lists
      await user.selectOptions(screen.getByRole("combobox", { name: "Kind of letter" }), "dunning");
      await waitFor(() => expect(within(card).getAllByRole("link")).toHaveLength(1));
      await user.click(within(card).getByRole("button", { name: "File it for Alex Rivera" }));
      await waitFor(() => expect(filings).toEqual([{ doc_library: ALEX }]));
      const toastItem = (await screen.findByText("Filed 1 letter for Alex Rivera")).closest("li")!;
      await waitFor(() => expect(listedIds()).toEqual(["doc_library"]));
      expect(screen.queryByRole("region", { name: /Addressed to Alex Rivera/ })).toBeNull();
      // focus goes to the letters, not the page
      await waitFor(() => expect(document.activeElement).toHaveAttribute("href", "/documents/doc_library"));

      await user.click(within(toastItem).getByRole("button", { name: "Undo" }));
      await waitFor(() => expect(filings).toEqual([{ doc_library: ALEX }, { doc_library: null }]));
      const back = await screen.findByRole("region", { name: /Addressed to Alex Rivera, not filed yet/ });
      expect(within(back).getByRole("button", { name: "File it for Alex Rivera" })).toBeInTheDocument();

      // without the kind: all of them
      await user.selectOptions(screen.getByRole("combobox", { name: "Kind of letter" }), "");
      await user.click(await within(back).findByRole("button", { name: "File these 2 for Alex Rivera" }));
      await waitFor(() => expect(filings.at(-1)).toEqual({ doc_library: ALEX, doc_dentist: ALEX }));
      expect(await screen.findByText("Filed 2 letters for Alex Rivera")).toBeInTheDocument();
    });

    it("says how to file a person's letters when none is filed yet, and that every letter is someone's", async () => {
      withPeople();
      renderInbox(`/inbox?for=${MIA}`);
      expect(await screen.findByRole("heading", { name: "No letters filed for Mia Rivera" })).toBeInTheDocument();
      expect(screen.getByText("Open a letter and press “Change” next to “For you” to file it for Mia Rivera.")).toBeInTheDocument();
      expect(screen.queryByRole("region", { name: /Addressed to/ })).toBeNull();
    });

    it("points up to the letters addressed to a person when none is filed for them yet", async () => {
      withPeople().links = {};
      renderInbox(`/inbox?for=${ALEX}`);
      expect(await screen.findByRole("heading", { name: "No letters filed for Alex Rivera" })).toBeInTheDocument();
      expect(screen.getByText("The letters above are addressed to Alex Rivera. File them with one press.")).toBeInTheDocument();
      expect(screen.getByRole("region", { name: /Addressed to Alex Rivera, not filed yet/ })).toBeInTheDocument();
    });
  });

  it("opens a tray letter and files it", async () => {
    renderInbox();
    const tray = await screen.findByRole("region", { name: /New mail/ });
    const user = userEvent.setup();
    const card = within(tray).getByText("Stadtwerke Musterstadt").closest("li")!;
    await user.click(within(card).getByRole("button", { name: "Let Ordnung read it" }));
    await waitFor(() => expect(srv.db.state.tray.find((t) => t.id === "mail_stadtwerke")?.opened).toBe(true));
    // the letter appears in the list right away (being read — titled from the tray, never the file name — or filed)
    expect(await screen.findByRole("link", { name: /— Stadtwerke Musterstadt|Electricity price increase from 1 Nov/ })).toHaveAttribute(
      "href",
      "/documents/doc_power_price",
    );
  });
});

describe("Inbox: possible scams", () => {
  const rowOf = (name: string | RegExp) => screen.getByRole("link", { name }).closest("li")!;
  /** The page loads lazily and every list is a request: room for a busy machine. */
  const SLOW = { timeout: 5_000 };

  it("tags only the scam letter, never the genuine bill its warning compares it with", async () => {
    // the fake "last reminder" from New mail, read
    srv.openAllMail();
    renderInbox();
    const fake = await screen.findByRole("link", { name: /Last reminder/ }, SLOW);
    await waitFor(() => expect(within(fake.closest("li")!).getAllByText("Possible scam").length).toBeGreaterThan(0), SLOW);
    expect(within(rowOf("Broadcasting fee due 15 Nov")).queryAllByText("Possible scam")).toHaveLength(0);
  });

  it("says when the scam warnings couldn't be checked, shows no countdown to pay until they are, and tries again", async () => {
    srv.openAllMail();
    failing.add("GET /suggestions");
    renderInbox();
    const line = await screen.findByText(/Scam warnings couldn't be checked/, undefined, SLOW);
    // unknown, so no letter counts down to a payment it may not owe (the parking fine is due tomorrow)
    expect(within(rowOf("Parking fine (Verwarnungsgeld)")).queryByText(/Pay the parking fine/)).toBeNull();
    expect(screen.queryAllByText("Possible scam")).toHaveLength(0);
    failing.clear();
    await userEvent.setup().click(within(line.closest("p")!).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByText(/Scam warnings couldn't be checked/)).toBeNull(), SLOW);
    expect(within(rowOf(/Last reminder/)).getAllByText("Possible scam").length).toBeGreaterThan(0);
    expect(within(rowOf("Parking fine (Verwarnungsgeld)")).getByText(/Pay the parking fine/)).toBeInTheDocument();
  });
});
