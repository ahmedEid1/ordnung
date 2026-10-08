# ADR 0017 — Phone access over the home network

**Status:** accepted · **Date:** 2026-10-07

## Context
Letters arrive at the door, not at the desk. People photograph them with their phone, check what is due
on the sofa and pay from the banking app on the same phone — but Ordnung only answered the browser on the
computer it runs on: `ordnung serve` listens on `127.0.0.1`, accepts only `localhost` Host headers and
signs a browser in with a session token that changes at every start (ADR 0013 keeps it out of logs). The
README said so: "no mobile app". Opening that up touches the parts of Ordnung that are hardest to see and
hardest to undo — who can reach the server, with which secret, over which network — so it gets short
written policies (ADR 0007) rather than a flag that exposes the computer's own listener.

A security review of the first design found three ways it could be abused before anyone noticed: a device
on the Wi-Fi could exhaust the computer's memory before pairing, someone who saw the QR code could pair
first and look like the person's own phone, and the certificate authority a phone could trust vouched for
every private address — the router included. The decisions below are the design with those findings
fixed.

## Principle
The letters stay on the computer; the phone is a window, not a copy. The computer's own listener does not
change.

## Decision

**A second listener, in the same process, off until turned on.** Settings → Phone starts a second uvicorn
server on the same event loop and app as `ordnung serve`, bound to one home-network IPv4 address of the
computer (never `0.0.0.0`) and a saved port (8767, or the next free one). It is started with `startup()`
and stopped with `shutdown()`, never `serve()` or `run()`, so it never takes over Ctrl+C or SIGTERM; its
lifespan is off, so there is still one worker, one daily tick and one folder watcher; it is limited to 128
connections. The computer listener, its token, its Host allow-list and the CLI are untouched. The choice
is kept in the database (meta `phone_access`), so start at login brings it back without a flag. It is
never available in the demo, nor when Ordnung runs without a session token (`--no-token`). Policy:
`ordnung/phone/__init__.py` and `ordnung/phone/access.py`.

