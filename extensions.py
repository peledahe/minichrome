"""Extensiones de Chrome (Manifest V3) para Minichrome.

Usa el sistema de extensiones nativo de QtWebEngine (QWebEngineExtensionManager):
las páginas corren en chrome-extension://, con su service worker, storage
persistente, mensajería y content scripts reales.

QtWebEngine solo implementa una parte de chrome.* (runtime, storage, i18n,
alarms, management y un tabs mínimo). Para que las extensiones no fallen al
llamar al resto, cada una se carga desde una copia en installed_extensions/.runtime/
con ui/extension_shim.js inyectado en su service worker y en sus páginas HTML.
La carpeta original de la extensión nunca se modifica.
"""
import os
import io
import json
import re
import base64
import hashlib
import zipfile
import shutil
import urllib.request
from PyQt6.QtCore import (QObject, pyqtSignal, pyqtSlot, QUrl, Qt, QTimer, QBuffer, QIODevice, QFile,
                          QRect, QPropertyAnimation, QEasingCurve)
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)
from PyQt6.QtGui import QPixmap, QCursor
from PyQt6.QtWebEngineCore import QWebEngineScript
from config import BASE, UI_DIR, is_internal_url
from db import _db
from browser import profile, WebView

INSTALL_DIR = os.path.join(BASE, "installed_extensions")
RUNTIME_DIR = os.path.join(INSTALL_DIR, ".runtime")
SHIM_SRC = os.path.join(UI_DIR, "extension_shim.js")
# Chromium reserva los nombres que empiezan con "_" dentro de una extensión.
SHIM_NAME = "minichrome-shim.js"
SW_WRAPPER_NAME = "minichrome-sw.js"


# ─── Descarga / paquetes .crx ─────────────────────────────────────────────────
def _pb_fields(buf: bytes):
    """Recorre los campos de un mensaje protobuf (solo varint y length-delimited)."""
    i = 0
    while i < len(buf):
        key = shift = 0
        while True:
            b = buf[i]; i += 1
            key |= (b & 0x7F) << shift; shift += 7
            if not b & 0x80:
                break
        field, wire = key >> 3, key & 7
        if wire == 0:
            while buf[i] & 0x80:
                i += 1
            i += 1
        elif wire == 2:
            ln = shift = 0
            while True:
                b = buf[i]; i += 1
                ln |= (b & 0x7F) << shift; shift += 7
                if not b & 0x80:
                    break
            yield field, buf[i:i + ln]
            i += ln
        else:
            return


def extension_id_from_key(public_key: bytes) -> str:
    digest = hashlib.sha256(public_key).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def crx_public_key(crx_data: bytes, ext_id: str | None = None) -> bytes | None:
    """Clave pública de un .crx (v2 o v3); con ext_id elige la que genera ese ID."""
    if crx_data[:4] != b"Cr24":
        return None
    version = int.from_bytes(crx_data[4:8], "little")
    if version == 2:
        klen = int.from_bytes(crx_data[8:12], "little")
        return crx_data[16:16 + klen]
    if version != 3:
        return None
    hlen = int.from_bytes(crx_data[8:12], "little")
    keys = []
    try:
        for field, proof in _pb_fields(crx_data[12:12 + hlen]):
            if field in (2, 3):  # sha256_with_rsa / sha256_with_ecdsa
                keys += [v for f, v in _pb_fields(proof) if f == 1]
    except IndexError:
        return None
    for k in keys:
        if ext_id is None or extension_id_from_key(k) == ext_id:
            return k
    return None


def extract_crx_bytes(crx_data: bytes, dest_dir: str, ext_id: str | None = None):
    """Extrae un .crx o .zip en dest_dir.

    Si el manifest no trae "key", se añade la del .crx para que Chromium le
    asigne a la extensión el mismo ID que en la Chrome Web Store.
    """
    os.makedirs(dest_dir, exist_ok=True)
    zip_offset = crx_data.find(b"PK\x03\x04")
    if zip_offset == -1:
        raise ValueError("El archivo descargado no contiene un formato ZIP/CRX válido.")

    with zipfile.ZipFile(io.BytesIO(crx_data[zip_offset:])) as z:
        z.extractall(dest_dir)

    key = crx_public_key(crx_data, ext_id)
    mf_path = os.path.join(dest_dir, "manifest.json")
    if key and os.path.exists(mf_path):
        try:
            with open(mf_path, "r", encoding="utf-8-sig") as f:
                mf = json.load(f)
            if "key" not in mf:
                mf["key"] = base64.b64encode(key).decode()
                with open(mf_path, "w", encoding="utf-8") as f:
                    json.dump(mf, f, ensure_ascii=False, indent=2)
        except (OSError, ValueError):
            pass


