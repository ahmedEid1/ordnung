# Using Ordnung

How to use Ordnung on your own computer, beyond the [README](../README.md): a tour of what it does, how to install,
run and update it, the environment variables it reads, and every limitation. To try it first with no Claude account
and no tokens, open the [online demo](https://ahmedeid1.github.io/ordnung/), or install it and run `ordnung demo`.

[A tour](#a-tour) · [Install and run](#install-and-run) · [Updating](#updating) · [Environment variables](#environment-variables) · [Limitations](#limitations)

## A tour

<table>
<tr>
<td width="50%"><img src="assets/today.png" alt="Today page"><br><b>Today.</b> A secretary's note, the three things that matter this week with countdowns, what's coming, Ideas with reasons, and scam warnings.</td>
<td width="50%"><img src="assets/document.png" alt="A photographed tax assessment with the objection sentence highlighted"><br><b>Every letter.</b> What it is, what to do, by when and what happens if you ignore it. Each fact points to the sentence it came from; this one was read from a phone photo.</td>
</tr>
<tr>
<td><img src="assets/why.png" alt="Why this date? receipt with every rule step"><br><b>Why this date?</b> Every step of the calculation with its rule and citation, and how sure Ordnung is.</td>
<td><img src="assets/court-order.png" alt="A court payment order with its deadline and a get-advice card"><br><b>High-stakes letters.</b> A court payment order, enforcement order, dismissal, landlord's notice, rent increase or operating-cost statement gets the law's own date and a "get advice" card that names free or low-cost help.†</td>
</tr>
<tr>
<td><img src="assets/pay.png" alt="The Pay panel with a GiroCode"><br><b>Pay by scan.</b> For a bank transfer the Pay panel shows a GiroCode (EPC-QR) your banking app scans. Never for a direct debit, a scam or a bill a reminder replaced; a value read from a photo waits until you compare it with the paper.</td>
<td><img src="assets/numbers.png" alt="My numbers"><br><b>My numbers.</b> Your Steuer-ID, social insurance, customer and case numbers from your letters, sorted by whose they are, check digits tested, hidden until you choose <i>Show</i>.</td>
</tr>
<tr>
<td><img src="assets/ask.png" alt="Ask with a checked answer"><br><b>Ask.</b> Answers about your letters, every date and amount checked against the record it cites. Here the fine's amount, read from a photo, stays in quotation marks as the letter's, and a note says so.</td>
<td><img src="assets/week.png" alt="The weekly review, step Pay this week"><br><b>Weekly review.</b> Ten minutes, seven short steps: what's new, what to compare with the paper, pay, post, wait for, decide and file. It ends with "All clear until …" ("All clear for today" when the next thing is due tomorrow) and that next thing, or with what is overdue.</td>
</tr>
<tr>
<td><img src="assets/timeline.png" alt="Timeline with life lanes"><br><b>Timeline.</b> The year ahead as life lanes (permits, contracts, tax, study, work, home), then month by month.</td>
<td><img src="assets/contracts.png" alt="Contracts"><br><b>Contracts.</b> Fixed costs, how each contract ends in plain words, and the last day to post a cancellation.</td>
</tr>
<tr>
<td><img src="assets/proof.png" alt="Proof of sending for a cancellation sent by Einschreiben"><br><b>Letters and proof of sending.</b> Bilingual drafts and DIN 5008 PDFs; an Einschreiben's tracking number is checked, the posting receipt is kept as proof, and <i>Waiting for</i> reminds you when no answer comes.</td>
<td><img src="assets/trace.png" alt="How it was read: the steps of reading a letter"><br><b>How it was read.</b> Every step of a letter's reading: what Claude was asked, what it cost, and what code checked and computed. Exports to OpenTelemetry.</td>
</tr>
<tr>
<td><img src="assets/scam.png" alt="A scam letter flagged"><br><b>Scam and injection defence.</b> Scam signs such as pressure or a payee account abroad flag a letter. Its dates still show on its page and in the warning, but stay off Today, the calendar and the notification until you choose <i>I checked — it's genuine</i>; it never gets a GiroCode. Text hidden in a PDF and instructions aimed at an AI are shown, never followed.</td>
<td><img src="assets/today-dark.png" alt="Today in dark mode"><br><b>Light and dark.</b> Both themes have no serious or critical violations of axe 4.14's WCAG 2.2 AA rules, with one documented exemption (the page image's highlight buttons: WCAG 2.5.8's "equivalent" exception), and every page works from 320 px wide up (below); CI checks both.</td>
</tr>
<tr>
<td><img src="assets/pair-phone.png" alt="Pairing a phone: on the computer, a QR code and a pairing code; on the phone, once paired, two check words; on the computer, the same two words"><br><b>Your phone at home.</b> Settings → Phone shows a QR code for the phone's camera. Once the phone pairs, both screens show the same two words, so you know the phone that paired is yours. Then it opens Ordnung in its browser over your home Wi-Fi: photograph a letter, tick off a to-do, read what a letter means. Settings, backups and deleting stay on the computer.‡</td>
<td><img src="assets/your-computers.png" alt="Settings, Your computers: this computer, sam-desktop, is in use and saved to the sync folder; the other, sam-laptop, is standing by and has the latest changes"><br><b>Your computers.</b> Optional: Ordnung moves between your laptop and your desktop through a folder your own sync tool keeps in step (Nextcloud, Syncthing, Dropbox, iCloud Drive), and only encrypted files go there. One computer is in use at a time; on the other, <i>Use Ordnung here</i> brings everything over. Nothing is merged.‡</td>
</tr>
</table>

<p align="center">
  <img src="assets/mobile.png" width="30%" alt="Today on a phone">
  &nbsp;
  <img src="assets/mobile-dark.png" width="30%" alt="The tax assessment on a phone in dark mode">
</p>

† The recorded demo has no court letter, so this picture (and the court order in the tour) comes from
the app's mock data, the browser-only demo's, opened with `?mock=full`: a hand-written sample letter
whose date, "Why this date?" and advice card are generated by the rules engine
([`scripts/gen_mock_high_stakes.py`](../scripts/gen_mock_high_stakes.py),
[`scripts/gen_mock_advice.py`](../scripts/gen_mock_advice.py)). Everything else, apart from the two pictures
marked ‡, is `ordnung demo`. The mock data is a different sample life, and the tab keeps it (a banner says so)
until you open `?mock=0`.

‡ The demo opens itself to no network and syncs nowhere, so these two pictures come from the real app
(`ordnung serve`) on throwaway data folders, made the way the browser tests run it
([`web/e2e/readme-pictures.spec.ts`](../web/e2e/readme-pictures.spec.ts), part of `make capture`). The phone is
Chromium emulating a Pixel 7 on the same computer, so its address shows as 127.0.0.1 (at home it is your
phone's address on your Wi-Fi), and a stand-in for the sync tool copies the folder between the two
computers; the picture shows a typical path for that folder instead of its temporary one. The phone picture
puts three moments side by side: the code, the paired phone, and the computer once it paired.

**Also:** *one inbox* — a watched folder for your scanner or phone app, and e-mails (`.eml`, or Outlook's
`.msg`) whose PDF and photo attachments become letters; new files wait on your computer until you choose
*Read these* or *Keep private* · *template letters* — withdrawal, more time, instalments, defect notice, GDPR access,
inspecting receipts, deposit back, new address · *reminders* — calendar export with alarms, a morning
desktop notification (discreet by default) while the browser is closed, start at login, optional sync
with your own CalDAV calendar · *app-menu shortcut* — open Ordnung from your app menu, Start menu or
Applications folder, signed in, without a terminal · *encrypted backup* in one file (AES-256-GCM, under a passphrase of five
or more unrelated words, or a password manager's random password with capital and small letters) with a
restore that checks every byte · *tax year* — a year's letters for your tax return, by the date on them;
mark or unmark any letter yourself, and the Inbox shows one year at a time · *your household* — file a letter
for your partner or your child when Ordnung asks (it never files one by itself), find their letters, see their
numbers on My numbers and whose a date is on Today and the Timeline, and reply in their name when they sign
their own · *export letters* — your originals as files in folders by year and
sender, with a list for a spreadsheet · *moving checklist* — who needs your new address, from your contracts and letters, starting with the
Bürgeramt's two weeks · *call notes* — *Note a call* in a person's or an organisation's drawer, or on an overdue
reply or promise under *Waiting for*, keeps when you called, with whom, what was said and what was promised, with
a day and an amount; a promise with a day is waited for under *Waiting for*, and *They kept it* is your click;
no AI reads it · *Claude Desktop and Claude Code* can use the deadline engine as MCP tools.

## Install and run

You need Git, [uv](https://docs.astral.sh/uv/) or pipx, Python 3.11 or newer (CI tests 3.11–3.14) and, to read
your own letters, Claude Code 2.1.0 or newer, signed in with a paid Claude plan (Pro, Max, Team or Enterprise) or
an Anthropic Console account; the free Claude plan doesn't include Claude Code. Install
[Claude Code](https://claude.com/claude-code)
with Anthropic's installer — `curl -fsSL https://claude.ai/install.sh | bash` on macOS and Linux,
`irm https://claude.ai/install.ps1 | iex` in Windows PowerShell; other ways are in its
[setup guide](https://code.claude.com/docs/en/setup) — and run `claude` once to sign in. Installed this
way it updates itself; `claude update` updates it at once. Ordnung calls it in headless mode; there is
nothing else to configure. Without Claude you can still store letters privately, find them by name or by the
text in the file (a PDF's own text, or the text a scanner added to a scan — kept for search only, never checked
or sent to Claude; a photo by its name, and by the words Ordnung reads in it when Tesseract is installed, kept
the same way) and add your own dates (Timeline → Add a date, or on a letter's page), also ones that repeat. A
letter added while Claude isn't installed, isn't signed in or is older than 2.1.0 waits (*Waiting for Claude*)
instead of failing, and is read once Claude is ready, without a restart; meanwhile search finds it by the words
in its PDF. CI tests Ordnung on Linux, with a real Tesseract for text in pictures. A CI job on macOS and
Windows (weekly and on main, required to pass) installs Ordnung, checks the demo and `ordnung doctor`,
and runs the tests of the code that differs there: the data-folder lock, durable writes, hand-off sync, phone
access's network lookups and certificates, autostart entries, app-menu shortcuts, backups and text in pictures
(looking for Tesseract, which isn't installed there). The other tests, desktop notifications, starting at a
real login, and phone access and sync between real devices are not tested on macOS or Windows.

```bash
uv tool install git+https://github.com/ahmedEid1/ordnung   # or: pipx install git+https://github.com/ahmedEid1/ordnung; the built web app is included
ordnung doctor                  # checks Claude, search, fonts, text in pictures, your data folder and database, your last backup, disk encryption
ordnung serve                   # the web app on http://127.0.0.1:8765
ordnung shortcut                # Ordnung in your app menu: opens it signed in, no terminal needed
ordnung add ~/Downloads/*.pdf   # or drag files into the app
ordnung brief                   # today's note in the terminal
ordnung ask "When can I cancel my phone contract?"
ordnung autostart enable        # start at login; then switch on the morning notification in Settings → Reminders
ordnung backup --to /media/usb  # everything in one encrypted file; `ordnung restore FILE` brings it back
```

`ordnung add` exits with 1 when a letter couldn't be read, or waits for Claude: to be installed, signed
in or updated, or for its usage limit to pass (it is stored and read once Claude is ready).

Ask's recorded answers fit the demo as it starts. After you mark things paid or done, Ask says so and
offers *Start the demo over*, so you can ask again: stop the demo (Ctrl+C where it runs), then run
`ordnung demo --reset`.

**Words in photos (optional).** To find photos and scans Claude isn't reading (kept private, waiting, or that
couldn't be read) by their words, install Tesseract 4.1 or newer with its German language data. Ordnung doesn't
install it; `ordnung doctor` says whether it found it (*Text in pictures*) and gives the same line for your
system:

- Linux: `sudo apt install tesseract-ocr tesseract-ocr-deu` (Fedora:
  `sudo dnf install tesseract tesseract-langpack-deu`), then restart Ordnung.
- macOS: `brew install tesseract tesseract-lang`, then restart Ordnung.
- Windows: the installer from https://github.com/UB-Mannheim/tesseract/wiki, with German ticked under
  “Additional language data”, then restart Ordnung.

Tesseract runs on the computer Ordnung runs on, one page at a time at low priority: nothing is sent anywhere
to read a picture. The words are kept for your letter search only, marked *not checked*, and are never shown,
checked or sent to Claude
([ADR 0024](decisions/0024-words-ordnung-reads-in-a-picture-are-for-finding-not-reading.md)).
Settings → Data → *Text in pictures* turns it off and deletes the words read before; `ORDNUNG_OCR=off` turns it
off on one computer ([how](privacy.md#words-in-pictures-optional)).

**Without a terminal.** `ordnung shortcut` puts Ordnung where your computer keeps its apps: an entry in
your app menu on Linux, `Ordnung.app` in the Applications folder of your home folder on a Mac (Launchpad,
Spotlight and the Dock take it), or a shortcut in your Start menu on Windows. It prints what it writes, and
where, before writing anything, and needs no admin rights; `--dry-run` only prints. Opening it signs your
browser in. When Ordnung isn't running, it starts in a window of its own, and closing that window stops
Ordnung; when it already runs (for example because it starts at login), only the browser opens, after a
terminal window flashes on Linux and Windows. Ordnung is never started without a window you can see. The
shortcut opens the data folder it was added for. On Linux and macOS it records this terminal's `PATH`, as
start at login does, so Ordnung finds the same `claude` and Tesseract: run `ordnung shortcut` again after
moving Claude Code. `ordnung shortcut --remove` takes it out again. It never replaces or removes a file it
didn't write, and it doesn't add the demo, which opens with `ordnung demo`.

- **Linux:** the entry asks your desktop for a terminal window to run in. GNOME, KDE and most desktops
  have one; on a desktop without a terminal it knows (some minimal window managers), opening the entry
  does nothing visible: start Ordnung with `ordnung serve` there.
- **macOS:** Launchpad and Spotlight can take a moment to list the new app. It is made on your Mac and
  isn't signed; macOS warns about an unidentified developer only for apps downloaded from the internet.
  When Ordnung isn't running, the app opens a Terminal window that runs Ordnung, and Terminal asks before
  you close that window while Ordnung runs.
- **Windows:** right-click it in the Start menu to pin it to the taskbar. A shortcut can't carry
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` or `ORDNUNG_OCR`: when one is set in your terminal,
  `ordnung shortcut` prints the `setx` command that sets it for your account.

CI's job on macOS and Windows tests the files the shortcut writes there, and on Windows that the shell
reads its target and opens it; opening it from the desktop's own menu isn't tested on any system.

**On your phone.** With Ordnung running on your computer, open Settings → Phone, turn on phone access and
choose *Pair a phone*: scan the QR code with the phone's camera (or type the address and the code). The
phone warns once that the connection isn't private, because Ordnung made its own certificate; the
pairing dialog shows its fingerprint, so you can check that it is your computer answering. Your
computer's firewall may ask whether Python may accept connections: allow it on private networks only
(the dialog's *Phone can't connect?* has the narrowest rule for each system). The phone must be on the
same Wi-Fi as the computer, and not on a guest network: guest networks keep devices apart. Then Ordnung
opens in the phone's browser: photograph a letter page by page, see what's due, tick things off, pay by
copying the details or saving the GiroCode as a picture. It works while the computer is on and Ordnung
runs; reserve the computer's address in your router, because a new address means pairing again.
Details: [docs/privacy.md](privacy.md#phone-access-optional) and
[ADR 0017](decisions/0017-phone-access-over-the-home-network.md).

**On your other computer.** Ordnung can move between your laptop and your desktop through a folder your
own sync tool already keeps in step (Nextcloud, Syncthing, Dropbox, iCloud Drive, a network drive). In
Settings → Your computers, choose a new folder inside it, name this computer and take the suggested
five-word passphrase (save it in your password manager). On the other computer, choose *I already use
Ordnung on another computer* when you set Ordnung up, the same folder and the same passphrase. From then on
Ordnung is in use on one computer at a time: the computer in use saves an encrypted copy into the folder a
few seconds after each change, the top bar says when the other computer has it ("Saved · desktop has it"),
and on the other computer one click, *Use Ordnung here*, brings everything over. If both computers changed
something while they couldn't see each other, Ordnung asks once which computer's Ordnung to keep and saves
the other as an encrypted copy. Keep the folder available offline on both computers, and update Ordnung on
both together ([Updating](#updating)). Details:
[docs/privacy.md](privacy.md#hand-off-sync-between-your-computers-optional) and
[ADR 0018](decisions/0018-hand-off-sync-through-a-folder-you-already-sync.md).

```bash
ordnung sync                                     # in use here or standing by, when it last saved, the other computers
ordnung sync connect ~/Nextcloud/Vault           # set up (the passphrase twice) or join (once); ORDNUNG_SYNC_PASSPHRASE skips the prompt
ordnung sync use-here                            # bring everything over and use Ordnung on this computer
ordnung sync choose this                         # both computers changed: keep this one's Ordnung (or the other's name)
ordnung sync save --hand-over                    # save now and stand by, before you switch computers
ordnung sync passphrase | kept | forget NAME | disconnect
```

**The deadline engine in Claude Desktop or Claude Code.** The rules engine also runs as MCP tools with
no data folder and nothing personal: `compute_deadline` (what a letter says → the date, with its legal
steps and citations), `german_holidays`, `add_working_days` and `check_iban`.

```bash
ordnung mcp install --client claude-desktop           # prints the entry and where it goes
ordnung mcp install --client claude-desktop --write   # merges it in (backup first); restart Claude
ordnung mcp install --client claude-code              # the `claude mcp add` command
```

Then ask Claude about a letter; it reads, Ordnung's engine computes. `--with-ledger` also gives the
client your read-only ledger ([what that means](privacy.md#using-ordnung-from-claude-desktop-or-claude-code)),
and `--remove-ledger` takes that entry out again.

**From a source checkout** you also need [uv](https://docs.astral.sh/uv/) and Node.js 20.19+ or 22.12+
(Vite 8 needs one of them; `nvm use` picks the one in `.nvmrc`; the accessibility checker that `make e2e`
and `make ui-audit` use asks for 22.12+). [CONTRIBUTING.md](../CONTRIBUTING.md) has the checks CI runs and
how to send a change:

```bash
make install     # Python venv (the versions CI pins in constraints.txt) + web dependencies
make check       # lint, types, tests
make serve       # backend; `make web-dev` for the Vite dev server
make e2e         # Playwright over the demo and the real app with a fake Claude (installs Playwright's Chromium first: make browser)
make capture     # these screenshots, the tour video and the GIF (needs ffmpeg)
```

### Updating

Each release has a version number (`ordnung --version` shows yours) and an entry in [CHANGELOG.md](../CHANGELOG.md).
Stop Ordnung first (Ctrl+C where `ordnung serve` runs, or close the window the shortcut opened; if it starts at
login, `ordnung autostart disable` prints how to stop it and `ordnung autostart enable` how to start it again).
A backup first lets you go back: an older Ordnung can't open a database a newer one has updated.

```bash
ordnung backup --to /media/usb   # optional: the way back
pipx reinstall ordnung           # installed with uv: uv tool upgrade ordnung
ordnung doctor
```

`pipx reinstall` and `uv tool upgrade` install the newest code from GitHub, which can hold changes no release
has yet; `pipx upgrade ordnung` can keep the old code when the version number didn't change. To install a
release instead, name its tag once it has one:
`pipx install --force "git+https://github.com/ahmedEid1/ordnung@vX.Y.Z"`
(with uv: `uv tool install "git+https://github.com/ahmedEid1/ordnung@vX.Y.Z"`), and a release without a tag by
its commit, taken from the repository's history. An install made from a tag stays on that release when you
reinstall or upgrade it; install the next tag the same way. When a version changes how the database is stored,
Ordnung updates your data folder by itself the next time it starts (each step completes or leaves it as it was).
With hand-off sync, update both computers: until then Settings → Your computers says that the other one runs
another version, and if the database changed, the computer with the older Ordnung can't bring the other's
changes over; it says *Update Ordnung on this computer* and keeps saving its own changes.
If the shortcut stops opening Ordnung after an update (its window closes at once, or nothing opens), the
Python it runs has moved: run `ordnung shortcut` again, and `ordnung autostart enable` too if Ordnung
starts at login.

To go back, install the version you had again by its tag
(`pipx install --force "git+https://github.com/ahmedEid1/ordnung@vX.Y.Z"`, or `uv tool install` with the same
address; a version without a tag by its commit, taken from the repository's history), then
`ordnung restore FILE --force`, which moves the updated data folder aside.

## Environment variables

Ordnung needs none of these; each changes a default on the computer it is set on. *Read in* names the modules under
`src/ordnung/` that read it.

| Variable | What it does | Default | Read in |
|---|---|---|---|
| `ORDNUNG_HOME` | Your data folder. `--data-dir` wins over it | your platform's user data folder ([which](privacy.md#at-a-glance)) | `config.py` |
| `ORDNUNG_DEMO_HOME` | The folder `ordnung demo` keeps its data in; `ordnung demo --data-dir` wins over it. The demo never uses `ORDNUNG_HOME`, so it never touches your data | a separate `ordnung-demo` folder | `demo/loader.py` |
| `ORDNUNG_CLAUDE_BIN` | The Claude Code program Ordnung runs: a name it looks for on your `PATH`, or a path. `ordnung doctor` says when it isn't there | `claude` on your `PATH` | `llm/claude_cli.py`, `doctor.py` |
| `ORDNUNG_CLAUDE_MODEL` | The model every call runs on while it is set, over the one chosen under Settings → Claude connection; that page says so, and the model saved there waits until it is unset | unset | `llm/claude_cli.py`, `api/routes/system.py` |
| `ORDNUNG_OCR` | `off`, `0`, `false` or `no` (any case) turns text in pictures off on this computer, whatever Settings → Data says; another value leaves it to Settings ([how](privacy.md#words-in-pictures-optional)). `ordnung autostart enable` records it, and so does `ordnung shortcut` on Linux and macOS; on Windows the shortcut can't, so `ordnung shortcut` prints the `setx` command that sets it for your account | unset | `config.py`, `autostart.py` |
| `ORDNUNG_BACKUP_PASSPHRASE` | The passphrase `ordnung backup` and `ordnung restore` take instead of asking, for a scheduled backup. A new backup's passphrase must still be long enough; one that isn't strong only gets a warning | unset: they ask | `cli.py` |
| `ORDNUNG_SYNC_PASSPHRASE` | The passphrase `ordnung sync connect` and `ordnung sync passphrase` take instead of asking; Ordnung still keeps it only in your password store | unset: they ask | `sync/__init__.py`, `cli.py` |
| `ORDNUNG_DEBUG` | Set to anything, a failing `ordnung` command shows the whole Python error instead of a short message | unset | `cli.py` |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | Claude Code's own: `1` turns off its telemetry and error reporting, for Ordnung's calls too ([more](privacy.md#hardening-built-into-every-model-call)). `ordnung autostart enable` and `ordnung shortcut` record it as they record `ORDNUNG_OCR` | unset | `autostart.py`, `shortcut.py` |
| `ANTHROPIC_API_KEY` | Claude Code's own; Ordnung reads it only to warn you. While it is set, Claude Code bills Ordnung's calls to that API key instead of your Claude plan: `ordnung doctor` warns, and Settings → Claude connection says so | unset | `doctor.py`, `api/deps.py` |

These are for tests, and for recording the demo's answers:

| Variable | What it does | Default | Read in |
|---|---|---|---|
| `ORDNUNG_TODAY` | The day (`YYYY-MM-DD`) Ordnung takes for today, instead of the computer's date | unset | `clock.py` |
| `ORDNUNG_BACKEND` | Where answers come from: `claude` (Claude Code), `replay` (recorded answers only), `replay+claude` (a recorded answer, else Claude Code) or `fake` (for unit tests) | `claude` | `llm/runtime.py` |
| `ORDNUNG_RECORD` | `1` lets `ordnung demo --live --rebuild` record new answers for the demo; it sends only the sample letters to Claude | unset | `cli.py` |

The rest are for maintainers and tests, or set by Ordnung itself. `ORDNUNG_FIXTURES`, `ORDNUNG_SAMPLES` and
`ORDNUNG_DEMO_DB` point Ordnung at other recorded answers, sample letters and prebuilt demo database, and
`ORDNUNG_PHONE_TEST_ADDRESS` lets the browser tests' phone access listen on a loopback address. Ordnung sets
`ORDNUNG_PIN_TODAY` (a benchmark letter's day, which the rules tools then keep) and `ORDNUNG_MASKED_NUMBERS` (your
own numbers masked, for a question asked on a paired phone) for the MCP servers it starts, and
`ORDNUNG_NOTIFY_TITLE` and `ORDNUNG_NOTIFY_BODY` to hand the morning notification to Windows PowerShell, which
shows it.

## Limitations

- Built for Germany. The rules engine knows German deadlines and holidays; letters from other
  countries are read and filed, but their dates are taken as written.
- Not legal advice. The rules were researched against statutes and case law and checked against
  worked examples, but not reviewed by a lawyer. Court deadlines always come with a "get advice"
  warning, and in doubt Ordnung picks the earliest plausible date.
- Ordnung knows which German state (Land) a sender is in only once you set it for that sender (*Which
  state is this sender in?* in its drawer, also offered under a date's *Why this date?*) or answer *Is X in
  Bavaria?*, which Ordnung asks from the postcode on their letter: in their details, and on the letter and
  among Today's Ideas when one of their dates may depend on it. Until then, for letters from a Land
  authority it uses nationwide public holidays and the 3-day delivery rule at lower confidence, so a date
  can come out a few days early (1–3 on the benchmark's letters, up to 5 around Christmas), never late. Once
  you set it, Ordnung counts that state's own delivery rule (checked against the states' law gazettes in
  November 2026): the 4th day in most states, the 3rd in Hessen. For Bremen and the Saarland, whose law
  Ordnung could not check, it keeps the 3rd day at lower confidence; Rhineland-Palatinate and Saxony-Anhalt
  are counted with the 4th day without that check, so a date there could be a day late if that is wrong. In
  Baden-Württemberg, Bavaria and Mecklenburg-Vorpommern a matter begun before their switch to the 4th day
  (7 February 2025 in Baden-Württemberg, 1 January 2025 in the other two) keeps the 3rd day, which a letter
  rarely shows: Ordnung counts the 4th, and the date says "Worth a second look" and names the earlier
  deadline — if your matter began before then, go by that one. An e-mailed decision from a Brandenburg
  authority counts from the day it arrived; Ordnung counts from the day it was sent unless you enter when it
  arrived. The benchmark gives Ordnung the Land printed on the letterhead; the
  [evaluation report](evals.md#6-results) gives its numbers without it, as the app runs. There is
  no question when the postcode is listed in two states or not at all (many P.O. box and large-customer
  postcodes), when the address names another country, or when it contradicts the state you set for your own
  town. A suggestion can be wrong (a central mail centre in another state, a misread digit): the question
  shows the postcode so you can check.
- Photos and scans are read by Claude, so reading them needs a model call; Ordnung's own text recognition
  (optional, with Tesseract) is for search only. JPEG photos above about 179 megapixels (some phones' 200 MP
  mode), and PNG, WebP or HEIC images above about 89.5 megapixels, are refused; take the photo at normal
  resolution. The text a scanner adds to a PDF (a "searchable PDF") is kept for search only and isn't checked:
  a letter found by it says so, and it is never shown as the letter's words, used to check a date or an
  amount, or sent to Claude. With Tesseract installed, the words Ordnung reads in a photo or scan Claude isn't
  reading are kept the same way, marked *not checked*; Tesseract often misreads handwriting, creased paper and
  small print, so such a letter may not be found by every word on it. Without Tesseract, a photo kept
  private, waiting or that couldn't be read is found only by its name.
- Changing the language of explanations doesn't re-read older letters: what Claude wrote before stays in
  the old language. With Arabic or Ukrainian that older text keeps its own direction and voice; with
  Turkish, Spanish or French a screen reader may read older English text in the new language's voice.
- The app's own text is in English only: buttons, receipts, the Ideas Ordnung's own rules make, and
  notifications. Ordnung reads German letters, and what Claude writes for you (explanations, translations,
  Ask's answers, Today's note and the weekly review's Ideas) follows the language you choose in Settings;
  letters to German offices stay in German.
- High-stakes kinds are named by Claude and checked by code against the rest of the reading, partly from
  its German wording: where code reads a kind itself, code's kind wins, and it drops Claude's where the
  reading rules it out (a sender that is clearly no court, a contract of another category). A letter read
  before extraction prompt version 9 names no kind and is classified by code alone. You can change a
  letter's kind on its page
  ([ADR 0010](decisions/0010-high-stakes-kinds-assigned-by-code.md) lists the accepted misses).
- A letter keeps the reading it was given. One read before extraction prompt version 9 can have a
  to-do's action or a key fact's label in German, in the letter's number formats, and no word about a
  decision window Ordnung computed; *Read again* on the letter's page reads it with the current prompt.
- A recurring payment is dated only when its letter gives a first date, a working day (also the last,
  "am letzten Bankarbeitstag") or a day of the month ("zum 1. eines Monats", counted from the letter's date
  or the contract's start) — except a lease's own monthly rent, which is due by the law's 3rd working day
  (§ 556b Abs. 1 BGB), from the month the tenancy starts at the earliest, one confidence level lower and
  with a warning to check the lease. A payment its letter gives no day for ("monatlich im Voraus"), or a
  day of the month on an undated letter with no contract start, is listed with its amount and no due
  date: Ordnung doesn't invent a start. A letter read before extraction prompt version 12 holds no day of
  the month, no last working day and no statutory notice periods; *Read again* reads it with the current
  prompt.
- A repeating date is one entry at its next day: Timeline, Today, the calendar file and a synced calendar show
  that one, and it moves on when you mark it done or its day has passed. A date you add without a letter counts
  working days with the nationwide public holidays only, so where your Land has a holiday of its own, its
  working day can come out a day early, or a day late for "the last working day".
- A deadline or a payment you add that repeats every week, or a deadline every 2 weeks, is among Today's Ideas
  nearly all the time: by default Ordnung reminds you from 14 days before a deadline and 7 days before a payment
  (Settings → Reminders), and the next one is never further off, unless you mark one done before its day. Added
  as a reminder, the dialog's first kind, such a date is an Idea only on its day.
- The tax year files a letter by the date printed on it (else the day it arrived), not by the year it is for:
  a yearly statement for 2025 dated February 2026 is a 2026 letter, which is why a tax year also lists the
  letters for taxes dated January–May of the next year, for you to check — a heuristic that also lists a
  January payslip for the new year and misses a statement dated in June. Claude marks a letter for taxes when
  it reads it; *For taxes* on a letter's page changes that, for private letters too, and your choice stays when
  the letter is read again; Ask and the Ideas Claude suggests each week follow it. A letter still waiting under
  *From your folder — not read yet* can't be marked, and *Export letters* with *Only letters for taxes* off takes all of a year's letters,
  private ones too, but not those: choose *Read these* or *Keep private* first. The ZIP *Export letters* saves
  isn't encrypted, and letters you wrote in Ordnung and their proofs of sending aren't in it.
- The moving checklist knows only the organisations Ordnung has seen in your contracts and letters (a running
  contract, or a letter of the last three years from a bank, an insurer, your employer, a landlord, a utility,
  an office and the like); others, such as your doctor or online shops, aren't on it. It doesn't cover moving
  abroad or the contract rights a move may give, and its day to register, two weeks after the move, is never
  moved off a weekend or holiday: the earlier, safe day.
- The check for incomplete readings works from the letter's text with fixed rules, in German and English
  wording only. When the letter's dates or periods disagree, or its own date can't be read, it files the
  to-do without a date for you to fill in. Besides the objection deadline it catches a fixed pay-by or send-by
  date a reading left out only when the letter states it with its year in strict words ("Zahlbar bis", "Bitte
  überweisen Sie … bis zum …") or in a few looser words that ask you directly ("Wir bitten Sie um Zahlung bis …",
  "Zahlungsfrist: …" under a request to pay), as a "Check this date in the letter" to-do; most looser wording, a
  date without its year or a period is missed. For a letter served with a yellow envelope
  (*Postzustellungsurkunde*) it counts from the date you enter for the envelope: a pickup day entered instead can
  make the date up to 14 days late. Some layouts an
  attacker plants can still mislead it
  ([ADR 0015](decisions/0015-incomplete-readings-get-a-check-written-by-code.md) lists what it misses).
- The benchmark letters are synthetic, and the Ask benchmark uses the demo's own sample life. Real post
  is messier. In the demo, which runs on the sample life's day, Ask can still take the computer's date for today
  and call a date that is still ahead passed: the `claude` CLI tells the model the computer's date as well, and
  Ask is told never to use it (the Ask benchmark, recorded a month after its own day, still has such answers:
  [docs/evals-ask.md](evals-ask.md) counts them).
- One person's Ordnung, in use on one computer at a time. A letter addressed to someone else (a partner, a
  child) says so, you can file it for them once they are in your household, and a reply to it can go out in
  their name. Once it is filed, My numbers lists its numbers under them, and Ask, Ordnung's own Ideas, Today and
  the Timeline say whose it is; its dates and reminders are still yours to act on, and the letters the weekly
  Ideas get carry no filing, though the titles of Ordnung's own Ideas name the person. A phone you pair in Settings → Phone can use it in its browser over your home
  Wi-Fi while the computer is on: the letters stay on the computer, the phone warns once about Ordnung's own certificate,
  and it can't change settings, back up or delete. There is no
  app-store app. Ordnung moves between your computers one at a time through a folder you sync yourself; it
  doesn't merge changes made on two computers at once (it asks which to keep), a computer standing by
  sends no reminders and reads no letters, and calendar sync is connected on each computer.
- E-mailed letters come in as saved files: `.eml`, or Outlook's `.msg`, which Ordnung keeps as an `.eml` copy
  (the `.msg` itself isn't kept). Ordnung doesn't fetch mail from a mailbox. An Outlook e-mail whose text is
  only in RTF comes in without its text (its attachments still come in), and a signed or encrypted one can't be
  opened: save its attachments and add those.
- Calendar sync keeps your dates current only in a CalDAV calendar that takes a user name and an app password
  (Nextcloud, iCloud, mailbox.org …). Google Calendar and Outlook.com don't offer that, so they get the calendar
  file: a snapshot whose alarms fire, but dates from letters read later reach it only when you download and import
  the file again (Today's Ideas say when there are new ones).
- Hand-off sync was tested with a simulated sync tool (files late, out of order, in pieces, conflict copies,
  online-only placeholders) and two data folders on one machine, not yet with a real Nextcloud, Syncthing or
  iCloud Drive folder on two physical computers. Forgetting a lost computer doesn't lock it out (it still
  knows the passphrase): a new sync folder with a new passphrase does
  ([what else to do](privacy.md#if-your-computer-is-lost-or-stolen)), and changing the passphrase isn't
  possible yet.
- Hand-off sync saves the database in 1 MiB slices and uploads every slice a save changed, which adds up on a
  large library: measured on a generated library of 1,500 letters and 80 MiB of database, reading one more
  letter changed 29 of its 80 slices, about 29 MiB to upload. Once every computer has caught up, Ordnung deletes
  replaced slices after a day of its running time (until then, after a week of it), but your provider's version
  history and trash may keep them longer: on a metered connection or a small quota, turn version history off for
  the sync folder if your provider lets you, and empty its trash now and then.
- Ordnung can't see backups of the whole computer (Time Machine, File History), so the weekly review reminds
  you to back up even when you make those; a scheduled `ordnung backup` counts. Its disk-encryption check is a
  best effort on macOS (FileVault) and Linux (LUKS and encrypted folders such as eCryptfs; not fscrypt or
  ZFS's own encryption). On Windows it can't check: its row there says where to see that BitLocker or Device
  encryption is on.
- Phone access was tested with phone emulation in Chromium over HTTPS, not yet on physical phones. How
  iPhones and Android phones word the certificate warning, whether a certificate they trust stays limited
  to the computer's one address, whether the page can open their camera and whether they keep the sign-in
  when Ordnung is opened from a bookmark or the Home Screen still has to be checked on real devices; until
  then the steps the app shows follow each system's documented menus.
