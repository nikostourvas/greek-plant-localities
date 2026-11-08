# Data sources: endpoints, limits, gotchas

Verified live on 2026-10-18. `gpl.py` already queries the sources marked **[auto]**; the others are for manual or ad-hoc use.
If an automatic source breaks (an API change), this file is the place to look first.

All endpoints tested live with curl unless marked X (unverified / unreachable from test machine).

## 0. Name resolution (always first — collect all synonyms)
- Flora of Greece CDM **[auto]** REST API (Dimopoulos et al. 2013/2016 checklist): https://api.cybertaxonomy.org/flora-greece/
  - `portal/taxon/find?query=<name>&doTaxa=true&doSynonyms=true&pageSize=10&pageIndex=0`
  - `portal/taxon/{uuid}/synonymy`
  - `portal/taxon/{uuid}/taxonRelationshipsDTO` → `relations` with `misapplication: true`: names misapplied to the taxon in Greek floras ("auct. fl. graec."); the name is in `taggedText` items of type `name` and `rank`. Not part of `/synonymy`.
  - `description/distributionInfoFor/{uuid}?part=tree` → presence per Greek floristic region (Pe, StE, SPi, NPi, NC, NE, IoI, EAe, WAe…)
  - No `.json` suffix (→400). Portal web UI is behind Anubis; use API host only.
- Euro+Med **[auto]**: https://api.cybertaxonomy.org/euromed/ (same CDM API; filter results by `class`)
- GBIF backbone **[auto]**: `https://api.gbif.org/v1/species/match?name=<name>&kingdom=Plantae` → usageKey (taxonKey includes synonyms)
  - The backbone sometimes treats a synonym, or a name misapplied in Greek floras, as a separate taxon (e.g. *Satureja graveolens* and *Thymus graveolens* for *Acinos graveolens*). `taxonKey=<main key>` misses records filed under those, so `occurrences.gbif` also queries their keys. Keys whose `speciesKey` is the main key are already covered.
  - Use `strict=true` and require `matchType` EXACT: "Acinos rotundifolius" otherwise matches only the genus *Acinos* (thousands of Greek records).
- Catalogue of Life (ChecklistBank, latest release `3LR`, WCVP-based) **[auto]**, no key:
  - `https://api.checklistbank.org/dataset/3LR/nameusage/search?q=<name>`: a synonym's usage carries its `accepted` usage
  - `/taxon/{id}`: rank and `parentId`
  - `/tree/{id}/children`: infraspecific taxa
  - `/taxon/{id}/synonyms`: `homotypic`, `heterotypic`, `misapplied`
  - WCVP often ranks a Flora of Greece species as a subspecies (e.g. *Acinos graveolens* = *Clinopodium graveolens* subsp. *graveolens*), so take the parent species and all its children.
- JACQ names **[auto]**: `https://services.jacq.org/jacq-services/rest/JACQscinames/find/<name>`
- WFO: https://list.worldfloraonline.org/matching_rest.php?input_string=… (broken TLS chain)
- POWO blocks scripts (Cloudflare); use WCVP dump / rWCVP. Global Names Verifier for fuzzy matching.

## 1. Specimen / occurrence databases
### GBIF **[auto]** (open API; scraping www.gbif.org NOT allowed)
- `https://api.gbif.org/v1/occurrence/search?taxonKey=<key>&country=GR&limit=300&offset=0`
- Filters: hasCoordinate=true, hasGeospatialIssue=false, basisOfRecord=PRESERVED_SPECIMEN; facet=institutionCode&limit=0
- limit ≤300; offset+limit ≤100,000. Set User-Agent with email. 429 under load. >15 min jobs → download API.
- Download API (POST /v1/occurrence/download/request) needs GBIF account; gives DOI that must be cited in publications.
- Also query WITHOUT country=GR (or geometry polygon): records with country "ZZ"/missing are missed (Zelkova: 7 of ~90).
- Coarse georeferencing common; check `issues`. Duplicates across herbaria and via JACQ BioCASe.
- Big herbaria with Greek material already in GBIF: B (+Willing) ~210k, LD (Strid) 129.5k, K 42.9k, BR 16.4k, W/WU 23k, P ~7k, E 4.9k, G 1.9k.
- R: rgbif; Python: pygbif.

