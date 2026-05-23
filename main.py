import os
import sys
import json
import base64
import sqlite3
import time
import shutil
import subprocess
from datetime import datetime
from urllib.parse import urlparse
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QSizePolicy, QFrame,
    QGraphicsDropShadowEffect, QScrollArea, QListWidget, QListWidgetItem,
    QDialog, QStackedLayout, QDateEdit
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (QWebEngineProfile, QWebEnginePage, QWebEngineScript, QWebEngineSettings, QWebEngineUrlRequestInterceptor)
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import (QUrl, QUrlQuery, Qt, QSize, QTimer, QPropertyAnimation,
                           QEasingCurve, QPoint, QRect, QObject, pyqtSlot, pyqtSignal, QDate)
from PyQt6.QtGui import QColor, QCursor, QFont, QIcon, QPixmap, QDesktopServices, QImage

# ─── Config ──────────────────────────────────────────────────────────────────
BASE  = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "web_cache")
SCREENSHOTS_DIR = os.path.join(BASE, "memory_screenshots")
DB    = os.path.join(BASE, "browser_data.db")
LINKS_FILE    = os.path.join(BASE, "quick_links.json")
SETTINGS_FILE = os.path.join(BASE, "settings.json")
HOME  = f"file://{os.path.join(BASE, 'ui', 'newtab.html')}"
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

def _db():
    c = sqlite3.connect(DB)
    # Tablas originales
    c.execute("CREATE TABLE IF NOT EXISTS fav(id INTEGER PRIMARY KEY,title TEXT,url TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,title TEXT,url TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS screenshots(id INTEGER PRIMARY KEY, path TEXT, url TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)")
    
    # Tablas de Agenda y Compras
    c.execute("CREATE TABLE IF NOT EXISTS agenda(id INTEGER PRIMARY KEY, text TEXT, dueDate TEXT, done INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS shopping(id INTEGER PRIMARY KEY, text TEXT, value REAL, currency TEXT, dueDate TEXT, paymentMethod TEXT, done INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS income(id INTEGER PRIMARY KEY, text TEXT, value REAL, currency TEXT, dueDate TEXT, received INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS kanban_cols(id INTEGER PRIMARY KEY, title TEXT, pos INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS kanban_cards(id INTEGER PRIMARY KEY, col_id INTEGER, text TEXT, pos INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, content TEXT DEFAULT '', color TEXT DEFAULT 'yellow', x INTEGER DEFAULT 20, y INTEGER DEFAULT 20, z_index INTEGER DEFAULT 1, ts DATETIME DEFAULT CURRENT_TIMESTAMP)")
    
    # Tablas de VideoPlayer
    c.execute("CREATE TABLE IF NOT EXISTS video_tags(url TEXT PRIMARY KEY, data TEXT)")
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
    if 'z_index' not in notes_cols:
        c.execute("ALTER TABLE notes ADD COLUMN z_index INTEGER DEFAULT 1")

    pw_cols = {row[1] for row in c.execute("PRAGMA table_info(passwords)").fetchall()}
    if 'type' not in pw_cols:
        c.execute("ALTER TABLE passwords ADD COLUMN type TEXT DEFAULT 'web'")
    if 'url' not in pw_cols:
        c.execute("ALTER TABLE passwords ADD COLUMN url TEXT DEFAULT ''")
    if 'notes' not in pw_cols:
        c.execute("ALTER TABLE passwords ADD COLUMN notes TEXT DEFAULT ''")
    
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
        ('passwordAutoSavePolicy', 'ask')
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

_db().close()

# ─── Perfil persistente ───────────────────────────────────────────────────────
_prof = None
_ua_interceptor = None


class DomainUAInterceptor(QWebEngineUrlRequestInterceptor):
    """Fuerza cabeceras adicionales para evadir detecciones y bloqueos de Google."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ff_ua = b"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"

    def interceptRequest(self, info):
        url = info.requestUrl()
        if url.scheme().lower() not in ("http", "https"):
            return
            
        info.setHttpHeader(b"Accept-Language", b"es-ES,es;q=0.9,en;q=0.8")
        
        host = (url.host() or "").lower()
        if "accounts.google.com" in host or "mail.google.com" in host:
            info.setHttpHeader(b"User-Agent", self._ff_ua)
        else:
            # Perplexity (Cloudflare) valida estrictamente los Client Hints si decimos ser Chrome
            info.setHttpHeader(b"Sec-Ch-Ua", b'"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"')
            info.setHttpHeader(b"Sec-Ch-Ua-Mobile", b"?0")
            info.setHttpHeader(b"Sec-Ch-Ua-Platform", b'"Windows"')


def profile():
    global _prof, _ua_interceptor
    if not _prof:
        _prof = QWebEngineProfile("MinichromeProfile")
        # Usamos un UA de Windows moderno (Chrome 124) que suele tener menos restricciones
        _prof.setHttpUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        _prof.setPersistentStoragePath(CACHE)
        _prof.setCachePath(os.path.join(CACHE, "httpcache"))
        _prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        _prof.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)

        _ua_interceptor = DomainUAInterceptor(_prof)
        _prof.setUrlRequestInterceptor(_ua_interceptor)

        # CSS Global (scrollbars personalizados delgados y sutiles)
        s = QWebEngineScript()
        s.setSourceCode("""
            (function(){
                var st = document.createElement('style');
                st.id = 'minichrome-scrollbar-style';
                st.innerHTML = `
                    ::-webkit-scrollbar { width: 8px !important; height: 8px !important; }
                    ::-webkit-scrollbar-track { background: transparent !important; }
                    ::-webkit-scrollbar-thumb { background: rgba(128, 128, 128, 0.2) !important; border-radius: 10px !important; }
                    ::-webkit-scrollbar-thumb:hover { background: rgba(128, 128, 128, 0.5) !important; }
                `;
                if (document.head) {
                    document.head.appendChild(st);
                } else {
                    document.documentElement.appendChild(st);
                }
            })();
        """)
        s.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        s.setRunsOnSubFrames(True)
        s.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
        _prof.scripts().insert(s)

        # ── Script de Captura de Contraseñas ──────────────────────────────────
        pwd_capture = QWebEngineScript()
        pwd_capture.setName("pwd_capture")
        pwd_capture.setSourceCode("""
(function(){
    const pageHost = (location.hostname || '').toLowerCase();
    const skipPwdHelperDomains = [
        'copilot.microsoft.com',
        'perplexity.ai',
        'chatgpt.com',
        'openai.com',
        'claude.ai',
        'bing.com',
        'google.com',
        'microsoft.com',
        'challenges.cloudflare.com',
        'hcaptcha.com',
        'recaptcha.net'
    ];
    if (skipPwdHelperDomains.some((d) => pageHost === d || pageHost.endsWith('.' + d))) {
        return;
    }

    let lastUserSeen = '';
    let lastCaptureKey = '';
    let lastAutofillHost = '';
    let lastAutofillRequestTs = 0;
    let lastRememberApplyTs = 0;
    let rememberScanCacheTs = 0;
    let rememberScanCache = [];
    let observerDebounceTimer = null;
    const rememberSessionStorageKey = '__mc_remember_session_pref_v1';

    function normalizeText(value) {
        return String(value || '')
            .toLowerCase()
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .trim();
    }

    function getRememberPref() {
        try {
            return localStorage.getItem(rememberSessionStorageKey);
        } catch (_err) {
            return null;
        }
    }

    function setRememberPref(enabled) {
        try {
            localStorage.setItem(rememberSessionStorageKey, enabled ? '1' : '0');
        } catch (_err) {
            // Ignorar errores de storage en sitios restringidos.
        }
    }

    function isVisible(el) {
        if (!el) return false;
        const st = window.getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden') return false;
        if (el.disabled || el.readOnly) return false;
        return true;
    }

    function findPasswordField() {
        const fields = Array.from(document.querySelectorAll('input[type="password"]'));
        return fields.find(isVisible) || null;
    }

    function getCheckboxContextText(checkbox) {
        let text = [
            checkbox.getAttribute('aria-label') || '',
            checkbox.name || '',
            checkbox.id || '',
            checkbox.className || ''
        ].join(' ');

        const parentLabel = checkbox.closest('label');
        if (parentLabel) {
            text += ' ' + (parentLabel.innerText || parentLabel.textContent || '');
        }

        if (checkbox.id) {
            try {
                const explicitLabel = document.querySelector(`label[for="${checkbox.id}"]`);
                if (explicitLabel) {
                    text += ' ' + (explicitLabel.innerText || explicitLabel.textContent || '');
                }
            } catch (_err) {
                // Selector invalido por IDs especiales.
            }
        }

        return normalizeText(text);
    }

    function isRememberSessionCheckbox(checkbox) {
        if (!checkbox || checkbox.tagName !== 'INPUT') return false;
        if ((checkbox.type || '').toLowerCase() !== 'checkbox') return false;
        const txt = getCheckboxContextText(checkbox);
        return /(mantener|recordar|remember|stay signed|keep signed|sesion|session|confi|trust|logged in|log in)/.test(txt);
    }

    function findRememberSessionCheckboxes(forceRefresh) {
        const now = Date.now();
        if (!forceRefresh && (now - rememberScanCacheTs) < 1200) {
            return rememberScanCache;
        }

        // Solo tiene sentido en vistas de login.
        if (!findPasswordField()) {
            rememberScanCache = [];
            rememberScanCacheTs = now;
            return rememberScanCache;
        }

        rememberScanCache = Array.from(document.querySelectorAll('input[type="checkbox"]')).filter((cb) => {
            return isVisible(cb) && isRememberSessionCheckbox(cb);
        });
        rememberScanCacheTs = now;
        return rememberScanCache;
    }

    function applyRememberSessionPreference() {
        if (getRememberPref() !== '1') return;
        const now = Date.now();
        if ((now - lastRememberApplyTs) < 1200) return;
        lastRememberApplyTs = now;

        const matches = findRememberSessionCheckboxes(false);
        matches.forEach((cb) => {
            if (cb.checked) return;
            cb.checked = true;
            cb.dispatchEvent(new Event('input', { bubbles: true }));
            cb.dispatchEvent(new Event('change', { bubbles: true }));
        });
    }

    function captureRememberSessionPreference() {
        const matches = findRememberSessionCheckboxes(true);
        if (!matches.length) return;
        const anyChecked = matches.some((cb) => cb.checked);
        setRememberPref(anyChecked);
    }

    function findUserField(passField) {
        const selectors = [
            'input[type="email"]',
            'input[type="text"]',
            'input[name*="user" i]',
            'input[name*="login" i]',
            'input[name*="mail" i]',
            'input[name*="identifier" i]',
            'input[id*="user" i]',
            'input[id*="login" i]',
            'input[id*="mail" i]'
        ].join(',');

        const form = passField ? (passField.form || passField.closest('form')) : null;
        if (form) {
            const candidates = Array.from(form.querySelectorAll(selectors));
            const inForm = candidates.find(isVisible);
            if (inForm) return inForm;
        }

        const globalCandidates = Array.from(document.querySelectorAll(selectors));
        return globalCandidates.find(isVisible) || null;
    }

    function findInlineUserText() {
        const selectors = [
            '[data-identifier]',
            '[id*="profileidentifier" i]',
            '[id*="account" i] span',
            '[aria-label*="@"]',
            'div[role="button"] span',
            'div[role="link"] span'
        ];
        for (const sel of selectors) {
            const nodes = document.querySelectorAll(sel);
            for (const node of nodes) {
                const text = (node.innerText || node.textContent || '').trim();
                if (text && (text.includes('@') || text.length > 3)) {
                    return text;
                }
            }
        }
        return '';
    }

    function trackUserFromEvent(target) {
        if (!target || target.tagName !== 'INPUT') return;
        const type = (target.type || '').toLowerCase();
        const name = (target.name || '').toLowerCase();
        const id = (target.id || '').toLowerCase();
        if (['email', 'text'].includes(type) || /user|mail|login|identifier/.test(name + ' ' + id)) {
            const val = (target.value || '').trim();
            if (val) lastUserSeen = val;
        }
    }

    function getCredentialSnapshot() {
        const passField = findPasswordField();
        if (!passField) return null;

        const pass = (passField.value || '').trim();
        if (!pass || pass.length < 4) return null;

        const userField = findUserField(passField);
        const user = ((userField && userField.value) || lastUserSeen || findInlineUserText() || '').trim();
        if (!user) return null;

        return {
            site: window.location.hostname,
            user: user,
            pwd: pass,
            url: window.location.href,
            type: 'web'
        };
    }

    function emitPasswordCapture() {
        const data = getCredentialSnapshot();
        if (!data) return;
        const key = [data.site, data.user, data.pwd].join('|');
        if (key === lastCaptureKey) return;
        lastCaptureKey = key;
        console.log('MINICHROME_PWD:' + JSON.stringify(data));
    }

    function maybeRequestAutofill() {
        const passField = findPasswordField();
        if (!passField) return;
        const host = window.location.hostname || '';
        if (!host) return;

        const now = Date.now();
        // Reintentos suaves para formularios que montan/rehidratan campos tarde.
        if (host === lastAutofillHost && (now - lastAutofillRequestTs) < 1600) return;
        lastAutofillHost = host;
        lastAutofillRequestTs = now;

        console.log('MINICHROME_AUTOFILL_REQUEST:' + JSON.stringify({
            host: host,
            url: window.location.href
        }));
    }

    document.addEventListener('input', (e) => {
        trackUserFromEvent(e.target);
    }, true);

    document.addEventListener('change', (e) => {
        const target = e.target;
        if (target && isRememberSessionCheckbox(target)) {
            rememberScanCacheTs = 0;
            setRememberPref(!!target.checked);
        }
    }, true);

    window.addEventListener('submit', () => {
        captureRememberSessionPreference();
        setTimeout(emitPasswordCapture, 120);
    }, true);

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        const t = e.target;
        if (t && t.tagName === 'INPUT' && (t.type || '').toLowerCase() === 'password') {
            setTimeout(emitPasswordCapture, 120);
        }
    }, true);

    document.addEventListener('click', (e) => {
        const btn = e.target && e.target.closest('button, input[type="submit"], input[type="button"]');
        if (!btn) return;
        const text = ((btn.innerText || btn.value || '') + ' ' + (btn.getAttribute('aria-label') || '')).toLowerCase();
        if (/siguiente|continuar|entrar|ingresar|acceder|login|log in|sign in|next/.test(text)) {
            captureRememberSessionPreference();
            setTimeout(emitPasswordCapture, 180);
        }
    }, true);

    let bootChecks = 0;
    const bootTimer = setInterval(() => {
        applyRememberSessionPreference();
        maybeRequestAutofill();
        bootChecks += 1;
        if (bootChecks >= 6) clearInterval(bootTimer);
    }, 600);

    const observer = new MutationObserver(() => {
        if (observerDebounceTimer) return;
        observerDebounceTimer = setTimeout(() => {
            observerDebounceTimer = null;
            applyRememberSessionPreference();
            maybeRequestAutofill();
        }, 220);
    });

    const startObserver = () => {
        if (!document.body) return;
        observer.observe(document.body, { childList: true, subtree: true });
        applyRememberSessionPreference();
        maybeRequestAutofill();
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startObserver, { once: true });
    } else {
        startObserver();
    }
})();
        """)
        pwd_capture.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        pwd_capture.setRunsOnSubFrames(False)
        pwd_capture.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        _prof.scripts().insert(pwd_capture)

        # ── Stealth mínimo para evadir antibots (Cloudflare, Google, etc) ────────
        stealth = QWebEngineScript()
        stealth.setName("stealth")
        stealth.setSourceCode("""
