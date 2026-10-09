/**
 * The passphrase estimator counts as the server's (`src/ordnung/passphrase.py`): both are held to the same vectors
 * (`passphraseVectors.json`, which `tests/test_passphrase_strength.py` reads too) — what people make up stays
 * refused, a password manager's random password passes — and each to a seeded corpus of what four password managers
 * generate, 99 % of each passing.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import VECTORS from "./passphraseVectors.json";
import {
  APPLE_PASSWORD_BITS,
  applePassword,
  DIGIT_ALPHABET,
  DIGIT_RUN_CHARS,
  humanPattern,
  KEYBOARD_COLUMNS,
  LEETSPEAK,
  LOWER_ALPHABET,
  MIN_PASSPHRASE_BITS,
  OTHER_ALPHABET,
  passphraseBits,
  PATTERN_CHARS,
  RANDOM_MIN_CHARS,
  randomBits,
  UPPER_ALPHABET,
  VOWELS,
  WORD_LETTERS,
  wordBits,
  WORDS_SHARE,
} from "./passphrase";

/** The server's estimator, whose numbers these are. */
const ESTIMATOR = readFileSync(resolve(__dirname, "../../../../src/ordnung/passphrase.py"), "utf8");

function constant(name: string): string {
  const m = new RegExp(`^${name}(?::[^=]+)? = (.+)$`, "m").exec(ESTIMATOR);
  if (!m) throw new Error(`${name} isn't in ordnung/passphrase.py`);
  return m[1]!.trim();
}

/** How many passwords of each generator the corpus holds, and how many of them must pass (as on the server). */
const SAMPLES = 2000;
const PASSING = 0.99;

/** A seeded random number in [0, 1) (mulberry32): the same corpus on every run. */
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type Random = () => number;
const choice = (random: Random, from: string) => from[Math.floor(random() * from.length)]!;
const UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const LOWER = "abcdefghijklmnopqrstuvwxyz";
const DIGITS = "0123456789";
const SYMBOLS = "!#$%&()*+,-./:;<=>?@[]^_{|}~";

/** `length` characters from `sets` together, at least one of each — as the generators make sure. */
function randomCharacters(random: Random, length: number, ...sets: string[]): string {
  for (;;) {
    const drawn = Array.from({ length }, () => choice(random, sets.join(""))).join("");
    if (sets.every((set) => [...drawn].some((c) => set.includes(c)))) return drawn;
  }
}

/** Apple's: three groups of two made-up syllables (consonant, vowel, consonant), a digit before or after a hyphen or at the end, a capital. */
function apple(random: Random): string {
  const groups = Array.from({ length: 3 }, () => Array.from({ length: 6 }, (_, i) => choice(random, i === 1 || i === 4 ? "aeiouy" : "bcdfghjkmnpqrstvwxz")));
  const spots: [number, number][] = [[0, 5], [1, 0], [1, 5], [2, 0], [2, 5]];
  const [g, at] = spots[Math.floor(random() * spots.length)]!;
  groups[g]![at] = choice(random, DIGITS);
  const letters = groups.flatMap((group, gi) => group.flatMap((c, i) => (/[a-z]/.test(c) ? [[gi, i] as const] : [])));
  const [lg, li] = letters[Math.floor(random() * letters.length)]!;
  groups[lg]![li] = groups[lg]![li]!.toUpperCase();
  return groups.map((group) => group.join("")).join("-");
}

const GENERATORS: Record<string, (random: Random) => string> = {
  Bitwarden: (random) => randomCharacters(random, 14, UPPER, LOWER, DIGITS),
  "1Password": (random) => randomCharacters(random, 20, UPPER, LOWER, DIGITS, SYMBOLS),
  Chrome: (random) => randomCharacters(random, 15, "abcdefghijkmnpqrstuvwxyz", "ABCDEFGHJKLMNPQRSTUVWXYZ", "23456789"),
  Apple: apple,
};

describe("the shared vectors (the server's test reads the same file)", () => {
  it.each(VECTORS.weak)("refuses what people make up: $passphrase ($kind)", ({ passphrase, bits, pattern }) => {
    expect(passphraseBits(passphrase)).toBeCloseTo(bits, 5);
    expect(passphraseBits(passphrase)).toBeLessThan(MIN_PASSPHRASE_BITS);
    expect(humanPattern(passphrase)).toBe(pattern);
  });

  it.each(VECTORS.strong)("takes a password manager's password: $passphrase ($kind)", ({ passphrase, bits, pattern }) => {
    expect(passphraseBits(passphrase)).toBeCloseTo(bits, 5);
    expect(passphraseBits(passphrase)).toBeGreaterThanOrEqual(MIN_PASSPHRASE_BITS);
    expect(humanPattern(passphrase)).toBe(pattern);
  });
});

