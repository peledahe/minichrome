"""Perfil web, WebPage (captura/autollenado de contraseñas) y WebView."""
import os
import re
import json
import sqlite3
import time
import browser_features as bf
from urllib.parse import urlparse
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSizePolicy, QDialog, QFileDialog
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEngineProfile, QWebEnginePage, QWebEngineScript, QWebEngineSettings,
    QWebEngineUrlRequestInterceptor, QWebEngineFileSystemAccessRequest
)
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl, Qt, QObject, QStandardPaths, QTimer, pyqtSignal
from config import (CACHE, DB, SPELL_LANG, is_internal_url, load_quick_links, save_quick_links,
                    load_search_engines, save_search_engines)
from secure_store import encrypt, decrypt
from db import _db, get_config, save_history
from widgets import BTN_NAV, Notif
from bridges import AgendaBridge, ExtensionMediaBridge, PasswordBridge, remember_granted_dir
import slack_sync

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
        
        # Solo el inicio de sesión de Google: en Gmail el UA de Firefox 124 hace
        # que muestre "Ya no se admite esta versión" (el motor real es Chrome 140).
        host = (url.host() or "").lower()
        if host == "accounts.google.com":
            info.setHttpHeader(b"User-Agent", self._ff_ua)


_PROFILE_NAME = "minichrome-web_cache"


def _new_profile():
    """Perfil persistente con los datos en CACHE (web_cache/).

    No se usa setPersistentStoragePath(): cambiar la ruta después de crear el
    perfil deja el sistema de extensiones de Chromium ligado a las
    preferencias anteriores y setExtensionEnabled() tumba el proceso.
    QWebEngineProfileBuilder lo evitaría, pero PyQt6 no permite instanciarlo.
    Tampoco sirve un nombre con "../": Chromium rechaza esas rutas (LevelDB,
    caché del service worker). Se usa la ruta por defecto de Qt para el nombre
    del perfil, convertida en un enlace simbólico a CACHE.
    """
    base = os.path.join(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation),
                        "QtWebEngine")
    link = os.path.join(base, _PROFILE_NAME)
    try:
        os.makedirs(base, exist_ok=True)
        if os.path.islink(link) and os.path.realpath(link) != os.path.realpath(CACHE):
            os.unlink(link)
        if not os.path.lexists(link):
            os.symlink(CACHE, link)
    except OSError as e:
        print(f"[perfil] no se pudo enlazar {link} -> {CACHE}: {e}")
    if os.path.realpath(link) == os.path.realpath(CACHE):
        return QWebEngineProfile(_PROFILE_NAME)
    # Sin enlace: los datos siguen en CACHE, pero las extensiones no se podrán activar.
    prof = QWebEngineProfile("MinichromeProfile")
    prof.setPersistentStoragePath(CACHE)
    return prof


