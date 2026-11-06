"""Herbarium codes: what "B", "LD" or "COI" stand for.

Specimen databases name herbaria by their Index Herbariorum code (B = Berlin, K = Kew, LD = Lund),
sometimes by a database-specific name instead (NHMW for W, NMNHG for ATH). `canonical()` maps those
to the Index Herbariorum code and `describe()` looks the codes up in the Index Herbariorum API
(https://sweetgum.nybg.org/science/ih/), so that reports and maps can say where a specimen is kept.
"""
from __future__ import annotations

import urllib.parse

from . import net

IH = "https://sweetgum.nybg.org/science/api/v1/institutions"
IH_PAGE = "https://sweetgum.nybg.org/science/ih/herbarium-details/?irn="

# database-specific institution names -> Index Herbariorum code
ALIASES = {
    "NHMW": "W",  # JACQ owner abbreviation of the Vienna museum
    "MNHN": "P",
    "Moscow State University": "MW",
    "UNIBAS:HERBARIA": "BAS",
    "School of Biology, Aristotle University of Thessaloniki": "TAU",
    "HB-AUTH": "TAU",  # DiSSCo Hellas codes
    "HB-NKUA": "ATHU",
    "NMNHG": "ATH",
}
NOT_NAMED = "herbarium not named"


def canonical(inst: str) -> str:
    inst = (inst or "").strip()
    return ALIASES.get(inst, inst)


def describe(codes) -> dict[str, dict]:
    """code -> {code, name, city, country, url}; name is empty when Index Herbariorum doesn't know the code."""
    out = {}
    for code in sorted({c for c in codes if c}):
        e = {"code": code, "name": "", "city": "", "country": "", "url": ""}
        if code == NOT_NAMED:
            e["name"] = "a specimen is cited, but the source doesn't say where it is kept"
        elif " " not in code and len(code) <= 12:
            d = net.get(f"{IH}/{urllib.parse.quote(code)}", source="Index Herbariorum")
            if isinstance(d, dict) and d.get("code") == code:
                a = d.get("address") or {}
                e.update(name=" – ".join(filter(None, [(d.get("organization") or "").strip(" ,"), d.get("division")])),
                         city=a.get("physicalCity") or "", country=a.get("physicalCountry") or "",
                         url=f"{IH_PAGE}{d['irn']}" if d.get("irn") else "")
        out[code] = e
    found = sum(1 for e in out.values() if e["name"])
    net.log("Index Herbariorum", "ok", f"{found} of {len(out)} herbarium codes resolved", found)
    return out


def short(code: str, info: dict[str, dict]) -> str:
    """'B (Berlin, Germany)' for maps and GPS descriptions."""
    e = info.get(code) or {}
    place = ", ".join(filter(None, [e.get("city"), e.get("country")]))
    return f"{code} ({place})" if place else code
