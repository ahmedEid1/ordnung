/**
 * The phone's pairing page and the first-run wizard send their answer once per press: a double tap on "Pair this
 * phone" sent the code twice before the first answer set the phone's cookie (the computer took the second for
 * someone else using the code), and "Finish setup" pressed twice sent the setup twice. A failed one takes the next
 * press.
 */
import { afterEach, describe, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import { routes } from "@/app/router";
import { stubShellGlobals } from "@/test/app";
import { __clearToasts } from "@/components/ui/Toast";
import { OnboardingWizard } from "@/features/onboarding/OnboardingWizard";
import { expectOnePressAtATime } from "@/test/busyButton";
import { holdRequests, useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";

afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

describe("pairing a phone", () => {
  it("“Pair this phone” takes one press at a time, and the next once it failed", async () => {
    stubShellGlobals();
    const api = useMockApi({ client: "phone", paired: false });
    const { code } = api.srv.phone.startPairing();
    const held = holdRequests((c) => c.method === "POST" && c.path === "/phone/pair");
    const client = makeTestQueryClient({ client: "computer" });
    client.removeQueries();
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={createMemoryRouter(routes, { initialEntries: [`/pair#${code}`] })} />
      </QueryClientProvider>,
    );
    await screen.findByRole("button", { name: "Pair this phone" });
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => screen.getByRole("button", { name: "Pair this phone" }), held });
  });
});

describe("the first-run wizard", () => {
  it("“Finish setup” takes one press at a time, and the next once it failed", async () => {
    const api = useMockApi();
    api.srv.db.state.profile = { ...api.srv.db.state.profile, name: "", address: "", onboarded: false };
    api.srv.db.state.health = { ...api.srv.db.state.health, demo: false };
    const client = makeTestQueryClient();
    client.setQueryData(qk.health, { ...TEST_HEALTH, demo: false });
    const held = holdRequests((c) => c.method === "POST" && c.path === "/onboarding");
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />, { route: "/welcome", client });
    await user.click(await screen.findByRole("button", { name: "Get started" }));
    await user.click(await screen.findByRole("radio", { name: /Bayern/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Skip for now" }));
    await screen.findByRole("heading", { level: 1, name: "Is Claude ready?" });
    // "Finish setup" once Claude is ready, else "Continue without AI": the same press
    const finish = () => screen.getByRole("button", { name: /^(Finish setup|Continue without AI)$/ });
    await expectOnePressAtATime({ user, button: finish, held });
  });
});
