# Statute texts

Sections of fourteen German federal statutes, one statute per file, in the wording of
[Gesetze im Internet](https://www.gesetze-im-internet.de/), the federal government's site for federal law in its
current consolidated form (Federal Ministry of Justice, Federal Office of Justice). The site calls these
consolidated texts non-official ("nicht amtliche Texte"): the binding wording is the one promulgated in the
Bundesgesetzblatt. Statutes are not protected by copyright in Germany (§ 5 Abs. 1 Urheberrechtsgesetz).
`laender.txt` holds the law of the sixteen Länder on when a written decision of their authorities counts as
delivered, from the Land's own legal portal or from the Land's law gazette; it is described under "Länder" below.

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

`laender.txt` holds, for each Land, the law on when a written administrative act of the Land's authorities that is
sent by post counts as notified (Bekanntgabe des Verwaltungsaktes), from one of two kinds of official source:

- The Land's official legal portal, which gives the act in its current consolidated wording (Baden-Württemberg,
  Bayern, Brandenburg, Niedersachsen, Nordrhein-Westfalen, Sachsen): the section of the Land's administrative
  procedure act on the notification of an administrative act where the act has one, or else the section by which the
  Land's act applies the federal Verwaltungsverfahrensgesetz (`vwvfg.txt`); and any section of the same act that
  changes that rule or says which wording applies to procedures already under way.
- Where the portal could not be fetched, the Land's law gazette (Gesetz- und Verordnungsblatt) as the Land's
  government, its parliament or the gazette's publisher puts it online (Berlin, Hamburg, Hessen,
  Mecklenburg-Vorpommern, Schleswig-Holstein, Thüringen): the provisions as promulgated, that is the section itself
  where it was enacted or promulgated whole, or else the amending provisions that change it, with any transitional
  provision and the provision on their coming into force (for Berlin and Hessen that provision is not in the block
  but quoted under "How the file was made").

### What the file holds

- The first line is "Verwaltungsverfahrensrecht der Länder". Then, after a blank line each, one block per Land in
  the order of the table below.
