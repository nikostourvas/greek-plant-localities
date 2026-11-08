"""Genetic data: which records and populations already have sequences.

Sources:
- ENA Portal API: all INSDC data (GenBank, ENA and DDBJ exchange daily), i.e. sequences, read runs (SRA),
  samples (BioSample) and assemblies. Queried by NCBI taxon ID, worldwide; every record is kept and `origin`
  says whether it comes from Greece.
- BOLD v5 public portal API: barcodes, often with coordinates; many are not in INSDC.
- GGBN: DNA and tissue bank holdings, counts per genus only (record-level GGBN data come through GBIF,
  see `dna` in occurrences.py).

INSDC records rarely give a country or coordinates. For those, the title of the publication (from the ENA
flat file) often names the place ("… from Chios Island (Greece)"), so it is used to classify the origin.
No API key is needed for any of these.

Sequence databases match bare names, without authors, so `sequence_names` leaves out the names that would
bring in another species: names only misapplied to the taxon in Greek floras, later homonyms, and names that
NCBI or the GBIF backbone give to a different species (see the examples there).
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import urllib.parse

from . import geo, net

ENA_TAX = "https://www.ebi.ac.uk/ena/taxonomy/rest/any-name"
ENA_SEARCH = "https://www.ebi.ac.uk/ena/portal/api/search"
ENA_EMBL = "https://www.ebi.ac.uk/ena/browser/api/embl"
ENA_VIEW = "https://www.ebi.ac.uk/ena/browser/view"
BOLD = "https://portal.boldsystems.org/api"
BOLD_RECORD = "https://portal.boldsystems.org/record"
GGBN = "https://www.ggbn.org/ggbn_portal/api/search"
GBIF_SPECIES = "https://api.gbif.org/v1/species"
GBIF_BACKBONE = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"
# backbone usages from the Catalogue of Life are taxonomic opinions; those from IPNI (a nomenclator) or WoRMS
# are bare name records, all marked "accepted" (Thymus alpinus Pall., Dipsacus sylvestris Lam.)
GBIF_COL = "7ddf754f-d193-4cc9-b351-99906754a03b"

ENA_MAX = 5000  # sequences per query; more than this is a model or crop species, not a fieldwork question
TITLE_LOOKUPS = 60  # publication titles fetched for sequences without country or coordinates
GREECE_BOX = (19.2, 34.7, 29.8, 41.8)  # lon/lat bounds, as occurrences.GREECE_WKT; includes parts of neighbours

SEQ_FIELDS = ["sequence_id", "source", "kind", "scientific_name", "marker", "origin", "country", "locality",
              "latitude", "longitude", "specimen_voucher", "institution", "collector", "field_id", "collection_date",
              "study", "bin", "insdc", "title", "description", "url"]

# marker names in INSDC descriptions; a record can hold several (trnK intron with matK)
MARKERS = [
    ("plastome", r"chloroplast,? complete genome|plastid,? complete genome"),
    ("mitogenome", r"mitochondri\w*,? complete genome"),
    ("rbcL", r"\brbcL\b|ribulose-1,5-bisphosphate"),
    ("matK", r"\bmatK\b|maturase K"),
    ("trnH-psbA", r"psbA-trnH|trnH-psbA"),
    ("ITS", r"internal transcribed spacer|\bITS[12]?\b|5\.8S"),
    ("ETS", r"external transcribed spacer"),
    ("trnL-F", r"\btrnL\b|\btrnF\b|trnL-trnF"),
    ("trnK", r"\btrnK\b"),
    ("rps16", r"\brps16\b"),
    ("rpl16", r"\brpl16\b"),
    ("rpl32-trnL", r"rpl32"),
    ("ndhF", r"\bndhF\b"),
    ("ycf1", r"\bycf1\b"),
    ("trnS-trnG", r"trnS-trnG|trnG-trnS"),
    ("trnT-trnL", r"trnT-trnL"),
    ("atpB-rbcL", r"atpB-rbcL"),
    ("psbJ-petA", r"psbJ-petA"),
    ("petB-petD", r"petB-petD|petD"),
    ("SSR", r"microsatellite|simple sequence repeat"),
]
GREEK_WORDS = ["Greece", "Greek", "Hellas", "Hellenic", "Crete", "Kriti", "Aegean", "Peloponnes", "Ionian islands",
               "Thessal", "Epirus", "Euboea", "Evia", "Chios", "Lesbos", "Lesvos", "Samos", "Rhodes", "Rodos",
               "Naxos", "Kefalonia", "Cephalonia", "Corfu", "Kerkyra", "Athos", "Olympus", "Parnassos", "Pindos",
               "Taygetos", "Karpathos", "Ikaria", "Cyclades", "Kiklades", "Dodecanese"]


def markers(text: str) -> str:
    found = [m for m, rx in MARKERS if re.search(rx, text or "", re.I)]
    if "matK" in found and "trnK" in found:
        found.remove("trnK")
    return "+".join(found) or "other"


def _in_greece_box(lat, lon) -> bool:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    x0, y0, x1, y1 = GREECE_BOX
    return x0 <= lon <= x1 and y0 <= lat <= y1


# INSDC placeholders for an unknown country, and INSDC spellings that differ from the ISO names GBIF lists
MISSING = ("missing", "not collected", "not applicable", "not provided", "not recorded", "unknown", "restricted access",
           "na", "n/a")
COUNTRY_ALIASES = {"usa", "uk", "russia", "turkey", "turkiye", "iran", "syria", "south korea", "north korea", "laos",
                   "vietnam", "czech republic", "macedonia", "ivory coast", "cape verde", "brunei", "taiwan", "kosovo",
                   "palestine", "west bank", "gaza strip", "micronesia", "borneo", "antarctica", "bolivia", "venezuela",
                   "tanzania", "moldova", "democratic republic of the congo", "republic of the congo"}


def countries() -> set[str]:
    d = net.get("https://api.gbif.org/v1/enumeration/country", source="GBIF countries") or []
    return {c["title"].lower() for c in d if c.get("title")} | COUNTRY_ALIASES


def _is_country(head: str, known: set[str] | None) -> bool:
    h = head.lower().strip()
    if known is None:
        return True
    return h in known or (len(h) >= 4 and any(k.startswith(h) for k in known))


def _mentions(text: str, words) -> bool:
    return any(re.search(r"\b" + re.escape(w), text or "", re.I) for w in words)


def _greek_place(text: str) -> bool:
    """A Greek settlement, island or natural feature of that name (for localities put in the country field)."""
    hits = geo.nominatim(text, n=3)
    return any(h["feature"].split(":")[0] in ("place", "natural", "boundary") and h["name"].lower() == text.lower()
               for h in hits)


def origin(country: str, lat, lon, title: str = "", greek_words=(), known=None, place_check=None) -> str:
    """'Greece', 'Greece (publication)', 'possibly Greece (coordinates)', 'foreign' or 'unknown'.
    `known`: country names (anything else in the country field is treated as a locality);
    `place_check`: function telling whether such a locality is a Greek place."""
    words = list(GREEK_WORDS) + list(greek_words)
    c = (country or "").strip()
    head = c.split(":")[0].strip()
    h = head.lower()
    if h in MISSING or h.startswith(("missing", "not ")):  # 'missing: control sample', 'not collected'
        c = head = ""
    if c:
        if head.lower().startswith("greece") or _mentions(c, words):
            return "Greece"
        if _is_country(head, known):
            return "foreign"
        if place_check and place_check(head):  # e.g. 'Avdou', a village on Crete, given as the country
            return "Greece"
    if lat not in ("", None) and lon not in ("", None):
        return "possibly Greece (coordinates)" if _in_greece_box(lat, lon) else "foreign"
    if title and _mentions(title, words):
        return "Greece (publication)"
    return "unknown"


def _ena_location(loc: str):
    """'41.207 N 26.311 E' -> (41.207, 26.311)"""
    m = re.match(r"\s*([\d.]+)\s*([NS])\s+([\d.]+)\s*([EW])", loc or "")
    if not m:
        return "", ""
    lat, lon = float(m.group(1)), float(m.group(3))
    return (-lat if m.group(2) == "S" else lat), (-lon if m.group(4) == "W" else lon)


# ---------------------------------------------------------------- names for sequence databases
_NOT_AUTHORS = {"ex", "et", "in", "and", "nom", "illeg", "inval", "nud", "cons", "nov", "rej", "superfl", "sensu",
                "auct", "non", "al", "fil", "pro", "syn"}


def _authors(authorship: str) -> set[str]:
    """Author names in an authorship, accents and initials dropped: '(L.) Lassen, 1989' -> {'l', 'lassen'}."""
    s = unicodedata.normalize("NFKD", authorship or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return {w for w in re.findall(r"[a-z]+", s) if w not in _NOT_AUTHORS and (len(w) > 1 or w == "l")}


def _full_names(names: dict, n: str) -> list[str]:
    """Flora of Greece and Euro+Med full names (with authors and status) of the name n."""
    out = []
    for src in ("flora_of_greece", "euromed"):
        s = names.get(src) or {}
        for full in list(s.get("synonyms_full") or []) + [m.get("full") or "" for m in s.get("misapplied") or []]:
            rest = full[len(n):].strip()
            if full.startswith(n + " ") and rest[:1] and (rest[0].isupper() or rest[0] == "("):
                out.append(full)
    return out


def _homonym(n: str, fulls: list[str], accepted: str) -> str:
    """Another species that the GBIF backbone (Catalogue of Life) accepts under the bare binomial n, by other
    authors; '' if none."""
    d = net.get(GBIF_SPECIES, {"name": n, "datasetKey": GBIF_BACKBONE, "limit": 20}, source="GBIF backbone") or {}
    ours = set().union(*(_authors(f[len(n):]) for f in fulls))
    for u in d.get("results") or []:
        if u.get("taxonomicStatus") != "ACCEPTED" or u.get("canonicalName") != n or u.get("constituentKey") != GBIF_COL:
            continue
        if (u.get("species") or "") == " ".join(accepted.split()[:2]):
            continue  # the taxon itself
        if ours & _authors(u.get("authorship")):
            continue  # same name and type, only another taxonomy (e.g. a segregate species): not a homonym
        return u.get("scientificName") or n
    return ""


def sequence_names(names: dict) -> tuple[list[str], dict[str, str]]:
    """The core names to search in sequence databases, and the ones left out with the reason.

    Left out: names only misapplied to the taxon in Greek floras (elsewhere they are the other taxon, e.g.
    Onosma taurica for O. erecta); later homonyms (nom. illeg.: Orchis militaris Poir. for O. italica is not
    O. militaris L.); binomials that the GBIF backbone also accepts as a species of other authors (Centaurea
    horrida Ten. is a synonym of C. calcitrapa, but the sequences are of C. horrida Badarò from Sardinia).
    Names added by hand are always kept. NCBI's own synonymy is checked in taxids().
    """
    accepted = names.get("accepted") or ""
    own = {accepted, " ".join((names.get("query") or "").split())}
    kinds = {e["name"]: e.get("kinds") or [] for e in names.get("name_table") or []}
    species = accepted.split()[:2] if len(accepted.split()) == 2 else None
    keep, skip = [], {}
    for n in names["search_names"]:
        k = kinds.get(n, [])
        if n in own or "added by hand" in k or n.split()[:2] == species:  # infraspecific names of the species itself
            keep.append(n)
            continue
        fulls = _full_names(names, n)
        other = ""
        if k and all("misapplied" in x for x in k):
            skip[n] = "misapplied in Greek floras; elsewhere the name is another taxon"
        elif any("nom. illeg" in f for f in fulls):
            skip[n] = f"later homonym ({next(f for f in fulls if 'nom. illeg' in f).rstrip(' ,')})"
        elif len(n.split()) == 2 and (other := _homonym(n, fulls, accepted)):
            skip[n] = f"homonym: {(fulls or [n])[0]} here, but GBIF also accepts {other}"
        else:
            keep.append(n)
    for n, why in skip.items():
        net.log("genetic data", "skipped", f"name '{n}' not searched: {why}")
    return keep, skip


# ---------------------------------------------------------------- ENA (INSDC)
def taxids(names: dict, use: list[str] | None = None) -> dict[str, str]:
    """NCBI/ENA taxon IDs of the accepted name and the core names (synonyms are often separate entries).

    A synonym that NCBI files under a species with none of the taxon's names is skipped (NCBI treats
    Coronilla parviflora as Securigera parviflora, not Securigera cretica)."""
    own = {names.get("accepted"), " ".join((names.get("query") or "").split())}
    ours = set(names.get("extended_names") or []) | set(names["search_names"])
    acc = (names.get("accepted") or "").split()
    out = {}
    for n in use if use is not None else names["search_names"]:
        d = net.get(f"{ENA_TAX}/{urllib.parse.quote(n)}", source="ENA taxonomy")
        for t in d if isinstance(d, list) else []:
            if t.get("taxId") and t.get("rank") in ("species", "subspecies", "varietas", "forma", None):
                sn = t.get("scientificName") or n
                same_species = len(acc) == 2 and sn.split()[:2] == acc  # e.g. Crataegus monogyna var. monogyna
                if n not in own and sn != n and sn not in ours and not same_species:
                    net.log("ENA taxonomy", "skipped", f"'{n}' is {sn} ({t['taxId']}) in NCBI, another taxon: not searched")
                    continue
                out[t["taxId"]] = sn
    net.log("ENA taxonomy", "ok" if out else "not_found", ", ".join(f"{v} {k}" for k, v in out.items()), len(out))
    return out


def _ena_search(result: str, query: str, fields: str, label: str) -> list[dict]:
    d = net.get(ENA_SEARCH, {"result": result, "query": query, "fields": fields, "format": "json", "limit": ENA_MAX},
                source=label)
    rows = d if isinstance(d, list) else []
    if len(rows) >= ENA_MAX:
        net.log(label, "truncated", f"{result}: first {ENA_MAX} only")
    return rows


def _ena_title(acc: str) -> str:
    """Title of the first publication in the ENA flat file (RT lines), '' for direct submissions."""
    t = net.get(f"{ENA_EMBL}/{acc}", {"lineLimit": 80}, source="ENA references", as_json=False) or ""
    blocks, cur = [], []
    for line in t.splitlines():
        if line.startswith("RT "):
            cur.append(line[5:].strip())
            if line.rstrip().endswith(";"):
                blocks.append(" ".join(cur).strip(' ;"'))
                cur = []
    return next((b for b in blocks if b), "")


def ena(names: dict, ids: dict[str, str]) -> list[dict]:
    if not ids:
        return []
    q = " OR ".join(f"tax_tree({i})" for i in ids)
    out = []
    seq_fields = ("accession,scientific_name,description,country,location,specimen_voucher,isolate,collection_date,"
                  "collected_by,study_accession,bio_material")
    for r in _ena_search("sequence", q, seq_fields, "ENA sequences"):
        lat, lon = _ena_location(r.get("location"))
        out.append({"sequence_id": r["accession"], "source": "ENA", "kind": "sequence",
                    "scientific_name": r.get("scientific_name"), "marker": markers(r.get("description")),
                    "country": r.get("country"), "latitude": lat, "longitude": lon,
                    "specimen_voucher": r.get("specimen_voucher") or r.get("bio_material") or r.get("isolate"),
                    "collector": r.get("collected_by"), "collection_date": r.get("collection_date"),
                    "study": r.get("study_accession"), "description": r.get("description"),
                    "url": f"{ENA_VIEW}/{r['accession']}"})
    data_fields = ("scientific_name,country,location,lat,lon,specimen_voucher,collection_date,collected_by,"
                   "study_accession,sample_accession,description")
    runs = _ena_search("read_run", q, "run_accession,library_strategy,instrument_platform," + data_fields, "ENA read runs")
    for r in runs:
        out.append(_ena_data(r, "run", r["run_accession"], f"reads ({r.get('library_strategy') or '?'})"))
    for r in _ena_search("assembly", q, "accession,assembly_title,assembly_level,genome_representation," + data_fields,
                         "ENA assemblies"):
        out.append(_ena_data(r, "assembly", r["accession"], f"assembly ({r.get('assembly_level') or '?'})",
                             r.get("assembly_title")))
    with_runs = {r.get("sample_accession") for r in runs}
    for r in _ena_search("sample", q, "sample_accession,sample_title," + data_fields.replace(",sample_accession", ""),
                         "ENA samples"):
        if r.get("sample_accession") not in with_runs:  # BioSamples whose data are elsewhere (e.g. only metadata)
            out.append(_ena_data(r, "sample", r["sample_accession"], "sample (no reads)", r.get("sample_title")))
    net.log("ENA", "ok", f"taxa {', '.join(ids)}", len(out))
    return out


def _ena_data(r: dict, kind: str, acc: str, marker: str, desc: str = "") -> dict:
    lat, lon = r.get("lat") or "", r.get("lon") or ""
    if not lat:
        lat, lon = _ena_location(r.get("location"))
    return {"sequence_id": acc, "source": "ENA", "kind": kind, "scientific_name": r.get("scientific_name"),
            "marker": marker, "country": r.get("country"), "latitude": lat, "longitude": lon,
            "specimen_voucher": r.get("specimen_voucher"), "collector": r.get("collected_by"),
            "collection_date": r.get("collection_date"), "study": r.get("study_accession"),
            "description": desc or r.get("description"), "url": f"{ENA_VIEW}/{acc}"}


# ---------------------------------------------------------------- BOLD
def bold(names: dict, use: list[str] | None = None) -> list[dict]:
    """Public BOLD records (no API key) for every core name that BOLD knows."""
    out, seen = [], set()
    for n in use if use is not None else names["search_names"]:
        pre = net.get(f"{BOLD}/query/preprocessor", {"query": f"tax:{n}"}, source="BOLD") or {}
        matched = [t.get("matched") for t in pre.get("successful_terms") or [] if t.get("matched")]
        if not matched:
            continue
        q = net.get(f"{BOLD}/query", {"query": matched[0], "extent": "full"}, source="BOLD") or {}
        if not q.get("query_id"):
            continue
        tsv = net.get(f"{BOLD}/documents/{q['query_id']}/download", {"format": "tsv"}, source="BOLD", as_json=False)
        for r in csv.DictReader(io.StringIO(tsv or ""), delimiter="\t"):
            pid = r.get("processid")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            m = re.match(r"\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]", r.get("coord") or "")
            out.append({"sequence_id": pid, "source": "BOLD", "kind": "barcode",
                        "scientific_name": r.get("species") or r.get("identification"),
                        "marker": r.get("marker_code") or "?", "country": r.get("country/ocean"),
                        "locality": ", ".join(filter(None, [r.get("province/state"), r.get("region"), r.get("site")])),
                        "latitude": m.group(1) if m else "", "longitude": m.group(2) if m else "",
                        "specimen_voucher": r.get("museumid") or r.get("sampleid"), "institution": r.get("inst"),
                        "collector": r.get("collectors"), "field_id": r.get("fieldid"),
                        "collection_date": r.get("collection_date_start"), "bin": r.get("bin_uri"),
                        "insdc": r.get("insdc_acs"), "description": r.get("identified_by") and f"det. {r['identified_by']}",
                        "url": f"{BOLD_RECORD}/{pid}"})
    net.log("BOLD", "ok", "public portal API", len(out))
    return out


# ---------------------------------------------------------------- GGBN
def ggbn_counts(names: dict) -> dict[str, dict]:
    """DNA / tissue / specimen counts per genus in GGBN's DNA banks (its API gives no records)."""
    out = {}
    # genera of the accepted names only: synonym genera (Thymus, Melissa for Acinos graveolens) hold other species
    accepted = [names.get("accepted"), (names.get("euromed") or {}).get("accepted"), (names.get("gbif") or {}).get("accepted"),
                (names.get("catalogue_of_life") or {}).get("accepted")]
    for g in dict.fromkeys(n.split()[0] for n in accepted if n):
        t = net.get(GGBN, {"getSampletype": "", "name": g}, source="GGBN", as_json=False) or ""
        try:
            st = json.loads(t).get("sampletype") or {}
        except ValueError:  # unknown names return an HTML page
            continue
        if st:
            out[g] = st
    net.log("GGBN", "ok", "; ".join(f"{g}: {v}" for g, v in out.items()), len(out))
    return out


