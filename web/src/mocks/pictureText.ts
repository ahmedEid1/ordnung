/**
 * *Text in pictures* on the mock's computer (`Health.picture_text`, ADR 0024): `GET /health` takes it from
 * {@link pictureTextHealth}; a phone's health has none (`phoneHealth`, `./phone`). The mock's computer has no
 * Tesseract installed (`HEALTH.picture_text`, `./data/system`), whatever the switch says.
 */
import type { PictureTextStatus } from "@/api/types";
import type { MockDb } from "./db";

/** What the mock's computer has of Text in pictures. */
export function pictureTextHealth(db: MockDb): PictureTextStatus | null {
  return db.state.health.picture_text;
}
