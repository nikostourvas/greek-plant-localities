"""Literature and grey-literature leads.

Produces "leads": documents that mention the species and may contain
localities. Metadata only; Claude then reads abstracts / open PDFs of the
promising ones. Greek repositories are queried slowly (see net.HOST_DELAY).
"""
from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup

from . import net

LEAD_FIELDS = ["source", "kind", "title", "authors", "year", "institution", "url", "matched", "abstract"]

GREEK_CONTEXT = "(Greece OR Greek OR Hellas OR Crete OR Kriti OR Peloponnese OR Peloponnisos OR Aegean OR Macedonia OR Thrace OR Epirus OR Ionian)"


def _lead(**kw) -> dict:
    d = {k: "" for k in LEAD_FIELDS}
    d.update({k: (v if v is not None else "") for k, v in kw.items()})
    d["abstract"] = re.sub(r"\s+", " ", str(d["abstract"]))[:700]
    d["title"] = re.sub(r"\s+", " ", html.unescape(str(d["title"]))).strip()
    return d


# ------------------------------------------------- openarchives.gr (EKT aggregator)
OA = "https://www.openarchives.gr/aggregator-openarchives"
OA_TYPES = {
    "MSc thesis": "http://semantics.gr/authorities/openarchives-item-types/metaptyxiakh-ergasia",
    "Diploma/BSc thesis": "http://semantics.gr/authorities/openarchives-item-types/ptyxiakh-ergasia",
    "PhD thesis": "http://semantics.gr/authorities/openarchives-item-types/PhD-thesis",
    "any": None,
}


def openarchives(names: dict, max_pages: int = 4) -> list[dict]:
    out, seen = [], set()
    for term in names["search_names"]:
        for kind, t in OA_TYPES.items():
            for page in range(1, max_pages + 1):
                params = {"portalSearches[0].keywords[0].value": term, "page.page": page}  # unquoted = AND; quotes act as OR here
                if t:
                    params["portalSearches[0].ektTypes"] = t
                h = net.get(f"{OA}/portal/advancedSearch/search", params, source="openarchives.gr", as_json=False)
                if not h:
                    break
                soup = BeautifulSoup(h, "html.parser")
                items = soup.select("div.media-body")
                for it in items:
                    a = it.select_one("h5.media-heading a")
                    if not a or "/edm/" not in a.get("href", ""):
                        continue
                    url = "https://www.openarchives.gr" + a["href"]
                    if url in seen:
                        continue
                    seen.add(url)
                    f = {}
                    for div in it.find_all("div", recursive=False):
                        lab = div.find("strong")
                        if lab:
                            f[lab.get_text(" ", strip=True).rstrip(":").strip()] = " | ".join(
                                s.get_text(" ", strip=True) for s in div.find_all("span"))
                    out.append(_lead(source="openarchives.gr", kind=f.get("Τύπος τεκμηρίου", kind),
                                     title=a.get_text(" ", strip=True), authors=f.get("Δημιουργός"),
                                     year=f.get("Χρονολογία"), institution=f.get("Φορέας") or f.get("Συλλογή"),
                                     url=url, matched=term, abstract=f.get("Επιστημονικό πεδίο", "")))
                if len(items) < 30:
                    break
    net.log("openarchives.gr", "ok", "", len(out))
    return out


# ------------------------------------------------- didaktorika.gr (PhD theses)
def didaktorika(names: dict) -> list[dict]:
    out, seen = [], set()
    for term in names["search_names"]:  # quoted = phrase; unquoted words are OR-ed here
        h = net.get("https://www.didaktorika.gr/eadd/simple-search", {"query": f'"{term}"', "rpp": 100, "start": 0},
                    source="didaktorika.gr", as_json=False)
        if not h:
            continue
        soup = BeautifulSoup(h, "html.parser")
        for row in soup.select("table tr"):
            a = row.find("a", href=re.compile(r"^/eadd/handle/10442/\d+$"))
            if not a:
                continue
            url = "https://www.didaktorika.gr" + a["href"]
            if url in seen:
                continue
            seen.add(url)
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            out.append(_lead(source="didaktorika.gr", kind="PhD thesis", title=a.get_text(" ", strip=True),
                             year=cells[0] if cells else "", authors=cells[-1] if len(cells) > 2 else "",
                             url=url, matched=term))
    net.log("didaktorika.gr", "ok", "PDFs are behind a CAPTCHA: download by hand", len(out))
    return out


