# Statute texts

Sections of thirteen German federal statutes, one statute per file, in the wording of
[Gesetze im Internet](https://www.gesetze-im-internet.de/), the federal government's site for federal law in its
current consolidated form (Federal Ministry of Justice, Federal Office of Justice). The site calls these
consolidated texts non-official ("nicht amtliche Texte"): the binding wording is the one promulgated in the
Bundesgesetzblatt. Statutes are not protected by copyright in Germany (§ 5 Abs. 1 Urheberrechtsgesetz).

## What each file holds

- The first line is the statute's name and abbreviation. The lines under it are the site's status lines for that
  statute, as the site gives them.
- Then each section listed in the table below, in that order: a line with its number and title (the SGG's
  sections have no title), a blank line, then the section's paragraphs, one per line. List items are on lines of
  their own: a list starts four spaces further in than the text it belongs to, and the rest of an item lines up
  with the text of its first line. The site's footnotes to a section follow it under a line "Fußnote".
- The words are the site's, complete and unchanged. Only white space differs: every run of spaces, line breaks
  and no-break spaces is one space.

## How the files were made

On the day in the Retrieved column, each statute's XML download (the Source column) was fetched and the listed
sections were taken from it. On the same day every section was compared word for word with its own page on the
site, `https://www.gesetze-im-internet.de/<folder>/__<number>.html` (for example
https://www.gesetze-im-internet.de/bgb/__187.html; the EGAO's is
https://www.gesetze-im-internet.de/aoeg_1977/art_97__1.html). All 80 sections matched, each on its file's day.

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
- Only federal law is here. The law of a federal state (Land), such as its own administrative procedure act or
  its public holidays act, is not.

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
| `vwgo.txt` | Verwaltungsgerichtsordnung (VwGO) | §§ 57, 58, 68, 70, 74 | https://www.gesetze-im-internet.de/vwgo/xml.zip | 2026-11-04 | `2bca19e1bd51d0e8b3ffa9be525d11e4ef8eafab5aa281a68be5c205ff260521` |
