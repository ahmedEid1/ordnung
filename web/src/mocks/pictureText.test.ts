/**
 * *Text in pictures* in the mock backend (the static demo and `?mock=1`), as the API answers it: `GET /health` says
 * what the mock's computer does (`picture_text`, the doctor's row as a state), following the switch saved under
 * Settings → Data; `ORDNUNG_OCR=off` on the computer wins over it; a phone's health has none.
 */
import { describe, expect, it } from "vitest";
import type { AppSettings, Health, PictureTextStatus } from "@/api/types";
import { createMockServer } from "./server";
import { HEALTH } from "./data/system";
import { phoneHealth } from "./phone";
import { OFF_IN_SETTINGS, pictureTextHealth } from "./pictureText";

const srv = () => createMockServer({ staticDemo: false, latency: 0 });
type Server = ReturnType<typeof srv>;

const health = async (s: Server) => (await (await s.handle("GET", "/health", new URLSearchParams(), undefined)).json()) as Health;
const save = async (s: Server, read: boolean) => {
  const res = await s.handle("PUT", "/settings", new URLSearchParams(), { read_picture_text: read });
  expect(res.ok, `PUT /settings → ${res.status}`).toBe(true);
  return (await res.json()) as AppSettings;
};

/** The doctor's row for a computer whose variable turned it off (`ordnung.doctor`). */
const VARIABLE: PictureTextStatus = { state: "off_by_variable", detail: "Turned off (ORDNUNG_OCR=off)", fix: null };

describe("Text in pictures in the mock's health", () => {
  it("says what the computer has while the switch is on, and off once it is saved off, in the doctor's words", async () => {
    const s = srv();
    expect((await health(s)).picture_text).toEqual(HEALTH.picture_text);
    expect(HEALTH.picture_text?.state).toBe("not_installed");
    expect((await save(s, false)).read_picture_text).toBe(false);
    expect((await health(s)).picture_text).toEqual({ state: "off", detail: OFF_IN_SETTINGS, fix: null });
    expect(OFF_IN_SETTINGS).toBe("Off (Settings → Data → Text in pictures)");
    await save(s, true);
    expect((await health(s)).picture_text).toEqual(HEALTH.picture_text);
  });

  it("keeps the variable's state whatever the switch says: it only ever turns it off, and wins", async () => {
    const s = srv();
    s.db.state.health = { ...s.db.state.health, picture_text: VARIABLE };
    for (const read of [false, true]) {
      await save(s, read);
      expect(pictureTextHealth(s.db)).toEqual(VARIABLE);
      expect((await health(s)).picture_text).toEqual(VARIABLE);
    }
  });

  it("a phone's health has no Text in pictures", () => {
    expect(phoneHealth({ ...HEALTH, picture_text: VARIABLE }).picture_text).toBeNull();
    expect(phoneHealth(HEALTH).picture_text).toBeNull();
  });
});