# ------------------------------------------------- DSpace repositories not (fully) in openarchives
DSPACE7 = {  # REST discover endpoints (full-text indexed where the repository extracts text)
    "Amitos (Univ. Peloponnese)": "https://amitos.library.uop.gr/server/api/discover/search/objects",
    "IHU Repository": "https://repository-api.ihu.gr/server/api/discover/search/objects",
    "Hellanicus (Univ. Aegean)": "https://hellanicus-api.lib.aegean.gr/server/api/discover/search/objects",
}
DSPACE6 = {  # XMLUI discover pages
    "Dione (Univ. Piraeus)": "https://dione.lib.unipi.gr/xmlui/discover",
    "UTH IR (Univ. Thessaly)": "http://ir.lib.uth.gr/xmlui/discover",
    "TEI West Greece repository": "http://repository.teiwest.gr/xmlui/discover",
}


def _md(md, key):
    v = md.get(key) or []
    return " | ".join(x.get("value", "") for x in v)


def dspace(names: dict) -> list[dict]:
    out = []
    for term in names["search_names"]:
        for label, url in DSPACE7.items():
            d = net.get(url, {"query": f'"{term}"', "dsoType": "ITEM", "size": 50}, source=label)
            objs = (((d or {}).get("_embedded") or {}).get("searchResult") or {}).get("_embedded", {}).get("objects", [])
            for o in objs:
                it = o["_embedded"]["indexableObject"]
                md = it.get("metadata", {})
                out.append(_lead(source=label, kind=_md(md, "dc.type"), title=_md(md, "dc.title"),
                                 authors=_md(md, "dc.contributor.author"), year=_md(md, "dc.date.issued")[:4],
                                 institution=label, url=_md(md, "dc.identifier.uri") or f"handle:{it.get('handle')}",
                                 matched=term, abstract=_md(md, "dc.description.abstract")))
        for label, url in DSPACE6.items():
            h = net.get(url, {"query": f'"{term}"', "rpp": 50}, source=label, as_json=False)
            if not h:
                continue
            soup = BeautifulSoup(h, "html.parser")
            base = re.match(r"https?://[^/]+", url).group(0)
            for div in soup.select("div.ds-artifact-item"):
                a = div.select_one(".artifact-description a[href*='/handle/']") or div.find("a", href=re.compile(r"/handle/"))
                if not a:
                    continue
                title = div.select_one(".artifact-title") or a.find("h4") or a
                auth = div.select_one(".author")
                date = div.select_one(".date")
                abst = div.select_one(".abstract")
                out.append(_lead(source=label, kind="", title=title.get_text(" ", strip=True),
                                 authors=auth.get_text(" ", strip=True) if auth else "",
                                 year=(date.get_text(strip=True)[:4] if date else ""), institution=label,
                                 url=base + a["href"], matched=term,
                                 abstract=abst.get_text(" ", strip=True) if abst else ""))
    uniq = {(l["source"], l["url"]): l for l in out}
    net.log("DSpace repositories", "ok", "", len(uniq))
    return list(uniq.values())


# ------------------------------------------------- OpenAIRE Graph (theses from Greek institutions)
def openaire(names: dict) -> list[dict]:
    out, seen = [], set()
    for term in names["search_names"]:
        for itype in ("Master thesis", "Doctoral thesis", "Bachelor thesis", None):
            p = {"search": f'"{term}"', "pageSize": 100}
            if itype:
                p.update(instanceType=itype, countryCode="GR")
            d = net.get("https://api.openaire.eu/graph/v1/researchProducts", p, source="OpenAIRE")
            for r in (d or {}).get("results", []):
                if r["id"] in seen:
                    continue
                seen.add(r["id"])
                urls = [u for i in r.get("instances", []) for u in (i.get("urls") or [])]
                out.append(_lead(source="OpenAIRE", kind=itype or (r.get("instances") or [{}])[0].get("type", ""),
                                 title=r.get("mainTitle"), year=(r.get("publicationDate") or "")[:4],
                                 authors="; ".join(a.get("fullName", "") for a in (r.get("authors") or [])[:4]),
                                 institution=r.get("publisher"), url=urls[0] if urls else "", matched=term,
                                 abstract=" ".join(r.get("descriptions") or [])))
    net.log("OpenAIRE", "ok", "", len(out))
    return out


