# Greek grey literature

Verified 2026-10-18. `gpl.py` queries automatically: openarchives.gr (MSc, diploma, PhD and untyped), didaktorika.gr, OpenAIRE, and DSpace repositories not well covered by openarchives (Amitos, IHU, Hellanicus, Dione, UTH, TEI West).

Cautions: many Greek hosts rate-limit/block fast clients (IKEE, UOWM blocked after ~25 probes) → 2–5 s between requests. Anubis bot walls: Pyxida, Estia, Pandemos, Dias, BASE. Unreachable from test machine: Olympias, Polynoe, NTUA, UOWM, HMU, Nefeli (retest from Greek network).

### Aggregators
- **openarchives.gr (EKT) — primary search, covers most repositories (metadata only)**
  `https://www.openarchives.gr/aggregator-openarchives/portal/advancedSearch/search?portalSearches%5B0%5D.keywords%5B0%5D.value=TERM&portalSearches%5B0%5D.ektTypes=http://semantics.gr/authorities/openarchives-item-types/metaptyxiakh-ergasia&page.page=1`
  - types: metaptyxiakh-ergasia (MSc), ptyxiakh-ergasia (diploma/BSc), PhD-thesis; 30/page
  - keywords[0].field = title | who | (empty = all)
  - collections incl.: IKEE_AUT, pergamos, ntua, phdtheses, uth_rep, rep_ihu, repo_duth, hypatia, pyxida, aua, nemertes, elocus, hellanicus, uoi, uowm, polynoe, dias, estia, psepheda, apothesis, eureka
  - NOT covered: Dione, Pandemos, Amitos, HMU, Ionian → query directly
  - JSON API exists (`.../api/search.json`) but needs personal key.
  - **Query syntax (tested 2026-10-19):** unquoted words are combined with AND ("Zelkova abelicea" → 2 relevant results). Quoted phrases behave like OR (“"Quercus abelicea"” → 266 unrelated). Send names unquoted.
- OpenAIRE Graph API (no key): `https://api.openaire.eu/graph/v1/researchProducts?search=TERM&instanceType=Master%20thesis&countryCode=GR&pageSize=100` (also "Bachelor thesis", "Doctoral thesis"); lower recall.
- BASE, CORE: not scriptable (IP whitelist / 403 / key).

### didaktorika.gr (PhD)
- DSpace 1.8. Search: `https://www.didaktorika.gr/eadd/simple-search?query=TERM&rpp=50&start=0` (/search disallowed by robots; simple-search not)
- Query syntax is the opposite of openarchives: unquoted words are OR-ed, and a quoted phrase is a phrase. Send names quoted.
- OAI-PMH: `https://www.didaktorika.gr/eadd_oai/request` (oai_dc, mods, …; ids `oai:10442/N`)
- PDFs CAPTCHA-gated → manual download.

