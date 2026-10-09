/**
 * The web build's THIRD-PARTY-NOTICES.txt: every package whose code, styles or fonts the build
 * bundles, with its version, its licence and the licence text it ships with. The build strips licence
 * comments, and MIT, ISC and the fonts' SIL Open Font License all need their notice to travel with
 * copies; the file sits next to index.html, so the committed build and the wheel carry it.
 *
 * vite.config.ts adds the plugin. The packages come from the bundle itself:
 *   - the modules of each script chunk that come from node_modules;
 *   - the files behind each asset (the fonts' .woff2 files);
 *   - the packages the app's own stylesheets import by name (Tailwind and the fonts' CSS, which
 *     Tailwind inlines before Vite sees them as modules);
 *   - the helpers Vite and Rolldown add to the bundle (module preload, the chunk runtime).
 * CI's freshness check (scripts/source-hash.mjs --check) refuses a committed build without the file.
 */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

export const NOTICES_FILE = "THIRD-PARTY-NOTICES.txt";

const RULE = "-".repeat(80);
/** Code a build tool adds to the bundle, by the start of its virtual module id (each package is
 * looked up from Vite's folder, as Vite finds Rolldown). */
const HELPERS = [
  ["\0vite/", "vite"],
  ["\0rolldown/", "rolldown"],
];
const LICENCE_FILE = /^(licen[cs]e|copying)/i;
/** Vite's licence file goes on to list the licences of the packages bundled into its own Node code,
 * none of which reaches the app: the notices keep only Vite's own licence. */
