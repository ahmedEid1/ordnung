/**
 * Mock page images: renders a letter spec to an A4 SVG (1240 × 1754 px ≈ 150 dpi) and records
 * where every text line landed, so evidence quotes can be located and turned into highlight
 * boxes (relative 0..1 coordinates) exactly like the real pipeline does with the PDF text layer.
 *
 * Text widths are estimated from Helvetica metrics and enforced with `textLength`, so the boxes
 * match the rendered glyphs whatever sans-serif font the browser substitutes.
 */
import type { Box } from "@/api/types";

export const PAGE_W = 1240;
export const PAGE_H = 1754;

// Helvetica advance widths (1/1000 em) for ASCII 32..126
const W =
  "278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,278,278,584,584,584,556,1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,667,611,722,667,944,667,667,611,278,278,278,469,556,333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,500,278,556,500,722,500,500,500,334,260,334,584"
    .split(",")
    .map(Number);
const EXTRA: Record<string, number> = {
  ä: 556, ö: 556, ü: 556, Ä: 667, Ö: 778, Ü: 722, ß: 611, "€": 556, "§": 556, "–": 556, "—": 1000,
  "„": 333, "“": 333, "”": 333, "‘": 222, "’": 222, "·": 278, é: 556, è: 556, á: 556, ó: 556, "×": 584,
  "°": 400, " ": 278, "•": 350, "²": 333, "…": 1000,
};

function charWidth(ch: string): number {
  const c = ch.charCodeAt(0);
  if (c >= 32 && c <= 126) return W[c - 32]!;
  return EXTRA[ch] ?? 556;
}

/** Width in px of `text` at `size` px (bold ≈ +7 %). */
export function measure(text: string, size: number, bold = false): number {
  let w = 0;
  for (const ch of text) w += charWidth(ch);
  return (w / 1000) * size * (bold ? 1.07 : 1);
}

/** Greedy word wrap to `maxWidth`. */
export function wrap(text: string, size: number, maxWidth: number, bold = false): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (line && measure(candidate, size, bold) > maxWidth) {
      lines.push(line);
      line = word;
    } else line = candidate;
  }
  if (line) lines.push(line);
  return lines;
}

// ------------------------------------------------------------------------------------------------
// Spec
// ------------------------------------------------------------------------------------------------

export type Block =
  | string
  | { text: string; bold?: boolean; size?: number; indent?: number }
  | { rows: [string, string][]; boldLast?: boolean }
  | { gap: number };

export interface LetterPageSpec {
  subject?: string;
  blocks: Block[];
}

export interface LetterSpec {
  /** Sender brand shown in the letterhead. */
  brand: { name: string; color: string; tagline?: string; mark?: "circle" | "square" | "wave" | "shield" | "bars" | "eagle" | "none"; serif?: boolean };
  /** DIN 5008 return-address line above the recipient. */
  senderLine?: string;
  recipient?: string[];
  /** Right-hand info block (label, value). */
  info?: [string, string][];
  pages: LetterPageSpec[];
  /** Small print at the bottom of every page (bank details, register). */
  footer?: string[];
  /** Render like a phone photo (paper on a table, vignette). */
  photo?: boolean;
  /** Passport/ID style data page instead of a letter. */
  idCard?: { title: string; subtitle: string; fields: [string, string][] };
}

interface PlacedLine {
  page: number;
  x: number;
  y: number; // baseline
  size: number;
  bold: boolean;
  text: string;
  width: number;
  color: string;
  anchor?: "end";
}

export interface RenderedLetter {
  pages: string[]; // SVG strings
  lines: PlacedLine[];
  /** Locate a quote → highlight boxes (relative coords) or null if not on any page. */
  locate(quote: string, preferPage?: number | null): { page: number; boxes: Box[] } | null;
  /** Plain text of a page (lines joined). */
  pageText(page: number): string;
}

// ------------------------------------------------------------------------------------------------
// Layout
// ------------------------------------------------------------------------------------------------

const LEFT = 150;
const RIGHT = 1110;
const BODY = 22;
const LH = 34;
const FOOT_Y = 1612;

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function norm(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase();
}

/** Photo mode maps paper coordinates into the photo frame. */
const PHOTO = { x: 70, y: 64, s: 0.886 };