### University repositories (botany-relevant in bold)
| University | Repository | URL | OAI-PMH | Direct search |
|---|---|---|---|---|
| **NKUA** | Pergamos | https://pergamos.lib.uoa.gr | /uoa/dl/frontend/oaipmh (sets born_digital_postgraduate_thesis, born_digital_graduate_thesis, born_digital_thesis) | JS-only; robots disallows /search |
| **AUTH** | IKEE (Invenio) | https://ikee.lib.auth.gr | /oai2d (X) | /search?p=TERM (X); throttle hard |
| **Patras** | Nemertes (DSpace 7.6) | https://nemertes.library.upatras.gr | /server/oai/request | – |
| ↳ ex-TEI W. Greece | | http://repository.teiwest.gr/xmlui/ | – | /xmlui/discover?query=TERM |
| **Crete** | E-Locus | https://elocus.lib.uoc.gr | /index.tkl | reCAPTCHA |
| **Ioannina** (+ex-TEI Epirus, Arta) | Olympias | https://olympias.lib.uoi.gr/jspui/ (X) | X | via OA `uoi` |
| **DUTH** (Forestry, Orestiada) | repo.lib.duth.gr | https://repo.lib.duth.gr/jspui/ | /oai/request (set Γεωπονίας & Δασολογίας) | 403 |
| **Thessaly** (+ex-TEI) | UTH IR | http://ir.lib.uth.gr/xmlui/ (http!) | http://ir.lib.uth.gr/oai/request | /xmlui/discover?query=TERM |
| **Aegean** | Hellanicus (DSpace 7.6) | https://hellanicus.lib.aegean.gr | https://hellanicus-api.lib.aegean.gr/server/oai/request | /search?query=TERM ; REST https://hellanicus-api.lib.aegean.gr/server/api/discover/search/objects?query=TERM&dsoType=ITEM |
| **AUA** (+ex-TEI Sterea, Karpenisi forestry) | DSpace@AUA | http://dspace.aua.gr | http://dspace.aua.gr/oai/request | UI broken |
| NTUA | DSpace | https://dspace.lib.ntua.gr/xmlui/ (X) | X | via OA `ntua` |
| Piraeus | Dione | https://dione.lib.unipi.gr/xmlui/ | /oai/request | /xmlui/discover?query= |
| Macedonia | Psephida | https://dspace.lib.uom.gr | /oai/request (curl UA) | – |
| Ionian | none | library.ionio.gr PDF lists; OPAC ionio-opac.seab.gr | – | – |
| Harokopio | Estia | https://estia.hua.gr (Anubis) | X | via OA `estia` |
| Panteion | Pandemos | https://pandemos.panteion.gr (Anubis) | X | – |
| AUEB | Pyxida | https://pyxida.aueb.gr | /server/oai/request (browser UA) | – |
| **Peloponnese** (Agric. Kalamata) | Amitos (DSpace 9.2) | https://amitos.library.uop.gr | /server/oai/request | REST /server/api/discover/search/objects?query=TERM&dsoType=ITEM |
| **W. Macedonia** (Agric. Florina) | DSpace UOWM | https://dspace.uowm.gr/xmlui/ (X) | X | via OA `uowm` |
| **IHU** (Agric. Sindos, Forestry Drama) | IHU Repository (DSpace 7.6) | https://repository.ihu.gr | https://repository-api.ihu.gr/server/oai/request | /search?query= ; REST at repository-api |
| West Attica | Polynoe (X); ex-TEI Athens Hypatia http://hypatia.teiath.gr (OAI /oai/request) | | | via OA `polynoe` |
| TU Crete | Dias (Anubis) | https://dias.library.tuc.gr | X | via OA `dias` |
| **HMU** (Agric. Heraklion) | Apothesis | https://apothesis.lib.hmu.gr (X, empty body) | X | – |
| Hellenic Open Univ. | Apothesis (Drupal) | https://apothesis.eap.gr | – | /archive/search?term= (AJAX); via OA `apothesis` |
| MAICh (CIHEAM Chania) | library catalogue only | http://library.maich.gr | – | manual |
| Goulandris NHM | OPAC only | https://library.gnhm.gr/webopac/Vubis.csp | – | manual |


## Society proceedings and journals **[auto: proceedings corpus]**

`gpl.py` downloads these once (`gpl.py corpus`), keeps only the extracted text in `~/.cache/greek-plant-localities/corpus/`, and searches them on every run like the floras. The list lives in `scripts/gplkit/textsearch.py` (`PROCEEDINGS`); add new volumes there.

- **HELECOS (Ελληνική Οικολογική Εταιρεία):**
  - 2nd–12th conferences (2004–2025) at `https://www.helecos.gr/el/activities/helecos-congresses/{YEAR}-{N}th-helecos-conference/{file}.pdf`.
  - No PDF for the 1st (2002).
  - The site search covers pages only, not PDFs.
- **Hellenic Botanical Society (ΕΒΕ):**
  - 5th–18th conferences (1994–2024) at `https://www.hbs.gr/sites/default/files/conferences/`; the conference list is at https://www.hbs.gr/el/conferences.
  - The 5th (1994) is a scan without a text layer, so it needs OCR.
  - The 1st–4th are not online.
  - The journal *Botanika Chronika* is print only.
- **Hellenic Forestry Society (ΕΔΕ, forestry.gr):**
  - The index is `https://www.forestry.gr/δημοσιεύσεις/πρακτικά-συνεδρίων/{year}`.
  - Most `/assets/pdf/praktika/` links return 404. Wayback Machine copies are used for 2015, 2018 and 2019 (parts 1–2); list them with `https://web.archive.org/cdx/search/cdx?url=forestry.gr/assets/pdf/praktika/&matchType=prefix`.
  - 2021 (Trikala) and 2023 are on a free host (`hexdec.xtreemhost.com`) that refuses non-browser clients, so download them by hand.
