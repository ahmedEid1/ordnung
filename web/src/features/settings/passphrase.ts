/**
 * The strength of a new passphrase — a new backup's and a new sync folder's alike: the server's estimator
 * (`src/ordnung/passphrase.py`, whose description says how it counts), counted the same way, and the five made-up
 * words both suggest. The numbers mirrored here are pinned to it by `sync.test.tsx` and `passphrase.test.ts`, and both
 * estimators are held to the same vectors (`passphraseVectors.json`).
 */

/** A new backup's or sync folder's passphrase needs about this many bits by {@link passphraseBits} (`MIN_PASSPHRASE_BITS`). */
export const MIN_PASSPHRASE_BITS = 70;
/** The most one token counts: a word from a large list (`TOKEN_BITS_MAX`). */
export const TOKEN_BITS_MAX = 14;
/** A suggestion has this many random words (`SUGGESTED_WORDS`). */
export const SUGGESTED_WORDS = 5;

const LETTER = /\p{L}/u;
const DIGIT = /\p{Nd}/u;
const UPPER = /\p{Uppercase}/u;
const LOWER = /\p{Lowercase}/u;
const LETTER_BITS = Math.log2(26);
const DIGIT_BITS = Math.log2(10);
/** What a very common word counts (`COMMON_WORD_BITS`). */
const COMMON_WORD_BITS = 7;
/** Keyboard rows (`KEYBOARD_ROWS`): a token along one, either way, is a walk. */
export const KEYBOARD_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm", "qwertzuiop", "asdfghjklöä", "yxcvbnm", "azertyuiop", "qsdfghjklm", "wxcvbn", "1234567890"];
/** Keyboard columns, QWERTY and QWERTZ (`KEYBOARD_COLUMNS`): four along one is a walk in random characters. */
export const KEYBOARD_COLUMNS = ["1qaz", "1qay", "2wsx", "3edc", "4rfv", "5tgb", "6yhn", "6zhn", "7ujm"];
/** Very common words, case-folded (`COMMON_WORDS_TEXT`, word for word). */
export const COMMON_WORDS_TEXT =
  "a about after all also an and any are as at back be because but by can come could day did do even " +
  "first for from get give go good had has have he her him his how i if in into is it its just know " +
  "like look make me most my new no not now of on one only or other our out over people say see she so " +
  "some take than that the their them then there these they think this time to too two up us use want " +
  "was way we well were what when which who why will with work would year yes you your der die das und " +
  "ich du er sie es wir ihr ist nicht mit dem den ein eine zu von auf für im mein dein sein ja nein " +
  "zero three four five six seven eight nine ten eleven twelve twenty hundred thousand second third " +
  "null eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf zwanzig hundert tausend january " +
  "february march april may june july august september october november december januar februar märz " +
  "mai juni juli oktober dezember monday tuesday wednesday thursday friday saturday sunday montag " +
  "dienstag mittwoch donnerstag freitag samstag sonntag today tomorrow yesterday heute morgen gestern " +
  "spring summer autumn fall winter frühling sommer herbst red green blue yellow black white orange " +
  "purple pink brown grey gray silver gold rot grün blau gelb schwarz weiss password passwort pass " +
  "letmein welcome hello hallo admin login secret geheim iloveyou love liebe dragon monkey sunshine " +
  "princess football master shadow test ordnung";
export const COMMON_WORDS = new Set(COMMON_WORDS_TEXT.split(" "));

