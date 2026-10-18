#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31", "beautifulsoup4>=4.12", "pymupdf>=1.24"]
# ///
"""greek-plant-localities: find known localities of a plant species in Greece.

    uv run gpl.py run "Zelkova abelicea"          # everything, fully automatic
    uv run gpl.py names "Zelkova abelicea"        # name resolution only
    uv run gpl.py geocode "Omalos" "Ομαλός"       # gazetteer candidates
    uv run gpl.py build <run_dir>                 # rebuild outputs after editing literature_localities.csv
    uv run gpl.py config --email me@x.org --add-zotero "Plants of Greece"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gplkit import config, geo, literature, names as namesmod, natura, net, occurrences, outputs, report, textsearch  # noqa: E402

LIT_LOC_FIELDS = ["locality", "latitude", "longitude", "uncertainty_m", "georef_method", "source_ref", "page",
                  "year", "collector_or_author", "notes"]


def slug(s: str) -> str:
    return "_".join(s.split()).replace("/", "-")


def run_dir(species: str, out: str | None) -> Path:
    if out:
        d = Path(out).expanduser()
    else:
        d = Path(config.load()["output_root"]).expanduser() / f"{slug(species)}_{dt.date.today():%Y-%m-%d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_names(a):
    res = namesmod.resolve(a.species)
    print(json.dumps({k: v for k, v in res.items() if k not in ("flora_of_greece", "euromed", "gbif", "jacq")},
                     indent=2, ensure_ascii=False))


def cmd_geocode(a):
    rows = []
    for q in a.query:
        for r in geo.lookup(q):
            rows.append({"query": q, **r})
    if not config.load().get("geonames_username"):
        print("# note: GeoNames disabled (no geonames_username in config); Nominatim only", file=sys.stderr)
    print(json.dumps(rows, indent=1, ensure_ascii=False))


def cmd_corpus(a):
    items = textsearch.corpus_items()
    for i, (label, url) in enumerate(items.items(), 1):
        pages = textsearch._remote_pdf_pages(url, label)
        print(f"[{i}/{len(items)}] {'ok' if pages else 'FAILED'}  {label}", file=sys.stderr)
    for r in net.LOG:
        if r["status"] != "ok":
            print(f"  {r['status']}: {r['detail']}", file=sys.stderr)


def cmd_config(a):
    cfg = dict(config.load())
    if a.email:
        cfg["contact_email"] = a.email
    if a.geonames:
        cfg["geonames_username"] = a.geonames
    if a.openalex_key:
        cfg["openalex_api_key"] = a.openalex_key
    if a.output_root:
        cfg["output_root"] = a.output_root
    for p in a.add_pdf or []:
        cfg["local_pdfs"] = sorted(set(cfg.get("local_pdfs", [])) | {p})
    for z in a.add_zotero or []:
        cfg["zotero_collections"] = sorted(set(cfg.get("zotero_collections", [])) | {z})
    if a.zotero_dir:
        cfg["zotero_data_dir"] = a.zotero_dir
    if any([a.email, a.geonames, a.openalex_key, a.output_root, a.add_pdf, a.add_zotero, a.zotero_dir]) or not config.exists():
        p = config.save(cfg)
        print(f"saved {p}", file=sys.stderr)
    print(json.dumps(cfg, indent=2, ensure_ascii=False))


def cmd_run(a):
    if not config.exists():
        print("WARNING: no config yet; run `gpl.py config --email ...` first (see SKILL.md, first run).", file=sys.stderr)
    d = run_dir(a.species, a.out)
    skip = set((a.skip or "").split(",")) - {""}
    print(f"[gpl] output: {d}", file=sys.stderr)

    nm = namesmod.resolve(a.species)
    (d / "names.json").write_text(json.dumps(nm, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[gpl] names: {nm['accepted']} + {len(nm['search_names']) - 1} synonyms", file=sys.stderr)

    if "occurrences" not in skip:
        recs = occurrences.harvest(nm)
        outputs.write_csv(d / "occurrences.csv", recs, occurrences.FIELDS)
        print(f"[gpl] occurrences: {len(recs)} records", file=sys.stderr)
    if "natura" not in skip:
        sites = natura.natura2000_sites(nm)
        outputs.write_csv(d / "natura2000_sites.csv", sites)
        grid = natura.article17_grid(nm)
        if grid:
            (d / "art17_grid.geojson").write_text(json.dumps(grid), encoding="utf-8")
        print(f"[gpl] Natura 2000: {len(sites)} sites; Article 17 cells: {len(grid['features']) if grid else 0}", file=sys.stderr)
    if "text" not in skip:
        hits = textsearch.search(nm, extra_paths=a.pdf or [], classic="classic" not in skip,
                                 proceedings="proceedings" not in skip)
        (d / "text_hits.json").write_text(json.dumps(hits, indent=1, ensure_ascii=False), encoding="utf-8")
        report.write_text_hits_md(d / "text_hits.md", hits)
        print(f"[gpl] flora/PDF text hits: {len(hits)}", file=sys.stderr)
    if "literature" not in skip:
        leads = literature.harvest(nm)
        outputs.write_csv(d / "leads.csv", leads, literature.LEAD_FIELDS)
        print(f"[gpl] literature leads: {len(leads)}", file=sys.stderr)
    if not (d / "literature_localities.csv").exists():
        outputs.write_csv(d / "literature_localities.csv", [], LIT_LOC_FIELDS)
    # keep log rows of sources skipped in this run (partial re-runs with --skip)
    rerun = {r["source"] for r in net.LOG}
    kept = [r for r in outputs.read_csv(d / "sources_log.csv") if r["source"] not in rerun]
    outputs.write_csv(d / "sources_log.csv", kept + net.LOG, ["source", "status", "n", "detail"])
    build(d)


def build(d: Path):
    nm = json.loads((d / "names.json").read_text(encoding="utf-8"))
    recs = outputs.read_csv(d / "occurrences.csv")
    lit = outputs.read_csv(d / "literature_localities.csv")
    lit_recs = []
    for i, r in enumerate(lit, 1):
        rr = {k: "" for k in occurrences.FIELDS}
        rr.update(record_id=f"lit:{i}", source="Literature (extracted)", locality=r.get("locality"),
                  latitude=r.get("latitude"), longitude=r.get("longitude"), uncertainty_m=r.get("uncertainty_m"),
                  year=r.get("year"), collector=r.get("collector_or_author"),
                  notes=f"{r.get('source_ref')} p.{r.get('page')}; {r.get('georef_method')}; {r.get('notes')}",
                  is_primary="yes")
        lit_recs.append(rr)
    allrecs = recs + lit_recs
    sites = outputs.candidate_sites(allrecs)
    outputs.write_csv(d / "candidate_sites.csv", sites,
                      ["site_id", "latitude", "longitude", "n_records", "sources", "first_year", "last_year",
                       "best_uncertainty_m", "example_locality", "record_ids"])
    areas = outputs.candidate_sites(allrecs, radius_m=10000, max_uncertainty_m=None, prefix="A")
    outputs.write_csv(d / "candidate_areas.csv", areas,
                      ["site_id", "latitude", "longitude", "n_records", "n_generalised", "sources", "first_year",
                       "last_year", "best_uncertainty_m", "example_locality", "record_ids"])
    n2k = outputs.read_csv(d / "natura2000_sites.csv")
    layers = {
        "candidate_sites": ("POINT", outputs.point_features(sites)),
        "candidate_areas": ("POINT", outputs.point_features(areas)),
        "occurrences": ("POINT", outputs.point_features(allrecs)),
        "natura2000_site_centroids": ("POINT", outputs.point_features(n2k)),
    }
    gp = d / "art17_grid.geojson"
    if gp.exists():
        g = json.loads(gp.read_text(encoding="utf-8"))
        layers["art17_distribution"] = ("MULTIPOLYGON", [(f["geometry"], f["properties"]) for f in g["features"] if f.get("geometry")])
    sp = slug(nm["accepted"])
    outputs.write_gpkg(d / f"{sp}.gpkg", layers)

    def desc(r):
        return " | ".join(str(x) for x in [r.get("source"), r.get("institution"), r.get("catalog_number"), r.get("collector"),
                                            r.get("event_date") or r.get("year"), r.get("locality"),
                                            f"±{r.get('uncertainty_m')} m" if r.get("uncertainty_m") else ""] if x)
    folders = {
        "Candidate sites": [(s["site_id"], f"{s['n_records']} rec.; {s['sources']}; last {s['last_year']}; {s['example_locality']}",
                             s["latitude"], s["longitude"], "site") for s in sites],
        "Candidate areas (10 km, incl. generalised records)": [(a["site_id"], f"{a['n_records']} rec. ({a['n_generalised']} generalised); {a['sources']}; last {a['last_year']}",
                                                               a["latitude"], a["longitude"], "generalised") for a in areas],
        "Occurrences (precise)": [(r["record_id"], desc(r), r["latitude"], r["longitude"],
                                   "literature" if r["source"].startswith("Literature") else "occurrence")
                                  for r in allrecs if outputs.has_xy(r) and r.get("is_primary") == "yes" and r.get("coords_generalised") != "yes"],
        "Occurrences (generalised / withheld)": [(r["record_id"], desc(r), r["latitude"], r["longitude"], "generalised")
                                                 for r in allrecs if outputs.has_xy(r) and r.get("is_primary") == "yes" and r.get("coords_generalised") == "yes"],
        "Natura 2000 sites listing the species (centroids)": [(f"{s['site_code']} {s['site_name']}", f"pop {s.get('pop_min')}-{s.get('pop_max')} {s.get('unit')}",
                                                               s["latitude"], s["longitude"], "natura") for s in n2k if outputs.has_xy(s)],
    }
    outputs.write_kml(d / f"{sp}.kml", nm["accepted"], folders)
    outputs.write_gpx(d / f"{sp}_sites.gpx", [(s["site_id"], s["example_locality"][:100], s["latitude"], s["longitude"]) for s in sites])
    report.write_report(d, nm, allrecs, sites, n2k, areas)
    print(f"[gpl] built: {d}/report.md, {sp}.gpkg, {sp}.kml, {sp}_sites.gpx, candidate_sites.csv", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="full automatic search")
    r.add_argument("species")
    r.add_argument("--out", help="output directory (default: <output_root>/<Species>_<date>)")
    r.add_argument("--pdf", action="append", help="extra PDF file or folder to search (repeatable)")
    r.add_argument("--skip", help="comma list: occurrences,natura,text,classic,proceedings,literature")
    r.set_defaults(func=cmd_run)
    n = sub.add_parser("names", help="resolve names and synonyms")
    n.add_argument("species")
    n.set_defaults(func=cmd_names)
    g = sub.add_parser("geocode", help="gazetteer candidates for place names")
    g.add_argument("query", nargs="+")
    g.set_defaults(func=cmd_geocode)
    b = sub.add_parser("build", help="rebuild outputs and report from a run directory")
    b.add_argument("run_dir")
    b.set_defaults(func=lambda a: build(Path(a.run_dir).expanduser()))
    w = sub.add_parser("corpus", help="download and cache the public proceedings corpus (one-off, slow)")
    w.set_defaults(func=cmd_corpus)
    c = sub.add_parser("config", help="show or edit configuration")
    c.add_argument("--email")
    c.add_argument("--geonames")
    c.add_argument("--openalex-key")
    c.add_argument("--output-root")
    c.add_argument("--add-pdf", action="append")
    c.add_argument("--add-zotero", action="append")
    c.add_argument("--zotero-dir")
    c.set_defaults(func=cmd_config)
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