### JACQ **[auto]** (open REST API, Swagger: https://services.jacq.org/jacq-services/rest/description/index.php)
- `https://services.jacq.org/jacq-services/rest/objects/specimens?term=<name>&nation=Greece&list=0&rpp=100&p=0`
- `nation` = English country name (undocumented; "GRC" → 0). list=0 for full records. rpp ≤100. `sc=` = herbarium code.
- No rate limits stated; robots allows all. Cite by CETAF stable ID (materialSampleID).
- Most of JACQ already in GBIF (W, WU, GJO, GZU, JE, PR, BRNU, HBG, PI, B). UNIQUE: UPA (Patras, ~3.3k), CBH (Kefalonia, 378), personal herbaria (e.g. HPILSL). → query with sc=UPA / sc=CBH, or all and dedupe.

### DiSSCo Hellas **[auto]** (https://dissco-gr.nhmc.uoc.gr) — UNIQUE data, not in GBIF
- Custom React SPA + open (undocumented) JSON API. robots.txt allows; Crawl-delay: 1.
- `https://dissco-gr.nhmc.uoc.gr/api/catalog?filter_genus=<Genus>&search=<epithet>&perPage=200` (+ page param; response has totalPages)
- `/api/catalog/record/{occurrenceID}`, `/api/catalog/statistics`, `/data/institutions/units.json`
- `search=` is full-text over all fields → always combine with filter_genus.
- Herbaria: HB-NKUA (ATHU, 69k), HB-AUTH (TAU, 71k), NMNHG (ATH/Goulandris, 92k), NHMC botany (7.8k), MAICH (12k). UPA registered, unpublished.
- Sensitive taxa: coordinates generalised (NHMC/NMNHG 7071 m = 10 km grid; HB-NKUA rounded 0.01°; "Precise locality withheld"). → email curators.
- Polite: UA with email, 1 req/s, cache, ask NHMC about terms.

### iNaturalist **[auto]** API v1 (https://api.inaturalist.org/v1/)
- ~1 req/s, ≤10k/day. CC research-grade already in GBIF; API adds ARR + needs-ID obs.
- Threatened taxa obscured to 0.2° cell (check `obscured`, `taxon_geoprivacy`).

### Others
- Geneva G catalogue (Boissier/Heldreich/Orphanides types): https://www.ville-ge.ch/musinfo/bd/cjb/chg/ (HTML, scrapable)
- EVA / GIVD vegetation plots (Hellenic Woodland DB, Hellenic Beech DB, VegHellas): on request.
- DiSSCo EU sandbox API: mirror of GBIF, not useful yet.
- Print-only: Strid Atlas of the Aegean Flora (2016), Mountain Flora of Greece, Flora Hellenica, Turland et al. 1993 (Crete).

### Index Herbariorum **[auto]** (NYBG; herbarium codes)
- `https://sweetgum.nybg.org/science/api/v1/institutions/<CODE>` → organization, address, irn (page: `https://sweetgum.nybg.org/science/ih/herbarium-details/?irn=<irn>`). The `?code=` filter on `/institutions` is ignored and returns all ~4900 herbaria.
- Database-specific names are mapped to IH codes in `gplkit/herbaria.py` (NHMW → W, NMNHG → ATH, HB-NKUA → ATHU, HB-AUTH → TAU, MNHN → P). Add new ones there.