def parse_webstore_id(input_str: str) -> str | None:
    """Extrae el ID de 32 caracteres de una URL o texto de la Chrome Web Store."""
    input_str = (input_str or "").strip()
    if re.match(r"^[a-p]{32}$", input_str):
        return input_str
    m = re.search(r"\/detail\/(?:[^\/]+\/)?([a-p]{32})", input_str)
    if m:
        return m.group(1)
    m2 = re.search(r"([a-p]{32})", input_str)
    if m2:
        return m2.group(1)
    return None


def download_crx_from_webstore(ext_id: str) -> bytes:
    url = f"https://clients2.google.com/service/update2/crx?response=redirect&prodversion=134.0.0.0&acceptformat=crx2,crx3&x=id%3D{ext_id}%26uc"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        }
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read()


# ─── Copia de ejecución con el shim ───────────────────────────────────────────
def _runtime_dir_for(ext_id: str) -> str:
    return os.path.join(RUNTIME_DIR, re.sub(r"[^A-Za-z0-9_.-]", "_", ext_id))


def _inject_shim_html(html: str) -> str:
    tag = f'<script src="/{SHIM_NAME}"></script>'
    for pattern in (r"<head\b[^>]*>", r"<html\b[^>]*>"):
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return html[:m.end()] + tag + html[m.end():]
    m = re.match(r"\s*<!doctype[^>]*>", html, re.IGNORECASE)
    pos = m.end() if m else 0
    return html[:pos] + tag + html[pos:]


def stage_extension(src_dir: str, ext_id: str) -> str:
    """Copia la extensión a .runtime/<id> con el shim inyectado y devuelve la ruta."""
    dest = _runtime_dir_for(ext_id)
    shutil.rmtree(dest, ignore_errors=True)
    # _metadata viene en los .crx de la Web Store; Chromium rechaza nombres con "_"
    # al cargar extensiones desempaquetadas (salvo _locales).
    shutil.copytree(src_dir, dest, symlinks=False,
                    ignore=shutil.ignore_patterns(".git", "node_modules", "_metadata", ".runtime"))
    shutil.copyfile(SHIM_SRC, os.path.join(dest, SHIM_NAME))

    mf_path = os.path.join(dest, "manifest.json")
    with open(mf_path, "r", encoding="utf-8-sig") as f:
        mf = json.load(f)

    bg = mf.get("background") or {}
    sw = bg.get("service_worker")
    if sw:
        sw_url = "/" + sw.lstrip("/")
        if bg.get("type") == "module":
            wrapper = f'import "/{SHIM_NAME}";\nimport {json.dumps(sw_url)};\n'
        else:
            wrapper = f'importScripts("/{SHIM_NAME}", {json.dumps(sw_url)});\n'
        with open(os.path.join(dest, SW_WRAPPER_NAME), "w", encoding="utf-8") as f:
            f.write(wrapper)
        bg["service_worker"] = SW_WRAPPER_NAME
        with open(mf_path, "w", encoding="utf-8") as f:
            json.dump(mf, f, ensure_ascii=False, indent=2)

    for root, _dirs, files in os.walk(dest):
        for name in files:
            if not name.lower().endswith((".html", ".htm")):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
                    html = f.read()
                with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
                    f.write(_inject_shim_html(html))
            except OSError:
                pass
    return dest