/** Random characters count from this many on (`RANDOM_MIN_CHARS`). */
export const RANDOM_MIN_CHARS = 12;
/** The alphabet random characters count: lower-case letters, upper-case, digits, other characters, each if used (`LOWER_ALPHABET` …). */
export const LOWER_ALPHABET = 26;
export const UPPER_ALPHABET = 26;
export const DIGIT_ALPHABET = 10;
export const OTHER_ALPHABET = 33;
/** A very common word, a run, a keyboard walk or a repeat makes a pattern from this many characters on (`PATTERN_CHARS`) … */
export const PATTERN_CHARS = 4;
/** … digits in a row from this many (`DIGIT_RUN_CHARS`) … */
export const DIGIT_RUN_CHARS = 5;
/** … a word from this many letters (`WORD_LETTERS`) … */
export const WORD_LETTERS = 3;
/** … and words when those of {@link PATTERN_CHARS} letters or more make up this share (`WORDS_SHARE`). */
export const WORDS_SHARE = 0.6;
/** Leetspeak undone before looking for a very common word (`LEETSPEAK`). */
export const LEETSPEAK: Record<string, string> = { "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", $: "s" };
/** A word has one of these, also with an accent (`VOWELS`). */
export const VOWELS = "aeiouy";
/** Apple's own figure for its strong passwords (`APPLE_PASSWORD_BITS`). */
export const APPLE_PASSWORD_BITS = 71;

/**
 * The tokens {@link wordBits} counts (`ordnung.passphrase.passphrase_tokens`): the passphrase in Unicode NFC cut
 * into runs of letters and runs of digits (anything else only separates them), and a run of letters cut again
 * before an upper-case letter that follows a lower-case one ("CorrectHorse" is two).
 */
export function passphraseTokens(passphrase: string): string[] {
  const tokens: string[] = [];
  let current = "";
  let previous = "";
  for (const char of passphrase.normalize("NFC")) {
    const letter = LETTER.test(char);
    const digit = DIGIT.test(char);
    if (!letter && !digit) {
      if (current) tokens.push(current);
      current = "";
      previous = "";
      continue;
    }
    const sameKind = previous !== "" && DIGIT.test(previous) === digit;
    const camel = letter && UPPER.test(char) && LOWER.test(previous);
    if (sameKind && !camel) current += char;
    else {
      if (current) tokens.push(current);
      current = char;
    }
    previous = char;
  }
  if (current) tokens.push(current);
  return tokens;
}

/** Unicode case folding as Python's `str.casefold()` does it, close enough for telling words apart ("ß" is "ss"). */
function casefold(token: string): string {
  return token.toUpperCase().toLowerCase();
}

const perChar = (token: string) => (DIGIT.test([...token][0] ?? "") ? DIGIT_BITS : LETTER_BITS);

/**
 * `ordnung.passphrase.is_run`: a case-folded token of three characters or more that is one character again and again
 * ("aaa"), runs in order either way ("abc", "54321") or walks along a keyboard row ("qwerty", "0987").
 */
export function isRun(token: string): boolean {
  const chars = [...token];
  if (chars.length < 3) return false;
  if (new Set(chars).size === 1) return true;
  const steps = new Set(chars.slice(1).map((c, i) => c.codePointAt(0)! - chars[i]!.codePointAt(0)!));
  if (steps.size === 1 && (steps.has(1) || steps.has(-1))) return true;
  return KEYBOARD_ROWS.some((row) => row.includes(token) || [...row].reverse().join("").includes(token));
}

/** What one case-folded token counts (`ordnung.passphrase.token_bits`). */
function tokenBits(token: string): number {
  if (isRun(token)) return perChar(token) + 1;
  const length = [...token].length;
  if (COMMON_WORDS.has(token)) return Math.min(COMMON_WORD_BITS, length * perChar(token));
  return Math.min(length * perChar(token), TOKEN_BITS_MAX);
}

/**
 * The words' count of a passphrase in bits (`ordnung.passphrase.word_bits`): each *distinct* token (compared
 * case-folded) counts its length times log2 26 (letters) or log2 10 (digits), at most {@link TOKEN_BITS_MAX} — a
 * token is at best a word from a large list; a run, a keyboard walk or a repeated character about one character, a
 * very common word 7 bits, and tokens that only make a run together ("a b c d …") that one run. Five unrelated words
 * of three or more letters reach 70.
 */
