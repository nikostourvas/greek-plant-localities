"""Writers: CSV, GeoPackage (pure stdlib), KML, GPX; candidate-site clustering."""
from __future__ import annotations

import csv
import datetime as dt
import math
import sqlite3
import struct
from pathlib import Path
from xml.sax.saxutils import escape


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    fields = fields or (list(rows[0].keys()) if rows else ["empty"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def has_xy(r) -> bool:
    return _num(r.get("latitude")) is not None and _num(r.get("longitude")) is not None


# ------------------------------------------------------------------ clustering
def haversine_m(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def candidate_sites(recs: list[dict], radius_m: float = 1000, max_uncertainty_m: float | None = 5000,
                    prefix: str = "S") -> list[dict]:
    """Single-linkage clusters of primary records.

    Sites (default): precise records only. Records with generalised
    coordinates or uncertainty above `max_uncertainty_m` are left out because
    they point to an area, not a site. Areas: call with radius_m=10000,
    max_uncertainty_m=None to cluster every record with coordinates.
    """
    pts = []
    for r in recs:
        if r.get("is_primary", "yes") != "yes" or not has_xy(r):
            continue
        unc = _num(r.get("uncertainty_m"))
        if max_uncertainty_m is not None and (r.get("coords_generalised") == "yes" or (unc is not None and unc > max_uncertainty_m)):
            continue
        pts.append(r)
    n = len(pts)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    xy = [(_num(p["latitude"]), _num(p["longitude"])) for p in pts]
    order = sorted(range(n), key=lambda i: xy[i][0])
    for a_idx, i in enumerate(order):  # sweep on latitude to avoid all pairs
        for j in order[a_idx + 1:]:
            if (xy[j][0] - xy[i][0]) * 111000 > radius_m:
                break
            if haversine_m(xy[i], xy[j]) <= radius_m:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    sites = []
    for members in groups.values():
        lat = sum(xy[i][0] for i in members) / len(members)
        lon = sum(xy[i][1] for i in members) / len(members)
        years = [int(float(pts[i]["year"])) for i in members if _num(pts[i].get("year"))]
        uncs = [_num(pts[i].get("uncertainty_m")) for i in members if _num(pts[i].get("uncertainty_m")) is not None]
        locs = [str(pts[i].get("locality") or "") for i in members if pts[i].get("locality")]
        sites.append({
            "latitude": round(lat, 5), "longitude": round(lon, 5), "n_records": len(members),
            "sources": ", ".join(sorted({pts[i]["source"] for i in members})),
            "first_year": min(years) if years else "", "last_year": max(years) if years else "",
            "best_uncertainty_m": min(uncs) if uncs else "",
            "example_locality": max(locs, key=len)[:200] if locs else "",
            "n_generalised": sum(1 for i in members if pts[i].get("coords_generalised") == "yes"),
            "record_ids": " ".join(pts[i]["record_id"] for i in members)[:1000],
        })
    sites.sort(key=lambda s: (-(s["last_year"] or 0), -s["n_records"]))
    for k, s in enumerate(sites, 1):
        s["site_id"] = f"{prefix}{k:03d}"
    return sites


# ------------------------------------------------------------------ GeoPackage
def _wkb_point(x, y) -> bytes:
    return struct.pack("<BIdd", 1, 1, x, y)


def _wkb_polygon(rings) -> bytes:
    b = struct.pack("<BII", 1, 3, len(rings))
    for ring in rings:
        b += struct.pack("<I", len(ring)) + b"".join(struct.pack("<dd", x, y) for x, y, *_ in ring)
    return b


def _wkb_multipolygon(polys) -> bytes:
    return struct.pack("<BII", 1, 6, len(polys)) + b"".join(_wkb_polygon(p) for p in polys)


def _gpb(wkb: bytes, env=None) -> bytes:
    if env is None:
        return b"GP" + struct.pack("<BBi", 0, 0b00000001, 4326) + wkb
    return b"GP" + struct.pack("<BBi", 0, 0b00000011, 4326) + struct.pack("<dddd", *env) + wkb


def _geom_blob(geom: dict):
    t = geom["type"]
    if t == "Point":
        x, y = geom["coordinates"][:2]
        return _gpb(_wkb_point(x, y)), (x, y, x, y)
    polys = [geom["coordinates"]] if t == "Polygon" else geom["coordinates"]
    xs = [p[0] for poly in polys for ring in poly for p in ring]
    ys = [p[1] for poly in polys for ring in poly for p in ring]
    env = (min(xs), max(xs), min(ys), max(ys))
    return _gpb(_wkb_multipolygon(polys), env), (env[0], env[2], env[1], env[3])


def write_gpkg(path: Path, layers: dict[str, tuple[str, list[tuple[dict, dict]]]]) -> None:
    """layers: name -> (geometry type 'POINT'|'MULTIPOLYGON', [(geojson geometry, properties), ...])."""
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    c = con.cursor()
    c.execute("PRAGMA application_id = 1196444487")  # 'GPKG'
    c.execute("PRAGMA user_version = 10200")
    c.executescript("""
    CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY, organization TEXT NOT NULL,
      organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT);
    CREATE TABLE gpkg_contents (table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
      description TEXT DEFAULT '', last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
      min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER,
      CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
    CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL, column_name TEXT NOT NULL,
      geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL,
      CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name));
    """)
    wgs84 = ('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
             'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,'
             'AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]')
    c.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)", [
        ("WGS 84 geodetic", 4326, "EPSG", 4326, wgs84, "longitude/latitude WGS 84"),
        ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", None),
        ("Undefined geographic SRS", 0, "NONE", 0, "undefined", None)])
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for name, (gtype, feats) in layers.items():
        cols: list[str] = []
        for _, props in feats:
            for k in props:
                if k not in cols:
                    cols.append(k)
        numeric = {k for k in cols if all(_num(p.get(k)) is not None or p.get(k) in ("", None) for _, p in feats)
                   and any(_num(p.get(k)) is not None for _, p in feats)}
        coldefs = ", ".join(f'"{k}" {"REAL" if k in numeric else "TEXT"}' for k in cols)
        c.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY AUTOINCREMENT, geom {gtype}{", " + coldefs if cols else ""})')
        bbox = [math.inf, math.inf, -math.inf, -math.inf]
        collist = "".join(f', "{k}"' for k in cols)
        ph = ",".join("?" * (len(cols) + 1))
        for geom, props in feats:
            blob, (x0, y0, x1, y1) = _geom_blob(geom)
            bbox = [min(bbox[0], x0), min(bbox[1], y0), max(bbox[2], x1), max(bbox[3], y1)]
            vals = [(_num(props.get(k)) if k in numeric else (None if props.get(k) in (None, "") else str(props.get(k))))
                    for k in cols]
            c.execute(f'INSERT INTO "{name}" (geom{collist}) VALUES ({ph})', [blob] + vals)
        if not feats:
            bbox = [None] * 4
        c.execute("INSERT INTO gpkg_contents VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (name, "features", name, "", now, *bbox, 4326))
        c.execute("INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)", (name, "geom", gtype, 4326, 0, 0))
    con.commit()
    con.close()


def point_features(rows: list[dict]) -> list[tuple[dict, dict]]:
    return [({"type": "Point", "coordinates": [_num(r["longitude"]), _num(r["latitude"])]}, r)
            for r in rows if has_xy(r)]


# ------------------------------------------------------------------ KML / GPX
STYLE = {"site": "ff0000ff", "occurrence": "ff00aaff", "generalised": "ff888888", "natura": "ff00ff00", "literature": "ffff00ff"}


def _placemark(name, desc, lat, lon, style):
    return (f"<Placemark><name>{escape(str(name))}</name><styleUrl>#{style}</styleUrl>"
            f"<description>{escape(str(desc))}</description>"
            f"<Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>")


def write_kml(path: Path, title: str, folders: dict[str, list[tuple[str, str, float, float, str]]]) -> None:
    styles = "".join(f'<Style id="{k}"><IconStyle><color>{v}</color><scale>{1.2 if k == "site" else 0.8}</scale>'
                     f'<Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon>'
                     f'</IconStyle></Style>' for k, v in STYLE.items())
    body = "".join(f"<Folder><name>{escape(fname)}</name>" + "".join(_placemark(*p) for p in pms) + "</Folder>"
                   for fname, pms in folders.items())
    path.write_text('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
                    f"<name>{escape(title)}</name>{styles}{body}</Document></kml>", encoding="utf-8")


def write_gpx(path: Path, waypoints: list[tuple[str, str, float, float]]) -> None:
    wpts = "".join(f'<wpt lat="{lat}" lon="{lon}"><name>{escape(n)}</name><desc>{escape(d)}</desc></wpt>'
                   for n, d, lat, lon in waypoints)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="greek-plant-localities" '
                    f'xmlns="http://www.topografix.com/GPX/1/1">{wpts}</gpx>', encoding="utf-8")
