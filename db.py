"""Esquema SQLite (migraciones en _db) y helpers de datos del navegador."""
import os
import sqlite3
from urllib.parse import urlparse
from PyQt6.QtCore import QUrl
from config import DB, SCREENSHOTS_DIR

def _db():
    c = sqlite3.connect(DB)
    # Tablas originales
    c.execute("CREATE TABLE IF NOT EXISTS fav(id INTEGER PRIMARY KEY,title TEXT,url TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,title TEXT,url TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS screenshots(id INTEGER PRIMARY KEY, path TEXT, url TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)")
    
    # Tablas de Agenda y Compras
    c.execute("CREATE TABLE IF NOT EXISTS agenda(id INTEGER PRIMARY KEY, text TEXT, dueDate TEXT, done INTEGER DEFAULT 0, tag TEXT DEFAULT '')")
    c.execute("CREATE TABLE IF NOT EXISTS shopping(id INTEGER PRIMARY KEY, text TEXT, value REAL, currency TEXT, dueDate TEXT, paymentMethod TEXT, done INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS income(id INTEGER PRIMARY KEY, text TEXT, value REAL, currency TEXT, dueDate TEXT, received INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS kanban_cols(id INTEGER PRIMARY KEY, title TEXT, pos INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS kanban_cards(id INTEGER PRIMARY KEY, col_id INTEGER, text TEXT, pos INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, content TEXT DEFAULT '', color TEXT DEFAULT 'yellow', x INTEGER DEFAULT 20, y INTEGER DEFAULT 20, width INTEGER DEFAULT 220, height INTEGER DEFAULT 170, z_index INTEGER DEFAULT 1, ts DATETIME DEFAULT CURRENT_TIMESTAMP)")
    
    # Tablas de VideoPlayer
    c.execute("CREATE TABLE IF NOT EXISTS video_tags(url TEXT PRIMARY KEY, data TEXT, scope TEXT DEFAULT '')")
    c.execute("CREATE TABLE IF NOT EXISTS video_playback(url TEXT PRIMARY KEY, time REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS video_playlists(id INTEGER PRIMARY KEY, name TEXT, items TEXT)")
    
    c.execute("CREATE TABLE IF NOT EXISTS app_config(key TEXT PRIMARY KEY, val TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS passwords(id INTEGER PRIMARY KEY, site TEXT, username TEXT, password TEXT, type TEXT DEFAULT 'web', url TEXT DEFAULT '', notes TEXT DEFAULT '', ts DATETIME DEFAULT CURRENT_TIMESTAMP)")

    # Migracion segura para instalaciones existentes
    notes_cols = {row[1] for row in c.execute("PRAGMA table_info(notes)").fetchall()}
    if 'x' not in notes_cols:
        c.execute("ALTER TABLE notes ADD COLUMN x INTEGER DEFAULT 20")
    if 'y' not in notes_cols:
        c.execute("ALTER TABLE notes ADD COLUMN y INTEGER DEFAULT 20")
    if 'width' not in notes_cols:
        c.execute("ALTER TABLE notes ADD COLUMN width INTEGER DEFAULT 220")
    if 'height' not in notes_cols:
        c.execute("ALTER TABLE notes ADD COLUMN height INTEGER DEFAULT 170")
    if 'z_index' not in notes_cols:
        c.execute("ALTER TABLE notes ADD COLUMN z_index INTEGER DEFAULT 1")

    pw_cols = {row[1] for row in c.execute("PRAGMA table_info(passwords)").fetchall()}
    if 'type' not in pw_cols:
        c.execute("ALTER TABLE passwords ADD COLUMN type TEXT DEFAULT 'web'")
    if 'url' not in pw_cols:
        c.execute("ALTER TABLE passwords ADD COLUMN url TEXT DEFAULT ''")

    video_tag_cols = {row[1] for row in c.execute("PRAGMA table_info(video_tags)").fetchall()}
    if 'scope' not in video_tag_cols:
        c.execute("ALTER TABLE video_tags ADD COLUMN scope TEXT DEFAULT ''")
    c.execute("CREATE INDEX IF NOT EXISTS idx_video_tags_scope ON video_tags(scope)")
    if 'notes' not in pw_cols:
        c.execute("ALTER TABLE passwords ADD COLUMN notes TEXT DEFAULT ''")

    # Migración: observaciones en agenda, compras e ingresos
    agenda_cols = {row[1] for row in c.execute("PRAGMA table_info(agenda)").fetchall()}
    if 'notes' not in agenda_cols:
        c.execute("ALTER TABLE agenda ADD COLUMN notes TEXT DEFAULT ''")
    if 'tag' not in agenda_cols:
        c.execute("ALTER TABLE agenda ADD COLUMN tag TEXT DEFAULT ''")
    shopping_cols = {row[1] for row in c.execute("PRAGMA table_info(shopping)").fetchall()}
    if 'notes' not in shopping_cols:
        c.execute("ALTER TABLE shopping ADD COLUMN notes TEXT DEFAULT ''")
    income_cols = {row[1] for row in c.execute("PRAGMA table_info(income)").fetchall()}
    if 'notes' not in income_cols:
        c.execute("ALTER TABLE income ADD COLUMN notes TEXT DEFAULT ''")
    
    # Inicializar config por defecto si está vacía
    if not c.execute("SELECT key FROM app_config LIMIT 1").fetchone():
        defaults = [('exchangeRate', '7.80'), ('paymentMethods', '["Efectivo","Tarjeta","Transferencia"]')]
        c.executemany("INSERT INTO app_config VALUES(?,?)", defaults)

    # Claves compartidas entre Agenda, VideoPlayer, ImagePlayer y New Tab
    default_media_path = os.path.expanduser("~/Videos")
    if not os.path.isdir(default_media_path):
        default_media_path = os.path.expanduser("~")

    shared_defaults = [
        ('videoEnabled', '1'),
        ('imagesEnabled', '1'),
        ('shoppingEnabled', '1'),
        ('incomeEnabled', '1'),
        ('kanbanEnabled', '1'),
        ('notesEnabled', '1'),
        ('arcadeEnabled', '1'),
        ('homeUrl', 'https://www.google.com'),
        ('mediaPath', default_media_path),
        ('videoStartMuted', '0'),
        ('videoSortBy', 'name-asc'),
        ('passwordAutoSavePolicy', 'ask'),
        # Menú "Más opciones": desactivados para conservar el comportamiento previo
        ('restoreSession', '0'),
        ('spellCheckEnabled', '0')
    ]
    c.executemany("INSERT OR IGNORE INTO app_config(key,val) VALUES(?,?)", shared_defaults)

    # Limpieza única de duplicados históricos en contraseñas (mismo sitio+usuario normalizados).
    dedupe_flag = c.execute("SELECT val FROM app_config WHERE key='passwordsDedupV1'").fetchone()
    if not dedupe_flag or dedupe_flag[0] != '1':
        dup_rows = c.execute(
            "SELECT lower(trim(site)) AS s_key, lower(trim(username)) AS u_key, MAX(id) AS keep_id "
            "FROM passwords "
            "WHERE trim(site)<>'' AND trim(username)<>'' "
            "GROUP BY s_key, u_key HAVING COUNT(*) > 1"
        ).fetchall()
        for s_key, u_key, keep_id in dup_rows:
            c.execute(
                "DELETE FROM passwords "
                "WHERE lower(trim(site))=? AND lower(trim(username))=? AND id<>?",
                (s_key, u_key, keep_id)
            )
        c.execute("INSERT OR REPLACE INTO app_config(key,val) VALUES(?,?)", ('passwordsDedupV1', '1'))

    # Asegurar claves de configuracion para visor de imagenes
    default_image_path = os.path.expanduser("~/Pictures")
    if not os.path.isdir(default_image_path):
        default_image_path = os.path.expanduser("~")
    c.execute("INSERT OR IGNORE INTO app_config(key,val) VALUES(?,?)", ('imageMediaPath', default_image_path))
    c.execute("INSERT OR IGNORE INTO app_config(key,val) VALUES(?,?)", ('imageSortBy', 'name-asc'))
    c.execute("INSERT OR IGNORE INTO app_config(key,val) VALUES(?,?)", ('imageLastFolder', '.'))
    c.execute("INSERT OR IGNORE INTO app_config(key,val) VALUES(?,?)", ('screenshotsPath', SCREENSHOTS_DIR))
        
    c.commit(); return c

