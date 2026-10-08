/**
 * The first-run wizard as a person walks it (UI audit round 1, onboarding): focus follows the
 * steps, the tab title names them, "Continue" stays reachable and explains itself, typed answers
 * survive, a failed finish shows next to its button, the online demo's finish screen points to
 * Sam's letters, and someone who is set up already has a way back into the app.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import type { ClaudeStatus, Health } from "@/api/types";
import { __clearToasts } from "@/components/ui/Toast";
import { useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { CopyCommand } from "./CopyCommand";
import { OnboardingWizard } from "./OnboardingWizard";
import { CLAUDE_INSTALL, CLAUDE_NPM_INSTALL } from "./options";
import { ProgressDots } from "./ProgressDots";
import { StepAddress, StepClaude } from "./Steps";
import { JOIN_LINK, JOIN_PATH, WIZARD_STEPS, initialDraft } from "./wizard";

const mode = vi.hoisted(() => ({ staticDemo: false }));
vi.mock("@/mocks/mode", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/mocks/mode")>()), isStaticDemo: () => mode.staticDemo }));

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", RO);
  vi.stubGlobal("scrollTo", () => {});
  mode.staticDemo = false;
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

/** A first run on the mock API (`useMockApi()` first): nothing set up yet, not the demo. */
function firstRun(api: ReturnType<typeof useMockApi>, health: Partial<Health> = {}) {
  api.srv.db.state.profile = { ...api.srv.db.state.profile, name: "", address: "", onboarded: false };
  api.srv.db.state.health = { ...api.srv.db.state.health, demo: false, ...health };
  const client = makeTestQueryClient();
  client.setQueryData(qk.health, { ...TEST_HEALTH, demo: false, ...health });
  const user = userEvent.setup();
  const view = renderWithProviders(<OnboardingWizard />, { route: "/welcome", client });
  return { ...api, ...view, user };
}

const h1 = (name: string) => screen.findByRole("heading", { level: 1, name });

