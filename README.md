# greek-plant-localities

A [Claude Code](https://claude.com/claude-code) skill that finds every known locality of a plant species in Greece and turns them into field-ready outputs for sampling campaigns.

Give it a species name (`/greek-plant-localities:greek-plant-localities Zelkova abelicea`, or just ask "where can I sample *Zelkova abelicea* in Greece?"). It then:

1. **Finds every name first.** It collects:
   - the synonyms from the Flora of Greece checklist (Dimopoulos et al. 2013, 2016), Euro+Med, the GBIF backbone and the Catalogue of Life (WCVP, including the synonyms of subspecies)
   - the names Flora of Greece lists as misapplied in Greek floras ("auct. fl. graec."), which older Greek literature and herbaria often use

   Claude reviews the list and can add names, for example ones you mention or ones used by Halácsy. Every name is then used in the searches below.
2. **Collects specimens and observations** from:
   - [GBIF](https://www.gbif.org), including records that lack a country code
   - [DiSSCo Hellas](https://dissco-gr.nhmc.uoc.gr), the Greek national herbaria (ATHU, TAU, ATH/Goulandris, NHMC, MAICH), which are not in GBIF
   - [JACQ](https://www.jacq.org), which adds UPA, CBH and private herbaria
   - [iNaturalist](https://www.inaturalist.org)

   Duplicates across herbaria and portals are grouped.
3. **Adds conservation data:** the Natura 2000 sites whose Standard Data Form lists the species, and the Habitats Directive Article 17 distribution grid (2019–2024).
4. **Searches the full text** of:
   - classic floras: Halácsy's *Conspectus Florae Graecae* and Boissier's *Flora Orientalis*
   - the proceedings of HELECOS (Hellenic Ecological Society) and the Hellenic Botanical and Forestry Societies, plus the ΓΕΩΤΕΕ journal (about 80 volumes, downloaded once and cached as text)
   - your own PDFs or Zotero collections of floras and reports. Private files are read locally and never shared.
5. **Collects literature leads:**
   - Greek theses: [openarchives.gr](https://www.openarchives.gr), [didaktorika.gr](https://www.didaktorika.gr), university repositories, OpenAIRE
   - papers: OpenAlex
   - taxonomic treatments: Plazi, including the *Red Data Book of Rare and Threatened Plants of Greece*
   - Zenodo datasets
6. **Claude reads and georeferences:** it reads the flora passages and the promising theses and papers, extracts and georeferences the localities (GeoNames, OSM, EKT Pandektis for old place names), and writes a report with ranked candidate sampling sites.

**Outputs** go to `~/greek-plant-localities/<Species>_<date>/`, twelve files:
- for you: `report.md`, a GeoPackage for QGIS, a KML for Google Earth or a phone, a GPX for GPS units, and `sites.csv` (the candidate sites as a spreadsheet)
- working files: `occurrences.csv`, `sequences.csv`, `natura2000.csv`, `leads.csv`, `text_hits.md`, `georeferenced.csv` (the points Claude places) and `run.json` (names and source log)

In the maps, records are coloured by how far their point can be trusted: precise coordinates; a pin placed by Claude at the most probable place from the locality text (old labels, floras); or generalised and withheld coordinates. The marker shape shows whether a herbarium specimen (or another deposited sample) exists for the record or site, and the report lists the herbaria that hold them, with what the herbarium codes stand for (Index Herbariorum). It also lists genetic data already published (ENA/GenBank sequences, reads and genomes; BOLD barcodes) and says, for each site, whether the DNA comes from the site's own specimens or only from a population nearby.

## Install

You need Claude Code and [uv](https://docs.astral.sh/uv/getting-started/installation/). uv runs the Python scripts and installs their dependencies on first use.

```text
/plugin marketplace add nikostourvas/greek-plant-localities
/plugin install greek-plant-localities@greek-plant-localities
```

To get updates automatically, run `/plugin`, open the **Marketplaces** tab, select `greek-plant-localities` and choose **Enable auto-update**.
Or put this in `~/.claude/settings.json`, which also installs it on a new machine:

```json
{
  "extraKnownMarketplaces": {
    "greek-plant-localities": {
      "source": { "source": "github", "repo": "nikostourvas/greek-plant-localities" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": { "greek-plant-localities@greek-plant-localities": true }
}
```

Without the plugin system, clone the repo and symlink the skill:

```bash
git clone https://github.com/nikostourvas/greek-plant-localities ~/src/greek-plant-localities
ln -s ~/src/greek-plant-localities/skills/greek-plant-localities ~/.claude/skills/greek-plant-localities
```

You then update it with `git pull`.

## First run

On first use the skill asks you once for:
- a contact email (sent in the User-Agent, as the APIs request)
- an optional [GeoNames](https://www.geonames.org/login) username
- any private flora PDFs or Zotero collections to search
- optionally, a local copy of the [BOLD public data package](https://bench.boldsystems.org/index.php/datapackages/Latest) (Parquet; free login), searched instead of the BOLD API, which blocks clients that send many queries: `gpl.py config --bold-snapshot /path/BOLD_Public.<date>.parquet`

These are stored in `~/.config/greek-plant-localities/config.json`.

## Using the scripts without Claude

```bash
cd skills/greek-plant-localities/scripts
uv run gpl.py config --email you@example.org
uv run gpl.py run "Abies cephalonica"
uv run gpl.py geocode "Chelmos" "Χελμός"
```

## Good manners and caveats

- **Throttling:** Greek university servers block fast clients, so requests are throttled (2.5–3 s per Greek host) and cached for 14 days. Please don't remove this.
- **Undocumented API:** DiSSCo Hellas has an open but undocumented JSON API. It generalises coordinates of sensitive taxa to a 10 km grid; ask the curators for precise localities.
- **Sensitive data:** precise localities of threatened plants are sensitive. Use the outputs for fieldwork, not for publication.
- **Citing GBIF:** for published analyses, cite a GBIF download DOI rather than search results.
- **Source details:** see [`references/sources.md`](skills/greek-plant-localities/references/sources.md) and [`references/greek-grey-literature.md`](skills/greek-plant-localities/references/greek-grey-literature.md).

## License

MIT. Data retrieved belongs to the respective providers and carries their licences (CC0, CC BY, CC BY-NC).