(function(){
    try {
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es', 'en'], configurable: true });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5], configurable: true });
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8, configurable: true });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8, configurable: true });
        
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = parameters => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
    } catch (_e) {}
})();
        """)
        stealth.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        stealth.setRunsOnSubFrames(False)
        stealth.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        _prof.scripts().insert(stealth)

    return _prof

# ─── Puente Agenda (Python <=> JS) ───────────────────────────────────────────
class AgendaBridge(QObject):
    updated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

    @pyqtSlot(result=list)
    def get_agenda(self):
        c = _db(); res = c.execute("SELECT id, text, dueDate, done FROM agenda ORDER BY id DESC").fetchall(); c.close()
        return [{"id":r[0],"text":r[1],"dueDate":r[2],"done":bool(r[3])} for r in res]

    @pyqtSlot(str, str)
    def add_agenda(self, text, date):
        c = _db(); c.execute("INSERT INTO agenda(text, dueDate) VALUES(?,?)", (text, date)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, str, str)
    def update_agenda(self, aid, text, date):
        c = _db(); c.execute("UPDATE agenda SET text=?, dueDate=? WHERE id=?", (text, date, aid)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int)
    def delete_agenda(self, aid):
        c = _db(); c.execute("DELETE FROM agenda WHERE id=?", (aid,)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, bool)
    def toggle_agenda(self, aid, done):
        c = _db(); c.execute("UPDATE agenda SET done=? WHERE id=?", (int(done), aid)); c.commit(); c.close()
        self.updated.emit()


    @pyqtSlot(result=list)
    def get_shopping(self):
        c = _db(); res = c.execute("SELECT id, text, value, currency, dueDate, paymentMethod, done FROM shopping ORDER BY id DESC").fetchall(); c.close()
        return [{"id":r[0],"text":r[1],"value":r[2],"currency":r[3],"dueDate":r[4],"paymentMethod":r[5],"done":bool(r[6])} for r in res]

    @pyqtSlot(str, float, str, str, str)
    def add_shopping(self, text, val, cur, date, pm):
        c = _db(); c.execute("INSERT INTO shopping(text, value, currency, dueDate, paymentMethod) VALUES(?,?,?,?,?)", (text, val, cur, date, pm)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, str, float, str, str, str)
    def update_shopping(self, sid, text, val, cur, date, pm):
        c = _db(); c.execute("UPDATE shopping SET text=?, value=?, currency=?, dueDate=?, paymentMethod=? WHERE id=?", (text, val, cur, date, pm, sid)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int)
    def delete_shopping(self, sid):
        c = _db(); c.execute("DELETE FROM shopping WHERE id=?", (sid,)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, bool)
    def toggle_shopping(self, sid, done):
        c = _db(); c.execute("UPDATE shopping SET done=? WHERE id=?", (int(done), sid)); c.commit(); c.close()
        self.updated.emit()


    @pyqtSlot(result=list)
    def get_income(self):
        c = _db(); res = c.execute("SELECT id, text, value, currency, dueDate, received FROM income ORDER BY id DESC").fetchall(); c.close()
        return [{"id":r[0],"text":r[1],"value":r[2],"currency":r[3],"dueDate":r[4],"received":bool(r[5])} for r in res]

    @pyqtSlot(str, float, str, str)
    def add_income(self, text, val, cur, date):
        c = _db(); c.execute("INSERT INTO income(text, value, currency, dueDate) VALUES(?,?,?,?)", (text, val, cur, date)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, bool)
    def toggle_income(self, iid, received):
        c = _db(); c.execute("UPDATE income SET received=? WHERE id=?", (int(received), iid)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, str, float, str, str)
    def update_income(self, iid, text, val, cur, date):
        c = _db(); c.execute("UPDATE income SET text=?, value=?, currency=?, dueDate=? WHERE id=?", (text, val, cur, date, iid)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int)
    def delete_income(self, iid):
        c = _db(); c.execute("DELETE FROM income WHERE id=?", (iid,)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int)
    def delete_kanban_card(self, cid):
        c = _db(); c.execute("DELETE FROM kanban_cards WHERE id=?", (cid,)); c.commit(); c.close()
        self.updated.emit()


    @pyqtSlot(str, result=str)
    def get_config(self, key):
        c = _db(); r = c.execute("SELECT val FROM app_config WHERE key=?", (key,)).fetchone(); c.close()
        return r[0] if r else ""

    @pyqtSlot(str, str)
    def set_config(self, key, val):
        c = _db(); c.execute("INSERT OR REPLACE INTO app_config(key,val) VALUES(?,?)", (key, val)); c.commit(); c.close()
        self.updated.emit()

    # ─── API de Videos (Sistema de archivos y yt-dlp) ─────────────────────────
    @pyqtSlot(result=str)
    def get_media_path(self):
        c = _db(); r = c.execute("SELECT val FROM app_config WHERE key='mediaPath'").fetchone(); c.close()
        path = r[0] if r else os.path.expanduser("~/Videos")
        return path if os.path.exists(path) else os.path.expanduser("~")

    def _normalize_rel(self, rel_path):
        if not rel_path or rel_path in (".", "/"):
            return ""
        return os.path.normpath(rel_path).replace("\\", "/")

    def _safe_media_path(self, rel_path):
        base = os.path.abspath(self.get_media_path())
        rel_norm = self._normalize_rel(rel_path)
        target = os.path.abspath(os.path.join(base, rel_norm))
        if os.path.commonpath([target, base]) != base:
            raise ValueError("Ruta fuera de la biblioteca")
        return target

    def _rel_to_media_url(self, rel_path):
        abs_path = self._safe_media_path(rel_path)
        return QUrl.fromLocalFile(abs_path).toString()

    def _legacy_media_url(self, rel_path):
        rel_norm = self._normalize_rel(rel_path)
        return f"/media/{rel_norm}" if rel_norm else "/media"

    def _migrate_video_metadata(self, old_rel, new_rel):
        old_url = self._rel_to_media_url(old_rel)
        new_url = self._rel_to_media_url(new_rel)
        old_legacy = self._legacy_media_url(old_rel)

        c = _db()
        playback_rows = c.execute(
            "SELECT url, time FROM video_playback WHERE url IN (?, ?)",
            (old_url, old_legacy)
        ).fetchall()
        for _old, t in playback_rows:
            c.execute(
                "INSERT OR REPLACE INTO video_playback(url, time) VALUES(?, ?)",
                (new_url, t)
            )
        c.execute("DELETE FROM video_playback WHERE url IN (?, ?)", (old_url, old_legacy))

        tag_rows = c.execute(
            "SELECT url, data FROM video_tags WHERE url IN (?, ?)",
            (old_url, old_legacy)
        ).fetchall()
        for _old, data in tag_rows:
            c.execute(
                "INSERT OR REPLACE INTO video_tags(url, data) VALUES(?, ?)",
                (new_url, data)
            )
        c.execute("DELETE FROM video_tags WHERE url IN (?, ?)", (old_url, old_legacy))

        c.commit()
        c.close()

    def _migrate_folder_metadata(self, old_rel_folder, new_rel_folder):
        old_rel = self._normalize_rel(old_rel_folder)
        new_rel = self._normalize_rel(new_rel_folder)
        if not old_rel or not new_rel:
            return

        old_file_prefix = self._rel_to_media_url(old_rel)
        new_file_prefix = self._rel_to_media_url(new_rel)
        if not old_file_prefix.endswith("/"):
            old_file_prefix += "/"
        if not new_file_prefix.endswith("/"):
            new_file_prefix += "/"

        old_legacy_prefix = self._legacy_media_url(old_rel)
        new_legacy_prefix = self._legacy_media_url(new_rel)
        if not old_legacy_prefix.endswith("/"):
            old_legacy_prefix += "/"
        if not new_legacy_prefix.endswith("/"):
            new_legacy_prefix += "/"

        c = _db()
        for table in ("video_playback", "video_tags"):
            rows = c.execute(f"SELECT url FROM {table}").fetchall()
            for (url_val,) in rows:
                new_url = url_val
                if url_val.startswith(old_file_prefix):
                    new_url = new_file_prefix + url_val[len(old_file_prefix):]
                elif url_val.startswith(old_legacy_prefix):
                    new_url = new_legacy_prefix + url_val[len(old_legacy_prefix):]

                if new_url != url_val:
                    c.execute(f"UPDATE {table} SET url=? WHERE url=?", (new_url, url_val))

        c.commit()
        c.close()

    def _purge_folder_metadata(self, rel_folder):
        rel_norm = self._normalize_rel(rel_folder)
        if not rel_norm:
            return

        file_prefix = self._rel_to_media_url(rel_norm)
        legacy_prefix = self._legacy_media_url(rel_norm)
        if not file_prefix.endswith("/"):
            file_prefix += "/"
        if not legacy_prefix.endswith("/"):
            legacy_prefix += "/"

        c = _db()
        c.execute("DELETE FROM video_playback WHERE url LIKE ? OR url LIKE ?", (f"{file_prefix}%", f"{legacy_prefix}%"))
        c.execute("DELETE FROM video_tags WHERE url LIKE ? OR url LIKE ?", (f"{file_prefix}%", f"{legacy_prefix}%"))
        c.commit()
        c.close()

    @pyqtSlot(result=str)
    def get_video_folders(self):
        import json
        base = os.path.abspath(self.get_media_path())

        video_exts = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4v', '.wmv', '.flv', '.ogv', '.m3u8', '.ts')
        
        def _build_tree(dir_path):
            nodes = []
            try:
                for entry in os.scandir(dir_path):
                    if entry.is_dir() and not entry.name.startswith('.'):
                        nodes.append({
                            "name": entry.name,
                            "path": os.path.relpath(entry.path, base),
                            "children": _build_tree(entry.path)
                        })
            except Exception:
                pass
            return sorted(nodes, key=lambda x: x['name'].lower())
            
        tree = _build_tree(base)
        
        # Verificar si hay videos en la raíz
        try:
            root_videos = [e.name for e in os.scandir(base) if e.is_file() and e.name.lower().endswith(video_exts)]
            if root_videos:
                tree.insert(0, {"name": "[Raíz de Biblioteca]", "path": ".", "children": []})
        except: pass
        
        return json.dumps(tree)

    @pyqtSlot(str, result=str)
    def get_videos(self, rel_path):
        import json
        rel_clean = self._normalize_rel(rel_path)
        target = self._safe_media_path(rel_clean)
        videos = []
        exts = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4v', '.wmv', '.flv', '.ogv', '.m3u8', '.ts')
        try:
            for entry in os.scandir(target):
                if entry.is_file() and entry.name.lower().endswith(exts):
                    rel_file = entry.name if not rel_clean else f"{rel_clean}/{entry.name}"
                    st = entry.stat()
                    video_data = {
                        "name": entry.name,
                        "url": self._rel_to_media_url(rel_file),
                        "size": st.st_size,
                        "mtime": st.st_mtime
                    }

                    base_name = os.path.splitext(entry.name)[0]
                    for sub_ext in ('.vtt', '.srt'):
                        sub_file = os.path.join(target, base_name + sub_ext)
                        if os.path.exists(sub_file):
                            rel_sub = (base_name + sub_ext) if not rel_clean else f"{rel_clean}/{base_name + sub_ext}"
                            video_data["subtitle"] = self._rel_to_media_url(rel_sub)
                            break

                    videos.append(video_data)
        except Exception:
            pass
        return json.dumps(sorted(videos, key=lambda x: x['name'].lower()))

    @pyqtSlot(str, str, result=bool)
    def rename_video(self, old_path, new_name):
        try:
            if not new_name:
                return False

            safe_name = os.path.basename(new_name.strip())
            if not safe_name:
                return False

            op = self._safe_media_path(old_path)
            np = os.path.join(os.path.dirname(op), safe_name)

            base = os.path.abspath(self.get_media_path())
            np_abs = os.path.abspath(np)
            if os.path.commonpath([np_abs, base]) != base:
                return False

            old_rel = os.path.relpath(op, base).replace("\\", "/")
            new_rel = os.path.relpath(np_abs, base).replace("\\", "/")

            os.rename(op, np_abs)

            # También renombrar subtítulos
            old_base = os.path.splitext(op)[0]
            new_base = os.path.splitext(np_abs)[0]
            for ext in ['.srt', '.vtt']:
                if os.path.exists(old_base + ext):
                    os.rename(old_base + ext, new_base + ext)

            self._migrate_video_metadata(old_rel, new_rel)
            return True
        except: return False

    @pyqtSlot(str, result=bool)
    def delete_video(self, rel_path):
        try:
            abs_video = self._safe_media_path(rel_path)
            if not os.path.isfile(abs_video):
                return False

            os.remove(abs_video)

            # Eliminar subtítulos asociados si existen
            base_no_ext = os.path.splitext(abs_video)[0]
            for ext in ('.srt', '.vtt'):
                sub_path = base_no_ext + ext
                if os.path.exists(sub_path):
                    os.remove(sub_path)

            rel_norm = self._normalize_rel(rel_path)
            file_url = self._rel_to_media_url(rel_norm)
            legacy_url = self._legacy_media_url(rel_norm)
            c = _db()
            c.execute("DELETE FROM video_playback WHERE url IN (?, ?)", (file_url, legacy_url))
            c.execute("DELETE FROM video_tags WHERE url IN (?, ?)", (file_url, legacy_url))
            c.commit()
            c.close()
            return True
        except: return False

    @pyqtSlot(str, str, str, result=bool)
    def move_video(self, filename, from_folder, to_folder):
        try:
            base = os.path.abspath(self.get_media_path())
            from_rel = self._normalize_rel(from_folder)
            to_rel = self._normalize_rel(to_folder)

            old_rel = filename if not from_rel else f"{from_rel}/{filename}"
            new_rel = filename if not to_rel else f"{to_rel}/{filename}"

            op = self._safe_media_path(old_rel)
            np = self._safe_media_path(new_rel)

            os.makedirs(os.path.dirname(np), exist_ok=True)
            shutil.move(op, np)

            # Mover subtítulos junto al video
            old_base = os.path.splitext(op)[0]
            new_base = os.path.splitext(np)[0]
            for ext in ('.srt', '.vtt'):
                old_sub = old_base + ext
                new_sub = new_base + ext
                if os.path.exists(old_sub):
                    os.makedirs(os.path.dirname(new_sub), exist_ok=True)
                    shutil.move(old_sub, new_sub)

            self._migrate_video_metadata(old_rel, new_rel)
            return True
        except: return False

    @pyqtSlot(str, str, result=bool)
    def create_folder(self, parent_path, folder_name):
        try:
            name = os.path.basename((folder_name or "").strip())
            if not name:
                return False

            parent_abs = self._safe_media_path(parent_path)
            new_folder = os.path.abspath(os.path.join(parent_abs, name))
            base = os.path.abspath(self.get_media_path())
            if os.path.commonpath([new_folder, base]) != base:
                return False

            os.makedirs(new_folder, exist_ok=True)
            return True
        except:
            return False

    @pyqtSlot(str, str, result=bool)
    def rename_folder(self, old_path, new_name):
        try:
            old_rel = self._normalize_rel(old_path)
            if not old_rel:
                return False

            safe_name = os.path.basename((new_name or "").strip())
            if not safe_name:
                return False

            old_abs = self._safe_media_path(old_rel)
            parent_abs = os.path.dirname(old_abs)
            new_abs = os.path.abspath(os.path.join(parent_abs, safe_name))
            base = os.path.abspath(self.get_media_path())
            if os.path.commonpath([new_abs, base]) != base:
                return False

            parent_rel = os.path.dirname(old_rel).replace("\\", "/")
            new_rel = safe_name if not parent_rel else f"{parent_rel}/{safe_name}"

            os.rename(old_abs, new_abs)
            self._migrate_folder_metadata(old_rel, new_rel)
            return True
        except:
            return False

    @pyqtSlot(str, result=bool)
    def delete_folder(self, folder_path):
        try:
            rel = self._normalize_rel(folder_path)
            if not rel:
                return False

            abs_folder = self._safe_media_path(rel)
            if not os.path.isdir(abs_folder):
                return False

            shutil.rmtree(abs_folder)
            self._purge_folder_metadata(rel)
            return True
        except:
            return False

    @pyqtSlot(str, result=str)
    def browse_folders(self, target_path):
        import json
        try:
            requested = (target_path or "").strip()
            if not requested:
                current = os.path.abspath(self.get_media_path())
            else:
                current = os.path.abspath(os.path.expanduser(requested))

            if not os.path.isdir(current):
                current = os.path.abspath(self.get_media_path())

            parent = os.path.dirname(current)
            if not parent:
                parent = current

            folders = []
            for entry in os.scandir(current):
                if entry.is_dir() and not entry.name.startswith('.'):
                    folders.append(entry.name)

            return json.dumps({
                "currentPath": current,
                "parentPath": parent,
                "folders": sorted(folders, key=lambda n: n.lower())
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @pyqtSlot(str, result=str)
    def search_video(self, filename):
        import json
        try:
            if not filename:
                return json.dumps({"found": False})

            base = os.path.abspath(self.get_media_path())
            for root, _dirs, files in os.walk(base):
                if filename in files:
                    rel_folder = os.path.relpath(root, base).replace("\\", "/")
                    rel_folder = "." if rel_folder == "." else rel_folder
                    rel_file = filename if rel_folder == "." else f"{rel_folder}/{filename}"
                    return json.dumps({
                        "found": True,
                        "folder": rel_folder,
                        "url": self._rel_to_media_url(rel_file)
                    })

            return json.dumps({"found": False})
        except Exception as e:
            return json.dumps({"found": False, "error": str(e)})

    # ─── API de Imagenes (Python + SQLite via app_config) ───────────────────
    @pyqtSlot(result=str)
    def get_image_media_path(self):
        c = _db(); r = c.execute("SELECT val FROM app_config WHERE key='imageMediaPath'").fetchone(); c.close()
        path = r[0] if r and r[0] else os.path.expanduser("~/Pictures")
        if not os.path.isdir(path):
            path = os.path.expanduser("~")
        return path

    def _safe_image_path(self, rel_path):
        base = os.path.abspath(self.get_image_media_path())
        rel_norm = self._normalize_rel(rel_path)
        target = os.path.abspath(os.path.join(base, rel_norm))
        if os.path.commonpath([target, base]) != base:
            raise ValueError("Ruta fuera de la biblioteca de imagenes")
        return target

    @pyqtSlot(result=str)
    def get_image_settings(self):
        import json
        c = _db()
        rows = c.execute("SELECT key, val FROM app_config WHERE key IN ('imageMediaPath', 'imageSortBy', 'imageLastFolder')").fetchall()
        c.close()
        data = {k: v for k, v in rows}
        return json.dumps({
            "imageMediaPath": data.get("imageMediaPath", self.get_image_media_path()),
            "sortBy": data.get("imageSortBy", "name-asc"),
            "lastFolder": data.get("imageLastFolder", ".")
        })

    @pyqtSlot(result=str)
    def get_image_folders(self):
        import json
        base = os.path.abspath(self.get_image_media_path())

        def _build_tree(dir_path):
            nodes = []
            try:
                for entry in os.scandir(dir_path):
                    if entry.is_dir() and not entry.name.startswith('.'):
                        rel = os.path.relpath(entry.path, base).replace("\\", "/")
                        nodes.append({
                            "name": entry.name,
                            "path": rel,
                            "children": _build_tree(entry.path)
                        })
            except Exception:
                pass
            return sorted(nodes, key=lambda x: x['name'].lower())

        return json.dumps(_build_tree(base))

    @pyqtSlot(str, result=str)
    def get_images(self, rel_path):
        import json
        image_exts = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif', '.tiff')
        rel = self._normalize_rel(rel_path)
        target = self._safe_image_path(rel)
        images = []
        try:
            for entry in os.scandir(target):
                if entry.is_file() and entry.name.lower().endswith(image_exts):
                    st = entry.stat()
                    rel_file = entry.name if not rel else f"{rel}/{entry.name}"
                    images.append({
                        "name": entry.name,
                        "path": rel_file,
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        "url": QUrl.fromLocalFile(os.path.abspath(entry.path)).toString()
                    })
        except Exception:
            pass
        return json.dumps(sorted(images, key=lambda x: x['name'].lower()))

    @pyqtSlot(str, result=str)
    def get_image_absolute_path(self, rel_path):
        return self._safe_image_path(rel_path)

    @pyqtSlot(str, str, result=str)
    def rename_image(self, rel_path, new_name):
        import json
        try:
            safe_name = os.path.basename((new_name or '').strip())
            if not safe_name:
                return json.dumps({"success": False, "error": "Nombre invalido"})

            old_abs = self._safe_image_path(rel_path)
            new_abs = os.path.join(os.path.dirname(old_abs), safe_name)
            base = os.path.abspath(self.get_image_media_path())
            new_abs = os.path.abspath(new_abs)
            if os.path.commonpath([new_abs, base]) != base:
                return json.dumps({"success": False, "error": "Ruta invalida"})

            os.rename(old_abs, new_abs)
            new_rel = os.path.relpath(new_abs, base).replace("\\", "/")
            return json.dumps({"success": True, "newPath": new_rel})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @pyqtSlot(str, str, result=bool)
    def move_image(self, rel_path, dest_folder):
        try:
            src = self._safe_image_path(rel_path)
            dst_dir = self._safe_image_path(dest_folder)
            if not os.path.isdir(dst_dir):
                return False
            dst = os.path.join(dst_dir, os.path.basename(src))
            shutil.move(src, dst)
            return True
        except Exception:
            return False

    @pyqtSlot(str, result=bool)
    def delete_image(self, rel_path):
        try:
            abs_path = self._safe_image_path(rel_path)
            if not os.path.isfile(abs_path):
                return False
            os.remove(abs_path)
            return True
        except Exception:
            return False

    @pyqtSlot(str, result=bool)
    def create_image_folder(self, rel_path):
        try:
            abs_path = self._safe_image_path(rel_path)
            os.makedirs(abs_path, exist_ok=True)
            return True
        except Exception:
            return False

    @pyqtSlot(str, str, result=bool)
    def rename_image_folder(self, old_rel_path, new_name):
        try:
            safe_name = os.path.basename((new_name or '').strip())
            if not safe_name:
                return False
            old_abs = self._safe_image_path(old_rel_path)
            new_abs = os.path.abspath(os.path.join(os.path.dirname(old_abs), safe_name))
            base = os.path.abspath(self.get_image_media_path())
            if os.path.commonpath([new_abs, base]) != base:
                return False
            os.rename(old_abs, new_abs)
            return True
        except Exception:
            return False

    @pyqtSlot(str, result=bool)
    def delete_image_folder(self, rel_path):
        try:
            abs_path = self._safe_image_path(rel_path)
            if not os.path.isdir(abs_path):
                return False
            shutil.rmtree(abs_path)
            return True
        except Exception:
            return False

    @pyqtSlot(str, result=str)
    def browse_local_path(self, target_path):
        import json
        try:
            requested = (target_path or '').strip()
            current = os.path.abspath(os.path.expanduser(requested if requested else self.get_image_media_path()))
            if not os.path.isdir(current):
                current = os.path.abspath(self.get_image_media_path())

            parent = os.path.dirname(current)
            if not parent:
                parent = current

            folders = []
            for entry in os.scandir(current):
                if entry.is_dir() and not entry.name.startswith('.'):
                    folders.append(entry.name)

            return json.dumps({
                "currentPath": current,
                "parentPath": parent,
                "folders": sorted(folders, key=lambda n: n.lower())
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @pyqtSlot(str, result=bool)
    def set_image_wallpaper(self, rel_path):
        """Aplica una imagen de la biblioteca como fondo de pantalla (Linux)."""
        try:
            abs_path = self._safe_image_path(rel_path)
            if not os.path.isfile(abs_path):
                return False

            file_uri = QUrl.fromLocalFile(abs_path).toString()
            desktop = (os.environ.get('XDG_CURRENT_DESKTOP', '') or '').lower()

            # GNOME / Ubuntu / Cinnamon (gsettings)
            if shutil.which('gsettings') and any(x in desktop for x in ['gnome', 'ubuntu', 'cinnamon']):
                subprocess.run(['gsettings', 'set', 'org.gnome.desktop.background', 'picture-uri', file_uri], check=False)
                subprocess.run(['gsettings', 'set', 'org.gnome.desktop.background', 'picture-uri-dark', file_uri], check=False)
                return True

            # XFCE (xfconf-query)
            if shutil.which('xfconf-query') and 'xfce' in desktop:
                # Ruta comun para fondo en XFCE; si falla, simplemente devuelve False
                subprocess.run([
                    'xfconf-query', '-c', 'xfce4-desktop',
                    '-p', '/backdrop/screen0/monitor0/image-path', '-s', abs_path
                ], check=False)
                return True

            # Fallback generico con feh (si existe)
            if shutil.which('feh'):
                subprocess.run(['feh', '--bg-fill', abs_path], check=False)
                return True

            return False
        except Exception:
            return False

    @pyqtSlot(str, result=str)
    def resolve_video_url(self, url):
        """Usa yt-dlp nativamente para resolver la URL de streaming."""
        import subprocess, json
        yt_dlp_path = '/home/perry/.local/bin/yt-dlp'
        try:
            # Determinamos si es youtube u otra cosa
            site = "YouTube" if "youtu" in url else "Externo"
            if "xhamster" in url: site = "xHamster"
            elif "pornhub" in url: site = "Pornhub"
            
            res = subprocess.run([
                yt_dlp_path, '-f', 'best[ext=mp4][protocol=https]/best',
                '--get-url', '--get-title', '--no-playlist', 
                '--add-header', 'Cookie:parental-control=yes; AgeGate=1', url
            ], capture_output=True, text=True, timeout=15)
            
            if res.returncode == 0:
                lines = [l for l in res.stdout.strip().split('\n') if l]
                title = lines[0] if len(lines) > 0 else "Video"
                vurl = lines[1] if len(lines) > 1 else None
                aurl = lines[2] if len(lines) > 2 else None
                
                if vurl:
                    return json.dumps({
                        "type": "youtube-direct",
                        "videoUrl": vurl, # Devolvemos directo, luego hacemos proxy si es necesario
                        "audioUrl": aurl,
                        "name": f"{site} - {title}",
                        "videoId": url.split('=')[-1] if '=' in url else url.split('/')[-1]
                    })
            
            # Fallback a embed si falla yt-dlp
            vid = url.split('/')[-1].split('=')[-1]
            return json.dumps({
                "type": "embed", "id": vid, "url": url, "name": f"{site} - Video"
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── Cloud Playlists, Playback y Tags ──────────────────────────────────────
    @pyqtSlot(result=str)
    def get_playlists(self):
        c = _db(); res = c.execute("SELECT id, name, items FROM video_playlists ORDER BY id ASC").fetchall(); c.close()
        import json
        return json.dumps([{"id": r[0], "name": r[1], "items": json.loads(r[2])} for r in res])

    @pyqtSlot(str)
    def set_playlists(self, data_json):
        import json
        lists = json.loads(data_json)
        c = _db()
        c.execute("DELETE FROM video_playlists")
        for i, lst in enumerate(lists):
            c.execute("INSERT INTO video_playlists(id, name, items) VALUES(?,?,?)", (i, lst.get('name',''), json.dumps(lst.get('items',[]))))
        c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(str, str)
    def save_playback(self, url, time_str):
        c = _db(); c.execute("INSERT OR REPLACE INTO video_playback(url, time) VALUES(?,?)", (url, float(time_str))); c.commit(); c.close()

    @pyqtSlot(result=str)
    def get_playback_history(self):
        import json
        c = _db(); res = c.execute("SELECT url, time FROM video_playback").fetchall(); c.close()
        return json.dumps({r[0]: r[1] for r in res})

    @pyqtSlot(result=str)
    def get_video_tags(self):
        import json
        c = _db(); res = c.execute("SELECT url, data FROM video_tags").fetchall(); c.close()
        return json.dumps({r[0]: json.loads(r[1]) for r in res})

    @pyqtSlot(str)
    def save_video_tags(self, data_json):
        import json
        tags_map = json.loads(data_json)
        c = _db()
        c.execute("DELETE FROM video_tags")
        for url, data in tags_map.items():
            c.execute("INSERT INTO video_tags(url, data) VALUES(?,?)", (url, json.dumps(data)))
        c.commit(); c.close()

    @pyqtSlot(result=list)
    def get_kanban_cols(self):
        c = _db(); res = c.execute("SELECT id, title, pos FROM kanban_cols ORDER BY pos ASC").fetchall(); c.close()
        return [{"id":r[0],"title":r[1],"pos":r[2]} for r in res]

    @pyqtSlot(int, result=list)
    def get_kanban_cards(self, col_id):
        c = _db(); res = c.execute("SELECT id, col_id, text, pos FROM kanban_cards WHERE col_id=? ORDER BY pos ASC", (col_id,)).fetchall(); c.close()
        return [{"id":r[0],"col_id":r[1],"text":r[2],"pos":r[3]} for r in res]

    @pyqtSlot(str, int)
    def add_kanban_col(self, title, pos):
        c = _db(); c.execute("INSERT INTO kanban_cols(title, pos) VALUES(?,?)", (title, pos)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, str, int)
    def add_kanban_card(self, col_id, text, pos):
        c = _db(); c.execute("INSERT INTO kanban_cards(col_id, text, pos) VALUES(?,?,?)", (col_id, text, pos)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, int, int)
    def move_kanban_card(self, card_id, new_col_id, new_pos):
        c = _db(); c.execute("UPDATE kanban_cards SET col_id=?, pos=? WHERE id=?", (new_col_id, new_pos, card_id)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, int, str)
    def update_kanban_card(self, card_id, col_id, text):
        c = _db(); c.execute("UPDATE kanban_cards SET col_id=?, text=? WHERE id=?", (col_id, text, card_id)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(result=list)
    def get_notes(self):
        c = _db(); res = c.execute("SELECT id, content, color, x, y, z_index FROM notes ORDER BY z_index ASC").fetchall(); c.close()
        return [{"id":r[0],"content":r[1] or '',"color":r[2] or 'yellow',"x":r[3] or 20,"y":r[4] or 20,"zIndex":r[5] or 1} for r in res]

    @pyqtSlot(str, int, int, int, result=int)
    def add_note(self, color, x, y, z_index):
        c = _db()
        cur = c.execute("INSERT INTO notes(content, color, x, y, z_index) VALUES('',?,?,?,?)", (color, x, y, z_index))
        c.commit()
        nid = cur.lastrowid
        c.close()
        return nid

    @pyqtSlot(int, str)
    def update_note_content(self, nid, content):
        c = _db(); c.execute("UPDATE notes SET content=? WHERE id=?", (content, nid)); c.commit(); c.close()

    @pyqtSlot(int, str)
    def update_note_color(self, nid, color):
        c = _db(); c.execute("UPDATE notes SET color=? WHERE id=?", (color, nid)); c.commit(); c.close()

    @pyqtSlot(int, int, int)
    def update_note_pos(self, nid, x, y):
        c = _db(); c.execute("UPDATE notes SET x=?, y=? WHERE id=?", (x, y, nid)); c.commit(); c.close()

    @pyqtSlot(int, int)
    def update_note_zindex(self, nid, z_index):
        c = _db(); c.execute("UPDATE notes SET z_index=? WHERE id=?", (z_index, nid)); c.commit(); c.close()

    @pyqtSlot(int)
    def delete_note(self, nid):
        c = _db(); c.execute("DELETE FROM notes WHERE id=?", (nid,)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(str, str, result=str)
    def save_annotated_screenshot(self, data_url, original_path):
        try:
            if not data_url or not data_url.startswith("data:image/"):
                return ""
            payload = data_url.split(",", 1)[1]
            raw = base64.b64decode(payload)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            screenshots_dir = get_screenshots_dir()
            path = os.path.join(screenshots_dir, f"shot_annotated_{stamp}.png")
            with open(path, "wb") as f:
                f.write(raw)
            save_screenshot(path, "annotated")
            cleanup_original_screenshot(original_path, screenshots_dir)
            return path
        except Exception as ex:
            print(f"[Screenshot] Error al guardar anotacion: {ex}")
            return ""

    @pyqtSlot(str, str, result=bool)
    def copy_annotated_screenshot(self, data_url, original_path):
        try:
            if not data_url or not data_url.startswith("data:image/"):
                return False
            payload = data_url.split(",", 1)[1]
            raw = base64.b64decode(payload)
            image = QImage()
            if not image.loadFromData(raw, "PNG"):
                return False
            QApplication.clipboard().setImage(image)
            cleanup_original_screenshot(original_path, get_screenshots_dir())
            return True
        except Exception as ex:
            print(f"[Screenshot] Error al copiar anotacion: {ex}")
            return False

    @pyqtSlot(str, result=bool)
    def discard_screenshot(self, original_path):
        try:
            cleanup_original_screenshot(original_path, get_screenshots_dir())
            return True
        except Exception as ex:
            print(f"[Screenshot] Error al descartar captura: {ex}")
            return False

    @pyqtSlot()
    def close_current_tab(self):
        self.parent().main_win._close_tab_safe(self.parent().main_win._active)

    @pyqtSlot()
    def window_minimize(self):
        self.parent().main_win.showMinimized()

    @pyqtSlot()
    def window_maximize(self):
        mw = self.parent().main_win
        if mw.isMaximized(): mw.showNormal()
        else: mw.showMaximized()

    @pyqtSlot()
    def window_close(self):
        # Cerramos solo la pestaña actual si es la agenda
        self.parent().main_win._close_tab_safe(self.parent().main_win._active)


class PasswordBridge(QObject):
    updated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

    def _normalize_type(self, site, pwd_type):
        t = (pwd_type or '').strip().lower()
        if t in ('web', 'app'):
            return t
        return 'web' if '.' in (site or '') else 'app'

    def _find_existing_id(self, c, site, user, exclude_id=None):
        base_sql = (
            "SELECT id FROM passwords "
            "WHERE lower(trim(site))=lower(trim(?)) "
            "AND lower(trim(username))=lower(trim(?))"
        )
        params = [site, user]
        if exclude_id:
            base_sql += " AND id<>?"
            params.append(int(exclude_id))
        row = c.execute(base_sql + " ORDER BY id ASC LIMIT 1", tuple(params)).fetchone()
        return int(row[0]) if row else None

    def _normalize_policy(self, policy):
        val = (policy or 'ask').strip().lower()
        return val if val in ('ask', 'always', 'never') else 'ask'

    @pyqtSlot(result=str)
    def get_auto_save_policy(self):
        c = _db()
        row = c.execute("SELECT val FROM app_config WHERE key='passwordAutoSavePolicy'").fetchone()
        c.close()
        return self._normalize_policy(row[0] if row else 'ask')

    @pyqtSlot(str)
    def set_auto_save_policy(self, policy):
        val = self._normalize_policy(policy)
        c = _db()
        c.execute("INSERT OR REPLACE INTO app_config(key,val) VALUES(?,?)", ('passwordAutoSavePolicy', val))
        c.commit()
        c.close()
        self.updated.emit()

    @pyqtSlot(result=list)
    def get_passwords(self):
        c = _db()
        res = c.execute(
            "SELECT id, site, username, password, type, url, notes, ts FROM passwords ORDER BY site ASC"
        ).fetchall()
        c.close()
        return [
            {
                "id": r[0],
                "site": r[1],
                "username": r[2],
                "password": r[3],
                "type": r[4] or self._normalize_type(r[1], ''),
                "url": r[5] or '',
                "notes": r[6] or '',
                "ts": r[7]
            }
            for r in res
        ]

    @pyqtSlot(str, str, str)
    def save_password(self, site, user, pwd):
        site = (site or '').strip()
        user = (user or '').strip()
        pwd = pwd or ''
        if not site or not user or not pwd:
            return

        c = _db()
        existing_id = self._find_existing_id(c, site, user)
        pwd_type = self._normalize_type(site, '')
        if existing_id:
            c.execute(
                "UPDATE passwords SET password=?, type=?, ts=CURRENT_TIMESTAMP WHERE id=?",
                (pwd, pwd_type, existing_id)
            )
        else:
            c.execute(
                "INSERT INTO passwords(site, username, password, type, url, notes) VALUES(?,?,?,?,?,?)",
                (site, user, pwd, pwd_type, '', '')
            )
        c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, str, str, str, str, str, str, result=int)
    def upsert_password(self, pid, site, user, pwd, pwd_type, url, notes):
        site = (site or '').strip()
        user = (user or '').strip()
        pwd = pwd or ''
        if not site or not user or not pwd:
            return 0

        c = _db()
        norm_type = self._normalize_type(site, pwd_type)
        row = c.execute("SELECT id FROM passwords WHERE id=?", (pid,)).fetchone() if pid else None

        if row:
            duplicate_id = self._find_existing_id(c, site, user, exclude_id=pid)
            if duplicate_id:
                # Unificar en un solo registro cuando una edición colisiona con otro ya existente.
                c.execute(
                    "UPDATE passwords SET site=?, username=?, password=?, type=?, url=?, notes=?, ts=CURRENT_TIMESTAMP WHERE id=?",
                    (site, user, pwd, norm_type, url or '', notes or '', duplicate_id)
                )
                c.execute("DELETE FROM passwords WHERE id=?", (pid,))
                new_id = duplicate_id
            else:
                c.execute(
                    "UPDATE passwords SET site=?, username=?, password=?, type=?, url=?, notes=?, ts=CURRENT_TIMESTAMP WHERE id=?",
                    (site, user, pwd, norm_type, url or '', notes or '', pid)
                )
                new_id = pid
        else:
            existing_id = self._find_existing_id(c, site, user)
            if existing_id:
                c.execute(
                    "UPDATE passwords SET password=?, type=?, url=?, notes=?, ts=CURRENT_TIMESTAMP WHERE id=?",
                    (pwd, norm_type, url or '', notes or '', existing_id)
                )
                new_id = existing_id
            else:
                c.execute(
                    "INSERT INTO passwords(site, username, password, type, url, notes) VALUES(?,?,?,?,?,?)",
                    (site, user, pwd, norm_type, url or '', notes or '')
                )
                new_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

        c.commit(); c.close()
        self.updated.emit()
        return int(new_id)

    @pyqtSlot(int)
    def delete_password(self, pid):
        c = _db(); c.execute("DELETE FROM passwords WHERE id=?", (pid,)); c.commit(); c.close()
        self.updated.emit()



# ─── WebPage personalizada (intercepta mensajes de consola) ───────────────────
class WebPage(QWebEnginePage):
    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self._last_pwd_prompt_key = ""
        self._last_pwd_prompt_ts = 0.0
        self._last_autofill_host = ""
        self._last_autofill_ts = 0.0

    def _normalized_host(self, value: str) -> str:
        raw = (value or "").strip().lower()
        if not raw:
            return ""
        if "://" not in raw:
            raw = "https://" + raw
        try:
            parsed = urlparse(raw)
            return (parsed.hostname or "").lower()
        except Exception:
            return ""

    def _load_matching_credentials(self, host: str, url: str = "") -> list[dict]:
        host = self._normalized_host(host)
        if not host:
            return []

        c = sqlite3.connect(DB)
        rows = c.execute(
            "SELECT id, site, username, password, type, url, ts FROM passwords WHERE type='web' OR type IS NULL OR type=''"
        ).fetchall()
        c.close()

        url_host = self._normalized_host(url)
        ranked = []
        for row in rows:
            # Acepta credenciales guardadas con dominio en "site" o en "url"
            # para que Llaves de Agenda funcione como fuente de autofill.
            candidates = set()
            saved_site_host = self._normalized_host(row[1] or "")
            saved_url_host = self._normalized_host(row[5] or "")
            if saved_site_host:
                candidates.add(saved_site_host)
            if saved_url_host:
                candidates.add(saved_url_host)
            if not candidates:
                continue

            score = 0
            for candidate in candidates:
                if host == candidate:
                    score = max(score, 120)
                if host.endswith("." + candidate):
                    score = max(score, 110)
                if candidate.endswith("." + host):
                    score = max(score, 95)

                if url_host:
                    if url_host == candidate:
                        score = max(score, 115)
                    elif url_host.endswith("." + candidate):
                        score = max(score, 105)

            if score <= 0:
                continue

            ranked.append({
                "id": int(row[0]),
                "site": row[1] or "",
                "username": row[2] or "",
                "password": row[3] or "",
                "url": row[5] or "",
                "ts": row[6] or "",
                "score": score,
            })

        ranked.sort(key=lambda item: (item["score"], item["ts"]), reverse=True)
        return ranked[:5]

    def _run_autofill(self, credentials: list[dict]):
        if not credentials:
            return
        js_payload = json.dumps([
            {"username": c.get("username", ""), "password": c.get("password", "")}
            for c in credentials if c.get("password")
        ], ensure_ascii=False)
        if not js_payload or js_payload == "[]":
            return

        fill_js = f"""
