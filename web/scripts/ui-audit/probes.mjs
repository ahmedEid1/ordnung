/**
 * UI audit probes: layout checks that run inside the page, the keyboard-focus walk, axe-core and
 * the console / network listeners. Plain ESM so a Playwright spec can import them too:
 *
 *   import { layoutFindings, focusFindings, axeFindings, watchPage } from "../scripts/ui-audit/probes.mjs";
 *
 * Every finding is `{ probe, kind?, selector, text, rect, detail }`; `rect` is in page coordinates
 * (CSS px, scroll offset included). The caller adds the state, viewport and theme.
 */
import AxeBuilder from "@axe-core/playwright";

export const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/** Probe names, in report order (the letters follow the audit brief). */
export const PROBES = {
  "page-overflow": "a. page scrolls sideways (scrollWidth > clientWidth)",
  "offscreen": "b. element extends past the left/right edge of the viewport",
  "clipped-text": "c. text cut off by an overflow hidden/clip box (no ellipsis)",
  "truncated": "c. deliberate truncation (ellipsis / line-clamp) — judge whether information is lost",
  "clipped-content": "c. controls or images cut off by an overflow hidden/clip box",
  "text-overflow": "d. text (kind text) or a box (kind box) sticks out of its container without being clipped",
  "overlap": "e. interactive elements overlap each other",
  "covered": "e. an interactive element's centre is covered by another element",
  "target-size": "f. interactive target smaller than 24×24 CSS px, too close to its neighbours",
  "target-size-spaced": "f. smaller than 24×24 but spaced far enough apart (WCAG 2.5.8 spacing exception), or exempt",
  "broken-image": "g. image failed to load",
  "empty-icon": "g. SVG icon rendered with zero size",
  "focus-invisible": "h. keyboard focus lands on an element without a visible focus indicator",
  "focus-hidden": "h. keyboard focus lands on a hidden element",
  "focus-offscreen": "h. keyboard focus lands on an element outside the viewport",
  "focus-obscured": "h. the focused element is covered by another element",
  "axe": "i. axe-core violation (WCAG 2.2 A/AA)",
  "console": "j. console error / warning",
  "page-error": "j. uncaught error in the page",
  "request-failed": "j. failed request or HTTP 4xx/5xx",
  "small-text": "k. text rendered smaller than 12 px",
  "structure": "extra: no or several <h1>, no or several <main> landmarks",
};

// ------------------------------------------------------------------------------------------------
// In-page layout probe (a–g, k). Self-contained: it is serialised into the page.
// ------------------------------------------------------------------------------------------------

