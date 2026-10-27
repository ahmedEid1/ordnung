/**
 * Your household in the mock backend (the static demo and `?mock=1`): the API's policy
 * (`ordnung.secretary.household`, ADR 0023) ported, held to it by the shared vectors in `householdVectors.json`.
 *
 * Made by d3-contract as the shapes and the empty answers: the household starts empty (as `ordnung demo`'s),
 * `GET /api/household` answers it, PUT and PATCH answer 501 like the API until d3-household-core builds them.
 * A letter deleted for good leaves no filing behind; the trash keeps it.
 */
import type { DocumentDetail, Household, HouseholdChange, HouseholdFiling, HouseholdMember, LetterFor } from "@/api/types";
import type { MockDb } from "./db";

/** The `household` row as the API stores it (`StoredHousehold`): never an API body. */
export interface StoredHousehold {
  format: number;
  members: HouseholdMember[];
  /** letter id → member id, or `"me"` */
  links: Record<string, string>;
}

/** What PUT and PATCH answer until d3-household-core builds them (as the API does). */
export const HOUSEHOLD_NOT_BUILT = "Your household isn't built yet.";
/** Whether PUT and PATCH are built here (d3-household-core turns it on with the policy). */
export const HOUSEHOLD_WRITES_BUILT = false as boolean;
/** The version of a household with no people (the API's: 16 hex of the SHA-256 of `[]`). */
export const EMPTY_VERSION = "4f53cda18c2baa0c";

/** A household refusal as the API answers it (`{detail}` with this status). */
export class HouseholdRefusal extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** The household a new demo starts with: nobody. */
export function emptyHousehold(): StoredHousehold {
  return { format: 1, members: [], links: {} };
}

/** `GET /api/household`. */
export function householdView(db: MockDb): Household {
  void db;
  return { members: [], filed: {}, mine: [], suggested: {}, version: EMPTY_VERSION };
}

/** `PUT /api/household`: replace the list of people. */
export function saveHousehold(db: MockDb, body: HouseholdChange): Household {
  void db;
  void body;
  throw new HouseholdRefusal(501, HOUSEHOLD_NOT_BUILT);
}

/** `PATCH /api/household`: file letters for a person, as the person's own, or forget the answer. */
export function fileLetters(db: MockDb, body: HouseholdFiling): Household {
  void db;
  void body;
  throw new HouseholdRefusal(501, HOUSEHOLD_NOT_BUILT);
}

/** Who a letter is for, on its page (`LetterDetail.household`). */
export function letterFor(db: MockDb, doc: DocumentDetail["document"]): LetterFor {
  void db;
  void doc;
  return { filed_for: null, mine: false, suggested: null, add: null };
}

/** A letter deleted for good: its filing goes with it (the trash keeps it). */
export function forgetLetterFiling(db: MockDb, docId: string): void {
  delete db.state.household.links[docId];
}
