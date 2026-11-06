"""Occurrence harvesting: GBIF, DiSSCo Hellas, JACQ, iNaturalist.

All records are mapped to one flat schema (FIELDS) so that they can be
deduplicated and written to CSV / GeoPackage / KML together.
"""
from __future__ import annotations

import re

from . import net
from .names import canonical

FIELDS = [
    "record_id", "source", "source_url", "scientific_name", "basis", "institution", "catalog_number",
    "collector", "record_number", "event_date", "year", "country", "region", "locality", "elevation_m",
    "latitude", "longitude", "uncertainty_m", "coords_generalised", "license", "dna", "notes", "dup_group",
    "is_primary",
]

GREECE_WKT = "POLYGON((19.2 34.7,29.8 34.7,29.8 41.8,19.2 41.8,19.2 34.7))"
GBIF_MAX = 20000  # beyond this the GBIF download API (with DOI) is the right tool


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _year(date):
    m = re.match(r"(\d{4})", str(date or ""))
    return int(m.group(1)) if m else None


def _herbarium_from_catalog(cat) -> str:
    """Index Herbariorum-style acronym at the start of a catalogue number ("B 10 0196469",
    "L.2868810", "TAU024127"), for records that do not name their herbarium."""
    m = re.match(r"^([A-Z]{1,6})[\s.:\-]*\d", str(cat or ""))
    return m.group(1) if m else ""


DNA_EXT = "http://rs.gbif.org/terms/1.0/DNADerivedData"
GGBN_EXT = "http://data.ggbn.org/schemas/ggbn/terms/"


def _gbif_dna(r: dict) -> str:
    """'DNA-derived data: rbcL', 'GGBN material sample', associated sequences, or '' (GBIF record)."""
    ext = r.get("extensions") or {}
    out = []
    if ext.get(DNA_EXT):
        genes = sorted({str(v) for e in ext[DNA_EXT] for k, v in e.items() if k.endswith("0000044") and v})  # MIxS target_gene
        out.append("DNA-derived data" + (f": {', '.join(genes)}" if genes else ""))
    if any(k.startswith(GGBN_EXT) for k in ext):
        out.append("GGBN material sample (DNA/tissue bank)")
    if r.get("associatedSequences"):
        out.append(f"sequences: {r['associatedSequences']}")
    if r.get("isSequenced") and not out:
        out.append("sequenced")
    return "; ".join(out)


def _herbarium_code(catalog, collection_code, basis) -> str:
    """Herbarium of a specimen whose record leaves out institutionCode: the catalogue-number prefix,
    else a collection code that looks like an acronym (not "Botany" or "Herbarium")."""
    if "OBSERVATION" in str(basis or "").upper():
        return ""
    cc = str(collection_code or "")
    return _herbarium_from_catalog(catalog) or (cc if re.fullmatch(r"[A-Z][A-Z-]{0,9}", cc) else "")


def _rec(**kw) -> dict:
    r = {k: "" for k in FIELDS}
    r.update({k: v for k, v in kw.items() if v is not None})
    return r


# ---------------------------------------------------------------- GBIF
def _gbif_page(params: dict, label: str):
    out, offset = [], 0
    while True:
        p = dict(params, limit=300, offset=offset)
        page = net.get("https://api.gbif.org/v1/occurrence/search", p, source=label)
        if not page:
            break
        out += page.get("results", [])
        if page.get("endOfRecords", True) or len(out) >= GBIF_MAX:
            break
        offset += 300
    return out, (page or {}).get("count")


def _gbif_other_keys(names: dict, key: int) -> dict[int, str]:
    """GBIF keys, outside the main taxon, of names we search: records filed under
    them are missed by taxonKey=<main key>. This happens when GBIF treats a
    synonym or a name misapplied in Greek floras as a separate taxon (e.g.
    Satureja graveolens, Thymus graveolens for Acinos graveolens).

    Only exact species-level matches count ("Acinos rotundifolius" matches just
    the genus Acinos). A key is used only if GBIF files the name under one of our
    names, or if the name is curated (Flora of Greece synonym, misapplied in
    Greek floras, or added by hand): a homonym such as Melissa graveolens Host
    (= M. officinalis) would otherwise bring in another species."""
    wanted = {n.lower() for n in names["extended_names"]}
    curated = set(names["search_names"])
    out = {}
    for n in names["extended_names"][1:]:
        m = net.get("https://api.gbif.org/v1/species/match", {"name": n, "kingdom": "Plantae", "strict": "true"},
                    source="GBIF (other names)")
        if not m or m.get("matchType") != "EXACT" or m.get("rank") not in ("SPECIES", "SUBSPECIES", "VARIETY", "FORM"):
            continue
        k, acc = m.get("usageKey"), m.get("acceptedUsageKey") or m.get("usageKey")
        if key in (k, acc, m.get("speciesKey")):
            continue  # already covered by taxonKey=<main key>
        if (m.get("species") or "").lower() in wanted:
            out.setdefault(acc, n)  # GBIF files the name under one of our names: take that whole taxon
        elif n in curated:
            out.setdefault(k, n)  # curated name GBIF files elsewhere: only the records under this name
    return out


