// @vitest-environment node
/**
 * `npm run lint` checks the `.mjs` scripts in `scripts/` too (the UI audit, the README pictures, the build's source
 * hash and notices), with the app's rule for unused names. They run in Node and hand functions to the browser, so
 * both sets of globals are known.
 */
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

async function lintScript(code: string) {
  const [result] = await new ESLint().lintText(code, { filePath: "scripts/ui-audit/example.mjs" });
  return result!.messages.map((m) => `${m.ruleId}: ${m.message}`);
}

describe("linting the scripts", () => {
  it("reports a name that is never used, as in the app", async () => {
    expect(await lintScript("const unused = 1;\nexport const used = 2;\n")).toEqual([
      "no-unused-vars: 'unused' is assigned a value but never used. Allowed unused vars must match /^_/u.",
    ]);
    expect(await lintScript("export function onRequest(_route, request) {\n  return request;\n}\n")).toEqual([]);
  });

  it("reports a name that is not defined, and knows Node's and the browser's", async () => {
    expect(await lintScript("export const where = [process.cwd(), document.title, nowhere];\n")).toEqual([
      "no-undef: 'nowhere' is not defined.",
    ]);
  });
});
