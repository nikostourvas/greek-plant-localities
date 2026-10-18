"""Gazetteer lookups for georeferencing literature localities.

GeoNames (needs a free username in config; best for mountains, peaks,
gorges and alternate spellings) and Nominatim/OpenStreetMap (1 req/s, no
bulk use). Results are candidates: Claude picks one and records the method.
"""
from __future__ import annotations

from . import config, net

GREECE_VIEWBOX = "19.2,41.8,29.8,34.7"


def geonames(q: str, n: int = 8) -> list[dict]:
    user = config.load().get("geonames_username")
    if not user:
        return []
    d = net.get("http://api.geonames.org/searchJSON", {"q": q, "country": "GR", "maxRows": n, "username": user,
                                                       "style": "FULL", "orderby": "relevance"}, source="GeoNames")
    if d and d.get("status"):
        net.log("GeoNames", "error", d["status"].get("message", ""))
        return []
    return [{"gazetteer": "GeoNames", "name": g.get("name"), "alt_names": ",".join(
                a["name"] for a in (g.get("alternateNames") or [])[:8] if a.get("lang") in ("el", "en", "", None)),
             "feature": f"{g.get('fcode')} ({g.get('fcodeName')})", "admin": ", ".join(filter(None, [g.get("adminName1"), g.get("adminName2")])),
             "latitude": float(g["lat"]), "longitude": float(g["lng"]), "elevation_m": g.get("elevation") or g.get("srtm3"),
             "id": f"https://www.geonames.org/{g['geonameId']}"} for g in (d or {}).get("geonames", [])]


def nominatim(q: str, n: int = 6) -> list[dict]:
    d = net.get("https://nominatim.openstreetmap.org/search", {"q": q, "countrycodes": "gr", "format": "jsonv2",
                                                               "limit": n, "accept-language": "en,el", "namedetails": 1},
                source="Nominatim")
    return [{"gazetteer": "Nominatim/OSM", "name": r.get("name") or r.get("display_name", "").split(",")[0],
             "alt_names": ",".join(v for k, v in (r.get("namedetails") or {}).items() if k in ("name:el", "name:en", "old_name", "alt_name")),
             "feature": f"{r.get('category')}:{r.get('type')}", "admin": r.get("display_name", "")[:150],
             "latitude": float(r["lat"]), "longitude": float(r["lon"]), "elevation_m": "",
             "id": f"https://www.openstreetmap.org/{r.get('osm_type')}/{r.get('osm_id')}"} for r in (d or [])]


def lookup(q: str) -> list[dict]:
    return geonames(q) + nominatim(q)
