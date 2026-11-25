#!/usr/bin/env node
/**
 * Screenshots for the README and the guide, the demo video and GIF, captured from a running demo (`make capture`).
 *
 *   ordnung demo --serve --no-browser --reset --port 8797 --data-dir /tmp/ordnung-capture
 *   node web/scripts/capture.mjs --only shots --data /tmp/ordnung-capture --port 8797 --out docs/assets
 *   (then a second fresh demo for `--only video`)
 *
 * The pictures (`--only shots`) and the video (`--only video`) each start from a fresh demo of their own (--reset,
 * a data folder each: `make capture` starts both): both read letters from the New-mail tray and send the phone
 * contract's cancellation, and Ask's recorded answers replay only against the ledger they were recorded from, so
 * what one of them does would show in the other. A change of the tour never changes a picture.
 *
 * `ordnung demo`'s recorded letters include no court letter, so the court payment order comes from the
 * app's mock mode (`?mock=full`, the static web demo's data): the same app on hand-written sample
 * letters whose dates, receipts and advice card come from the rules engine
 * (scripts/gen_mock_high_stakes.py, scripts/gen_mock_advice.py). `?mock=0` returns to the demo.
 *
 * Every picture and the video are drawn at CAPTURE_SCALE device pixels to the CSS pixel (2: a 1440×900 window gives
 * a 2880×1800 picture), so their text is sharp on high-density screens. The video, in a window of its own (VIDEO), is the page's own frames
 * (`page.screencast`, JPEG at CAPTURE_FRAME_QUALITY), each with the moment it was drawn: it writes them to
 * `<out>/video` with `frames.txt` (each frame and how long it stays on screen, on the video's clock: see `film`) and
 * `cut` (the second where README's loop ends); `make capture` turns them into `demo.mp4` (the whole tour, LOOP and
 * TOUR), and `demo.webp` and `demo.gif` (README's loop, LOOP).
 * Set PW_CHROMIUM_PATH to use a Chromium that is already installed.
 *
 * Every page it opens is guarded (`guardPage`): the theme the picture is in, and nothing that would tell a reader
 * about the computer that made it — a path, its name, the git e-mail, the author's name (`forbiddenWords` in
 * capture-guard.mjs, found when it runs; none is written here). A page that shows one stops the capture
 * (`assertClean`). A failed run's screenshot goes to CAPTURE_REVIEW (`make capture`'s review folder), never to
 * `<out>`; the video records into a temporary folder until the tour has run clean, so a stopped tour's recording
 * never reaches `<out>` either.
 */
import { cpSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { chromium } from "@playwright/test";
import { forbiddenWords, pathRoots } from "./capture-guard.mjs";
import { shownAs } from "./ui-audit/steps.mjs";

const { values: opts } = parseArgs({
  options: {
    data: { type: "string", default: "/tmp/ordnung-capture" },
    port: { type: "string", default: "8797" },
    out: { type: "string", default: "docs/assets" },
    only: { type: "string" }, // "video" or "shots": each on a fresh demo of its own
  },
});
if (opts.only !== "shots" && opts.only !== "video") {
  throw new Error('--only shots or --only video: the pictures and the video each need a fresh demo of their own (scripts/capture.sh starts both)');
}

const BASE = `http://127.0.0.1:${opts.port}`;
const OUT = resolve(opts.out);
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
/** Where a failed run's screenshot goes: it may show what the guard found, so never into `<out>`. */
const REVIEW = resolve(process.env.CAPTURE_REVIEW || join(tmpdir(), "ordnung-capture-review"));
const TOKEN = JSON.parse(readFileSync(join(opts.data, "server.json"), "utf8")).token;
const CLIENT = { "X-Ordnung-Client": "web" };
const FINANZAMT = "Finanzamt Musterstadt";
const PHONE_QUESTION = "When does my phone contract end, and by when do I have to cancel it?";
const MONEY_QUESTION = "What do I have to pay in the next four weeks?";
/**
 * The operating-cost statement, by its sample's file name: a letter's title is the model's and changes with
 * every recording of the demo, so letters are found by their files (a New-mail letter by its tray sender)
 * and titles read from the API.
 */
const STATEMENT_FILE = "13_nebenkostenabrechnung_2025.pdf";
/** An Einschreiben number with a correct check digit (the e2e suite's). */
const TRACKING = "RT 123 456 785 DE";
/** The mock world's court payment order (web/src/mocks/data/documents.ts), opened by `?mock=full`. */
const COURT_ORDER = `/documents/doc_mahnbescheid?mock=full`;
/** A whole number from the environment (`name`), `fallback` when unset, else stops the capture. */
function setting(name, fallback, { min, max }) {
  const value = Number(process.env[name] || fallback);
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`${name} must be a whole number from ${min} to ${max}`);
  return value;
}

/**
 * Device pixels to a CSS pixel, for every picture and the video (CAPTURE_SCALE): 2 keeps the text sharp on a
 * high-density screen, where a picture at 1 looks soft. The phone's pictures are at 2 whatever it is, as a phone draws.
 */
const SCALE = setting("CAPTURE_SCALE", 2, { min: 1, max: 3 });
/** The JPEG quality of the video's frames (CAPTURE_FRAME_QUALITY): high enough that `make capture`'s MP4 loses no detail to them. */
const FRAME_QUALITY = setting("CAPTURE_FRAME_QUALITY", 95, { min: 50, max: 100 });
/** The window of every desktop picture, in CSS pixels (a picture is SCALE times as many device pixels). */
const DESKTOP = { width: 1440, height: 900 };
/**
 * The video's window, in CSS pixels (CAPTURE_VIDEO_WIDTH, CAPTURE_VIDEO_HEIGHT): 1280 is the narrowest in which a
 * letter's page puts the photographed letter beside its explanation, so one frame shows the German letter, the
 * highlighted sentence and the date (narrower, the photo goes under the explanation, out of the window). README shows
 * the animation about 880 px wide, 0.69 of its size. 960 high keeps a letter's title, what to do and its whole deadline
 * card on screen together, above the caption band.
 */
const VIDEO = {
  width: setting("CAPTURE_VIDEO_WIDTH", 1280, { min: 1024, max: 1920 }),
  height: setting("CAPTURE_VIDEO_HEIGHT", 960, { min: 700, max: 1200 }),
};
/**
 * The tour's captions, in the order they are shown. The first six are README's loop (demo.webp, demo.gif): a letter
 * arrives, Ordnung says what it is, what to do and by when, the sentence the date came from and how the date was
 * worked out. The rest are the whole tour (demo.mp4) after it.
 */
const LOOP = [
  "Ordnung: a private secretary for your paperwork.",
  "A photographed letter arrives.",
  "Claude reads it. Code works out the dates.",
  "What it is, what to do, and by when.",
  "Every fact links to the sentence it came from.",
  "Why this date? Each step, with the law behind it.",
];
const TOUR = [
  "The weekly review: ten minutes, one step at a time.",
  "Pay by scanning a code with your banking app. Nothing is paid for you.",
  "The year ahead in one view.",
  "Ask about your letters. Every date and amount is checked against your records.",
  "Contracts: the last day to cancel each one.",
  "A cancellation drafted for you; the proof of sending is kept.",
  "Scam signs flag a letter. Hidden text aimed at AI is ignored.",
  "A court payment order: two weeks by law, and where to get free advice.",
  "How it was read: what Claude was asked, and what code checked.",
  "Runs on your own computer. Try it: ordnung demo",
];
/**
 * How long a caption stays on screen at least, in milliseconds: long enough to read twice at a calm pace (2.5 s and
 * 0.25 s a word). The capture stops when one is shown for less (`readingTimes`).
 */
const readingTime = (text) => 2500 + 250 * text.split(/\s+/).length;
const LAUNCH = process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {};

// ------------------------------------------------------------------------------------------------
// A visible cursor and a caption band (a headless recording shows neither), kept across page loads
// ------------------------------------------------------------------------------------------------

