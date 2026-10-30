import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";
import { afterEach } from "vitest";
import { setClientKind } from "@/api/clientKind";

// findBy* and waitFor wait 5 s, not Testing Library's 1 s: a busy machine can take longer than that to show a
// page, and each test may take 20 s (vite.config.ts)
configure({ asyncUtilTimeout: 5_000 });

// a test in phone mode (`useMockApi({ client: "phone" })`) leaves the next one on the computer
afterEach(() => setClientKind("computer"));
