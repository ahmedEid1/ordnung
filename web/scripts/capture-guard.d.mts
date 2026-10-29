/**
 * Types for `capture-guard.mjs`, so the README pictures of the real app (e2e/readme-pictures.spec.ts, TypeScript) are
 * checked for what the demo's pictures are.
 */

/** A word no picture may show, with what it is (for the message, which never repeats the word). */
export interface ForbiddenWord {
  text: string;
  what: string;
}

/** What no picture may show: this computer's paths and name, the git e-mail, the author's name, CAPTURE_FORBIDDEN. */
export function forbiddenWords(repo: string, folders?: [path: string, what: string][]): ForbiddenWord[];

/** The first folder of the home folder, the temporary folder and every path in `paths` ("/home/", "/tmp/"). */
export function pathRoots(paths?: string[]): string[];

/** What of `forbidden` and `roots` `text` shows: what each is, never the word. */
export function leaks(text: string, forbidden: ForbiddenWord[], roots: string[]): string[];
