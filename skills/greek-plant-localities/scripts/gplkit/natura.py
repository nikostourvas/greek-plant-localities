"""Natura 2000 Standard Data Forms and Habitats Directive Article 17 grids (EEA).

Natura 2000 gives the sites whose Standard Data Form lists the species (with
population size and data quality) but no points; we keep the site centroid.
Article 17 (2019-2024 round) gives the reported 10x10 km distribution, only
for species in the Habitats Directive annexes, and with sensitive species
removed from the public version.
"""
from __future__ import annotations

import math

from . import net

B = "https://bio.discomap.eea.europa.eu/arcgis/rest/services"
N2K = f"{B}/ProtectedSites/Natura2000Species/MapServer/0/query"
ART17 = f"{B}/Article17/ART17_2019_2024_public/MapServer"

N2K_FIELDS = {
    "SiteCode": "site_code", "NaturaSitePolygon_WM_Public_SITENAME": "site_name",
    "NaturaSitePolygon_WM_Public_SITETYPE": "site_type", "CONTAINSSPECIES_SPECIESNAME": "species_as_listed",
    "CONTAINSSPECIES_POPULATION": "population_rating", "CONTAINSSPECIES_ABUNDANCECATEGORY": "abundance_category",
    "LOWERBOUND": "pop_min", "UPPERBOUND": "pop_max", "COUNTINGUNIT": "unit",
    "CONTAINSSPECIES_DATAQUALITY": "data_quality", "CONTAINSSPECIES_MOTIVATION": "motivation",
    "CONTAINSSPECIES_SENSITIVE": "sensitive", "NaturaSitePolygon_WM_Public_Area_km2": "area_km2",
    "NaturaSitePolygon_WM_Public_POINT_X": "_x", "NaturaSitePolygon_WM_Public_POINT_Y": "_y",
}


def _merc_to_wgs(x, y):
    lon = x / 6378137.0 * 180 / math.pi
    lat = (2 * math.atan(math.exp(y / 6378137.0)) - math.pi / 2) * 180 / math.pi
    return round(lat, 5), round(lon, 5)


def _q(s: str) -> str:
    return s.replace("'", "''")


def natura2000_sites(names: dict) -> list[dict]:
    rows, seen = [], set()
    for name in names["extended_names"]:
        d = net.get(N2K, {"where": f"CONTAINSSPECIES_COUNTRYCODE='GR' AND SpeciesNameClean LIKE '{_q(name)}%'",
                          "outFields": ",".join(N2K_FIELDS), "returnGeometry": "false", "f": "json"},
                    source="Natura 2000 SDF")
        for f in (d or {}).get("features", []):
            a = f["attributes"]
            if a["SiteCode"] in seen:
                continue
            seen.add(a["SiteCode"])
            row = {v: a.get(k) for k, v in N2K_FIELDS.items()}
            if row["_x"] and row["_y"]:
                row["latitude"], row["longitude"] = _merc_to_wgs(row["_x"], row["_y"])
            row.pop("_x"), row.pop("_y")
            row["sdf_url"] = f"https://natura2000.eea.europa.eu/Natura2000/SDF.aspx?site={a['SiteCode']}"
            rows.append(row)
    net.log("Natura 2000 SDF", "ok", "", len(rows))
    return rows


def article17_grid(names: dict) -> dict | None:
    """Return a GeoJSON FeatureCollection of Greece's Art. 17 distribution, or None."""
    code = None
    for name in names["extended_names"]:
        d = net.get(f"{ART17}/16/query", {"where": f"species_name LIKE '{_q(name)}%'", "outFields": "species_code,species_name",
                                          "returnGeometry": "false", "f": "json"}, source="Article 17")
        feats = (d or {}).get("features", [])
        if feats:
            code = feats[0]["attributes"]["species_code"]
            break
    if not code:
        net.log("Article 17", "not_listed", "species not in Habitats Directive annexes (or not in reference list)")
        return None
    gj = net.get(f"{ART17}/6/query", {
        "where": f"species_distribution3857_diss_multi_public.species_code='{code}' AND species_distribution3857_diss_multi_public.country='EL'",
        "outFields": "*", "returnGeometry": "true", "outSR": "4326", "geometryPrecision": "5", "f": "geojson"},
        source="Article 17")
    feats = (gj or {}).get("features", [])
    for f in feats:
        f["properties"] = {k.split(".")[-1]: v for k, v in f["properties"].items()}
    net.log("Article 17", "ok" if feats else "empty", f"species_code={code}", len(feats))
    return {"type": "FeatureCollection", "features": feats, "species_code": code} if feats else None
