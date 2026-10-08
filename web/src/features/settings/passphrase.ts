/**
 * The strength of a new passphrase — a new backup's and a new sync folder's alike: the server's estimator
 * (`src/ordnung/passphrase.py`), counted the same way, and the five made-up words both suggest. The numbers mirrored
 * here are pinned to it by `sync.test.tsx`.
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
const COMMON_WORDS = new Set(COMMON_WORDS_TEXT.split(" "));

/**
 * The tokens {@link passphraseBits} counts (`ordnung.passphrase.passphrase_tokens`): the passphrase in Unicode NFC cut
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
 * The estimated entropy of a passphrase in bits (`ordnung.passphrase.passphrase_bits`): each *distinct* token (compared
 * case-folded) counts its length times log2 26 (letters) or log2 10 (digits), at most {@link TOKEN_BITS_MAX} — a
 * token is at best a word from a large list; a run, a keyboard walk or a repeated character about one character, a
 * very common word 7 bits, and tokens that only make a run together ("a b c d …") that one run. Five unrelated words
 * of three or more letters reach 70.
 */
export function passphraseBits(passphrase: string): number {
  const tokens = passphraseTokens(passphrase).map(casefold);
  const joined = tokens.join("");
  if (tokens.length > 1 && isRun(joined)) return perChar(joined) + 1;
  let bits = 0;
  for (const token of new Set(tokens)) bits += tokenBits(token);
  return bits;
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
const CONSONANTS = "bdfgjklmnprstvz";
const VOWELS = "aeiou";

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
      const letter = draw(word.length % 2 === 0 ? CONSONANTS : VOWELS, byte);
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
