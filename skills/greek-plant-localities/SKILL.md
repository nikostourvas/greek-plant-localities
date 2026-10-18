---
name: greek-plant-localities
description: Find every known locality of a plant species in Greece in order to plan field sampling. Searches GBIF, the DiSSCo Hellas national herbaria node, JACQ and iNaturalist, plus Natura 2000 and Article 17 data. Also searches Greek theses (openarchives.gr, didaktorika.gr, university repositories), Plazi, OpenAlex, Zenodo, classic floras (Halácsy, Boissier), the proceedings of the Greek ecological, botanical and forestry societies, and the user's own flora PDFs and Zotero collections. Then georeferences literature localities and writes a CSV, GeoPackage, KML, GPX and Markdown report of candidate sites.
when_to_use: The user wants to know where a plant (vascular plant, usually rare, endemic or threatened) grows in Greece, wants candidate populations or sampling sites, or asks to plan a sampling campaign or fieldwork for a species in Greece.
argument-hint: "<species name>"
allowed-tools: Bash(uv run ${CLAUDE_SKILL_DIR}/scripts/gpl.py *)
---

# Greek plant localities

Give it a species name. It runs a full automatic search for all known Greek localities and produces field-ready outputs.
The scripts do the deterministic part: querying APIs, deduplicating, writing files.
You do the judgement part: reading floras and theses, georeferencing, recommending sites.