describe("walking the wizard", () => {
  it("moves the focus to each new step's heading once it is on screen, and names the step in the tab title (R1-onboarding-1, -4)", async () => {
    const { user } = firstRun(useMockApi());
    await h1("Welcome to Ordnung");
    expect(document.title).toBe("Step 1 of 4: Welcome to Ordnung · Ordnung");

    await user.click(screen.getByRole("button", { name: "Get started" }));
    const region = await h1("Where do you live?");
    await waitFor(() => expect(region).toHaveFocus());
    expect(document.title).toBe("Step 2 of 4: Where do you live? · Ordnung");

    await user.click(screen.getByRole("radio", { name: /Bayern/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Your name and address" })).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Skip for now" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Is Claude ready?" })).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Your name and address" })).toHaveFocus());
  });

  it("keeps “Continue” reachable without a state: the hint describes it and it leads to the question (R1-onboarding-8)", async () => {
    const { user } = firstRun(useMockApi());
    await user.click(await screen.findByRole("button", { name: "Get started" }));
    await h1("Where do you live?");
    const cont = screen.getByRole("button", { name: "Continue" });
    expect(cont).not.toBeDisabled();
    expect(cont).toHaveAttribute("aria-disabled", "true");
    expect(cont).toHaveAccessibleDescription("Choose your state to continue.");
    const group = screen.getByRole("group", { name: "Your state (Bundesland)" });
    expect(group).toHaveAccessibleDescription("Decides the public holidays for payments you make. A letter's deadlines use its sender's state.");

    cont.focus();
    await user.keyboard("{Enter}");
    expect(within(group).getAllByRole("radio")[0]).toHaveFocus();
    expect(screen.getByRole("heading", { level: 1, name: "Where do you live?" })).toBeInTheDocument();

    // the choice shows by more than colour: a check mark on the chosen card and pill
    await user.click(within(group).getByRole("radio", { name: /Bayern/ }));
    const chosen = (name: RegExp) => screen.getByRole("radio", { name }).closest("label")!.querySelector(".lucide-check");
    expect(chosen(/Bayern/)).not.toBeNull();
    expect(chosen(/Berlin/)).toBeNull();
    expect(chosen(/^English$/)).not.toBeNull();
    expect(screen.getByRole("button", { name: "Continue" })).not.toHaveAttribute("aria-disabled");
    expect(screen.queryByText("Choose your state to continue.")).toBeNull();
  });

  it("offers “Skip for now” only while nothing is typed, and never throws typed answers away (R1-onboarding-7)", async () => {
    const { user, calls } = firstRun(useMockApi());
    await user.click(await screen.findByRole("button", { name: "Get started" }));
    await user.click(await screen.findByRole("radio", { name: /Berlin/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await h1("Your name and address");
    expect(screen.getByRole("button", { name: "Skip for now" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();

    await user.type(screen.getByRole("textbox", { name: /Your name/ }), "Sam Rivera");
    expect(screen.queryByRole("button", { name: "Skip for now" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await h1("Is Claude ready?");
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByRole("textbox", { name: /Your name/ })).toHaveValue("Sam Rivera");

    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Finish setup" }));
    await h1("You're all set, Sam");
    expect(calls.find((c) => c.method === "POST" && c.path === "/onboarding")?.body).toMatchObject({ profile: { region: "BE", name: "Sam Rivera" } });
  });

  it("shows a failed finish next to the button, not as a toast, and clears it on success (R1-onboarding-7)", async () => {
    const { user } = firstRun(useMockApi());
    const mocked = globalThis.fetch;
    let fail = true;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      if (fail && String(input).endsWith("/api/onboarding")) {
        fail = false;
        return new Response(JSON.stringify({ detail: "The data folder is read-only." }), { status: 500, headers: { "Content-Type": "application/json" } });
      }
      return mocked(input, init);
    });
    await user.click(await screen.findByRole("button", { name: "Get started" }));
    await user.click(await screen.findByRole("radio", { name: /Hamburg/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Skip for now" }));
    await user.click(await screen.findByRole("button", { name: "Finish setup" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't finish setting up");
    expect(alert).toHaveTextContent("The data folder is read-only. Your answers are still here — try again.");
    expect(screen.getAllByText("Couldn't finish setting up")).toHaveLength(1); // no toast as well

    await user.click(screen.getByRole("button", { name: "Finish setup" }));
    await h1("You're all set");
    expect(screen.queryByText("Couldn't finish setting up")).toBeNull();
  });
});

describe("the name & address step", () => {
  it("shows a four-line address whole and the letterhead line on up to two readable lines (R1-onboarding-5)", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<StepAddress draft={{ ...initialDraft(), name: "", address: "" }} onChange={() => {}} headingRef={() => {}} />);
    const address = screen.getByRole("textbox", { name: /Postal address/ });
    expect(address).toHaveAttribute("rows", "4");
    expect(address).toHaveClass("[field-sizing:content]");
    expect(address.className).not.toMatch(/\bmin-h-0\b/);
    const placeholder = screen.getByText("Your name · Street 1 · 12345 City");
    expect(placeholder).toHaveClass("text-muted", "text-[12px]");
    expect(placeholder).not.toHaveClass("text-faint");

    const line = "Alexandra Maria Rivera-Schneidermann · Hauptbahnhofsvorplatzstraße 123a · 12345 Musterstadt-Mitte · Deutschland";
    rerender(<StepAddress draft={{ ...initialDraft(), name: "Alexandra Maria Rivera-Schneidermann", address: "Hauptbahnhofsvorplatzstraße 123a\n12345 Musterstadt-Mitte\nDeutschland" }} onChange={() => {}} headingRef={() => {}} />);
    const preview = screen.getByText(line);
    expect(preview).toHaveClass("line-clamp-2");
    expect(preview).not.toHaveClass("truncate");
    expect(preview).toHaveAttribute("title", line);

    // leaving the field shows the address from its first line
    const field = screen.getByRole("textbox", { name: /Postal address/ });
    field.scrollTop = 40;
    await user.click(field);
    await user.tab();
    expect(field.scrollTop).toBe(0);
  });
});

describe("the Claude check", () => {
  const claude = (c: Partial<ClaudeStatus>): ClaudeStatus => ({
    installed: true,
    version: "2.1.4 (Claude Code)",
    path: "/usr/local/bin/claude",
    ok: true,
    detail: "Signed in with your Claude subscription.",
    needs_version: null,
    ...c,
  });
  const step = (props: Partial<Parameters<typeof StepClaude>[0]>) => (
    <StepClaude claude={undefined} view="missing" checking={false} onRecheck={() => {}} headingRef={() => {}} {...props} />
  );

  it("says what it found in its own words, with one name for the program (R1-onboarding-6)", () => {
    const { rerender } = render(step({ claude: claude({}), view: "ready" }));
    const status = () => screen.getByRole("status");
    expect(status()).toHaveTextContent("Claude is readySigned in and working.Claude Code 2.1.4");
    expect(screen.getByText(/the Claude program on this computer/)).toBeInTheDocument();

    rerender(step({ claude: claude({ ok: false, detail: "Claude Code is installed but not signed in. Run `claude` once and sign in." }), view: "signed_out" }));
    expect(status()).toHaveTextContent("Start it once in your terminal and sign in with your Claude account, then check again.");
    expect(status()).not.toHaveTextContent("`");

    rerender(step({ view: "checking" }));
    expect(status()).toHaveTextContent("Looking for Claude on this computer…");
    expect(screen.queryByText(/isn't installed/)).toBeNull();

    rerender(step({ view: "unknown" }));
    expect(status()).toHaveTextContent("Couldn't check for Claude");
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
    expect(screen.queryByText(/isn't installed/)).toBeNull();
  });

  it("answers “Check again” even when nothing changed (R1-onboarding-6)", async () => {
    const user = userEvent.setup();
    const onRecheck = vi.fn();
    const { rerender } = render(step({ onRecheck }));
    await user.click(screen.getByRole("button", { name: "Check again" }));
    expect(onRecheck).toHaveBeenCalledOnce();
    rerender(step({ onRecheck, checking: true }));
    expect(screen.getByRole("status")).toHaveTextContent("Checking again…");
    rerender(step({ onRecheck, checking: false }));
    expect(screen.getByRole("status")).toHaveTextContent("Checked just now — still not found on this computer.");
  });

  it("not installed: Anthropic's installer for this computer's system, the other ways, and the plan it needs", async () => {
    const user = userEvent.setup();
    render(step({ view: "missing" }));
    expect(screen.getByRole("status")).toHaveTextContent("Claude isn't installed yet");
    // jsdom says Linux: its installer first, and the system can be switched
    expect(screen.getByRole("tab", { name: "Linux", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Copy command to install Claude Code: ${CLAUDE_INSTALL.linux.command}` })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Windows" }));
    expect(screen.getByText(CLAUDE_INSTALL.windows.command)).toBeInTheDocument();
    expect(screen.getByText("winget install Anthropic.ClaudeCode")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Mac" }));
    expect(screen.getByText(CLAUDE_INSTALL.mac.command)).toBeInTheDocument();
    expect(screen.getByText("brew install --cask claude-code")).toBeInTheDocument();
    // npm only as the last way, with what it needs
    expect(screen.getByText(/Node\.js 22 or newer/)).toBeInTheDocument();
    expect(screen.getByText(CLAUDE_NPM_INSTALL)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Node\.js 18/);
    expect(document.body).toHaveTextContent("Claude Code needs a paid Claude plan (Pro, Max, Team or Enterprise) or an Anthropic Console account");
    expect(document.body).toHaveTextContent("the free plan doesn't include it");
    expect(document.body).toHaveTextContent("Without Claude you can still store letters privately, search them and add your own dates");
  });

  it("too old: names the version Ordnung needs and the update command, never a sign-in", () => {
    render(step({ claude: claude({ ok: false, version: "2.0.9 (Claude Code)", needs_version: "2.1.0" }), view: "outdated" }));
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Claude Code needs an update");
    expect(status).toHaveTextContent("Claude Code 2.0.9 — Ordnung needs 2.1.0 or newer");
    expect(screen.getByRole("button", { name: "Copy command to update Claude Code: claude update" })).toBeInTheDocument();
    expect(screen.getByText("brew upgrade claude-code")).toBeInTheDocument();
    expect(screen.getByText("winget upgrade Anthropic.ClaudeCode")).toBeInTheDocument();
    expect(screen.queryByText(/sign in/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("shows the installer command whole, wrapping only inside its address (R1-onboarding-3)", () => {
    const command = CLAUDE_INSTALL.mac.command;
    render(<CopyCommand command={command} label="install Claude Code" />);
    const code = screen.getByText(command);
    expect(code).toHaveClass("whitespace-normal", "[overflow-wrap:anywhere]");
    expect(code).not.toHaveClass("overflow-x-auto");
    // never between the two slashes of "https://"
    expect(code.innerHTML).toBe("curl -fsSL https://<wbr>claude.ai/<wbr>install.sh | bash");
    expect(screen.getByRole("button", { name: `Copy command to install Claude Code: ${command}` })).toBeInTheDocument();
  });

  it("shows a long npm command whole, wrapping after the package scope (R1-onboarding-3)", () => {
    render(<CopyCommand command={CLAUDE_NPM_INSTALL} label="install Claude Code with npm" />);
    expect(screen.getByText(CLAUDE_NPM_INSTALL).innerHTML).toBe("npm install -g @anthropic-ai/<wbr>claude-code");
  });

  it("never breaks a path right after its root slash (no lone “/” at a line's end)", () => {
    const command = "ordnung autostart enable --data-dir /home/sam/Ordnung";
    render(<CopyCommand command={command} label="start Ordnung when you log in" />);
    // … and a long option ("--data-dir") never breaks after its dashes
    const code = document.querySelector("code")!;
    expect(code.textContent).toBe(command);
    expect(code.innerHTML).toBe('ordnung autostart enable <span class="whitespace-nowrap">--data-dir</span> /home/<wbr>sam/<wbr>Ordnung');
  });
});

describe("the finish screen", () => {
  async function finishSetup(api: ReturnType<typeof useMockApi>, opts: { staticDemo?: boolean } = {}) {
    mode.staticDemo = Boolean(opts.staticDemo);
    const ctx = firstRun(api);
    await ctx.user.click(await screen.findByRole("button", { name: "Get started" }));
    await ctx.user.click(await screen.findByRole("radio", { name: /Bremen/ }));
    await ctx.user.click(screen.getByRole("button", { name: "Continue" }));
    await ctx.user.click(await screen.findByRole("button", { name: "Skip for now" }));
    await ctx.user.click(await screen.findByRole("button", { name: "Finish setup" }));
    await h1("You're all set");
    return ctx;
  }

  it("leaves setup for Today without keeping the wizard in the history (R1-onboarding-4, -9)", async () => {
    const { user, router } = await finishSetup(useMockApi());
    expect(document.title).toBe("Setup complete · Ordnung");
    expect(screen.getByText("Setup complete")).toBeInTheDocument(); // not "All set" above "You're all set"
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: /Drop your letters here/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explore the demo instead" })).toBeInTheDocument();

    const today = screen.getByRole("link", { name: "Go to Today" });
    expect(today.className).not.toMatch(/underline/); // a button, not a small text link
    await user.click(today);
    expect(router.state.location.pathname).toBe("/");
    expect(router.state.historyAction).toBe("REPLACE");
  });

  it("points to Sam's letters in the online demo, which can't keep files (R1-onboarding-9)", async () => {
    await finishSetup(useMockApi(), { staticDemo: true });
    expect(screen.getByRole("heading", { level: 2, name: "Sam's letters are waiting" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open New mail" })).toHaveAttribute("href", "/inbox");
    expect(screen.queryByRole("button", { name: "Choose files" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Explore the demo instead" })).toBeNull();
  });
});

describe("someone who is set up already", () => {
  it("sees “Change your setup” with a way back into the app, which leaves the wizard out of the history (R1-onboarding-4)", async () => {
    const api = useMockApi();
    const user = userEvent.setup();
    const { router } = renderWithProviders(<OnboardingWizard />, { route: "/welcome" });
    await h1("Change your setup");
    expect(document.title).toBe("Step 1 of 4: Change your setup · Ordnung");
    expect(api.srv.db.state.profile.onboarded).toBe(true);
    const links = screen.getAllByRole("link", { name: "Back to Ordnung" });
    expect(links).toHaveLength(2); // the logo and the footer
    await user.click(links[1]!);
    expect(router.state.location.pathname).toBe("/");
    expect(router.state.historyAction).toBe("REPLACE");
    // joining another computer's Ordnung is for a first run (set up already: Settings → Your computers)
    expect(screen.queryByRole("link", { name: JOIN_LINK })).toBeNull();
  });
});

describe("someone who uses Ordnung on another computer already (hand-off sync)", () => {
  it("finds “I already use Ordnung on another computer” on the first step, leading to /join", async () => {
    const { user, router } = firstRun(useMockApi());
    await h1("Welcome to Ordnung");
    const join = screen.getByRole("link", { name: JOIN_LINK });
    expect(join).toHaveAttribute("href", JOIN_PATH);
    await user.click(join);
    expect(router.state.location.pathname).toBe("/join");
    // only the first step offers it
    await act(() => router.navigate("/welcome"));
    await user.click(await screen.findByRole("button", { name: "Get started" }));
    await h1("Where do you live?");
    expect(screen.queryByRole("link", { name: JOIN_LINK })).toBeNull();
  });
});

describe("progress", () => {
  it("ends in a “Done” pill instead of a stray check after the dots (R1-onboarding-9)", () => {
    const { rerender } = render(<ProgressDots steps={WIZARD_STEPS} current={1} />);
    expect(screen.getByRole("list", { name: "Setup, step 2 of 4" })).toBeInTheDocument();
    rerender(<ProgressDots steps={WIZARD_STEPS} current={WIZARD_STEPS.length} />);
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.getByText("Setup: all 4 steps done")).toBeInTheDocument();
  });
});
