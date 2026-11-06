#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31", "beautifulsoup4>=4.12", "pymupdf>=1.24"]
# ///
"""greek-plant-localities: find known localities of a plant species in Greece.

    uv run gpl.py names "Zelkova abelicea"        # synonyms and misapplied names: review first
    uv run gpl.py run "Zelkova abelicea"          # everything, fully automatic
    uv run gpl.py run "X y" --add-name "Old name" # search an extra name too (kept for re-runs)
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

from gplkit import config, genetic, geo, herbaria, literature, names as namesmod, natura, net, occurrences, outputs, report, textsearch  # noqa: E402

SITE_FIELDS = ["site_id", "kind", "latitude", "longitude", "n_records", "n_generalised", "n_vouchered", "herbaria",
               "n_dna_same", "dna_same_specimens", "n_dna_nearby", "dna_nearby", "sources", "first_year", "last_year",
               "last_voucher_year", "best_uncertainty_m", "example_locality", "record_ids"]
SEQ_FIELDS = genetic.SEQ_FIELDS + ["match", "match_basis", "distance_m", "linked_records", "site_ids"]
# files of the old layout (before 2026-11-06) that are now folded into others, or no longer written
OLD_GENERATED = ["text_hits.json", "candidate_sites.csv", "candidate_areas.csv", "herbaria.csv"]


def slug(s: str) -> str:
    return "_".join(s.split()).replace("/", "-")


def run_dir(species: str, out: str | None) -> Path:
    if out:
        d = Path(out).expanduser()
    else:
        d = Path(config.load()["output_root"]).expanduser() / f"{slug(species)}_{dt.date.today():%Y-%m-%d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_run(d: Path) -> dict:
    """run.json: the names, GGBN counts, Article 17 grid and source log of a run directory."""
    p = d / "run.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def save_run(d: Path, **parts) -> None:
    run = load_run(d)
    run.update(parts)
    (d / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False), encoding="utf-8")


def migrate(d: Path) -> None:
    """Bring a run directory of the old layout (20 files) to the current one; prints what it did."""
    done = []
    run = load_run(d)
    for key, name in (("names", "names.json"), ("ggbn", "ggbn.json"), ("art17", "art17_grid.geojson")):
        p = d / name
        if p.exists():
            run.setdefault(key, json.loads(p.read_text(encoding="utf-8")))
            p.unlink()
            done.append(f"{name} -> run.json")
    p = d / "sources_log.csv"
    if p.exists():
        run.setdefault("sources", outputs.read_csv(p))
        p.unlink()
        done.append("sources_log.csv -> run.json")
    if done:
        (d / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False), encoding="utf-8")
    lit = d / "literature_localities.csv"
    if lit.exists():
        rows = outputs.read_csv(d / "georeferenced.csv") + [dict(r, record_id="") for r in outputs.read_csv(lit)]
        outputs.write_csv(d / "georeferenced.csv", rows, outputs.GEOREF_FIELDS)
        lit.unlink()
        done.append("literature_localities.csv -> georeferenced.csv (rows without record_id)")
    if (d / "natura2000_sites.csv").exists():
        (d / "natura2000_sites.csv").rename(d / "natura2000.csv")
        done.append("natura2000_sites.csv -> natura2000.csv")
    for p in [d / n for n in OLD_GENERATED] + list(d.glob("*_sites.gpx")) + list(d.glob("*_approximate.gpx")):
        if p.exists():
            p.unlink()
            done.append(f"{p.name} removed (rebuilt as sites.csv / one GPX / gpkg table, or no longer needed)")
    for m in done:
        print(f"[gpl] layout: {m}", file=sys.stderr)


def manual_names(a, d: Path | None = None) -> tuple[list[str], list[str]]:
    """--add-name/--drop-name, merged with the edits saved in an earlier run (run.json)."""
    prev = {}
    if d and d.exists():
        migrate(d)
        prev = (load_run(d).get("names") or {}).get("manual") or {}
    new_add, new_drop = a.add_name or [], a.drop_name or []
    add = [n for n in prev.get("add", []) if n not in new_drop] + new_add
    drop = [n for n in prev.get("drop", []) if n not in new_add] + new_drop
    return list(dict.fromkeys(add)), sorted(set(drop))


def names_table(nm: dict) -> str:
    fog, gb, cl = nm["flora_of_greece"], nm["gbif"], nm["catalogue_of_life"]
    lines = [f"Accepted: {nm['accepted_full']}  ({nm.get('family') or '?'})"]
    if not fog.get("found"):
        lines.append(f"WARNING: Flora of Greece does not know “{nm['query']}”; using {nm['accepted']}.")
    if not nm.get("greek_distribution") and fog.get("found"):
        lines.append("WARNING: Flora of Greece lists no Greek distribution for this taxon.")
    if gb.get("found"):
        lines.append(f"GBIF: {gb.get('accepted_full')} (taxonKey {gb.get('taxonKey')}, match {gb.get('matchType')})"
                     + ("" if gb.get("matchType") == "EXACT" else "  WARNING: not an exact match"))
    else:
        lines.append("GBIF: not found")
    lines.append(f"Catalogue of Life: {cl.get('accepted') or 'not found'}")
    lines.append("Greek regions: " + (", ".join(a["code"] or a["area"] for a in nm.get("greek_distribution", [])) or "—"))
    lines.append("")
    w = max(len(r["name"]) for r in nm["name_table"]) + 2
    k = max(len(", ".join(r["kinds"])) for r in nm["name_table"]) + 2
    lines.append(f"{'tier':9}{'name':{w}}{'kind':{k}}sources")
    for r in nm["name_table"]:
        lines.append(f"{r['tier']:9}{r['name']:{w}}{', '.join(r['kinds']):{k}}{', '.join(r['sources'])}")
    if nm.get("misapplied_names"):
        lines += ["", "Misapplied in Greek floras (Flora of Greece):"] + [f"  {m}" for m in nm["misapplied_names"]]
    if nm["manual"]["add"] or nm["manual"]["drop"]:
        lines += ["", f"Added by hand: {', '.join(nm['manual']['add']) or '—'}; dropped: {', '.join(nm['manual']['drop']) or '—'}"]
    lines += ["", f"{len(nm['search_names'])} core names (all searches), {len(nm['extended_names'])} names in total (fast searches)."]
    return "\n".join(lines)


def cmd_names(a):
    add, drop = manual_names(a, Path(a.out).expanduser() if a.out else None)
    res = namesmod.resolve(a.species, add=add, drop=drop)
    if a.json:
        print(json.dumps({k: v for k, v in res.items() if k not in ("flora_of_greece", "euromed", "gbif", "catalogue_of_life", "jacq")},
                         indent=2, ensure_ascii=False))
    else:
        print(names_table(res))


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

    add, drop = manual_names(a, d)  # also brings an old-layout directory up to date
    nm = namesmod.resolve(a.species, add=add, drop=drop)
    save_run(d, names=nm)
    print(f"[gpl] names: {nm['accepted']} + {len(nm['search_names']) - 1} core names, "
          f"{len(nm['extended_names'])} in total", file=sys.stderr)

    if "occurrences" not in skip:
        recs = occurrences.harvest(nm)
        outputs.write_csv(d / "occurrences.csv", recs, occurrences.FIELDS)
        print(f"[gpl] occurrences: {len(recs)} records", file=sys.stderr)
    if "natura" not in skip:
        sites = natura.natura2000_sites(nm)
        outputs.write_csv(d / "natura2000.csv", sites)
        grid = natura.article17_grid(nm)
        save_run(d, art17=grid or None)
        print(f"[gpl] Natura 2000: {len(sites)} sites; Article 17 cells: {len(grid['features']) if grid else 0}", file=sys.stderr)
    if "genetic" not in skip:
        seqs, ggbn = genetic.harvest(nm)
        outputs.write_csv(d / "sequences.csv", seqs, SEQ_FIELDS)
        save_run(d, ggbn=ggbn)
        n_gr = sum(1 for q in seqs if q["origin"] != "foreign")
        print(f"[gpl] genetic data: {len(seqs)} sequences, runs or assemblies ({n_gr} from Greece or of unknown origin)",
              file=sys.stderr)
    if "text" not in skip:
        hits = textsearch.search(nm, extra_paths=a.pdf or [], classic="classic" not in skip,
                                 proceedings="proceedings" not in skip)
        report.write_text_hits_md(d / "text_hits.md", hits)
        print(f"[gpl] flora/PDF text hits: {len(hits)}", file=sys.stderr)
    if "literature" not in skip:
        leads = literature.harvest(nm)
        outputs.write_csv(d / "leads.csv", leads, literature.LEAD_FIELDS)
        print(f"[gpl] literature leads: {len(leads)}", file=sys.stderr)
    if not (d / "georeferenced.csv").exists():
        outputs.write_csv(d / "georeferenced.csv", [], outputs.GEOREF_FIELDS)
    # keep log rows of sources skipped in this run (partial re-runs with --skip)
    rerun = {r["source"] for r in net.LOG}
    kept = [r for r in load_run(d).get("sources") or [] if r["source"] not in rerun]
    save_run(d, sources=kept + [dict(r, n=str(r.get("n", ""))) for r in net.LOG])
    build(d)


def build(d: Path):
    migrate(d)
    run = load_run(d)
    nm = run["names"]
    recs = outputs.read_csv(d / "occurrences.csv")
    placed = outputs.read_csv(d / "georeferenced.csv")
    outputs.apply_georef(recs, [r for r in placed if r.get("record_id")])  # pins for occurrence records
    lit = [r for r in placed if not r.get("record_id")]  # localities from floras and papers
    lit_recs = []
    for i, r in enumerate(lit, 1):
        rr = {k: "" for k in occurrences.FIELDS}
        rr.update(record_id=f"lit:{i}", source="Literature (extracted)", locality=r.get("locality"),
                  institution=r.get("herbarium") or "", voucher=r.get("voucher") or "",
                  latitude=r.get("latitude"), longitude=r.get("longitude"), uncertainty_m=r.get("uncertainty_m"),
                  year=r.get("year"), collector=r.get("collector_or_author"),
                  notes=f"{r.get('source_ref')} p.{r.get('page')}; {r.get('georef_method')}; {r.get('notes')}",
                  is_primary="yes",
                  # a pin placed from the locality text, unless the source itself gives coordinates
                  coords_inferred="" if (r.get("georef_method") or "").lower().startswith("source") else "yes")
        lit_recs.append(rr)
    allrecs = recs + lit_recs
    for r in allrecs:
        r["precision"] = outputs.precision(r)
    outputs.add_vouchers(allrecs)
    seqs = outputs.read_csv(d / "sequences.csv")
    outputs.link_sequences(allrecs, seqs)
    sites = outputs.candidate_sites(allrecs)
    outputs.link_sites(sites, allrecs, seqs)
    areas = outputs.candidate_sites(allrecs, radius_m=10000, max_uncertainty_m=None, prefix="A")
    outputs.link_sites(areas, allrecs, [dict(q) for q in seqs], radius_m=10000)  # copies: sequences keep the site links
    for x in sites:
        x["kind"] = "site"
    for x in areas:
        x["kind"] = "area (10 km)"
    outputs.write_csv(d / "sites.csv", sites + areas, SITE_FIELDS)
    for q in seqs:
        q["match"] = q.get("match") or "not matched"
    outputs.write_csv(d / "sequences.csv", seqs, SEQ_FIELDS)
    # what the herbarium codes stand for
    prim = [r for r in allrecs if r.get("is_primary") == "yes"]
    codes = {h for r in prim for h in r["herbaria"].split("; ") if h}
    herb = herbaria.describe(codes)
    for code, e in herb.items():
        e["n_records"] = sum(1 for r in prim if code in r["herbaria"].split("; "))
        e["n_sites"] = sum(1 for s in sites if code in s["herbaria"].split("; "))
    herb_rows = sorted(herb.values(), key=lambda e: (-e["n_records"], e["code"]))
    n2k = outputs.read_csv(d / "natura2000.csv")
    # sequences on the map: their own coordinates, else those of the record they come from
    by_id = {r["record_id"]: r for r in allrecs}
    seq_points = []
    for q in seqs:
        rec = next((by_id[i] for i in str(q.get("linked_records") or "").split() if outputs.has_xy(by_id.get(i, {}))), None)
        if outputs.has_xy(q):
            seq_points.append(dict(q, position="own coordinates"))
        elif rec:
            seq_points.append(dict(q, latitude=rec["latitude"], longitude=rec["longitude"],
                                   position=f"of record {rec['record_id']}"))
    layers = {
        "candidate_sites": ("POINT", outputs.point_features(sites)),
        "candidate_areas": ("POINT", outputs.point_features(areas)),
        # one layer per precision class, so that QGIS draws each in its own colour
        "occurrences_precise": ("POINT", outputs.point_features([r for r in allrecs if r["precision"] == "precise"])),
        "occurrences_placed": ("POINT", outputs.point_features([r for r in allrecs if r["precision"] == "placed"])),
        "occurrences_approximate": ("POINT", outputs.point_features([r for r in allrecs if r["precision"] == "approximate"])),
        "natura2000_site_centroids": ("POINT", outputs.point_features(n2k)),
        "sequences": ("POINT", outputs.point_features(seq_points)),
        "herbaria": (None, [(None, e) for e in herb_rows]),  # what the herbarium codes stand for
    }
    g = run.get("art17")
    if g:
        layers["art17_distribution"] = ("MULTIPOLYGON", [(f["geometry"], f["properties"]) for f in g["features"] if f.get("geometry")])
    sp = slug(nm["accepted"])
    outputs.write_gpkg(d / f"{sp}.gpkg", layers)

    def where(h):  # "B (Berlin, Germany); LD (Lund, Sweden)"
        return "; ".join(herbaria.short(c, herb) for c in h.split("; ") if c)

    def desc(r):
        ev = f"{r['evidence']}: {r['vouchers']} [{where(r['herbaria'])}]" if r.get("vouchers") else r["evidence"]
        other = "" if r.get("vouchers") else " ".join(filter(None, [r.get("institution"), r.get("catalog_number")]))
        return " | ".join(str(x) for x in [ev, r.get("source"), other, r.get("collector"),
                                            r.get("event_date") or r.get("year"), r.get("locality"),
                                            f"±{r.get('uncertainty_m')} m" if r.get("uncertainty_m") else "",
                                            "pin placed from the locality text" if r["precision"] == "placed" else "",
            f"DNA from this specimen: {r['sequences']}" if r.get("sequences") else ""] if x)

    def seq_desc(q):
        m = {"same specimen": f"same specimen as {q.get('linked_records')} ({q.get('match_basis')})",
             "nearby": f"NOT matched to a specimen; {q.get('match_basis')}"}.get(q.get("match") or "", "not matched to a record")
        return " | ".join(filter(None, [f"{q.get('marker')} ({q.get('source')} {q.get('kind')})", m, q.get("origin"),
                                        q.get("country"), q.get("specimen_voucher"), q.get("collector"),
                                        q.get("collection_date"), q.get("locality"), q.get("position"), q.get("url")]))

    def nov(x):  # style suffix: open diamond when no specimen or sample is known
        return "" if x.get("herbaria") else "_nov"

    def site_desc(s, generalised=False):
        v = (f"specimens in {where(s['herbaria'])} ({s['n_vouchered']} rec., last {s['last_voucher_year'] or '?'})"
             if s["herbaria"] else "no specimen known: observations or literature only")
        g = f" ({s['n_generalised']} generalised)" if generalised else ""
        dna = (f"; DNA from these specimens: {s['dna_same_specimens']}" if s.get("dna_same_specimens") else "") + \
              (f"; DNA nearby (not the same specimens): {s['dna_nearby']}" if s.get("dna_nearby") else "")
        return f"{v}{dna}; {s['n_records']} rec.{g}; {s['sources']}; last {s['last_year']}; {s['example_locality']}"
    folders = {
        "Candidate sites": [(s["site_id"], site_desc(s), s["latitude"], s["longitude"], "site" + nov(s)) for s in sites],
        "Candidate areas (10 km, incl. generalised records)": [(a["site_id"], site_desc(a, True), a["latitude"], a["longitude"],
                                                                "generalised" + nov(a)) for a in areas],
        "Occurrences (precise)": [(r["record_id"], desc(r), r["latitude"], r["longitude"],
                                   ("literature" if r["source"].startswith("Literature") else "occurrence") + nov(r))
                                  for r in prim if r["precision"] == "precise"],
        "Occurrences (pin placed at the most probable place)": [(r["record_id"], desc(r), r["latitude"], r["longitude"], "placed" + nov(r))
                                                                for r in prim if r["precision"] == "placed"],
        "Occurrences (generalised, withheld or > 5 km)": [(r["record_id"], desc(r), r["latitude"], r["longitude"], "generalised" + nov(r))
                                                          for r in prim if r["precision"] == "approximate"],
        "Natura 2000 sites listing the species (centroids)": [(f"{s['site_code']} {s['site_name']}", f"pop {s.get('pop_min')}-{s.get('pop_max')} {s.get('unit')}",
                                                               s["latitude"], s["longitude"], "natura") for s in n2k if outputs.has_xy(s)],
        "Genetic data (ENA/GenBank, BOLD): Greece or unknown origin": [
            (q["sequence_id"], seq_desc(q), q["latitude"], q["longitude"], "dna") for q in seq_points if q.get("origin") != "foreign"],
        "Genetic data: other countries": [
            (q["sequence_id"], seq_desc(q), q["latitude"], q["longitude"], "dna") for q in seq_points if q.get("origin") == "foreign"],
    }
    outputs.write_kml(d / f"{sp}.kml", nm["accepted"], folders, hidden={"Genetic data: other countries"})
    # one GPX. Garmin symbols: red = candidate site, blue = pin placed from the locality text, green = generalised or
    # > 5 km; flag where a specimen or sample exists, pin where there is none. `type` says the same in words.
    outputs.write_gpx(d / f"{sp}.gpx", [
        (s["site_id"], site_desc(s)[:200], s["latitude"], s["longitude"], ("Flag" if s["herbaria"] else "Pin") + ", Red",
         "candidate site") for s in sites] + [
        ("~" + r["record_id"], desc(r)[:200], r["latitude"], r["longitude"],
         ("Flag, " if r.get("herbaria") else "Pin, ") + ("Blue" if r["precision"] == "placed" else "Green"),
         "placed pin" if r["precision"] == "placed" else "approximate")
        for r in prim if r["precision"] in ("placed", "approximate")])
    report.write_report(d, nm, allrecs, sites, n2k, areas, herb_rows, seqs, run.get("ggbn") or {},
                        outputs.read_csv(d / "leads.csv"), lit, run.get("sources") or [], bool(run.get("art17")))
    print(f"[gpl] built: {d}/report.md, {sp}.gpkg, {sp}.kml, {sp}.gpx, sites.csv", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="full automatic search")
    r.add_argument("species")
    r.add_argument("--out", help="output directory (default: <output_root>/<Species>_<date>)")
    r.add_argument("--pdf", action="append", help="extra PDF file or folder to search (repeatable)")
    r.add_argument("--skip", help="comma list: occurrences,natura,genetic,text,classic,proceedings,literature")
    n = sub.add_parser("names", help="resolve names and synonyms (run this first and review the list)")
    n.add_argument("species")
    n.add_argument("--out", help="run directory whose saved name edits to include")
    n.add_argument("--json", action="store_true", help="print JSON instead of the review table")
    for x in (r, n):
        x.add_argument("--add-name", action="append", metavar="NAME",
                       help="extra name to search in every search, e.g. one used in Greek floras (repeatable; kept for re-runs)")
        x.add_argument("--drop-name", action="append", metavar="NAME",
                       help="name to leave out, e.g. a homonym (repeatable; kept for re-runs)")
    r.set_defaults(func=cmd_run)
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