`GPL` below means: `uv run ${CLAUDE_SKILL_DIR}/scripts/gpl.py`. It needs [uv](https://docs.astral.sh/uv/). If `uv` is missing, tell the user to install it with `curl -LsSf https://astral.sh/uv/install.sh | sh` and stop. Python dependencies install automatically on first run.

## Step 0: configuration (first run only)

Run `GPL config`. If it printed `saved ...`, no config existed before. In that case ask the user these questions **once, in a single message**:

1. A contact email. It goes in the User-Agent; GBIF, Nominatim and OpenAlex ask for one.
2. Optionally, a GeoNames username. It is free at geonames.org and must be enabled for web services. GeoNames knows mountains, gorges and peaks much better than OSM.
3. Optionally, a free OpenAlex API key (openalex.org/settings/api). Without one, OpenAlex shares a small daily budget with everyone on the same IP address and may refuse requests.
4. **Do they have private copies of floras, atlases, red lists, habitat manuals or reports?** For example *Mountain Flora of Greece*, *Flora Hellenica*, the *Atlas of the Aegean Flora*, or the Greek habitat interpretation manual. Ask either way:
   - Zotero collection names. These are read directly from `zotero.sqlite`, and subcollections are included.
   - Folders or files of PDFs.

   These are searched locally only and never uploaded or shared.
5. Where to save results. The default is `~/greek-plant-localities/`.

Save the answers with `GPL config --email ... [--geonames ...] [--openalex-key ...] [--add-zotero "Collection"] [--add-pdf /path] [--output-root ...]`.
Then start `GPL corpus` in the background. It is a one-off download of the public proceedings corpus (HELECOS, Hellenic Botanical and Forestry Societies, ΓΕΩΤΕΕ; about 80 PDFs), and only the extracted text is kept.
After that, never ask again; runs are fully automatic.
The config file is `~/.config/greek-plant-localities/config.json`.

## Step 1: run the automatic search

```bash
GPL run "Genus species [subsp. x]"     # add --pdf <file|dir> for one-off extra PDFs
```

Run it in the background. It takes about 5–25 minutes because Greek repositories are queried slowly on purpose (they block fast clients). The first run takes about 10 minutes longer if `GPL corpus` has not finished. HTTP responses are cached for 14 days, so re-runs are fast.

It writes to `<output_root>/<Genus_species>_<date>/`:

| file | content |
|---|---|
| `names.json` | accepted name, synonyms, Greek floristic regions (Flora of Greece), GBIF key |
| `occurrences.csv` | GBIF + DiSSCo Hellas + JACQ + iNaturalist records in one schema; `dup_group`/`is_primary` mark duplicates |
| `natura2000_sites.csv` | Natura 2000 sites whose Standard Data Form lists the species (population, data quality) |
| `art17_grid.geojson` | Article 17 2019–2024 10 km distribution (Habitats Directive species only) |
| `text_hits.md` / `.json` | passages that mention any of the names, from: the user's flora PDFs and Zotero; Halácsy and Boissier; the proceedings of HELECOS and the Hellenic Botanical and Forestry Societies; and ΓΕΩΤΕΕ |
| `leads.csv` | theses, papers, treatments and datasets that mention the species |
| `literature_localities.csv` | **empty; you fill it** (steps 2–4) |
| `candidate_sites.csv` | 1 km clusters of precise records: candidate sampling sites |
| `candidate_areas.csv` | 10 km clusters including generalised records: where the species is known but no precise site is published |
| `<sp>.gpkg`, `<sp>.kml`, `<sp>_sites.gpx`, `report.md` | built outputs (GeoPackage for QGIS; KML for Google Earth or a phone; GPX for GPS units) |
| `sources_log.csv` | per-source status; check it for failures |

Before going on, check `names.json`:
- If Flora of Greece did not find the taxon (`flora_of_greece.found` is false), or GBIF's `matchType` is not `EXACT`, tell the user which name was used.
- If the species is not in Greece according to Flora of Greece, say so but continue.

Then check `sources_log.csv`. If a source failed with a timeout or a 5xx error, re-run once with `--out <run_dir>` and `--skip` for the sources that worked. For example, `--skip occurrences,natura,text` re-runs only the literature search, and the cache makes the rest instant.

## Step 2: extract localities from the flora text hits

Read `text_hits.md`. Each block is a passage that starts at a mention of the species. For each block:
- **Is it the species' own entry,** or only a mention, such as "in *Abies cephalonica* woodland" in another species' habitat? Skip mentions.
- **Pull out every locality.** In the Strid floras, localities are listed by region (PELOPONNISOS:, STEREA ELLAS:, S PINDHOS: …), usually as mountain names. A `!` means the authors saw a specimen. Note the altitude range and habitat; they help you place points.
- **For Halácsy and Boissier:** these give 19th-century localities with the collector, e.g. "Heldr.!" or "Orph.!". They are valuable for finding historic populations again.
- **Add one row per locality to `literature_localities.csv`.** Columns: `locality, latitude, longitude, uncertainty_m, georef_method, source_ref, page, year, collector_or_author, notes`. Georeference as described in step 4.

Many hits are long. Read the context in full; locality lists often come after a long description.
For widespread species `text_hits.md` can be large. Read it in parts (it is grouped by source), floras first, then proceedings.

## Step 3: work through the literature leads

Open `leads.csv`.

**Rank the leads by likely locality content:**
1. Theses or papers on the species itself.
2. Floristic studies of a specific area within the species' range.
3. Vegetation or habitat studies.
4. Anything else.

For a rare taxon, look at every lead. For a widespread one, look at the top 30–40.

**For each promising lead:**
- **openarchives.gr records:** fetch the record page (WebFetch is fine). It links to the source repository record, which has the abstract and often an open PDF.
- **Fetching PDFs:** download with `curl` into the run directory's `pdfs/` folder, waiting at least 3 s between requests to the same Greek host.
- **Searching the PDFs:** run `GPL run "<species>" --out <run_dir> --skip occurrences,natura,literature --pdf <run_dir>/pdfs`. This searches them like the floras and adds them to `text_hits.md`.
- **didaktorika.gr PhD theses:** the PDFs are behind a CAPTCHA. Read the abstract on the record page and list the thesis under manual follow-ups.
- **Plazi treatments** (`treatment.plazi.org/id/...`): fetch them. Material citations hold localities. If the kind is "Red Data Book of Greece", the treatment has the distribution and threats; quote the key facts in the report.
- **Natura 2000 Special Environmental Studies (ΕΠΜ):** for a rare species, check the ΕΠΜ chapter 3 (flora) of the study group covering the Natura sites in `natura2000_sites.csv`. How to find it is in `references/greek-grey-literature.md`. Download that chapter only; never crawl ypen.gov.gr.
- **Conference abstracts in `text_hits.md`:** HELECOS and Hellenic Botanical Society abstracts often give a locality and an author to contact. The authors of recent abstracts are good people to ask about precise sites.
- **Leads with no access:** record them as manual follow-ups (title + URL). Do not guess their content.

Add the localities you extract to `literature_localities.csv`. Put the reference in `source_ref`, e.g. "Kozlowski 2012 MSc AUTH" or "Strid & Tan 1986: 123".

## Step 4: georeferencing

For records without coordinates (literature rows, and the important coordinate-less rows in `occurrences.csv`):

1. Run `GPL geocode "<name>" "<Greek spelling>" "<variant>"`. Try the transliteration variants (Chelmos / Helmos / Χελμός; Killini / Kyllini / Ziria) and the feature type ("Oros Chelmos").
2. **Old or renamed places** (Ottoman, Slavic or Arvanitic names on 19th–20th century labels): look them up in EKT Pandektis, "Name changes of settlements in Greece": https://pandektis.ekt.gr/pandektis/handle/10442/4968. Fetch it with WebFetch.
3. **Choose the candidate** that matches the region, the altitude and habitat in the source, and the species' known range (the regions in `names.json`).
4. **Uncertainty** (point-radius method): give the radius that covers the described place.

   | Description | Typical uncertainty |
   |---|---|
   | Summit or precise feature | 500–1000 m |
   | Village "near X" | 2–5 km |
   | Gorge or plateau | 1–5 km |
   | Mountain massif | its radius, often 5–15 km |
   | Island | its radius |

   Add uncertainty for vague wording.
5. **Record the method** in `georef_method`, e.g. "GeoNames 262178 summit; radius = massif".
6. **Never invent coordinates.** If you cannot place a locality with confidence, leave latitude and longitude empty; the row still appears in the report.

## Step 5: build and write the synthesis

```bash
GPL build <run_dir>
```

This rebuilds `candidate_sites.csv`, the GeoPackage, the KML/GPX and `report.md`, merging in your `literature_localities.csv`.

Then write the synthesis in `report.md`, **only between the markers `<!-- CLAUDE-SYNTHESIS-START -->` and `<!-- CLAUDE-SYNTHESIS-END -->`**. That text survives rebuilds; anything else you write is overwritten.

**Contents of the synthesis:**
- **Distribution summary:** regions, mountains or islands, altitude range and habitat, with how recent and how reliable the evidence is.
- **Recommended sampling sites, ranked.** The site table is in `candidate_sites.csv`. Favour these:
  - recent records
  - several independent sources
  - precise coordinates
  - sites that cover the geographic and environmental range (for population genetics: spread across regions and isolated populations)

  For each site give the site id, area, best evidence, and practical notes such as the Natura 2000 site, the altitude, and whether it's a historic record still to be confirmed.
- **Gaps:** regions known only from old records or from generalised coordinates (`candidate_areas.csv` areas with no candidate site). These are worth confirming or asking curators about.
- **Manual follow-ups:**
  - curators to email about withheld coordinates (DiSSCo Hellas generalises sensitive taxa to 10 km)
  - CAPTCHA-protected PhD theses
  - print sources that aren't available
- **Permits:** the species' protection status (Red Data Book, Habitats Directive annex, P.D. 67/1981 if relevant) and any permits needed.

Finally, tell the user:
- where the outputs are
- the headline numbers: records, unique localities, candidate sites, theses found
- the 3–5 best sites
- what needs manual follow-up

Keep it short; the report has the detail.

## Rules

- **Precise localities of threatened taxa are sensitive.** The outputs are for the user's own fieldwork; remind them not to publish exact coordinates. Do not upload the outputs anywhere.
- **Private PDFs never leave the machine.** Quote only the short passages needed for the report.
- **Respect the sources.** Don't remove the throttling in `scripts/gplkit/net.py`. Don't scrape Google Scholar, ResearchGate or www.gbif.org. If a host blocks the client, record it and move on.
- **Results that will be published** need a GBIF download with a DOI (GBIF account required), not the search API. Mention this when relevant.
- **Background on each source:** endpoints, limits and gotchas are in `references/sources.md`. Greek repositories, and what to do when the automatic search misses them, are in `references/greek-grey-literature.md`.