def gbif(names: dict) -> list[dict]:
    key = names.get("gbif_taxon_key")
    if not key:
        net.log("GBIF", "skipped", "no GBIF taxon key")
        return []
    recs, count = _gbif_page({"taxonKey": key, "country": "GR"}, "GBIF")
    if count and count > GBIF_MAX:
        net.log("GBIF", "truncated", f"{count} records; only {GBIF_MAX} fetched. Use the GBIF download API (DOI) for the full set.")
    # Records inside Greece with no/unknown country code are missed by country=GR.
    extra, _ = _gbif_page({"taxonKey": key, "geometry": GREECE_WKT}, "GBIF (no country code)")
    seen = {r["key"] for r in recs}
    recs += [r for r in extra if r["key"] not in seen and r.get("countryCode") in (None, "", "ZZ")]
    via = {}
    for k, n in _gbif_other_keys(names, key).items():
        c = (net.get("https://api.gbif.org/v1/occurrence/search", {"taxonKey": k, "country": "GR", "limit": 0},
                     source="GBIF (other names)") or {}).get("count", 0)
        if c > max(500, 3 * (count or 0)):
            net.log("GBIF (other names)", "skipped", f"'{n}' (taxonKey {k}): {c} Greek records, too many for a synonym; check by hand")
            continue
        more, _ = _gbif_page({"taxonKey": k, "country": "GR"}, "GBIF (other names)") if c else ([], 0)
        new = [r for r in more if r["key"] not in seen]
        seen |= {r["key"] for r in new}
        recs += new
        via |= {r["key"]: n for r in new}
        net.log("GBIF (other names)", "ok", f"'{n}' taxonKey={k}", len(new))
    out = []
    for r in recs:
        issues = r.get("issues") or []
        out.append(_rec(
            source="GBIF", source_url=f"https://www.gbif.org/occurrence/{r['key']}",
            record_id=f"gbif:{r['key']}", scientific_name=r.get("scientificName"),
            basis=r.get("basisOfRecord"),
            institution=r.get("institutionCode") or _herbarium_code(r.get("catalogNumber"), r.get("collectionCode"), r.get("basisOfRecord")),
            catalog_number=r.get("catalogNumber"), collector=r.get("recordedBy"),
            record_number=r.get("recordNumber") or r.get("fieldNumber"), event_date=r.get("eventDate", "")[:10],
            year=r.get("year"), country=r.get("countryCode"), region=r.get("stateProvince"),
            locality=r.get("locality") or r.get("verbatimLocality"),
            elevation_m=r.get("elevation"), latitude=r.get("decimalLatitude"),
            longitude=r.get("decimalLongitude"), uncertainty_m=r.get("coordinateUncertaintyInMeters"),
            coords_generalised="yes" if r.get("dataGeneralizations") or "COORDINATE_ROUNDED" in issues else "",
            license=r.get("license"), dna=_gbif_dna(r),
            notes="; ".join(filter(None, [r.get("datasetName"), ",".join(issues),
                                          f"det. {r['identifiedBy']} {str(r.get('dateIdentified') or '')[:10]}".strip()
                                          if r.get("identifiedBy") else "",
                                          f"found via the name '{via[r['key']]}'" if r["key"] in via else ""])),
        ))
    net.log("GBIF", "ok", f"taxonKey={key}", len(out))
    return out


# ---------------------------------------------------------------- DiSSCo Hellas
DGR = "https://dissco-gr.nhmc.uoc.gr"


