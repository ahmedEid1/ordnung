#!/usr/bin/env node
/**
 * Print the static demo's world as JSON — the in-memory mock database (`src/mocks/db.ts`) as it starts:
 * profile, today, parties, threads, letters, to-dos, contracts, drafts, their proofs and call notes.
 *
 * `scripts/gen_mock_numbers.py` feeds it to Ordnung's own Python code, so the static demo's My numbers
 * and weekly session are what the real app computes for the same letters (with the same ids).
 *
 *     node web/scripts/mock-world.mjs > world.json
 */
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createJiti } from "jiti";

const here = dirname(fileURLToPath(import.meta.url));
const jiti = createJiti(import.meta.url, { alias: { "@": resolve(here, "../src") }, interopDefault: true });
const { MockDb } = await jiti.import(resolve(here, "../src/mocks/db.ts"));

const db = new MockDb();
const s = db.state;
process.stdout.write(
  JSON.stringify({
    today: db.today,
    profile: s.profile,
    parties: s.parties,
    cases: s.cases,
    documents: s.documents,
    items: s.items,
    contracts: s.contracts,
    drafts: s.drafts,
    proofs: s.proofs,
    calls: s.calls,
  }),
);