describe("a password manager's random password", () => {
  it.each(Object.keys(GENERATORS))("%s: 99 % of a seeded corpus passes", (name) => {
    const random = seeded([...name].reduce((sum, c) => sum * 31 + c.codePointAt(0)!, SAMPLES));
    const passwords = Array.from({ length: SAMPLES }, () => GENERATORS[name]!(random));
    const refused = passwords.filter((p) => passphraseBits(p) < MIN_PASSPHRASE_BITS);
    expect(refused.length, refused.slice(0, 10).join(" ")).toBeLessThanOrEqual((1 - PASSING) * SAMPLES);
  });

  it("counts its length times the alphabet it uses, from 12 characters on and without a space", () => {
    expect(randomBits("kT9xVbq2MzRw7p")).toBeCloseTo(14 * Math.log2(62), 9);
    expect(randomBits("u3wu6tIj?&pu+Vj@vt%F")).toBeCloseTo(20 * Math.log2(95), 9);
    expect(randomBits("k7qmx3vxdp9t")).toBeCloseTo(12 * Math.log2(36), 9);
    expect(randomBits("kT9xVbq2MzR")).toBe(0);
    expect(randomBits("kT9xVbq 2MzRw7p")).toBe(0);
    expect(passphraseBits("Xk9#mQ2!vR7@pL4$")).toBeCloseTo(16 * Math.log2(95), 9);
  });

  it("is never counted less than its words", () => {
    for (const vector of [...VECTORS.weak, ...VECTORS.strong]) expect(passphraseBits(vector.passphrase)).toBeGreaterThanOrEqual(wordBits(vector.passphrase));
  });

  it("takes letters as a pattern only in the case people type", () => {
    expect(humanPattern("k7Lovej2QxZ9")).toBe("a very common word");
    expect(humanPattern("k7L0vej2QxZ9")).toBe("a very common word");
    expect(humanPattern("k7LoVej2QxZ9")).toBeNull();
    expect(humanPattern("xTqWerkQ9vW7")).toBeNull();
    expect(humanPattern("Tiger7#Horse")).toBe("words");
    expect(humanPattern("tIGer7#hORse")).toBeNull();
    expect(humanPattern("Tgrkz7#Hrspq")).toBeNull();
  });

  it("knows Apple's strong passwords by their shape", () => {
    expect(applePassword("kuvGis-hihvo6-quzbyc")).toBe(true);
    expect(passphraseBits("kuvGis-hihvo6-quzbyc")).toBe(APPLE_PASSWORD_BITS);
    for (const other of ["kuvgis-hihvo6-quzbyc", "kuvGis-hihvoq-quzbyc", "kuvGis-hih6oq-quzbyc", "Garden-flower-tiger7", "kuvGis-hihvo6"]) {
      expect(applePassword(other), other).toBe(false);
      expect(passphraseBits(other), other).toBeLessThan(MIN_PASSPHRASE_BITS);
    }
  });

  it("uses the server's numbers, keyboard columns and leetspeak", () => {
    expect(Number(constant("RANDOM_MIN_CHARS"))).toBe(RANDOM_MIN_CHARS);
    expect(Number(constant("LOWER_ALPHABET"))).toBe(LOWER_ALPHABET);
    expect(Number(constant("UPPER_ALPHABET"))).toBe(UPPER_ALPHABET);
    expect(Number(constant("DIGIT_ALPHABET"))).toBe(DIGIT_ALPHABET);
    expect(Number(constant("OTHER_ALPHABET"))).toBe(OTHER_ALPHABET);
    expect(Number(constant("PATTERN_CHARS"))).toBe(PATTERN_CHARS);
    expect(Number(constant("DIGIT_RUN_CHARS"))).toBe(DIGIT_RUN_CHARS);
    expect(Number(constant("WORD_LETTERS"))).toBe(WORD_LETTERS);
    expect(Number(constant("WORDS_SHARE"))).toBe(WORDS_SHARE);
    expect(Number(constant("APPLE_PASSWORD_BITS"))).toBe(APPLE_PASSWORD_BITS);
    expect(constant("VOWELS")).toBe(JSON.stringify(VOWELS));
    const columns = /^KEYBOARD_COLUMNS: tuple\[str, \.\.\.\] = \(([^)]*)\)/m.exec(ESTIMATOR)?.[1] ?? "";
    expect([...columns.matchAll(/"([^"]*)"/g)].map((m) => m[1])).toEqual(KEYBOARD_COLUMNS);
    const leet = /^LEETSPEAK = \{([^}]*)\}/m.exec(ESTIMATOR)?.[1] ?? "";
    expect(Object.fromEntries([...leet.matchAll(/"([^"]+)": "([^"]+)"/g)].map((m) => [m[1], m[2]]))).toEqual(LEETSPEAK);
  });
});