- **ΓΕΩΤΕΕ «Γεωτεχνικά Επιστημονικά Θέματα»** (2000–2026, about 46 issues): links are read from https://geotee.gr/geotechnika-epistimonika-themata/ at run time.
- **Not online:** Επιστημονική Επετηρίδα Τμ. Δασολογίας ΑΠΘ, «Δασική Έρευνα» (Forest Research Institute), the proceedings of the Range Science Society (Λιβαδοπονική Εταιρεία), and *Annales Musei Goulandris* (print only).

## Natura 2000 Special Environmental Studies (ΕΠΜ) — manual / ad hoc

- **Drafts for public consultation** are on the ΥΠΕΝ forum. The WordPress REST API lists the files without a key:
  - `https://ypen.gov.gr/diavouleusi/wp-json/wp/v2/media?search=EPM&per_page=100&page=N&_fields=source_url,date` (about 227 chapter PDFs, 2022–2026)
  - `https://ypen.gov.gr/wp-json/wp/v2/media?search=ΕΠΜ` (approved studies as ZIPs, e.g. `ΜΕΛΕΤΕΣ_ΕΠΜ_8Α.zip`, 72 MB)
- **What's useful:** chapter 3 (ΤΤΑ) lists the flora of the Habitats Directive, priority species and endemics per site, plus zoning and land-use maps. Locality detail is mostly at site level.
- **How they're organised:** by study group (region), not by site. To use them, find the study group covering the Natura sites in `natura2000_sites.csv`, then download only that group's chapter 3 and search it with `gpl.py run ... --pdf`.
- **robots.txt:** ypen.gov.gr has `Disallow: /*.pdf$`. Fetch single files on purpose; never crawl.

## Other registers

- **Forest management plans** (δασικές διαχειριστικές μελέτες) are not public. Only the approval acts are on Diavgeia: `https://diavgeia.gov.gr/opendata/search/advanced.json?q=subject:"διαχειριστικής μελέτης"&size=50`.
- **Environmental impact studies (ΜΠΕ):** the Ηλεκτρονικό Περιβαλλοντικό Μητρώο has an open JSON API, `https://api.eprm.ypen.gr/v1/license-decisions?page[number]=1&page[size]=50&filter[text_search]={term}`. It returns decision metadata, coordinates, a Natura flag and the Diavgeia PDF, but not the impact study itself. Text search covers titles only. Low value.
- **EU LIFE projects:** search at https://webgate.ec.europa.eu/life/publicWebsite/search. The API needs a session cookie and CSRF token, so use it manually. Greek plant-relevant projects:
  - LIFE04 NAT/GR/000104 CRETAPLANT (plant micro-reserves, Crete)
  - LIFE99 NAT/GR/006497 Rouva forest (*Zelkova*)
  - LIFE98 NAT/GR/005264 Vai (*Phoenix theophrasti*)
  - LIFE11 NAT/GR/001014 FOROPENFORESTS
  - LIFE07 NAT/GR/000286 PINUS (Parnonas)
  - LIFE12 NAT/GR/000539 JunEx
  - LIFE07 NAT/GR/000296 JUNICOAST
  - LIFE03 NAT/GR/000093 (Athos *Quercus frainetto*)
  - LIFE09 NAT/GR/000323 (Skyros)
  - LIFE16 NAT/GR/000606 (Andros)
  - LIFE94 NAT/GR/001201 (habitat and flora inventory)

  Detailed reports are usually only on the projects' own websites.

## Other full-text search endpoints

- **Internet Archive full-text search** (beta, unstable): `https://archive.org/services/search/beta/page_production/?user_query={q}&service_backend=fts&hits_per_page=50`. It also finds Greek Government Gazette (ΦΕΚ) issues. `advancedsearch.php` searches metadata only.
- **OpenAlex:** `filter=fulltext.search:{greek term},language:el` works for Greek-language papers, e.g. common names such as «ελάτη».
- **Zenodo:** Latin names only; Greek terms return almost nothing.
- **openarchives.gr:** adding `/json` to a record URI returns JSON-LD.

## Host status (from a Greek IP, 2026-10-19)

| Status | Hosts |
|---|---|
| Reachable | openarchives.gr; Polynoe; UOWM; HMU Apothesis (expired TLS certificate) |
| Reachable, but searches blocked by Anubis | IKEE |
| Timing out | Olympias (Ioannina), DSpace@NTUA, geodata.gov.gr |
| Renamed | hsgme.gr → www.eagme.gr |