# ─── Modelo ───────────────────────────────────────────────────────────────────
class ChromeExtension:
    """Extensión registrada en Minichrome (carpeta original + estado nativo)."""
    def __init__(self, ext_id: str, path: str, enabled: bool = True, manifest: dict | None = None):
        self.id = ext_id
        self.path = os.path.abspath(path)
        self.enabled = enabled
        self.manifest = self._read_manifest() or manifest or {}
        self.messages = self._load_locales()
        self.name = self._resolve_msg(self.manifest.get("name") or self.manifest.get("short_name") or os.path.basename(path))
        self.version = self.manifest.get("version", "1.0")
        self.description = self._resolve_msg(self.manifest.get("description", ""))
        self.icon_path = self._resolve_icon()
        self.action_popup = self._resolve_action_popup()
        self.side_panel = self._resolve_side_panel()
        # En el panel lateral se prefiere la página de side_panel (fluida, a todo
        # el alto) sobre el popup (tamaño fijo); sin ninguna se abre en pestaña.
        self.page = self.side_panel or self.action_popup or self._resolve_fallback_page()
        self.popup_path = os.path.join(self.path, self.page) if self.page else ""
        # Estado del motor: ID de Chromium y error de carga (si lo hubo).
        self.native_id = ""
        self.error = ""

    @property
    def loaded(self) -> bool:
        return bool(self.native_id) and not self.error

    def _read_manifest(self) -> dict:
        mf_path = os.path.join(self.path, "manifest.json")
        if os.path.exists(mf_path):
            try:
                with open(mf_path, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except (OSError, ValueError):
                pass
        return {}

    def _load_locales(self) -> dict:
        """Mensajes i18n (para nombre y descripción), con español preferente."""
        locales_dir = os.path.join(self.path, "_locales")
        messages = {}
        if not os.path.isdir(locales_dir):
            return messages
        default_loc = self.manifest.get("default_locale")
        for group in ([default_loc, "en", "en_US", "en_GB"],
                      ["es", "es_419", "es_ES", "es_MX", "es_AR", "es_CO", "es_CL"]):
            for loc in group:
                fpath = os.path.join(locales_dir, loc or "", "messages.json")
                if loc and os.path.exists(fpath):
                    try:
                        with open(fpath, "r", encoding="utf-8-sig") as f:
                            for k, v in json.load(f).items():
                                messages[k.lower()] = v
                        break
                    except (OSError, ValueError):
                        pass
        return messages

    def _resolve_msg(self, text: str) -> str:
        """Reemplaza placeholders de i18n tipo __MSG_key__ por su traducción."""
        if not text or not isinstance(text, str):
            return text or ""

        def repl(match):
            msg_obj = self.messages.get(match.group(1).lower())
            if isinstance(msg_obj, dict) and "message" in msg_obj:
                return str(msg_obj["message"])
            return match.group(1)

        return re.sub(r"__MSG_([a-zA-Z0-9_@]+)__", repl, text)

    def _resolve_icon(self) -> str:
        def pick(icons):
            if isinstance(icons, str):
                icons = {"0": icons}
            if not isinstance(icons, dict):
                return ""
            for size in sorted(icons, key=lambda s: -int(s) if s.isdigit() else 0):
                cand = os.path.join(self.path, icons[size])
                if os.path.exists(cand):
                    return cand
            return ""

        action = self.manifest.get("action") or self.manifest.get("browser_action") or {}
        return pick(self.manifest.get("icons")) or pick(action.get("default_icon")) or ""

    def _resolve_action_popup(self) -> str:
        action = self.manifest.get("action") or self.manifest.get("browser_action") or {}
        popup = (action.get("default_popup") or "").lstrip("/")
        return popup if popup and os.path.exists(os.path.join(self.path, popup)) else ""

    @property
    def opens_in_panel(self) -> bool:
        return bool(self.side_panel or self.action_popup)

    def _resolve_side_panel(self) -> str:
        path = ((self.manifest.get("side_panel") or {}).get("default_path") or "").lstrip("/")
        return path if path and os.path.exists(os.path.join(self.path, path)) else ""

    def _resolve_fallback_page(self) -> str:
        """Página a abrir en pestaña cuando no hay popup (p. ej. la acción abre la app)."""
        mf = self.manifest
        side = (mf.get("side_panel") or {}).get("default_path")
        options = (mf.get("options_ui") or {}).get("page") or mf.get("options_page")
        stem = re.sub(r"[^a-z0-9]", "", (mf.get("short_name") or "").lower())
        for name in [side, f"{stem}.html" if stem else None, "organizer.html", "index.html",
                     "main.html", "app.html", "popup.html", options]:
            if name and os.path.exists(os.path.join(self.path, name.lstrip("/"))):
                return name.lstrip("/")
        return ""


# ─── Panel lateral────────────────────────────────────────────────────────────────
def _qwebchannel_js() -> str:
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.OpenModeFlag.ReadOnly):
        return ""
    try:
        return bytes(f.readAll()).decode("utf-8")
    finally:
        f.close()