- A block starts with the Land's name. The next line is the statute's name.
- From a portal: then the portal's status lines for that statute, as the portal gives them (where the portal shows a
  label and its value side by side, the line joins them with ": "). Then each provision: a line with its number and
  title (Bavaria numbers by "Art.", and the Niedersachsen act's sections carry no title), a blank line, its
  paragraphs one per line, list items as in the federal files; the portal's footnotes to a provision follow it under
  a line "Fußnote". The words are the portal's, complete and unchanged; every run of white space is one space. The
  sentence numbers that some portals print in small raised type (Bayern, Sachsen) are left out, as the federal texts
  carry none.
- From a gazette: then, where the gazette prints them under the statute's name, the lines of its date or version
  ("Vom 21. April 2016", "in der Fassung vom 15. Januar 2010"), and one line "Fundstelle: ..." per gazette issue
  used: the gazette, its year, issue number and day of issue, the pages, the act's title and date, and the
  provisions taken from it (Hamburg's second such line names its constitution, which the Bürgerschaft prints in its
  handbook). Then each provision as printed: a line with its number and title (a section, "§ 1 Anwendungsbereich";
  an article, "Artikel 1 Änderung des Landesverwaltungsverfahrensgesetzes"; for Hamburg's amending act, which has no
  articles, the act's title), a blank line, then its text, one paragraph per line. Of an amending article, the
  opening sentence and only the numbered items that touch the rule are held; the items left out change other
  provisions. The items are list items as in the federal files: an item starts four spaces further in than the text
  it belongs to, and the wording an item inserts (between „ and “) lines up with the text of the item's first line.
  Mecklenburg-Vorpommern's Artikel 1 appears twice, once from each of the two acts named in its "Fundstelle:" lines,
  in the order of those lines.
- The words are the gazette's, complete and unchanged, apart from white space: every run of white space is one
  space, a word that the print splits at a line end with a hyphen is joined, and running heads, page numbers,
  footnote marks (Hessen's "Artikel 23)" is Artikel 2 with footnote mark 3) and the sentence numbers that the
  Bürgerschaft's handbook prints in small raised type in Hamburg's Artikel 54 are left out. What the print gets wrong
  is kept: Mecklenburg-Vorpommern's § 120a ends without its closing quotation mark, and its Artikel 95 Abs. 7 reads
  "Artikel 56 Artikel 73" without a comma, both as printed. The signature lines under an act ("Ausgefertigt ...",
  the place, the day and the signatories) are left out.
- A Land for which no official source could be fetched, or none that gives the rule, has a block of two lines: its
  name and "Not retrieved (see SOURCES.md)." Its rule is not filled in from memory or from any other source.

### How the file was made

On the day in the table each source was fetched over HTTPS (certificates checked) and the provisions were taken
from it. Baden-Württemberg's portal is a script page; it loads each document's text from the portal's own document
service on the same host (`/jportal/wsrest/recherche3/document`, after its `init` call), and that text, which is the
page's, was taken from there. The addresses in the table are the portal's permanent links to the three documents
(the statute's front page, § 41, § 102b).

A second, separate pass found every line of each retrieved block, in order, as consecutive words of its source: for
a portal its page, for a gazette the text layer of its PDF files. Hamburg's statute line, which its act prints only
in the genitive, was found in the gazette's subject index for 2025 ("Hamburgisches Verwaltungsverfahrensgesetz,
Änderung 338"). Schleswig-Holstein's pages are scans without a text layer: its block was read from the page images
(GVOBl. 2024 pp. 934 and 936), and the second pass compared it with a machine reading (OCR) of the same images; where
the two differed ("$" for "§", "GVOBI." for "GVOBl.", ",.ber." for ", ber."), the image was read again, enlarged,
and shows the block's reading. The act's day, 13 December, is written into the printed "Vom . Dezember 2024" by
hand; the next act that changed the statute, of 26 March 2025, cites it as "Gesetz vom 13. Dezember 2024 (GVOBl.
Schl.-H. S. 934)".

For each gazette source, the acts that changed the statute after the act held were looked for, up to the day in the
table. Where the provision of an act held on its coming into force is not in the block, it is quoted here:

- Berlin. § 12 of the Act of 21 April 2016 (GVBl. 2016 Nr. 11, S. 220), not held in the block, reads in its first
  sentence: "Dieses Gesetz tritt am Tage nach der Verkündung im Gesetz- und Verordnungsblatt für Berlin in Kraft."
  Each later amending act cites the one before it: Gesetz vom 5. Juli 2018 (GVBl. S. 462, Artikel 1: § 8), Gesetz
  vom 12. Oktober 2020 (GVBl. S. 807, Artikel 4: §§ 3, 4), Gesetz vom 17. Dezember 2020 (GVBl. S. 1485, Artikel 4:
  § 2 Abs. 5), Gesetz vom 27. September 2021 (GVBl. S. 1117, Artikel 13: § 8), Gesetz vom 10. Juli 2024 (GVBl.
  S. 465, Artikel 2: § 2 Abs. 2), Gesetz vom 11. Dezember 2025 (GVBl. S. 590, Artikel 5: § 8) and Gesetz vom
  1. April 2026 (GVBl. S. 158, Artikel 4: § 6 Abs. 2). None changes § 1. Read at
  https://pardok.parlament-berlin.de/starweb/adis/citat/VT/18/gvbl/g18180462.pdf,
  https://pardok.parlament-berlin.de/starweb/adis/citat/VT/18/gvbl/g20480807.pdf,
  https://pardok.parlament-berlin.de/starweb/adis/citat/VT/18/gvbl/g20611485.pdf,
  https://pardok.parlament-berlin.de/starweb/adis/citat/VT/18/gvbl/g21731117.pdf,
  https://pardok.parlament-berlin.de/starweb/adis/citat/VT/19/gvbl/g24280465.pdf,
  https://pardok.parlament-berlin.de/starweb/adis/citat/VT/19/gvbl/g25360590.pdf and
  https://pardok.parlament-berlin.de/starweb/adis/citat/VT/19/gvbl/g26110158.pdf.
- Hamburg. The Zwölftes Gesetz zur Änderung des Hamburgischen Verwaltungsverfahrensgesetzes vom 5. Mai 2025
  (HmbGVBl. Nr. 17 of 13 May 2025, S. 338) is in the block whole, up to its signature lines; it has no provision on
  its coming into force. Artikel 54 of the constitution is in the block. The gazette's subject index for 2025
  (https://www.luewu.de/wp-content/uploads/2026/02/GVBL-SV-2025.pdf) lists no other change to the act in 2025. Of
  the issues of 2026, Nr. 1 to 33 (https://www.luewu.de/gvbl/2026/), none changes the act; Nr. 17 cites it as
  "zuletzt geändert am 5. Mai 2025 (HmbGVBl. S. 338)".
- Hessen. § 41 is held as promulgated in the Bekanntmachung der Neufassung of 15 January 2010, and Abs. 2a as
  inserted by Artikel 2 Nr. 5 of the Act of 12 September 2018. Artikel 6 of that act (GVBl. 2018 Nr. 21, S. 576),
  not held in the block, reads: "Dieses Gesetz tritt am Tag nach der Verkündung in Kraft. Abweichend von Satz 1
  tritt Art. 3 am 1. Dezember 2018 in Kraft." Each later amending act cites the one before it:
  Gesetz vom 13. Dezember 2012 (GVBl. S. 622, Artikel 9: § 96), Gesetz vom 26. Juni 2015 (GVBl. S. 254), Gesetz vom
  12. September 2018 (GVBl. S. 570), Gesetz vom 16. Februar 2023 (GVBl. S. 78, 81) and the Erstes
  Bürokratieabbaugesetz vom 16. Dezember 2025 (GVBl. 2025 Nr. 110, Artikel 40: § 3a Abs. 4). Of these, only the act
  of 2018 changes § 41. Read at https://starweb.hessen.de/cache/GVBL/2012/00028.pdf,
  https://starweb.hessen.de/cache/GVBL/2015/00016.pdf, https://starweb.hessen.de/cache/GVBL/2023/00006.pdf and
  https://verkuendung.hessen.de/sites/verkuendung.hessen.de/files/veroeffentlichungsplattform_plugin/published/1239/GVBl_2025_Nr_110_Regelungstext.pdf;
  a search of that promulgation platform for the statute's classification number (FFN 304-18) finds no other act.
- Mecklenburg-Vorpommern. The provisions on coming into force of both acts are in the block: Artikel 4 of the Act of
  11 December 2024 (GVOBl. 2024 Nr. 27, S. 622) and Artikel 95 of the Erstes Gesetz zur Bürokratieentlastung of
  8 July 2026 (GVOBl. 2026 Nr. 21, S. 754). The opening sentence of the 2026 act's Artikel 1, also in the block,
  cites the statute in the wording of 6 May 2020 "das durch Artikel 1 des Gesetzes vom 11. Dezember 2024 (GVOBl. M-V
  S. 617) geändert worden ist". The issues read on the Landtag's document server are, of 2025, Nr. 2, 3, 5, 7 to 11,
  13, 15, 20, 23 and 26, and, of 2026, Nr. 2 to 5, 7, 9 to 18, 20 to 23 and 27 (issued 22 September 2026); none of
  them holds another act that changes the statute. Of the issues after Nr. 21 of 2026, Nr. 24, 25 and 26 and every
  issue after Nr. 27 were not read: they were not found on that server.
- Schleswig-Holstein. Artikel 2 of the Act of 13 December 2024 (GVOBl. 2024 Nr. 15, S. 936), on its coming into
  force, is in the block. The acts that changed the Landesverwaltungsgesetz after it change other provisions only:
  Gesetz vom 26. März 2025 (GVOBl. 2025/51), Gesetz vom 10. Juni 2025 (GVOBl. 2025/76), Gesetz vom 6. Oktober 2026
  (GVOBl. 2026/95) and the Gesetz zur Stärkung des Verfassungsschutzes im Lande Schleswig-Holstein vom 15. Oktober
  2026 (GVOBl. 2026/102 of 30 October 2026), whose Artikel 2 Abs. 2 changes § 181a Abs. 3 Satz 5 only. Each cites
  the one before it as the last change, except that the acts of 6 and of 15 October 2026 both cite the act of
  10 June 2025. Read at
  https://verkuendungsportal.schleswig-holstein.de/home/gvobl/veroeffentlichungen/2025/2025_juni/2025-76_juni12.pdf,
  https://verkuendungsportal.schleswig-holstein.de/home/gvobl/veroeffentlichungen/2026/2026_10/2026-102_oktober30
  and the same portal's pages for 2025/51 and 2026/95.
- Thüringen. Artikel 1 of the Act of 2 July 2024 (GVBl. 2024 Nr. 9, S. 277) is the Thüringer
  Verwaltungsverfahrensgesetz, printed whole; Artikel 90 (S. 297), on the act's coming into force, is in the block.
  The correction in GVBl. 2024 Nr. 11 p. 522 concerns its Artikel 8 only. The issues read since, 2024 Nr. 10 to 17,
  2025 Nr. 1 to 14 and 2026 Nr. 1 to 9, hold no change to the act. 2024 Nr. 12, issued on 30 August 2024
  (https://parldok.thueringer-landtag.de/ParlDok/dokument/99202), holds ordinances and one announcement only. GVBl.
  2025 Nr. 13 cites the act as "vom 2. Juli 2024 (GVBl. S. 277) in der jeweils geltenden Fassung".

The sha256 in the table is that of the Land's block: the lines from the Land's name to the last line before the
blank line that precedes the next Land's name (to the end of the file for the last Land), each ending in a line
break.

sha256 of `laender.txt`: `a03cc3666e9fb5334999d7429071224af3278dc27cff690d2d019ff18b9fa32b`

| Land | Statute | Provisions | Source | Retrieved | sha256 |
|---|---|---|---|---|---|
| Baden-Württemberg | Verwaltungsverfahrensgesetz für Baden-Württemberg (Landesverwaltungsverfahrensgesetz - LVwVfG) | §§ 41, 102b | https://www.landesrecht-bw.de/perma?d=jlr-NNLBW00007E83, https://www.landesrecht-bw.de/perma?d=jlr-NNLBW00007E83NN00000000103, https://www.landesrecht-bw.de/perma?d=jlr-NNLBW00007E83NN00000000202 | 2026-11-04 | `2aed656ef7576afe5c0d4e7445144a91ae178ac87c55654cbf8570555a84eae0` |
| Bayern | Bayerisches Verwaltungsverfahrensgesetz (BayVwVfG) | Art. 41, 98 | https://www.gesetze-bayern.de/Content/Document/BayVwVfG, https://www.gesetze-bayern.de/Content/Document/BayVwVfG-41, https://www.gesetze-bayern.de/Content/Document/BayVwVfG-98 | 2026-11-04 | `a575e54d129b0c4dbdc0af2bd2226c9cee9b7e3057d748568c603cd38dd9b7ae` |
| Berlin | Gesetz über das Verfahren der Berliner Verwaltung | § 1 | https://pardok.parlament-berlin.de/starweb/adis/citat/VT/17/gvbl/g16110218.pdf | 2026-11-04 | `ae0c38978fafe3dc943d04ce555ec87e03bde5cfbb79b76647e62af563ca0edd` |
| Brandenburg | Verwaltungsverfahrensgesetz für das Land Brandenburg (VwVfGBbg) | §§ 1, 7 | https://bravors.brandenburg.de/gesetze/vwvfgbbg | 2026-11-04 | `5aa4391e03a7d26f8243be8695fd20f0ca34afaac84f2ec65726665636e858a1` |
| Bremen | not retrieved | – | https://www.transparenz.bremen.de/, https://www.gesetzblatt.bremen.de/ | 2026-11-04 | `ea8e9191906c95e417efddbadbc925f72e9903261e86a35b26e16ea024732512` |
| Hamburg | Hamburgisches Verwaltungsverfahrensgesetz | Zwölftes Gesetz zur Änderung des Hamburgischen Verwaltungsverfahrensgesetzes; Artikel 54 (Verfassung) | https://www.luewu.de/wp-content/uploads/2025/08/GVBL_HH_2025-17.pdf, https://www.hamburgische-buergerschaft.de/resource/blob/1153290/c21dc133a3623d0684ecb939f48c0585/handbuch-2-februar-2026-data.pdf, https://www.luewu.de/wp-content/uploads/2026/02/GVBL-SV-2025.pdf | 2026-11-04 | `254ed304d573e97859beb72275b0a2dde07e3668036e8ac3a20deab67f939f7b` |
| Hessen | Hessisches Verwaltungsverfahrensgesetz (HVwVfG) | § 41; Artikel 2 (Nr. 5) | https://starweb.hessen.de/cache/GVBL/2010/00003.pdf, https://starweb.hessen.de/cache/GVBL/2018/00021.pdf | 2026-11-04 | `9664a5650965ee91e1539e7f2106328e22a141b479e189dfe93adb01a73cf8cf` |
| Mecklenburg-Vorpommern | Landesverwaltungsverfahrensgesetz | Artikel 1 (Nr. 14, 34); Artikel 4; Artikel 1 (Nr. 14); Artikel 95 | https://www.dokumentation.landtag-mv.de/parldok/dokument/63481, https://www.dokumentation.landtag-mv.de/parldok/dokument/72069 | 2026-11-04 | `d6db03b4abdcbdd0578b6ac6420808c0e9817f207574460cba0aa38bef33e036` |
| Niedersachsen | Niedersächsisches Verwaltungsverfahrensgesetz (NVwVfG) | § 1 | https://voris.wolterskluwer-online.de/browse/document/631d25e7-bc57-322f-8763-640c7c45a804, https://voris.wolterskluwer-online.de/browse/document/78aa978e-72b9-39a7-aee5-53b1567912f5 | 2026-11-04 | `4d597a4b7767f71db5e42bb2fe4496d7e860287c7eaa6b6acf0c747fc829a79a` |
| Nordrhein-Westfalen | Verwaltungsverfahrensgesetz für das Land Nordrhein-Westfalen (Verwaltungsverfahrensgesetz NRW – VwVfG NRW) | §§ 41, 97 | https://recht.nrw.de/lrgv/gesetz/01012025-verwaltungsverfahrensgesetz-fuer-das-land-nordrhein-westfalen | 2026-11-04 | `c61c2ddc3d4063fda0d585f8b6fddb799c879907e5047d022d3ebb6c1dc90101` |
| Rheinland-Pfalz | not retrieved | – | https://landesrecht.rlp.de/, https://gvbl.rlp.de/ | 2026-11-04 | `2dd8c6f637c36bb68f5a80aa009d512b6d0d25c80d81720d08f74254f10b5fd0` |
| Saarland | not retrieved | – | https://recht.saarland.de/, https://www.amtsblatt.saarland.de/, https://www.landtag-saar.de/, https://www.saarland.de/ | 2026-11-04 | `9c9ce60c7f471e9a4e05ea90065316477719fff3034c9ba77e0563dbaeeee178` |
| Sachsen | Gesetz zur Regelung des Verwaltungsverfahrens- und des Verwaltungszustellungsrechts für den Freistaat Sachsen (SächsVwVfZG) | § 1 | https://www.revosax.sachsen.de/vorschrift/11377-SaechsVwVfZG | 2026-11-04 | `a0c534eeee6d69102a996dc315a3de12d14152606b0894bc402e7f387f4a4a75` |
| Sachsen-Anhalt | not retrieved | – | https://www.landesrecht.sachsen-anhalt.de/, https://www.landtag.sachsen-anhalt.de/, https://padoka.landtag.sachsen-anhalt.de/ | 2026-11-04 | `b4d6aa36b8f467bfee6466d5f35cf1c32d7971d7db3528d9d957892a290984bf` |
| Schleswig-Holstein | Landesverwaltungsgesetz | Artikel 1 (Nr. 2); Artikel 2 | https://verkuendungsportal.schleswig-holstein.de/mm/gvobl_jahrgang_2024/II_GVOBl_Jahrgang_2024 | 2026-11-04 | `5e79d3c60914212c75a349278399e37ff6132ea559e9e10c94f2a5b144a3b7e1` |
| Thüringen | Thüringer Verwaltungsverfahrensgesetz (ThürVwVfG) | §§ 1, 8; Artikel 90 | https://parldok.thueringer-landtag.de/ParlDok/dokument/98016/gesetz_und_verordnungsblatt_nr_9_2024.pdf | 2026-11-04 | `7033df9fe5f023afd67cb0e9759f4491ca23a622fd0ad6a3a820d00d35f84573` |

### Not retrieved

Four of the sixteen Länder are not retrieved: Bremen, Rheinland-Pfalz, Saarland and Sachsen-Anhalt. Each Land's
portal was tried first (the first address in its row); for each of these four, the other addresses in its row, the
Land's gazette and its parliament or government, were tried next, on the day shown. Nothing else was used in their
place.

- Bremen: the portal and the gazette's site (www.gesetzblatt.bremen.de) both answered "403 Forbidden".
- Rheinland-Pfalz: the portal closed the connection before any answer, every time in 20 tries over about eight
  minutes. The gazette's site (gvbl.rlp.de, published by the Staatskanzlei) answered, but its archive begins with
  2004: the act of 23 December 1976 (GVBl. S. 308) is not in it, and no act found there gives the wording of its
  § 1 Abs. 1. The yearly indexes 2004 to 2025 and the half-year index 2026 name no act amending it in their titles;
  the one amendment read, § 48 of an act of 22 December 2015 (GVBl. 2015 Nr. 17), changes § 1 Abs. 3 only.
- Saarland: the portal, the gazette's site (www.amtsblatt.saarland.de) and the Landtag's site (www.landtag-saar.de)
  closed the connection before any answer; the government's site (www.saarland.de) answered "403 Forbidden".
- Sachsen-Anhalt: the portal closed the connection before any answer. The Landtag's site and its document server
  (padoka.landtag.sachsen-anhalt.de) answered, but no copy of the gazette was found on them.

A Landtag's record of an act as adopted, the bill and the vote, is not taken here, only a portal's or a gazette's
text: such records were read for Bremen (Bremische Bürgerschaft Drs. 21/299), Rheinland-Pfalz (Landtag Drs.
14/2221) and Sachsen-Anhalt (Landtag Drs. 4/1838 and 4/2412), whose gazettes could not be reached, and no text of
theirs is here.

### Limits

- Earlier wordings of the law, which are not here, are named in Baden-Württemberg's § 102b ("in der bis zum
  6. Februar 2025 geltenden Fassung"), Bayern's Art. 98 ("in der bis zum Ablauf des 31. Dezember 2024 geltenden
  Fassung"), Mecklenburg-Vorpommern's § 120a ("in der bis zum 31. Dezember 2024 geltenden Fassung"),
  Nordrhein-Westfalen's § 97 ("in der zum Zeitpunkt des Beginns des Verfahrensschritts jeweils geltenden
  Fassung") and Thüringen's § 8 ("nach den bisher geltenden Vorschriften", "nach den bisher geltenden
  Rechtsvorschriften").
- The sections held for Berlin, Brandenburg, Niedersachsen, Sachsen and Thüringen name the federal
  Verwaltungsverfahrensgesetz; its § 41 is in `vwvfg.txt`, in the wording that file's source gave on that file's day.
- A gazette gives an act as promulgated. Where a block holds amending provisions (Hamburg, Hessen's Abs. 2a,
  Mecklenburg-Vorpommern, Schleswig-Holstein), the section they change is not here in its consolidated wording; for
  Hamburg's § 41 Abs. 2 and Schleswig-Holstein's § 110 Abs. 2, only the words that the amendment replaces are.
- The federal act that Artikel 95 Abs. 5 of Mecklenburg-Vorpommern's act of 8 July 2026 names, "[Gesetz zur
  Fortentwicklung des Verwaltungsverfahrensgesetzes]", is not here.
- Letters of a Land's tax office: the Abgabenordnung is federal law (`ao.txt`). The section that sets its scope,
  § 1 AO, is not among the sections held.
- A portal shows the wording in force on the day it is read. What it gives as the day each provision took its
  present wording: Baden-Württemberg § 41 and § 102b "gültig ab: 07.02.2025"; Bayern "Text gilt ab: 01.01.2025",
  shown alike on the statute's front page and on the pages of Art. 41 and Art. 98; Nordrhein-Westfalen §§ 41 and 97,
  the footnotes in the file (1 January 2025); Niedersachsen § 1 "ab 01.10.2022 (aktuelle Fassung)"; Brandenburg and
  Sachsen give the statute's status only (the lines in the file).
