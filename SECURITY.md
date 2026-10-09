# Security policy

Ordnung keeps people's letters, deadlines and bank details on their own computer. If you find a way
to get at them, or to make Ordnung do something it shouldn't, please tell us privately first, not in
a public issue.

## How to report

Use GitHub's private reporting: the repository's **Security** tab → **Report a vulnerability**, or
open <https://github.com/ahmedEid1/ordnung/security/advisories/new> directly. Only you and the
maintainers see the report, and the fix can be discussed and prepared there before anything is
public.

The button is there only while private vulnerability reporting is turned on for the repository: the
owner turns it on once, in the repository's security settings. If you can't find it, open an issue
with the **Security contact** form, which asks for nothing about the problem, and you will be given a
private way to send the report.

Please include:

- the Ordnung version (`ordnung --version`) and your system;
- what an attacker needs (someone on your Wi-Fi, a letter you add, a file in your sync folder, …) and
  what they get;
- the steps, ideally against the demo (`ordnung demo`, a fictional person's letters) or a letter you
  made up.

**Never send real letters or personal data**, yours or anyone else's: no scans, photos or e-mails of
real letters, no names, addresses, IBANs, tax or case numbers, no `ordnung.db`, data folder, backup
file or sync folder from real use, no passphrases, session tokens, pairing codes or phone keys. A
plain `ordnung trace` names the letter's sender, to-dos, threads and contracts and shows its dates, so
don't send one of a real letter either. If a real letter is the only way to show the problem,
describe it; we will ask for a made-up one.

## What is in scope

Anything in this repository, in particular:

- **The local server**: the API and web app on `127.0.0.1` (its session token, the same-origin and
  Host checks, the content security policy), and the files it reads: uploads, e-mail attachments and
  the watched folder.
- **Phone access**: the listener on your home network, its HTTPS certificate, pairing, the phones'
  sign-in and the list of what a paired phone may do.
- **Hand-off sync**: the sync folder's format (its encryption, key file and names), and what a
  damaged or hostile sync folder can do to the data folder.
- **Backups**: the encrypted backup files and restoring them.
- **The MCP servers**: the rules tools and the read-only ledger for Claude Desktop and Claude Code.
- **Prompt injection through a letter**: a letter that makes a reading, Ask or a drafted letter do
  something it shouldn't, such as reveal another letter, change your records or hide a deadline.
- **Calendar sync**: the app password and what is sent to your calendar.

What each part is meant to protect, and how, is in
[docs/architecture.md](docs/architecture.md#components-and-trust-boundaries) and
[docs/privacy.md](docs/privacy.md).

Not in scope: problems in Claude Code or the Claude models themselves (report those to Anthropic),
attacks that need someone already in control of your user account, and a known vulnerability in a
dependency that Ordnung doesn't expose (CI's dependency audit tracks those; a normal issue is fine).

## Which versions get fixes

The newest release (see [CHANGELOG.md](CHANGELOG.md)) and `main`. Please check that the problem is
still there in one of them. A fix ships as a new version, with a line in the changelog; say in the
report whether you want to be named there.