export function wordBits(passphrase: string): number {
  const tokens = passphraseTokens(passphrase).map(casefold);
  const joined = tokens.join("");
  if (tokens.length > 1 && isRun(joined)) return perChar(joined) + 1;
  let bits = 0;
  for (const token of new Set(tokens)) bits += tokenBits(token);
  return bits;
}

/** Every `length` characters in a row of `lines`, either way (`_pieces`). */
function pieces(lines: string[], length: number): string[] {
  const found = new Set<string>();
  for (const row of lines) {
    for (const line of [[...row], [...row].reverse()]) for (let at = 0; at + length <= line.length; at++) found.add(line.slice(at, at + length).join(""));
  }
  return [...found];
}

const PATTERN_WORDS = [...COMMON_WORDS].filter((word) => [...word].length >= PATTERN_CHARS);
const WALKS = pieces([...KEYBOARD_ROWS, ...KEYBOARD_COLUMNS, "abcdefghijklmnopqrstuvwxyz"], PATTERN_CHARS);
const DIGITS_IN_ORDER = pieces(["0123456789"], PATTERN_CHARS);
const DATE = /\p{Nd}{1,2}[./-]\p{Nd}{1,2}[./-]\p{Nd}{2}/u;
const APPLE_SHAPE = /^[A-Za-z0-9]{6}-[A-Za-z0-9]{6}-[A-Za-z0-9]{6}$/;
const SPACE = /[\p{Z}\t\n\v\f\r]/u;

/** The runs of characters (code points) of `chars` that `keep` keeps (`_runs`). */
function runs(chars: string[], keep: (char: string) => boolean): string[][] {
  const found: string[][] = [];
  let current: string[] = [];
  for (const char of chars) {
    if (keep(char)) {
      current.push(char);
      continue;
    }
    if (current.length) found.push(current);
    current = [];
  }
  if (current.length) found.push(current);
  return found;
}

/** The letters of `chars` are lower case, upper case or capitalised, as people type a word (`_plain_case`). */
function plainCase(chars: string[]): boolean {
  const letters = chars.filter((char) => LETTER.test(char));
  return (
    letters.every((char) => LOWER.test(char)) ||
    letters.every((char) => UPPER.test(char)) ||
    (UPPER.test(letters[0]!) && letters.slice(1).every((char) => LOWER.test(char)))
  );
}

/** One of `found` is in `lowered` (`chars` in lower case, character by character) where `chars`' letters are in plain case (`_spelled`). */
function spelled(lowered: string[], chars: string[], found: string[]): boolean {
  const text = lowered.join("");
  // which character starts at each UTF-16 offset of `text` (a piece found starts at one)
  const start = new Map<number, number>();
  let offset = 0;
  lowered.forEach((char, index) => {
    start.set(offset, index);
    offset += char.length;
  });
  for (const piece of found) {
    const length = [...piece].length;
    for (let at = text.indexOf(piece); at >= 0; at = text.indexOf(piece, at + 1)) {
      const index = start.get(at);
      if (index !== undefined && plainCase(chars.slice(index, index + length))) return true;
    }
  }
  return false;
}

/** `part` can be a word (`_word`): at least {@link WORD_LETTERS} letters, lower case or capitalised, with a vowel. */
function isWord(part: string): boolean {
  const chars = [...part];
  const shaped = chars.every((char) => LOWER.test(char)) || (UPPER.test(chars[0]!) && chars.slice(1).every((char) => LOWER.test(char)));
  return chars.length >= WORD_LETTERS && shaped && chars.some((char) => VOWELS.includes(char.toLowerCase().normalize("NFD")[0]!));
}

/** The words of `chars`: the parts of each run of letters that is made only of words (`_words`). */
function words(chars: string[]): string[] {
  const found: string[] = [];
  for (const run of runs(chars, (char) => LETTER.test(char))) {
    const parts = passphraseTokens(run.join(""));
    if (parts.every(isWord)) found.push(...parts);
  }
  return found;
}

