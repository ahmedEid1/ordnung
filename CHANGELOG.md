# Changelog

What changed in each version of Ordnung, newest first. `ordnung --version` shows the one you have, and
[Updating](README.md#updating) says how to get the newest.

## Unreleased

### Added

- **Whose number it is.** A number from a letter you filed for someone in your household is listed under *About
  Alex Rivera* on My numbers, whose first tab is then *People*. A number that letters for two of you show says
  "Also on letters for Alex Rivera — check whose it is", and a sender's numbers or a case that are only theirs
  say *For Alex Rivera*. On a paired phone their numbers show only their last 4 characters, like yours.
- **Ask, the Ideas, your reminders and the Timeline say whose it is.** Ask is told who is in your household,
  which letters you filed for whom and whose each number is; letters you keep private stay out. An Idea about
  their letters names them (*Alex Rivera's passport expires …*, *For Alex Rivera: …*), unless you keep one of
  them private; filing a letter later renames the same Idea, so *Not relevant* or *Remind me in a week* still
  holds. The calendar file, calendar sync *With details* and the morning notification *With details* put their
  name in front of a to-do of their letter; *Discreet* never names anyone. On the Timeline, a date from their
  letter says *For Alex Rivera ·*, as Today does. Ordnung still files a letter only when you say so
  ([ADR 0025](docs/decisions/0025-ask-and-the-ideas-say-whose-it-is.md)).
- **Ask knows how your dates repeat.** For a to-do or date that repeats, Ask is told how, in the words the app
  uses (*every month on the 3rd working day*), and the date it moves on to once you mark this one done — also for
  a date you moved by hand, whose schedule carries on after it. A rent a later rent replaces says from which
  month.
- **Text in pictures can be turned off in Settings.** Settings → Data → *Text in pictures* turns off reading the
  words in photos and scans Claude isn't reading. It counts at once: a reading under way stops and the words
  read before are deleted; turned on again, Ordnung starts reading and looks for Tesseract afresh. The card says
  what this computer does: reading, with Tesseract's version; not installed, with the line to install it; or
  turned off by `ORDNUNG_OCR=off`, which still wins on that computer. With hand-off sync the switch travels with
  your settings.

### Changed

- **Ask and *Weekly Ideas* follow your *For taxes* choice.** A letter you took off your letters for taxes no
  longer reaches them as one for taxes, and Ask no longer gets Claude's note on why it could matter for your tax
  return; a letter you marked yourself reaches them as one for taxes, and Ask is told you marked it. Letters you
  keep private stay private: neither sees anything of them, your choice included.
- `ordnung doctor` marks a row that is neither fine nor a problem as info (`i`): Tesseract not installed, text
  in pictures turned off, and on Windows a new *Disk encryption* row that says where to check BitLocker or
  Device encryption, which Ordnung can't read there. An info row never fails the check, and its fix is printed
  as an *Optional —* tip.
- A file of a type Ordnung doesn't read is refused with a message that names Outlook's `.msg` among the types it
  takes.
- In the demo, adding someone to your household or marking a letter for taxes makes the suggested questions'
  recorded answers stop fitting, as changing a letter does; Ask says how to start the demo over.

### Fixed

- *Renew your passport before extending your residence permit* pairs a passport and a residence permit of the
  same person, and the student permit card reads only your own residence permit: a letter filed for someone of
  your household no longer counts as yours there.
- An Outlook e-mail or older Office file is never taken for a PDF, even one with a PDF in its first bytes: if it
  reaches the reading without being opened as an e-mail, Ordnung says what it is and how to add it.
- Screen readers and voice control: the names of links and buttons hold the words they show, in the order shown
  (WCAG 2.5.3, *Label in Name*). The Inbox link is "Inbox 4 — 1 letter to check, 3 not read yet"; it was
  "Inbox, 1 letter to check, 3 not read yet". Your name in the sidebar, the buttons that open a sender's details,
  Ask's sources and *Mark done* under a letter's *Probably dealt with* now name all the words they show, and the
  tour's slim bar and Settings' rule topics no longer run two words together ("4You"). Each still says
  everything it said before.
- The demo tour on a narrow phone: when a step's card shows *Show me the Ideas* or another long button, that
  button and *Back* move to a line of their own instead of lying over the step dots, so tapping a dot goes to
  that step.

### Upgrading

- A computer still on 0.3.0 shows every number as yours and the Ideas' titles without names, and Ideas it
  refreshes lose the name until an updated computer refreshes them. Update both computers.
- A computer still on 0.3.0 doesn't know the *Text in pictures* switch: it reads pictures as its `ORDNUNG_OCR`
  says, and the settings it saves leave the switch out. An updated computer that then receives them by hand-off
  sync keeps its own choice.

## 0.3.0 — 2026-10-29

The second numbered release. [Updating](README.md#updating) says how to install it; *Upgrading* below says
what a computer still on 0.2.0 does with what this version adds, if you use hand-off sync between the two.

### Added

- **Dates you add yourself can repeat.** *Add a date* has a *Repeats* choice: every week or every 2 weeks on
  its weekday, every month on its day, every month on a working day (the 3rd, the last …), every 3 or 6
  months, or every year. A repeating date shows its next day, moves on when you mark it done or once its day
  has passed, and is never overdue because a week or a month went by. Your own dates can be edited later:
  choose *Edit* on the letter's page, or open one without a letter from Timeline. When you change the day of
  one that repeats, you choose whether only that one moves or every one after it (one on a working day moves
  alone); *Remove* stops it, with Undo.
- **A letter addressed to someone else says so.** When a letter names someone other than you (your partner,
  your child, "Familie …"), its page shows *Addressed to …* under its title. A reply, objection, template
  letter or cancellation you write from it still starts in your name: its *From* field says who the letter
  was addressed to, and one press (*Reply in Alex Rivera's name*) fills in that name; *Use my name* goes
  back. The letter's sender block, signature, PDF and proof of sending then use it, and so does a name you
  type into the letter's *From* later. Ordnung doesn't add the name to what it sends Claude, but the related
  letter's title and summary, sent as read, often name the person it was addressed to. Everything else about
  the letter stays yours: its dates, reminders and numbers.
- **Ordnung reminds you to back up, and says what to do if your computer is lost.** It now notes every
  encrypted backup — from Settings → Data, from `ordnung backup` (a scheduled one too) and the backup a
  restored copy came from — and Settings → Data says when the last one was made. When it is more than 30 days
  old, or there is none, the weekly review ends by saying so. A backup from Settings counts once your
  browser has received it, also if you then cancel saving the file. While hand-off sync is connected, its
  copy in your sync folder counts too, because your sync tool copies that folder elsewhere (Ordnung can't
  check that it does); backups of the whole computer (Time Machine, File History) don't, because Ordnung
  can't see them. `ordnung doctor` (and *Run check* in Settings) adds two checks that only ever warn:
  your last backup and, on macOS and Linux, whether the disk under the data folder is encrypted (FileVault,
  LUKS, as a best effort). [docs/privacy.md](docs/privacy.md#if-your-computer-is-lost-or-stolen) has a
  checklist for a lost or stolen computer: before, a backup and disk encryption (BitLocker or Device
  encryption on Windows); after, restore your backup, a new sync folder with a new passphrase, sign out of
  Claude, your phones and the calendar.
- **Ordnung suggests a sender's state from the postcode on their letter.** A sender's state decides which
  public holidays move the dates of their letters; until you set it, Ordnung counts only nationwide
  holidays, so a date can come out a day or two early, or a day late when it is counted backwards from an
  event (its *Why this date?* then says to act a working day before it). Now it asks *Is X in Bavaria?*
  with the postcode it read, in the sender's details, and on the letter and in Today's Ideas when one of
  their dates may change. It never sets the state without you: *Yes* sets it (with Undo), *Don't know*
  leaves their dates as counted without it
  ([ADR 0019](docs/decisions/0019-a-sender-s-land-is-suggested-never-set.md)). The lookup runs on your
  computer. Postcode data © GeoNames, CC BY 4.0.
- **Your tax year, and your letters as files.** *Inbox → Letters for taxes* lists the letters that could
  matter for a year's tax return, by the date on the letter (else the day it arrived) and grouped by kind,
  each with Claude's note on why, then the ones dated January–May of the next year, when yearly statements
  such as the *Lohnsteuerbescheinigung* usually arrive: check which year each is for. Today's tax-season
  Idea (*Your 2025 tax documents are ready to collect*) now opens it, and so does a letter's tax note.
  *Export letters* (Settings → Data, or *Export these letters…* on a tax year) downloads your letters'
  original files as one ZIP, in folders by year and sender
  (`2025/Finanzamt Musterstadt/2025-03-14 Steuerbescheid 2025.pdf`), with `index.csv` for a spreadsheet.
  It runs only when you click it, on your computer, never from a phone, and it writes and sends nothing.
  The ZIP isn't encrypted: anyone who has it can read the letters, so keep it safe.
- **Scans you keep private, or add while Claude isn't connected, can be found by their words.** Many
  scanners and phone apps save a "searchable PDF": a picture of the page with the scanner's own reading of
  it as hidden text. Ordnung never takes that text for the letter's words (it reads the picture, and checks
  what it read against the paper), and until now it threw the text away, so such a scan was found only by
  its file name. Now the scanner's text is kept with the letter's page images for search only: a letter
  found that way says *Found in your scanner's text — not checked*, and its page says what that text is
  for. It is never shown as the letter's words, never used to check a date or an amount, and never sent to
  Claude; Ask doesn't search it. Once Claude has read a page, that page's scanner text is removed. Scans
  you added before are caught up in the background after the update
  ([ADR 0020](docs/decisions/0020-a-scanner-s-text-is-for-finding-not-reading.md)).
- **A moving checklist.** Tell Ordnung you moved in Settings → Profile: tick *I moved* as you change your
  address there, or, if you saved the new address already, choose *Moved recently? Start the moving
  checklist* and enter the address before. Today then lists who needs your new address: first,
  registering at the citizens' office (Bürgeramt) within two weeks of moving in (§ 17 Abs. 1 BMG); then
  the organisations Ordnung knows from your contracts and letters — your bank, insurers, employer,
  landlord, utilities and others — each with the new-address letter one click away (your old address and
  the day filled in); and the broadcasting fee office, when it isn't among them. Tick a row off, or mark
  it *Not needed*, with Undo; a sender's row goes by itself once you mark a new-address letter to them as
  sent. The checklist is for a move in the last six months or the next three, ends six months after the
  move, and *Stop the checklist* ends it at once. Nothing is sent for you, and no row names an address
  ([ADR 0021](docs/decisions/0021-a-move-is-said-never-guessed.md)).
- **Open Ordnung from your app menu.** `ordnung shortcut` adds Ordnung to your app menu on Linux, to the
  Applications folder in your home folder on a Mac (Launchpad and Spotlight find it), or to the Start menu on
  Windows. Opening it signs your browser in. When Ordnung isn't running, it starts in a window of its own, and
  closing that window stops it. Ordnung is never started without a window you can see. When it already runs
  (for example from start at login), only the browser opens. `ordnung shortcut` prints what it writes before
  writing, needs no admin rights and never replaces or removes a file it didn't write; `--dry-run` only
  prints, and `ordnung shortcut --remove` takes it out again. Settings → Reminders shows whether it is there,
  and for which data folder. It also says when the command has to run again (Ordnung was installed somewhere
  else), and when a launcher Ordnung didn't write is in the way. The demo isn't added: it opens with
  `ordnung demo`.
- **E-mails saved from Outlook.** Ordnung now takes the `.msg` file Outlook saves (an e-mail dragged to the
  desktop, or saved with *Save as*) wherever it takes an `.eml`: *Add letters*, your phone, the watched folder,
  `ordnung add` and proof of a sent letter. It opens the file on your computer and keeps the e-mail as an
  `.eml` copy named like the file, with its sender, date, subject and text; every attached PDF or photo
  becomes a letter of its own. The `.msg` itself isn't kept, so what only Outlook has (categories, flags,
  formatting) is lost: keep the file if you need it. The same file always makes the same copy, so adding it
  twice finds it already in Ordnung. Signed or encrypted e-mails, calendar entries, contacts and tasks are
  refused with the reason, and an e-mail whose text Outlook kept only as RTF comes in without its text (its
  attachments still come in). Before, an Outlook file was refused (the watched folder left it alone), or taken
  for a PDF when an attached PDF came first in it.
- **Mark any letter for taxes yourself.** A letter's page has a *For taxes* button: press it to add the letter
  to your letters for taxes, or to take one Claude marked off them — private letters too, and on your phone,
  with Undo. Your choice stays when the letter is read again; the Tax year page, *Export letters* with *Only
  letters for taxes*, the tax-season Idea and the weekly review's *Keep it with your tax papers* follow it. Ask
  and *Weekly Ideas* still see Claude's own mark on each letter; the tax-season Idea, whose title *Weekly
  Ideas* and the daily note send like every Idea's, follows your choice.
- **The Inbox shows one year at a time.** A *Year* choice next to the kind of letter shows the letters dated
  in that year (else arrived in it), as the Tax year page files them; its *Letters for taxes* link then opens
  that year.
- **Your household.** Add the people whose letters come to you too, such as your partner or your children, in
  Settings → Profile & address (Claude never sees the list). A letter addressed to one of them asks *Is this
  letter for Alex Rivera?* — one press files it, *Change* files it for someone else, and nothing is filed by
  itself ([ADR 0023](docs/decisions/0023-letters-for-your-household-are-suggested-never-filed.md)). The Inbox
  shows one person's letters and files the ones addressed to them at once (*File these 3 for Alex Rivera*);
  Inbox and Today rows say whose letter it is; a reply to their letter can go out in their name when they sign
  their own letters (for a child, it goes out in yours). A paired phone can file letters but not change the
  list, and *Download a copy of your records* holds it. Their letters' dates, reminders and numbers stay yours,
  and Ask and Ideas still treat them as yours.
- **Words in private photos are searchable (optional).** With Tesseract installed, a free program Ordnung
  doesn't install, Ordnung reads the words in the photos and scans Claude isn't reading: kept private, waiting
  from your watched folder or for Claude, or that couldn't be read. Tesseract runs on the computer Ordnung runs
  on, one page at a time at low priority, and nothing is sent anywhere to read a picture. The words are kept
  with the letter's page images for search only: a letter found that way says *Found in text Ordnung read from
  the picture — not checked*, and its page says which of its pages Ordnung read. They are never shown as the
  letter's words, never used to check a date or an amount, and never sent to Claude; Ask doesn't search them.
  Once Claude reads a page, what Ordnung read there is removed. `ordnung doctor` says whether Ordnung found
  Tesseract (*Text in pictures*) and how to install it, and `ORDNUNG_OCR=off` turns it off
  ([ADR 0024](docs/decisions/0024-words-ordnung-reads-in-a-picture-are-for-finding-not-reading.md)).
- **Releases.** A version tag builds the wheel and the source package, checks them, and publishes a GitHub
  Release with this changelog's section. Publishing to PyPI waits until the owner has set it up
  ([docs/releasing.md](docs/releasing.md)): until then a release goes to GitHub only. It uses PyPI's
  Trusted Publishing, so no token is stored anywhere, and a pull request never publishes. On PyPI the
  README's links and pictures point to GitHub. [Updating](README.md#updating) says how to install one release
  by its tag.
- **CI checks more.** It replays the holdout, holdout2 and dev splits too, and the numbers without the
  sender's Land, each gated at the published number (no model calls); its slow checks run in a job of their
  own. Coverage now counts branches and has floors for the whole package, hand-off sync and phone access.
  Weekly, it fails once the rules were last checked against the law more than 90 days ago, and checks that a
  freshly installed Claude Code (the newest, and 2.1.0) still takes every flag Ordnung passes, without
  signing in.
- **The benchmark page pools the three held-out splits** into one table with tighter intervals, and each
  held-out split now also shows how the rest of each letter was read, the adversarial letters and what its one
  recording cost ([docs/evals.md](docs/evals.md)). Scam letters are scored as the app decides too, beside the
  benchmark's looser rule: in the app, an IBAN that only fails its checksum is no scam sign on its own.
- README's Limitations now say that the app's own text is in English only, that Google Calendar and Outlook.com
  get the calendar file rather than live sync, and how much one hand-off sync save can upload on a large library.
- The web app's licence notices ship with it: `THIRD-PARTY-NOTICES.txt`, next to the built app and among
  the package's licence files, names every package and font the app bundles (the Inter and Fraunces
  fonts are under the SIL Open Font License) with its licence text. The package's licence expression now
  names every licence it ships: `MIT AND ISC AND OFL-1.1 AND Bitstream-Vera AND CC-BY-4.0`.
- [SECURITY.md](SECURITY.md) says how to report a security problem privately (where GitHub's private
  reporting is off, a *Security contact* issue form asks for nothing about the problem). A bug report now
  goes through a form that asks for `ordnung --version` and `ordnung doctor` and warns never to attach a
  real letter, and [CONTRIBUTING.md](CONTRIBUTING.md) says how to work on Ordnung.

### Changed

- The sign-in page and the *isn't running* screen say to open Ordnung from your apps if you added it there
  with `ordnung shortcut`, before the commands that start it.
- `ordnung serve` in a terminal suggests `ordnung shortcut` for its data folder while Ordnung isn't in your
  app menu, and `ordnung autostart enable` says you can open the app from there too.
- Settings → Calendar says that Google Calendar and Outlook.com take the calendar file, not calendar sync, and
  *Where do I find these?* lists them with that.
- Windows: the Start-menu shortcut names the Python it runs where Windows' shell reads a shortcut's target (an
  ID list, as Windows' own shortcuts have); before, the shell found no target in it, though it opened it. Run
  `ordnung shortcut` again to rewrite one you added before.
- The web app is built with newer packages (motion 14 among them), CI and the release workflow use version 7
  of GitHub's checkout, setup-node and upload-artifact actions, and Dependabot's weekly pull requests no longer
  ask for labels the repository doesn't have. TypeScript majors wait until the packages that need TypeScript
  take them.
- The release workflow takes the built files from its first job with version 8 of GitHub's download-artifact
  action, which stops the release when a file doesn't match the checksum it was uploaded with.
- Ask no longer goes through every letter to work out the key a question is logged and replayed under when
  nothing in your letters, to-dos, contracts, senders or profile changed since the last question: about 0.1 s
  less per question with 500 letters, more with a bigger archive.
- Faster on a big library and on the phone: Ordnung sends its answers and the web app's files compressed
  (gzip), on the demo about 6 times less data for the answers and 3 times less for the app's files. The letter
  list no longer carries each letter's explanation, key facts, references and bank details; the letter's own
  page loads them, and *Download a copy of your records* still has every letter whole. Live updates, downloads,
  signing in and pairing are never compressed
  ([ADR 0022](docs/decisions/0022-compressed-answers-and-a-lighter-letter-list.md)).
- The online demo is on GitHub Pages, <https://ahmedeid1.github.io/ordnung/>, where anyone can open it
  without an account. It is built again from `main` whenever the web app changes
  (`.github/workflows/demo.yml`, [docs/releasing.md](docs/releasing.md)).

### Fixed

- A to-do added through the API with a working-day rule stayed on the day it was given until that day passed;
  it is now dated by its rule at once.
- A to-do that repeats on a working day ("bis zum 3. Werktag") says so on its letter's page and in the
  sender's details; it said only "every month".
- A letter added while Claude isn't installed, isn't signed in or is too old is found by the words in its
  PDF straight away. Before, only the first such letter was; the others were found by name until Claude
  read them.
- A letter waiting for Claude that you delete for good and add again while Ordnung runs is found by the words
  in its PDF again. Before, only its name found it until Claude read it.
- The Inbox's own search finds the letters waiting from your watched folder, as the search at the top does.
  While you search, *From your folder — not read yet* lists only the ones it found ("1 of 3"), a found e-mail
  with its attachments, one found only in its scanner's text says so, and *Read it* and *Keep private* are
  for the letters listed. Before, the Inbox's search left them out and said no letter matched.
- A password manager's strong random password with capital and small letters now protects a new backup or
  a new sync folder. 0.2.0 counted only words, so symbols and capitals counted nothing and many such
  passwords were refused. Now random characters count by the alphabet they use (14 random letters and
  digits are about 83 bits), unless they show a pattern people make: a common word, also in leetspeak; a
  year or a date, also with `_`, `#` or the like between its parts; a run or a keyboard walk, also typed
  with Shift; a repeat; or words, also in capitals, with caps lock on, in alternating case or in another
  script. A name or a word with digits and symbols ("Max#Richter#94"), also with a stray letter or two
  ("Andreas!88#Xy"), counts as its words and digits, and so does a word spelled in leetspeak
  ("Schm3tt3rl1ng!"). Random small letters alone look like one long word, so they still count as one.
  Apple's strong passwords ("xxxxxx-xxxxxx-xxxxxx") count too. Five unrelated words, and everything that
  passed before, still pass, except words typed with a dotless ı for an i ("Dıe"): they now count as the
  words they are, as the web app already counted them.
- When Claude's usage limit is reached, the time Ordnung says it continues at is in your profile's time zone,
  not the computer's.
- When the weekly review can't write Ideas (Claude didn't answer, or its limit is reached), Settings → Privacy
  & AI usage says so and that Ordnung tries again tomorrow; before, only Ordnung's log did.
- The app no longer has a design-system page at `/dev/ui`; it stays in the demos and in development.
- Closing the terminal window that runs `ordnung serve` (on Windows, its console window) stops Ordnung as
  Ctrl+C does: hand-off sync saves your last changes and hands over, and the sign-in page and `server.json`
  are removed. Before, Ordnung ended at once, and your other computer saw this one as still using it.
- macOS: backups, and the copies hand-off sync keeps, are flushed to the disk itself before Ordnung goes on,
  as its other files are; before, they could still sit in the drive's cache.
- A big library stays quick: the weekly review, and the Ideas worked out again after each letter is read,
  no longer slow down with the square of the number of letters and senders.
- A PDF that hides a decompression bomb behind ASCII85 or ASCIIHex data with a stray character in it is
  refused at upload, as other bombs are. The check read such data strictly and counted nothing, while
  PDFium, which shows the letter, reads it up to (ASCII85) or past (ASCIIHex) that character. The check's
  LZW, RunLength, ASCII85 and ASCIIHex decoding now has tests of its own, compared with PDFium's.
- Windows: the message that another Ordnung process is using the data folder names that process ("pid N:
  ordnung serve"), as on Linux and macOS, and so does restore's.
- Windows: stopping Ordnung, and hand-off sync from the command line when it ends, now wait up to 20 seconds
  for a running sync operation before closing the database, instead of leaving it open. An operation still
  running after that (on a share that stopped answering) may still hold it.
- Windows: once Ordnung has stopped, its database is closed. Hand-off sync's thread, which ends as Ordnung
  stops, could still be closing its connection a moment later, so the data folder couldn't be deleted or
  replaced right away.
- Stopping Ordnung, or handing over to another computer with hand-off sync, while the daily check was at work
  (the day's to-dos and Ideas, calendar sync) didn't wait for that work. It went on after the check had stopped:
  the day's to-dos were no longer kept apart from a letter being read at that moment, and a hand-over could be
  saved before the work ended. Stopping now waits for it, at most 10 seconds.
- When two computers had answered hand-off sync's question (which computer's Ordnung to keep) apart, each
  keeping its own, the question came back, as it should. But keeping the same Ordnung once more didn't settle
  it: the question came back after every such answer. Now the answer given then stands. A computer whose Ordnung
  another computer had already kept, exactly as it is, is no longer asked again.
- An e-mail from a Windows mail program that labels its text ISO-8859-1 but writes "…" or "€" in it is read,
  with the "…" and "€" as written: Ordnung reads that label as Windows-1252, as mail programs and browsers do.
  Before, the "…" became a paragraph separator, and where the text layout has raqm (Linux, as a rule) the
  e-mail couldn't be added: the upload or proof failed with an error, the watched folder only logged it and
  `ordnung add` said *Unexpected error*. Other paragraph separators in an e-mail's text (U+2029, U+0085,
  U+001C–U+001E) start a new line now. Should Pillow's layout fail on anything else, the e-mail is refused
  with a reason at every way in, not with an error.

### Upgrading

- A computer still on 0.2.0 that receives the new question by hand-off sync shows it among its Ideas but
  never takes it away once it no longer applies. Update both computers.
- A computer still on 0.2.0 shows the repeating dates you add on a newer one and moves them on, but can't
  change how they repeat.
- On a computer still on 0.2.0, a letter written in someone else's name prints your name under its signature
  until it is marked as sent. Print such letters on an updated computer.
- A computer still on 0.2.0 shows its own tax-season Idea, whose *See the documents* opens one letter rather
  than the tax year (and it may count the year's letters slightly differently).
- A computer still on 0.2.0 finds a scan only by its name, as before, and deletes its scanner's text with the
  letter. A scan Claude reads there keeps its scanner's text until an updated computer receives it by hand-off
  sync and removes it.
- A computer still on 0.2.0 that receives the moving checklist by hand-off sync shows its rows among its Ideas
  and never takes them away, and saving the profile there forgets the move. Update both computers.
- Outlook e-mails (`.msg`) that were already in your watched folder before the update count as files that
  were there when you chose the folder: they wait for you, also with "Read new files with Claude straight
  away" on.
- Backups made with `ordnung backup` before this version left no note, so Ordnung has no record of them and
  says so until the next one, which counts.
- A script that reads the letter list (`GET /api/documents`) no longer finds `explanation`, `key_facts`,
  `references`, `payment` or `sha256` in its rows: read them from the letter (`GET /api/documents/{id}`), or
  every letter whole from `GET /api/documents.json` on the computer.
- A computer still on 0.2.0 keeps the letters you marked or unmarked for taxes but doesn't use your choices:
  its Tax year page, export and tax-season Idea go by Claude's marks alone, and a letter deleted for good there
  leaves its choice behind (its id and yes or no, nothing of the letter) until you next mark or unmark a letter
  on an updated computer: the same file added again on 0.2.0 meanwhile takes that choice back (on an updated
  computer it starts with none). Update both computers.
- A computer still on 0.2.0 keeps your household and the letters you filed for its people when it receives
  them by hand-off sync or from a backup, but doesn't show them: there every letter is yours, as before. Update
  both computers.
- A letter deleted for good on a computer still on 0.2.0 leaves its filing behind (its id, nothing of the
  letter) until an updated computer in use runs its daily check: the same file added again on 0.2.0 meanwhile
  is filed as before (on an updated computer it starts unfiled).
- Tesseract is optional and Ordnung doesn't install it; `ordnung doctor` gives the line for your system. A
  computer still on 0.2.0 finds a private photo only by its name, as before, and deletes the words Ordnung read
  in it with the letter.

## 0.2.0 — 2026-10-08

The first numbered release. Every install before it reports 0.1.0, the version of the first commit
(2026-09-25), and pip, so also `pipx upgrade`, only replaces an install whose version went up: hence
0.2.0, not 0.1.0.

### Since the first commit

- **Reading letters.** Claude reads a letter, a scan or a photo; tested rules compute every deadline
  (delivery fictions, §§ 187–193 BGB, the holidays of each Land, contract terms, high-stakes letters) with
  citations and *Why this date?*. Code checks quotes and digits, and a check of its own files a to-do when a
  reading left a date out. *How it was read* shows every step.
- **Ask** answers questions about your letters with a citation for each claim, checked against the record.
- **Your secretary:** Today's note, Ideas, the weekly review, Waiting for, My numbers, scam signs, and
  paying by GiroCode behind a safety check.
- **Letters you send:** template letters and bilingual drafts as DIN 5008 PDFs, sending advice, proof of
  sending.
- **One inbox** (a watched folder, e-mail attachments), reminders with a morning notification and
  autostart, calendar export and CalDAV sync, encrypted backups.
- **Your phone at home:** pair it, photograph letters and tick off to-dos over your home Wi-Fi.
- **Hand-off sync** between your computers through a folder you already sync.
- **The rules engine as MCP tools** for Claude Desktop and Claude Code.
- **The demo** (recorded answers, zero tokens) and two benchmarks replayed in CI: reading letters, on a
  test split and three held-out splits, and Ask.

### Fixed

- Updates install: the version now goes up with each release (the Python package reads it from
  `src/ordnung/__init__.py`; tests check that the web app and the demo say the same), and
  [Updating](README.md#updating) says how to update.
- Claude Code setup advice follows Anthropic's installer for each system and names the Claude plans that
  include it. A Claude Code older than 2.1.0 no longer counts as ready: letters wait, and nothing is sent,
  until it is updated.
- *Read again* no longer starts two paid readings of the same letter: while one waits or runs, it gets
  that one.
- Phone access on Windows no longer offers VPN addresses, nor a virtual machine's unless the router is on
  its network; it recommends the address on the router's network, and learns the router later when it
  couldn't read it at turn-on.
- A phone is no longer signed out when two page loads cross the hourly sign-in change.
- A sync folder that stops answering no longer leaves a thread behind on each look: a file that hangs
  is skipped at once until it answers, other files (this computer's own saves too) go on, and at most 4
  calls wait at a time. Until the folder answers, Ordnung looks at it every 3 minutes instead of every
  15 seconds.
- Kept sync copies: forgetting a computer on a full disk is refused for lack of space instead of failing
  with an internal error, and the record of kept copies reaches the disk before it counts. Both now have
  direct tests.
- Backups: a new backup's passphrase must be as strong as a new sync folder's (about 70 bits: five or more
  unrelated words; one Ordnung 0.1.0 suggested still counts), and new backups use sync's key stretching
  (scrypt 2^18, 256 MiB). Older backups still open.
- macOS and Windows: CI runs the code that differs there (the lock, durable writes, sync, phone access,
  autostart, backups) weekly and on main. On macOS a durable write now flushes the drive's cache
  (`F_FULLFSYNC`; it was a plain fsync), and a Windows checkout, also the one `pipx install git+…` makes,
  keeps every file byte for byte, so `ordnung demo` uses its prebuilt database there instead of rebuilding
  it.

### Upgrading

- Follow [Updating](README.md#updating): `pipx reinstall ordnung` (or `uv tool upgrade ordnung`), then
  `ordnung doctor`. With hand-off sync, update both computers.
- Ordnung now needs Claude Code 2.1.0 or newer; `claude update` updates it. Until then letters wait.
- `ordnung backup` and the download in Settings → Data refuse a passphrase under about 70 bits by
  Ordnung's estimate and suggest five made-up words instead. The estimate counts words, so many random
  passwords from a password manager fall short too (symbols don't count); a passphrase Ordnung 0.1.0
  suggested still counts as strong. One a script gives in `ORDNUNG_BACKUP_PASSPHRASE` that falls short only
  gets a warning, so a scheduled backup is still made; change it when you can. Backups made before still
  restore.
- Phone access turned on at a VPN's or a virtual machine's address before keeps listening there: turn it
  off and on again in Settings → Phone, which now offers only home-network addresses (your phones pair
  again).
- A letter keeps the reading it was given. One read before extraction prompt version 9 or 12 lacks what
  those versions added; *Read again* on its page reads it with the current prompt
  ([Limitations](README.md#limitations)).
