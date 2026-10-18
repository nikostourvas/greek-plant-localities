"""Full-text search of floras and reports for the species' names.

Three corpora:
  * the user's private PDFs (config "local_pdfs": files or folders),
  * PDFs of Zotero collections (config "zotero_collections", read straight
    from zotero.sqlite, so Zotero's MCP server is not needed),
  * public-domain classic floras on the Internet Archive (Halácsy's
    Conspectus Florae Graecae, Boissier's Flora Orientalis), downloaded once
    as OCR text and cached.
Each hit gives file, page and a context window; Claude reads the windows and
extracts the localities.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import time
import unicodedata
from pathlib import Path

from . import config, net

CLASSIC_FLORAS = {
    "conspectusflorae01hal": "Halácsy, Conspectus Florae Graecae vol. 1 (1900)",
    "conspectusflorae02hal": "Halácsy, Conspectus Florae Graecae vol. 2 (1902)",
    "conspectusflorae03hal": "Halácsy, Conspectus Florae Graecae vol. 3 (1904)",
    "conspectusflora02halgoog": "Halácsy, Conspectus Florae Graecae Supplementum (1908)",
    "floraorientaliss01bois": "Boissier, Flora Orientalis vol. 1 (1867)",
    "floraorientaliss02bois": "Boissier, Flora Orientalis vol. 2 (1872)",
    "floraorientaliss03bois": "Boissier, Flora Orientalis vol. 3 (1875)",
    "floraorientaliss04bois": "Boissier, Flora Orientalis vol. 4 (1879)",
    "floraorientaliss05bois": "Boissier, Flora Orientalis vol. 5 (1884)",
    "PierreEdmondBoissierFloraOrientalisSiveEnumeratioPlantarumInOrienteAGraeciaEtAeg": "Boissier, Flora Orientalis Supplementum (1888)",
}

# Greek society proceedings (verified 2026-10-19). Downloaded once; only the
# extracted text is kept in the cache. Add new volumes here.
HEL = "https://www.helecos.gr/el/activities/helecos-congresses"
HBS = "https://www.hbs.gr/sites/default/files/conferences"
WB = "https://web.archive.org/web"
PROCEEDINGS = {
    "HELECOS 2nd (2004) Mytilini": f"{HEL}/2004-2nd-helecos-conference/Proceedings_Mytilini_2004.pdf",
    "HELECOS 3rd (2006) Ioannina": f"{HEL}/2006-3rd-helecos-conference/Proceedings_Ioannina_2006.pdf",
    "HELECOS 4th (2008) Volos": f"{HEL}/2008-4th-helecos-conference/Proceedings_Volos_2008.pdf",
    "HELECOS 5th (2010) Patra": f"{HEL}/2010-5th-helecos-conference/Proceedings_Patra_2010.pdf",
    "HELECOS 6th (2012) Athens": f"{HEL}/2012-6th-helecos-conference/Proceedings_Athens_2012.pdf",
    "HELECOS 7th (2014) Mytilini": f"{HEL}/2014-7th-helecos-conference/Proceedings_Mytilini_2014.pdf",
    "HELECOS 8th (2016) Thessaloniki": f"{HEL}/2016-8th-helecos-conference/Proceedings_Thessaloniki_2016.pdf",
    "HELECOS 9th (2018) abstracts": f"{HEL}/2018-9th-helecos-conference/Book-of-abstracts-HELECOS9.pdf",
    "HELECOS 10th (2021) proceedings": f"{HEL}/2021-10th-helecos-conference/helecos10-proceedings-final.pdf",
    "HELECOS 11th (2023) abstracts": f"{HEL}/2023-11th-helecos-conference/HELECOS11-abstracts-024.pdf",
    "HELECOS 12th (2025) abstracts": f"{HEL}/2025-12th-helecos-conference/HELECOS12-2025-abstracts.pdf",
    "Hellenic Botanical Society 5th (1994)": f"{HBS}/5o-synedrio-1994.pdf",
    "Hellenic Botanical Society 6th (1996)": f"{HBS}/6o-synedrio-1996.pdf",
    "Hellenic Botanical Society 7th (1998)": f"{HBS}/7o-synedrio-1998-0.pdf",
    "Hellenic Botanical Society 8th (2000)": f"{HBS}/8o-synedrio-2000.pdf",
    "Hellenic Botanical Society 9th (2002)": f"{HBS}/9o-sinedrio-2002.pdf",
    "Hellenic Botanical Society 10th (2005)": f"{HBS}/10o-sinedrio-2005.pdf",
    "Hellenic Botanical Society 11th abstracts": f"{HBS}/ebe11-programme-abstracts.pdf",
    "Hellenic Botanical Society 12th abstracts": f"{HBS}/ebe12-book-abstracts.pdf",
    "Hellenic Botanical Society 12th abstracts suppl.": f"{HBS}/ebe12-book-abstracts-supplement.pdf",
    "Hellenic Botanical Society 13th abstracts": f"{HBS}/ebe13-book-abstracts.pdf",
    "Hellenic Botanical Society 14th (2015) abstracts": f"{HBS}/ebe14-2015-book-abstracts.pdf",
    "Hellenic Botanical Society 15th (2017) abstracts": f"{HBS}/ebe15-2017-book-abstracts.pdf",
    "Hellenic Botanical Society 16th (2019)": f"{HBS}/ebe16o-sinedrio-2019.pdf",
    "Hellenic Botanical Society 17th / HELECOS 10th (2021) abstracts": f"{HBS}/helecos-10-book-abstracts-final.pdf",
    "Hellenic Botanical Society 18th (2024) abstracts": "https://www.hbs.gr/sites/default/files/conference18-2024/EBE18-book-of-abstracts-1.00.pdf",
    "Hellenic Forestry Society 17th (2015)": f"{WB}/20211011185327id_/https://www.forestry.gr/assets/pdf/praktika/TELIKA%20PRAKTIKA%20SYNEDRIOY%20EDE%202015.pdf",
    "Hellenic Forestry Society 2017 workshop (Edessa)": "https://www.forestry.gr/assets/pdf/conf/FULL%20CONGRESS%20PROCEEDINGS%20HFS%202017%20WORKSHOP%202(2)%20with%20ISBN.pdf",
    "Hellenic Forestry Society 18th (2018)": f"{WB}/20220522114515id_/https://www.forestry.gr/assets/pdf/praktika/praktika2018.pdf",
    "Hellenic Forestry Society 19th (2019) part 1": f"{WB}/20210917193627id_/https://www.forestry.gr/assets/pdf/praktika/PRAKTIKA%20EDE_part1.pdf",
    "Hellenic Forestry Society 19th (2019) part 2": f"{WB}/20211128113456id_/https://www.forestry.gr/assets/pdf/praktika/PRAKTIKA%20EDE_part2.pdf",
    "Hellenic Forestry Society 20th (2021) Trikala": "http://hexdec.xtreemhost.com/praktika21.pdf",
    "Hellenic Forestry Society 21st (2023)": "http://hexdec.xtreemhost.com/praktika23.pdf",
    "Hellenic Forestry Society 22nd (2025) Ioannina": "https://forestry.gr/assets/pdf/PRAKTIKA2025.pdf",
}
GEOTEE_INDEX = "https://geotee.gr/geotechnika-epistimonika-themata/"  # «Γεωτεχνικά Επιστημονικά Θέματα» issues

BEFORE, AFTER = 300, 3000
MAX_HITS_PER_FILE = 60


def patterns(names: dict) -> list[tuple[str, re.Pattern, str | None]]:
    """(label, regex, genus required nearby). Abbreviated names ("Z. abelicea")
    only count when the full genus name occurs on the same or previous page,
    otherwise "A. cretica" would match every Arabis/Anchusa/... cretica."""
    pats = []
    for n in names["extended_names"]:
        toks = [re.escape(t) for t in n.split()]
        pats.append((n, re.compile(r"\b" + r"\s+".join(toks) + r"\b", re.I), None))
    for n in names["extended_names"]:
        genus, rest = n.split(" ", 1)
        toks = [re.escape(t) for t in rest.split()]
        pats.append((f"{genus[0]}. {rest}", re.compile(r"\b" + re.escape(genus[0]) + r"\.\s*" + r"\s+".join(toks) + r"\b"), genus))
    return pats


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\u2206", "\u0394")  # Greek PDFs often encode Δ as ∆
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # re-join hyphenated line breaks
    return re.sub(r"[ \t]+", " ", text)


def _search_pages(pages: list[str], pats, label: str, path: str) -> list[dict]:
    hits = []
    prev = ""
    for pno, raw in enumerate(pages, 1):
        page = _normalise(raw)
        nxt = _normalise(pages[pno]) if pno < len(pages) else ""
        joined = page + "\n" + nxt  # locality lists often run onto the next page
        for term, pat, genus in pats:
            if genus and genus not in page and genus not in prev:
                continue
            for m in pat.finditer(page):
                hits.append({"corpus": label, "file": path, "page": pno, "matched": term,
                             "_start": m.start(), "_end": m.end(), "_text": joined})
        prev = page
    # merge hits on the same page whose windows overlap (an entry listing several synonyms)
    hits.sort(key=lambda h: (h["page"], h["_start"]))
    merged: list[dict] = []
    for h in hits:
        last = merged[-1] if merged else None
        if last and last["page"] == h["page"] and h["_start"] <= last["_end"] + AFTER // 2:
            if h["matched"] not in last["matched"].split(", "):
                last["matched"] += ", " + h["matched"]
            last["_end"] = max(last["_end"], h["_end"])
            continue
        merged.append(h)
    out = []
    for h in merged[:MAX_HITS_PER_FILE]:
        s = max(0, h["_start"] - BEFORE)
        out.append({"corpus": h["corpus"], "file": h["file"], "page": h["page"], "matched": h["matched"],
                    "context": h["_text"][s:h["_end"] + AFTER].strip()})
    return out


def _pdf_pages(path: Path) -> list[str]:
    st = path.stat()
    key = hashlib.sha256(f"{path}:{st.st_size}:{st.st_mtime}".encode()).hexdigest()
    cp = config.cache_dir() / "pdftext" / f"{key}.json"
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    import pymupdf as fitz
    fitz.TOOLS.mupdf_display_errors(False)  # damaged-but-readable PDFs are common
    with fitz.open(path) as doc:
        pages = [p.get_text() for p in doc]
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return pages


def _expand(paths) -> list[Path]:
    out = []
    for p in paths:
        p = Path(p).expanduser()
        if p.is_dir():
            out += sorted(p.rglob("*.pdf")) + sorted(p.rglob("*.PDF"))
        elif p.exists():
            out.append(p)
    return out


def zotero_pdfs(collections: list[str], data_dir: str) -> list[tuple[str, Path]]:
    """(item title, pdf path) for every PDF in the named collections and their subcollections."""
    d = Path(data_dir).expanduser()
    db = d / "zotero.sqlite"
    if not db.exists() or not collections:
        return []
    with tempfile.TemporaryDirectory() as tmp:  # copy: Zotero keeps the live DB locked
        local = Path(tmp) / "z.sqlite"
        shutil.copy(db, local)
        con = sqlite3.connect(local)
        cols = con.execute("SELECT collectionID, collectionName, parentCollectionID FROM collections").fetchall()
        wanted = {c[0] for c in cols if c[1] in collections}
        grew = True
        while grew:
            new = {c[0] for c in cols if c[2] in wanted} - wanted
            grew = bool(new)
            wanted |= new
        if not wanted:
            net.log("Zotero", "not_found", f"collections {collections}")
            return []
        q = f"""
        SELECT COALESCE(v.value, ''), att.key, ia.path
        FROM collectionItems ci
        JOIN itemAttachments ia ON ia.parentItemID = ci.itemID
        JOIN items att ON att.itemID = ia.itemID
        LEFT JOIN itemData idt ON idt.itemID = ci.itemID
             AND idt.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'title')
        LEFT JOIN itemDataValues v ON v.valueID = idt.valueID
        WHERE ci.collectionID IN ({",".join(map(str, wanted))}) AND ia.contentType = 'application/pdf'
        """
        rows = con.execute(q).fetchall()
        con.close()
    out = []
    for title, key, path in rows:
        if path and path.startswith("storage:"):
            p = d / "storage" / key / path[len("storage:"):]
        else:
            p = Path(path or "")
        if p.exists():
            out.append((title, p))
    return out


def _ia_text(identifier: str) -> list[str] | None:
    cp = config.cache_dir() / "classic" / f"{identifier}.txt"
    if not cp.exists():
        meta = net.get(f"https://archive.org/metadata/{identifier}", source="Internet Archive")
        files = [f["name"] for f in (meta or {}).get("files", []) if f["name"].endswith("_djvu.txt")]
        if not files:
            net.log("Internet Archive", "error", f"no OCR text for {identifier}")
            return None
        txt = net.get(f"https://archive.org/download/{identifier}/{files[0]}", source="Internet Archive",
                      as_json=False, cache=False, timeout=180)
        if not txt:
            return None
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(txt, encoding="utf-8")
    text = cp.read_text(encoding="utf-8")
    # djvu.txt has form feeds between pages in most items; fall back to fixed chunks
    pages = text.split("\f") if text.count("\f") > 20 else [text[i:i + 4000] for i in range(0, len(text), 4000)]
    return pages


def _remote_pdf_pages(url: str, label: str) -> list[str] | None:
    """Download a public PDF once, keep only its text (pages) in the cache."""
    key = hashlib.sha256(url.encode()).hexdigest()
    cp = config.cache_dir() / "corpus" / f"{key}.json"
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    fail = config.cache_dir() / "corpus" / f"{key}.failed"
    if fail.exists() and (time.time() - fail.stat().st_mtime) < 7 * 86400:
        return None  # retry failed downloads weekly, not on every run
    import pymupdf as fitz
    fitz.TOOLS.mupdf_display_errors(False)  # damaged-but-readable PDFs are common
    cp.parent.mkdir(parents=True, exist_ok=True)
    host = re.match(r"https?://([^/]+)", url).group(1)
    net._throttle(host)
    try:
        with net.session().get(url, stream=True, timeout=120) as r:
            if r.status_code != 200 or "pdf" not in r.headers.get("content-type", "pdf"):
                raise RuntimeError(f"HTTP {r.status_code} {r.headers.get('content-type')}")
            with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
                for chunk in r.iter_content(1 << 20):
                    tmp.write(chunk)
                tmp.flush()
                with fitz.open(tmp.name) as doc:
                    pages = [p.get_text() for p in doc]
    except Exception as e:
        fail.write_text(str(e))
        net.log("Proceedings corpus", "error", f"{label}: {e}. Download by hand: {url}")
        return None
    if sum(len(p) for p in pages) < 200 * max(1, len(pages)):
        net.log("Proceedings corpus", "warning", f"{label}: scanned without text layer (needs OCR)")
    cp.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return pages


def corpus_items() -> dict[str, str]:
    items = dict(PROCEEDINGS)
    h = net.get(GEOTEE_INDEX, source="GEOTEE index", as_json=False)
    for m in re.finditer(r'href="(https://geotee\.gr/wp-content/uploads/[^"]+\.pdf)"', h or ""):
        items[f"ΓΕΩΤΕΕ Γεωτεχνικά Επιστημονικά Θέματα: {m.group(1).rsplit('/', 1)[-1]}"] = m.group(1)
    return items


def search(names: dict, extra_paths=(), classic: bool = True, proceedings: bool = True) -> list[dict]:
    cfg = config.load()
    pats = patterns(names)
    hits = []
    files = [(p.name, p) for p in _expand(list(cfg.get("local_pdfs", [])) + list(extra_paths))]
    files += zotero_pdfs(cfg.get("zotero_collections", []), cfg.get("zotero_data_dir", "~/Zotero"))
    seen = set()
    for title, p in files:
        if p in seen:
            continue
        seen.add(p)
        try:
            pages = _pdf_pages(p)
        except Exception as e:
            net.log("local PDFs", "error", f"{p.name}: {e}")
            continue
        if sum(len(x) for x in pages) < 200 * len(pages):
            net.log("local PDFs", "warning", f"{p.name}: little or no text layer (needs OCR)")
        h = _search_pages(pages, pats, f"private: {title or p.name}", str(p))
        net.log("local PDFs", "ok", p.name, len(h))
        hits += h
    if classic:
        for ident, label in CLASSIC_FLORAS.items():
            pages = _ia_text(ident)
            if pages:
                h = _search_pages(pages, pats, label, f"https://archive.org/details/{ident}")
                for x in h:
                    x["page"] = f"~{x['page']}"  # page index in the OCR file, not the printed page number
                hits += h
        net.log("Classic floras (IA)", "ok", "", sum(1 for h in hits if not h["corpus"].startswith("private")))
    if proceedings:
        n = 0
        for label, url in corpus_items().items():
            pages = _remote_pdf_pages(url, label)
            if pages:
                h = _search_pages(pages, pats, label, url)
                n += len(h)
                hits += h
        net.log("Proceedings corpus", "ok", "HELECOS, Hellenic Botanical & Forestry Societies, ΓΕΩΤΕΕ", n)
    return hits