class ExtensionTabBridge(QObject):
    """Objeto `mcext` del panel de la extensión: operaciones sobre la pestaña activa de Minichrome."""
    scriptResult = pyqtSignal(int, str)

    def __init__(self, extension: ChromeExtension, panel, main_win):
        super().__init__(panel)
        self.extension = extension
        self.panel = panel
        self.main_win = main_win

    def _allowed(self) -> bool:
        """Solo la página de la propia extensión puede usar el puente: si el
        panel navega a otro sitio, ese sitio no debe tocar las pestañas."""
        url = self.panel.web.url()
        return url.scheme() == "chrome-extension" and bool(self.extension.native_id) \
            and url.host() == self.extension.native_id

    def _view(self):
        if not self._allowed():
            return None
        cur = getattr(self.main_win, "_cur", None)
        return cur() if cur else None

    def _scriptable_view(self):
        """Pestaña activa si es una web normal (nunca páginas internas ni de otra extensión)."""
        v = self._view()
        if not v:
            return None
        url = v.url()
        if url.scheme() not in ("http", "https", "file") or is_internal_url(url):
            return None
        return v

    @pyqtSlot(result=str)
    def activeTab(self):
        v = self._view()
        if not v:
            return ""
        views = getattr(self.main_win, "_views", [])
        idx = views.index(v) if v in views else 0
        size = v.size()
        return json.dumps({
            "id": idx + 1, "index": idx, "windowId": 1, "active": True, "highlighted": True,
            "selected": True, "pinned": False, "audible": False, "discarded": False,
            "autoDiscardable": True, "incognito": False, "status": "complete",
            "mutedInfo": {"muted": False}, "groupId": -1,
            "url": v.url().toString(), "title": v.title(),
            "favIconUrl": v.iconUrl().toString(),
            "width": size.width(), "height": size.height(),
        })

    @pyqtSlot(str)
    def openTab(self, url):
        qurl = QUrl(url)
        if not self._allowed() or qurl.scheme() in ("javascript", "data"):
            return
        self.main_win.new_tab(qurl.toString())

    @pyqtSlot(str, int, result=str)
    def captureVisibleTab(self, fmt, quality):
        v = self._scriptable_view()
        if not v:
            return ""
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        is_png = fmt.lower() == "png"
        v.grab().save(buf, "PNG" if is_png else "JPEG", -1 if is_png else max(0, min(100, quality)))
        mime = "image/png" if is_png else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(bytes(buf.data())).decode()

    def _read_files(self, files_json):
        base = os.path.realpath(_runtime_dir_for(self.extension.id))
        out = []
        for rel in json.loads(files_json or "[]"):
            path = os.path.realpath(os.path.join(base, str(rel).lstrip("/")))
            if not path.startswith(base + os.sep):
                raise ValueError(f"Archivo fuera de la extensión: {rel}")
            with open(path, "r", encoding="utf-8") as f:
                out.append(f.read())
        return out

    def _run(self, req_id, code):
        v = self._scriptable_view()
        if not v:
            self.scriptResult.emit(req_id, json.dumps({"error": "No se puede ejecutar código en esta pestaña"}))
            return

        def done(result):
            try:
                self.scriptResult.emit(req_id, json.dumps({"result": result}, default=str))
            except RuntimeError:
                pass  # el panel ya se cerró

        v.page().runJavaScript(code, QWebEngineScript.ScriptWorldId.ApplicationWorld.value, done)

    @pyqtSlot(int, str, str)
    def executeScript(self, req_id, code, files_json):
        try:
            if not code:
                code = "\n;\n".join(self._read_files(files_json))
        except (OSError, ValueError) as e:
            self.scriptResult.emit(req_id, json.dumps({"error": str(e)}))
            return
        self._run(req_id, code)

    @pyqtSlot(int, str, str)
    def insertCSS(self, req_id, css, files_json):
        try:
            css = "\n".join([css] + self._read_files(files_json))
        except (OSError, ValueError) as e:
            self.scriptResult.emit(req_id, json.dumps({"error": str(e)}))
            return
        self._run(req_id, "(function(){var s=document.createElement('style');s.textContent=%s;"
                          "(document.head||document.documentElement).appendChild(s);})()" % json.dumps(css))