function layoutProbeInPage(opts) {
  const MAX = opts?.max ?? 400;
  const out = [];
  const root = document.documentElement;
  const vw = root.clientWidth; // excludes a classic scrollbar
  const vh = root.clientHeight;
  const sx = window.scrollX;
  const sy = window.scrollY;
  const styles = new Map();
  const cs = (el) => {
    let s = styles.get(el);
    if (!s) {
      s = getComputedStyle(el);
      styles.set(el, s);
    }
    return s;
  };
  const rects = new Map();
  const rectOf = (el) => {
    let r = rects.get(el);
    if (!r) {
      r = el.getBoundingClientRect();
      rects.set(el, r);
    }
    return r;
  };
  const pageRect = (r) => ({ x: Math.round(r.left + sx), y: Math.round(r.top + sy), w: Math.round(r.width), h: Math.round(r.height) });
  const clean = (s, n = 90) => (s ?? "").replace(/\s+/g, " ").trim().slice(0, n);
  const textOf = (el, n = 90) => clean(el.innerText || el.textContent || el.getAttribute?.("aria-label") || el.getAttribute?.("title") || el.getAttribute?.("alt") || "", n);
  const unstableId = (id) => !id || /[:«»]/.test(id) || /^(r|radix-|headlessui-)\d/.test(id);

  function path(el) {
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 6) {
      let s = cur.tagName.toLowerCase();
      if (!unstableId(cur.id)) {
        parts.unshift(`${s}#${CSS.escape(cur.id)}`);
        break;
      }
      const role = cur.getAttribute("role");
      if (role) s += `[role=${role}]`;
      const label = cur.getAttribute("aria-label");
      if (label) s += `[aria-label="${clean(label, 40)}"]`;
      for (const a of ["data-tour", "data-testid", "data-highlight", "data-popover", "data-docked"]) {
        if (cur.hasAttribute(a)) {
          const v = cur.getAttribute(a);
          s += v ? `[${a}="${clean(v, 30)}"]` : `[${a}]`;
        }
      }
      if (cur.classList?.contains("card")) s += ".card";
      const parent = cur.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter((c) => c.tagName === cur.tagName);
        if (same.length > 1) s += `:nth-of-type(${same.indexOf(cur) + 1})`;
      }
      parts.unshift(s);
      if (cur.tagName === "MAIN" || cur.tagName === "BODY" || role === "dialog") break;
      cur = parent;
    }
    return parts.join(" > ");
  }

  function visible(el) {
    if (!el.isConnected) return false;
    if (el.checkVisibility && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const r = rectOf(el);
    return r.width > 0 || r.height > 0;
  }
  // visually hidden on purpose (Tailwind sr-only: 1px box or clip-path inset(50%)), itself or a close parent
  const srOnly = (el) => {
    const own = rectOf(el);
    if (own.width <= 1.5 && own.height <= 1.5 && cs(el).display !== "contents") return true;
    for (let a = el, i = 0; a && a !== document.body && i < 5; a = a.parentElement, i += 1) {
      const s = cs(a);
      if (s.position === "absolute" && (/inset\(50%\)/.test(s.clipPath) || /rect\(0(px)?,? 0(px)?,? 0(px)?,? 0(px)?\)/.test(s.clip))) return true;
    }
    return false;
  };
  // the part of an element that isn't cut away by scrolling/clipping parents (null: nothing shows) —
  // e.g. entries scrolled out of view inside a scrolling list, or a collapsed (0 px) section
  const shown = new Map();
  const shownRect = (el) => {
    if (shown.has(el)) return shown.get(el);
    const r = rectOf(el);
    let box = { l: r.left, t: r.top, r: r.right, b: r.bottom };
    for (let a = el.parentElement; a && a !== document.body && a !== root; a = a.parentElement) {
      const s = cs(a);
      if (s.overflowX !== "visible" || s.overflowY !== "visible") {
        const ar = rectOf(a);
        const bl = parseFloat(s.borderLeftWidth) || 0;
        const bt = parseFloat(s.borderTopWidth) || 0;
        const l = ar.left + bl;
        const t = ar.top + bt;
        box = { l: Math.max(box.l, l), t: Math.max(box.t, t), r: Math.min(box.r, l + a.clientWidth), b: Math.min(box.b, t + a.clientHeight) };
        if (box.r - box.l < 1 || box.b - box.t < 1) {
          shown.set(el, null);
          return null;
        }
      }
      if (s.position === "fixed") break;
    }
    const out = new DOMRect(box.l, box.t, box.r - box.l, box.b - box.t);
    shown.set(el, out);
    return out;
  };
  const clips = (v) => v === "hidden" || v === "clip";
  const scrolls = (v) => v === "auto" || v === "scroll";
  const add = (f) => {
    if (out.length < MAX) out.push(f);
    else if (out.length === MAX) out.push({ probe: "truncated-report", selector: "", text: `more than ${MAX} findings — only the first ${MAX} are listed`, rect: null, detail: {} });
  };
  const inModalBackground = (() => {
    const modals = Array.from(document.querySelectorAll('[aria-modal="true"], dialog[open]')).filter((m) => visible(m));
    if (!modals.length) return () => false;
    return (el) => !modals.some((m) => m.contains(el) || el.contains(m));
  })();
  const hiddenFromAT = (el) => Boolean(el.closest("[inert], [aria-hidden=true]"));

  const all = Array.from(document.body.getElementsByTagName("*"));

  // ---- a. page-level horizontal overflow ---------------------------------------------------
  const sw = Math.max(root.scrollWidth, document.body.scrollWidth);
  if (sw > vw + 0.5) {
    add({ probe: "page-overflow", selector: "html", text: `page is ${sw}px wide in a ${vw}px viewport`, rect: { x: 0, y: 0, w: sw, h: root.scrollHeight }, detail: { scrollWidth: sw, clientWidth: vw, innerWidth: window.innerWidth, by: sw - vw } });
  }

  // ---- b. elements past the left/right edge ------------------------------------------------
  const offenders = new Set();
  for (const el of all) {
    if (el.closest("svg") && el.tagName.toLowerCase() !== "svg") continue;
    const r = rectOf(el);
    if (!(r.width > 0 && r.height > 0)) continue;
    const pastRight = r.right + sx > vw + 1; // page coordinates: we may be scrolled
    const pastLeft = r.left + sx < -1;
    if (!pastRight && !pastLeft) continue;
    if (!visible(el) || srOnly(el)) continue;
    // inside a scroll/clip box (other than the page itself): that box decides what is visible —
    // it is checked as an element of its own (a scroller that bleeds past the edge is reported once)
    let contained = false;
    for (let a = el.parentElement; a && a !== document.body && a !== root; a = a.parentElement) {
      const s = cs(a);
      if (clips(s.overflowX) || scrolls(s.overflowX)) {
        contained = true;
        break;
      }
      if (s.position === "fixed") break;
    }
    if (contained) continue;
    offenders.add(el);
  }
  for (const el of offenders) {
    if (el.parentElement && offenders.has(el.parentElement)) continue; // report the outermost one
    const r = rectOf(el);
    const inside = Array.from(offenders).filter((o) => o !== el && el.contains(o)).length;
    add({
      probe: "offscreen",
      selector: path(el),
      text: textOf(el),
      rect: pageRect(r),
      detail: { left: Math.round(r.left + sx), right: Math.round(r.right + sx), viewport: vw, by: Math.round(Math.max(r.right + sx - vw, -(r.left + sx))), descendants: inside, position: cs(el).position },
    });
  }

  // ---- d. boxes wider than their parent (not text): a child sticking out of an unclipped parent
  // by more than 8 px (small negative margins for optical alignment are fine) ------------------
  for (const el of all) {
    if (offenders.has(el)) continue;
    const s = cs(el);
    if (s.position === "absolute" || s.position === "fixed" || s.display === "contents" || s.display === "inline" || s.display === "none") continue;
    let p = el.parentElement;
    while (p && cs(p).display === "contents") p = p.parentElement;
    if (!p || p === document.body || p === root) continue;
    const ps = cs(p);
    if (ps.overflowX !== "visible" || ps.display === "inline") continue;
    const r = rectOf(el);
    if (!(r.width > 0 && r.height > 0)) continue;
    const pr = rectOf(p);
    const by = Math.max(r.right - pr.right, pr.left - r.left);
    if (by <= 8) continue;
    if (!visible(el) || srOnly(el) || el.closest("svg")) continue;
    add({
      probe: "text-overflow",
      kind: "box",
      selector: path(el),
      text: textOf(el),
      rect: pageRect(r),
      detail: { parent: path(p), parentWidth: Math.round(pr.width), width: Math.round(r.width), by: Math.round(by) },
    });
  }

  // ---- c/d/k. text: clipped, truncated, spilling, too small ---------------------------------
  const clipFindings = new Map(); // container → finding
  const spillFindings = new Map();
  const smallText = new Map();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.nodeValue && n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
  });
  const range = document.createRange();
  let tn;
  let count = 0;
  while ((tn = walker.nextNode()) && count < 20000) {
    count += 1;
    const p = tn.parentElement;
    if (!p || p.closest("script,style,noscript,template,title,textarea,option,select")) continue;
    if (!visible(p) || srOnly(p)) continue;
    range.selectNodeContents(tn);
    const lines = Array.from(range.getClientRects()).filter((r) => r.width > 0.5 && r.height > 0.5);
    if (!lines.length) continue;
    const ps = cs(p);
    const fontSize = parseFloat(ps.fontSize);
    // k. small text
    if (fontSize < 12 && !smallText.has(p)) {
      smallText.set(p, { probe: "small-text", selector: path(p), text: clean(tn.nodeValue), rect: pageRect(rectOf(p)), detail: { fontSize: Math.round(fontSize * 100) / 100, ariaHidden: hiddenFromAT(p) } });
    }
    // walk up: the first box the text leaves decides
    let depth = 0;
    for (let a = p; a && a !== document.body && a !== root && depth < 14; a = a.parentElement, depth += 1) {
      const s = cs(a);
      if (s.display === "inline" || s.display === "contents") continue;
      const r = rectOf(a);
      const bl = parseFloat(s.borderLeftWidth) || 0;
      const br = parseFloat(s.borderRightWidth) || 0;
      const bt = parseFloat(s.borderTopWidth) || 0;
      const bb = parseFloat(s.borderBottomWidth) || 0;
      const pl = parseFloat(s.paddingLeft) || 0;
      const pr = parseFloat(s.paddingRight) || 0;
      const pt = parseFloat(s.paddingTop) || 0;
      const pb = parseFloat(s.paddingBottom) || 0;
      // the padding box (what overflow clips to) and the content box
      const pad = { l: r.left + bl, r: r.left + bl + a.clientWidth, t: r.top + bt, b: r.top + bt + a.clientHeight };
      if (!a.clientWidth && !a.clientHeight) {
        pad.r = r.right - br;
        pad.b = r.bottom - bb;
      }
      const content = { l: pad.l + pl, r: pad.r - pr, t: pad.t + pt, b: pad.b - pb };
      const clipX = clips(s.overflowX);
      const clipY = clips(s.overflowY);
      const scrollX = scrolls(s.overflowX);
      const scrollY = scrolls(s.overflowY);
      const vTol = Math.max(2, fontSize * 0.35);
      const box = clipX || clipY ? pad : content;
      let overX = 0;
      let overY = 0;
      for (const l of lines) {
        overX = Math.max(overX, l.right - box.r, box.l - l.left);
        overY = Math.max(overY, l.bottom - box.b, box.t - l.top);
      }
      const leavesX = overX > 1;
      const leavesY = overY > vTol;
      if ((clipX && leavesX) || (clipY && leavesY)) {
        const ellipsis = s.textOverflow === "ellipsis";
        const clamp = s.webkitLineClamp && s.webkitLineClamp !== "none";
        const kind = ellipsis || clamp ? "truncated" : "clipped-text";
        let f = clipFindings.get(a);
        if (!f) {
          const titled = a.getAttribute("title") ?? a.closest("[title]")?.getAttribute("title") ?? null;
          const labelled = a.closest("[aria-label]")?.getAttribute("aria-label") ?? null;
          f = {
            probe: kind,
            selector: path(a),
            text: clean(a.textContent),
            rect: pageRect(r),
            detail: {
              how: ellipsis ? "ellipsis" : clamp ? `line-clamp ${s.webkitLineClamp}` : `overflow ${s.overflowX}/${s.overflowY}`,
              fullText: clean(a.textContent, 400),
              title: titled ? clean(titled, 200) : null,
              ariaLabel: labelled ? clean(labelled, 200) : null,
              axis: leavesX && leavesY ? "both" : leavesX ? "x" : "y",
              hiddenPx: Math.round(Math.max(leavesX ? overX : 0, leavesY ? overY : 0)),
            },
          };
          clipFindings.set(a, f);
        }
        break;
      }
      if (clipX || clipY || scrollX || scrollY) break; // text inside a scroller/clipper is handled there
      if (leavesX || leavesY) {
        // an auto-height box grows around its text: text below it means a fixed/limited height
        if (!spillFindings.has(a)) {
          spillFindings.set(a, {
            probe: "text-overflow",
            kind: "text",
            selector: path(a),
            text: clean(tn.nodeValue),
            rect: pageRect(r),
            detail: {
              axis: leavesX ? "x" : "y",
              by: Math.round(leavesX ? overX : overY),
              boxWidth: Math.round(content.r - content.l),
              boxHeight: Math.round(content.b - content.t),
              whiteSpace: cs(p).whiteSpace,
              overflowWrap: cs(p).overflowWrap,
              wordBreak: cs(p).wordBreak,
            },
          });
        }
        break;
      }
      // positioned on purpose (badges, overlays): its parents don't have to contain it
      if (s.position === "absolute" || s.position === "fixed") break;
    }
  }
  for (const f of clipFindings.values()) add(f);
  for (const f of spillFindings.values()) add(f);
  for (const f of smallText.values()) add(f);

  // ---- interactive elements ------------------------------------------------------------------
  const INTERACTIVE = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], [role=tab], [role=menuitem], [role=option], [role=switch], [role=checkbox], [role=radio], [tabindex]:not([tabindex="-1"])';
  const interactive = Array.from(document.querySelectorAll(INTERACTIVE)).filter((el) => {
    if (!visible(el)) return false;
    if (el.closest("[inert]")) return false;
    return true;
  });
  // what can actually be seen (not scrolled away inside a scroller, not in a collapsed section)
  const onScreen = interactive.filter((el) => shownRect(el));

  // c. controls / images cut off by clip boxes
  // (images are cropped on purpose — thumbnails with object-cover — so only controls count)
  const collapsed = (el) => {
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const s = cs(a);
      if ((s.overflowX !== "visible" || s.overflowY !== "visible") && (a.clientWidth < 1 || a.clientHeight < 1)) return true;
    }
    return false;
  };
  for (const el of interactive) {
    if (srOnly(el) || collapsed(el)) continue;
    const r = rectOf(el);
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const s = cs(a);
      if (!(clips(s.overflowX) || clips(s.overflowY) || scrolls(s.overflowX) || scrolls(s.overflowY))) continue;
      if (scrolls(s.overflowX) || scrolls(s.overflowY)) break; // reachable by scrolling
      const ar = rectOf(a);
      const bl = parseFloat(s.borderLeftWidth) || 0;
      const bt = parseFloat(s.borderTopWidth) || 0;
      const pad = { l: ar.left + bl, r: ar.left + bl + a.clientWidth, t: ar.top + bt, b: ar.top + bt + a.clientHeight };
      const cutX = clips(s.overflowX) && (r.right > pad.r + 1 || r.left < pad.l - 1);
      const cutY = clips(s.overflowY) && (r.bottom > pad.b + 1 || r.top < pad.t - 1);
      if (cutX || cutY) {
        const hidden = Math.max(0, Math.min(r.right, pad.r) - Math.max(r.left, pad.l)) * Math.max(0, Math.min(r.bottom, pad.b) - Math.max(r.top, pad.t));
        const area = r.width * r.height || 1;
        add({
          probe: "clipped-content",
          selector: path(el),
          text: textOf(el),
          rect: pageRect(r),
          detail: { container: path(a), visibleShare: Math.round((hidden / area) * 100) / 100, axis: cutX && cutY ? "both" : cutX ? "x" : "y", tag: el.tagName.toLowerCase() },
        });
      }
      break;
    }
  }

  // e. overlapping controls (same layer only: fixed/sticky bars vs. page content is checked below)
  const layerOf = (el) => {
    for (let a = el; a && a !== document.body; a = a.parentElement) {
      const p = cs(a).position;
      if (p === "fixed" || p === "sticky") return a;
    }
    return document.body;
  };
  // a visually hidden radio/checkbox is operated through its label: the label is the target
  const labelOf = (el) => el.closest("label") ?? (el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null);
  const targets = [];
  for (const el of onScreen) {
    if (el.closest("[aria-hidden=true]")) continue;
    if (!srOnly(el)) targets.push(el);
    else if (el.matches("input")) {
      const label = labelOf(el);
      if (label && visible(label) && !targets.includes(label)) targets.push(label);
    }
  }
  const layers = new Map(targets.map((el) => [el, layerOf(el)]));
  const seenPairs = new Set();
  for (let i = 0; i < targets.length; i += 1) {
    const a = targets[i];
    const ra = shownRect(a) ?? rectOf(a);
    for (let j = i + 1; j < targets.length; j += 1) {
      const b = targets[j];
      if (layers.get(a) !== layers.get(b)) continue;
      if (a.contains(b) || b.contains(a)) continue;
      const rb = shownRect(b) ?? rectOf(b);
      const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (w > 2 && h > 2) {
        const key = `${path(a)}|${path(b)}`;
        if (seenPairs.has(key)) continue;
        seenPairs.add(key);
        add({ probe: "overlap", selector: path(a), text: `${textOf(a, 40)} ⟷ ${textOf(b, 40)}`, rect: pageRect(ra), detail: { other: path(b), otherRect: pageRect(rb), overlap: { w: Math.round(w), h: Math.round(h) } } });
      }
    }
  }

  // f. target size (WCAG 2.5.8), skipping links inside running text
  const inSentence = (el) => {
    const s = cs(el);
    if (!s.display.startsWith("inline") || s.display === "inline-flex" || s.display === "inline-grid" || s.display === "inline-block") return false;
    const block = el.parentElement?.closest("p, li, dd, td, blockquote, span, div");
    if (!block) return false;
    const own = clean(el.textContent);
    const around = clean(block.textContent);
    return around.length > own.length + 3;
  };
  const boxes = targets.map((el) => [el, rectOf(el)]);
  for (const [el, r] of boxes) {
    if (r.width >= 24 && r.height >= 24) continue;
    if (el.matches("a") && inSentence(el)) continue;
    // spacing exception: a 24 px circle on its centre doesn't touch another target
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    let spacingOk = true;
    for (const [other, o] of boxes) {
      if (other === el || other.contains(el) || el.contains(other)) continue;
      const nx = Math.max(o.left, Math.min(cx, o.right));
      const ny = Math.max(o.top, Math.min(cy, o.bottom));
      if (Math.hypot(nx - cx, ny - cy) < 12) {
        spacingOk = false;
        break;
      }
    }
    add({
      probe: "target-size",
      kind: el.matches("button[data-highlight]") ? "exempt" : spacingOk ? "undersized-but-spaced" : "undersized",
      selector: path(el),
      text: textOf(el),
      rect: pageRect(r),
      detail: { width: Math.round(r.width * 10) / 10, height: Math.round(r.height * 10) / 10, spacingOk, exempt: el.matches("button[data-highlight]") ? "evidence highlight (equivalent full-size control next to the fact)" : null },
    });
  }

  // g. broken images and zero-size icons
  for (const img of Array.from(document.images)) {
    if (!img.getAttribute("src")) continue;
    if (img.complete && img.naturalWidth === 0 && visible(img)) {
      add({ probe: "broken-image", selector: path(img), text: clean(img.alt) || img.currentSrc.slice(-80), rect: pageRect(rectOf(img)), detail: { src: img.currentSrc || img.src } });
    } else if (!img.complete && visible(img)) {
      add({ probe: "broken-image", selector: path(img), text: `still loading: ${clean(img.alt) || img.src.slice(-80)}`, rect: pageRect(rectOf(img)), detail: { src: img.src, loading: img.loading, pending: true } });
    }
  }
  for (const svg of Array.from(document.querySelectorAll("svg"))) {
    if (svg.parentElement?.closest("svg")) continue;
    const s = cs(svg);
    if (s.display === "none" || s.visibility === "hidden") continue;
    const parent = svg.parentElement;
    if (!parent || !visible(parent)) continue;
    const r = rectOf(svg);
    if ((r.width === 0 || r.height === 0) && svg.getAttribute("width") !== "0") {
      add({ probe: "empty-icon", selector: path(svg), text: textOf(parent, 60), rect: pageRect(r), detail: { width: r.width, height: r.height, class: clean(svg.getAttribute("class"), 80) } });
    }
  }

  // headings and landmarks: one <h1> per screen, one <main>
  const h1s = Array.from(document.querySelectorAll("h1")).filter((h) => {
    const s = cs(h);
    return s.display !== "none" && s.visibility !== "hidden" && !h.closest("[hidden], [inert], [aria-hidden=true]");
  });
  const modalOpen = Array.from(document.querySelectorAll('[aria-modal="true"]')).some((m) => visible(m));
  // (a modal dialog, drawer or sheet makes the page with its <h1> inert; the dialog is the screen then)
  if (!h1s.length && !modalOpen) add({ probe: "structure", kind: "no-h1", selector: "body", text: "no <h1> on this screen", rect: null, detail: { title: document.title } });
  else if (h1s.length > 1) add({ probe: "structure", kind: "several-h1", selector: h1s.map(path).join(" | ").slice(0, 300), text: h1s.map((h) => clean(h.textContent, 40)).join(" | "), rect: null, detail: { count: h1s.length } });
  const mains = Array.from(document.querySelectorAll("main, [role=main]"));
  if (mains.length !== 1 && !modalOpen) add({ probe: "structure", kind: mains.length ? "several-main" : "no-main", selector: "body", text: `${mains.length} <main> landmarks`, rect: null, detail: {} });

  return { findings: out, interactiveCount: interactive.length, scrollHeight: root.scrollHeight, clientWidth: vw, clientHeight: vh };
}