export function renderLetter(spec: LetterSpec): RenderedLetter {
  const lines: PlacedLine[] = [];
  const pageCount = spec.idCard ? 1 : spec.pages.length;
  const add = (l: Omit<PlacedLine, "width">) => {
    const width = measure(l.text, l.size, l.bold);
    lines.push({ ...l, width });
  };

  if (spec.idCard) {
    layoutIdCard(spec, add);
  } else {
    spec.pages.forEach((p, i) => layoutPage(spec, p, i + 1, pageCount, add));
  }

  const pages = Array.from({ length: pageCount }, (_, i) => toSvg(spec, i + 1, pageCount, lines.filter((l) => l.page === i + 1)));

  const pageText = (page: number) =>
    lines
      .filter((l) => l.page === page)
      .map((l) => l.text)
      .join(" ");

  const locate = (quote: string, preferPage?: number | null) => {
    const q = norm(quote);
    if (!q) return null;
    const order = Array.from({ length: pageCount }, (_, i) => i + 1).sort((a, b) =>
      a === preferPage ? -1 : b === preferPage ? 1 : a - b,
    );
    for (const page of order) {
      const pl = lines.filter((l) => l.page === page);
      // build normalised page text with a map back to (line, char offset)
      let text = "";
      const map: { li: number; ci: number }[] = [];
      pl.forEach((l, li) => {
        if (text) {
          text += " ";
          map.push({ li: -1, ci: -1 });
        }
        const lower = l.text.toLowerCase();
        for (let ci = 0; ci < lower.length; ci++) {
          const ch = /\s/.test(lower[ci]!) ? " " : lower[ci]!;
          if (ch === " " && text.endsWith(" ")) continue;
          text += ch;
          map.push({ li, ci });
        }
      });
      const at = text.indexOf(q);
      if (at === -1) continue;
      const spans = new Map<number, [number, number]>();
      for (let k = at; k < at + q.length; k++) {
        const m = map[k];
        if (!m || m.li < 0) continue;
        const cur = spans.get(m.li);
        spans.set(m.li, cur ? [Math.min(cur[0], m.ci), Math.max(cur[1], m.ci + 1)] : [m.ci, m.ci + 1]);
      }
      const boxes: Box[] = [];
      for (const [li, [s, e]] of spans) {
        const l = pl[li]!;
        const scale = l.width / Math.max(1, measure(l.text, l.size, l.bold));
        let x0 = l.x + measure(l.text.slice(0, s), l.size, l.bold) * scale;
        let x1 = l.x + measure(l.text.slice(0, e), l.size, l.bold) * scale;
        if (l.anchor === "end") {
          x0 -= l.width;
          x1 -= l.width;
        }
        let y0 = l.y - l.size * 0.86;
        let y1 = l.y + l.size * 0.28;
        let bx0 = x0 - 3;
        let bx1 = x1 + 3;
        if (spec.photo) {
          bx0 = PHOTO.x + bx0 * PHOTO.s;
          bx1 = PHOTO.x + bx1 * PHOTO.s;
          y0 = PHOTO.y + y0 * PHOTO.s;
          y1 = PHOTO.y + y1 * PHOTO.s;
        }
        boxes.push({
          page,
          x0: round(bx0 / PAGE_W),
          y0: round(y0 / PAGE_H),
          x1: round(bx1 / PAGE_W),
          y1: round(y1 / PAGE_H),
        });
      }
      boxes.sort((a, b) => a.y0 - b.y0);
      return { page, boxes };
    }
    return null;
  };

  return { pages, lines, locate, pageText };
}

const round = (n: number) => Math.round(n * 10000) / 10000;