function overlay() {
  const install = () => {
    if (document.getElementById("cap-cursor")) return;
    const cursor = document.createElement("div");
    cursor.id = "cap-cursor";
    cursor.style.cssText =
      "position:fixed;z-index:2147483647;width:24px;height:24px;margin:-2px 0 0 -4px;pointer-events:none;transition:transform .12s ease;";
    cursor.innerHTML =
      '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M5 2.5l14 10.6-6.2 1.1-3.6 6.3z" fill="#16181d" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    const [x, y] = (sessionStorage.getItem("cap-xy") ?? "-60,-60").split(",").map(Number);
    cursor.style.left = `${x}px`;
    cursor.style.top = `${y}px`;
    document.body.appendChild(cursor);
    /** The browser's clock, in milliseconds since 1970 (as `Date.now()` and the frames' moments). */
    const now = () => performance.timeOrigin + performance.now();
    document.addEventListener(
      "mousemove",
      (e) => {
        cursor.style.left = `${e.clientX}px`;
        cursor.style.top = `${e.clientY}px`;
        sessionStorage.setItem("cap-xy", `${e.clientX},${e.clientY}`);
      },
      true,
    );
    // a click shows: the pointer presses in, and a ring spreads from it and fades
    document.addEventListener(
      "mousedown",
      (e) => {
        window.__pressedAt = performance.timeOrigin + e.timeStamp;
        cursor.style.transform = "scale(.82)";
        const ring = document.createElement("div");
        ring.style.cssText =
          `position:fixed;z-index:2147483646;left:${e.clientX - 18}px;top:${e.clientY - 18}px;width:36px;height:36px;` +
          "border-radius:50%;border:3px solid rgba(13,110,95,.85);pointer-events:none;";
        document.body.appendChild(ring);
        ring.animate(
          [
            { transform: "scale(.35)", opacity: 1 },
            { transform: "scale(1.35)", opacity: 0 },
          ],
          { duration: 480, easing: "ease-out" },
        ).onfinish = () => ring.remove();
      },
      true,
    );
    document.addEventListener("mouseup", () => (cursor.style.transform = ""), true);
    // when anything last scrolled (the window or a box in the page): the page's own scrolling after a click
    let scrolledAt = 0;
    document.addEventListener("scroll", () => (scrolledAt = now()), { capture: true, passive: true });
    // when the app last went to another page (a sidebar link): what a click set moving ends there, before the new page
    // draws its first frame
    window.__navAt = 0;
    for (const name of ["pushState", "replaceState"]) {
      const original = History.prototype[name];
      History.prototype[name] = function (...args) {
        window.__navAt = now();
        return original.apply(this, args);
      };
    }
    window.addEventListener("popstate", () => (window.__navAt = now()));
    /**
     * The pointer glides to x, y, in a time that grows with the distance (0.3 to 0.7 s): the browser times it, so it
     * takes as long on a busy computer as on a quiet one. Resolves once it is there, with when it started and ended on
     * the browser's clock.
     */
    window.__glide = (x, y) => {
      const from = cursor.getBoundingClientRect();
      const ms = Math.round(Math.min(700, Math.max(300, Math.hypot(x - from.left, y - from.top) * 0.6)));
      const start = now();
      cursor.style.transition = `transform .12s ease, left ${ms}ms cubic-bezier(.45,0,.25,1), top ${ms}ms cubic-bezier(.45,0,.25,1)`;
      cursor.style.left = `${x}px`;
      cursor.style.top = `${y}px`;
      sessionStorage.setItem("cap-xy", `${x},${y}`);
      return new Promise((done) =>
        setTimeout(() => {
          cursor.style.transition = "transform .12s ease";
          done({ start, end: start + ms });
        }, ms),
      );
    };
    /**
     * Scrolls `el` (the window when null) by dy in a time that grows with the distance (0.45 to 0.9 s), eased, timed by
     * the browser as the glide is: where it is drawn at a moment is where the moment puts it, however few frames a busy
     * computer draws. Resolves once it stands still, with when it started and ended on the browser's clock.
     */
    window.__scroll = (el, dy, fixed) => {
      const box = el ?? document.scrollingElement;
      const start = box.scrollTop;
      const end = Math.max(0, Math.min(box.scrollHeight - box.clientHeight, start + dy));
      const ms = fixed ?? Math.round(Math.min(900, Math.max(450, 350 + Math.abs(end - start) * 0.25)));
      const began = performance.now();
      return new Promise((done) => {
        const step = (at) => {
          const t = Math.min(1, Math.max(0, at - began) / ms);
          const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
          box.scrollTop = start + (end - start) * eased;
          if (t < 1) requestAnimationFrame(step);
          else done({ start: performance.timeOrigin + began, end: performance.timeOrigin + began + ms });
        };
        requestAnimationFrame(step);
      });
    };
    /**
     * After a click: resolves once `after` milliseconds have passed since the press and nothing has scrolled for 200 ms
     * (the page's own smooth scrolling to what was clicked), with the press and the end of what it set moving, on the
     * browser's clock; when the click went to another page, it ends where it went (the new page's loading is not kept).
     */
    window.__settled = (after) =>
      new Promise((done) => {
        const pressed = window.__pressedAt ?? now();
        const went = (end) => ({ start: pressed, end: window.__navAt > pressed ? Math.min(end, window.__navAt) : end });
        const check = () => {
          const t = now();
          if (t >= pressed + after && t - scrolledAt >= 200) done(went(Math.max(pressed + after, Math.min(scrolledAt, t))));
          else if (t - pressed > 4000) done(went(t));
          else requestAnimationFrame(check);
        };
        requestAnimationFrame(check);
      });

    // the caption: a band along the bottom of the main column (the sidebar stays whole), there from the first frame
    // to the last, empty between captions, so the page never jumps; README shows the animation about 880 px wide, where
    // 21 px semi-bold, white on near-black, is 14.5 px
    const bar = document.createElement("div");
    bar.id = "cap-caption";
    bar.style.cssText =
      "position:fixed;left:0;right:0;bottom:0;height:56px;z-index:2147483646;pointer-events:none;" +
      "background:#111418;color:#fff;font:600 21px/56px var(--font-sans, system-ui, sans-serif);" +
      "text-align:center;white-space:nowrap;overflow:hidden;padding:0 24px;";
    const words = document.createElement("span");
    bar.appendChild(words);
    document.body.appendChild(bar);
    /** The band starts where the sidebar ends (the app's `aside`, along the window's left edge). */
    const place = () => {
      const side = [...document.querySelectorAll("aside")].map((a) => a.getBoundingClientRect()).find((r) => r.left <= 0 && r.height >= innerHeight - 1);
      const left = `${Math.round(side?.right ?? 0)}px`;
      if (bar.style.left !== left) bar.style.left = left;
    };
    setInterval(place, 200);
    window.__caption = (text) => {
      place();
      words.textContent = text ?? "";
      sessionStorage.setItem("cap-text", text ?? "");
    };
    window.__caption(sessionStorage.getItem("cap-text") ?? "");
  };
  if (document.body) install();
  else document.addEventListener("DOMContentLoaded", install);
}

/** The demo tour's card stays out of the pictures: the API ends it in the demo, but mock mode starts its own. */
function hideDemoTour() {
  const install = () => {
    const style = document.createElement("style");
    style.textContent = '[aria-label="Demo tour"], [aria-label^="Demo tour ·"] { display: none !important; }';
    document.head.appendChild(style);
  };
  if (document.head) install();
  else document.addEventListener("DOMContentLoaded", install);
}

// ------------------------------------------------------------------------------------------------
// The guard: README's media are public, so no page may show this computer, its owner or the wrong theme
// ------------------------------------------------------------------------------------------------

/**
 * What no page may show (capture-guard.mjs, which the real app's two pictures share), found when the capture runs:
 * this computer's paths, the demo's data folder and where the pictures go among them, its name, the git e-mail, the
 * author's name and CAPTURE_FORBIDDEN's words. None of it is written into the repo.
 */
const FORBIDDEN = forbiddenWords(REPO, [[resolve(opts.data), "the demo's data folder"], [OUT, "the pictures' folder"]]);
/** The start of every path of this computer the capture knows: a path cut off at the window's edge still shows it. */
const ROOTS = pathRoots([REPO, resolve(opts.data), OUT]);

