# Security policy

This page is for anyone who has found a security problem in Ordnung: how to report it, what counts, and what
happens next.

Ordnung keeps people's letters, deadlines and bank details on their own computer. If you find a way
to get at them, or to make Ordnung do something it shouldn't, please tell us privately first, not in
a public issue.

## In one minute

- **Report privately**, never in a public issue: the repository's **Security** tab → **Report a
  vulnerability** ([how to report](#how-to-report)).
- **Send no real letters or personal data**: show the problem with the demo or a letter you made up
  ([what to include](#what-to-include)).
- **In scope:** anything in this repository, from the local server, phone access and hand-off sync to prompt
  injection through a letter ([what is in scope](#what-is-in-scope)).
- **Not in scope:** Claude Code or the Claude models themselves, attacks that need your user account already, and
  a dependency's known vulnerability that Ordnung doesn't expose.
- **What happens next:** the fix can be prepared privately, and ships as a new version with a line in the changelog
  ([what happens next](#what-happens-next)).

[How to report](#how-to-report) · [What to include](#what-to-include) · [What is in scope](#what-is-in-scope) ·
[What happens next](#what-happens-next)

## How to report

Use GitHub's private reporting: the repository's **Security** tab → **Report a vulnerability**, or
open <https://github.com/ahmedEid1/ordnung/security/advisories/new> directly. Only you and the
maintainers see the report, and the fix can be discussed and prepared there before anything is
public.

The button is there only while private vulnerability reporting is turned on for the repository: the
owner turns it on once, in the repository's security settings. If you can't find it, open an issue
with the **Security contact** form, which asks for nothing about the problem, and you will be given a
private way to send the report.

## What to include

Please include:

- the Ordnung version (`ordnung --version`) and your system;
- what an attacker needs (someone on your Wi-Fi, a letter you add, a file in your sync folder, …) and
  what they get;
- the steps, ideally against the demo (`ordnung demo`, a fictional person's letters) or a letter you
  made up.

**Never send real letters or personal data**, yours or anyone else's:

- no scans, photos or e-mails of real letters, no names, addresses, IBANs, tax or case numbers;
- no `ordnung.db`, data folder, backup file or sync folder from real use, no passphrases, session tokens,
  pairing codes or phone keys;
- no `ordnung trace` of a real letter either: a plain one names the letter's sender, to-dos, threads and
  contracts and shows its dates.

If a real letter is the only way to show the problem, describe it; we will ask for a made-up one.

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

**Not in scope:** problems in Claude Code or the Claude models themselves (report those to Anthropic),
attacks that need someone already in control of your user account, and a known vulnerability in a
dependency that Ordnung doesn't expose (CI's dependency audit tracks those; a normal issue is fine).

<a id="which-versions-get-fixes"></a>

## What happens next

- **Fixed versions.** The newest release (see [CHANGELOG.md](CHANGELOG.md)) and `main` get fixes. Please check
  that the problem is still there in one of them.
- **The fix.** A fix ships as a new version, with a line in the changelog; say in the report whether you want to
  be named there.