(function(creds) {{
    if (!Array.isArray(creds) || !creds.length) return false;

    function isVisible(el) {{
        if (!el) return false;
        const st = window.getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden') return false;
        if (el.disabled || el.readOnly) return false;
        return true;
    }}

    function setValue(el, value) {{
        if (!el || !isVisible(el) || value == null) return false;
        const next = String(value);
        if (!next) return false;
        if (el.value === next) return true;
        el.focus();

        // Algunos frameworks (React/Vue) ignoran asignaciones directas sin setter nativo.
        const proto = Object.getPrototypeOf(el);
        const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
        if (descriptor && typeof descriptor.set === 'function') {{
            descriptor.set.call(el, next);
        }} else {{
            el.value = next;
        }}

        try {{
            el.dispatchEvent(new InputEvent('input', {{
                bubbles: true,
                cancelable: true,
                data: next,
                inputType: 'insertText'
            }}));
        }} catch (_err) {{
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }}

        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        el.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: 'Unidentified' }}));
        el.blur();
        return true;
    }}

    function findUserField(passField) {{
        const selectors = [
            'input[type="email"]',
            'input[type="text"]',
            'input[name*="user" i]',
            'input[name*="login" i]',
            'input[name*="mail" i]',
            'input[name*="identifier" i]',
            'input[id*="user" i]',
            'input[id*="login" i]',
            'input[id*="mail" i]'
        ].join(',');

        const form = passField ? (passField.form || passField.closest('form')) : null;
        if (form) {{
            const inForm = Array.from(form.querySelectorAll(selectors)).find(isVisible);
            if (inForm) return inForm;
        }}
        return Array.from(document.querySelectorAll(selectors)).find(isVisible) || null;
    }}

    const selected = creds[0];
    const passwordFields = Array.from(document.querySelectorAll('input[type="password"]')).filter(isVisible);
    if (!passwordFields.length) return false;

    let wroteSomething = false;
    for (const passField of passwordFields) {{
        const userField = findUserField(passField);
        if (userField && selected.username && !userField.value) {{
            wroteSomething = setValue(userField, selected.username) || wroteSomething;
        }}
        if (selected.password) {{
            wroteSomething = setValue(passField, selected.password) || wroteSomething;
        }}
    }}
    return wroteSomething;
}})({js_payload});
        """
        self.runJavaScript(fill_js)

    def _save_or_update_password(self, data: dict):
        site = self._normalized_host(data.get("site") or data.get("url") or "")
        user = (data.get("user") or "").strip()
        pwd = data.get("pwd") or ""
        full_url = (data.get("url") or "").strip()

        if not site or not user or not pwd:
            return

        c = sqlite3.connect(DB)
        existing = c.execute(
            "SELECT id, password FROM passwords "
            "WHERE lower(trim(site))=lower(trim(?)) AND lower(trim(username))=lower(trim(?)) "
            "ORDER BY id ASC LIMIT 1",
            (site, user)
        ).fetchone()

        if existing:
            if (existing[1] or "") == pwd:
                c.close()
                return
            c.execute(
                "UPDATE passwords SET password=?, type='web', url=?, ts=CURRENT_TIMESTAMP WHERE id=?",
                (pwd, full_url, existing[0])
            )
            action = "actualizada"
        else:
            c.execute(
                "INSERT INTO passwords(site, username, password, type, url, notes) VALUES(?,?,?,?,?,?)",
                (site, user, pwd, 'web', full_url, '')
            )
            action = "guardada"

        c.commit()
        c.close()

        vw = self.view()
        if vw and hasattr(vw, "main_win"):
            Notif("Contraseña " + action, f"{user} en {site}", vw.main_win)

    def _get_pwd_policy(self) -> str:
        c = _db()
        row = c.execute("SELECT val FROM app_config WHERE key='passwordAutoSavePolicy'").fetchone()
        c.close()
        policy = (row[0] if row else 'ask') or 'ask'
        policy = policy.strip().lower()
        return policy if policy in ('ask', 'always', 'never') else 'ask'

    def _set_pwd_policy(self, policy: str):
        val = (policy or 'ask').strip().lower()
        if val not in ('ask', 'always', 'never'):
            val = 'ask'
        c = _db()
        c.execute("INSERT OR REPLACE INTO app_config(key,val) VALUES(?,?)", ('passwordAutoSavePolicy', val))
        c.commit()
        c.close()

    def _ask_save_password(self, site: str, user: str) -> str:
        vw = self.view()
        parent = vw.main_win if (vw and hasattr(vw, 'main_win')) else vw

        d = QDialog(parent)
        d.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        d.setStyleSheet(
            "QDialog{background:#11111a; border:1px solid rgba(255,255,255,0.1); border-radius:12px;}"
        )

        v = QVBoxLayout(d)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(12)

        t = QLabel("Guardar contraseña")
        t.setStyleSheet("color:white; font-size:16px; font-weight:bold;")
        v.addWidget(t)

        m = QLabel(f"¿Quieres guardar la clave de {user} en {site}?")
        m.setStyleSheet("color:#aaa; font-size:13px;")
        m.setWordWrap(True)
        v.addWidget(m)

        h = QHBoxLayout()
        h.setSpacing(10)
        h.addStretch()

        choice = {'value': 'skip'}

        btn_no = QPushButton("No guardar")
        btn_no.setStyleSheet(BTN_NAV)
        btn_no.clicked.connect(lambda: (choice.__setitem__('value', 'skip'), d.accept()))

        btn_never = QPushButton("Nunca guardar")
        btn_never.setStyleSheet(BTN_NAV + "background:rgba(255,95,87,0.08); color:#ff8f87;")
        btn_never.clicked.connect(lambda: (choice.__setitem__('value', 'never'), d.accept()))

        btn_yes = QPushButton("Guardar")
        btn_yes.setStyleSheet(BTN_NAV + "background:rgba(81,162,255,0.12); color:#cfe6ff;")
        btn_yes.clicked.connect(lambda: (choice.__setitem__('value', 'save'), d.accept()))

        h.addWidget(btn_no)
        h.addWidget(btn_never)
        h.addWidget(btn_yes)
        v.addLayout(h)

        d.exec()
        return choice['value']

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith("MINICHROME_LINKS:"):
            save_quick_links(message[len("MINICHROME_LINKS:"):])
        elif message.startswith("MINICHROME_AUTOFILL_REQUEST:"):
            try:
                data = json.loads(message[len("MINICHROME_AUTOFILL_REQUEST:"):])
                host = self._normalized_host(data.get("host") or "")
                if not host:
                    return

                now_ts = time.time()
                if host == self._last_autofill_host and (now_ts - self._last_autofill_ts) < 0.9:
                    return

                self._last_autofill_host = host
                self._last_autofill_ts = now_ts
                creds = self._load_matching_credentials(host, data.get("url") or "")
                self._run_autofill(creds)
            except Exception as e:
                print(f"[Autofill] Error: {e}")
        elif message.startswith("MINICHROME_PWD:"):
            try:
                data = json.loads(message[len("MINICHROME_PWD:"):])
                site = self._normalized_host(data.get("site") or data.get("url") or "")
                user = (data.get("user") or "").strip()
                pwd = data.get("pwd") or ""
                if not site or not user or not pwd:
                    return

                prompt_key = f"{site}|{user}|{pwd}"
                now_ts = time.time()
                if prompt_key == self._last_pwd_prompt_key and (now_ts - self._last_pwd_prompt_ts) < 15.0:
                    return
                self._last_pwd_prompt_key = prompt_key
                self._last_pwd_prompt_ts = now_ts

                c = sqlite3.connect(DB)
                existing = c.execute(
                    "SELECT id, password FROM passwords WHERE site=? AND username=?",
                    (site, user)
                ).fetchone()
                c.close()

                if existing and (existing[1] or "") == pwd:
                    return

                policy = self._get_pwd_policy()
                if policy == 'never':
                    return
                if policy == 'ask':
                    decision = self._ask_save_password(site, user)
                    if decision == 'never':
                        self._set_pwd_policy('never')
                        vw = self.view()
                        if vw and hasattr(vw, 'main_win'):
                            Notif("Auto-guardado desactivado", "No se volveran a solicitar claves", vw.main_win)
                        return
                    if decision != 'save':
                        return

                # Persistencia automática para que el autollenado use inmediatamente
                # las credenciales en el área Llaves de Agenda.
                self._save_or_update_password({
                    "site": site,
                    "user": user,
                    "pwd": pwd,
                    "url": data.get("url") or ""
                })
            except Exception as e:
                print(f"[Passwords] Error al capturar: {e}")
        else:
            pass  # suprimir logs de consola en producción

    def runJavaScriptConfirm(self, frame, message):
        """Sobrescribe el diálogo confirm() de JS con una modal premium."""
        d = QDialog(self.view())
        d.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        d.setStyleSheet("QDialog{background:#11111a; border:1px solid rgba(255,255,255,0.1); border-radius:12px;}")
        v = QVBoxLayout(d); v.setContentsMargins(24, 24, 24, 24)
        
        t = QLabel("Confirmación")
        t.setStyleSheet("color:white; font-size:16px; font-weight:bold; margin-bottom:4px;")
        v.addWidget(t)
        
        m = QLabel(message)
        m.setStyleSheet("color:#aaa; font-size:13px; margin-bottom:12px;")
        m.setWordWrap(True)
        v.addWidget(m)
        
        h = QHBoxLayout(); h.setSpacing(10); h.addStretch()
        bc = QPushButton("Cancelar"); bc.setStyleSheet(BTN_NAV); bc.clicked.connect(d.reject)
        ba = QPushButton("Aceptar"); ba.setStyleSheet(BTN_NAV + "background:rgba(255,255,255,0.08); color:#ff5f57;"); ba.clicked.connect(d.accept)
        
        h.addWidget(bc); h.addWidget(ba)
        v.addLayout(h)
        
        return d.exec() == QDialog.DialogCode.Accepted

# ─── WebView ──────────────────────────────────────────────────────────────────
class WebView(QWebEngineView):
    def __init__(self, main_win, url=""):
        super().__init__()
        self.main_win = main_win
        self._was_maximized_before_web_fullscreen = False
        page = WebPage(profile(), self)
        self.setPage(page)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        
        # Canal de comunicación para la Agenda
        self._channel = QWebChannel(self)
        self._bridge = AgendaBridge(self)
        self._pw_bridge = PasswordBridge(self)
        self._channel.registerObject("py", self._bridge)
        self._channel.registerObject("pw", self._pw_bridge)
        self.page().setWebChannel(self._channel)

        page.geometryChangeRequested.connect(self._ignore_geom)
        page.fullScreenRequested.connect(self._handle_fullscreen_request)
        if url:
            self.load(QUrl(url))
        self.loadFinished.connect(self._on_load)

    def _ignore_geom(self, _geom):
        """Descarta peticiones de resize/move del JS para evitar márgenes."""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)

    def _handle_fullscreen_request(self, request):
        """Sincroniza Fullscreen API web con fullscreen real de la ventana Qt."""
        enable_fullscreen = bool(request.toggleOn())
        request.accept()

        if enable_fullscreen:
            self._was_maximized_before_web_fullscreen = self.main_win.isMaximized()
            self.main_win.showFullScreen()
            return

        if self.main_win.isFullScreen():
            if self._was_maximized_before_web_fullscreen:
                self.main_win.showMaximized()
            else:
                self.main_win.showNormal()


    def _on_load(self, ok):
        url = self.url().toString()
        if not ok or not url:
            return
        if url.startswith("file://"):
            if "newtab.html" in url:
                links = load_quick_links()
                if links is not None:
                    import json as _json
                    js = f"window._miniLinks = {_json.dumps(links)}; if (typeof renderLinks === 'function') renderLinks();"
                    self.page().runJavaScript(js)
        else:
            save_history(self.title(), url)

    def createWindow(self, _type):
        return self.main_win.new_tab("")


# ─── Estilos comunes ──────────────────────────────────────────────────────────
BTN_NAV = """
QPushButton{background:transparent;border:none;color:rgba(255,255,255,0.75);
  font-size:15px;border-radius:6px;padding:4px;}
