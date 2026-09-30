/**
 * Settings → Claude connection → Model (mock API): the field shows the model every call runs on,
 * Sonnet 5 by default; an edit is unsaved until Save (trimmed) or Discard; a name the server refuses
 * is shown under the field, focused, and nothing is saved; while ORDNUNG_CLAUDE_MODEL pins a model
 * (health.model_pinned) the card says so, and a save says the saved model waits.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import { __clearToasts } from "@/components/ui/Toast";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import SettingsPage from "@/pages/SettingsPage";
import { DEFAULT_MODEL } from "./ClaudeSection";

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
  act(() => __clearToasts());
});

const renderClaude = () => renderWithProviders(<SettingsPage />, { route: "/settings?section=claude" });

describe("Settings → Claude → Model", () => {
  it("shows the model every call runs on — Sonnet 5 by default — and what else it may be", async () => {
    useMockApi();
    renderClaude();
    const field = await screen.findByRole("textbox", { name: "Model" });
    expect(DEFAULT_MODEL).toBe("claude-sonnet-5");
    expect(field).toHaveValue("claude-sonnet-5");
    expect(field).toHaveAttribute("placeholder", DEFAULT_MODEL);
    expect(field).toHaveAccessibleDescription("Sonnet 5 by default: claude-sonnet-5. Any model id or alias Claude Code accepts, for example claude-opus-5-5, sonnet or sonnet[1m].");
    expect(screen.getByText("The demo and the benchmarks keep the model they were recorded with.")).toBeInTheDocument();
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    expect(screen.queryByText(/Pinned to/)).toBeNull();
  });

  it("names the model ORDNUNG_CLAUDE_MODEL pins, and a save then says the saved model waits", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    const client = makeTestQueryClient(); // health is pre-seeded, so the pin goes into the seed
    client.setQueryData(qk.health, { ...TEST_HEALTH, model_pinned: "claude-sonnet-5" });
    renderWithProviders(<SettingsPage />, { route: "/settings?section=claude", client });
    const field = await screen.findByRole("textbox", { name: "Model" });
    expect(screen.getByText(/^Pinned to/)).toHaveTextContent(
      "Pinned to claude-sonnet-5 by ORDNUNG_CLAUDE_MODEL while Ordnung runs: every call uses it, and the model saved here counts once the variable is unset.",
    );
    await user.clear(field);
    await user.type(field, "claude-opus-5-5");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/claude-opus-5-5 counts once ORDNUNG_CLAUDE_MODEL is unset — until then every call runs on claude-sonnet-5\./)).toBeInTheDocument();
    expect(screen.queryByText(/from now on\./)).toBeNull();
    expect(srv.db.state.settings.model).toBe("claude-opus-5-5");
  });

  it("an edit is unsaved until Save, and Discard puts the saved model back", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderClaude();
    const field = await screen.findByRole("textbox", { name: "Model" });
    await user.clear(field);
    await user.type(field, "claude-opus-5-5");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(field).toHaveValue("claude-sonnet-5");
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    expect(calls.find((c) => c.method === "PUT" && c.path === "/settings")).toBeUndefined();
  });

  it("saves the model trimmed and says every call runs on it from now on", async () => {
    const { srv, calls } = useMockApi();
    const user = userEvent.setup();
    renderClaude();
    const field = await screen.findByRole("textbox", { name: "Model" });
    await user.clear(field);
    await user.type(field, "  claude-opus-5-5 ");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Every call to Claude runs on claude-opus-5-5 from now on\./)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT" && c.path === "/settings")?.body).toEqual({ model: "claude-opus-5-5" });
    expect(srv.db.state.settings.model).toBe("claude-opus-5-5");
    expect(field).toHaveValue("claude-opus-5-5");
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });

  it("a name Claude Code can't take is refused under the field, focused, and nothing is saved", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    renderClaude();
    const field = await screen.findByRole("textbox", { name: "Model" });
    await user.clear(field);
    await user.type(field, "claude opus 5 5");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
    expect(field).toHaveAccessibleDescription("A model name has no spaces and doesn't start with a dash — like claude-sonnet-5 or sonnet[1m].");
    await waitFor(() => expect(field).toHaveFocus());
    expect(screen.getByText("Fix the highlighted field to save")).toBeInTheDocument();
    expect(srv.db.state.settings.model).toBe("claude-sonnet-5");
    // typing again clears the reason; an empty name is refused too
    await user.clear(field);
    expect(field).not.toHaveAttribute("aria-invalid");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(field).toHaveAccessibleDescription("Enter a model id or alias, like claude-sonnet-5 or sonnet."));
    expect(srv.db.state.settings.model).toBe("claude-sonnet-5");
    // what Claude Code takes is taken: a 1M-context alias, a Bedrock id, a Vertex id
    for (const accepted of ["sonnet[1m]", "us.anthropic.claude-sonnet-4-5-20250929-v1:0", "claude-sonnet-4-5@20250929"]) {
      await user.clear(field);
      await user.type(field, accepted.replace("[", "[[")); // "[[" types a "[" (user-event reads [Key] as a key)
      await user.click(screen.getByRole("button", { name: "Save changes" }));
      await waitFor(() => expect(srv.db.state.settings.model).toBe(accepted));
      expect(field).not.toHaveAttribute("aria-invalid");
    }
  });
});
