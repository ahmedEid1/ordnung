/** Shared constants for Sam Rivera's sample life (simulated today: Mon 28 Sep 2026). */
export const TODAY = "2026-09-28";

/** ISO timestamp helper: ts("2026-09-11", "17:20") → "2026-09-11T15:20:00Z" (Berlin summer time). */
export function ts(date: string, time = "09:00"): string {
  const [h, m] = time.split(":").map(Number);
  const utcH = (h! - 2 + 24) % 24; // CEST = UTC+2 (good enough for sample data)
  return `${date}T${String(utcH).padStart(2, "0")}:${String(m).padStart(2, "0")}:00Z`;
}

export const SAM = {
  name: "Sam Rivera",
  first: "Sam",
  street: "Beispielweg 5",
  city: "12345 Musterstadt",
  email: "sam.rivera@example.org",
  phone: "+49 151 2345 6789",
  iban: "DE31 7601 0085 0234 5678 12",
};

export const RECIPIENT = [SAM.name, SAM.street, SAM.city];

/** Fake content hash (stable per id). */
export function sha(id: string): string {
  let h = 2166136261;
  let out = "";
  for (let r = 0; r < 8; r++) {
    for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619) >>> 0;
    h = Math.imul(h ^ r, 2246822519) >>> 0;
    out += h.toString(16).padStart(8, "0");
  }
  return out.slice(0, 64);
}
