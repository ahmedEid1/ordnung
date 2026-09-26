/** Tiny .ics generator for the mock (the real app builds these in `calendar/ics.py`). */
import type { Item } from "@/api/types";

const esc = (s: string) => s.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
const d8 = (iso: string) => iso.replace(/-/g, "");

export function itemsToIcs(items: Item[], reminderDays: Record<string, number[]> = {}): string {
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Ordnung//Demo//EN", "CALSCALE:GREGORIAN", "X-WR-CALNAME:Ordnung"];
  for (const i of items) {
    const date = i.send_by ?? i.due_date;
    if (!date) continue;
    lines.push("BEGIN:VEVENT", `UID:${i.id}@ordnung.local`, `DTSTAMP:20260928T070000Z`);
    if (i.due_time) {
      const t = i.due_time.replace(":", "") + "00";
      lines.push(`DTSTART;TZID=Europe/Berlin:${d8(date)}T${t}`, `DURATION:PT1H`);
    } else {
      lines.push(`DTSTART;VALUE=DATE:${d8(date)}`);
    }
    const prefix = i.send_by ? "Send by: " : "";
    lines.push(`SUMMARY:${esc(prefix + i.title)}`);
    if (i.description) lines.push(`DESCRIPTION:${esc(i.description)}`);
    if (i.location) lines.push(`LOCATION:${esc(i.location)}`);
    for (const days of reminderDays[i.kind] ?? [1]) {
      lines.push("BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${esc(i.title)}`, `TRIGGER:-P${days}D`, "END:VALARM");
    }
    lines.push("END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n");
}

export function icsDataUrl(ics: string): string {
  return `data:text/calendar;charset=utf-8,${encodeURIComponent(ics)}`;
}