/**
 * The first pattern people make that `passphrase` shows (`ordnung.passphrase.human_pattern`; null: none): "a very
 * common word", "a year or a date", "five digits in a row", "a run or a keyboard walk", "a repeat" or "words".
 */
export function humanPattern(passphrase: string): string | null {
  const chars = [...passphrase.normalize("NFC")];
  // lower case character by character, so a piece found lies where it lies in the text
  const lowered = chars.map((char) => {
    const lower = char.toLowerCase();
    return [...lower].length === 1 ? lower : char;
  });
  const unleet = lowered.map((char) => LEETSPEAK[char] ?? char);
  if (spelled(lowered, chars, PATTERN_WORDS) || spelled(unleet, chars, PATTERN_WORDS)) return "a very common word";
  const digitRuns = runs(chars, (char) => DIGIT.test(char));
  const years = digitRuns.some((run) => run.some((_, at) => at + 4 <= run.length && ["19", "20"].includes(run.slice(at, at + 2).join(""))));
  if (years || DATE.test(chars.join(""))) return "a year or a date";
  if (digitRuns.some((run) => run.length >= DIGIT_RUN_CHARS)) return "five digits in a row";
  const digits = digitRuns.map((run) => run.join("")).join("");
  let again = false;
  for (let at = 0; at + PATTERN_CHARS <= chars.length; at++) {
    if (new Set(lowered.slice(at, at + PATTERN_CHARS)).size === 1 && plainCase(chars.slice(at, at + PATTERN_CHARS))) again = true;
  }
  if (again || spelled(lowered, chars, WALKS) || DIGITS_IN_ORDER.some((piece) => digits.includes(piece))) return "a run or a keyboard walk";
  const grams = new Set<string>();
  for (let at = 0; at + PATTERN_CHARS <= lowered.length; at++) {
    const gram = lowered.slice(at, at + PATTERN_CHARS).join("");
    if (grams.has(gram)) return "a repeat";
    grams.add(gram);
  }
  const found = words(chars);
  const long = found.filter((word) => [...word].length >= PATTERN_CHARS);
  const longLetters = long.reduce((sum, word) => sum + [...word].length, 0);
  if (long.length >= 2 || found.length >= 3 || longLetters >= WORDS_SHARE * chars.length) return "words";
  return null;
}

/**
 * The random characters' count of a passphrase in bits (`ordnung.passphrase.random_bits`): its length times log2 of
 * the alphabet it uses — 0 below {@link RANDOM_MIN_CHARS} characters, with a space, or with a pattern people make.
 */
export function randomBits(passphrase: string): number {
  const chars = [...passphrase.normalize("NFC")];
  if (chars.length < RANDOM_MIN_CHARS || chars.some((char) => SPACE.test(char)) || humanPattern(passphrase) !== null) return 0;
  const alphabet =
    (chars.some((char) => LOWER.test(char)) ? LOWER_ALPHABET : 0) +
    (chars.some((char) => UPPER.test(char)) ? UPPER_ALPHABET : 0) +
    (chars.some((char) => DIGIT.test(char)) ? DIGIT_ALPHABET : 0) +
    (chars.some((char) => !(LOWER.test(char) || UPPER.test(char) || DIGIT.test(char))) ? OTHER_ALPHABET : 0);
  return chars.length * Math.log2(alphabet);
}

/** `passphrase` has the shape of Apple's strong passwords, "kuvGis-hihvo6-quzbyc" (`ordnung.passphrase.apple_password`). */
export function applePassword(passphrase: string): boolean {
  if (!APPLE_SHAPE.test(passphrase)) return false;
  if ((passphrase.match(/[A-Z]/g) ?? []).length !== 1 || (passphrase.match(/[0-9]/g) ?? []).length !== 1) return false;
  return passphrase
    .toLowerCase()
    .split("-")
    .every((group) => [...group].every((char, at) => (/[0-9]/.test(char) ? at === 0 || at === 5 : VOWELS.includes(char) === (at === 1 || at === 4))));
}