class ExtensionPanel(QFrame):
    """Panel lateral derecho con la interfaz (action.default_popup) de la extensión.

    Ocupa todo el alto de la ventana y su ancho se ajusta al contenido de la
    página, igual que Chrome dimensiona sus popups; no es modal. La página es un
    WebView como el de las pestañas (permisos, certificados, pantalla completa,
    impresión, ventanas nuevas…) para que la extensión se comporte igual.
    """
    closed = pyqtSignal()
    MARGIN = 12      # igual que Minichrome.SIDE_MARGIN
    PAD = 8          # separación entre el borde de la tarjeta y la página
    MIN_W, DEFAULT_W, MAX_W = 300, 420, 900

    def __init__(self, extension: ChromeExtension, url: QUrl, main_win, parent):
        super().__init__(parent)
        self.extension = extension
        self.url = url
        self.main_win = main_win
        self.content_w = self.DEFAULT_W
        self.content_h = None    # alto del contenido (solo popups de tamaño fijo)
        self.fluid = bool(extension.side_panel) and url.path().lstrip("/") == extension.side_panel
        self._closing = False
        self.setObjectName("ext_panel")
        self.setStyleSheet("""
            #ext_panel{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 rgba(18,24,42,0.985), stop:1 rgba(12,16,30,0.985));
              border:1px solid rgba(120,160,255,0.32); border-radius:16px;}
            QLabel{background:transparent;}
            QPushButton{background:transparent; border:none; border-radius:15px;
              color:rgba(255,255,255,0.55); font-size:13px;}
            QPushButton:hover{background:rgba(255,255,255,0.08); color:white;}
        """)
        # Sin _shadow(): un QGraphicsEffect sobre un ancestro de QWebEngineView
        # hace que la página se pinte y reciba eventos por un camino lento.

        v = QVBoxLayout(self)
        v.setContentsMargins(self.PAD, 10, self.PAD, self.PAD)
        v.setSpacing(8)

        # Encabezado: icono, nombre y versión, abrir en pestaña, recargar, cerrar
        hdr = QHBoxLayout()
        hdr.setContentsMargins(6, 0, 0, 0)
        hdr.setSpacing(8)
        ico = QLabel()
        ico.setFixedSize(22, 22)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if extension.icon_path and os.path.exists(extension.icon_path):
            ico.setPixmap(QPixmap(extension.icon_path).scaled(
                22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            ico.setText("🧩")
        hdr.addWidget(ico)
        title = QLabel(f"<b style='color:#ffffff; font-size:13px;'>{extension.name}</b> "
                       f"<span style='color:rgba(255,255,255,0.45); font-size:10px;'>v{extension.version}</span>")
        title.setMinimumWidth(0)
        hdr.addWidget(title, 1)
        for text, tip, slot in (("↗", "Abrir en una pestaña", self._open_in_tab),
                                ("↻", "Recargar", self._reload_view),
                                ("✕", "Cerrar", self.close_panel)):
            b = QPushButton(text)
            b.setFixedSize(30, 30)
            b.setToolTip(tip)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(slot)
            hdr.addWidget(b)
        v.addLayout(hdr)

        # Página de la extensión (perfil compartido: mismo storage y service worker)
        self.web = WebView(main_win, record_history=False)
        self.page = self.web.page()
        self.web.closeRequested.connect(self.close_panel)
        self.web.permission_policy = self._permission_policy

        # qwebchannel.js antes que el código de la página: el shim lo usa para
        # hablar con ExtensionTabBridge (tabs.query, captureVisibleTab, scripting…).
        channel_js = _qwebchannel_js()
        if channel_js:
            script = QWebEngineScript()
            script.setName("minichrome_qwebchannel")
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            script.setSourceCode(channel_js)
            self.page.scripts().insert(script)
        # El WebView ya tiene su canal (py/pw solo en páginas internas); mcext se
        # añade a ese mismo canal y solo responde a la página de esta extensión.
        self._bridge = ExtensionTabBridge(extension, self, main_win)
        self.page.webChannel().registerObject("mcext", self._bridge)


        self.web.loadFinished.connect(self._on_loaded)
        v.addWidget(self.web, 1)

        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._anim_done)
        # Muchas extensiones cambian de vista sin recargar: se vuelve a medir.
        self._fit_timer = QTimer(self)
        self._fit_timer.setInterval(800)
        self._fit_timer.timeout.connect(self._fit_to_content)

        self.web.setUrl(url)

    # ── Geometría ────────────────────────────────────────────────────────────
    def _extra_w(self):
        return 2 * self.PAD + 2  # márgenes laterales + borde

    def _extra_h(self):
        lay = self.layout()
        mg = lay.contentsMargins()
        return mg.top() + mg.bottom() + lay.spacing() + 30 + 2  # encabezado + borde

    def target_rect(self) -> QRect:
        W, H = self.parentWidget().width(), self.parentWidget().height()
        m = self.MARGIN
        max_w = max(self.MIN_W, min(self.MAX_W, int(W * 0.7)))
        w = max(self.MIN_W, min(max_w, self.content_w + self._extra_w()))
        max_h = max(200, H - 2 * m)
        # Popup de tamaño fijo: la tarjeta se ajusta también al alto del contenido.
        h = max_h if self.content_h is None else max(160, min(max_h, self.content_h + self._extra_h()))
        return QRect(W - w - m, m, w, h)

    def _animate_to(self, rect: QRect, ms: int):
        self._anim.stop()
        self._anim.setDuration(ms)
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(rect)
        self._anim.start()

    def open_panel(self):
        r = self.target_rect()
        self.setGeometry(self.parentWidget().width() + 24, r.y(), r.width(), r.height())
        self.show()
        self.raise_()
        self.web.setFocus()  # como una pestaña activa (portapapeles, teclado)
        self._animate_to(r, 300)
        self._fit_timer.start()

    def close_panel(self):
        if self._closing:
            return
        self._closing = True
        self._fit_timer.stop()
        r = self.geometry()
        self._animate_to(QRect(self.parentWidget().width() + 24, r.y(), r.width(), r.height()), 250)

    def _anim_done(self):
        if self._closing:
            self.hide()
            self.closed.emit()
            self.deleteLater()

    def relayout(self):
        """Llamado al redimensionar la ventana principal."""
        if not self._closing and self._anim.state() != QPropertyAnimation.State.Running:
            self.setGeometry(self.target_rect())
        self.raise_()  # por encima de la barra, como los demás paneles laterales

    def _on_loaded(self, ok):
        if ok:
            for delay in (0, 300):
                QTimer.singleShot(delay, self._fit_to_content)

    # Caja de la interfaz: se baja desde <body> mientras haya un único hijo que
    # ocupe todo el ancho (p. ej. #root); el primer elemento más estrecho que la
    # ventana da el ancho propio del popup, y su alto cuenta solo si no estira
    # hasta el borde inferior. Se ignoran los elementos fijos (FAB, avisos) y los
    # display:contents se recorren como si no existieran.
    _MEASURE_JS = """(function(){
        var d=document.documentElement,b=document.body;if(!b)return null;
        function kids(e){var out=[];[].forEach.call(e.children,function(c){var s=getComputedStyle(c);
            if(s.display==='contents'){out=out.concat(kids(c));return;}
            if(s.display!=='none'&&s.position!=='fixed'&&s.position!=='absolute'&&c.tagName!=='SCRIPT'&&c.tagName!=='STYLE')out.push(c);});
            return out;}
        var box=b,cw=d.clientWidth,ch=d.clientHeight;
        while(box.getBoundingClientRect().width>=cw-1){var k=kids(box);if(k.length!==1)break;box=k[0];}
        var r=box.getBoundingClientRect();
        return [Math.ceil(r.width),Math.ceil(r.height),r.width<cw-1,r.height>=100&&r.bottom<ch-1,d.scrollWidth,cw];
    })()"""

    def _fit_to_content(self):
        def apply(m):
            if not m or self._closing:
                return
            box_w, box_h, own_w, own_h, scroll_w, client_w = m
            want_w, want_h = self.content_w, self.content_h
            if scroll_w > client_w + 1:
                want_w = scroll_w               # el contenido no cabe: ampliar
            elif own_w and not self.fluid:
                want_w = box_w                  # popup con ancho propio (p. ej. 320px)
            if not self.fluid and own_h:
                want_h = box_h                  # y con alto propio (p. ej. 480px)
            if abs(want_w - self.content_w) > 2 or want_h != self.content_h:
                self.content_w, self.content_h = want_w, want_h
                self._animate_to(self.target_rect(), 180)

        self.page.runJavaScript(self._MEASURE_JS, apply)

    def _permission_policy(self, permission):
        """Como Chrome con las extensiones: su propia página puede usar el
        portapapeles y, si el manifest lo declara, las notificaciones."""
        origin = permission.origin()
        if origin.scheme() != "chrome-extension" or origin.host() != self.extension.native_id:
            return None
        kind = permission.permissionType().name
        declared = set(self.extension.manifest.get("permissions") or [])
        if kind == "ClipboardReadWrite":
            return True
        if kind == "Notifications" and "notifications" in declared:
            return True
        return None

    # ── Acciones ─────────────────────────────────────────────────────────────
    def _reload_view(self):
        self.web.setUrl(self.url)

    def _open_in_tab(self):
        self.main_win.new_tab(self.url.toString())
        self.close_panel()


# ─── Gestor ───────────────────────────────────────────────────────────────────
class ExtensionsManager(QObject):
    """Registro de extensiones (tabla `extensions`) sincronizado con el motor."""
    extensions_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.extensions: dict[str, ChromeExtension] = {}
        self._native = profile().extensionManager()
        self._native.loadFinished.connect(self._on_load_finished)
        self._native.unloadFinished.connect(self._on_unload_finished)
        self._loading: dict[str, str] = {}    # ruta de .runtime -> id en Minichrome
        self._reloading: dict[str, str] = {}  # ID de Chromium -> id en Minichrome
        self._init_db()
        self.reload_all()

    def _init_db(self):
        c = _db()
        c.execute("""
            CREATE TABLE IF NOT EXISTS extensions(
                id TEXT PRIMARY KEY,
                name TEXT,
                path TEXT,
                enabled INTEGER DEFAULT 1,
                manifest_json TEXT DEFAULT '{}'
            )
        """)
        c.commit()
        c.close()

    # ── Motor nativo ──────────────────────────────────────────────────────────
    def _native_info(self, ext: ChromeExtension):
        # Los QWebEngineExtensionInfo de las señales no sobreviven al slot en
        # PyQt6: siempre se buscan de nuevo por ID.
        if not ext.native_id:
            return None
        for info in self._native.extensions():
            if info.id() == ext.native_id:
                return info
        return None

    def _load(self, ext: ChromeExtension):
        ext.native_id, ext.error = "", ""
        if (ext.manifest.get("manifest_version") or 2) != 3:
            ext.error = "Solo se admiten extensiones Manifest V3."
            return
        try:
            staged = stage_extension(ext.path, ext.id)
        except (OSError, ValueError) as e:
            ext.error = f"No se pudo preparar la extensión: {e}"
            return
        self._loading[os.path.realpath(staged)] = ext.id
        self._native.loadExtension(staged)

    def _on_load_finished(self, info):
        path, native_id = os.path.realpath(info.path()), info.id()
        error, loaded = info.error(), info.isLoaded()
        ext_id = self._loading.pop(path, None)
        ext = self.extensions.get(ext_id) if ext_id else None
        if not ext:
            return
        ext.native_id = native_id if loaded else ""
        ext.error = "" if loaded else (error or "No se pudo cargar la extensión.")
        if ext.error:
            print(f"[extensiones] {ext.name}: {ext.error}")
        # setExtensionEnabled no debe llamarse dentro del slot de loadFinished.
        QTimer.singleShot(0, lambda: self._apply_enabled(ext))

    def _apply_enabled(self, ext: ChromeExtension):
        info = self._native_info(ext)
        if info is not None and info.isEnabled() != ext.enabled:
            self._native.setExtensionEnabled(info, ext.enabled)
        self.extensions_changed.emit()

    def _reload(self, ext: ChromeExtension):
        # Volver a cargar una extensión ya cargada la deja deshabilitada cuando
        # Qt termina, después de _apply_enabled: se descarga y se carga de nuevo.
        info = self._native_info(ext)
        if info is None:
            self._load(ext)
            return
        self._reloading[ext.native_id] = ext.id
        self._native.unloadExtension(info)

    def _on_unload_finished(self, info):
        ext_id = self._reloading.pop(info.id(), None)
        ext = self.extensions.get(ext_id) if ext_id else None
        if ext:
            QTimer.singleShot(0, lambda: self._load(ext))

    def _unload(self, ext: ChromeExtension):
        info = self._native_info(ext)
        if info is not None:
            self._native.unloadExtension(info)
        ext.native_id = ""
        shutil.rmtree(_runtime_dir_for(ext.id), ignore_errors=True)

    # ── API usada por la ventana ─────────────────────────────────────────────
    def reload_all(self):
        old = self.extensions
        self.extensions = {}
        c = _db()
        rows = c.execute("SELECT id, name, path, enabled, manifest_json FROM extensions").fetchall()
        for ext_id, stored_name, path, enabled, mf_raw in rows:
            try:
                mf = json.loads(mf_raw) if mf_raw else None
            except ValueError:
                mf = None
            ext = ChromeExtension(ext_id, path, bool(enabled), mf)
            if ext_id in old:
                ext.native_id = old[ext_id].native_id
            self.extensions[ext_id] = ext
            if not os.path.exists(os.path.join(path, "manifest.json")):
                ext.error = f"No se encuentra la carpeta {path}"
                continue
            if ext.name and ext.name != stored_name:
                c.execute("UPDATE extensions SET name=? WHERE id=?", (ext.name, ext_id))
        c.commit()
        c.close()

        for ext_id, ext in old.items():
            if ext_id not in self.extensions:
                self._unload(ext)
        for ext in self.extensions.values():
            if not ext.error:
                self._reload(ext)
        self.extensions_changed.emit()

    def install_extension(self, folder_path: str, custom_id: str | None = None) -> ChromeExtension | None:
        folder_path = os.path.abspath(folder_path)
        mf_path = os.path.join(folder_path, "manifest.json")
        if not os.path.exists(mf_path):
            return None
        try:
            with open(mf_path, "r", encoding="utf-8-sig") as f:
                mf = json.load(f)
        except (OSError, ValueError):
            return None

        ext_id = custom_id or os.path.basename(folder_path).lower().replace(" ", "_")
        ext = ChromeExtension(ext_id, folder_path, True, mf)
        if ext_id in self.extensions:
            ext.native_id = self.extensions[ext_id].native_id

        c = _db()
        c.execute("""
            INSERT INTO extensions(id, name, path, enabled, manifest_json)
            VALUES(?, ?, ?, 1, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                path=excluded.path,
                enabled=1,
                manifest_json=excluded.manifest_json
        """, (ext_id, ext.name, folder_path, json.dumps(mf)))
        c.commit()
        c.close()

        self.extensions[ext_id] = ext
        self._reload(ext)
        self.extensions_changed.emit()
        return ext

    def install_from_webstore(self, webstore_url_or_id: str) -> ChromeExtension:
        """Descarga e instala una extensión directamente desde la Chrome Web Store."""
        ext_id = parse_webstore_id(webstore_url_or_id)
        if not ext_id:
            raise ValueError("No se pudo identificar un ID válido de la Chrome Web Store.")

        crx_data = download_crx_from_webstore(ext_id)
        dest_dir = os.path.join(INSTALL_DIR, ext_id)
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir, ignore_errors=True)
        extract_crx_bytes(crx_data, dest_dir, ext_id)

        ext = self.install_extension(dest_dir, custom_id=ext_id)
        if not ext:
            raise ValueError("La extensión se descargó pero no contiene un manifest.json válido.")
        return ext

    def install_from_crx_file(self, file_path: str) -> ChromeExtension:
        """Instala una extensión desde un archivo .crx o .zip local."""
        with open(file_path, "rb") as f:
            data = f.read()
        key = crx_public_key(data)
        base_name = extension_id_from_key(key) if key else \
            os.path.splitext(os.path.basename(file_path))[0].lower().replace(" ", "_")
        dest_dir = os.path.join(INSTALL_DIR, base_name)
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir, ignore_errors=True)
        extract_crx_bytes(data, dest_dir)

        ext = self.install_extension(dest_dir, custom_id=base_name)
        if not ext:
            raise ValueError("El paquete no contiene un manifest.json válido.")
        return ext

    def toggle_extension(self, ext_id: str, enabled: bool):
        ext = self.extensions.get(ext_id)
        if not ext:
            return
        ext.enabled = enabled
        c = _db()
        c.execute("UPDATE extensions SET enabled=? WHERE id=?", (1 if enabled else 0, ext_id))
        c.commit()
        c.close()
        self._apply_enabled(ext)

    def remove_extension(self, ext_id: str):
        """Desinstala la extensión, eliminando sus archivos si fue descargada en installed_extensions."""
        ext = self.extensions.get(ext_id)
        if not ext:
            return
        self._unload(ext)
        try:
            if os.path.abspath(ext.path).startswith(os.path.abspath(INSTALL_DIR) + os.sep):
                shutil.rmtree(ext.path, ignore_errors=True)
        except OSError as e:
            print(f"Error borrando directorio de extensión {ext_id}: {e}")

        del self.extensions[ext_id]
        c = _db()
        c.execute("DELETE FROM extensions WHERE id=?", (ext_id,))
        c.commit()
        c.close()
        self.extensions_changed.emit()

    def page_url(self, ext: ChromeExtension) -> QUrl | None:
        """URL chrome-extension:// del popup (o de la página principal si no hay popup)."""
        if not ext.loaded or not ext.page:
            return None
        return QUrl(f"chrome-extension://{ext.native_id}/{ext.page}")


_manager_instance = None

def manager() -> ExtensionsManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ExtensionsManager()
    return _manager_instance
