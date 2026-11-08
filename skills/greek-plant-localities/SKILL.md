---
name: greek-plant-localities
description: Find every known locality of a plant species in Greece in order to plan field sampling. First collects all the names the taxon has been recorded under (synonyms and names misapplied in Greek floras, from Flora of Greece, Euro+Med, GBIF and the Catalogue of Life), then searches all of them in GBIF, the DiSSCo Hellas national herbaria node, JACQ and iNaturalist, plus Natura 2000 and Article 17 data. Also searches Greek theses (openarchives.gr, didaktorika.gr, university repositories), Plazi, OpenAlex, Zenodo, classic floras (Halácsy, Boissier), the proceedings of the Greek ecological, botanical and forestry societies, and the user's own flora PDFs and Zotero collections. Then georeferences literature localities and writes a CSV, GeoPackage, KML, GPX and Markdown report of candidate sites.
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

## Step 1: find all the names first

Herbarium labels, floras and theses often use old or misapplied names, so collect every name before searching.

```bash
GPL names "Genus species [subsp. x]"
```

It prints the accepted name (Flora of Greece) and a table of every name with its kind and source:
- **core** names are used by every search, including the slow Greek repository searches:
  - Flora of Greece and Euro+Med synonyms
  - names that Flora of Greece says were **misapplied in Greek floras** ("auct. fl. graec."). Greek literature and herbaria often file the taxon under exactly these names, e.g. *Acinos rotundifolius* and *Calamintha exigua* for *Acinos graveolens*.
- **extended** names are used only by the fast searches (GBIF, DiSSCo Hellas, JACQ, Natura 2000, full text): GBIF and Catalogue of Life (WCVP) synonyms, including the synonyms of subspecies.
- **Sequence databases** (ENA/GenBank, BOLD) match bare names, so they get the core names minus those that would bring in another species: names only misapplied in Greek floras, later homonyms (*nom. illeg.*), binomials that the Catalogue of Life also accepts as a species of other authors (*Centaurea horrida* Ten., a synonym of *C. calcitrapa*, vs the Sardinian *C. horrida* Badarò), and names that NCBI files under another species. Each skipped name is listed in the report's source table; names added by hand are always searched.

Review the list:
- **Warnings.** If Flora of Greece does not know the name, or GBIF's match is not `EXACT`, tell the user which name is used. If Flora of Greece gives no Greek distribution, say so but continue.
- **Add missing names** with `--add-name "<name>"` (repeatable):
  - every name the user gave
  - names you can source as used for this taxon in Greek literature but missing from the table, e.g. a combination used by Halácsy, Boissier or Hayek, the Flora Europaea or Med-Checklist name, or a recent recombination.

  Don't add names from memory alone. Say where each added name comes from.
- **Drop** with `--drop-name "<name>"` an extended name that clearly belongs to another taxon that is common in Greece (a homonym). Such a name would flood the text hits.
- To preview a change, run `GPL names "<species>" --add-name ... --drop-name ...`.

Then tell the user in one or two lines which names will be searched: the accepted name, how many synonyms, the misapplied names, and anything you added. Continue without waiting for an answer.

Added and dropped names are saved in the run directory's `run.json` (`names`) and reused by later runs into the same directory, so pass them once.

## Step 2: run the automatic search

```bash
GPL run "Genus species [subsp. x]" [--add-name "..."] [--drop-name "..."]   # add --pdf <file|dir> for one-off extra PDFs
```

Run it in the background. It takes about 5–25 minutes because Greek repositories are queried slowly on purpose (they block fast clients). The first run takes about 10 minutes longer if `GPL corpus` has not finished. HTTP responses are cached for 14 days, so re-runs are fast.

It writes to `<output_root>/<Genus_species>_<date>/`:

Twelve files and a `pdfs/` folder:

| file | content |
|---|---|
| `report.md` | the report; your synthesis goes between its markers (step 6) |
| `<sp>.gpkg` | GeoPackage for QGIS: candidate sites and areas, occurrences split by how far to trust the point (`occurrences_precise`, `_placed`, `_approximate`), `sequences`, Natura 2000 centroids, Article 17 grid, and the attribute table `herbaria` (what the Index Herbariorum codes stand for: B = Berlin, K = Kew, LD = Lund …) |
| `<sp>.kml` | the same for Google Earth or a phone. Colour = trust in the point (orange or magenta precise, blue placed from the locality text, grey generalised or > 5 km); filled circle = a specimen exists, open diamond = observations or literature only; purple stars = sequences |
| `<sp>.gpx` | for GPS units: candidate sites (red) and placed (blue) or approximate (green) pins; flag = specimen exists, pin = none; `type` says which |
| `sites.csv` | all candidate sites (`kind` = site: 1 km clusters of precise records) and areas (`kind` = area: 10 km clusters, generalised records included). `herbaria` / `n_vouchered`: where specimens from the site are kept. Genetic data in two kinds: `dna_same_specimens` (made from the site's own specimens) and `dna_nearby` (only coordinates within 1 km, 10 km for areas; not the same plants) |
| `occurrences.csv` | GBIF + DiSSCo Hellas + JACQ + iNaturalist records in one schema; `dup_group`/`is_primary` mark duplicates |
| `sequences.csv` | all genetic data found for the names, worldwide: ENA/GenBank sequences, read runs, samples and assemblies, and BOLD barcodes (public, no key). `origin`: Greece; Greece (publication) when only the paper's title names the place; possibly Greece (coordinates); foreign; unknown. `match`: **same specimen** (identifier: voucher, catalogue number, or collector + field number; `match_basis` says which), **nearby** (only coordinates, with `distance_m`), or not matched |
| `natura2000.csv` | Natura 2000 sites whose Standard Data Form lists the species (population, data quality) |
| `leads.csv` | theses, papers, treatments and datasets that mention the species; `genetic` flags genetic studies |
| `text_hits.md` | passages that mention any of the names, from: the user's flora PDFs and Zotero; Halácsy and Boissier; the proceedings of HELECOS and the Hellenic Botanical and Forestry Societies; and ΓΕΩΤΕΕ |
| `georeferenced.csv` | **you fill it** (steps 3–5): every point you place. Rows **without** `record_id` are localities from floras and papers; rows **with** a `record_id` are pins (or corrections) for records in `occurrences.csv`. It survives re-runs |
| `run.json` | `names` (accepted name, every searched name with kind and source, names added or dropped by hand, Greek floristic regions, GBIF key), `ggbn` (DNA-bank counts), `art17` (grid, if any) and `sources` (per-source status) |

Folders from before 2026-11-06 (20 files) are converted to this layout on the next `run` or `build`.

Then check the source log at the end of `report.md` (also `run.json`, `sources`). A host that fails 2 requests in a row (timeouts or 5xx) is skipped for the rest of the run, and the log says so. If a source failed this way, re-run once with `--out <run_dir>` and `--skip` for the sources that worked; if it fails again, list it under manual follow-ups. For example, `--skip occurrences,natura,text` re-runs only the literature search, and the cache makes the rest instant.

**Genetic data.** Read the "Genetic data" section of `report.md`. Keep its two kinds of match apart in everything you write: **same specimen** means the site is sequenced; **nearby** means only that a population close by was sequenced (give the distance), not these plants. For sequences "not at a candidate site", check the publication or voucher where it is quick (a paper's sample table often gives the populations), and say in the synthesis which regions are already sequenced, with which markers, and by whom; genome-scale data (runs, assemblies) deserve a mention. GGBN gives genus counts only; mention them if DNA or tissue samples exist.

## Step 3: extract localities from the flora text hits

Read `text_hits.md`. Each block is a passage that starts at a mention of the species. For each block:
- **Is it the species' own entry,** or only a mention, such as "in *Abies cephalonica* woodland" in another species' habitat? Skip mentions.
- **Is the name used for this taxon?** A misapplied name refers to it only in Greek floras. Elsewhere, for example *Acinos exiguus* in Cyprus, it is the other taxon. A homonym among the extended names can also match an unrelated plant.
- **A name missing from the list?** Floras, Halácsy and Boissier above all, sometimes file the taxon under a name that is not in the name list (`run.json`, `names`). Search it too with `GPL run "<species>" --out <run_dir> --add-name "<name>"`. Cached queries replay instantly, so only the new name is actually queried.
- **Pull out every locality.** In the Strid floras, localities are listed by region (PELOPONNISOS:, STEREA ELLAS:, S PINDHOS: …), usually as mountain names. A `!` means the authors saw a specimen. Note the altitude range and habitat; they help you place points.
- **Note the voucher.** When the source cites a specimen, fill `herbarium` with the Index Herbariorum code(s) where it is kept ("LD", "K, LD"; "?" for a `!` that doesn't say where). Fill `voucher` with what identifies it: collector, number, year, or an exsiccata such as "Heldr. herb. norm. 619". Leave both empty for sight records and plain locality lists. These rows count as vouchered localities.
- **For Halácsy and Boissier:** these give 19th-century localities with the collector, e.g. "Heldr.!" or "Orph.!". They are valuable for finding historic populations again.
- **Add one row per locality to `georeferenced.csv`, with `record_id` empty.** Columns: `record_id, locality, latitude, longitude, uncertainty_m, georef_method, source_ref, page, year, collector_or_author, herbarium, voucher, notes`. Georeference as described in step 5.

Many hits are long. Read the context in full; locality lists often come after a long description.
For widespread species `text_hits.md` can be large. Read it in parts (it is grouped by source), floras first, then proceedings.

## Step 4: work through the literature leads

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
- **Natura 2000 Special Environmental Studies (ΕΠΜ):** for a rare species, check the ΕΠΜ chapter 3 (flora) of the study group covering the Natura sites in `natura2000.csv`. How to find it is in `references/greek-grey-literature.md`. Download that chapter only; never crawl ypen.gov.gr.
- **Conference abstracts in `text_hits.md`:** HELECOS and Hellenic Botanical Society abstracts often give a locality and an author to contact. The authors of recent abstracts are good people to ask about precise sites.
- **Leads with no access:** record them as manual follow-ups (title + URL). Do not guess their content.

Add the localities you extract to `georeferenced.csv` (`record_id` empty). Put the reference in `source_ref`, e.g. "Kozlowski 2012 MSc AUTH" or "Strid & Tan 1986: 123".

## Step 5: georeferencing

For records without coordinates: literature rows, and the coordinate-less rows in `occurrences.csv`. Place every record whose locality text allows it, not just the important ones. Each placed record becomes a blue pin in the maps, so the user can see in the field where old or vague records probably were.

1. Run `GPL geocode "<name>" "<Greek spelling>" "<variant>"`. Try the transliteration variants (Chelmos / Helmos / Χελμός; Killini / Kyllini / Ziria) and the feature type ("Oros Chelmos").
2. **Old or renamed places** (Ottoman, Slavic or Arvanitic names on 19th–20th century labels): look them up in EKT Pandektis, "Name changes of settlements in Greece": https://pandektis.ekt.gr/pandektis/handle/10442/4968. Fetch it with WebFetch.
3. **Choose the candidate** that matches the region, the altitude and habitat in the source, and the species' known range (the regions in the report, or `run.json` → `names`).
4. **Uncertainty** (point-radius method): give the radius that covers the described place.

   | Description | Typical uncertainty |
   |---|---|
   | Summit or precise feature | 500–1000 m |
   | Village "near X" | 2–5 km |
   | Gorge or plateau | 1–5 km |
   | Mountain massif | its radius, often 5–15 km |
   | Island | its radius |

   Add uncertainty for vague wording.
5. **Record the method** in `georef_method`, e.g. "GeoNames 262178 summit; radius = massif". If a paper prints coordinates, start `georef_method` with "source" (e.g. "source: UTM given"); the row is then treated as precise, not placed.
6. **Where the pin goes:**
   - literature localities: `georeferenced.csv`, `record_id` empty;
   - records already in `occurrences.csv`: a row in `georeferenced.csv` with their `record_id` (fill `latitude, longitude, uncertainty_m, georef_method, notes`). Use the same file to correct wrong coordinates (e.g. a mistyped latitude): start `georef_method` with "source" so that the record stays precise, and explain the correction. It survives re-runs, which rewrite `occurrences.csv`.
7. **Never invent coordinates.** If you cannot place a locality with confidence, leave latitude and longitude empty; the row still appears in the report. Records that name only a country, a large island or a region (radius above ~25 km) aren't worth a pin.

## Step 6: build and write the synthesis

```bash
GPL build <run_dir>
```

This rebuilds `sites.csv`, the GeoPackage, the KML, the GPX and `report.md`, merging in your `georeferenced.csv`.

Then write the synthesis in `report.md`, **only between the markers `<!-- CLAUDE-SYNTHESIS-START -->` and `<!-- CLAUDE-SYNTHESIS-END -->`**. That text survives rebuilds; anything else you write is overwritten.

**Contents of the synthesis:**
- **Distribution summary:** regions, mountains or islands, altitude range and habitat, with how recent and how reliable the evidence is.
- **Recommended sampling sites, ranked.** All sites are in `sites.csv` (`kind` = site). Favour these:
  - recent records
  - several independent sources
  - precise coordinates
  - genetic data (`dna_same_specimens`, `dna_nearby` in `sites.csv`): say whether a site is already sequenced (same specimens) or only has a sequenced population nearby (give the distance), and with which markers, so the user can reuse the data or choose unsampled populations
  - a herbarium specimen (`herbaria` in `sites.csv`): the identification can be checked, and a specimen revised by a specialist (see the identification history in `occurrences.csv` notes) is the best evidence
  - sites that cover the geographic and environmental range (for population genetics: spread across regions and isolated populations)

  For each site give the site id, area, best evidence (with the herbaria holding specimens), and practical notes such as the Natura 2000 site, the altitude, and whether it's a historic record still to be confirmed.
- **Gaps:** regions known only from old records or from generalised coordinates (areas in `sites.csv` with no candidate site). These are worth confirming or asking curators about.
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