def get_config(key: str, default: str = "") -> str:
    c = _db(); r = c.execute("SELECT val FROM app_config WHERE key=?", (key,)).fetchone(); c.close()
    return r[0] if r else default

def set_config(key: str, val: str):
    c = _db(); c.execute("INSERT OR REPLACE INTO app_config(key,val) VALUES(?,?)", (key, val)); c.commit(); c.close()

def get_screenshots_dir():
    c = _db()
    r = c.execute("SELECT val FROM app_config WHERE key='screenshotsPath'").fetchone()
    c.close()
    path = (r[0] if r and r[0] else SCREENSHOTS_DIR).strip()
    if not path:
        path = SCREENSHOTS_DIR
    os.makedirs(path, exist_ok=True)
    return path

def cleanup_original_screenshot(original_path, screenshots_dir=None):
    if not original_path:
        return
    try:
        src = original_path.strip()
        if src.startswith("file://"):
            src = QUrl(src).toLocalFile()
        base_dir = os.path.realpath(screenshots_dir or get_screenshots_dir())
        src_real = os.path.realpath(src)
        if src_real.startswith(base_dir) and os.path.isfile(src_real) and os.path.basename(src_real).startswith("shot_"):
            os.remove(src_real)
    except Exception as rm_ex:
        print(f"[Screenshot] No se pudo borrar original: {rm_ex}")

