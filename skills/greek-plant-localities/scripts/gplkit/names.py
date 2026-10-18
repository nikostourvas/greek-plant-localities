"""Name resolution: accepted name, synonyms and Greek distribution.

Sources: Flora of Greece (Dimopoulos et al. 2013, 2016 checklist, CDM API),
Euro+Med PlantBase (same API), GBIF backbone, JACQ. The union of all names is
what every later search uses, because old herbarium labels and theses often
use synonyms.
"""
from __future__ import annotations

import re

from . import net

FOG = "https://api.cybertaxonomy.org/flora-greece"
EUROMED = "https://api.cybertaxonomy.org/euromed"
GBIF = "https://api.gbif.org/v1"
JACQ = "https://services.jacq.org/jacq-services/rest"

def canonical(name: str) -> str:
    """Strip authors and 'sec. ...' from a CDM/GBIF title string."""
    name = re.sub(r"\s+sec\..*$", "", name).replace(" syn.", "").strip()
    toks = name.split()
    out = []
    for i, t in enumerate(toks):
        if i == 0 or (t[:1].islower() and t not in ("de", "van", "von", "ex", "et", "&")) or t in ("subsp.", "var.", "f.", "×"):
            out.append(t)
        elif i >= 2 and out and out[-1] in ("subsp.", "var.", "f."):
            out.append(t)
        else:
            break
    return " ".join(out)


def _walk_titles(o, klass: str, acc: list):
    if isinstance(o, dict):
        if o.get("class") == klass and "titleCache" in o:
            acc.append(o["titleCache"])
        for v in o.values():
            _walk_titles(v, klass, acc)
    elif isinstance(o, list):
        for v in o:
            _walk_titles(v, klass, acc)


def _cdm(base: str, name: str, label: str) -> dict:
    out = {"source": label, "found": False}
    find = net.get(f"{base}/portal/taxon/find", {"query": name, "doTaxa": "true", "doSynonyms": "true",
                                                  "pageSize": 20, "pageIndex": 0}, source=label)
    if not find:
        return out
    recs = [r for r in find.get("records", []) if r.get("class") in ("Taxon", "Synonym")]
    target = canonical(name)
    taxon = None
    for r in recs:
        if r["class"] == "Taxon" and canonical(r.get("titleCache", "")) == target:
            taxon = r
            break
    if taxon is None:
        # the query may be a synonym: follow it to its accepted taxon
        for r in recs:
            if r["class"] == "Synonym" and canonical(r.get("titleCache", "")) == target:
                acc = net.get(f"{base}/portal/taxon/{r['uuid']}/accepted", source=label)
                if isinstance(acc, list) and acc:
                    acc = acc[0]
                if isinstance(acc, dict) and acc.get("uuid"):
                    taxon = acc
                break
    if taxon is None:
        net.log(label, "not_found", name)
        return out
    out.update(found=True, uuid=taxon["uuid"], accepted=canonical(taxon["titleCache"]),
               accepted_full=re.sub(r"\s+sec\..*$", "", taxon["titleCache"]))
    syn = net.get(f"{base}/portal/taxon/{taxon['uuid']}/synonymy", source=label) or {}
    titles: list[str] = []
    _walk_titles(syn, "Synonym", titles)
    out["synonyms_full"] = sorted({re.sub(r"\s+(syn\.\s+)?sec\..*$", "", t) for t in titles})
    out["synonyms"] = sorted({canonical(t) for t in titles} - {out["accepted"]})
    dist = net.get(f"{base}/description/distributionInfoFor/{taxon['uuid']}", {"part": "tree"}, source=label)
    areas = []

    def walk(node):
        for d in node.get("data") or []:
            a = d.get("area", {})
            areas.append({"area": a.get("label"), "code": a.get("abbrevLabel") or a.get("idInVocabulary"),
                          "status": (d.get("status") or {}).get("label")})
        for c in node.get("children") or []:
            walk(c)
    if dist and dist.get("tree"):
        walk(dist["tree"]["rootElement"])
    out["distribution"] = areas
    net.log(label, "ok", out["accepted"], len(out["synonyms"]))
    return out