function layoutPage(
  spec: LetterSpec,
  page: LetterPageSpec,
  n: number,
  total: number,
  add: (l: Omit<PlacedLine, "width">) => void,
) {
  const ink = "#1f1d1a";
  const grey = "#6b675f";
  let y: number;
  if (n === 1) {
    // letterhead
    const plain = spec.brand.mark === "none";
    const bx = plain ? LEFT : LEFT + 66;
    add({ page: n, x: bx, y: plain ? 110 : 132, size: plain ? 22 : 34, bold: !plain, text: spec.brand.name, color: spec.brand.color });
    if (spec.brand.tagline) add({ page: n, x: bx, y: plain ? 140 : 166, size: 17, bold: false, text: spec.brand.tagline, color: grey });
    if (spec.senderLine) add({ page: n, x: LEFT, y: 330, size: 14, bold: false, text: spec.senderLine, color: grey });
    (spec.recipient ?? []).forEach((r, i) => add({ page: n, x: LEFT, y: 382 + i * 32, size: 21, bold: false, text: r, color: ink }));
    (spec.info ?? []).forEach(([k, v], i) => {
      add({ page: n, x: 790, y: 330 + i * 52, size: 14, bold: false, text: k, color: grey });
      add({ page: n, x: 790, y: 352 + i * 52, size: 19, bold: false, text: v, color: ink });
    });
    y = Math.max(640, 330 + (spec.info?.length ?? 0) * 52 + 60);
  } else {
    add({ page: n, x: LEFT, y: 120, size: 17, bold: true, text: spec.brand.name, color: spec.brand.color });
    add({ page: n, x: RIGHT, y: 120, size: 15, bold: false, text: `Seite ${n} von ${total}`, color: grey, anchor: "end" });
    y = 210;
  }
  if (page.subject) {
    for (const line of wrap(page.subject, 24, RIGHT - LEFT, true)) {
      add({ page: n, x: LEFT, y, size: 24, bold: true, text: line, color: ink });
      y += 36;
    }
    y += 22;
  }
  for (const b of page.blocks) {
    if (typeof b === "object" && "gap" in b) {
      y += b.gap;
      continue;
    }
    if (typeof b === "object" && "rows" in b) {
      b.rows.forEach(([k, v], i) => {
        const bold = Boolean(b.boldLast && i === b.rows.length - 1);
        add({ page: n, x: LEFT + 10, y, size: 20, bold, text: k, color: ink });
        add({ page: n, x: RIGHT - 10, y, size: 20, bold, text: v, color: ink, anchor: "end" });
        y += 32;
      });
      y += 16;
      continue;
    }
    const text = typeof b === "string" ? b : b.text;
    const bold = typeof b === "string" ? false : Boolean(b.bold);
    const size = typeof b === "string" ? BODY : b.size ?? BODY;
    const indent = typeof b === "string" ? 0 : b.indent ?? 0;
    for (const line of wrap(text, size, RIGHT - LEFT - indent, bold)) {
      add({ page: n, x: LEFT + indent, y, size, bold, text: line, color: ink });
      y += size === BODY ? LH : Math.round(size * 1.5);
    }
    y += 16;
  }
  if (n < total) add({ page: n, x: RIGHT, y: 1560, size: 15, bold: false, text: `Seite ${n} von ${total}`, color: grey, anchor: "end" });
  (spec.footer ?? []).forEach((f, i) => add({ page: n, x: LEFT, y: FOOT_Y + 30 + i * 22, size: 14, bold: false, text: f, color: grey }));
}

function layoutIdCard(spec: LetterSpec, add: (l: Omit<PlacedLine, "width">) => void) {
  const card = spec.idCard!;
  const ink = "#1f2a3a";
  const grey = "#5b6678";
  add({ page: 1, x: 200, y: 330, size: 30, bold: true, text: card.title, color: ink });
  add({ page: 1, x: 200, y: 368, size: 18, bold: false, text: card.subtitle, color: grey });
  card.fields.forEach(([k, v], i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 560 + col * 290;
    const y = 450 + row * 78;
    add({ page: 1, x, y, size: 14, bold: false, text: k, color: grey });
    add({ page: 1, x, y: y + 28, size: 22, bold: true, text: v, color: ink });
  });
}

// ------------------------------------------------------------------------------------------------
// SVG
// ------------------------------------------------------------------------------------------------

function brandMark(spec: LetterSpec): string {
  const c = spec.brand.color;
  const x = LEFT;
  const y = 98;
  switch (spec.brand.mark) {
    case "none":
      return "";
    case "square":
      return `<rect x="${x}" y="${y}" width="46" height="46" rx="8" fill="${c}"/><rect x="${x + 12}" y="${y + 12}" width="22" height="22" rx="3" fill="#fff" opacity=".9"/>`;
    case "wave":
      return `<circle cx="${x + 23}" cy="${y + 23}" r="23" fill="${c}"/><path d="M${x + 6} ${y + 26} q8 -10 17 0 t17 0" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round"/>`;
    case "shield":
      return `<path d="M${x + 23} ${y} l21 8 v16 c0 13 -9 21 -21 26 c-12 -5 -21 -13 -21 -26 v-16z" fill="${c}"/><path d="M${x + 14} ${y + 24} l7 7 l12 -13" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`;
    case "bars":
      return `<rect x="${x}" y="${y + 20}" width="10" height="26" rx="2" fill="${c}"/><rect x="${x + 16}" y="${y + 10}" width="10" height="36" rx="2" fill="${c}"/><rect x="${x + 32}" y="${y}" width="10" height="46" rx="2" fill="${c}"/>`;
    case "eagle":
      return `<rect x="${x}" y="${y}" width="46" height="46" rx="4" fill="none" stroke="${c}" stroke-width="3"/><path d="M${x + 9} ${y + 17} h28 M${x + 13} ${y + 25} h20 M${x + 17} ${y + 33} h12" stroke="${c}" stroke-width="3.5" stroke-linecap="round"/>`;
    default:
      return `<circle cx="${x + 23}" cy="${y + 23}" r="23" fill="${c}"/><circle cx="${x + 23}" cy="${y + 23}" r="9" fill="#fff" opacity=".9"/>`;
  }
}