**Home network only, and only this one.** The addresses offered come from the network interfaces with
their netmasks; tunnels and VPNs are never offered, nor are containers and virtual machines unless the
router is on their network (an external Hyper-V switch carries the computer's own Wi-Fi or Ethernet).
An interface is judged by its name and, on Windows, by its adapter's description too ("Hyper-V Virtual
Ethernet Adapter", "WireGuard Tunnel"): Windows' names alone ("Ethernet 3") don't say what an adapter
is. The address recommended is the one on the router's network, so a VPN that took the default route
isn't; when the router can't be read or no address is on its network, it is the one the computer
reaches the internet from. The listener answers only devices in the bound address's subnet, so a Docker
container or a peer behind a VPN is refused. It remembers the router (the default gateway's address and
hardware address, where the system lets Ordnung read them; one that can't be read when phone access is
turned on is remembered the first time it can be, and a saved one is never replaced by itself): when
the computer wakes up on another network that hands it the same address — every FRITZ!Box hands out
192.168.178.x unless told otherwise — phone access pauses until the person says *This is my home
network*. It never moves to a new address by itself. Policy: `ordnung/phone/net.py`.

**HTTPS with a certificate authority for that one address.** Ordnung makes a small certificate authority
whose name constraints allow exactly the listener's address and no DNS name, and issues a 397-day server
certificate for it. A phone that trusts it therefore can't be made to trust the router, a NAS or any
website through it — not even by someone who copies the authority's key from a backup of the computer's
disk. A new address makes a new authority, and Ordnung tells the person to install the new one and remove
the old; renewing at the same address keeps it. The names in both certificates are neutral ("Home network
certificate 7K3M"): they are sent to anyone on the network who opens a connection. The phone warns once;
Settings shows the fingerprints to compare. Trusting the authority is offered only on phones whose browser
is expected to keep its constraint (iPhone and iPad, Chrome on Android — still to be confirmed on real
phones), and after that a warning means that something else is answering in the computer's place — don't
continue. Browsers ignore HSTS for an address, so no certificate error can be made impossible to click
through; the docs say so rather than promise it away. Keys live in `<data>/phone/`, never in the database
or a backup. Policy: `ordnung/phone/tls.py`.

**A code shown on the computer pairs one phone, and a code seen by two pairs nobody.** The QR code carries
the address and a 10-character code (50 bits) in the URL fragment; it works once, for 10 minutes. A
wrong, expired or missing code gets the same answer, so a guess learns nothing about whether a code is
open. One device gets 5 wrong tries for a code and is then locked out of it; 100 wrong tries from the whole
network cancel the code, and the computer lists the addresses they came from. If a code that already
paired a phone comes again, two devices had it — someone may have seen the screen — so the phone that used
it is removed too and the computer says so. The phone and the computer both show two check words derived
from the phone's id ("amber tulip"); a phone's name loses invisible and control characters. The computer
shows each new phone at once, with its address and Remove. Chosen over a confirmation click on the
computer (the code already proves someone saw the screen, and a relaying attacker passes a click anyway)
and over a code in the query string (link previews could spend it). Policy: `ordnung/phone/pairing.py`.

**Each phone has its own sign-in, never the session token.** A 256-bit token per phone in a `__Host-`
cookie (Secure, HttpOnly, SameSite=Strict, named per port); only its SHA-256 is stored. It changes at
most once an hour on a page load, and the previous one stays valid for 2 minutes after the phone first
uses the new one; a sign-in it replaced that comes back later means it was copied, and the phone is
signed out with a notice on the computer — so a cookie taken while someone clicked through a warning
stops working soon after. Removing a phone signs it out at once, ends its live streams and stops an upload
still arriving; turning phone access off does the same. A request counts as in flight from the gate's
first check, so a stop waits for it; one that writes always finishes — the listener's own stop never
cancels it (it may hold the ledger lock) — an upload that arrived is filed and answered, and the next
request is refused. The phone is told why: removed, its sign-in used from two places, its code used by
another device, unused (the pairing page says which), or that phone access stopped (it stays paired and
keeps what it was sending). A phone unused for 30 days is forgotten; pairing again is one scan. It is
refused when it comes back, not only by the daily round, so a restart doesn't let it in. The session
token is ignored on the phone listener and the phone cookie on the computer listener.

**What a phone may do is an allow-list checked before routing.** Look, add, write and tick off; settings,
the profile, phone access, backups, deleting, held-letter decisions and downloads of files or records
(originals, letter PDFs, the calendar files) stay on the computer — the phone shows the dates, and
calendar sync can put them in the phone's calendar. A route that isn't on the list is refused, and a test
makes every new route a decision. The list is published in the OpenAPI schema (`x-ordnung-phone`). On a phone the person's own numbers in
*My numbers* and in Ask's numbers tool, and the profile's IBAN, show only their last 4 characters:
whoever holds an unlocked phone shouldn't read a tax ID off a list (a letter still shows what it prints).
Each phone may ask Ask 30 questions, start 20 other things that ask Claude and add 30 letters an hour
(each letter of an upload counts, photos of one letter once), so a lost phone can't use up the Claude
account. Everything a phone changes says so in the privacy log
("on Anna's iPhone"), and the Remove dialog counts the changes of the last 30 days. Policy:
`ordnung/phone/scope.py`, `ordnung/phone/mask.py`, `ordnung/phone/actor.py`.

**Strict requests on the network.** The phone listener answers only the exact `https://<address>:<port>`
Host, refuses dot segments and doubled or back slashes in a path, requires `Origin` on every change and
sends `no-store` on every API answer. Before pairing it answers only the pairing page, the built app's own
files and a pairing request of at most 1 KiB with a stated length — a body without a length is refused on
every request, and every body is counted as it arrives — so no device on the Wi-Fi can make the computer
read a large body before it is signed in. Policy: `ordnung/api/phone_gate.py`.

**A restored copy doesn't take over phones.** Backups leave phone access out (the record is removed from
the database snapshot, and `phone/` was never in a backup); a restore detaches it; Delete everything
removes the certificates. Hand-off sync between computers (ADR 0018) leaves the same record out.

Chosen over: the session link on the phone (one full-admin secret, no scope, no revocation);
`serve --host 0.0.0.0` (the whole API on every interface); plain HTTP (sniffable letters and sign-ins); a
public certificate through a relay name (needs a server Ordnung doesn't have); one authority for all
private networks (a copied key could stand in for the router); mDNS names (announce Ordnung to the
network; unreliable on Android); a separate process (two writers on one data folder).

## Consequences and known limits
- The phone works only while the computer is on, awake, running Ordnung and on the same network; there is
  no offline mode and no push notification to the phone.
- Phones warn about the certificate once per certificate (yearly, and when the computer's address
  changes) unless they trust the authority; Chrome may ask again after some days. Every warning is a
  chance for someone in the middle; the hourly sign-in change limits what a cookie taken that way is worth.
- An attacker who already controls the home network at the moment of pairing can sit in the middle if the
  fingerprint isn't compared; browsers give pages no access to the certificate, so this can't be checked
  automatically.
- When the router can't be read, a network that hands the computer the same address isn't told apart from
  home; a stranger there reaches only the pairing page and refusals. A router first read later is
  trusted as home's, also when the computer has moved to another network with the same address by then.
- A VPN or tunnel is known by its name or its adapter's description; one whose names say nothing (a
  Windows VPN connection someone named "Work") is offered, and recommended when it holds the default
  route and no other address is on the router's network.
- A new address means pairing again and, for a phone that trusted the old authority, installing the new
  one; the docs suggest reserving the address in the router.
- Other HTTPS software on the computer's address receives the phone's cookie if the phone visits it
  (cookies ignore ports), as with today's local cookie.
- A phone may spend Claude usage (Ask, "Read again", drafting) like the computer, within its hourly
  limits; usage shows in Privacy & AI usage.
- Tested with phone emulation in Chromium over HTTPS (the browser tests pair an emulated phone, use it,
  check what it is refused and remove it), not yet on physical phones. How each phone's browser words the
  warning, keeps the authority's constraint, opens the camera and keeps the sign-in still has to be
  checked on real iPhones and Android phones before the docs' steps can be called confirmed.
- A letter shows what is printed on it, also one written on the phone: a template letter that asks for
  money back on the person's account (the deposit return) carries the profile's IBAN in full, while the
  profile and *My numbers* show only its last 4 characters. Masking it there would make the phone's editor
  save the mask into the letter, and the print preview shows the letter as it will be printed; the letter
  is logged as written on that phone.
- Why a phone was signed out is kept in memory: after a restart, a phone removed before it came back is
  told only that it was removed.
- No IPv6, no mDNS, no app-store app. A phone reaches only its own computer: it can't take Ordnung over
  from another one (hand-off sync between computers, ADR 0018, is the computers' own).
