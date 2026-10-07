import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { setClientKind } from "@/api/clientKind";

// a test in phone mode (`useMockApi({ client: "phone" })`) leaves the next one on the computer
afterEach(() => setClientKind("computer"));