def profile():
    global _prof, _ua_interceptor
    if not _prof:
        _prof = _new_profile()
        # UA real del motor sin la marca "QtWebEngine/x.y.z", que algunos sitios
        # bloquean; así coincide con la versión de Chrome que realmente corre.
        _prof.setHttpUserAgent(re.sub(r"\s*QtWebEngine/\S+", "", _prof.httpUserAgent()))
        _prof.setCachePath(os.path.join(CACHE, "httpcache"))
        _prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        _prof.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)

        _ua_interceptor = DomainUAInterceptor(_prof)
        _prof.setUrlRequestInterceptor(_ua_interceptor)

        # Corrector ortográfico (opcional, menú "Más opciones")
        _prof.setSpellCheckLanguages([SPELL_LANG])
        _prof.setSpellCheckEnabled(get_config("spellCheckEnabled", "0") == "1")

        # CSS Global (scrollbars personalizados delgados y sutiles)
        s = QWebEngineScript()
        s.setSourceCode("""
            (function(){
                var st = document.createElement('style');
                st.id = 'minichrome-scrollbar-style';
                st.textContent = `
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

        # ── Script de Integración con Chrome Web Store ────────────────────────
        cws_script = QWebEngineScript()
        cws_script.setName("cws_helper")
        cws_script.setSourceCode("""
        (function(){
            if (location.hostname !== 'chromewebstore.google.com') return;

            var style = document.createElement('style');
            style.textContent = `
                .minichrome-cws-btn {
                    background: linear-gradient(135deg, #2563eb, #7c3aed) !important;
                    color: white !important;
                    border: 1px solid rgba(255,255,255,0.4) !important;
                    border-radius: 24px !important;
                    padding: 8px 24px !important;
                    font-weight: 700 !important;
                    font-size: 13px !important;
                    cursor: pointer !important;
                    display: inline-flex !important;
                    align-items: center !important;
                    gap: 6px !important;
                    box-shadow: 0 4px 14px rgba(124,58,237,0.4) !important;
                    transition: transform 0.15s, filter 0.15s !important;
                }
                .minichrome-cws-btn:hover {
                    filter: brightness(1.1) !important;
                    transform: scale(1.02) !important;
                }
            `;
            (document.head || document.documentElement).appendChild(style);

            // Aviso "no disponible" (la tienda no reconoce Minichrome como Chrome).
            // Se oculta solo el bloque pequeño que lo contiene, nunca un ancestro
            // con el resto de la página.
            var UNAVAILABLE = /(elemento no (está )?disponible|item (is )?(currently )?unavailable|no disponible actualmente)/i;
            var MAX_BANNER_TEXT = 400;

            function hideUnavailable() {
                var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                var node;
                while ((node = walker.nextNode())) {
                    if (!UNAVAILABLE.test(node.nodeValue || '')) continue;
                    var el = node.parentElement, box = null;
                    while (el && el !== document.body && el.tagName !== 'MAIN'
                           && (el.textContent || '').length <= MAX_BANNER_TEXT) {
                        box = el;
                        el = el.parentElement;
                    }
                    if (box && !box.dataset.mcHidden) {
                        box.dataset.mcHidden = '1';
                        box.style.display = 'none';
                    }
                }
            }

            function fixButtons() {
                document.querySelectorAll('button:not(.minichrome-cws-btn)').forEach(function(btn) {
                    var txt = (btn.textContent || '').trim();
                    if (txt.includes('Agregar a Chrome') || txt.includes('Añadir a Chrome') || txt.includes('Add to Chrome')
                        || txt.includes('Disponible en Chrome') || txt.includes('No compatible')) {
                        btn.removeAttribute('disabled');
                        btn.style.opacity = '1';
                        btn.style.cursor = 'pointer';
                        btn.style.pointerEvents = 'auto';
                        // La tienda exige Trusted Types: innerHTML lanzaría un error.
                        btn.textContent = '➕ Instalar en Minichrome';
                        btn.classList.add('minichrome-cws-btn');
                        btn.onclick = function(e) {
                            e.preventDefault();
                            e.stopPropagation();
                            window.location.hash = '#install-minichrome-ext=' + Date.now();
                        };
                    }
                });
            }

            // La tienda es una SPA: se revisa al cambiar el DOM (agrupado por frame).
            var queued = false;
            function fixCWS() {
                queued = false;
                if (!document.body) return;
                hideUnavailable();
                fixButtons();
            }
            new MutationObserver(function() {
                if (!queued) { queued = true; requestAnimationFrame(fixCWS); }
            }).observe(document.documentElement, {childList: true, subtree: true, characterData: true});
            fixCWS();
        })();
        """)
        cws_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        cws_script.setRunsOnSubFrames(True)
        cws_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        _prof.scripts().insert(cws_script)

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



    return _prof



# ─── WebPage personalizada (intercepta mensajes de consola) ───────────────────
_FRAME_BLOCKED_RE = re.compile(r"Refused to (?:display|frame) '([^']+)'")


class WebPage(QWebEnginePage):
    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self._last_pwd_prompt_key = ""
        self._last_pwd_prompt_ts = 0.0
        self._last_autofill_host = ""
        self._last_autofill_ts = 0.0
        self._bridges: dict[str, QObject] = {}
        self._bridges_published = False
        self._ext_bridges: dict[str, QObject] = {}
        self._ext_bridges_published = False
        self.urlChanged.connect(self._sync_bridges)
        self.loadFinished.connect(lambda _ok: self._sync_bridges(self.url()))
        self.fileSystemAccessRequested.connect(self._handle_file_system_access)

    def chooseFiles(self, mode, old_files, accepted_mime_types):
        """showDirectoryPicker() y <input webkitdirectory> piden una carpeta: el
        diálogo por defecto de Qt no permitía elegirla en los visores, se usa el de carpetas."""
        if mode == QWebEnginePage.FileSelectionMode.FileSelectUploadFolder:
            start = old_files[0] if old_files else QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.HomeLocation)
            parent = self.parent() if isinstance(self.parent(), QWidget) else None
            path = QFileDialog.getExistingDirectory(parent, "Seleccionar carpeta", start)
            return [path] if path else []
        return super().chooseFiles(mode, old_files, accepted_mime_types)

    def _handle_file_system_access(self, request):
        """Concede acceso al sistema de archivos solicitado por la página o extensión."""
        request.accept()
        # Las carpetas concedidas a extensiones permiten luego reproducir sus
        # videos H.264 con el reproductor nativo (ExtensionMediaBridge).
        if request.handleType() == QWebEngineFileSystemAccessRequest.HandleType.Directory:
            origin = request.origin()
            remember_granted_dir(f"{origin.scheme()}://{origin.host()}", request.filePath().toLocalFile())

    # ── Bridges py/pw solo para páginas internas; mcmedia solo para extensiones ──
    def set_internal_bridges(self, channel, bridges: dict, extension_bridges: dict | None = None):
        """El canal queda fijo; los objetos solo se publican en páginas internas
        (bridges) o en páginas chrome-extension:// (extension_bridges)."""
        self._bridges = bridges
        self._ext_bridges = extension_bridges or {}
        self.setWebChannel(channel)
        self._sync_bridges(self.url())

    def _sync_bridges(self, url, allow_register=True):
        channel = self.webChannel()
        if channel is None:
            return
        self._bridges_published = self._publish(
            channel, self._bridges, self._bridges_published, is_internal_url(url), allow_register)
        self._ext_bridges_published = self._publish(
            channel, self._ext_bridges, self._ext_bridges_published,
            url.scheme() == "chrome-extension", allow_register)

    @staticmethod
    def _publish(channel, objects, published, wanted, allow_register):
        if published and not wanted:
            for obj in objects.values():
                channel.deregisterObject(obj)
            return False
        if wanted and allow_register and not published:
            for name, obj in objects.items():
                channel.registerObject(name, obj)
            return True
        return published

    def _sync_remote_access(self, url):
        """Solo las páginas propias (ui/) pueden cargar recursos remotos, como
        los favicons de la página de inicio. Otros archivos locales no."""
        attr = QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls
        internal = is_internal_url(url)
        if self.settings().testAttribute(attr) != internal:
            self.settings().setAttribute(attr, internal)

    def _sync_clipboard_access(self, url):
        """Las páginas de extensiones (chrome-extension://) pueden usar
        navigator.clipboard, como en Chrome; los sitios web no."""
        attr = QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard
        is_ext = url.scheme() == "chrome-extension"
        if self.settings().testAttribute(attr) != is_ext:
            self.settings().setAttribute(attr, is_ext)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        # Regreso de la autorización de Slack: se toma el código aquí y la
        # dirección (https://localhost/…) nunca llega a cargarse.
        if is_main_frame and url.toString().startswith(slack_sync.REDIRECT_URI):
            slack_sync.client().handle_redirect(url.toString())
            view = self.parent()
            if hasattr(view, "closeRequested"):
                QTimer.singleShot(0, view.closeRequested.emit)
            return False
        # Retira los bridges antes de salir hacia un sitio externo; el registro
        # solo ocurre al confirmarse la URL interna (urlChanged), cuando el
        # documento externo anterior ya no existe.
        if is_main_frame:
            self._sync_bridges(url, allow_register=False)
            self._sync_remote_access(url)
            self._sync_clipboard_access(url)
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

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
                "password": decrypt(row[3]),
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
            if decrypt(existing[1]) == pwd:
                c.close()
                return
            c.execute(
                "UPDATE passwords SET password=?, type='web', url=?, ts=CURRENT_TIMESTAMP WHERE id=?",
                (encrypt(pwd), full_url, existing[0])
            )
            action = "actualizada"
        else:
            c.execute(
                "INSERT INTO passwords(site, username, password, type, url, notes) VALUES(?,?,?,?,?,?)",
                (site, user, encrypt(pwd), 'web', full_url, '')
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
        # Cualquier sitio puede escribir en consola: el origen se toma de la URL
        # real de la pestaña, nunca de los datos que envía la página.
        page_url = self.url()
        if message.startswith("MINICHROME_LINKS:"):
            if is_internal_url(page_url):
                save_quick_links(message[len("MINICHROME_LINKS:"):])
        elif message.startswith("MINICHROME_ENGINES:"):
            if is_internal_url(page_url):
                save_search_engines(message[len("MINICHROME_ENGINES:"):])
        elif page_url.scheme() == "chrome-extension":
            # En Chrome la extensión quita X-Frame-Options/frame-ancestors con
            # declarativeNetRequest; QtWebEngine no puede, así que el shim
            # sustituye el iframe rechazado por un acceso para abrirlo en pestaña.
            m = _FRAME_BLOCKED_RE.match(message)
            if m:
                self.runJavaScript("window.__minichromeFrameBlocked && "
                                   f"window.__minichromeFrameBlocked({json.dumps(m.group(1))})")
        elif message.startswith("MINICHROME_AUTOFILL_REQUEST:"):
            try:
                if page_url.scheme() not in ("http", "https"):
                    return
                host = self._normalized_host(page_url.host())
                if not host:
                    return

                now_ts = time.time()
                if host == self._last_autofill_host and (now_ts - self._last_autofill_ts) < 0.9:
                    return

                self._last_autofill_host = host
                self._last_autofill_ts = now_ts
                creds = self._load_matching_credentials(host, page_url.toString())
                self._run_autofill(creds)
            except Exception as e:
                print(f"[Autofill] Error: {e}")
        elif message.startswith("MINICHROME_PWD:"):
            try:
                if page_url.scheme() not in ("http", "https"):
                    return
                data = json.loads(message[len("MINICHROME_PWD:"):])
                site = self._normalized_host(page_url.host())
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

                if existing and decrypt(existing[1]) == pwd:
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
                    "url": page_url.toString()
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
    closeRequested = pyqtSignal()

    def __init__(self, main_win, url="", record_history=True):
        super().__init__()
        self.main_win = main_win
        self._record_history = record_history
        # Opcional: callable(permission) -> True (conceder), False (denegar) o
        # None (preguntar como siempre). Lo usa el panel de extensiones.
        self.permission_policy = None
        self._was_maximized_before_web_fullscreen = False
        page = WebPage(profile(), self)
        self.setPage(page)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        
        # Canal de comunicación para la Agenda
        self._channel = QWebChannel(self)
        self._bridge = AgendaBridge(self)
        self._pw_bridge = PasswordBridge(self)
        self._media_bridge = ExtensionMediaBridge(self)
        page.set_internal_bridges(self._channel, {"py": self._bridge, "pw": self._pw_bridge},
                                  {"mcmedia": self._media_bridge})

        page.windowCloseRequested.connect(self.closeRequested)
        page.geometryChangeRequested.connect(self._ignore_geom)
        page.fullScreenRequested.connect(self._handle_fullscreen_request)

        # Funciones estándar de navegador (browser_features)
        page.permissionRequested.connect(self._on_permission)
        page.certificateError.connect(lambda err: bf.handle_certificate_error(self, err))
        self._crash_overlay = bf.CrashOverlay(self)
        bf.attach_print_feedback(self, self, self._notify)
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
        request.accept()
        self.set_app_fullscreen(bool(request.toggleOn()))

    def set_app_fullscreen(self, enable_fullscreen):
        if enable_fullscreen:
            if self.main_win.isFullScreen():
                return
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
                engines = load_search_engines()
                if engines is not None:
                    js = f"window._miniEngines = {json.dumps(engines)}; if (typeof renderEngines === 'function') renderEngines();"
                    self.page().runJavaScript(js)
        elif self._record_history:
            save_history(self.title(), url)

    def createWindow(self, _type):
        return self.main_win.new_tab("")

    def _notify(self, title, body):
        if isinstance(self.main_win, QWidget):
            Notif(title, body, self.main_win)

    def _on_permission(self, permission):
        # Las páginas internas y extensiones chrome-extension:// conservan permisos concedidos
        if is_internal_url(self.url()) or self.url().scheme() == "chrome-extension":
            permission.grant()
            return
        decision = self.permission_policy(permission) if self.permission_policy else None
        if decision is True:
            permission.grant()
        elif decision is False:
            permission.deny()
        else:
            bf.ask_permission(self, permission)