### Genetic data **[auto]** (`gplkit/genetic.py`; no keys)
- ENA Portal API (all INSDC data: GenBank, ENA, DDBJ exchange daily, so NCBI E-utilities are not needed): `https://www.ebi.ac.uk/ena/portal/api/search?result=sequence|read_run|sample|assembly&query=tax_tree(<taxid>)&fields=...&format=json`. Field names via `/returnFields?result=...`; `sequence` has `location` ("41.2 N 26.3 E"), not `lat`/`lon`. `country` is often empty: the publication title (`/ena/browser/api/embl/<acc>`, `RT` lines; not `RL`, which is the submitter address) often names the place.
- ENA taxonomy `ena/taxonomy/rest/any-name/<name>` does not resolve synonyms (Acinos graveolens → nothing; Clinopodium graveolens → 751796), so every core name is looked up.
- Names for sequence databases (`genetic.sequence_names`, `taxids`): INSDC and BOLD match bare names, so a synonym that is also another species' name brings in that species (first batch run: 123 *Centaurea horrida* Badarò sequences for *C. calcitrapa*, all *Orchis militaris* WGS for *O. italica*). Skipped: names only misapplied in Greek floras; names with *nom. illeg.* in a Flora of Greece/Euro+Med full name; binomials with an `ACCEPTED` GBIF backbone usage (`/v1/species?name=&datasetKey=<backbone>`) whose `constituentKey` is the Catalogue of Life and whose authors share none with the curated name. IPNI and WoRMS usages in the backbone are all `ACCEPTED`, including obscure later homonyms (*Thymus alpinus* Pall.), so they are ignored. NCBI's `authority` does not help: it gives *C. horrida* Ten. for the Sardinian sequences. Also skipped: a synonym whose ENA taxonomy hit is another species (*Coronilla parviflora* → *Securigera parviflora*); a variety of the species itself is kept (*Crataegus azarella* → *C. monogyna* var. *monogyna*).
- Segregates are kept: a name that the curated floras sink into the taxon but specialists accept (*Alyssum spruneri* Jord. & Fourr. = *A. montanum* subsp. *montanum* in Flora of Greece) has the same author everywhere, so it is not a homonym.
- BOLD v5 public portal API: `portal.boldsystems.org/api/query/preprocessor?query=tax:<name>` → `api/query?query=<matched>&extent=full` → `query_id` → `api/documents/<query_id>/download?format=tsv`. The v4 API (`v4.boldsystems.org/index.php/API_Public/...`) is offline. BOLD mines GenBank (process IDs `GBxxx`): de-duplicated against ENA via `insdc_acs`. BOLDconnectR (R) needs an API key; the portal API does not.
- GBIF: `isSequenced=true`; DNA-derived-data extension (`target_gene` = MIxS 0000044) and GGBN extensions (`dwcaExtension=http://data.ggbn.org/schemas/ggbn/terms/MaterialSample`) mark sequenced records and DNA-bank samples; `fieldNumber` matches BOLD `fieldid`.
- Origin of INSDC records: the `country` field is free-ish text. Placeholders ("missing", "not collected") mean unknown; localities also end up there ("Avdou", a village on Crete), so a value that is not a country name (GBIF's country list plus INSDC spellings such as USA, Russia, Turkey) is looked up in Nominatim within Greece.
- GGBN API (`www.ggbn.org/ggbn_portal/api/search?getSampletype&name=<genus>`): counts only, no records; species names unknown to GGBN return an HTML page.

## 2. Conservation / monitoring
- Red Data Book **[auto]** of Rare & Threatened Plants of Greece (Phitos et al. 2009) on Plazi (146 treatments, CC0): https://treatment.plazi.org/GgServer/summary/FFAEB063BD0FFFBDD906FF87393BFF92
- Natura 2000 (EEA) **[auto]** SDF tables + GeoPackage; species per site (no points). ArcGIS REST: bio.discomap.eea.europa.eu/.../Natura2000Species/MapServer
- Article 17 **[auto]** 10×10 km grids (EEA catalogue 9f71b3e3-f8ec-442b-a2d5-c3c190605ac4); sensitive species removed in public version. Web: https://nature-art17.eionet.europa.eu/article17/
- NECCA/OFYPEKA: https://necca.gov.gr/wp-json/wp/v2/endangered-species (WordPress JSON). Monitoring data not public → request.
- IUCN Red List API v4 (free token, no redistribution).
- Filotis (https://filotis.itia.ntua.gr/) — old biotope DB.

## 3. Literature
- Plazi TreatmentBank **[auto]**: `https://tb.plazi.org/GgServer/search?fullText.ftQuery=<name>&resultFormat=json` (CC0; material citations with localities)
- **[auto]** Internet Archive OCR (no key): Halácsy Conspectus Florae Graecae `archive.org/download/conspectusflorae01hal/conspectusflorae01hal_djvu.txt` (vols 1–3); Boissier Flora Orientalis.
- BHL API v3: free key required; website bot-walled.
- Journals: Phytologia Balcanica (https://phytolbalcan.arphahub.com/, "New floristic records in the Balkans"), Willdenowia (BioOne OA; Euro+Med Notulae), Bocconea / Flora Mediterranea (https://www.herbmedit.org/). Botanika Chronika: no online archive found.
- **[auto: OpenAlex, Zenodo]** OpenAlex (free key), Crossref (mailto), Zenodo, DataCite APIs. Semantic Scholar 429 without key. Google Scholar: no automated access.
- User's own Zotero library (zotero MCP) and Consensus MCP.

## 5. Georeferencing / pre-sampling
- Pandektis "Name Changes of Settlements in Greece": https://pandektis.ekt.gr/pandektis/handle/10442/4968 (old Ottoman/Slavic/Arvanitic → modern names)
- GeoNames API (own free username), Nominatim (≤1 req/s, no bulk), Wikidata SPARQL
- Copernicus DEM GLO-30 (AWS), Copernicus Land, EGDI geology 1:1M; HSGME 1:50k sheets (mostly paid)
- ELSTAT settlement lists

## 6. Manual follow-ups (not scriptable)
- Email curators ATHU, TAU, ATH (Goulandris), NHMC, MAICH, UPA for precise coordinates of sensitive taxa
- NECCA monitoring data request; EVA plot data request
- Print atlases (Strid), floras