def gbif(name: str) -> dict:
    m = net.get(f"{GBIF}/species/match", {"name": name, "kingdom": "Plantae", "verbose": "true"}, source="GBIF backbone")
    if not m or m.get("matchType") == "NONE":
        net.log("GBIF backbone", "not_found", name)
        return {"source": "GBIF backbone", "found": False}
    key = m.get("acceptedUsageKey") or m["usageKey"]
    info = net.get(f"{GBIF}/species/{key}", source="GBIF backbone") or {}
    syns, offset = [], 0
    while True:
        page = net.get(f"{GBIF}/species/{key}/synonyms", {"limit": 100, "offset": offset}, source="GBIF backbone")
        if not page:
            break
        syns += [s.get("canonicalName") for s in page.get("results", []) if s.get("canonicalName")]
        if page.get("endOfRecords", True):
            break
        offset += 100
    out = {"source": "GBIF backbone", "found": True, "taxonKey": key, "matchType": m.get("matchType"),
           "confidence": m.get("confidence"), "accepted": info.get("canonicalName") or m.get("canonicalName"),
           "accepted_full": info.get("scientificName"), "family": info.get("family"),
           "synonyms": sorted(set(syns))}
    net.log("GBIF backbone", "ok", f"{out['accepted']} key={key}", len(out["synonyms"]))
    return out


def jacq(name: str) -> dict:
    r = net.get(f"{JACQ}/JACQscinames/find/{name}", source="JACQ names")
    if not r:
        return {"source": "JACQ", "found": False}
    ids = r if isinstance(r, list) else r.get("result") or [r]
    return {"source": "JACQ", "found": bool(ids), "raw": ids[:5]}


def resolve(name: str) -> dict:
    name = " ".join(name.split())
    fog = _cdm(FOG, name, "Flora of Greece")
    em = _cdm(EUROMED, fog.get("accepted", name), "Euro+Med")
    gb = gbif(fog.get("accepted", name))
    accepted = fog.get("accepted") or em.get("accepted") or gb.get("accepted") or canonical(name)

    def usable(n):  # binomials, or trinomials with an explicit rank (GBIF's rank-less trinomials never occur in text)
        t = n.split()
        return len(t) == 2 or (len(t) >= 4 and t[2] in ("subsp.", "var.", "f."))

    # core: curated synonymy (Flora of Greece, Euro+Med), used by the slow, throttled repository searches
    core = {canonical(name), accepted}
    for src in (fog, em):
        core |= set(src.get("synonyms", []))
        if src.get("accepted"):
            core.add(src["accepted"])
    if not fog.get("found") and not em.get("found"):
        core |= set(gb.get("synonyms", []))
    # extended: + GBIF synonyms, used by fast searches (full text, DiSSCo, JACQ, Natura 2000).
    # GBIF lists may contain homonyms/misapplied names; text hits are reviewed by Claude.
    extended = core | set(gb.get("synonyms", [])) | ({gb["accepted"]} if gb.get("accepted") else set())
    core = sorted(n for n in core if n and usable(n) and n != accepted)
    extended = sorted(n for n in extended if n and usable(n) and n != accepted)
    genus, epithet = accepted.split()[:2]
    return {
        "query": name,
        "accepted": accepted,
        "accepted_full": fog.get("accepted_full") or gb.get("accepted_full") or accepted,
        "family": gb.get("family"),
        "search_names": [accepted] + core,
        "extended_names": [accepted] + extended,
        "gbif_taxon_key": gb.get("taxonKey"),
        "genus": genus,
        "epithet": epithet,
        "greek_distribution": fog.get("distribution", []),
        "flora_of_greece": fog,
        "euromed": em,
        "gbif": gb,
        "jacq": jacq(accepted),
    }