/**
 * The estimated entropy of a passphrase in bits (`ordnung.passphrase.passphrase_bits`): the larger of
 * {@link wordBits} and {@link randomBits}, or {@link APPLE_PASSWORD_BITS} for one of Apple's strong passwords.
 */
export function passphraseBits(passphrase: string): number {
  return Math.max(wordBits(passphrase), randomBits(passphrase), applePassword(passphrase) ? APPLE_PASSWORD_BITS : 0);
}

/** Strong enough for a new backup or sync folder (a hair below 70 from floating point still counts, as in Python's sum). */
export function strongEnough(passphrase: string): boolean {
  return passphraseBits(passphrase) >= MIN_PASSPHRASE_BITS - 1e-9;
}

/** How many more words of three or more letters would make the passphrase strong enough (0: it is). */
export function wordsShort(passphrase: string): number {
  return Math.max(0, Math.ceil((MIN_PASSPHRASE_BITS - passphraseBits(passphrase) - 1e-9) / TOKEN_BITS_MAX));
}

/**
 * The strength said under a new passphrase while it is typed: `enough` once it is strong enough and has `minChars`
 * characters (null: nothing typed yet).
 */
export function passphraseStrength(passphrase: string, enough: string, minChars: number): { tone: "ok" | "warn"; text: string } | null {
  if (!passphrase) return null;
  const short = wordsShort(passphrase);
  if (!short && [...passphrase].length >= minChars) return { tone: "ok", text: enough };
  if (!short) return { tone: "warn", text: `Strong words — now at least ${minChars} characters in all.` };
  return { tone: "warn", text: `Too easy to guess yet: add ${short === 1 ? "one more word" : `${short} more words`} that don't belong together (three letters or more each).` };
}

/** Easy to say and type: consonants and vowels that can't be mistaken for one another when read aloud. */
const SUGGEST_CONSONANTS = "bdfgjklmnprstvz";
const SUGGEST_VOWELS = "aeiou";

/** One letter of `alphabet`, drawn from `bytes` without modulo bias (null: this byte was rejected). */
function draw(alphabet: string, byte: number): string | null {
  const limit = 256 - (256 % alphabet.length);
  return byte < limit ? alphabet[byte % alphabet.length]! : null;
}

/** How many times the random numbers are drawn for one suggestion at most (a word is 5 of 32 bytes). */
const MAX_DRAWS = 64;

/**
 * A random passphrase of {@link SUGGESTED_WORDS} made-up words like `kirun-bodaf-sumel-tavok-perin`, made in the
 * browser with the system's random numbers: each word is consonant-vowel-consonant-vowel-consonant (log2(15³ · 5²) ≈
 * 16.4 bits, about 82 in all). A word drawn twice, or one the estimator counts less (a common word), is drawn again,
 * so the estimator counts each — five distinct words of five letters are exactly strong enough.
 */
export function suggestPassphrase(random: (bytes: Uint8Array) => Uint8Array = (b) => crypto.getRandomValues(b)): string {
  const words: string[] = [];
  let word = "";
  for (let draws = 0; words.length < SUGGESTED_WORDS; draws++) {
    if (draws >= MAX_DRAWS) throw new Error("The system's random numbers keep repeating, so no passphrase can be suggested.");
    for (const byte of random(new Uint8Array(32))) {
      const letter = draw(word.length % 2 === 0 ? SUGGEST_CONSONANTS : SUGGEST_VOWELS, byte);
      if (letter === null) continue;
      word += letter;
      if (word.length < 5) continue;
      if (!words.includes(word) && tokenBits(word) >= TOKEN_BITS_MAX) words.push(word);
      word = "";
      if (words.length === SUGGESTED_WORDS) break;
    }
  }
  return words.join("-");
}