# ---------------------------------------------------------------- all
def harvest(names: dict) -> tuple[list[dict], dict]:
    rows = []
    try:
        use, _ = sequence_names(names)
    except Exception as e:
        net.log("genetic data", "error", f"name check: {type(e).__name__}: {e}")
        use = names["search_names"]
    for f in (lambda: ena(names, taxids(names, use)), lambda: bold(names, use)):
        try:
            rows += f()
        except Exception as e:  # one broken source must not stop the run
            net.log("genetic data", "error", f"{type(e).__name__}: {e}")
    # BOLD and INSDC copy each other (BOLD mines GenBank; BOLD projects submit to INSDC). Keep one row per
    # sequence: the one with coordinates, else the ENA one (it has the publication); note the other ID.
    ena_rows = {r["sequence_id"].split(".")[0]: r for r in rows if r["source"] == "ENA"}
    drop = set()
    for b in [r for r in rows if r["source"] == "BOLD"]:
        for acc in (a.strip().split(".")[0] for a in str(b.get("insdc") or "").split(",") if a.strip()):
            e = ena_rows.get(acc)
            if not e:
                continue
            if b.get("latitude") and not e.get("latitude"):
                drop.add(id(e))
                b["insdc"] = acc
            else:
                drop.add(id(b))
                e["bin"], e["insdc"] = b.get("bin") or "", f"BOLD {b['sequence_id']}"
    rows = [r for r in rows if id(r) not in drop]

    greek = [a.get("area") for a in names.get("greek_distribution") or [] if a.get("area")]
    known = countries()
    places: dict[str, bool] = {}

    def place_check(text):
        if text not in places:
            places[text] = _greek_place(text)
        return places[text]

    titles: dict[str, str] = {}
    lookups = 0
    for r in rows:
        o = origin(r.get("country"), r.get("latitude"), r.get("longitude"), greek_words=greek, known=known,
                   place_check=place_check)
        if o == "unknown" and r["source"] == "ENA" and r["kind"] == "sequence":
            key = r.get("study") or r["sequence_id"]
            if key not in titles and lookups < TITLE_LOOKUPS:
                titles[key] = _ena_title(r["sequence_id"])
                lookups += 1
            r["title"] = titles.get(key, "")
            o = origin(r.get("country"), "", "", r["title"], greek, known)
        r["origin"] = o
    if lookups >= TITLE_LOOKUPS:
        net.log("ENA references", "truncated", f"publication titles looked up for the first {TITLE_LOOKUPS} studies only")
    foreign = sum(1 for r in rows if r["origin"] == "foreign")
    net.log("genetic data", "ok", f"{len(rows) - foreign} from Greece or of unknown origin, {foreign} from other countries",
            len(rows))
    return rows, ggbn_counts(names)
