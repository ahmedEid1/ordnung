/**
 * *Text in pictures* on the mock's computer (`Health.picture_text`, ADR 0024): `GET /health` takes it from
 * {@link pictureTextHealth}; a phone's health has none (`phoneHealth`, `./phone`). The mock's computer has no
 * Tesseract installed (`HEALTH.picture_text`, `./data/system`). Like the API (`ordnung.doctor.picture_text_status`):
 * the switch saved off in Settings → Data makes it `off`, and `ORDNUNG_OCR=off` on the computer wins over the switch.
 */
import type { PictureTextStatus } from "@/api/types";
import type { MockDb } from "./db";

/** What the doctor's row says when the person turned it off in Settings (`ordnung.doctor.OFF_IN_SETTINGS`). */
export const OFF_IN_SETTINGS = "Off (Settings → Data → Text in pictures)";

/** What the mock's computer does of Text in pictures, with the switch as saved. */
export function pictureTextHealth(db: MockDb): PictureTextStatus | null {
  const computer = db.state.health.picture_text;
  if (!computer || computer.state === "off_by_variable") return computer; // the variable wins
  if (db.state.settings.read_picture_text === false) return { state: "off", detail: OFF_IN_SETTINGS, fix: null };
  return computer;
}