/**
 * In every page the capture opens (an init script): at most every 250 ms after the page changes or scrolls, it looks
 * at the text on screen and the values of the fields on screen for a `forbidden` word (anywhere but inside a longer
 * word or number, in any case) or the start of a path of this computer (`roots`, see {@link pathRoots}), and at the
 * theme (`theme`: "dark" only for the two dark pictures). On screen, because
 * that is what a picture or a frame shows: the letter's "How it was read" holds an export command with the data
 * folder further down, which no picture shows. What it finds is kept in sessionStorage "cap-leaks", across the
 * tour's page loads, for {@link assertClean}.
 */
function guardPage({ forbidden, roots, theme }) {
  if (!location.protocol.startsWith("http")) return; // a new tab's blank page, before the capture opens one
  const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rules = forbidden.map(({ text, what }) => ({ what, pattern: new RegExp(`(?<![\\p{L}\\p{N}])${escape(text)}(?![\\p{L}\\p{N}])`, "iu") }));
  const note = (what) => {
    const where = `${location.pathname}${location.search}`;
    const found = JSON.parse(sessionStorage.getItem("cap-leaks") ?? "[]");
    if (found.some((f) => f.what === what && f.where === where)) return;
    found.push({ what, where });
    sessionStorage.setItem("cap-leaks", JSON.stringify(found));
  };
  const onScreen = (rect) => rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
  const visible = { checkOpacity: true, checkVisibilityCSS: true, opacityProperty: true, visibilityProperty: true };
  /** The texts on screen, in the page's order. */
  const shown = () => {
    const texts = [];
    const range = document.createRange();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!node.nodeValue.trim() || !node.parentElement?.checkVisibility(visible)) continue;
      range.selectNodeContents(node);
      if ([...range.getClientRects()].some(onScreen)) texts.push(node.nodeValue);
    }
    for (const field of document.querySelectorAll("input, textarea")) {
      if (field.value && field.checkVisibility(visible) && onScreen(field.getBoundingClientRect())) texts.push(field.value);
    }
    return texts;
  };
  const check = () => {
    if (!document.body || document.readyState === "loading") return;
    const texts = shown();
    // joined both ways: a path may be drawn in pieces, and a name may stand between two other texts
    const text = `${texts.join("")}\n${texts.join("\n")}`;
    for (const { what, pattern } of rules) if (pattern.test(text)) note(what);
    for (const root of roots) if (text.includes(root)) note("the start of a path of this computer");
    if (document.documentElement.classList.contains("dark") !== (theme === "dark")) note(theme === "dark" ? "the light theme" : "the dark theme");
  };
  let timer = 0;
  const soon = () => {
    if (timer) return;
    timer = setTimeout(() => {
      timer = 0;
      check();
    }, 250);
  };
  new MutationObserver(soon).observe(document, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["class", "value"] });
  document.addEventListener("scroll", soon, { capture: true, passive: true });
  window.addEventListener("resize", soon);
  window.addEventListener("load", check);
  window.__capCheck = check;
}

/** Stops the capture when the page showed, at any time since its tab opened, what no picture may (never repeating it). */
async function assertClean(page) {
  const found = await page.evaluate(() => {
    window.__capCheck?.();
    return JSON.parse(sessionStorage.getItem("cap-leaks") ?? "[]");
  });
  if (found.length) throw new Error(`A page showed what no picture may: ${found.map((f) => `${f.what} on ${f.where}`).join("; ")}`);
}

/** The video's frames as they come (recordVideo's), while the tour records them. */
let recorded = [];

/**
 * Shows `text` in the caption band (none: the band empty), and keeps when, for the video's check of reading times. It
 * returns once a frame with it has come: what is kept next starts with the new caption, never with a frame or two of
 * the one before it over the next page (a frame comes a moment after the page drew it, longer on a busy computer).
 */
async function caption(page, text) {
  const drawn = await page.evaluate(
    (t) =>
      new Promise((done) => {
        const same = (document.getElementById("cap-caption")?.textContent ?? "") === t;
        window.__caption?.(t);
        // two frames on: the first painted with the caption has begun by then, so a frame with a later moment shows it
        requestAnimationFrame(() => requestAnimationFrame(() => done({ at: performance.timeOrigin + performance.now(), same })));
      }),
    text,
  );
  for (const waited = Date.now(); !drawn.same && !(recorded.at(-1)?.at >= drawn.at) && Date.now() - waited < 2000; ) {
    await page.waitForTimeout(20);
  }
  captions.push({ text, at: drawn.at });
  await assertClean(page);
}

// ------------------------------------------------------------------------------------------------
// The video's clock: what the tour keeps, and for how long
// ------------------------------------------------------------------------------------------------

/**
 * What the video keeps of the tour, in order (milliseconds since 1970, the clock `Date.now()` reads and the browser's
 * `performance.timeOrigin + performance.now()`): a hold (`ms`, the page standing still under a caption) is shown for
 * exactly `ms`, however long it really took, and a motion (no `ms`: the pointer gliding, a scroll, a click and what it
 * opens) for the time the browser gave it, from its first frame to its last. Everything between them is left out:
 * page loads, the reading of a letter, the capture finding what to point at and waiting for the browser's answer.
 * Drawing frames at twice the pixels slows the page on a busy computer, which made the tour 115 to 126 s long and
 * longer under load; held this way, a still page held N seconds is the same picture, a motion is as long as the
 * browser planned it, and the video is as long from run to run.
 */
const film = [];
/** Each caption shown (or the band emptied, `text` ""), and when, on the clock of {@link film}. */
const captions = [];

/** Keeps a part of the video, in order: one that starts before the last one ended starts where it ended. */
function keep(part) {
  const last = film.at(-1);
  const from = last ? Math.max(part.from, last.to) : part.from;
  film.push({ ...part, from, to: Math.max(from, part.to) });
}

/** The page stands still for `ms` (under its caption): in the video exactly `ms`. */
async function hold(page, ms) {
  const from = Date.now();
  await page.waitForTimeout(ms);
  keep({ from, to: Date.now(), ms });
}

/**
 * Runs `act` (something moving on screen), which resolves with when the motion started and ended on the browser's
 * clock (the overlay's `__glide`, `__scroll` and `__settled`), and keeps that in the video: the time the browser gave
 * it, not the time the capture took to ask for it and hear back, which grows on a busy computer.
 */
async function motion(act) {
  const moved = await act();
  if (moved) keep({ from: moved.start, to: moved.end });
}

/** The pointer glides to x, y (the browser times it), then the mouse is there for real (hover, the click after). */
async function glide(page, x, y) {
  await motion(async () => {
    const moved = await page.evaluate(([px, py]) => window.__glide(px, py), [x, y]);
    await page.mouse.move(x, y);
    return moved;
  });
}

/** Scrolls the window by `dy` CSS pixels, smoothly, in a time the browser keeps (see the overlay's `__scroll`). */
async function scrollPage(page, dy) {
  if (Math.abs(dy) < 8) return;
  await motion(() => page.evaluate((d) => window.__scroll(null, d), dy));
}

/**
 * Brings `locator` into the window's clear part (below the sticky top bar, at least `clear` CSS pixels above the window's
 * bottom edge, 110 by default: above the caption band with room to spare) and glides the pointer onto it: its middle, or
 * `dx` from its left edge. Returns where the pointer is.
 */
async function pointAt(page, locator, { dx, clear = 110 } = {}) {
  await locator.waitFor();
  const dy = await locator.evaluate(
    (el, below) => {
      const r = el.getBoundingClientRect();
      return r.top > 90 && r.bottom < window.innerHeight - below ? 0 : r.top + r.height / 2 - window.innerHeight * 0.45;
    },
    clear,
  );
  await scrollPage(page, dy);
  // where it is once it stands still: a pointer sent to where the target was would click beside it
  const box = await still(locator);
  const x = box.x + (dx ?? Math.min(box.width / 2, 60));
  const y = box.y + box.height / 2;
  await glide(page, x, y);
  return { x, y };
}

