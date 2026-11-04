# Statute texts

Sections of fourteen German federal statutes, one statute per file, in the wording of
[Gesetze im Internet](https://www.gesetze-im-internet.de/), the federal government's site for federal law in its
current consolidated form (Federal Ministry of Justice, Federal Office of Justice). The site calls these
consolidated texts non-official ("nicht amtliche Texte"): the binding wording is the one promulgated in the
Bundesgesetzblatt. Statutes are not protected by copyright in Germany (§ 5 Abs. 1 Urheberrechtsgesetz).
`laender.txt` holds the law of the sixteen Länder on when a written decision of their authorities counts as
delivered, each from the Land's own legal portal; it is described under "Länder" below.

## What each file holds

- The first line is the statute's name and abbreviation. The lines under it are the site's status lines for that
  statute, as the site gives them.
- Then each section listed in the table below, in that order: a line with its number and title (the SGG's
  sections have no title), a blank line, then the section's paragraphs, one per line. List items are on lines of
  their own: a list starts four spaces further in than the text it belongs to, and the rest of an item lines up
  with the text of its first line. The site's footnotes to a section follow it under a line "Fußnote".
- The words are the site's, complete and unchanged. Only white space differs: every run of spaces, line breaks
  and no-break spaces is one space.
- `egbgb.txt` holds sections of an article ("Art 246a § 1", as the EGAO's "Art 97 § 1") and an annex,
  "Anlage 1", the Muster-Widerrufsbelehrung (the standard withdrawal notice). In the annex each row of its
  table is a line, a line break in it ends a line, and the marks that show where a design note
  (Gestaltungshinweis) applies, which the site shows as a small picture of the note's number, are written as
  that number in square brackets, for example `[1]`; the design notes themselves are a list whose items carry
  the same marks.

## How the files were made

On the day in the Retrieved column, each statute's XML download (the Source column) was fetched and the listed
sections were taken from it. On the same day every section was compared word for word with its own page on the
site, `https://www.gesetze-im-internet.de/<folder>/__<number>.html` (for example
https://www.gesetze-im-internet.de/bgb/__187.html; the EGAO's is
https://www.gesetze-im-internet.de/aoeg_1977/art_97__1.html). All 80 sections matched, each on its file's day.
`egbgb.txt`'s five parts were compared the same way with
https://www.gesetze-im-internet.de/bgbeg/art_246a__1.html to `art_246a__4.html` and with Anlage 1's page,
https://www.gesetze-im-internet.de/bgbeg/art_253anlage_1.html (the `[n]` marks left aside, as the page shows a
picture there); all five matched.

To check a file, compare its sha256 (for example `sha256sum bgb.txt`) with the value in the table.

## Limits

- The site shows the wording in force on the day it is read: a change that comes into force later appears there
  only from that day (the site's [notes](https://www.gesetze-im-internet.de/hinweise.html), no. 3).
- A status line "textlich nachgewiesen, dokumentarisch noch nicht abschließend bearbeitet" means that the change is
  in the text and only the site's own documentation of it is unfinished (the same notes, no. 4).
- The OWiG's status lines name two changes in force since 28 October 2026 that the site's text does not include
  yet ("noch nicht berücksichtigt"), both from the act in BGBl. 2026 I Nr. 321. Its Article 7 changes only § 110a
  OWiG, and its Article 15 only moves the day an earlier amending act comes into force, so neither changes §§ 46
  and 67.
- Apart from `laender.txt`, only federal law is here. A Land's public holidays act is not.

## Files

| File | Statute | Sections | Source | Retrieved | sha256 |
|---|---|---|---|---|---|
| `bgb.txt` | Bürgerliches Gesetzbuch (BGB) | §§ 130, 186–193, 309, 355, 356, 556, 558, 558a, 558b, 573c, 574, 574a, 574b, 622, 623 | https://www.gesetze-im-internet.de/bgb/xml.zip | 2026-11-04 | `d754399a62d575759e45d35b9eec681aa8fabd6444e39f7f46043befe5ffa185` |
| `ao.txt` | Abgabenordnung (AO) | §§ 108, 122, 355 | https://www.gesetze-im-internet.de/ao_1977/xml.zip | 2026-11-03 | `4f1359165484856c272f1b13090efcbf786884b0ec694d1162b86adfb2b41160` |
| `egao.txt` | Einführungsgesetz zur Abgabenordnung (EGAO) | Art 97 § 1 | https://www.gesetze-im-internet.de/aoeg_1977/xml.zip | 2026-11-03 | `d1444d933719606a6d4a66b1866e5c7a281f67521f54baa8f121ab6aa4852eec` |
| `vwvfg.txt` | Verwaltungsverfahrensgesetz (VwVfG) | §§ 31, 41 | https://www.gesetze-im-internet.de/vwvfg/xml.zip | 2026-11-03 | `32ee3088de91e21206b057b88ee03aa697c78b4e1155a7375c19edeeafae27f9` |
| `sgb_10.txt` | Zehntes Buch Sozialgesetzbuch - Sozialverwaltungsverfahren und Sozialdatenschutz - (SGB X) | §§ 26, 37 | https://www.gesetze-im-internet.de/sgb_10/xml.zip | 2026-11-03 | `ae4b1a929699d5144ce67241724b3c2b940e68907612c9a71960ac19ae404155` |
| `sgg.txt` | Sozialgerichtsgesetz (SGG) | §§ 64, 84 | https://www.gesetze-im-internet.de/sgg/xml.zip | 2026-11-03 | `fb1258eb49c5acdd532bf2e85193d9e397f2cfe6e3d4faf647e49f542d0c75cd` |
| `owig.txt` | Gesetz über Ordnungswidrigkeiten (OWiG) | §§ 46, 67 | https://www.gesetze-im-internet.de/owig_1968/xml.zip | 2026-11-03 | `10db1c86dd4bfc52bb67a74d3d7002c0a743b4f2fde6d5d82facc8bf875086b5` |
| `stpo.txt` | Strafprozeßordnung (StPO) | § 43 | https://www.gesetze-im-internet.de/stpo/xml.zip | 2026-11-03 | `f031bdcf30f037c484a8a70c826ebc9ae83373a763f560a65ebd797089c3a2d6` |
| `zpo.txt` | Zivilprozessordnung (ZPO) | §§ 166–195, 222, 339, 692, 694, 700 | https://www.gesetze-im-internet.de/zpo/xml.zip | 2026-11-03 | `6449cb70cbf60dd30afd52fd782da7fe4a3ac6f26110bc5143ad04fb202e3faa` |
| `kschg.txt` | Kündigungsschutzgesetz (KSchG) | §§ 4, 7 | https://www.gesetze-im-internet.de/kschg/xml.zip | 2026-11-03 | `770c2dfb1471c03ead0fc6629fd760bdc432bcbd7c3af9c5ddf05155ca578e20` |
| `tkg.txt` | Telekommunikationsgesetz (TKG) | §§ 56, 57 | https://www.gesetze-im-internet.de/tkg_2021/xml.zip | 2026-11-04 | `01462c30755aebf8227b7b6a2f45eaadc2d6fe7c83a8e2f69a849e0afe32321f` |
| `enwg.txt` | Gesetz über die Elektrizitäts- und Gasversorgung (EnWG) | § 41 | https://www.gesetze-im-internet.de/enwg_2005/xml.zip | 2026-11-03 | `142be8b4e9ad3fae833c3be4d14d715456f36d9508ce3d1b81defd18c8c52ec5` |
| `egbgb.txt` | Einführungsgesetz zum Bürgerlichen Gesetzbuche (BGBEG) | Art 246a §§ 1–4, Anlage 1 | https://www.gesetze-im-internet.de/bgbeg/xml.zip | 2026-11-04 | `e450eb3e37bcb983413baaa7d4a0a1a4b0f18ea3906d9cde5178b4b7f24cd3b1` |
| `vwgo.txt` | Verwaltungsgerichtsordnung (VwGO) | §§ 57, 58, 68, 70, 74 | https://www.gesetze-im-internet.de/vwgo/xml.zip | 2026-11-04 | `2bca19e1bd51d0e8b3ffa9be525d11e4ef8eafab5aa281a68be5c205ff260521` |
## Länder (`laender.txt`)

`laender.txt` holds, for each Land, as the Land's official legal portal gives it: the section of the Land's
administrative procedure act on the notification of an administrative act (Bekanntgabe des Verwaltungsaktes) where
the act has one, or else the section by which the Land's act applies the federal Verwaltungsverfahrensgesetz
(`vwvfg.txt`); and any section of the same act that changes that rule or says which wording applies to procedures
already under way.

### What the file holds

- The first line is "Verwaltungsverfahrensrecht der Länder". Then, after a blank line each, one block per Land in
  the order of the table below.
- A block starts with the Land's name. The next line is the statute's name, then the portal's status lines for that
  statute, as the portal gives them (where the portal shows a label and its value side by side, the line joins them
  with ": "). Then each provision: a line with its number and title (Bavaria numbers by "Art.", and the
  Niedersachsen act's sections carry no title), a blank line, its paragraphs one per line, list items as in the
  federal files; the portal's footnotes to a provision follow it under a line "Fußnote".
- The words are the portal's, complete and unchanged; every run of white space is one space. The sentence numbers
  that some portals print in small raised type (Bayern, Sachsen) are left out, as the federal texts carry none.
- A Land whose portal could not be fetched has a block of two lines: its name and "Not retrieved (see SOURCES.md)."
  Its rule is not filled in from memory or from any other source.

### How the file was made

On the day in the table each page was fetched over HTTPS (certificates checked) and the provisions were taken from
it; a second, separate pass over the same pages found every line of each retrieved block, in order, as consecutive
words of its page. Baden-Württemberg's portal is a script page; it loads each document's text from the portal's own
document service on the same host (`/jportal/wsrest/recherche3/document`, after its `init` call), and that text,
which is the page's, was taken from there. The addresses in the table are the portal's permanent links to the three
documents (the statute's front page, § 41, § 102b).

The sha256 in the table is that of the Land's block: the lines from the Land's name to the last line before the
blank line that precedes the next Land's name (to the end of the file for the last Land), each ending in a line
break.

sha256 of `laender.txt`: `72843c14be59b2d88d8f06b3c98c0b5e3c25ba8bc7f8af95900e33461eeacd75`

| Land | Statute | Provisions | Source | Retrieved | sha256 |
|---|---|---|---|---|---|
| Baden-Württemberg | Verwaltungsverfahrensgesetz für Baden-Württemberg (Landesverwaltungsverfahrensgesetz - LVwVfG) | §§ 41, 102b | https://www.landesrecht-bw.de/perma?d=jlr-NNLBW00007E83, https://www.landesrecht-bw.de/perma?d=jlr-NNLBW00007E83NN00000000103, https://www.landesrecht-bw.de/perma?d=jlr-NNLBW00007E83NN00000000202 | 2026-11-04 | `2aed656ef7576afe5c0d4e7445144a91ae178ac87c55654cbf8570555a84eae0` |
| Bayern | Bayerisches Verwaltungsverfahrensgesetz (BayVwVfG) | Art. 41 | https://www.gesetze-bayern.de/Content/Document/BayVwVfG, https://www.gesetze-bayern.de/Content/Document/BayVwVfG-41 | 2026-11-04 | `8df47a97cc72084e1515c6e8ac28397826a83d3878b17985c569531fa03fcefd` |
| Berlin | not retrieved | – | https://gesetze.berlin.de/ | 2026-11-04 | `23f87166a25f1dd5fbaa863ea043a9e7c083c3167f278fdd5928939f052b4682` |
| Brandenburg | Verwaltungsverfahrensgesetz für das Land Brandenburg (VwVfGBbg) | §§ 1, 7 | https://bravors.brandenburg.de/gesetze/vwvfgbbg | 2026-11-04 | `5aa4391e03a7d26f8243be8695fd20f0ca34afaac84f2ec65726665636e858a1` |
| Bremen | not retrieved | – | https://www.transparenz.bremen.de/ | 2026-11-04 | `ea8e9191906c95e417efddbadbc925f72e9903261e86a35b26e16ea024732512` |
| Hamburg | not retrieved | – | https://www.landesrecht-hamburg.de/ | 2026-11-04 | `1a6955d66c49b2a9672e2a068be45fc98150c4a63d53bf28140ceacd9ac95b13` |
| Hessen | not retrieved | – | https://www.rv.hessenrecht.hessen.de/ | 2026-11-04 | `353003321576662c84fe5e3ecc505ac42a242cd911d9c7dd1d6263b6e599fdf6` |
| Mecklenburg-Vorpommern | not retrieved | – | https://www.landesrecht-mv.de/ | 2026-11-04 | `084e3e5a133e948eef93977ac884ded0abd7fefaccc919d8fda74f39fb6a0cca` |
| Niedersachsen | Niedersächsisches Verwaltungsverfahrensgesetz (NVwVfG) | § 1 | https://voris.wolterskluwer-online.de/browse/document/631d25e7-bc57-322f-8763-640c7c45a804, https://voris.wolterskluwer-online.de/browse/document/78aa978e-72b9-39a7-aee5-53b1567912f5 | 2026-11-04 | `4d597a4b7767f71db5e42bb2fe4496d7e860287c7eaa6b6acf0c747fc829a79a` |
| Nordrhein-Westfalen | Verwaltungsverfahrensgesetz für das Land Nordrhein-Westfalen (Verwaltungsverfahrensgesetz NRW – VwVfG NRW) | §§ 41, 97 | https://recht.nrw.de/lrgv/gesetz/01012025-verwaltungsverfahrensgesetz-fuer-das-land-nordrhein-westfalen | 2026-11-04 | `c61c2ddc3d4063fda0d585f8b6fddb799c879907e5047d022d3ebb6c1dc90101` |
| Rheinland-Pfalz | not retrieved | – | https://landesrecht.rlp.de/ | 2026-11-04 | `2dd8c6f637c36bb68f5a80aa009d512b6d0d25c80d81720d08f74254f10b5fd0` |
| Saarland | not retrieved | – | https://recht.saarland.de/ | 2026-11-04 | `9c9ce60c7f471e9a4e05ea90065316477719fff3034c9ba77e0563dbaeeee178` |
| Sachsen | Gesetz zur Regelung des Verwaltungsverfahrens- und des Verwaltungszustellungsrechts für den Freistaat Sachsen (SächsVwVfZG) | § 1 | https://www.revosax.sachsen.de/vorschrift/11377-SaechsVwVfZG | 2026-11-04 | `a0c534eeee6d69102a996dc315a3de12d14152606b0894bc402e7f387f4a4a75` |
| Sachsen-Anhalt | not retrieved | – | https://www.landesrecht.sachsen-anhalt.de/ | 2026-11-04 | `b4d6aa36b8f467bfee6466d5f35cf1c32d7971d7db3528d9d957892a290984bf` |
| Schleswig-Holstein | not retrieved | – | https://www.gesetze-rechtsprechung.sh.juris.de/ | 2026-11-04 | `b5b082d7aa4501ee44175b5d70042d0935f48f3f28ef7cd48b4618c081326d70` |
| Thüringen | not retrieved | – | https://landesrecht.thueringen.de/ | 2026-11-04 | `a9d512f0e46d9471ec608324a3324b4b7e708a26c6ba44e741a38b65384ddfe6` |

### Not retrieved

Ten of the sixteen Länder are not retrieved: Berlin, Bremen, Hamburg, Hessen, Mecklenburg-Vorpommern,
Rheinland-Pfalz, Saarland, Sachsen-Anhalt, Schleswig-Holstein and Thüringen. For each, the address in the table was
tried on the day shown. Bremen's portal answered "403 Forbidden". For each of the others the connection was closed
before any answer, every time in 20 tries over about eight minutes, as on every earlier try that day. Nothing else
was used in their place.

### Limits

- Baden-Württemberg's § 102b keeps the wording of the act in force until 6 February 2025 for procedures begun
  before 7 February 2025. That earlier wording is not here.
- The sections held for Brandenburg, Niedersachsen and Sachsen point to the federal Verwaltungsverfahrensgesetz;
  its § 41 is in `vwvfg.txt`, in the wording in force on that file's day.
- Letters of a Land's tax office: the Abgabenordnung is federal law (`ao.txt`). The section that sets its scope,
  § 1 AO, is not among the sections held.
- A portal shows the wording in force on the day it is read. What it gives as the day each provision took its
  present wording: Baden-Württemberg § 41 and § 102b "gültig ab: 07.02.2025"; Bayern Art. 41 "Text gilt ab:
  01.01.2025"; Nordrhein-Westfalen §§ 41 and 97, the footnotes in the file (1 January 2025); Niedersachsen § 1 "ab
  01.10.2022 (aktuelle Fassung)"; Brandenburg and Sachsen give the statute's status only (the lines in the file).
