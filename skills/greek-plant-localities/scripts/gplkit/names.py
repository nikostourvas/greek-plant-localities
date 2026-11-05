"""Name resolution: accepted name, synonyms and Greek distribution.

Sources: Flora of Greece (Dimopoulos et al. 2013, 2016 checklist, CDM API),
Euro+Med PlantBase (same API), GBIF backbone, Catalogue of Life (WCVP
synonymy, including that of infraspecific taxa), JACQ. The union of all names
is what every later search uses, because old herbarium labels and theses often
use synonyms.

Flora of Greece also lists names misapplied to the taxon in Greek floras
("auct. fl. graec."). Older Greek literature and herbaria file the taxon under
exactly these names, so they are searched like synonyms.
"""
from __future__ import annotations

import re

from . import net

FOG = "https://api.cybertaxonomy.org/flora-greece"
EUROMED = "https://api.cybertaxonomy.org/euromed"
GBIF = "https://api.gbif.org/v1"
COL = "https://api.checklistbank.org/dataset/3LR"  # latest Catalogue of Life release
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
    out["misapplied"] = _misapplied(base, taxon["uuid"], label)
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
    net.log(label, "ok", out["accepted"], len(out["synonyms"]) + len(out["misapplied"]))
    return out


def _misapplied(base: str, uuid: str, label: str) -> list[dict]:
    """Names misapplied to the taxon (CDM 'misapplied for' relations), e.g.
    "Acinos rotundifolius auct. fl. graec., non Pers."."""
    d = net.get(f"{base}/portal/taxon/{uuid}/taxonRelationshipsDTO", source=label) or {}
    out = []
    for r in d.get("relations") or []:
        if not r.get("misapplication"):
            continue
        tt = r.get("taggedText") or []
        name = " ".join(t["text"] for t in tt if t.get("type") in ("name", "rank") and t.get("text"))
        if name:
            full = re.sub(r'^\W+', "", (r.get("cache") or name).replace('"', "")).strip()
            out.append({"name": name, "full": full, "doubtful": bool(r.get("doubtful"))})
    return out


def col(candidates: list[str], species_level: bool) -> dict:
    """Catalogue of Life (WCVP-based) synonymy of the taxon and of its infraspecific taxa.

    WCVP often ranks a Flora of Greece species as a subspecies (or the reverse),
    so for a species query the parent species and all its children are used."""
    out = {"source": "Catalogue of Life", "found": False}
    usage = None
    for q in candidates:
        d = net.get(f"{COL}/nameusage/search", {"q": q, "limit": 20}, source="Catalogue of Life") or {}
        for r in d.get("result", []):
            u = r.get("usage") or {}
            if (u.get("name") or {}).get("scientificName", "").lower() != q.lower():
                continue
            if "synonym" in (u.get("status") or ""):
                u = u.get("accepted") or {}
            elif u.get("status") not in ("accepted", "provisionally accepted"):
                continue
            if u.get("id"):
                usage = u
                break
        if usage:
            break
    if not usage:
        net.log("Catalogue of Life", "not_found", candidates[0] if candidates else "")
        return out
    taxon = net.get(f"{COL}/taxon/{usage['id']}", source="Catalogue of Life") or {}
    if species_level and (taxon.get("name") or {}).get("rank") not in (None, "species") and taxon.get("parentId"):
        taxon = net.get(f"{COL}/taxon/{taxon['parentId']}", source="Catalogue of Life") or taxon
    tid = taxon.get("id") or usage["id"]
    accepted = (taxon.get("name") or {}).get("scientificName") or (usage.get("name") or {}).get("scientificName")
    ids = {tid: accepted}
    kids = net.get(f"{COL}/tree/{tid}/children", {"limit": 100}, source="Catalogue of Life") or {}
    for k in kids.get("result") or []:
        if k.get("id") and k.get("name"):
            ids[k["id"]] = k["name"]
    syns, misapplied = set(), set()
    for i in ids:
        s = net.get(f"{COL}/taxon/{i}/synonyms", source="Catalogue of Life") or {}
        for kind in ("homotypic", "heterotypic", "misapplied"):
            for u in s.get(kind) or []:
                n = (u.get("name") or {}).get("scientificName") if isinstance(u, dict) else None
                if n:
                    (misapplied if kind == "misapplied" or u.get("status") == "misapplied" else syns).add(n)
    out.update(found=True, id=tid, accepted=accepted, infraspecific=sorted(set(ids.values()) - {accepted}),
               synonyms=sorted(syns - {accepted}), misapplied=sorted(misapplied))
    net.log("Catalogue of Life", "ok", f"{accepted} id={tid}", len(syns) + len(ids) - 1)
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


