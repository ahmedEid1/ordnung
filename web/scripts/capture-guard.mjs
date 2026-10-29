/**
 * What README's pictures may never show, for every picture `make capture` makes: the demo's (scripts/capture.mjs,
 * which looks at every page it opens) and the real app's two (e2e/readme-pictures.spec.ts, which looks at the text
 * of every part it puts in a picture). Found when the capture runs; none of it is written into the repo.
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { homedir, hostname, tmpdir } from "node:os";
import { join } from "node:path";

/**
 * What no picture may show: the home folder, the checkout (`repo`), the run's own `folders` (`[path, what it is]`,
 * e.g. the demo's data folder and where the pictures go), the computer's name, the git e-mail address, each word of
 * the author's name in pyproject.toml (three letters or more), and CAPTURE_FORBIDDEN's words (comma-separated, each
 * however short: a surname of two letters, initials). Each comes with what it is, for the message, which never
 * repeats it.
 */
export function forbiddenWords(repo, folders = []) {
  const found = [];
  // `shortest`: a word of the author's name under three letters would match too much ("Jo"); a word you name is
  // looked for however short
  const add = (text, what, shortest = 3) => {
    const word = (text ?? "").trim();
    if (word.length < shortest || word === "/" || found.some((f) => f.text.toLowerCase() === word.toLowerCase())) return;
    found.push({ text: word, what });
  };
  add(homedir(), "the home folder");
  add(repo, "the checkout's folder");
  for (const [path, what] of folders) add(path, what);
  const host = hostname();
  if (host.length >= 4 && host.toLowerCase() !== "localhost") add(host, "this computer's name");
  try {
    const email = execFileSync("git", ["config", "user.email"], { cwd: repo, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
    add(email, "the git e-mail address");
  } catch {
    // no e-mail set
  }
  const authors = readFileSync(join(repo, "pyproject.toml"), "utf8").match(/^authors\s*=\s*\[(.*?)\]$/ms)?.[1] ?? "";
  for (const [, name] of authors.matchAll(/\bname\s*=\s*"([^"]*)"/g)) {
    for (const word of name.split(/[^\p{L}]+/u)) add(word, "a word of the author's name");
  }
  for (const word of (process.env.CAPTURE_FORBIDDEN ?? "").split(",")) add(word, "a word of CAPTURE_FORBIDDEN", 1);
  return found;
}

/**
 * The first folder of the home folder, the temporary folder and every path in `paths` ("/home/", "/tmp/",
 * "C:\Users\"). A path on screen is often drawn in pieces (a command wraps at each "/") and cut off by the window's
 * edge, so the whole path is never there to find; its start is.
 */
export function pathRoots(paths = []) {
  const roots = new Set();
  for (const path of [homedir(), ...paths, tmpdir()]) {
    const root = `${path}/`.match(/^(?:[A-Za-z]:)?[\\/][^\\/]+[\\/]/)?.[0];
    if (root) roots.add(root);
  }
  return [...roots];
}

/**
 * A forbidden word anywhere in a text but inside a longer word or number, in any case (capture.mjs's `guardPage`
 * builds the same pattern in the page).
 */
function wordPattern(text) {
  return new RegExp(`(?<![\\p{L}\\p{N}])${text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\p{L}\\p{N}])`, "iu");
}

/** What of `forbidden` (`forbiddenWords`) and `roots` (`pathRoots`) `text` shows: what each is, never the word. */
export function leaks(text, forbidden, roots) {
  const found = forbidden.filter(({ text: word }) => wordPattern(word).test(text)).map(({ what }) => what);
  if (roots.some((root) => text.includes(root))) found.push("the start of a path of this computer");
  return [...new Set(found)];
}
