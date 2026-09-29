"""Rutas, ajustes de settings.json y enlaces rápidos."""
import os
import json
from PyQt6.QtCore import QUrl

# ─── Config ──────────────────────────────────────────────────────────────────
BASE  = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "web_cache")
SCREENSHOTS_DIR = os.path.join(BASE, "memory_screenshots")
DB    = os.path.join(BASE, "browser_data.db")
LINKS_FILE    = os.path.join(BASE, "quick_links.json")
ENGINES_FILE  = os.path.join(BASE, "search_engines.json")
MAX_ENGINES   = 20
SETTINGS_FILE = os.path.join(BASE, "settings.json")
HOME  = f"file://{os.path.join(BASE, 'ui', 'newtab.html')}"
UI_DIR = os.path.join(BASE, "ui")
DICTIONARIES_DIR = "/usr/share/hunspell-bdic"  # diccionarios .bdic del sistema
SPELL_LANG = "es_ES"


def is_internal_url(url) -> bool:
    """True solo para páginas propias de la app (file://…/ui/*)."""
    qurl = url if isinstance(url, QUrl) else QUrl(str(url or ""))
    if not qurl.isLocalFile():
        return False
    path = os.path.realpath(qurl.toLocalFile())
    return path.startswith(os.path.realpath(UI_DIR) + os.sep)
os.makedirs(CACHE, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def load_settings():
    """Carga la configuración persistida (zoom, etc.)."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_settings(data: dict):
    """Guarda la configuración en disco."""
    try:
        existing = load_settings()
        existing.update(data)
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as ex:
        print(f"[Settings] Error al guardar: {ex}")

def load_quick_links():
    """Carga los quick links desde el archivo JSON local."""
    try:
        if os.path.exists(LINKS_FILE):
            with open(LINKS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return None  # None = usar defaults del JS

def save_quick_links(data: str):
    """Guarda los quick links en el archivo JSON local."""
    try:
        links = json.loads(data)
        with open(LINKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(links, f, ensure_ascii=False, indent=2)
    except Exception as ex:
        print(f"[QuickLinks] Error al guardar: {ex}")


def _valid_engines(data) -> list[dict]:
    """Solo {name, url} con URL http(s) que contenga %s (lugar de la búsqueda)."""
    if not isinstance(data, list):
        raise ValueError("se esperaba una lista")
    out = []
    for item in data[:MAX_ENGINES]:
        name = str((item or {}).get("name", "")).strip()[:40]
        url = str((item or {}).get("url", "")).strip()
        if name and "%s" in url and url.lower().startswith(("https://", "http://")):
            out.append({"name": name, "url": url})
    return out


def load_search_engines():
    """Buscadores de la página de inicio; None = usar los predeterminados del JS."""
    try:
        if os.path.exists(ENGINES_FILE):
            with open(ENGINES_FILE, 'r', encoding='utf-8') as f:
                engines = _valid_engines(json.load(f))
                return engines or None
    except Exception:
        pass
    return None


def save_search_engines(data: str):
    """Guarda la lista administrada desde la página de inicio (vacía = predeterminados)."""
    try:
        engines = _valid_engines(json.loads(data))
        if engines:
            with open(ENGINES_FILE, 'w', encoding='utf-8') as f:
                json.dump(engines, f, ensure_ascii=False, indent=2)
        elif os.path.exists(ENGINES_FILE):
            os.remove(ENGINES_FILE)
    except Exception as ex:
        print(f"[Buscadores] Error al guardar: {ex}")