# ------------------------------------------------- OpenAlex (journal literature)
def openalex(names: dict, max_results: int = 300) -> list[dict]:
    from . import config
    q = "(" + " OR ".join(f'"{n}"' for n in names["search_names"]) + ") AND " + GREEK_CONTEXT
    out, cursor = [], "*"
    while cursor and len(out) < max_results:
        p = {"search": q, "per-page": 100, "cursor": cursor,
             "select": "id,doi,display_name,publication_year,authorships,primary_location,abstract_inverted_index,type"}
        if config.load().get("openalex_api_key"):
            p["api_key"] = config.load()["openalex_api_key"]
        elif config.load().get("contact_email"):
            p["mailto"] = config.load()["contact_email"]
        d = net.get("https://api.openalex.org/works", p, source="OpenAlex")
        if not d:
            break
        for w in d.get("results", []):
            inv = w.get("abstract_inverted_index") or {}
            words = sorted(((i, k) for k, v in inv.items() for i in v))
            src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
            out.append(_lead(source="OpenAlex", kind=w.get("type"), title=w.get("display_name"),
                             year=w.get("publication_year"), institution=src,
                             authors="; ".join(a["author"]["display_name"] for a in (w.get("authorships") or [])[:4]),
                             url=w.get("doi") or w.get("id"), matched="name + Greek context",
                             abstract=" ".join(k for _, k in words)))
        cursor = (d.get("meta") or {}).get("next_cursor")
        if not d.get("results"):
            break
        if not config.load().get("openalex_api_key"):
            if cursor:
                net.log("OpenAlex", "truncated", "first 100 results only; add a free OpenAlex API key (gpl.py config --openalex-key) for more")
            break  # without a key the shared per-IP budget refuses further pages
    net.log("OpenAlex", "ok", "", len(out))
    return out


# ------------------------------------------------- Plazi TreatmentBank
def plazi(names: dict) -> list[dict]:
    out, seen = [], set()
    for term in names["search_names"]:
        x = net.get("https://tb.plazi.org/GgServer/search", {
            "taxonomicName.isNomenclature": "true", "taxonomicName.exactMatch": "true",
            "taxonomicName.taxonomicName": term, "resultFormat": "xml"}, source="Plazi", as_json=False)
        if not x:
            continue
        for m in re.finditer(r"<document ([^>]*)>", x):
            attrs = dict(re.findall(r'([\w.\-]+)="([^"]*)"', m.group(1)))
            doc = attrs.get("docId")
            if not doc or doc in seen:
                continue
            seen.add(doc)
            master = html.unescape(attrs.get("masterDocTitle", ""))
            title = html.unescape(attrs.get("docTitle", ""))
            gen = names["genus"].lower()
            if gen not in title.lower() and not any(n.split()[0].lower() in title.lower() for n in names["search_names"]):
                continue  # treatment of another taxon that only cites ours (e.g. host plant)
            out.append(_lead(source="Plazi", kind="treatment" + (" (Red Data Book of Greece)" if "Red Data Book" in master else ""),
                             title=f"{title} — in: {master}", authors=html.unescape(attrs.get("docAuthor", "")),
                             year=attrs.get("docDate"), institution=html.unescape(attrs.get("docOrigin", "")),
                             url=f"https://treatment.plazi.org/id/{doc}", matched=term))
    net.log("Plazi", "ok", "", len(out))
    return out


# ------------------------------------------------- Zenodo
def zenodo(names: dict) -> list[dict]:
    out, seen = [], set()
    hits = []
    sn = names["search_names"]
    for i in range(0, len(sn), 4):  # long OR queries make Zenodo return HTTP 500
        q = " OR ".join(f'"{n}"' for n in sn[i:i + 4])
        for page in range(1, 5):  # unauthenticated requests are capped at 25 per page
            d = net.get("https://zenodo.org/api/records", {"q": q, "size": 25, "page": page, "sort": "bestmatch"}, source="Zenodo")
            batch = (d or {}).get("hits", {}).get("hits", [])
            hits += batch
            if len(batch) < 25:
                break
    for h in hits:
        md = h.get("metadata", {})
        if h["id"] in seen:
            continue
        seen.add(h["id"])
        out.append(_lead(source="Zenodo", kind=(md.get("resource_type") or {}).get("title", ""),
                         title=md.get("title"), year=(md.get("publication_date") or "")[:4],
                         authors="; ".join(c.get("name", "") for c in (md.get("creators") or [])[:4]),
                         url=h.get("links", {}).get("self_html") or h.get("doi_url"), matched="name",
                         abstract=BeautifulSoup(md.get("description") or "", "html.parser").get_text(" ")))
    net.log("Zenodo", "ok", "", len(out))
    return out


SOURCES = {
    "openarchives": openarchives, "didaktorika": didaktorika, "dspace": dspace, "openaire": openaire,
    "openalex": openalex, "plazi": plazi, "zenodo": zenodo,
}


def harvest(names: dict, sources=None) -> list[dict]:
    leads = []
    for s in sources or SOURCES:
        try:
            leads += SOURCES[s](names)
        except Exception as e:
            net.log(s, "error", f"{type(e).__name__}: {e}")
    return leads