function textEl(l: PlacedLine, serif: boolean): string {
  const family = serif ? "Georgia, 'Times New Roman', serif" : "Helvetica, Arial, 'Liberation Sans', 'DejaVu Sans', sans-serif";
  return `<text x="${l.x.toFixed(1)}" y="${l.y.toFixed(1)}" font-size="${l.size}" font-family="${family}"${l.bold ? ' font-weight="700"' : ""} fill="${l.color}"${
    l.anchor === "end" ? ' text-anchor="end"' : ""
  } textLength="${l.width.toFixed(1)}" lengthAdjust="spacingAndGlyphs">${esc(l.text)}</text>`;
}

function toSvg(spec: LetterSpec, n: number, _total: number, lines: PlacedLine[]): string {
  const paper = spec.photo ? "#f6f1e6" : "#ffffff";
  const parts: string[] = [];
  const isFirst = n === 1;
  const serifName = Boolean(spec.brand.serif);

  if (spec.idCard) {
    parts.push(`<rect x="150" y="240" width="940" height="520" rx="26" fill="#eef2f7" stroke="#c9d3e0" stroke-width="2"/>`);
    parts.push(`<rect x="150" y="240" width="940" height="46" rx="26" fill="#3d5a80" opacity=".12"/>`);
    parts.push(`<rect x="200" y="420" width="300" height="300" rx="14" fill="#d5dde8"/>`);
    parts.push(`<circle cx="350" cy="530" r="62" fill="#b6c3d4"/><path d="M250 700 c20 -80 180 -80 200 0" fill="#b6c3d4"/>`);
    parts.push(`<text x="200" y="740" font-size="16" font-family="monospace" fill="#5b6678" textLength="840" lengthAdjust="spacingAndGlyphs">P&lt;EXARIVERA&lt;&lt;SAM&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;&lt;</text>`);
  } else {
    if (isFirst) {
      parts.push(brandMark(spec));
      if (spec.brand.mark !== "none")
        parts.push(`<line x1="${LEFT}" y1="200" x2="${RIGHT}" y2="200" stroke="${spec.brand.color}" stroke-width="3" opacity=".85"/>`);
      if (spec.senderLine) {
        const w = measure(spec.senderLine, 14);
        parts.push(`<line x1="${LEFT}" y1="337" x2="${LEFT + w}" y2="337" stroke="#9a958a" stroke-width="1"/>`);
      }
      // fold marks
      parts.push(`<line x1="40" y1="620" x2="62" y2="620" stroke="#bbb" stroke-width="2"/><line x1="40" y1="877" x2="54" y2="877" stroke="#bbb" stroke-width="2"/>`);
    }
    if (spec.footer?.length) parts.push(`<line x1="${LEFT}" y1="${FOOT_Y}" x2="${RIGHT}" y2="${FOOT_Y}" stroke="#d9d4ca" stroke-width="1.5"/>`);
  }
  for (const l of lines) parts.push(textEl(l, serifName && l.size >= 30));
  // specimen watermark (all sample documents are marked SPECIMEN)
  parts.push(
    `<text x="620" y="1180" font-size="120" font-family="Helvetica, Arial, sans-serif" font-weight="700" fill="${spec.brand.color}" opacity=".045" text-anchor="middle" transform="rotate(-28 620 1180)">SPECIMEN</text>`,
  );

  const content = parts.join("");
  if (!spec.photo) {
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${PAGE_W} ${PAGE_H}" width="${PAGE_W}" height="${PAGE_H}"><rect width="100%" height="100%" fill="${paper}"/>${content}</svg>`;
  }
  // phone photo: dark desk, paper with shadow, uneven lighting
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${PAGE_W} ${PAGE_H}" width="${PAGE_W}" height="${PAGE_H}">
<defs>
<radialGradient id="desk" cx="50%" cy="45%" r="80%"><stop offset="0" stop-color="#5b4a3a"/><stop offset="1" stop-color="#2a211a"/></radialGradient>
<linearGradient id="light" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".18"/><stop offset=".55" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".16"/></linearGradient>
<filter id="sh" x="-5%" y="-5%" width="110%" height="110%"><feDropShadow dx="0" dy="14" stdDeviation="16" flood-color="#000" flood-opacity=".45"/></filter>
</defs>
<rect width="100%" height="100%" fill="url(#desk)"/>
<g transform="translate(${PHOTO.x} ${PHOTO.y}) scale(${PHOTO.s})">
<rect width="${PAGE_W}" height="${PAGE_H}" fill="${paper}" filter="url(#sh)"/>
${content}
<rect width="${PAGE_W}" height="${PAGE_H}" fill="url(#light)"/>
</g>
</svg>`;
}

/** SVG → data URL usable in <img src>. */
export function svgDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