/**
 * e. "covered": interactive elements whose centre is under another element.
 *
 * - An overlay (dialog, menu, popover, drawer) is open: its own controls are checked where they are.
 * - Otherwise page content is checked at the top and at the very bottom of the page, and counts
 *   as covered when the cover is in the page flow (a real overlap), or is fixed/sticky chrome that
 *   can't be scrolled away there: a top bar at the top of the page, a bottom bar at the bottom.
 * - Fixed controls outside overlays (tour card, toasts, tab bar) are checked where they are.
 */
async function coveredProbeInPage() {
  const out = [];
  const root = document.documentElement;
  const vw = root.clientWidth;
  const vh = root.clientHeight;
  const frame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const clean = (s, n = 80) => (s ?? "").replace(/\s+/g, " ").trim().slice(0, n);
  const INTERACTIVE = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=menuitem], [role=option], [role=switch], [tabindex]:not([tabindex="-1"])';
  const OVERLAY = '[aria-modal="true"], dialog[open], [role=dialog], [role=menu], [role=listbox][id], [data-popover]';
  const overlays = Array.from(document.querySelectorAll(OVERLAY)).filter((m) => {
    const r = m.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(m).visibility !== "hidden";
  });
  const unstableId = (id) => !id || /[:«»]/.test(id) || /^(r|radix-|headlessui-)\d/.test(id);
  function path(el) {
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 6) {
      let s = cur.tagName.toLowerCase();
      if (!unstableId(cur.id)) {
        parts.unshift(`${s}#${CSS.escape(cur.id)}`);
        break;
      }
      const role = cur.getAttribute("role");
      if (role) s += `[role=${role}]`;
      const label = cur.getAttribute("aria-label");
      if (label) s += `[aria-label="${clean(label, 40)}"]`;
      for (const a of ["data-tour", "data-testid", "data-docked", "data-popover"]) if (cur.hasAttribute(a)) s += cur.getAttribute(a) ? `[${a}="${clean(cur.getAttribute(a), 30)}"]` : `[${a}]`;
      if (cur.classList?.contains("card")) s += ".card";
      const parent = cur.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter((c) => c.tagName === cur.tagName);
        if (same.length > 1) s += `:nth-of-type(${same.indexOf(cur) + 1})`;
      }
      parts.unshift(s);
      if (cur.tagName === "MAIN" || cur.tagName === "BODY" || role === "dialog") break;
      cur = parent;
    }
    return parts.join(" > ");
  }
  const layerOf = (el) => {
    for (let a = el; a && a !== document.body && a !== root; a = a.parentElement) {
      const p = getComputedStyle(a).position;
      if (p === "fixed" || p === "sticky") return a;
    }
    return null;
  };
  const hidden = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 2 || r.height <= 2) return true;
    for (let a = el, i = 0; a && i < 5; a = a.parentElement, i += 1) {
      const s = getComputedStyle(a);
      if (s.position === "absolute" && /inset\(50%\)/.test(s.clipPath)) return true;
    }
    return false;
  };
  const els = Array.from(document.querySelectorAll(INTERACTIVE)).filter((el) => {
    if (el.closest("[inert], [aria-hidden=true]")) return false;
    if (el.checkVisibility && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    return !hidden(el);
  });
  const inOverlay = (el) => overlays.some((o) => o.contains(el));
  const seen = new Set();
  const report = (el, hit, where) => {
    const key = path(el);
    if (seen.has(key)) return;
    seen.add(key);
    const r = el.getBoundingClientRect();
    out.push({
      probe: "covered",
      selector: key,
      text: clean(el.innerText || el.getAttribute("aria-label") || el.getAttribute("title") || ""),
      rect: { x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY), w: Math.round(r.width), h: Math.round(r.height) },
      detail: { by: path(hit), byText: clean(hit.innerText, 60), at: where },
    });
  };
  // is the point inside every scrolling/clipping parent (not scrolled away inside a list)?
  const insideParents = (el, x, y) => {
    for (let a = el.parentElement; a && a !== document.body && a !== root; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.overflowX !== "visible" || s.overflowY !== "visible") {
        const ar = a.getBoundingClientRect();
        const l = ar.left + (parseFloat(s.borderLeftWidth) || 0);
        const t = ar.top + (parseFloat(s.borderTopWidth) || 0);
        if (x < l || y < t || x > l + a.clientWidth || y > t + a.clientHeight) return false;
      }
      if (s.position === "fixed") break;
    }
    return true;
  };
  const hitOf = (el) => {
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    if (cx < 0 || cy < 0 || cx >= vw || cy >= vh) return null;
    if (!insideParents(el, cx, cy)) return null;
    const hit = document.elementFromPoint(cx, cy);
    if (!hit || hit === el || el.contains(hit) || hit.contains(el)) return null;
    return hit;
  };

  // 1. where the page is now: overlay controls, and fixed controls outside overlays
  const now = overlays.length ? els.filter(inOverlay) : els.filter((el) => layerOf(el) && getComputedStyle(layerOf(el)).position === "fixed");
  for (const el of now) {
    const hit = hitOf(el);
    if (hit) report(el, hit, overlays.length ? "open overlay" : "fixed control");
  }
  if (overlays.length) return out;

  // 2. page content at the top and at the bottom of the page
  const content = els.filter((el) => !layerOf(el));
  const start = window.scrollY;
  const max = root.scrollHeight - vh;
  for (const [where, y] of [["top of page", 0], ["bottom of page", Math.max(0, max)]]) {
    if (where === "bottom of page" && max <= 4) break;
    window.scrollTo(0, y);
    await frame();
    for (const el of content) {
      const hit = hitOf(el);
      if (!hit) continue;
      const layer = layerOf(hit);
      if (!layer) {
        report(el, hit, `${where} (in-flow element on top)`);
        continue;
      }
      const lr = layer.getBoundingClientRect();
      const topChrome = lr.top < vh / 2;
      if ((where === "top of page" && topChrome) || (where === "bottom of page" && !topChrome)) report(el, hit, `${where} (can't be scrolled out from under it)`);
    }
  }
  window.scrollTo(0, start);
  await frame();
  return out;
}