/** The bounding box of `locator` once it is the same twice, 100 ms apart (at most 3 s). */
async function still(locator) {
  let box = await locator.boundingBox();
  for (let waited = 0; waited < 3000; waited += 100) {
    await locator.page().waitForTimeout(100);
    const now = await locator.boundingBox();
    if (box && now && now.x === box.x && now.y === box.y) return now;
    box = now;
  }
  if (!box) throw new Error(`nothing to point at: ${locator}`);
  return box;
}

/**
 * Points at `locator` and clicks it: the pointer rests on it a moment, then presses (its ring shows), and the page's
 * answer is kept for `after` milliseconds from the press (a dialog opening), longer while the page scrolls itself
 * (to what was clicked); what follows is the caller's.
 */
async function click(page, locator, { dx, clear, after = 450, press, blank } = {}) {
  const { x, y } = await pointAt(page, locator, { dx, clear });
  await hold(page, 250);
  // a click that goes to another page empties the band first: no frame shows a caption over a page it does not describe
  if (blank) await caption(page, "");
  await motion(async () => {
    if (press) {
      // held down a moment before it is let go, so the ring shows over the page before a link changes it
      await page.mouse.down();
      await page.evaluate((ms) => new Promise((done) => setTimeout(done, ms)), press);
      await page.mouse.up();
    } else await page.mouse.click(x, y);
    return page.evaluate((ms) => window.__settled(ms), after);
  });
}

/** Scroll the window smoothly until the top of `locator` is at `at` (0 top, 1 bottom) of its height. */
async function scrollTo(page, locator, at) {
  await locator.waitFor();
  const dy = await locator.evaluate((el, share) => el.getBoundingClientRect().top - window.innerHeight * share, at);
  await scrollPage(page, dy);
}

/**
 * Starts a beat: its caption, once the page it talks about is on screen, held for `ms` (in all, with what moves under
 * it, at least its reading time: see {@link readingTime}).
 */
async function beat(page, text, ms) {
  await caption(page, text);
  if (ms) await hold(page, ms);
}

/**
 * The page's own heading is on screen (its data may still be loading): not the start screen's while the app starts
 * (its `<main>` is busy, its heading for screen readers only) and not a letter page's stand-in while the letter
 * loads (`data-loading`).
 */
async function shown(page) {
  await page.locator('main:not([aria-busy="true"]) h1:not([data-loading])').first().waitFor();
}

/**
 * Go to a page from the sidebar. The caption (when given) changes as soon as the new page's heading is on
 * screen: not before it (over the page before), and not after its data settled (over the new page).
 */
async function nav(page, label) {
  const before = page.url();
  const links = page.getByRole("navigation").getByRole("link", { name: new RegExp(`^(\\d+)?${label}`) });
  // the press shows, its ring spreading over the page before for a quarter of a second, and the click's motion ends
  // where the app goes to the new page (`__settled`): its loading is left out of the video (nothing after it is kept
  // until the next beat), so its skeleton never shows under the caption before
  await click(page, links.filter({ visible: true }).first(), { press: 200, after: 250, blank: true });
  await page.waitForURL((url) => url.href !== before);
  await shown(page);
  await settle(page, 500);
  await assertClean(page);
}

// ------------------------------------------------------------------------------------------------
// Session and demo state
// ------------------------------------------------------------------------------------------------

/**
 * A browser context on the demo, every page of it guarded, a desktop window at SCALE unless `extra` says otherwise: in
 * the dark theme only when `extra` asks for it.
 */
async function newContext(browser, extra = {}) {
  const context = await browser.newContext({ viewport: DESKTOP, deviceScaleFactor: SCALE, locale: "en-GB", timezoneId: "Europe/Berlin", ...extra });
  await context.addInitScript(guardPage, { forbidden: FORBIDDEN, roots: ROOTS, theme: extra.colorScheme === "dark" ? "dark" : "light" });
  await context.addCookies([{ name: `ordnung_token_${opts.port}`, value: TOKEN, url: BASE, httpOnly: true, sameSite: "Strict" }]);
  await context.request.patch(`${BASE}/api/demo/tour`, { data: { active: false, completed: true }, headers: CLIENT });
  return context;
}

async function settle(page, ms = 600) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(ms);
}

async function apiGet(context, path) {
  const res = await context.request.get(`${BASE}${path}`);
  if (!res.ok()) throw new Error(`GET ${path} → ${res.status()}`);
  return res.json();
}

/** The id of the demo letter read from the sample `file` ("13_nebenkostenabrechnung_2025.pdf"). */
async function letterIdFor(context, file) {
  const docs = await apiGet(context, "/api/documents");
  const doc = docs.find((d) => d.filename === file);
  if (!doc) throw new Error(`no demo letter from the sample ${file} (the Inbox has ${docs.map((d) => d.filename).join(", ")})`);
  return doc.id;
}

/** The verdict card of the letter `id`, named by the letter's title as read (from the API). */
async function verdictOf(page, id) {
  const { document } = await apiGet(page.context(), `/api/documents/${id}`);
  return page.getByRole("article", { name: shownAs(document.title ?? document.filename) });
}

/**
 * The letter `id`'s own heading: its title as read (from the API), not the file's name it has while it is being
 * read (its "Reading your letter" card).
 */
async function titleOf(page, id) {
  const { document } = await apiGet(page.context(), `/api/documents/${id}`);
  return page.getByRole("main").getByRole("heading", { level: 1, name: shownAs(document.title ?? document.filename) });
}

/** The New-mail letter from `sender`, read if it wasn't yet (in the page, as a person would): its letter id. */
async function readMail(page, sender) {
  const tray = await apiGet(page.context(), "/api/demo/mail");
  const item = tray.find((t) => t.sender.startsWith(sender));
  if (!item) throw new Error(`no New-mail letter from ${sender}`);
  if (item.opened && item.doc_id) return item.doc_id;
  await page.goto(`${BASE}/inbox`);
  await settle(page);
  await page
    .getByRole("region", { name: /^New mail/ })
    .getByRole("listitem")
    .filter({ hasText: sender })
    .first()
    .getByRole("button", { name: "Let Ordnung read it" })
    .click();
  await page.waitForURL(/\/documents\/doc_/, { timeout: 60_000 });
  return new URL(page.url()).pathname.split("/").pop();
}

/** The tax assessment's objection to-do (its one deadline, titled by the model: from the API): its "show it on the page" button. */
async function objectionEvidence(page, taxId) {
  const { items } = await apiGet(page.context(), `/api/documents/${taxId}`);
  const deadline = items.find((i) => i.kind === "deadline");
  if (!deadline) throw new Error(`the tax assessment has no deadline (its to-dos: ${items.map((i) => i.title).join(", ")})`);
  return page
    .getByRole("region", { name: /^To-dos & dates/ })
    .getByRole("listitem")
    .filter({ hasText: shownAs(deadline.title) })
    .first()
    .getByRole("button", { name: /on the page$/ })
    .first();
}

/**
 * Today's secretary's note is the one Claude wrote for the demo's day ("Written for today"), recorded with the demo,
 * not the one written from the to-dos and dates ("From your to-dos & dates"), which Today shows once a letter read
 * since changes what the note was written from. Waits for it on `page` (Today), or stops the capture.
 */
async function claudesNote(page) {
  const note = page.getByRole("region", { name: "Your secretary's note" });
  try {
    await note.getByText("Written for today", { exact: true }).waitFor({ timeout: 15_000 });
  } catch {
    throw new Error("Today's note is not the one Claude wrote for the demo's day (\"Written for today\"): was a letter read before this picture?");
  }
}

/** A step of the weekly review, in its list of steps. */
function weekStep(page, name) {
  return page.getByRole("main").getByRole("button", { name: new RegExp(`^${name}`) }).first();
}