def resolve(name: str, add=(), drop=()) -> dict:
    """All names to search for a taxon.

    search_names (core) are curated and used by every search, including the slow,
    throttled Greek repository searches: Flora of Greece and Euro+Med synonyms,
    names misapplied in Greek floras, and names added by hand (`add`).
    extended_names add the GBIF and Catalogue of Life synonyms and infraspecific
    names, for the fast searches (full text, GBIF, DiSSCo, JACQ, Natura 2000).
    These lists may contain homonyms; text hits are reviewed by Claude.
    Names in `drop` are removed from both.
    """
    name = " ".join(name.split())
    add = [" ".join(n.split()) for n in add if n.strip()]
    drop = {" ".join(n.split()) for n in drop if n.strip()}
    fog = _cdm(FOG, name, "Flora of Greece")
    em = _cdm(EUROMED, fog.get("accepted", name), "Euro+Med")
    gb = gbif(fog.get("accepted", name))
    accepted = fog.get("accepted") or em.get("accepted") or gb.get("accepted") or canonical(name)
    cands = list(dict.fromkeys(n for n in (accepted, em.get("accepted"), gb.get("accepted"), canonical(name)) if n))
    cl = col(cands, species_level=len(accepted.split()) == 2)

    def usable(n):  # binomials, or trinomials with an explicit rank (GBIF's rank-less trinomials never occur in text)
        t = n.split()
        return len(t) == 2 or (len(t) >= 4 and t[2] in ("subsp.", "var.", "f."))

    table: dict[str, dict] = {}

    def note(n, source, kind, tier):
        if not n or (source != "added by hand" and not usable(n)):
            return
        e = table.setdefault(n, {"name": n, "sources": [], "kinds": [], "tier": tier})
        if source not in e["sources"]:
            e["sources"].append(source)
        if kind not in e["kinds"]:
            e["kinds"].append(kind)
        if tier == "core":
            e["tier"] = "core"

    # without a curated (Flora of Greece / Euro+Med) synonymy, the GBIF and COL synonyms become core
    curated = fog.get("found") or em.get("found")
    note(canonical(name), "query", "query", "core")
    for src in (fog, em):
        if src.get("accepted"):
            note(src["accepted"], src["source"], "accepted", "core")
        for n in src.get("synonyms", []):
            note(n, src["source"], "synonym", "core")
    for m in fog.get("misapplied", []):
        note(m["name"], "Flora of Greece", "misapplied in Greek floras", "core")
    for m in em.get("misapplied", []):
        note(m["name"], "Euro+Med", "misapplied", "extended")
    if gb.get("accepted"):
        note(gb["accepted"], "GBIF", "accepted", "extended")
    for n in gb.get("synonyms", []):
        note(n, "GBIF", "synonym", "extended" if curated else "core")
    if cl.get("found"):
        note(cl["accepted"], "Catalogue of Life", "accepted", "extended")
        for n in cl.get("infraspecific", []):
            note(n, "Catalogue of Life", "infraspecific taxon", "extended")
        for n in cl.get("synonyms", []):
            note(n, "Catalogue of Life", "synonym", "extended" if curated else "core")
        for n in cl.get("misapplied", []):
            note(n, "Catalogue of Life", "misapplied", "extended")
    for n in add:
        note(n, "added by hand", "added by hand", "core")
    for n in drop | {accepted}:
        table.pop(n, None)
    rows = sorted(table.values(), key=lambda e: (e["tier"] != "core", e["name"]))
    genus, epithet = accepted.split()[:2]
    return {
        "query": name,
        "accepted": accepted,
        "accepted_full": fog.get("accepted_full") or gb.get("accepted_full") or accepted,
        "family": gb.get("family"),
        "search_names": [accepted] + [e["name"] for e in rows if e["tier"] == "core"],
        "extended_names": [accepted] + [e["name"] for e in rows],
        "misapplied_names": [m["full"] for m in fog.get("misapplied", [])],
        "name_table": [{"name": accepted, "sources": ["Flora of Greece" if fog.get("found") else "resolved"],
                        "kinds": ["accepted"], "tier": "core"}] + rows,
        "manual": {"add": add, "drop": sorted(drop)},
        "gbif_taxon_key": gb.get("taxonKey"),
        "genus": genus,
        "epithet": epithet,
        "greek_distribution": fog.get("distribution", []),
        "flora_of_greece": fog,
        "euromed": em,
        "gbif": gb,
        "catalogue_of_life": cl,
        "jacq": jacq(accepted),
    }
