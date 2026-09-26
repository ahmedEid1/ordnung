/**
 * Browser plumbing for the UI audit: one isolated context per capture (viewport, theme, session
 * cookie), waiting until a page is settled, and route interception for the states that can't be
 * reached by clicking (loading skeletons, errors, live server events).
 */

export const VIEWPORTS = {
  "320x640": { width: 320, height: 640, phone: true },
  "390x844": { width: 390, height: 844, phone: true },
  "768x1024": { width: 768, height: 1024, phone: false },
  "1280x800": { width: 1280, height: 800, phone: false },
  "1920x1080": { width: 1920, height: 1080, phone: false },
};
export const THEMES = ["light", "dark"];
export const CLIENT_HEADER = { "X-Ordnung-Client": "web" };

/** Requests the audit failed, held or answered itself — not reported as the app's failures. */
export const intentional = new WeakSet();

/**
 * A fresh context for one capture: viewport (phones get touch + mobile emulation), the theme
 * stored the way ThemeToggle stores it (`localStorage["ordnung.theme"]`) plus the matching
 * `prefers-color-scheme`, reduced motion, a German-style locale/timezone as in the e2e suite, and
 * the session cookie. `storage` adds more localStorage keys before the app starts.
 */
export async function newAuditContext(browser, { viewport, theme, base, token, storage = {} }) {
  const vp = VIEWPORTS[viewport] ?? parseViewport(viewport);
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: 1,
    isMobile: vp.phone,
    hasTouch: vp.phone,
    colorScheme: theme,
    reducedMotion: "reduce",
    locale: "en-GB",
    timezoneId: "Europe/Berlin",
    acceptDownloads: true,
    serviceWorkers: "block",
  });
  if (token) {
    const { hostname } = new URL(base);
    await context.addCookies([{ name: "ordnung_token", value: token, domain: hostname, path: "/", httpOnly: true, sameSite: "Strict" }]);
  }
  await context.addInitScript(
    ({ theme, storage }) => {
      try {
        localStorage.setItem("ordnung.theme", theme);
        for (const [k, v] of Object.entries(storage)) localStorage.setItem(k, v);
      } catch {
        /* storage blocked */
      }
      // no blinking caret in screenshots
      const style = () => {
        const st = document.createElement("style");
        st.setAttribute("data-ui-audit", "");
        st.textContent = "*{caret-color:transparent!important}";
        (document.head ?? document.documentElement).appendChild(st);
      };
      if (document.head) style();
      else document.addEventListener("DOMContentLoaded", style, { once: true });
    },
    { theme, storage },
  );
  return context;
}

export function parseViewport(v) {
  const m = /^(\d+)x(\d+)$/.exec(v);
  if (!m) throw new Error(`bad viewport "${v}" (use WIDTHxHEIGHT)`);
  const width = Number(m[1]);
  return { width, height: Number(m[2]), phone: width < 768 };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Count the page's requests in flight (not the event stream, not requests the audit holds on
 * purpose). Playwright's "networkidle" fires once per navigation; this also covers the requests a
 * click starts.
 */
export function trackNetwork(page) {
  const inflight = new Set();
  let last = Date.now();
  const done = (r) => {
    if (inflight.delete(r)) last = Date.now();
  };
  page.on("request", (r) => {
    if (r.resourceType() === "eventsource") return;
    inflight.add(r);
    last = Date.now();
  });
  page.on("requestfinished", done);
  page.on("requestfailed", done);
  page.on("close", () => inflight.clear());
  page.__uiAuditNet = {
    busy: () => [...inflight].filter((r) => !intentional.has(r)).length,
    quietFor: () => Date.now() - last,
  };
}

/** Wait until no request has been in flight for `quiet` ms (falls back to Playwright's networkidle). */
export async function networkQuiet(page, { quiet = 350, timeout = 10_000 } = {}) {
  const net = page.__uiAuditNet;
  if (!net) return page.waitForLoadState("networkidle", { timeout }).catch(() => {});
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (net.busy() === 0 && net.quietFor() >= quiet) return;
    await sleep(50);
  }
}

/**
 * Wait until the page is still: network quiet, fonts loaded, images decoded (lazy ones are loaded
 * eagerly so full-page shots have them), and no finite animation running for 3 frames.
 */
export async function settle(page, { timeout = 12_000, idle = true } = {}) {
  const until = Date.now() + timeout;
  if (idle) await networkQuiet(page, { timeout: Math.max(1000, until - Date.now()) });
  await page
    .evaluate(async () => {
      document.querySelectorAll("img[loading=lazy]").forEach((img) => {
        img.loading = "eager";
      });
      await document.fonts?.ready;
    })
    .catch(() => {});
  await page
    .waitForFunction(() => Array.from(document.images).every((i) => i.complete || !i.getAttribute("src")), undefined, {
      timeout: Math.max(500, Math.min(6000, until - Date.now())),
      polling: 100,
    })
    .catch(() => {});
  await page
    .waitForFunction(
      () => {
        const w = window;
        const busy = document
          .getAnimations()
          .some((a) => a.playState === "running" && a.effect?.getTiming?.().iterations !== Infinity && !(a.effect?.target?.closest?.("[aria-busy=true]")));
        w.__uiAuditCalm = busy ? 0 : (w.__uiAuditCalm ?? 0) + 1;
        return w.__uiAuditCalm >= 3;
      },
      undefined,
      { polling: "raf", timeout: Math.max(500, Math.min(5000, until - Date.now())) },
    )
    .catch(() => {});
  if (idle) await networkQuiet(page, { quiet: 200, timeout: 3000 });
  await sleep(80);
}