const BUNDLED_DEPENDENCIES_HEADING = /^# Licenses of bundled dependencies/m;
const CSS_IMPORT = /@import\s+(?:url\(\s*)?["']([^"']+)["']/g;

function inNodeModules(path) {
  return path.split("\\").join("/").includes("/node_modules/");
}

/** The package a file in node_modules belongs to: the nearest folder above it whose package.json
 * has a name (some packages keep a nameless package.json in a sub-folder). */
export function packageDirOf(file) {
  let dir = dirname(file);
  while (inNodeModules(dir + "/")) {
    const manifest = join(dir, "package.json");
    if (existsSync(manifest) && JSON.parse(readFileSync(manifest, "utf8")).name) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

/** The folder of package `name` as Node finds it from `from` (node_modules folders upwards). */
export function findPackageDir(name, from) {
  let dir = resolve(from);
  for (;;) {
    const candidate = join(dir, "node_modules", ...name.split("/"));
    if (existsSync(join(candidate, "package.json"))) return candidate;
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

/** The package names a stylesheet imports by name (`@import "tailwindcss"`, `"@scope/name/file.css"`). */
export function cssPackageImports(css) {
  const names = new Set();
  for (const [, spec] of css.matchAll(CSS_IMPORT)) {
    if (/^[./]|^[a-z][a-z0-9+.-]*:/i.test(spec)) continue; // relative, absolute or a URL
    const parts = spec.split("/");
    names.add(spec.startsWith("@") ? parts.slice(0, 2).join("/") : parts[0]);
  }
  return [...names];
}

/** A package's name, version, licence and licence text, from its folder. */
export function readPackage(dir) {
  const manifest = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
  const file = readdirSync(dir).find((name) => LICENCE_FILE.test(name));
  let text = file ? readFileSync(join(dir, file), "utf8").replace(/\r\n?/g, "\n") : "";
  text = text.split(BUNDLED_DEPENDENCIES_HEADING)[0].trim();
  const licence = typeof manifest.license === "string" ? manifest.license.trim() : "";
  if (!text) {
    // no licence file: name who made it and where it comes from, as its package.json says
    const author = typeof manifest.author === "string" ? manifest.author : manifest.author?.name;
    const source = typeof manifest.repository === "string" ? manifest.repository : manifest.repository?.url;
    text = [
      "This package ships no licence file; its package.json names the licence above.",
      ...(author ? [`Author: ${author}`] : []),
      ...(source ? [`Source: ${source}`] : []),
    ].join("\n");
  }
  return { name: manifest.name, version: manifest.version ?? "0.0.0", licence, text };
}

/** `items` joined with ", " in lines of at most `width` characters, each line indented. */
function wrapped(items, indent, width = 100) {
  const lines = [];
  let line = "";
  for (const item of items) {
    const next = line ? `${line}, ${item}` : item;
    if (line && indent.length + next.length + 1 > width) {
      lines.push(`${indent}${line},`);
      line = item;
    } else {
      line = next;
    }
  }
  return [...lines, `${indent}${line}`];
}

/** The notices file's text for these packages (sorted, one section each). */
export function noticesText(packages) {
  const key = (pkg) => `${pkg.name}@${pkg.version}`;
  const sorted = [...packages].sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
  const byLicence = new Map();
  for (const pkg of sorted) {
    const licence = pkg.licence || "no licence named";
    byLicence.set(licence, [...(byLicence.get(licence) ?? []), pkg.name]);
  }
  const lines = [
    "Third-party notices: the Ordnung web app",
    "",
    "The Ordnung web app in this folder is built from Ordnung's own code, which is MIT licensed (see",
    "LICENSE), and from the packages below, whose code, styles and fonts are bundled into its files.",
    "Each is listed with its version and licence, followed by the licence text it ships with.",
    "",
    "The Python packages Ordnung runs on are not bundled here: pip installs each of them separately,",
    "with its own licence.",
    "",
    "Written by web/scripts/third-party-notices.mjs when the web app is built (make build-web).",
    "",
    "Licences:",
    ...[...byLicence]
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .flatMap(([licence, names]) => [`  ${licence}:`, ...wrapped(names, "    ")]),
    "",
  ];
  for (const pkg of sorted) {
    lines.push(RULE, `${pkg.name} ${pkg.version}`, `Licence: ${pkg.licence || "no licence named"}`, "");
    lines.push(pkg.text, "");
  }
  return lines.join("\n");
}

/** The Vite plugin: writes NOTICES_FILE into the build. */
export function thirdPartyNotices() {
  let root = process.cwd();
  /** Package folders found while the build ran (stylesheets' imports). */
  const fromStyles = new Set();
  return {
    name: "ordnung-third-party-notices",
    apply: "build",
    configResolved(config) {
      root = config.root;
    },
    transform(_code, id) {
      const file = id.split("?")[0];
      if (!file.endsWith(".css") || inNodeModules(file) || !existsSync(file)) return null;
      for (const name of cssPackageImports(readFileSync(file, "utf8"))) {
        const dir = findPackageDir(name, dirname(file));
        if (dir) fromStyles.add(dir);
        else this.warn(`${NOTICES_FILE}: ${file} imports ${name}, which isn't installed`);
      }
      return null;
    },
    generateBundle(_options, bundle) {
      const dirs = new Set(fromStyles);
      const toolDir = findPackageDir("vite", root) ?? root;
      for (const output of Object.values(bundle)) {
        const files =
          output.type === "chunk"
            ? output.moduleIds
            : (output.originalFileNames ?? []).map((name) => resolve(root, name));
        for (const id of files) {
          const helper = HELPERS.find(([prefix]) => id.startsWith(prefix));
          if (helper) {
            const dir = findPackageDir(helper[1], toolDir);
            if (dir) dirs.add(dir);
            continue;
          }
          if (id.startsWith("\0") || !inNodeModules(id)) continue;
          const dir = packageDirOf(id);
          if (dir) dirs.add(dir);
        }
      }
      const packages = new Map();
      for (const dir of dirs) {
        const pkg = readPackage(dir);
        packages.set(`${pkg.name}@${pkg.version}`, pkg);
        if (!pkg.licence) this.warn(`${NOTICES_FILE}: ${pkg.name}'s package.json names no licence`);
      }
      this.emitFile({ type: "asset", fileName: NOTICES_FILE, source: noticesText(packages.values()) });
    },
  };
}
