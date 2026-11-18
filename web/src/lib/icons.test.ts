/// <reference types="node" />
/**
 * Every lucide-react icon the app imports is one the library still supports: an icon its type
 * declarations mark `@deprecated` is due to go in a later version, and the app would stop building.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(__dirname, "..");
const DECLARATIONS = resolve(__dirname, "../../node_modules/lucide-react/dist/lucide-react.d.ts");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

/** The names imported from lucide-react, with the files that import each. */
function importedIcons(): Map<string, string[]> {
  const icons = new Map<string, string[]>();
  for (const file of sourceFiles(SRC)) {
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(/import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*["']lucide-react["']/g)) {
      for (const part of match[1].split(",")) {
        const name = part.trim().replace(/^type\s+/, "").split(/\s+as\s+/)[0].trim();
        if (name) icons.set(name, [...(icons.get(name) ?? []), file.slice(SRC.length + 1)]);
      }
    }
  }
  return icons;
}

/** The icons whose declaration carries a JSDoc `@deprecated`. */
function deprecatedIcons(declarations: string): Set<string> {
  const names = new Set<string>();
  for (const match of declarations.matchAll(/\/\*\*((?:(?!\*\/)[\s\S])*)\*\/\s*declare const (\w+)/g)) {
    if (match[1].includes("@deprecated")) names.add(match[2]);
  }
  return names;
}

describe("lucide-react icons", () => {
  it("the app imports none that the library marks deprecated", () => {
    const declarations = readFileSync(DECLARATIONS, "utf8");
    const deprecated = deprecatedIcons(declarations);
    // the reading of the declarations works: it finds each deprecated icon the file names
    expect(deprecated.size > 0 || !/@deprecated[\s\S]*?\*\/\s*declare const/.test(declarations)).toBe(true);
    const icons = importedIcons();
    expect(icons.size, "the app's icon imports are found").toBeGreaterThan(100);
    const used = [...icons].filter(([name]) => deprecated.has(name)).map(([name, files]) => `${name} (${files.join(", ")})`);
    expect(used, "deprecated lucide-react icons in use").toEqual([]);
  });
});