/** a–g and k for the current page state (no scrolling except for the covered check, which restores it). */
export async function layoutFindings(page, { max = 400 } = {}) {
  const res = await page.evaluate(layoutProbeInPage, { max });
  let covered = [];
  try {
    covered = await page.evaluate(coveredProbeInPage);
  } catch (err) {
    covered = [{ probe: "probe-error", selector: "", text: `covered probe failed: ${err.message}`, rect: null, detail: {} }];
  }
  return { findings: [...res.findings, ...covered], meta: { interactive: res.interactiveCount, scrollHeight: res.scrollHeight } };
}

// ------------------------------------------------------------------------------------------------
// h. Keyboard focus: Tab through the first N stops
// ------------------------------------------------------------------------------------------------

function focusSetupInPage() {
  const st = document.createElement("style");
  st.id = "__ui_audit_no_transitions";
  // computed styles must show the focused look right away (no half-finished transitions)
  st.textContent = "*,*::before,*::after{transition-duration:0s!important;transition-delay:0s!important}";
  document.head.appendChild(st);
  const sig = (el) => {
    const out = [];
    const take = (s) =>
      [s.outlineStyle, s.outlineWidth, s.outlineColor, s.outlineOffset, s.boxShadow, s.borderTopColor, s.borderBottomColor, s.borderLeftColor, s.borderRightColor, s.borderTopWidth, s.backgroundColor, s.color, s.textDecorationLine, s.textDecorationColor, s.opacity, s.filter].join("|");
    let cur = el;
    for (let i = 0; i < 4 && cur && cur.nodeType === 1; i += 1, cur = cur.parentElement) {
      out.push(take(getComputedStyle(cur)));
      out.push(take(getComputedStyle(cur, "::before")));
      out.push(take(getComputedStyle(cur, "::after")));
    }
    return out;
  };
  const base = new Map();
  const SEL = 'a[href], button, input, select, textarea, summary, iframe, [tabindex], [contenteditable=true]';
  if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  for (const el of Array.from(document.querySelectorAll(SEL))) base.set(el, sig(el));
  window.__uiAuditFocus = { base, sig, seen: [] };
  // start at the top of the page — unless an overlay is open (scrolling would move it)
  const overlay = document.querySelector('[aria-modal="true"], [role=dialog], [role=menu], [data-popover]');
  if (!overlay) window.scrollTo(0, 0);
}

