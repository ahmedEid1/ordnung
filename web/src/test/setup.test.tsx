/**
 * What `src/test/setup.ts` sets for every test file: `findBy*` and `waitFor` wait 5 s, not Testing Library's
 * 1 s. On a busy machine a page can take longer than 1 s to show what a test looks for, while the test itself
 * may take 20 s (`vite.config.ts`).
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { getConfig } from "@testing-library/react";

describe("the tests' setup", () => {
  it("lets findBy* and waitFor wait 5 s", () => {
    expect(getConfig().asyncUtilTimeout).toBe(5_000);
  });

  it("is not cut short by a test: no call waits less than 5 s", () => {
    const src = resolve(__dirname, "..");
    const shorter: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) walk(path);
        else if (/\.test\.tsx?$/.test(entry.name)) {
          for (const match of readFileSync(path, "utf8").matchAll(/\{\s*timeout:\s*([\d_]+)\s*\}/g)) {
            if (Number(match[1]!.replaceAll("_", "")) < 5_000) shorter.push(`${relative(src, path)}: ${match[0]}`);
          }
        }
      }
    };
    walk(src);
    expect(shorter).toEqual([]);
  });
});
