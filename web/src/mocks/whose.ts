/**
 * Whose an Idea is about in the mock backend (ADR 0023): `GET /suggestions` passes its list through
 * {@link nameIdeas}. The canned Ideas keep their own titles here; none names a person of the household.
 */
import type { Suggestion } from "@/api/types";
import type { MockDb } from "./db";

/** The Ideas as `GET /suggestions` lists them, each with its own title. */
export function nameIdeas(_db: MockDb, ideas: Suggestion[]): Suggestion[] {
  return ideas;
}