QPushButton:hover{background:rgba(255,255,255,0.15);color:white;}
QPushButton:pressed{background:rgba(255,255,255,0.25);}
"""
BTN_WIN_BASE = """
QPushButton{border:none;border-radius:6px;font-size:0px;}
QPushButton:hover{opacity:1;}
"""

def _shadow(w, blur=22, dy=5, alpha=140):
    s = QGraphicsDropShadowEffect(w)
    s.setBlurRadius(blur); s.setOffset(0,dy)
    s.setColor(QColor(0,0,0,alpha)); w.setGraphicsEffect(s)

# ─── Notificación sticky ──────────────────────────────────────────────────────
class Notif(QFrame):
    def __init__(self, title, body, parent):
        super().__init__(parent)
        self.setObjectName("notif_box")
        self.setStyleSheet("""#notif_box{background-color:#161622;
            border-radius:12px;border:1px solid rgba(255,255,255,0.15);}
            QLabel{color:white; background:transparent;}""")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(4)
        
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: white; font-weight: bold; font-size: 13px; background: transparent;")
        v.addWidget(lbl_title)
        
        lbl_body = QLabel(body)
        lbl_body.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 12px; background: transparent;")
        v.addWidget(lbl_body)
        
        self.adjustSize()
        pw = parent.size()
        self.move(pw.width() - self.width() - 20, pw.height() - self.height() - 20)
        self.show()
        QTimer.singleShot(3000, self.deleteLater)

# ─── Ventana Principal ────────────────────────────────────────────────────────
class Minichrome(QMainWindow):

    # alturas fijas
    TOGGLE_H = 20
    BAR_H  = 36   # barra dirección
    TABS_H = 28   # barra pestañas
    TOTAL  = TOGGLE_H + BAR_H + TABS_H + 4  # total


    def __init__(self):
        super().__init__()
        self.setWindowTitle("Minichrome")
        self.resize(1440, 900)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QMainWindow{background:transparent;}")

        self._views: list[WebView] = []
        self._tab_btns: list[QPushButton] = []
        self._active = -1
        self._bar_open = True
        self._drag_pos: QPoint | None = None
        self._loading_count = 0  # vistas actualmente cargando

        # ─ Spinner del botón "Ir" ────────────────────────────────────────────
        self._spin_frames = ["◴", "◷", "◶", "◵"]  # arcos rotando
        self._spin_idx = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(120)
        self._spin_timer.timeout.connect(self._spin_tick)

        # ── layout raíz ──────────────────────────────────────────────────────
        root = QWidget(); self.setCentralWidget(root)
        root.setObjectName("root")
        self._vbox = QVBoxLayout(root)
        self._vbox.setContentsMargins(0,0,0,0); self._vbox.setSpacing(0)
        self._update_corners()

        # ── Controles de ventana flotantes (top-right) ────────────────────────
        self._win_ctrl = self._build_win_ctrl(root)

        # ── Barra flotante centrada ───────────────────────────────────────────
        self._chrome = self._build_chrome(root)

        # Insertar botón de captura en win_ctrl (entre favoritos y minimizar)
        self._win_ctrl.layout().insertWidget(2, self._shot)

        # ── Notch (siempre visible cuando barra oculta) ───────────────────────
        self._notch = self._build_notch(root)
        self._notch.hide()

        # ── Área de vistas web ────────────────────────────────────────────────
        self._web_wrap = QWidget()
        self._web_wrap.setStyleSheet("background:#090911;")
        self._web_layout = QStackedLayout(self._web_wrap)
        self._web_layout.setContentsMargins(0,0,0,0)
        self._vbox.addWidget(self._web_wrap, 1)

        # ── Animación de la barra ─────────────────────────────────────────────
        self._anim = QPropertyAnimation(self._chrome, b"pos")
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # ── Agarraderas para redimensionar (Edge Grips) ───────────────────────
        self._build_resize_grips(root)
        # ── Panel lateral de Favoritos e Historial ─────────────────────────────
        self._fav_panel = self._build_fav_panel(root)
        self._hist_panel = self._build_hist_panel(root)

        self.new_tab(HOME)
        QTimer.singleShot(100, self._reposition)

    # ── Construcción de la barra flotante ──────────────────────────────────────
    def _build_chrome(self, parent):
        frame = QFrame(parent)
        frame.setObjectName("chrome")
        frame.setStyleSheet("""
            #chrome{background:transparent;}
            #main_bar{background:qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(81,162,255,0.96), stop:1 rgba(41,122,215,0.96));
              border:1px solid rgba(255,255,255,0.2);
              border-radius:12px;}
            #toggle_up{background:transparent;}
        """)
        _shadow(frame, blur=24, dy=8, alpha=150)
        # Eliminado setFixedWidth(850) para hacerlo responsive

        v = QVBoxLayout(frame)
        v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # Toggle Superior (estilo notch + arrastre de ventana)
        tw = QWidget()
        tw.setFixedHeight(self.TOGGLE_H)
        tw.setStyleSheet("background:transparent;")
        th = QHBoxLayout(tw); th.setContentsMargins(0,0,0,0); th.setSpacing(0)
        self._up_btn = QPushButton("∧")
        self._up_btn.setObjectName("toggle_up")
        self._up_btn.setFixedSize(80, self.TOGGLE_H)
        self._up_btn.setToolTip("Ocultar barra  (Ctrl+Space) · Arrastrar para mover")
        self._up_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._up_btn.setStyleSheet("""
            QPushButton{color:rgba(255,255,255,0.7); font-size:8px; padding:0; margin:0;
              background:qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(81,162,255,0.85), stop:1 rgba(41,122,215,0.85));
              border:1px solid rgba(255,255,255,0.2); border-bottom:none;
              border-top-left-radius:7px; border-top-right-radius:7px;}
            QPushButton:hover{color:white; background:rgba(81,162,255,0.98);
              border:1px solid rgba(255,255,255,0.3); border-bottom:none;}
        """)
        # Click sostenido = arrastrar ventana, click simple = ocultar barra
        self._up_btn.mousePressEvent   = self._upbtn_press
        self._up_btn.mouseMoveEvent    = self._upbtn_move
        self._up_btn.mouseReleaseEvent = self._upbtn_release
        th.addStretch(); th.addWidget(self._up_btn); th.addStretch()
        v.addWidget(tw)

        # Contenedor Principal (URL y botones)
        main_bar = QFrame()
        main_bar.setObjectName("main_bar")
        mb = QVBoxLayout(main_bar)
        mb.setContentsMargins(0,0,0,0); mb.setSpacing(0)

        row1 = QWidget(); row1.setFixedHeight(self.BAR_H)
        h1 = QHBoxLayout(row1); h1.setContentsMargins(8,2,8,2); h1.setSpacing(4)

        self._back = self._nb("‹","Atrás"); self._back.clicked.connect(self._go_back)
        self._fwd  = self._nb("›","Adelante"); self._fwd.clicked.connect(self._go_fwd)
        self._rld  = self._nb("↻","Recargar"); self._rld.clicked.connect(self._go_reload)

        self._sec = QLabel("")
        self._sec.setFixedSize(20, 20)
        self._sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sec.setStyleSheet("font-size:16px; background:transparent;")

        self._url = QLineEdit()
        self._url.setPlaceholderText("Buscar o navegar...")
        self._url.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._url.setFixedHeight(24)
        self._url.setStyleSheet("""
            QLineEdit{background:transparent;border:none;
              padding:0 4px;color:rgba(255,255,255,0.95);font-size:13px;
              selection-background-color:rgba(0,0,0,0.3);}
            QLineEdit:focus{background:rgba(0,0,0,0.15); border-radius:6px;}
        """)
        self._url.returnPressed.connect(self._navigate)

        # Contenedor conjunto icono+url sin gap interno
        url_wrap = QWidget()
        url_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        url_h = QHBoxLayout(url_wrap)
        url_h.setContentsMargins(0, 0, 0, 0)
        url_h.setSpacing(2)
        url_h.addWidget(self._sec)
        url_h.addWidget(self._url)

        # ── Controles de Zoom ─────────────────────────────────────────────
        ZOOM_BTN = """QPushButton{background:rgba(255,255,255,0.1);border:none;
            border-radius:5px;color:rgba(255,255,255,0.75);font-size:14px;}
            QPushButton:hover{background:rgba(255,255,255,0.22);color:white;}"""

        self._zoom_out = QPushButton("−")
        self._zoom_out.setFixedSize(20, 20)
        self._zoom_out.setToolTip("Reducir (Ctrl+-)")
        self._zoom_out.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._zoom_out.setStyleSheet(ZOOM_BTN)
        self._zoom_out.clicked.connect(self._zoom_out_act)

        self._zoom_lbl = QPushButton("100%")
        self._zoom_lbl.setFixedSize(34, 20)
        self._zoom_lbl.setToolTip("Restablecer zoom (doble clic)")
        self._zoom_lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._zoom_lbl.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:rgba(255,255,255,0.6);"
            "font-size:10px;} QPushButton:hover{color:white;}")
        self._zoom_lbl.clicked.connect(self._zoom_reset)

        self._zoom_in = QPushButton("+")
        self._zoom_in.setFixedSize(20, 20)
        self._zoom_in.setToolTip("Ampliar (Ctrl++)")
        self._zoom_in.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._zoom_in.setStyleSheet(ZOOM_BTN)
        self._zoom_in.clicked.connect(self._zoom_in_act)

        self._go = QPushButton("⊙")
        self._go.setFixedSize(28,28)
        self._go.setToolTip("Ir")
        self._go.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._go.setStyleSheet("""
            QPushButton{background:rgba(255,255,255,0.2);border:none;border-radius:14px;
              color:white;font-size:14px;}
            QPushButton:hover{background:rgba(255,255,255,0.35);}
        """)
        self._go.clicked.connect(self._go_clicked)
        
        self._fav = self._nb("☆","Guardar favorito")
        self._fav.clicked.connect(self._save_fav)

        self._shot = QPushButton("📷")
        self._shot.setFixedSize(14, 14)
        self._shot.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._shot.setToolTip("Capturar pantalla (Ctrl+Shift+S)")
        self._shot.setStyleSheet("""
            QPushButton{background:rgba(0,0,0,0.15);border:none;
              border-radius:7px;font-size:0px;}
            QPushButton:hover{background:#6c5ce7;font-size:8px;color:rgba(0,0,0,.7);}
        """)
        self._shot.clicked.connect(self._capture_screenshot)

        for w in [self._back, self._fwd, self._rld, url_wrap,
                  self._go, self._zoom_out, self._zoom_lbl, self._zoom_in,
                  self._fav]:
            h1.addWidget(w)
            
        mb.addWidget(row1)

        # Contenedor de Pestañas
        tabs_wrapper = QWidget()
        tabs_wrapper.setFixedHeight(self.TABS_H)
        h2 = QHBoxLayout(tabs_wrapper); h2.setContentsMargins(8,0,8,0); h2.setSpacing(4)
        h2.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._tabs_inner = QWidget()
        self._tabs_layout = QHBoxLayout(self._tabs_inner)
        self._tabs_layout.setContentsMargins(0,0,0,0); self._tabs_layout.setSpacing(4)
        self._tabs_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._tabs_inner.setStyleSheet("background:transparent;")

        self._tabs_scroll = QScrollArea()
        self._tabs_scroll.setWidget(self._tabs_inner)
        self._tabs_scroll.setWidgetResizable(True)
        self._tabs_scroll.setFixedHeight(self.TABS_H - 4)
        self._tabs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tabs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tabs_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        # Botones de scroll lateral para pestañas desbordadas
        self._scroll_left = QPushButton("‹")
        self._scroll_left.setToolTip("Pestañas anteriores")
        self._scroll_left.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._scroll_left.setFixedSize(20,24)
        self._scroll_left.setStyleSheet("QPushButton{background:rgba(81,162,255,0.9); border-radius:6px; color:white; font-size:16px; font-weight:bold;} QPushButton:hover{background:rgba(41,122,215,1);}")
        self._scroll_left.hide()

        self._scroll_right = QPushButton("›")
        self._scroll_right.setToolTip("Más pestañas")
        self._scroll_right.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._scroll_right.setFixedSize(20,24)
        self._scroll_right.setStyleSheet("QPushButton{background:rgba(81,162,255,0.9); border-radius:6px; color:white; font-size:16px; font-weight:bold;} QPushButton:hover{background:rgba(41,122,215,1);}")
        self._scroll_right.hide()

        def _do_scroll(dx):
            sb = self._tabs_scroll.horizontalScrollBar()
            sb.setValue(sb.value() + dx)

        self._scroll_left.clicked.connect(lambda: _do_scroll(-150))
        self._scroll_right.clicked.connect(lambda: _do_scroll(150))

        def _check_scroll(min_v, max_v):
            overflow = max_v > 0
            self._scroll_left.setVisible(overflow)
            self._scroll_right.setVisible(overflow)
            
        self._tabs_scroll.horizontalScrollBar().rangeChanged.connect(_check_scroll)

        add = QPushButton("＋")
        add.setToolTip("Nueva pestaña  (Ctrl+T)")
        add.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add.setFixedSize(24,24)
        add.setStyleSheet("QPushButton{background:rgba(41,122,215,0.7); border:1px solid rgba(255,255,255,0.2); border-radius:6px; color:rgba(255,255,255,0.75); font-size:13px;} QPushButton:hover{background:rgba(81,162,255,0.9); color:white; border-color:rgba(255,255,255,0.4);}")
        add.clicked.connect(lambda: self.new_tab(HOME))

        h2.addWidget(self._scroll_left)
        h2.addWidget(self._tabs_scroll, 1)
        h2.addWidget(self._scroll_right)
        h2.addWidget(add)
        
        v.addWidget(main_bar)
        v.addWidget(tabs_wrapper)

        # Arrastre de ventana desde la barra
        main_bar.mousePressEvent   = self._drag_press
        main_bar.mouseMoveEvent    = self._drag_move
        main_bar.mouseReleaseEvent = lambda e: setattr(self, '_drag_pos', None)

        frame.setFixedHeight(self.TOTAL)
        return frame

    # ── Notch ─────────────────────────────────────────────────────────────────
    def _build_notch(self, parent):
        btn = QPushButton("∨", parent)
        btn.setFixedSize(80, 14)
        btn.setToolTip("Mostrar barra  (Ctrl+Space) · Arrastrar para mover")
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet("""
            QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(81,162,255,0.85), stop:1 rgba(41,122,215,0.85));
              border:1px solid rgba(255,255,255,0.2);border-top:none;
              border-bottom-left-radius: 7px; border-bottom-right-radius: 7px;
              color:rgba(255,255,255,0.7);font-size:8px;}
            QPushButton:hover{background:rgba(81, 162, 255, 0.98);
              border:1px solid rgba(255,255,255,0.3);border-top:none;
              color:white;}
        """)
        _shadow(btn, blur=10, dy=2, alpha=80)
        btn.clicked.connect(self._show_bar)
        btn.mousePressEvent   = self._notch_press
        btn.mouseMoveEvent    = self._notch_move
        btn.mouseReleaseEvent = self._notch_release
        return btn

    def _notch_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._notch_drag_started = False

    def _notch_move(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self._notch_drag_started = True
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def _notch_release(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            was_dragging = getattr(self, '_notch_drag_started', False)
            self._drag_pos = None
            self._notch_drag_started = False
            if not was_dragging:
                self._show_bar()

    # ── Arrastre desde botón superior (ocultar barra) ─────────────────────────
    def _upbtn_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._upbtn_drag_started = False

    def _upbtn_move(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self._upbtn_drag_started = True
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def _upbtn_release(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            was_dragging = getattr(self, '_upbtn_drag_started', False)
            self._drag_pos = None
            self._upbtn_drag_started = False
            if not was_dragging:
                self._hide_bar()

    # ── Controles de ventana ──────────────────────────────────────────────────
    def _build_win_ctrl(self, parent):
        w = QWidget(parent)
        h = QHBoxLayout(w); h.setContentsMargins(6,6,6,6); h.setSpacing(6)
        w.setStyleSheet("background:transparent;")

        specs = [("◷","#3498db",self._toggle_hist_panel, "Historial de navegación"),
                 ("★","#9b59b6",self._toggle_fav_panel,   "Favoritos guardados"),
                 ("−","#febc2e",self.showMinimized,        "Minimizar ventana"),
                 ("□","#28c840",self._toggle_max,          "Maximizar / Restaurar"),
                 ("×","#ff5f57",self.close,                "Cerrar ventana")]
        for sym,col,fn,tip in specs:
            b = QPushButton(sym)
            b.setFixedSize(14,14)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setToolTip(tip)
            b.setStyleSheet(f"""
                QPushButton{{background:rgba(0,0,0,0.15);border:none;
                  border-radius:7px;font-size:0px;}}
                QPushButton:hover{{background:{col};font-size:8px;color:rgba(0,0,0,.7);}}
            """)
            b.clicked.connect(fn)
            h.addWidget(b)

        w.adjustSize()
        return w

    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._update_corners()

    def _update_corners(self):
        rad = 0 if self.isMaximized() else 10
        self.centralWidget().setStyleSheet(f"""
            #root {{ background:#090911; border-radius:{rad}px; border:1px solid rgba(255,255,255,0.1); }}
        """)

    def changeEvent(self, e):
        if e.type() == e.Type.WindowStateChange:
            self._update_corners()
        super().changeEvent(e)

    # ── Arrastre ──────────────────────────────────────────────────────────────
    def _drag_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _drag_move(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _nb(self, icon, tip):
        b = QPushButton(icon); b.setToolTip(tip)
        b.setFixedSize(28,28)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setStyleSheet(BTN_NAV); return b

    # ── Posicionamiento flotante ───────────────────────────────────────────────
    def _reposition(self):
        W = self.width()
        H = self.height()
        
        # Calcular ancho responsive (82% del total, min 450, max 900)
        cw = max(450, min(900, int(W * 0.82)))
        self._chrome.setFixedWidth(cw)
        
        # barra centrada
        if self._bar_open:
            self._chrome.move((W - cw)//2, 10)
        else:
            self._chrome.move((W - cw)//2, -self.TOTAL - 20)
        
        self._chrome.raise_()
        self._check_responsive(cw)

        # notch centrado (y=1 para respetar el borde de la ventana de 1px)
        self._notch.move((W - self._notch.width())//2, 1)
        self._notch.raise_()

        # fav panel
        fw = self._fav_panel.width()
        if self._fav_open:
            self._fav_panel.setGeometry(W - fw, 0, fw, H)
        else:
            self._fav_panel.setGeometry(W, 0, fw, H)
        self._fav_panel.raise_()
        
        # hist panel
        hw = self._hist_panel.width()
        if hasattr(self, '_hist_open'):
            if self._hist_open:
                self._hist_panel.setGeometry(0, 0, hw, H)
            else:
                self._hist_panel.setGeometry(-hw, 0, hw, H)
            self._hist_panel.raise_()
            
        # controles ventana top-right
        self._win_ctrl.adjustSize()
        self._win_ctrl.move(W - self._win_ctrl.width() - 4, 4)
        self._win_ctrl.raise_()

    def _check_responsive(self, width):
        """Oculta elementos secundarios si el espacio es reducido."""
        is_small = width < 680
        is_tiny = width < 520
        
        # Ocultar controles de zoom en pantallas pequeñas
        for w in [self._zoom_in, self._zoom_out, self._zoom_lbl]:
            w.setVisible(not is_small)
            
        # Ocultar botones secundarios en pantallas muy pequeñas
        self._fav.setVisible(not is_small)
        self._rld.setVisible(not is_tiny)
        self._fwd.setVisible(not is_tiny)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reposition()
        self._layout_grips()
        self._update_corners()

    # ── Redimensionamiento ────────────────────────────────────────────────────
    def _build_resize_grips(self, parent):
        # 4 widgets invisibles en los bordes
        self._grips = {}
        for edge, cur in [("top", Qt.CursorShape.SizeVerCursor),
                          ("bottom", Qt.CursorShape.SizeVerCursor),
                          ("left", Qt.CursorShape.SizeHorCursor),
                          ("right", Qt.CursorShape.SizeHorCursor)]:
            w = QWidget(parent)
            w.setCursor(QCursor(cur))
            w.setStyleSheet("background:transparent;")
            
            # Eventos
            w.mousePressEvent = lambda e, edge=edge: self._grip_press(e, edge)
            w.mouseMoveEvent = self._grip_move
            w.mouseReleaseEvent = self._grip_release
            self._grips[edge] = w
            
        self._grip_active = None
        self._grip_start_pos = None
        self._grip_start_geom = None

    def _layout_grips(self):
        T = 5 # grosor
        W, H = self.width(), self.height()
        if hasattr(self, '_grips'):
            self._grips["top"].setGeometry(0, 0, W, T)
            self._grips["bottom"].setGeometry(0, H-T, W, T)
            self._grips["left"].setGeometry(0, 0, T, H)
            self._grips["right"].setGeometry(W-T, 0, T, H)
            for w in self._grips.values():
                w.raise_()

    def _grip_press(self, e, edge):
        if e.button() == Qt.MouseButton.LeftButton:
            self._grip_active = edge
            self._grip_start_pos = e.globalPosition().toPoint()
            self._grip_start_geom = self.frameGeometry()

    def _grip_move(self, e):
        if self._grip_active and self._grip_start_pos:
            dp = e.globalPosition().toPoint() - self._grip_start_pos
            g = QRect(self._grip_start_geom)
            
            if self._grip_active == "right":
                g.setRight(max(g.left() + 400, g.right() + dp.x()))
            elif self._grip_active == "bottom":
                g.setBottom(max(g.top() + 300, g.bottom() + dp.y()))
            elif self._grip_active == "left":
                g.setLeft(min(g.right() - 400, g.left() + dp.x()))
            elif self._grip_active == "top":
                g.setTop(min(g.bottom() - 300, g.top() + dp.y()))
                
            self.setGeometry(g)

    def _grip_release(self, e):
        self._grip_active = None

    # ── Mostrar / Ocultar barra ───────────────────────────────────────────────
    def _show_bar(self):
        self._bar_open = True
        self._notch.hide()
        self._win_ctrl.show()
        self._anim.stop()
        self._anim.setStartValue(self._chrome.pos())
        self._anim.setEndValue(QPoint((self.width() - self._chrome.width())//2, 10))
        self._anim.start()

    def _hide_bar(self):
        self._bar_open = False
        self._win_ctrl.hide()
        self._anim.stop()
        self._anim.setStartValue(self._chrome.pos())
        self._anim.setEndValue(QPoint((self.width() - self._chrome.width())//2, -self.TOTAL - 20))
        self._anim.finished.connect(self._after_hide)
        self._anim.start()

    def _after_hide(self):
        self._anim.finished.disconnect(self._after_hide)
        self._notch.show()
        self._notch.raise_()

    # ── Panel de Favoritos ────────────────────────────────────────────────────
    def _build_fav_panel(self, parent):
        self._fav_open = False
        frame = QFrame(parent)
        frame.setFixedWidth(280)
        
        self._fav_timer = QTimer(frame)
        self._fav_timer.setSingleShot(True)
        self._fav_timer.timeout.connect(lambda: self._toggle_fav_panel() if self._fav_open else None)
        frame.enterEvent = lambda e: self._fav_timer.stop()
        frame.leaveEvent = lambda e: self._fav_timer.start(2000)
        
        frame.setStyleSheet("""
            QFrame{background:rgba(12, 18, 35, 0.98);
              border-left:1px solid rgba(81,162,255,0.25);}
            QListWidget{background:transparent; border:none; outline:none; padding-right:0px;}
            QListWidget::item{border-bottom:1px solid rgba(81,162,255,0.06);}
            QListWidget::item:hover{background:rgba(81,162,255,0.08);}
            QScrollBar:vertical{background:transparent; width:3px; margin:0;}
            QScrollBar::handle:vertical{background:rgba(81,162,255,0.25); border-radius:1px; min-height:20px;}
            QScrollBar::handle:vertical:hover{background:rgba(81,162,255,0.5);}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0;}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{background:transparent;}
        """)
        _shadow(frame, blur=40, dy=0, alpha=150)
        
        v = QVBoxLayout(frame)
        v.setContentsMargins(0, 0, 0, 10)
        v.setSpacing(0)
        
        # Encabezado con gradiente azul
        hdr = QWidget()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(41,122,215,0.6), stop:1 rgba(81,162,255,0.3)); border:none;")
        hdr_l = QHBoxLayout(hdr); hdr_l.setContentsMargins(15,0,15,0)
        t = QLabel("\u2605  Tus Favoritos")
        t.setStyleSheet("font-size:13px; font-weight:bold; color:rgba(255,255,255,0.9); background:transparent;")
        hdr_l.addWidget(t)
        v.addWidget(hdr)
        
        self._fav_list = QListWidget()
        self._fav_list.setContentsMargins(10, 5, 5, 5)
        v.addWidget(self._fav_list)
        
        self._fav_anim = QPropertyAnimation(frame, b"pos")
        self._fav_anim.setDuration(300)
        self._fav_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        return frame

    def _toggle_fav_panel(self):
        W = self.width()
        fw = self._fav_panel.width()
        self._fav_anim.stop()
        self._fav_anim.setStartValue(self._fav_panel.pos())
        if not self._fav_open:
            self._refresh_favs()
            self._fav_anim.setEndValue(QPoint(W - fw, 0))
            self._fav_open = True
            self._fav_timer.start(2000)
            if hasattr(self, '_hist_open') and self._hist_open: self._toggle_hist_panel()
        else:
            self._fav_anim.setEndValue(QPoint(W, 0))
            self._fav_open = False
            self._fav_timer.stop()
        self._fav_anim.start()

    def _refresh_favs(self):
        self._fav_list.clear()
        for fid, title, url in get_favs():
            it = QListWidgetItem()
            self._fav_list.addItem(it)
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(5,5,5,5)
            
            l = QLabel(title[:25] + ("…" if len(title)>25 else ""))
            l.setStyleSheet("color:#e0e0e0; font-size:12px; background:transparent;")
            l.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            l.mousePressEvent = lambda e, u=url: (self.new_tab(u), self._toggle_fav_panel())
            
            b = QPushButton("✕")
            b.setFixedSize(20,20)
            b.setStyleSheet("background:transparent; color:#ff5f57; border:none; font-size:12px;")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _, f=fid: self._ask_del_fav(f))
            
            h.addWidget(l, 1)
            h.addWidget(b)
            it.setSizeHint(w.sizeHint())
            self._fav_list.setItemWidget(it, w)

    def _ask_del_fav(self, fid):
        d = QDialog(self)
        d.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        d.setStyleSheet("QDialog{background:#11111a; border:1px solid rgba(255,255,255,0.1); border-radius:12px;}")
        v = QVBoxLayout(d)
        v.setContentsMargins(20,20,20,20)
        v.addWidget(QLabel("<b style='color:white; font-size:14px;'>¿Borrar favorito?</b>"))
        v.addWidget(QLabel("<span style='color:#aaa; font-size:12px;'>Esta acción no se puede deshacer.</span>"))
        h = QHBoxLayout()
        bc = QPushButton("Cancelar"); bc.setStyleSheet(BTN_NAV); bc.clicked.connect(d.reject)
        ba = QPushButton("Borrar"); ba.setStyleSheet(BTN_NAV + "color:#ff5f57;"); ba.clicked.connect(d.accept)
        h.addWidget(bc); h.addWidget(ba)
        v.addLayout(h)
        if d.exec() == QDialog.DialogCode.Accepted:
            del_fav(fid)
            self._refresh_favs()

    # ── Panel de Historial y Datos ────────────────────────────────────────────
    def _build_hist_panel(self, parent):
        self._hist_open = False
        frame = QFrame(parent)
        frame.setFixedWidth(290)
        
        self._hist_timer = QTimer(frame)
        self._hist_timer.setSingleShot(True)
        self._hist_timer.timeout.connect(lambda: self._toggle_hist_panel() if self._hist_open else None)
        frame.enterEvent = lambda e: self._hist_timer.stop()
        frame.leaveEvent = lambda e: self._hist_timer.start(2000)
        
        frame.setStyleSheet("""
            QFrame{background:rgba(12, 18, 35, 0.98); border-right:1px solid rgba(81,162,255,0.25);}
            QListWidget{background:transparent; border:none; outline:none; padding-left:0px;}
            QListWidget::item{border-bottom:1px solid rgba(81,162,255,0.06);}
            QListWidget::item:hover{background:rgba(81,162,255,0.08);}
            QScrollBar:vertical{background:transparent; width:3px; margin:0;}
            QScrollBar::handle:vertical{background:rgba(81,162,255,0.25); border-radius:1px; min-height:20px;}
            QScrollBar::handle:vertical:hover{background:rgba(81,162,255,0.5);}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0;}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{background:transparent;}
        """)
        _shadow(frame, blur=40, dy=0, alpha=150)
        
        v = QVBoxLayout(frame)
        v.setContentsMargins(0, 0, 0, 10)
        v.setSpacing(0)
        
        # Encabezado con gradiente azul
        hdr = QWidget()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(81,162,255,0.3), stop:1 rgba(41,122,215,0.6)); border:none;")
        hdr_l = QHBoxLayout(hdr); hdr_l.setContentsMargins(15,0,15,0)
        t = QLabel("\u25f7  Historial")
        t.setStyleSheet("font-size:13px; font-weight:bold; color:rgba(255,255,255,0.9); background:transparent;")
        hdr_l.addWidget(t)
        v.addWidget(hdr)
        
        PANEL_BTN = """QPushButton{font-size:11px; background:rgba(41,122,215,0.2);
            border:1px solid rgba(81,162,255,0.2); border-radius:4px;
            color:rgba(255,255,255,0.7); padding:3px 8px;}
            QPushButton:hover{background:rgba(41,122,215,0.4); color:white;
            border-color:rgba(81,162,255,0.4);}"""
        
        h_btns = QHBoxLayout()
        h_btns.setContentsMargins(10, 4, 10, 4)
        btn_clr_hist = QPushButton("Limpiar Historial")
        btn_clr_hist.setToolTip("Eliminar todo el historial de navegaci\u00f3n")
        btn_clr_hist.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_clr_hist.setStyleSheet(PANEL_BTN)
        btn_clr_hist.clicked.connect(self._clear_hist)
        
        btn_clr_cache = QPushButton("Limpiar Cach\u00e9")
        btn_clr_cache.setToolTip("Vaciar cach\u00e9, cookies y datos de formularios")
        btn_clr_cache.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_clr_cache.setStyleSheet(PANEL_BTN)
        btn_clr_cache.clicked.connect(self._clear_cache)
        
        h_btns.addWidget(btn_clr_hist)
        h_btns.addWidget(btn_clr_cache)
        v.addLayout(h_btns)
        
        self._hist_list = QListWidget()
        self._hist_list.setContentsMargins(5, 5, 10, 5)
        v.addWidget(self._hist_list)
        
        self._hist_anim = QPropertyAnimation(frame, b"pos")
        self._hist_anim.setDuration(300)
        self._hist_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        return frame

    def _toggle_hist_panel(self):
        hw = self._hist_panel.width()
        self._hist_anim.stop()
        self._hist_anim.setStartValue(self._hist_panel.pos())
        if not self._hist_open:
            self._refresh_hist()
            self._hist_anim.setEndValue(QPoint(0, 0))
            self._hist_open = True
            self._hist_timer.start(2000)
            if self._fav_open: self._toggle_fav_panel() # cerrar favoritos si estaba abierto
        else:
            self._hist_anim.setEndValue(QPoint(-hw, 0))
            self._hist_open = False
            self._hist_timer.stop()
        self._hist_anim.start()

    def _refresh_hist(self):
        self._hist_list.clear()
        for hid, title, url, visits in get_history():
            it = QListWidgetItem()
            self._hist_list.addItem(it)
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(5,5,5,5)
            h.setSpacing(4)
            
            d_title = title if title else url
            display_text = d_title[:28] + ("…" if len(d_title)>28 else "")
            if visits > 1:
                display_text += f" <span style='color:rgba(81,162,255,0.5); font-size:9px;'>({visits})</span>"
            
            l = QLabel(display_text)
            l.setStyleSheet("color:#e0e0e0; font-size:12px; background:transparent;")
            l.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            l.setToolTip(f"{url}\nClick para detalles" if visits > 1 else url)
            
            if visits > 1:
                l.mousePressEvent = lambda e, u=url: self._show_hist_details(u)
            else:
                l.mousePressEvent = lambda e, u=url: (self.new_tab(u), self._toggle_hist_panel())
            
            b = QPushButton("✕")
            b.setFixedSize(20,20)
            b.setStyleSheet("background:transparent; color:#ff5f57; border:none; font-size:12px;")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _, hi=hid: self._del_hist_item(hi))
            
            h.addWidget(l, 1)
            h.addWidget(b)
            it.setSizeHint(w.sizeHint())
            self._hist_list.setItemWidget(it, w)

    def _show_hist_details(self, url):
        d = QDialog(self)
        d.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        d.setStyleSheet("""
            QDialog{background:rgba(12, 18, 35, 0.98); border:1px solid rgba(81,162,255,0.4); border-radius:14px;}
            QListWidget{background:transparent; border:none; outline:none;}
            QScrollBar:vertical{background:transparent; width:3px; margin:0;}
            QScrollBar::handle:vertical{background:rgba(81,162,255,0.25); border-radius:1px; min-height:20px;}
            QScrollBar::handle:vertical:hover{background:rgba(81,162,255,0.5);}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0;}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{background:transparent;}
        """)
        v = QVBoxLayout(d); v.setContentsMargins(20,20,20,20); v.setSpacing(10)
        
        t = QLabel("\u25f7  Historial de Visitas")
        t.setStyleSheet("color:#81a2ff; font-size:16px; font-weight:bold;")
        v.addWidget(t)
        
        url_l = QLabel(url)
        url_l.setWordWrap(True)
        url_l.setStyleSheet("color:rgba(255,255,255,0.3); font-size:10px; margin-bottom:5px;")
        v.addWidget(url_l)
        
        lst = QListWidget()
        lst.setSpacing(2)
        v.addWidget(lst)
        
        for hid, title, ts in get_url_history(url):
            it = QListWidgetItem()
            lst.addItem(it)
            
            item_w = QWidget()
            item_h = QHBoxLayout(item_w); item_h.setContentsMargins(10,8,10,8); item_h.setSpacing(12)
            
            time_lbl = QLabel(ts[11:16])
            time_lbl.setStyleSheet("color:#81a2ff; font-weight:bold; font-size:11px;")
            
            title_lbl = QLabel(title if title else "Sin título")
            title_lbl.setStyleSheet("color:#e0e0e0; font-size:12px;")
            
            item_h.addWidget(time_lbl)
            item_h.addWidget(title_lbl, 1)
            
            item_w.setStyleSheet("QWidget:hover{background:rgba(81,162,255,0.1); border-radius:6px;}")
            
            it.setSizeHint(item_w.sizeHint())
            lst.setItemWidget(it, item_w)
        
        lst.itemClicked.connect(lambda: (self.new_tab(url), self._toggle_hist_panel(), d.accept()))
        
        bc = QPushButton("Cerrar")
        bc.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        bc.setFixedHeight(32)
        bc.setStyleSheet("""
            QPushButton{background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); 
              border-radius:6px; color:#aaa; font-size:12px;}
            QPushButton:hover{background:rgba(255,255,255,0.1); color:white; border-color:rgba(255,255,255,0.2);}
        """)
        bc.clicked.connect(d.reject)
        v.addWidget(bc)
        
        d.setFixedWidth(380)
        d.setFixedHeight(450)
        d.exec()

    def _del_hist_item(self, hid):
        del_history(hid)
        self._refresh_hist()

    def _clear_hist(self):
        d = QDialog(self)
        d.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        d.setStyleSheet(
            """
            QDialog{background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(14,20,36,0.98), stop:1 rgba(17,17,26,0.98));
                    border:1px solid rgba(81,162,255,0.32); border-radius:14px;}
            QLabel{background:transparent; color:#d7def5;}
            """
        )
        v = QVBoxLayout(d); v.setContentsMargins(20,20,20,20); v.setSpacing(10)
        v.addWidget(QLabel("<b style='color:#ffffff; font-size:15px;'>🗑️ Limpiar Historial</b>"))
        v.addWidget(QLabel("<span style='color:rgba(220,230,255,0.75); font-size:12px;'>Elige cómo quieres borrar registros de navegación.</span>"))

        body = QFrame()
        body.setStyleSheet("QFrame{background:rgba(81,162,255,0.08); border:1px solid rgba(81,162,255,0.2); border-radius:10px;}")
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(12,12,12,12)
        body_l.setSpacing(8)
        body_l.addWidget(QLabel("<span style='color:#81a2ff; font-size:11px; letter-spacing:0.4px;'>Opciones disponibles</span>"))
        body_l.addWidget(QLabel("<span style='color:#cfd8f6; font-size:12px;'>• Por dominio\n• Por rango de fechas\n• Borrado completo</span>"))
        v.addWidget(body)

        action = {'value': 'cancel'}
        h = QHBoxLayout()
        h.setSpacing(8)

        BTN_NEUTRAL = "QPushButton{background:rgba(108,117,125,0.30); border:1px solid rgba(198,204,214,0.45); border-radius:8px; color:#f0f4ff; padding:8px 12px; font-size:12px; font-weight:600;} QPushButton:hover{background:rgba(108,117,125,0.45); color:white;}"
        BTN_INFO = "QPushButton{background:rgba(25,118,210,0.40); border:1px solid rgba(127,190,255,0.70); border-radius:8px; color:#e6f4ff; padding:8px 12px; font-size:12px; font-weight:600;} QPushButton:hover{background:rgba(25,118,210,0.55); color:white;}"
        BTN_MAGIC = "QPushButton{background:rgba(123,31,162,0.42); border:1px solid rgba(216,165,255,0.72); border-radius:8px; color:#f3e5ff; padding:8px 12px; font-size:12px; font-weight:600;} QPushButton:hover{background:rgba(123,31,162,0.58); color:white;}"
        BTN_DANGER = "QPushButton{background:rgba(198,40,40,0.42); border:1px solid rgba(255,166,166,0.72); border-radius:8px; color:#ffe6e6; padding:8px 12px; font-size:12px; font-weight:700;} QPushButton:hover{background:rgba(198,40,40,0.58); color:white;}"

        bc = QPushButton("↩ Cancelar")
        bc.setStyleSheet(BTN_NEUTRAL)
        bc.clicked.connect(lambda: (action.__setitem__('value', 'cancel'), d.accept()))

        bd = QPushButton("🌐 Por dominio")
        bd.setStyleSheet(BTN_INFO)
        bd.clicked.connect(lambda: (action.__setitem__('value', 'domain'), d.accept()))

        bf = QPushButton("📅 Por fechas")
        bf.setStyleSheet(BTN_MAGIC)
        bf.clicked.connect(lambda: (action.__setitem__('value', 'dates'), d.accept()))

        ba = QPushButton("🗑 Borrar todo")
        ba.setStyleSheet(BTN_DANGER)
        ba.clicked.connect(lambda: (action.__setitem__('value', 'all'), d.accept()))

        h.addWidget(bc); h.addWidget(bd); h.addWidget(bf); h.addWidget(ba)
        v.addLayout(h)

        if d.exec() != QDialog.DialogCode.Accepted:
            return

        if action['value'] == 'domain':
            self._clear_hist_by_domain_dialog()
            return
        if action['value'] == 'dates':
            self._clear_hist_by_dates_dialog()
            return
        if action['value'] != 'all':
            return

        clear_history()
        self._refresh_hist()
        Notif("Historial", "Historial de navegación limpiado.", self.centralWidget())

    def _clear_hist_by_domain_dialog(self):
        d = QDialog(self)
        d.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        d.setStyleSheet(
            """
            QDialog{background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(14,20,36,0.98), stop:1 rgba(17,17,26,0.98));
                    border:1px solid rgba(81,162,255,0.3); border-radius:14px;}
            QLabel{color:#d7def5; background:transparent;}
            """
        )

        v = QVBoxLayout(d)
        v.setContentsMargins(20,20,20,20)
        v.setSpacing(10)

        v.addWidget(QLabel("<b style='color:#ffffff; font-size:15px;'>🌐 Borrar Historial por Dominio</b>"))
        v.addWidget(QLabel("<span style='color:rgba(220,230,255,0.75); font-size:12px;'>Ejemplo: google.com o perplexity.ai</span>"))

        inp = QLineEdit()
        inp.setPlaceholderText("dominio.com")
        inp.setStyleSheet("background:rgba(255,255,255,0.07); border:1px solid rgba(81,162,255,0.35); border-radius:9px; color:white; padding:9px;")

        cur = self._cur()
        if cur:
            host = (cur.url().host() or '').lower()
            if host.startswith('www.'):
                host = host[4:]
            inp.setText(host)

        v.addWidget(inp)

        h = QHBoxLayout()
        h.setSpacing(8)
        bc = QPushButton("Cancelar"); bc.setStyleSheet("QPushButton{background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.12); border-radius:8px; color:#d5d9e8; padding:8px 12px; font-size:12px;} QPushButton:hover{background:rgba(255,255,255,0.14); color:white;}"); bc.clicked.connect(d.reject)
        ba = QPushButton("Borrar dominio"); ba.setStyleSheet("QPushButton{background:rgba(255,95,87,0.14); border:1px solid rgba(255,95,87,0.36); border-radius:8px; color:#ffb3ae; padding:8px 12px; font-size:12px;} QPushButton:hover{background:rgba(255,95,87,0.26); color:white;}"); ba.clicked.connect(d.accept)
        h.addWidget(bc); h.addWidget(ba)
        v.addLayout(h)

        if d.exec() != QDialog.DialogCode.Accepted:
            return

        removed = clear_history_by_domain(inp.text())
        self._refresh_hist()
        if removed > 0:
            Notif("Historial", f"Registros eliminados del dominio: {removed}", self.centralWidget())
        else:
            Notif("Historial", "No se encontraron registros para ese dominio.", self.centralWidget())

    def _clear_hist_by_dates_dialog(self):
        d = QDialog(self)
        d.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        d.setStyleSheet(
            """
            QDialog{background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(14,20,36,0.98), stop:1 rgba(17,17,26,0.98));
                    border:1px solid rgba(155,89,182,0.35); border-radius:14px;}
            QLabel{color:#d7def5; background:transparent;}
            QDateEdit{background:rgba(255,255,255,0.07); border:1px solid rgba(155,89,182,0.4); border-radius:9px; color:white; padding:8px;}
            QDateEdit::drop-down{subcontrol-origin:padding; subcontrol-position:top right; width:20px; border-left:1px solid rgba(255,255,255,0.15);}
            QCalendarWidget QWidget{background:#141825; color:#d7def5;}
            QCalendarWidget QToolButton{background:rgba(155,89,182,0.2); color:#e7d3ff; border:none; border-radius:6px; padding:4px 8px;}
            QCalendarWidget QAbstractItemView:enabled{selection-background-color:rgba(155,89,182,0.35); selection-color:white;}
            """
        )

        v = QVBoxLayout(d)
        v.setContentsMargins(20,20,20,20)
        v.setSpacing(10)

        v.addWidget(QLabel("<b style='color:#ffffff; font-size:15px;'>📅 Borrar Historial por Fechas</b>"))
        v.addWidget(QLabel("<span style='color:rgba(220,230,255,0.75); font-size:12px;'>Selecciona el rango a limpiar.</span>"))

        start_lbl = QLabel("Desde")
        start_lbl.setStyleSheet("color:#caa8f0; font-size:11px; font-weight:600;")
        today = QDate.currentDate()
        start_inp = QDateEdit()
        start_inp.setCalendarPopup(True)
        start_inp.setDisplayFormat("yyyy-MM-dd")
        start_inp.setDate(today.addDays(-6))
        start_inp.setMinimumHeight(34)

        end_lbl = QLabel("Hasta")
        end_lbl.setStyleSheet("color:#caa8f0; font-size:11px; font-weight:600;")
        end_inp = QDateEdit()
        end_inp.setCalendarPopup(True)
        end_inp.setDisplayFormat("yyyy-MM-dd")
        end_inp.setDate(today)
        end_inp.setMinimumHeight(34)

        v.addWidget(start_lbl)
        v.addWidget(start_inp)
        v.addWidget(end_lbl)
        v.addWidget(end_inp)

        h = QHBoxLayout()
        h.setSpacing(8)
        bc = QPushButton("Cancelar"); bc.setStyleSheet("QPushButton{background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.12); border-radius:8px; color:#d5d9e8; padding:8px 12px; font-size:12px;} QPushButton:hover{background:rgba(255,255,255,0.14); color:white;}"); bc.clicked.connect(d.reject)
        ba = QPushButton("Borrar rango"); ba.setStyleSheet("QPushButton{background:rgba(255,95,87,0.14); border:1px solid rgba(255,95,87,0.36); border-radius:8px; color:#ffb3ae; padding:8px 12px; font-size:12px;} QPushButton:hover{background:rgba(255,95,87,0.26); color:white;}"); ba.clicked.connect(d.accept)
        h.addWidget(bc); h.addWidget(ba)
        v.addLayout(h)

        if d.exec() != QDialog.DialogCode.Accepted:
            return

        start = start_inp.date().toString("yyyy-MM-dd")
        end = end_inp.date().toString("yyyy-MM-dd")

        if end < start:
            Notif("Historial", "La fecha final no puede ser menor que la inicial.", self.centralWidget())
            return

        removed = clear_history_by_dates(start, end)
        self._refresh_hist()
        if removed > 0:
            Notif("Historial", f"Registros eliminados por fecha: {removed}", self.centralWidget())
        else:
            Notif("Historial", "No se encontraron registros en ese rango.", self.centralWidget())

    def _clear_cache(self):
        d = QDialog(self)
        d.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        d.setStyleSheet(
            """
            QDialog{background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(14,20,36,0.98), stop:1 rgba(17,17,26,0.98));
                    border:1px solid rgba(81,162,255,0.32); border-radius:14px;}
            QLabel{background:transparent; color:#d7def5;}
            """
        )
        v = QVBoxLayout(d); v.setContentsMargins(20,20,20,20); v.setSpacing(10)
        v.addWidget(QLabel("<b style='color:#ffffff; font-size:15px;'>🧹 Limpiar Caché y Datos</b>"))
        v.addWidget(QLabel("<span style='color:rgba(220,230,255,0.75); font-size:12px;'>Elige si quieres limpiar solo el sitio activo o todo el navegador.</span>"))

        cur_host = ""
        cur_view = self._cur()
        if cur_view:
            cur_host = (cur_view.url().host() or "").lower()
        if cur_host:
            host_chip = QLabel(f"<span style='color:#81a2ff; font-size:11px; font-weight:600;'>Sitio actual: {cur_host}</span>")
            host_chip.setStyleSheet("QLabel{background:rgba(81,162,255,0.10); border:1px solid rgba(81,162,255,0.26); border-radius:8px; padding:6px 8px;}")
            v.addWidget(host_chip)

        action = {"value": "cancel"}
        h = QHBoxLayout()
        h.setSpacing(8)

        bc = QPushButton("↩ Cancelar")
        bc.setStyleSheet("QPushButton{background:rgba(108,117,125,0.30); border:1px solid rgba(198,204,214,0.45); border-radius:8px; color:#f0f4ff; padding:8px 12px; font-size:12px; font-weight:600;} QPushButton:hover{background:rgba(108,117,125,0.45); color:white;}")
        bc.clicked.connect(lambda: (action.__setitem__("value", "cancel"), d.accept()))

        bs = QPushButton("🌐 Limpiar sitio actual")
        bs.setStyleSheet("QPushButton{background:rgba(25,118,210,0.40); border:1px solid rgba(127,190,255,0.70); border-radius:8px; color:#e6f4ff; padding:8px 12px; font-size:12px; font-weight:600;} QPushButton:hover{background:rgba(25,118,210,0.55); color:white;}")
        bs.clicked.connect(lambda: (action.__setitem__("value", "site"), d.accept()))

        ba = QPushButton("🧹 Limpiar todo")
        ba.setStyleSheet("QPushButton{background:rgba(198,40,40,0.42); border:1px solid rgba(255,166,166,0.72); border-radius:8px; color:#ffe6e6; padding:8px 12px; font-size:12px; font-weight:700;} QPushButton:hover{background:rgba(198,40,40,0.58); color:white;}")
        ba.clicked.connect(lambda: (action.__setitem__("value", "all"), d.accept()))

        h.addWidget(bc); h.addWidget(bs); h.addWidget(ba)
        v.addLayout(h)

        if d.exec() == QDialog.DialogCode.Accepted:
            if action["value"] == "site":
                self._clear_current_site_data()
                return
            if action["value"] != "all":
                return
            profile().clearHttpCache()
            profile().clearAllVisitedLinks()
            profile().cookieStore().deleteAllCookies()
            Notif("Caché y Datos", "Se ha vaciado el caché y formularios.", self.centralWidget())

    def _clear_current_site_data(self):
        view = self._cur()
        if not view:
            Notif("Caché y Datos", "No hay una pestaña activa para limpiar.", self.centralWidget())
            return

        qurl = view.url()
        if qurl.scheme() not in ("http", "https"):
            Notif("Caché y Datos", "El sitio actual no usa un dominio web válido.", self.centralWidget())
            return

        host = (qurl.host() or "").lower().lstrip('.')
        if not host:
            Notif("Caché y Datos", "No se pudo determinar el dominio actual.", self.centralWidget())
            return

        store = profile().cookieStore()
        origin = QUrl(f"https://{host}")
        deleted = {"count": 0}

        def on_cookie(cookie):
            domain = (cookie.domain() or "").lower().lstrip('.')
            if not domain:
                return

            matches = (
                host == domain or
                host.endswith('.' + domain) or
                domain.endswith('.' + host)
            )
            if not matches:
                return

            try:
                store.deleteCookie(cookie, origin)
            except TypeError:
                store.deleteCookie(cookie)
            deleted["count"] += 1

        def finalize():
            try:
                store.cookieAdded.disconnect(on_cookie)
            except Exception:
                pass

            # Limpia storage del origen actual dentro de la pestaña activa.
            clear_js = """
                (async () => {
                    try { localStorage.clear(); } catch (e) {}
                    try { sessionStorage.clear(); } catch (e) {}
                    try {
                        if (window.caches && caches.keys) {
                            const keys = await caches.keys();
                            await Promise.all(keys.map((k) => caches.delete(k)));
                        }
                    } catch (e) {}
                    try {
                        if (window.indexedDB && indexedDB.databases) {
                            const dbs = await indexedDB.databases();
                            for (const db of dbs || []) {
                                if (db && db.name) indexedDB.deleteDatabase(db.name);
                            }
                        }
                    } catch (e) {}
                    return true;
                })();
            """
            view.page().runJavaScript(clear_js)
            view.reload()
            Notif("Caché y Datos", f"Sitio limpiado: {host} (cookies: {deleted['count']}).", self.centralWidget())

        store.cookieAdded.connect(on_cookie)
        store.loadAllCookies()
        QTimer.singleShot(600, finalize)

    # ── Pestañas ─────────────────────────────────────────────────────────────
    def new_tab(self, url=HOME):
        view = WebView(self, url)
        view.hide()
        # Aplicar zoom persistido
        saved_zoom = load_settings().get("zoom", 1.0)
        view.setZoomFactor(saved_zoom)
        view.titleChanged.connect(lambda t, v=view: self._on_title(v, t))
        view.urlChanged.connect(lambda u, v=view: self._on_url(v, u))
        view.iconChanged.connect(lambda i, v=view: self._on_icon(v, i))
        view.loadStarted.connect(lambda v=view: self._start_loading(v))
        view.loadFinished.connect(lambda ok, v=view: self._stop_loading(v))
        self._web_layout.addWidget(view)
        self._views.append(view)

        idx = len(self._views) - 1
        btn = self._make_tab_btn("Nueva pestaña", idx)
        self._tab_btns.append(btn)
        self._tabs_layout.addWidget(btn)
        self._switch(idx)
        return view

    # ── Spinner de carga ────────────────────────────────────────────────
    # Estilos como constantes de módulo para evitar llaves dobles
    _GO_IDLE_SS = (
        "QPushButton{background:rgba(255,255,255,0.2);border:none;border-radius:14px;"
        "color:white;font-size:14px;}"
        "QPushButton:hover{background:rgba(255,255,255,0.35);}"
    )
    _GO_LOADING_SS = (
        "QPushButton{background:rgba(0,0,0,0.45);border:none;border-radius:14px;"
        "color:white;font-size:12px;}"
        "QPushButton:hover{background:rgba(0,0,0,0.65);}"
    )
    # Arcos que rotan en sentido horario
    _SPIN_FRAMES = ["◜", "◝", "◞", "◟"]

    def _go_clicked(self):
        """Ir a URL o cancelar carga según estado."""
        if self._loading_count > 0:
            self._cancel_loading()
        else:
            self._navigate()

    def _cancel_loading(self):
        v = self._cur()
        if v:
            v.stop()
        # _stop_loading se disparará via loadFinished, pero forzamos reset inmediato
        self._loading_count = 0
        self._spin_timer.stop()
        self._go.setText("⊙")
        self._go.setToolTip("Ir")
        self._go.setStyleSheet(self._GO_IDLE_SS)
        self._go.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def _start_loading(self, view):
        self._loading_count += 1
        if self._loading_count == 1:
            self._spin_idx = 0
            self._go.setToolTip("Cancelar carga")
            self._go.setStyleSheet(self._GO_LOADING_SS)
            self._go.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._spin_timer.start()

    def _stop_loading(self, view):
        self._loading_count = max(0, self._loading_count - 1)
        if self._loading_count == 0:
            self._spin_timer.stop()
            self._go.setText("⊙")
            self._go.setToolTip("Ir")
            self._go.setStyleSheet(self._GO_IDLE_SS)
            self._go.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def _spin_tick(self):
        self._go.setText(self._SPIN_FRAMES[self._spin_idx % len(self._SPIN_FRAMES)])
        self._spin_idx += 1

    def _make_tab_btn(self, title, idx):
        w = QWidget()
        w.setMaximumWidth(180)
        h = QHBoxLayout(w); h.setContentsMargins(8,0,4,0); h.setSpacing(4)
        w.setFixedHeight(24)
        w.setStyleSheet("""QWidget{background:rgba(255,255,255,.05);
            border-radius:8px;border:1px solid rgba(255,255,255,.08);}
            QWidget:hover{background:rgba(255,255,255,.08);}""")

        lbl = QLabel(title[:20])
        lbl.setStyleSheet("color:#b0b0b0;font-size:12px;background:transparent;border:none;")
        lbl.setObjectName("tab_lbl")

        icon_lbl = QLabel()
        icon_lbl.setObjectName("tab_icon")
        icon_lbl.setFixedSize(14, 14)
        icon_lbl.setStyleSheet("background:transparent; border:none;")
        icon_lbl.hide()

        cls = QPushButton("✕"); cls.setFixedSize(14,14)
        cls.setStyleSheet("QPushButton{background:transparent;border:none;color:#555;font-size:9px;}"
                          "QPushButton:hover{color:#ff6b6b;}")
        cls.clicked.connect(lambda _, i=idx: self._close_tab_safe(i))

        w.mousePressEvent = lambda e, btn=w: self._switch(self._tab_btns.index(btn)) if btn in self._tab_btns else None
        h.addWidget(icon_lbl); h.addWidget(lbl, 1); h.addWidget(cls)
        return w

    def _switch(self, idx):
        self._active = idx
        self._web_layout.setCurrentIndex(idx)
        self._refresh_tab_styles()
        self._sync_url()
        self._update_zoom_label()

    def _refresh_tab_styles(self):
        for i, w in enumerate(self._tab_btns):
            active = i == self._active
            lbl = w.findChild(QLabel, "tab_lbl")
            
            if active:
                bg = "rgba(41, 122, 215, 0.96)" # Coincide con la parte inferior del gradiente de la barra
                col = "#ffffff"
                border_top = "none"
                border_bottom = "1px solid rgba(255, 255, 255, 0.2)"
                border_sides = "1px solid rgba(255, 255, 255, 0.2)"
                radius = "border-bottom-left-radius: 8px; border-bottom-right-radius: 8px; border-top-left-radius: 0px; border-top-right-radius: 0px;"
                hover_bg = "rgba(41, 122, 215, 0.96)"
            else:
                bg = "rgba(0, 0, 0, 0.15)"
                col = "rgba(255,255,255,0.6)"
                border_top = "none"
                border_bottom = "none"
                border_sides = "none"
                radius = "border-bottom-left-radius: 8px; border-bottom-right-radius: 8px; border-top-left-radius: 0px; border-top-right-radius: 0px;"
                hover_bg = "rgba(0, 0, 0, 0.25)"
                
            w.setStyleSheet(f"""
                QWidget{{background:{bg}; {radius}
                border-top:{border_top}; border-bottom:{border_bottom}; 
                border-left:{border_sides}; border-right:{border_sides};}}
                QWidget:hover{{background:{hover_bg};}}
            """)
            if lbl: lbl.setStyleSheet(f"color:{col};font-size:12px;background:transparent;border:none;")

    def _close_tab_safe(self, idx):
        if len(self._views) <= 1:
            self.new_tab(HOME)
        v = self._views.pop(idx)
        v.deleteLater()
        btn = self._tab_btns.pop(idx)
        self._tabs_layout.removeWidget(btn)
        btn.deleteLater()
        new_idx = min(idx, len(self._views)-1)
        # recablear índices de cierre
        for i, w in enumerate(self._tab_btns):
            cls = w.findChildren(QPushButton)
            if cls: cls[0].clicked.disconnect()
            if cls: cls[0].clicked.connect(lambda _, j=i: self._close_tab_safe(j))
        self._switch(new_idx)

    def _cur(self) -> WebView | None:
        return self._views[self._active] if 0 <= self._active < len(self._views) else None

    def _on_title(self, view, title):
        idx = self._views.index(view) if view in self._views else -1
        if idx >= 0 and idx < len(self._tab_btns):
            lbl = self._tab_btns[idx].findChild(QLabel, "tab_lbl")
            if lbl: lbl.setText(title[:20] + ("…" if len(title)>20 else ""))

    def _on_icon(self, view, icon):
        idx = self._views.index(view) if view in self._views else -1
        if idx >= 0 and idx < len(self._tab_btns):
            icon_lbl = self._tab_btns[idx].findChild(QLabel, "tab_icon")
            if icon_lbl:
                if view.url().toString().startswith("file://"):
                    icon_lbl.setPixmap(QIcon(os.path.join(BASE, "ui", "favicon.png")).pixmap(14, 14))
                    icon_lbl.show()
                elif not icon.isNull():
                    icon_lbl.setPixmap(icon.pixmap(14, 14))
                    icon_lbl.show()

    def _on_url(self, view, url):
        u = url.toString()
        if u.startswith("file://"):
            idx = self._views.index(view) if view in self._views else -1
            if idx >= 0 and idx < len(self._tab_btns):
                icon_lbl = self._tab_btns[idx].findChild(QLabel, "tab_icon")
                if icon_lbl:
                    icon_lbl.setPixmap(QIcon(os.path.join(BASE, "ui", "favicon.png")).pixmap(14, 14))
                    icon_lbl.show()
        
        if view == self._cur():
            immersive = ["arcade.html", "agenda.html", "videoplayer.html", "imageplayer.html", "screenshot_editor.html"]
            if any(tool in u for tool in immersive):
                if self._bar_open:
                    self._hide_bar()
            else:
                if not self._bar_open:
                    self._show_bar()

            self._url.setText("" if u.startswith("file://") else u)
            self._update_sec(u)

    def _sync_url(self):
        v = self._cur()
        if v:
            u = v.url().toString()
            immersive = ["arcade.html", "agenda.html", "videoplayer.html", "imageplayer.html", "screenshot_editor.html"]
            if any(tool in u for tool in immersive):
                if self._bar_open:
                    self._hide_bar()
            else:
                if not self._bar_open:
                    self._show_bar()
                    
            self._url.setText("" if u.startswith("file://") else u)
            self._update_sec(u)

    def _update_sec(self, url):
        base = "font-size:16px; background:transparent;"
        if url.startswith("file://"):
            self._sec.setText("🛡️"); self._sec.setStyleSheet(base)
            self._sec.setToolTip("Página local segura")
        elif url.startswith("https"):
            self._sec.setText("🔒"); self._sec.setStyleSheet(base + "color:#00b894;")
            self._sec.setToolTip("Conexión segura")
        elif url.startswith("http"):
            self._sec.setText("⚠"); self._sec.setStyleSheet(base + "color:#e17055;")
            self._sec.setToolTip("Conexión no segura")
        else:
            self._sec.setText("")

    # ── Navegación ────────────────────────────────────────────────────────────
    # ── Zoom ──────────────────────────────────────────────────────────────────
    def _update_zoom_label(self):
        v = self._cur()
        factor = v.zoomFactor() if v else 1.0
        self._zoom_lbl.setText(f"{int(factor * 100)}%")


    def _apply_zoom_all(self, factor):
        """Aplica el zoom a todas las pestañas abiertas y lo persiste."""
        for view in self._views:
            view.setZoomFactor(factor)
        save_settings({"zoom": factor})
        self._update_zoom_label()

    def _zoom_in_act(self):
        v = self._cur()
        if v:
            new_f = round(min(v.zoomFactor() + 0.1, 5.0), 2)
            self._apply_zoom_all(new_f)

    def _zoom_out_act(self):
        v = self._cur()
        if v:
            new_f = round(max(v.zoomFactor() - 0.1, 0.25), 2)
            self._apply_zoom_all(new_f)

    def _zoom_reset(self):
        self._apply_zoom_all(1.0)


    # ── Navegación ────────────────────────────────────────────────────────────────
    def _navigate(self):
        txt = self._url.text().strip()
        if not txt: return
        if txt.startswith("http"):   url = txt
        elif "." in txt and " " not in txt: url = "https://" + txt
        else: url = "https://www.google.com/search?q=" + txt.replace(" ","+")
        v = self._cur()
        if v: v.load(QUrl(url))

    def _go_back(self):
        v = self._cur()
        if v: v.back()

    def _go_fwd(self):
        v = self._cur()
        if v: v.forward()

    def _go_reload(self):
        v = self._cur()
        if v: v.reload()

    # ── Favoritos ─────────────────────────────────────────────────────────────
    def _save_fav(self):
        v = self._cur()
        if not v: return
        save_fav(v.title(), v.url().toString())
        self._fav.setText("★")
        self._fav.setStyleSheet(BTN_NAV + "color:#ffd700;")
        QTimer.singleShot(2500, lambda: (
            self._fav.setText("☆"),
            self._fav.setStyleSheet(BTN_NAV)))
        Notif("Favorito guardado ★", v.title()[:45], self.centralWidget())

    def _capture_screenshot(self):
        was_bar_open = self._bar_open
        if was_bar_open:
            self._hide_bar()
            QTimer.singleShot(320, lambda: self._capture_screenshot_impl(True))
            return

        self._capture_screenshot_impl(False)

    def _capture_screenshot_impl(self, restore_bar):
        v = self._cur()
        if not v:
            if restore_bar:
                self._show_bar()
            return

        pix = v.grab()
        if pix.isNull():
            Notif("Captura fallida", "No se pudo capturar la vista actual", self.centralWidget())
            if restore_bar:
                self._show_bar()
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        raw_path = os.path.join(get_screenshots_dir(), f"shot_{stamp}.png")
        if not pix.save(raw_path, "PNG"):
            Notif("Captura fallida", "No se pudo guardar la imagen", self.centralWidget())
            if restore_bar:
                self._show_bar()
            return

        save_screenshot(raw_path, v.url().toString())
        QApplication.clipboard().setPixmap(pix)

        editor_path = os.path.join(BASE, "ui", "screenshot_editor.html")
        editor_url = QUrl.fromLocalFile(editor_path)
        query = QUrlQuery()
        query.addQueryItem("img", raw_path)
        editor_url.setQuery(query)
        self.new_tab(editor_url.toString())

        Notif("Captura guardada", "Se copio al portapapeles y se abrio el editor", self.centralWidget())
        # Si se abre screenshot_editor, la barra debe permanecer oculta.

    # ── Atajos ────────────────────────────────────────────────────────────────
    def keyPressEvent(self, e):
        k, m = e.key(), e.modifiers()
        C = Qt.KeyboardModifier.ControlModifier
        CS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        if m == C and k == Qt.Key.Key_T:       self.new_tab(HOME)
        elif m == C and k == Qt.Key.Key_W:     self._close_tab_safe(self._active)
        elif m == CS and k == Qt.Key.Key_S:    self._capture_screenshot()
        elif m == C and k == Qt.Key.Key_Space:
            self._hide_bar() if self._bar_open else self._show_bar()
        elif m == C and k == Qt.Key.Key_L:
            if not self._bar_open: self._show_bar()
            self._url.setFocus(); self._url.selectAll()
        elif m == C and k == Qt.Key.Key_Tab:   self._switch((self._active+1)%len(self._views))
        elif m == C and k == Qt.Key.Key_Equal: self._zoom_in_act()   # Ctrl++
        elif m == C and k == Qt.Key.Key_Minus: self._zoom_out_act()  # Ctrl+-
        elif m == C and k == Qt.Key.Key_0:     self._zoom_reset()    # Ctrl+0
        elif k == Qt.Key.Key_F5:               self._go_reload()
        elif k == Qt.Key.Key_Escape:
            self._hide_bar() if self._bar_open else self._show_bar()
        elif k == Qt.Key.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
        else: super().keyPressEvent(e)

# ─── Arranque ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                          "--enable-features=WebRTCPipeWireCapturer")
    app = QApplication(sys.argv)
    app.setApplicationName("Minichrome")
    app.setFont(QFont("Inter", 10))
    app.setStyleSheet("""
        QToolTip {
            background-color: #1a1a2e;
            color: #e0e8ff;
            border: 1px solid rgba(81, 162, 255, 0.55);
            border-radius: 6px;
            padding: 3px 7px;
            font-size: 11px;
            font-family: 'Inter', sans-serif;
            opacity: 230;
        }
    """)
    w = Minichrome()
    w.show()
    sys.exit(app.exec())