async function focusCheckInPage() {
  // let the browser finish scrolling the new focus into view
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const st = window.__uiAuditFocus;
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return { done: true };
  const clean = (s, n = 80) => (s ?? "").replace(/\s+/g, " ").trim().slice(0, n);
  const unstableId = (id) => !id || /[:«»]/.test(id) || /^(r|radix-|headlessui-)\d/.test(id);
  function path(e) {
    const parts = [];
    let cur = e;
    while (cur && cur.nodeType === 1 && parts.length < 6) {
      let s = cur.tagName.toLowerCase();
      if (!unstableId(cur.id)) {
        parts.unshift(`${s}#${CSS.escape(cur.id)}`);
        break;
      }
      const role = cur.getAttribute("role");
      if (role) s += `[role=${role}]`;
      const label = cur.getAttribute("aria-label");
      if (label) s += `[aria-label="${clean(label, 40)}"]`;
      const parent = cur.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter((c) => c.tagName === cur.tagName);
        if (same.length > 1) s += `:nth-of-type(${same.indexOf(cur) + 1})`;
      }
      parts.unshift(s);
      if (cur.tagName === "MAIN" || cur.tagName === "BODY" || role === "dialog") break;
      cur = parent;
    }
    return parts.join(" > ");
  }
  const key = path(el);
  const repeat = st.seen.includes(el);
  st.seen.push(el);
  const r = el.getBoundingClientRect();
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;
  const rect = { x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY), w: Math.round(r.width), h: Math.round(r.height) };
  const text = clean(el.innerText || el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("placeholder") || el.value || "");
  const findings = [];
  const visibleCss = el.checkVisibility ? el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) : true;
  const es = getComputedStyle(el);
  const tiny = (r.width <= 1.5 && r.height <= 1.5) || (es.position === "absolute" && /inset\(50%\)/.test(es.clipPath));
  // did anything about it (or up to 3 ancestors, or their ::before/::after) change? A visually
  // hidden control (sr-only radio) only counts what its label/parents show.
  const now = st.sig(el);
  const before = st.base.get(el);
  let changed = false;
  if (before) changed = now.some((v, i) => (!tiny || i >= 3) && v !== before[i]);
  else {
    const s = getComputedStyle(el);
    changed = (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== "none";
  }
  // an outline with a transparent colour or zero width doesn't count
  const s = getComputedStyle(el);
  const outline = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0 && !/rgba\([^)]*,\s*0\)$/.test(s.outlineColor) && s.outlineColor !== "transparent";
  if (!visibleCss || (tiny && !changed)) {
    findings.push({ probe: "focus-hidden", selector: key, text, rect, detail: { reason: !visibleCss ? "hidden by CSS" : "visually hidden (1px), and no parent shows the focus" } });
  } else if (r.bottom <= 0 || r.top >= vh || r.right <= 0 || r.left >= vw) {
    findings.push({ probe: "focus-offscreen", selector: key, text, rect, detail: { viewport: { w: vw, h: vh } } });
  } else {
    if (!changed && !outline) {
      findings.push({ probe: "focus-invisible", selector: key, text, rect, detail: { outline: `${s.outlineStyle} ${s.outlineWidth} ${s.outlineColor}`, boxShadow: s.boxShadow } });
    }
    // WCAG 2.4.11: not entirely hidden by author-created content (sticky bars, cards, toasts)
    // centre and four points a quarter in from the corners (rounded corners show what's below)
    const qx = r.width / 4;
    const qy = r.height / 4;
    const pts = [
      [r.left + r.width / 2, r.top + r.height / 2],
      [r.left + qx, r.top + qy],
      [r.right - qx, r.top + qy],
      [r.left + qx, r.bottom - qy],
      [r.right - qx, r.bottom - qy],
    ].filter(([x, y]) => x >= 0 && y >= 0 && x < vw && y < vh);
    const blockers = pts.map(([x, y]) => document.elementFromPoint(x, y)).filter((h) => h && h !== el && !el.contains(h) && !h.contains(el));
    if (pts.length && blockers.length === pts.length) {
      findings.push({ probe: "focus-obscured", selector: key, text, rect, detail: { entirely: true, by: path(blockers[0]) } });
    } else if (blockers.length && pts.length && blockers.length >= 3) {
      findings.push({ probe: "focus-obscured", selector: key, text, rect, detail: { entirely: false, by: path(blockers[0]) } });
    }
  }
  return { done: false, repeat, key, findings };
}