def save_fav(title, url):
    c = _db()
    if not c.execute("SELECT id FROM fav WHERE url=?", (url,)).fetchone():
        c.execute("INSERT INTO fav(title,url) VALUES(?,?)", (title, url))
        c.commit()
    c.close()

def get_favs():
    c = _db(); res = c.execute("SELECT id, title, url FROM fav ORDER BY id DESC").fetchall(); c.close(); return res

def del_fav(fid):
    c = _db(); c.execute("DELETE FROM fav WHERE id=?",(fid,)); c.commit(); c.close()

def save_history(title, url):
    if not url or url.startswith("data:") or url == "about:blank" or url.startswith("minichrome:"): return
    c = _db(); c.execute("INSERT INTO history(title,url) VALUES(?,?)",(title,url)); c.commit(); c.close()

def save_screenshot(path, url):
    c = _db()
    c.execute("INSERT INTO screenshots(path, url) VALUES(?,?)", (path, url))
    c.commit()
    c.close()

def get_history():
    c = _db()
    res = c.execute("""
        SELECT h.id, h.title, h.url, g.visits 
        FROM history h 
        JOIN (SELECT url, MAX(id) as max_id, COUNT(*) as visits FROM history GROUP BY url) g 
        ON h.id = g.max_id 
        ORDER BY h.id DESC 
        LIMIT 100
    """).fetchall()
    c.close()
    return res

def get_url_history(url):
    c = _db()
    res = c.execute("SELECT id, title, ts FROM history WHERE url=? ORDER BY id DESC", (url,)).fetchall()
    c.close()
    return res

def del_history(hid):
    c = _db(); c.execute("DELETE FROM history WHERE id=?",(hid,)); c.commit(); c.close()

def clear_history():
    c = _db(); c.execute("DELETE FROM history"); c.commit(); c.close()

def _normalize_domain(value: str) -> str:
    raw = (value or '').strip().lower()
    if not raw:
        return ''
    if '://' not in raw:
        raw = 'https://' + raw
    try:
        host = (urlparse(raw).hostname or '').lower()
    except Exception:
        host = ''
    if host.startswith('www.'):
        host = host[4:]
    return host

def clear_history_by_domain(domain: str) -> int:
    target = _normalize_domain(domain)
    if not target:
        return 0

    c = _db()
    rows = c.execute("SELECT id, url FROM history").fetchall()
    ids = []
    for hid, url in rows:
        host = _normalize_domain(url)
        if not host:
            continue
        if host == target or host.endswith('.' + target):
            ids.append((hid,))

    if ids:
        c.executemany("DELETE FROM history WHERE id=?", ids)
        c.commit()
    c.close()
    return len(ids)

def clear_history_by_dates(start_date: str, end_date: str) -> int:
    start = (start_date or '').strip()
    end = (end_date or '').strip()
    if not start:
        return 0
    if not end:
        end = start

    c = _db()
    c.execute(
        "DELETE FROM history WHERE date(ts) BETWEEN date(?) AND date(?)",
        (start, end)
    )
    removed = c.total_changes
    c.commit()
    c.close()
    return int(removed)

_db().close()
