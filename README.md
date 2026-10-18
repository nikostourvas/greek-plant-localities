# greek-plant-localities

A [Claude Code](https://claude.com/claude-code) skill that finds every known locality of a plant species in Greece and turns them into field-ready outputs for sampling campaigns.

Give it a species name (`/greek-plant-localities:greek-plant-localities Zelkova abelicea`, or just ask "where can I sample *Zelkova abelicea* in Greece?"). It then:

1. **Resolves the name** with the Flora of Greece checklist (Dimopoulos et al. 2013, 2016), Euro+Med and the GBIF backbone. All synonyms are used in every later search.
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

**Outputs** go to `~/greek-plant-localities/<Species>_<date>/`:
- `report.md`
- `candidate_sites.csv`
- `occurrences.csv`
- `leads.csv`
- a GeoPackage for QGIS
- KML for Google Earth or a phone
- GPX for GPS units

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