/**
 * Press Tab up to `max` times and check every stop: focus indicator visible, element visible and
 * on screen, not hidden under sticky/fixed layers. The walk starts at the top of the page when
 * nothing has focus, else right after the element that had it (e.g. inside an open dialog). Stops
 * when focus leaves the page or cycles (a focus trap). Leaves the page with transitions disabled.
 */
export async function focusFindings(page, { max = 40 } = {}) {
  await page.evaluate(focusSetupInPage);
  const findings = [];
  const order = [];
  for (let i = 0; i < max; i += 1) {
    await page.keyboard.press("Tab");
    const res = await page.evaluate(focusCheckInPage);
    if (res.done) break;
    if (res.repeat) {
      if (order.filter((k) => k === res.key).length >= 1 && order.length > 2) break;
    }
    order.push(res.key);
    for (const f of res.findings) findings.push({ ...f, detail: { ...f.detail, tabStop: i + 1 } });
  }
  return { findings, stops: order.length };
}

// ------------------------------------------------------------------------------------------------
// i. axe-core
// ------------------------------------------------------------------------------------------------

export async function axeFindings(page, { tags = AXE_TAGS } = {}) {
  const results = await new AxeBuilder({ page }).withTags(tags).analyze();
  const out = [];
  for (const v of results.violations) {
    for (const n of v.nodes) {
      out.push({
        probe: "axe",
        kind: v.id,
        selector: n.target.join(" "),
        text: (n.html ?? "").replace(/\s+/g, " ").slice(0, 140),
        rect: null,
        detail: { impact: n.impact ?? v.impact, help: v.help, helpUrl: v.helpUrl, summary: (n.failureSummary ?? "").split("\n").slice(1).join(" ").trim().slice(0, 300) },
      });
    }
  }
  return out;
}