/**
 * Keep toasts on screen while we capture (they pause while hovered — ToastItem's mouseenter).
 * Dispatches synthetic pointer-enter events, so the real mouse stays where it is.
 */
export async function pinToasts(page) {
  await page
    .evaluate(() => {
      for (const li of Array.from(document.querySelectorAll("li"))) {
        if (!li.closest(".pointer-events-none.fixed") && !li.closest("[aria-live]")) continue;
        li.dispatchEvent(new MouseEvent("mouseover", { bubbles: true, relatedTarget: document.body }));
      }
    })
    .catch(() => {});
}

// ------------------------------------------------------------------------------------------------
// Route interception
// ------------------------------------------------------------------------------------------------

const isApi = (url) => new URL(url).pathname.startsWith("/api/");

/**
 * Never answer matching API requests (loading skeletons). `except` lists path prefixes that go
 * through, e.g. ["/api/health"] so the shell renders around the skeletons.
 */
export async function holdApi(page, { except = ["/api/health", "/api/events"], only = null } = {}) {
  await page.route(
    (url) => isApi(url.href),
    async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (except.some((p) => path.startsWith(p)) || (only && !only.some((p) => path.startsWith(p)))) return route.fallback();
      intentional.add(route.request());
      // held until the context closes
      await new Promise(() => {});
    },
  );
}

/** Answer matching API requests with an error (error states). `status: 0` aborts (network down). */
export async function failApi(page, { status = 500, except = ["/api/health", "/api/events"], only = null, method = null } = {}) {
  await page.route(
    (url) => isApi(url.href),
    async (route) => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      if (except.some((p) => path.startsWith(p)) || (only && !only.some((p) => path.startsWith(p))) || (method && req.method() !== method)) return route.fallback();
      intentional.add(req);
      if (status === 0) return route.abort("connectionrefused");
      return route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ detail: status === 401 ? "Not authenticated" : "Something went wrong (UI audit)" }) });
    },
  );
}

/** Answer one API path (method + regexp) with `fn(request, original?)` → { status, json }. */
export async function fakeApi(page, method, pathRe, fn, { passthrough = false } = {}) {
  await page.route(
    (url) => isApi(url.href) && pathRe.test(new URL(url.href).pathname),
    async (route) => {
      const req = route.request();
      if (req.method() !== method) return route.fallback();
      intentional.add(req);
      let original;
      if (passthrough) {
        const res = await route.fetch();
        original = await res.json().catch(() => undefined);
      }
      const { status = 200, json } = await fn(req, original);
      return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(json) });
    },
  );
}

/**
 * Take over the live-events stream (`GET /api/events`). The app's EventSource waits until
 * `deliver(events)` answers it with those Server-Sent Events (and a one-hour `retry:`, so it
 * doesn't reconnect during the capture). Call before the first navigation.
 */
export async function controlEvents(page) {
  let release;
  let pending = [];
  const waiting = [];
  await page.route(
    (url) => new URL(url.href).pathname === "/api/events",
    async (route) => {
      intentional.add(route.request());
      if (release) return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream", "cache-control": "no-cache" }, body: "retry: 3600000\n\n" });
      waiting.push(route);
    },
  );
  return {
    /** Send these events (`[{ type, data }]`) to the connected page. */
    async deliver(events) {
      pending = events;
      release = true;
      const body = ["retry: 3600000", "", ...pending.flatMap((e) => [`event: ${e.type}`, `data: ${JSON.stringify(e.data)}`, ""])].join("\n") + "\n";
      const routes = waiting.splice(0);
      if (!routes.length) throw new Error("the page has not opened /api/events yet");
      for (const r of routes) await r.fulfill({ status: 200, headers: { "content-type": "text/event-stream", "cache-control": "no-cache" }, body }).catch(() => {});
    },
    async waitConnected(timeout = 10_000) {
      const until = Date.now() + timeout;
      while (!waiting.length && Date.now() < until) await sleep(50);
      if (!waiting.length) throw new Error("no /api/events connection");
    },
  };
}

/** A small file for the "Add letters" flows. */
export function fakeFile(name, mimeType) {
  const pdf = "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n";
  // 1×1 PNG
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z/C/HgAGgwJ/lK3Q6wAAAABJRU5ErkJggg==", "base64");
  const buffer = mimeType === "application/pdf" ? Buffer.from(pdf) : mimeType.startsWith("image/") ? png : Buffer.from("plain text, not a letter\n");
  return { name, mimeType, buffer };
}