def dissco_gr(names: dict) -> list[dict]:
    wanted = {n.lower() for n in names["extended_names"]}
    pairs = sorted({tuple(n.split()[:2]) for n in names["extended_names"]})
    out, seen = [], set()
    for genus, epithet in pairs:
        page = 1
        while True:
            d = net.get(f"{DGR}/api/catalog", {"filter_genus": genus, "search": epithet, "perPage": 200, "page": page},
                        source="DiSSCo Hellas")
            if not d or not d.get("success"):
                break
            for r in d.get("data", []):
                sn = canonical(r.get("scientificName", "")).lower()
                if not any(sn == w or sn.startswith(w + " ") for w in wanted):  # name or its infraspecific taxa
                    continue
                if r["occurrenceID"] in seen:
                    continue
                seen.add(r["occurrenceID"])
                withheld = r.get("informationWithheld") or ""
                out.append(_rec(
                    source="DiSSCo Hellas", record_id=f"dgr:{r['occurrenceID']}",
                    source_url=f"{DGR}/catalog/record/{r['occurrenceID']}",
                    scientific_name=r.get("scientificName"), basis=r.get("basisOfRecord"),
                    institution=r.get("institutionCode"), catalog_number=r.get("catalogNumber"),
                    collector=r.get("recordedBy"), record_number=r.get("recordNumber"),
                    event_date=(r.get("eventDate") or "")[:10], year=_year(r.get("eventDate")),
                    country="GR", region=", ".join(filter(None, [r.get("stateProvince"), r.get("county"), r.get("municipality"), r.get("island")])),
                    locality=r.get("locality"), latitude=_f(r.get("decimalLatitude")),
                    longitude=_f(r.get("decimalLongitude")), uncertainty_m=_f(r.get("coordinateUncertaintyInMeters")),
                    coords_generalised="yes" if (r.get("dataGeneralizations") or "withheld" in withheld.lower()) else "",
                    license=r.get("license"),
                    notes="; ".join(filter(None, [r.get("Institution Name"), r.get("dataGeneralizations"), withheld])),
                ))
            if page >= (d.get("totalPages") or 1):
                break
            page += 1
    net.log("DiSSCo Hellas", "ok", "", len(out))
    return out


# ---------------------------------------------------------------- JACQ
JACQ = "https://services.jacq.org/jacq-services/rest/objects/specimens"


def jacq(names: dict) -> list[dict]:
    out, seen = [], set()
    for name in names["extended_names"]:
        p = 0
        while True:
            d = net.get(JACQ, {"term": name, "nation": "Greece", "list": 0, "rpp": 100, "p": p}, source="JACQ")
            if not d:
                break
            for item in d.get("result", []):
                dwc, jq = item.get("dwc", {}), item.get("jacq", {})
                sid = dwc.get("dwc:materialSampleID") or jq.get("jacq:stableIdentifier")
                if sid in seen:
                    continue
                seen.add(sid)
                # the herbarium: the collection code (Index Herbariorum code, e.g. W), else JACQ's owner
                # abbreviation (NHMW for W) or the catalogue number
                herb = (dwc.get("dwc:collectionCode") or jq.get("jacq:OwnerOrganizationAbbrev")
                        or _herbarium_from_catalog(dwc.get("dwc:catalogNumber")))
                # some JACQ herbaria (e.g. B) put the catalogue number in recordNumber; the collector number is jacq:Nummer
                rec_no = dwc.get("dwc:recordNumber")
                if not rec_no or rec_no == dwc.get("dwc:catalogNumber"):
                    rec_no = jq.get("jacq:Nummer") or dwc.get("dwc:fieldNumber") or ""
                out.append(_rec(
                    source="JACQ", record_id=f"jacq:{jq.get('jacq:specimenID')}", source_url=sid,
                    scientific_name=dwc.get("dwc:scientificName"), basis=dwc.get("dwc:basisOfRecord"),
                    institution=herb, catalog_number=dwc.get("dwc:catalogNumber"),
                    collector=dwc.get("dwc:recordedBy"), record_number=rec_no,
                    event_date=dwc.get("dwc:eventDate"), year=_year(dwc.get("dwc:eventDate")),
                    country="GR", locality=dwc.get("dwc:locality"),
                    latitude=dwc.get("dwc:decimalLatitude"), longitude=dwc.get("dwc:decimalLongitude"),
                    notes="; ".join(filter(None, ["no coordinate uncertainty in JACQ",
                                                  f"identifications: {dwc['dwc:previousIdentifications']}"
                                                  if dwc.get("dwc:previousIdentifications") else ""])),
                ))
            if p + 1 >= (d.get("totalPages") or 1):
                break
            p += 1
    net.log("JACQ", "ok", "", len(out))
    return out


# ---------------------------------------------------------------- iNaturalist
INAT = "https://api.inaturalist.org/v1"
INAT_GREECE = 7094