// ------------------------------------------------------------------------------------------------
// j. console, page errors, failed requests
// ------------------------------------------------------------------------------------------------

/**
 * Start listening. `isIntentional(request)` marks requests the audit itself failed or held
 * (loading/error states) so they are not reported. Returns `{ stop(): findings[] }`.
 */
export function watchPage(page, { base, isIntentional = () => false } = {}) {
  const findings = [];
  let on = true;
  const short = (url) => (base && url.startsWith(base) ? url.slice(base.length) || "/" : url);
  const onConsole = (m) => {
    if (!on) return;
    const type = m.type();
    if (type !== "error" && type !== "warning") return;
    const loc = m.location?.() ?? {};
    const text = m.text();
    if (/Failed to load resource/.test(text) && loc.url && intentionalUrls.has(loc.url)) return;
    findings.push({ probe: "console", kind: type, selector: loc.url ? `${short(loc.url)}:${loc.lineNumber ?? 0}` : "", text: text.slice(0, 300), rect: null, detail: {} });
  };
  const intentionalUrls = new Set();
  const onPageError = (err) => {
    if (!on) return;
    findings.push({ probe: "page-error", selector: "", text: String(err.message ?? err).slice(0, 300), rect: null, detail: { stack: String(err.stack ?? "").split("\n").slice(0, 6).join("\n") } });
  };
  const onFailed = (req) => {
    if (!on) return;
    if (isIntentional(req)) {
      intentionalUrls.add(req.url());
      return;
    }
    const err = req.failure()?.errorText ?? "failed";
    // EventSource reconnects and requests cut short by a navigation are not failures of the page
    if (err === "net::ERR_ABORTED" && (/\/api\/events/.test(req.url()) || req.resourceType() === "document" || req.resourceType() === "image" || req.resourceType() === "fetch")) return;
    findings.push({ probe: "request-failed", kind: req.resourceType(), selector: `${req.method()} ${short(req.url())}`, text: err, rect: null, detail: {} });
  };
  const onResponse = (res) => {
    if (!on) return;
    const status = res.status();
    if (status < 400) return;
    const req = res.request();
    if (isIntentional(req)) {
      intentionalUrls.add(req.url());
      return;
    }
    findings.push({ probe: "request-failed", kind: `http ${status}`, selector: `${req.method()} ${short(req.url())}`, text: `${status} ${res.statusText()}`, rect: null, detail: {} });
  };
  page.on("console", onConsole);
  page.on("pageerror", onPageError);
  page.on("requestfailed", onFailed);
  page.on("response", onResponse);
  return {
    stop() {
      on = false;
      page.off("console", onConsole);
      page.off("pageerror", onPageError);
      page.off("requestfailed", onFailed);
      page.off("response", onResponse);
      return findings;
    },
  };
}
