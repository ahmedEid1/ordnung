#!/usr/bin/env node
/**
 * A hash of everything the production build is made from (sources, styles, public files, the
 * lockfile and build config; tests excluded). `vite build` stores it in the build's
 * `build-info.json`, and CI checks the committed build against the sources:
 *
 *   node scripts/source-hash.mjs                                  # print the hash
 *   node scripts/source-hash.mjs --check ../src/ordnung/web/dist/build-info.json
 *   node scripts/source-hash.mjs --check                          # the same: that file is the default
 *
 * The built app is committed (src/ordnung/web/dist) so `pip install git+…` works without Node.
 */
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const WEB_DIR = resolve(fileURLToPath(new URL("..", import.meta.url)));
/** The committed build's `build-info.json` (what `--check` reads when no file is given). */
const COMMITTED_BUILD_INFO = join(WEB_DIR, "..", "src", "ordnung", "web", "dist", "build-info.json");

const ROOTS = ["src", "public", "index.html", "package-lock.json", "vite.config.ts", "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json"];
const EXCLUDED = [/\.test\.tsx?$/, /^src\/test\//];

function files(path) {
  const stat = statSync(path);
  if (stat.isFile()) return [path];
  return readdirSync(path).flatMap((name) => files(join(path, name)));
}

export function sourceHash(dir = WEB_DIR) {
  const hash = createHash("sha256");
  const all = ROOTS.flatMap((root) => files(join(dir, root)))
    .map((path) => relative(dir, path).split("\\").join("/"))
    .filter((path) => !EXCLUDED.some((re) => re.test(path)))
    .sort();
  for (const path of all) {
    hash.update(path);
    hash.update("\0");
    hash.update(readFileSync(join(dir, path)));
    hash.update("\0");
  }
  return hash.digest("hex");
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const current = sourceHash();
  const at = process.argv.indexOf("--check");
  if (at === -1) {
    console.log(current);
  } else {
    const file = process.argv[at + 1] ?? COMMITTED_BUILD_INFO;
    let built = null;
    try {
      built = JSON.parse(readFileSync(file, "utf8")).sourceHash;
    } catch {
      /* missing or unreadable: reported below */
    }
    if (built !== current) {
      console.error(
        `The committed web build (${file}) is out of date with web/: rebuild it with \`make build-web\` and commit src/ordnung/web/dist.`,
      );
      process.exit(1);
    }
    console.log("The committed web build matches the sources.");
  }
}