def inaturalist(names: dict) -> list[dict]:
    # iNaturalist may accept another name (e.g. Clinopodium graveolens for Acinos graveolens):
    # take its taxon if its name is any of ours, trying the names other checklists accept too
    wanted = {n.lower() for n in names["extended_names"]}
    queries = dict.fromkeys(n for n in (names["accepted"], (names.get("gbif") or {}).get("accepted"),
                                        (names.get("catalogue_of_life") or {}).get("accepted")) if n)
    taxa = []
    for q in queries:
        t = net.get(f"{INAT}/taxa", {"q": q, "is_active": "true", "per_page": 10}, source="iNaturalist")
        taxa = [x for x in (t or {}).get("results", []) if x.get("name", "").lower() in wanted]
        if taxa:
            break
    if not taxa:
        net.log("iNaturalist", "not_found", ", ".join(queries))
        return []
    tid = taxa[0]["id"]
    out, page = [], 1
    while page <= 20:
        d = net.get(f"{INAT}/observations", {"taxon_id": tid, "place_id": INAT_GREECE, "per_page": 200, "page": page,
                                             "order_by": "id", "order": "asc"}, source="iNaturalist")
        if not d:
            break
        for o in d.get("results", []):
            lat = lon = None
            if o.get("location"):
                lat, lon = (float(v) for v in o["location"].split(","))
            obscured = o.get("obscured") or o.get("taxon_geoprivacy") in ("obscured", "private")
            out.append(_rec(
                source="iNaturalist", record_id=f"inat:{o['id']}", source_url=o.get("uri"),
                scientific_name=(o.get("taxon") or {}).get("name"), basis="HUMAN_OBSERVATION",
                institution="iNaturalist", catalog_number=str(o["id"]),
                collector=(o.get("user") or {}).get("login"), event_date=o.get("observed_on"),
                year=_year(o.get("observed_on")), country="GR", locality=o.get("place_guess"),
                latitude=lat, longitude=lon,
                uncertainty_m=28000 if obscured else o.get("positional_accuracy"),
                coords_generalised="yes" if obscured else "",
                license=o.get("license_code"), notes=f"quality_grade={o.get('quality_grade')}",
            ))
        if page * 200 >= d.get("total_results", 0):
            break
        page += 1
    net.log("iNaturalist", "ok", f"taxon_id={tid}", len(out))
    return out


# ---------------------------------------------------------------- dedup
def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _surname(collector) -> str:
    c = str(collector or "").split(";")[0].split("&")[0].split(",")[0].strip()
    toks = [t for t in re.split(r"[\s.]+", c) if len(t) > 2]
    return _norm(max(toks, key=len)) if toks else ""


def deduplicate(recs: list[dict]) -> list[dict]:
    """Group duplicates and mark one primary record per group.

    Two records are duplicates when they share institution+catalog number
    (same sheet seen via GBIF and JACQ/DiSSCo, or an iNaturalist obs. also in
    GBIF), or the same collector surname + exact date + collector number
    (duplicate sheets in different herbaria).
    """
    parent = list(range(len(recs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    index: dict[str, int] = {}
    for i, r in enumerate(recs):
        keys = []
        if r["catalog_number"]:
            inst = _norm(r["institution"]).replace("inaturalist", "inat")
            keys.append(f"cat:{inst}:{_norm(r['catalog_number'])}")
        sur, date = _surname(r["collector"]), str(r["event_date"] or "")[:10]
        observation = "OBSERVATION" in str(r["basis"]).upper() or r["institution"] == "iNaturalist"
        if sur and len(date) == 10 and not observation:  # one gathering, sheets in several herbaria
            keys.append(f"col:{sur}:{date}:{_norm(r['record_number'])}")
        for k in keys:
            if k in index:
                union(i, index[k])
            else:
                index[k] = i
    groups: dict[int, list[int]] = {}
    for i in range(len(recs)):
        groups.setdefault(find(i), []).append(i)

    def quality(r):
        has = r["latitude"] not in ("", None)
        unc = _f(r["uncertainty_m"])
        return (has, r["coords_generalised"] != "yes", -(unc if unc is not None else 1e7),
                r["source"] in ("DiSSCo Hellas", "JACQ"))

    for n, members in enumerate(groups.values(), 1):
        best = max(members, key=lambda i: quality(recs[i]))
        for i in members:
            recs[i]["dup_group"] = n
            recs[i]["is_primary"] = "yes" if i == best else ""
    return recs


def harvest(names: dict, sources=("gbif", "dissco_gr", "jacq", "inaturalist")) -> list[dict]:
    funcs = {"gbif": gbif, "dissco_gr": dissco_gr, "jacq": jacq, "inaturalist": inaturalist}
    recs = []
    for s in sources:
        try:
            recs += funcs[s](names)
        except Exception as e:  # one broken source must not stop the run
            net.log(s, "error", f"{type(e).__name__}: {e}")
    for r in recs:
        for k in ("latitude", "longitude"):
            r[k] = _f(r[k]) if r[k] != "" else ""
        if r["latitude"] == 0 and r["longitude"] == 0:
            r["latitude"] = r["longitude"] = ""
    return deduplicate(recs)