/** A small, well-formed one-page PDF standing in for the scan of the posting receipt. */
function receiptPdf() {
  const text = `BT /F1 16 Tf 30 150 Td (Einlieferungsbeleg ${TRACKING}) Tj 0 -24 Td (28.09.2026 11:05) Tj ET`;
  const objects = [
    "<</Type/Catalog/Pages 2 0 R>>",
    "<</Type/Pages/Kids[3 0 R]/Count 1>>",
    "<</Type/Page/Parent 2 0 R/MediaBox[0 0 420 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
    `<</Length ${text.length}>>\nstream\n${text}\nendstream`,
    "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
  ];
  let out = "%PDF-1.4\n";
  const offsets = [];
  objects.forEach((body, i) => {
    offsets.push(out.length);
    out += `${i + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
  out += `trailer\n<</Size ${objects.length + 1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

/**
 * The demo's FunkNetz cancellation, sent today by Einschreiben with its tracking number and the
 * posting receipt as proof (what "Mark as sent" and "Add proof" save). Once per demo; its draft id.
 * After Ask's recorded answers: it changes the ledger they are checked against.
 */
async function sendCancellation(context) {
  const contracts = await apiGet(context, "/api/contracts");
  const contract = contracts.find((c) => c.category === "mobile"); // FunkNetz's: by what it is, not by the name the model gave it
  if (!contract) throw new Error("no phone (mobile) contract in the demo");
  const drafts = await apiGet(context, "/api/drafts");
  const sent = drafts.find((d) => d.contract_id === contract.id && d.status === "sent" && d.tracking_number);
  if (sent) return sent.id;
  let draft = drafts.find((d) => d.contract_id === contract.id && d.kind === "cancellation");
  if (!draft) {
    const made = await context.request.post(`${BASE}/api/drafts`, { data: { kind: "cancellation", contract_id: contract.id }, headers: CLIENT });
    if (made.status() !== 201) throw new Error(`draft the cancellation → ${made.status()}`);
    draft = await made.json();
  }
  const marked = await context.request.post(`${BASE}/api/drafts/${draft.id}/sent`, {
    data: { channel: "registered_letter", date: "2026-09-28", tracking_number: TRACKING },
    headers: CLIENT,
  });
  if (!marked.ok()) throw new Error(`mark it sent → ${marked.status()} ${await marked.text()}`);
  const proof = await context.request.post(`${BASE}/api/drafts/${draft.id}/proofs`, {
    multipart: {
      file: { name: "Einlieferungsbeleg.pdf", mimeType: "application/pdf", buffer: receiptPdf() },
      kind: "posting_receipt",
      on_date: "2026-09-28",
      note: "Post office Musterstadt-Mitte, 11:05",
    },
    headers: CLIENT,
  });
  if (proof.status() !== 201) throw new Error(`add the posting receipt → ${proof.status()} ${await proof.text()}`);
  return draft.id;
}

// ------------------------------------------------------------------------------------------------
// The video: a tour of the golden path, the first part of which is the README's GIF
// ------------------------------------------------------------------------------------------------

/** The width and height of a JPEG (its first start-of-frame marker), or `undefined`. */
function jpegSize(data) {
  for (let at = 2; at + 9 < data.length; ) {
    if (data[at] !== 0xff) return undefined;
    const marker = data[at + 1];
    if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
      return { width: data.readUInt16BE(at + 7), height: data.readUInt16BE(at + 5) };
    }
    at += 2 + data.readUInt16BE(at + 2);
  }
  return undefined;
}

/**
 * The video's clock for `film` (see {@link film}): a moment of the tour (milliseconds) as seconds of the video. A hold
 * is stretched or squeezed to its planned length, a motion keeps its own, and a moment between them is where the
 * next one starts (it is left out).
 */
function videoClock(film) {
  let length = 0;
  const parts = film.map(({ from, to, ms }) => {
    const part = { from, to, start: length, length: ms ?? to - from };
    length += part.length;
    return part;
  });
  return (ms) => {
    for (const part of parts) {
      if (ms <= part.from) return part.start / 1000;
      if (ms < part.to) return (part.start + ((ms - part.from) * part.length) / (part.to - part.from)) / 1000;
    }
    return length / 1000;
  };
}

/**
 * The frames as an ffconcat list: each frame from the moment it was drawn until the next one (the page draws a frame
 * only when something on it changes), the last until the tour stopped, on the video's clock (`videoClock(film)`): the
 * frame on screen when the first moment kept starts is the list's first, from 0, and a frame drawn only in what is
 * left out is not in it. The first frame shown (the one on screen when the first moment kept starts or, when none was
 * yet, the first drawn after) is held from 0. So a second the tour names (where README's loop ends) is the same moment in the video
 * `make capture` makes of it.
 *
 * Frames come in the order they were drawn, but now and then one comes with a later moment than the next (the
 * browser gave it none, and Playwright took the moment it arrived: a few dozen in a tour). Such a frame is taken as
 * drawn no later than the next one; one that is then on screen for no time at all is left out.
 */
function concatList(frames, film, stopped) {
  const at = frames.map((f) => Math.min(f.at, stopped));
  for (let i = at.length - 2; i >= 0; i -= 1) at[i] = Math.min(at[i], at[i + 1]);
  const clock = videoClock(film);
  const seconds = (ms) => Math.round(clock(ms) * 1000) / 1000;
  const shown = [];
  for (let i = 0; i < frames.length; i += 1) {
    // the first shown from 0, also when it was drawn after the first moment kept: a later start would put every frame
    // after it that much earlier than the moment the tour names for it
    const from = shown.length ? seconds(at[i]) : 0;
    const until = seconds(i + 1 < frames.length ? at[i + 1] : stopped);
    if (until > from || (i === frames.length - 1 && !shown.length)) shown.push({ name: frames[i].name, seconds: until - from });
  }
  const lines = ["ffconcat version 1.0"];
  for (const frame of shown) lines.push(`file '${frame.name}'`, `duration ${frame.seconds.toFixed(3)}`);
  // the last frame again, so its duration is kept (ffmpeg drops a last file's own)
  lines.push(`file '${shown.at(-1).name}'`);
  return `${lines.join("\n")}\n`;
}

/**
 * The tour, recorded frame by frame. A screencast gives a frame in device pixels only when the browser itself draws at
 * that scale: with the window's scale set for the page alone (a context's `deviceScaleFactor`), every frame came as
 * CSS pixels (the window's size) however large a size it asked for. So the video has a browser of its own, started at SCALE.
 */
async function recordVideo() {
  const dir = join(OUT, "video");
  rmSync(dir, { recursive: true, force: true });
  // the frames go to a folder of their own until the tour has run clean: when the guard stops it, what was recorded up
  // to then shows what no picture may, and is deleted with the folder, never left in `<out>`
  const recording = mkdtempSync(join(tmpdir(), "ordnung-capture-video-"));
  const browser = await chromium.launch({ ...LAUNCH, args: [`--force-device-scale-factor=${SCALE}`] });
  try {
    const context = await newContext(browser, { viewport: VIDEO, deviceScaleFactor: SCALE });
    await context.addInitScript(overlay);
    await context.addInitScript(hideDemoTour);
    const page = await context.newPage();
    page.on("pageerror", (err) => console.error(`page error: ${err.stack ?? err}`));
    page.on("console", (m) => m.type() === "error" && console.error(`console: ${m.text()}`));
    const size = { width: VIDEO.width * SCALE, height: VIDEO.height * SCALE };
    /** Each frame's file and when it was drawn (milliseconds since 1970, the clock `Date.now()` reads). */
    const frames = [];
    await page.screencast.start({
      size,
      quality: FRAME_QUALITY,
      onFrame: ({ data, timestamp }) => {
        const name = `frame-${String(frames.length).padStart(6, "0")}.jpg`;
        writeFileSync(join(recording, name), data);
        frames.push({ name, at: timestamp, size: frames.length ? undefined : jpegSize(data) });
      },
    });
    let cut;
    let stopped;
    try {
      cut = await tour(page, frames);
      await assertClean(page);
      stopped = Date.now();
      await page.screencast.stop();
    } catch (err) {
      mkdirSync(REVIEW, { recursive: true });
      await page.screenshot({ path: join(REVIEW, "capture-error.png") }).catch(() => {});
      console.error(`the page when it stopped → ${join(REVIEW, "capture-error.png")}`);
      await context.close();
      throw err;
    }
    await context.close();
    const drawn = frames[0]?.size;
    if (!drawn || drawn.width !== size.width || drawn.height !== size.height) {
      throw new Error(`the video's frames are ${drawn ? `${drawn.width}×${drawn.height}` : "missing"}, not ${size.width}×${size.height}`);
    }
    // the video starts on Today, keeps the holds and the motions and leaves out the rest (page loads, the reading of a
    // letter, the app's boot screen when the tour switches between the demo and mock mode); README's loop ends on the
    // date's receipt, before the tour moves on
    const clock = videoClock(film);
    writeFileSync(join(recording, "frames.txt"), concatList(frames, film, stopped));
    const loop = clock(cut.loopEnd);
    writeFileSync(join(recording, "cut"), `${loop.toFixed(2)}\n`);
    const shown = readingTimes(captions, clock, stopped);
    shown.forEach(({ text, at, seconds }, i) => console.log(`  beat ${String(i + 1).padStart(2)}  ${at.toFixed(1).padStart(5)} s  ${seconds.toFixed(2)} s  ${text}`));
    try {
      renameSync(recording, dir);
    } catch {
      // the temporary folder is on another file system
      cpSync(recording, dir, { recursive: true });
    }
    // after the frames are in <out>/video, to look at: `make capture` removes them when the run fails
    const short = shown.filter(({ text, seconds }) => seconds * 1000 < readingTime(text));
    if (short.length) {
      throw new Error(`a caption is shown for less than its reading time: ${short.map(({ text, seconds }) => `"${text}" ${seconds.toFixed(2)} s of ${readingTime(text) / 1000} s`).join("; ")}`);
    }
    console.log(
      `video → ${dir} (${frames.length} frames of ${size.width}×${size.height}; the tour ${clock(stopped).toFixed(1)} s, README's loop ${loop.toFixed(1)} s, of ${((stopped - cut.started) / 1000).toFixed(1)} s recorded)`,
    );
  } finally {
    await browser.close();
    rmSync(recording, { recursive: true, force: true });
  }
}

/**
 * Each caption shown (`captions`, with when each came and when the band was emptied), on the video's clock (`clock`,
 * see {@link videoClock}): when it came and for how many seconds it stayed, until the next caption or the empty band
 * (or the tour's end, `stopped`).
 */
function readingTimes(captions, clock, stopped) {
  return captions.flatMap(({ text, at }, i) => {
    if (!text) return [];
    const until = i + 1 < captions.length ? captions[i + 1].at : stopped;
    return [{ text, at: clock(at), seconds: clock(until) - clock(at) }];
  });
}

/**
 * The tour, as the beats of {@link LOOP} and {@link TOUR}, recorded into `frames` (recordVideo's); returns when its
 * clock started (`started`) and when README's loop ends (`loopEnd`), in milliseconds of the clock {@link film} keeps;
 * each caption it shows is in {@link captions}. A caption changes once its page is on screen, never over the page
 * before it, and stays at least its reading time ({@link readingTime}: its holds and what moves under it). The pointer
 * rests off the text being read.
 */
async function tour(page, frames) {
  film.length = 0;
  captions.length = 0;
  recorded = frames;
  // a page before the tour's own, and its frame (the tab draws nothing until it has a page, and the frame comes a
  // moment later), so the screencast has a frame on screen when the first moment is kept
  await page.setContent('<!doctype html><body style="margin:0;background:#fff"></body>');
  for (const waited = Date.now(); !frames.length; await page.waitForTimeout(20)) {
    if (Date.now() - waited > 5000) throw new Error("the video has no frame 5 s after the tour's first page");
  }
  const started = Date.now();
  const mark = (what) => console.log(`  ${((Date.now() - started) / 1000).toFixed(1).padStart(5)} s  ${what}`);
  /** A full page load (into or out of mock mode, or a page the sidebar has no link to): left out of the video. */
  const load = async (url, ready) => {
    await caption(page, "");
    await page.goto(url);
    await (ready ? ready().waitFor({ timeout: 60_000 }) : shown(page));
    await settle(page, 400);
    await assertClean(page);
  };
  /** Closes a dialog or popover where the video does not show it, and leaves no focus ring on what opened it. */
  const close = async () => {
    await page.keyboard.press("Escape");
    await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
  };
  /** The pointer rests in the window's right margin, `y` from its top: off the text being read and off any button. */
  const rest = (y) => glide(page, VIDEO.width - 20, y);

  await page.goto(`${BASE}/`);
  await claudesNote(page);
  await settle(page, 400);

  mark("1 Today");
  // the first frame is README's still before the animation loads: Today with its caption, drawn in full
  await page.evaluate(([x, y]) => window.__glide(x, y), [VIDEO.width - 20, 300]);
  await caption(page, LOOP[0]);
  await page.waitForTimeout(500);
  await hold(page, 1300);
  // a short scroll: the top 3 under the note, whole above the caption band
  await scrollPage(page, await page.getByText("Top 3 this week", { exact: false }).first().evaluate(top3Below));
  await hold(page, 1700);

  mark("2 a letter arrives");
  await nav(page, "Inbox");
  await beat(page, LOOP[1], 1000);
  const letter = page.getByRole("region", { name: /^New mail/ }).getByRole("listitem").filter({ hasText: FINANZAMT }).first();
  const read = letter.getByRole("button", { name: "Let Ordnung read it" });
  const at = await pointAt(page, read);
  await hold(page, 2400);

  mark("3 Claude reads it");
  await beat(page, LOOP[2], 800);
  // the press and the page's first answer to it; the reading after it is left out
  await motion(async () => {
    await page.mouse.click(at.x, at.y);
    return page.evaluate(() => ({ start: window.__pressedAt, end: window.__pressedAt + 300 }));
  });
  // the reading, and the letter drawn as it was while being read, are left out: the video goes on once the letter's
  // own title is its heading
  await page.waitForURL(/\/documents\/doc_/, { timeout: 60_000 });
  const taxId = new URL(page.url()).pathname.split("/").pop();
  await (await titleOf(page, taxId)).waitFor({ timeout: 60_000 });
  await settle(page, 600);
  await assertClean(page);
  const verdict = await verdictOf(page, taxId);
  const deadline = verdict.getByRole("button", { name: "Why this date?" });
  await deadlineInView(page, deadline);
  // the photographed letter on the left, its title, summary, what to do and deadline card on the right; the pointer
  // leaves the button it clicked for the window's right margin, off the letter and its deadline card
  await rest(560);
  await hold(page, 3200);

  mark("4 what, what to do, by when");
  await beat(page, LOOP[3], 5000);

  mark("5 the sentence it came from");
  await beat(page, LOOP[4], 300);
  // the photo's pages drawn (while that is left out), so nothing moves under the sentence once it is shown
  await page.waitForFunction(() => [...document.querySelectorAll('[aria-label="Page images"] img')].every((img) => img.complete && img.naturalWidth > 0), null, {
    timeout: 15_000,
  });
  // the fact's "show it on the page" is with the to-dos, under the explanation: the page scrolls down to it, and after
  // the click the photo beside it scrolls itself to page 2 and the box with the highlighted sentence (kept as the
  // click's answer, see `click`)
  await click(page, await objectionEvidence(page, taxId), { after: 400 });
  // the button keeps no focus, whose tooltip would show when it is back on screen
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
  // back up to the deadline card while the pointer goes to its rest: the sentence beside the date
  await restWhile(page, 560, null);
  await hold(page, 2100);

  mark("6 why this date");
  await beat(page, LOOP[5], 200);
  // from the deadline card itself: the receipt opens beside the date, and the photo with its sentence stays on screen
  await click(page, deadline, { after: 350 });
  const receipt = page.getByRole("dialog", { name: "Why this date?" });
  await receipt.waitFor();
  await hold(page, 300);
  await click(page, receipt.getByRole("button", { name: "Show the rules" }), { after: 300 });
  await rulesInView(page, receipt, 600);
  // the loop's last frame: the finished receipt stands long enough to read before the loop goes back to Today
  await hold(page, 3000);
  const loopEnd = Date.now();

  mark("7 weekly review");
  await close();
  await load(`${BASE}/week`);
  await beat(page, TOUR[0], 700);
  await click(page, weekStep(page, "Pay this week"));
  await rest(300);
  await hold(page, 3100);

  mark("8 pay by scan");
  // a bill's Pay panel: the demo's first payment to this account asks to compare it with the letter once, then the
  // code shows at once (the weekly review's keeps it folded)
  const statement = await letterIdFor(page.context(), STATEMENT_FILE);
  const pay = () => page.getByRole("main").getByRole("article").first().getByRole("button", { name: /^Pay €/ });
  await load(`${BASE}/documents/${statement}`, pay);
  // the caption as soon as the bill is on screen: it is true of the bill and its Pay button, and the panel opens under it
  await beat(page, TOUR[1], 300);
  // the Pay button low in the window, just above the caption band: its panel (about 770 CSS px high) opens above it,
  // where there is room, and the window does not scroll to make some (with the button higher it jumped up and back
  // while the panel placed itself; three quarters down, it still slid down 130 px)
  await scrollTo(page, pay(), 0.89);
  await hold(page, 300);
  // the panel's opening kept until it stands still (it moves into place for half a second); the click leaves the
  // button where it is
  await click(page, pay(), { after: 700, clear: BAND + 8 });
  await page.getByRole("region", { name: "GiroCode (EPC-QR)" }).waitFor();
  await rest(160);
  await hold(page, 2400);
  await click(page, page.getByRole("button", { name: "These match the letter" }), { after: 700 });
  await page.getByRole("img", { name: /^GiroCode: transfer/ }).waitFor();
  await rest(160);
  await hold(page, 3800);
  await close();

  mark("9 timeline");
  await nav(page, "Timeline");
  await beat(page, TOUR[2], 0);
  await rest(330);
  await hold(page, 3200);

  mark("10 ask");
  await nav(page, "Ask");
  await beat(page, TOUR[3], 500);
  await click(page, page.getByRole("list", { name: "Suggested questions" }).getByRole("button", { name: PHONE_QUESTION }), { after: 200 });
  // the answer is a recording that replays: its coming is left out, the video goes on once it is there
  await page.getByRole("main").getByRole("status").filter({ hasText: "Answer ready." }).waitFor({ timeout: 60_000 });
  // the question's box keeps no focus ring or caret under the answer
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
  await settle(page, 500);
  await assertClean(page);
  await rest(200);
  await hold(page, 3500);

  mark("11 contracts");
  await nav(page, "Contracts");
  await beat(page, TOUR[4], 0);
  await rest(330);
  await hold(page, 4200);

  mark("11 proof of sending");
  // sent once Contracts is off screen (sent, it is no decision to make any more, and the page would change under the
  // viewer); after Ask, whose recorded answers replay only against the ledger they were recorded from
  const draftId = await sendCancellation(page.context());
  await load(`${BASE}/letters/${draftId}`);
  await beat(page, TOUR[5], 600);
  await scrollTo(page, page.getByRole("region", { name: "Proof of sending" }), 0.3);
  await rest(200);
  await hold(page, 3900);

  mark("12 a scam");
  // read where the video does not show it (the reading is left out as the tax assessment's was)
  await caption(page, "");
  const scamId = await readMail(page, "Rundfunk-Beitragsservice");
  const scamTitle = await titleOf(page, scamId);
  await load(`${BASE}/documents/${scamId}`, () => scamTitle);
  await beat(page, TOUR[6], 900);
  await scrollTo(page, page.getByText("This looks like a scam", { exact: false }).first(), 0.1);
  await rest(140);
  await hold(page, 3800);

  mark("13 a court order (mock mode)");
  const advice = () => page.getByText("Act now — and get advice", { exact: false }).first();
  await load(`${BASE}${COURT_ORDER}`, advice);
  await beat(page, TOUR[7], 0);
  await rest(140);
  await hold(page, 1600);
  // the advice card's title ("act within two weeks") near the top, and under it the free help, its first entry with
  // its "Free." whole above the caption band
  await scrollTo(page, page.getByRole("heading", { name: /act within two weeks/ }).first(), 0.12);
  const help = page.getByRole("heading", { name: "Free or low-cost help" }).locator("xpath=following-sibling::*[1]//li").first();
  if (!(await help.evaluate((el, band) => el.getBoundingClientRect().bottom <= window.innerHeight - band, BAND))) {
    throw new Error("the court order's first free help is not above the caption band");
  }
  await hold(page, 3700);

  mark("14 how it was read");
  // the tax assessment read at the start, back in the demo
  await load(`${BASE}/documents/${taxId}?view=trace&mock=0`);
  await beat(page, TOUR[8], 400);
  const steps = page.getByRole("list", { name: "Steps of this reading" });
  await click(page, steps.getByRole("button", { name: /^Claude reads the letter/ }).first());
  await hold(page, 1000);
  // the command that exports this reading, under the steps, names the demo's data folder (a path of this computer):
  // "Dates computed" low on screen keeps it below the window's edge, before the step opens and after
  const dates = steps.getByRole("button", { name: /^Dates computed/ }).first();
  await scrollTo(page, dates, 0.6);
  await click(page, dates);
  await rest(260);
  await hold(page, 1300);

  mark("15 the end");
  // on the Inbox, not Today: once a letter has been read, Today's note is the one written from the to-dos, not
  // Claude's (claudesNote)
  await nav(page, "Inbox");
  await beat(page, TOUR[9], 0);
  await rest(300);
  await hold(page, 4500);
  mark("done");
  return { started, loopEnd };
}

/** The caption band's height, in CSS pixels: what a caption talks about stands whole above it. */
const BAND = 56;

/**
 * Today's "Top 3 this week" heading (`el`, in the page): how far to scroll so that its three cards stand whole above
 * the caption band, with as much of the note above them as that leaves.
 */
function top3Below(el) {
  const section = el.closest("section") ?? el.parentElement;
  return section.getBoundingClientRect().bottom - (window.innerHeight - 56 - 20);
}

/**
 * The pointer glides to its rest in the window's right margin, `y` from its top, while the page scrolls: back to its
 * top when `within` is null, else the box that scrolls inside `within` (a locator) to its end. One motion, as long as
 * the longer of the two.
 */
async function restWhile(page, y, within) {
  const x = VIDEO.width - 20;
  await motion(async () => {
    const moved = await (within ?? page.locator("body")).evaluate(
      async (el, [px, py, toTop]) => {
        const box = !toTop && [el, ...el.querySelectorAll("*")].find((n) => n.scrollHeight > n.clientHeight + 4 && getComputedStyle(n).overflowY !== "visible");
        const scrolled = toTop ? window.__scroll(null, -window.scrollY) : box && window.__scroll(box, box.scrollHeight - box.clientHeight - box.scrollTop, 1000);
        const moves = (await Promise.all([window.__glide(px, py), scrolled])).filter(Boolean);
        return { start: Math.min(...moves.map((m) => m.start)), end: Math.max(...moves.map((m) => m.end)) };
      },
      [x, y, !within],
    );
    await page.mouse.move(x, y);
    return moved;
  });
}

/**
 * Scrolls a letter's verdict card so its deadline card (the date, "in N weeks", "Why this date?", whose button is
 * `deadline`) stands whole in the window, clear of the sticky top bar and above the caption band, with the letter's
 * title as high as that allows: when it already does, nothing moves. Stops the capture when the window is too short
 * for it.
 */
async function deadlineInView(page, deadline) {
  const dy = await deadline.evaluate((el, band) => {
    const title = el.closest("article").querySelector("h1")?.getBoundingClientRect();
    const bottom = el.getBoundingClientRect().bottom + 40;
    const clear = window.innerHeight - band;
    if (bottom <= clear) return 0;
    return Math.min(bottom - clear, title ? title.top - 70 : bottom - clear);
  }, BAND);
  await scrollPage(page, dy);
  const fits = await deadline.evaluate((el, band) => el.getBoundingClientRect().bottom + 24 <= window.innerHeight - band, BAND);
  if (!fits) throw new Error("the deadline card does not fit the video's window above the caption band: make CAPTURE_VIDEO_HEIGHT taller");
}

/**
 * "Why this date?" with its rules shown: the receipt is taller than its popover, and scrolls in itself to its end, so
 * its steps, each with its law, and the rule set it applied are on screen, while the pointer goes to its rest in the
 * right margin, `y` from the top, off the receipt.
 */
async function rulesInView(page, receipt, y) {
  await restWhile(page, y, receipt);
}

// ------------------------------------------------------------------------------------------------
// Screenshots
// ------------------------------------------------------------------------------------------------

async function shot(page, name, options = {}) {
  // the pointer rests on the sidebar's empty space: no hover tooltip in the picture
  if ((page.viewportSize()?.width ?? 0) >= 1024) await page.mouse.move(120, 600);
  await page.waitForTimeout(500);
  await assertClean(page);
  await page.screenshot({ path: join(OUT, `${name}.png`), ...options });
  console.log(`shot → ${name}.png`);
}

/** The Ask picture's window: tall enough for the question, the whole answer and what it offers after it. */
const ASK_VIEWPORT = { width: DESKTOP.width, height: 1700 };

/**
 * Ask, on the untouched demo (before the pictures read a letter): a recorded answer replays only
 * against the ledger it was recorded from (`ledger_fingerprint`), and this one's check has work to do. The
 * question box stays at the bottom of the window: the answer's end (its "Copy answer" row, and the questions
 * offered after it) must clear it, or the picture shows them cut off under it and the capture stops.
 */
async function askShot(browser) {
  const context = await newContext(browser, { viewport: ASK_VIEWPORT });
  const page = await context.newPage();
  await page.goto(`${BASE}/ask`);
  await settle(page);
  await page.getByRole("list", { name: "Suggested questions" }).getByRole("button", { name: MONEY_QUESTION }).click();
  await page.getByRole("main").getByRole("status").filter({ hasText: "Answer ready." }).waitFor({ timeout: 60_000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle(page);
  const box = await page.locator("form:has(#ask-input)").boundingBox();
  const ends = [page.getByRole("main").getByRole("button", { name: "Copy answer" }).last()];
  const offered = page.getByRole("main").getByRole("list", { name: "Suggested questions" });
  if (await offered.count()) ends.push(offered.last());
  for (const end of ends) {
    const at = await end.boundingBox();
    if (!box || !at || at.y + at.height > box.y) {
      throw new Error(
        `the Ask picture cuts the answer off: its end reaches y ${at ? Math.round(at.y + at.height) : "?"}, the question box starts at y ${box ? Math.round(box.y) : "?"} (make ASK_VIEWPORT taller)`,
      );
    }
  }
  await shot(page, "ask");
  await context.close();
}

/** A phone's window, at 2 device pixels to the CSS pixel as a phone draws, whatever CAPTURE_SCALE is. */
const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };

/**
 * Today, in light, dark and on a phone, before the other pictures read a letter: a letter read since (they read the
 * tax assessment and the scam letter) makes Claude's note stale, and Today then shows the note written from the
 * to-dos instead (claudesNote stops the capture).
 */
async function todayShots(browser) {
  const context = await newContext(browser);
  const page = await context.newPage();
  page.on("pageerror", (err) => console.error(`page error: ${err.stack ?? err}`));
  await page.goto(`${BASE}/`);
  await settle(page);
  await claudesNote(page);
  await shot(page, "today");
  await context.close();

  const dark = await newContext(browser, { colorScheme: "dark" });
  const darkPage = await dark.newPage();
  await darkPage.goto(`${BASE}/`);
  await darkPage.evaluate(() => localStorage.setItem("ordnung.theme", "dark"));
  await darkPage.reload();
  await settle(darkPage);
  await claudesNote(darkPage);
  await shot(darkPage, "today-dark");
  await dark.close();

  const phone = await newContext(browser, PHONE);
  const phonePage = await phone.newPage();
  await phonePage.goto(`${BASE}/`);
  await settle(phonePage);
  await claudesNote(phonePage);
  await shot(phonePage, "mobile");
  await phone.close();
}

async function screenshots(browser) {
  const context = await newContext(browser);
  const page = await context.newPage();
  page.on("pageerror", (err) => console.error(`page error: ${err.stack ?? err}`));

  const taxId = await readMail(page, FINANZAMT);
  await page.goto(`${BASE}/documents/${taxId}`);
  await settle(page);
  await (await objectionEvidence(page, taxId)).click();
  await page.waitForTimeout(900);
  // the highlight stays on the page image; the letter's verdict card goes back to the top
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);
  await shot(page, "document");
  // "Why this date?" as a close-up, in a window tall enough for every rule step
  await page.setViewportSize({ width: DESKTOP.width, height: 1500 });
  await (await verdictOf(page, taxId)).getByRole("button", { name: "Why this date?" }).click();
  const receipt = page.getByRole("dialog", { name: "Why this date?" });
  await receipt.getByRole("button", { name: "Show the rules" }).click();
  await page.waitForTimeout(700);
  await assertClean(page);
  await receipt.screenshot({ path: join(OUT, "why.png") });
  console.log("shot → why.png");
  await page.keyboard.press("Escape");
  await page.setViewportSize(DESKTOP);

  // How it was read, with Claude's call and the computed dates opened
  await page.goto(`${BASE}/documents/${taxId}?view=trace`);
  await settle(page);
  const steps = page.getByRole("list", { name: "Steps of this reading" });
  await steps.getByRole("button", { name: /^Claude reads the letter/ }).first().click();
  await steps.getByRole("button", { name: /^Dates computed/ }).first().click();
  await page.waitForTimeout(400);
  await steps.evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 80));
  await settle(page);
  await shot(page, "trace");

  // the Pay panel's GiroCode, once compared with the letter: the first payment to the demo's account asks for that
  const statementId = await letterIdFor(context, STATEMENT_FILE);
  await page.goto(`${BASE}/documents/${statementId}`);
  await settle(page);
  await page.getByRole("main").getByRole("article").first().getByRole("button", { name: /^Pay €/ }).click();
  await page.getByRole("region", { name: "GiroCode (EPC-QR)" }).waitFor();
  const compare = page.getByRole("button", { name: "These match the letter" });
  if (await compare.isVisible()) await compare.click();
  await page.getByRole("img", { name: /^GiroCode: transfer/ }).waitFor();
  await settle(page, 800);
  await shot(page, "pay");
  await page.keyboard.press("Escape");

  await page.goto(`${BASE}/week`);
  await settle(page);
  await weekStep(page, "Pay this week").click();
  await settle(page);
  await shot(page, "week");

  for (const [path, name] of [
    ["/numbers", "numbers"],
    ["/timeline", "timeline"],
    ["/contracts", "contracts"],
  ]) {
    await page.goto(`${BASE}${path}`);
    await settle(page);
    await shot(page, name);
  }

  const draftId = await sendCancellation(context);
  await page.goto(`${BASE}/letters/${draftId}`);
  await settle(page, 1000);
  const proof = page.getByRole("region", { name: "Proof of sending" });
  await proof.scrollIntoViewIfNeeded();
  await proof.evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 90));
  await settle(page);
  await shot(page, "proof");

  const scamId = await readMail(page, "Rundfunk-Beitragsservice");
  await page.goto(`${BASE}/documents/${scamId}`);
  await settle(page, 900);
  await shot(page, "scam");
  await context.close();

  const court = await newContext(browser);
  await court.addInitScript(hideDemoTour);
  const courtPage = await court.newPage();
  await courtPage.goto(`${BASE}${COURT_ORDER}`);
  await settle(courtPage, 1200);
  const byWhen = courtPage.getByRole("main").getByText("By when", { exact: true }).first();
  await byWhen.evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 90));
  await settle(courtPage);
  await shot(courtPage, "court-order");
  await court.close();

  const phoneDark = await newContext(browser, { ...PHONE, colorScheme: "dark" });
  const phoneDarkPage = await phoneDark.newPage();
  await phoneDarkPage.goto(`${BASE}/documents/${taxId}`);
  await phoneDarkPage.evaluate(() => localStorage.setItem("ordnung.theme", "dark"));
  await phoneDarkPage.reload();
  await settle(phoneDarkPage, 900);
  await shot(phoneDarkPage, "mobile-dark");
  await phoneDark.close();
}

// ------------------------------------------------------------------------------------------------

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch(LAUNCH);
try {
  if (opts.only === "shots") {
    await askShot(browser);
    await todayShots(browser);
    await screenshots(browser);
  } else {
    await recordVideo();
  }
} finally {
  await browser.close();
}
