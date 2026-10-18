"""User configuration and standard paths.

Config lives in ~/.config/greek-plant-localities/config.json (or
$GPL_CONFIG). Private resources (the user's own flora PDFs, Zotero
collections) are listed there and never shipped with the skill.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

VERSION = "0.1.0"

DEFAULTS = {
    "contact_email": "",          # sent in the User-Agent, as GBIF/Nominatim/Crossref ask
    "geonames_username": "",      # free account at geonames.org; enables GeoNames geocoding
    "openalex_api_key": "",       # free key at openalex.org/settings/api; without it OpenAlex shares a tiny per-IP budget
    "local_pdfs": [],             # files or folders with private flora books / reports
    "zotero_collections": [],     # Zotero collection names whose PDFs are searched
    "zotero_data_dir": "~/Zotero",
    "output_root": "~/greek-plant-localities",
}


def config_path() -> Path:
    env = os.environ.get("GPL_CONFIG")
    if env:
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    return base / "greek-plant-localities" / "config.json"


def cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser()
    d = base / "greek-plant-localities"
    d.mkdir(parents=True, exist_ok=True)
    return d


_cfg: dict | None = None


def load() -> dict:
    global _cfg
    if _cfg is None:
        cfg = dict(DEFAULTS)
        p = config_path()
        if p.exists():
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        _cfg = cfg
    return _cfg


def exists() -> bool:
    return config_path().exists()


def save(cfg: dict) -> Path:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULTS)
    merged.update(cfg)
    p.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    global _cfg
    _cfg = merged
    return p


def user_agent() -> str:
    email = load().get("contact_email") or "unknown"
    return (f"greek-plant-localities/{VERSION} "
            f"(+https://github.com/nikostourvas/greek-plant-localities; mailto:{email})")
