"""Funciones estándar de navegador (Fase 3).

Descargas, permisos por sitio, búsqueda en página, DevTools, impresión/PDF,
pestañas caídas y errores de certificado. Todo es aditivo: main.py solo
conecta señales, atajos y el menú "Más opciones".
"""
import os
import re

from PyQt6.QtCore import Qt, QUrl, QEvent, QStandardPaths
from PyQt6.QtGui import QDesktopServices, QCursor
from PyQt6.QtWidgets import (QFrame, QWidget, QLabel, QPushButton, QLineEdit,
                             QHBoxLayout, QVBoxLayout, QProgressBar, QScrollArea,
                             QDialog, QFileDialog, QMainWindow)
from PyQt6.QtWebEngineCore import (QWebEngineDownloadRequest, QWebEnginePage,
                                   QWebEnginePermission)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog


# ─── Estilos ──────────────────────────────────────────────────────────────────
PANEL_SS = """
    QFrame#panel{background:rgba(12,18,35,0.98); border:1px solid rgba(81,162,255,0.25);
      border-radius:10px;}
    QLabel{color:rgba(255,255,255,0.85); background:transparent; font-size:12px;}
    QLabel#muted{color:rgba(255,255,255,0.5); font-size:11px;}
    QLabel#title{color:rgba(255,255,255,0.9); font-size:13px; font-weight:bold;}
    QPushButton{background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.1);
      border-radius:6px; color:rgba(255,255,255,0.85); font-size:11px; padding:3px 8px;}
    QPushButton:hover{background:rgba(81,162,255,0.35); border-color:rgba(81,162,255,0.6);}
    QLineEdit{background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.12);
      border-radius:6px; color:white; padding:4px 8px; font-size:12px;}
    QLineEdit:focus{border-color:rgba(81,162,255,0.7);}
    QProgressBar{background:rgba(255,255,255,0.08); border:none; border-radius:2px; max-height:4px;}
    QProgressBar::chunk{background:#51a2ff; border-radius:2px;}
    QScrollArea{background:transparent; border:none;}
    QScrollBar:vertical{background:transparent; width:3px; margin:0;}
    QScrollBar::handle:vertical{background:rgba(81,162,255,0.3); border-radius:1px; min-height:20px;}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0;}
"""

DIALOG_SS = """
    QDialog{background:#11111a; border:1px solid rgba(255,255,255,0.1); border-radius:12px;}
    QLabel{color:#aaa; font-size:13px; background:transparent;}
    QLabel#title{color:white; font-size:16px; font-weight:bold;}
    QPushButton{background:transparent; border:none; color:rgba(255,255,255,0.75);
      font-size:13px; border-radius:6px; padding:6px 12px;}
    QPushButton:hover{background:rgba(255,255,255,0.15); color:white;}
    QPushButton#primary{background:rgba(81,162,255,0.85); color:white;}
    QPushButton#primary:hover{background:rgba(81,162,255,1);}
    QPushButton#danger{color:#ff5f57;}
"""


def fmt_bytes(n: int) -> str:
    if n < 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def downloads_dir() -> str:
    path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    return path or os.path.expanduser("~")


def _relayout(widget):
    """Pide a la ventana principal que reacomode los paneles flotantes."""
    place = getattr(widget.window(), "_place_overlays", None)
    if callable(place):
        place()


def _choice_dialog(parent, title: str, body: str, buttons: list[tuple[str, str, str]]) -> str:
    """Modal con el estilo de la app. buttons = [(clave, texto, objectName)].
    Devuelve la clave pulsada o "" si se cerró."""
    d = QDialog(parent)
    d.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
    d.setStyleSheet(DIALOG_SS)
    d.setMinimumWidth(380)
    v = QVBoxLayout(d)
    v.setContentsMargins(24, 24, 24, 24)
    t = QLabel(title); t.setObjectName("title"); t.setWordWrap(True)
    v.addWidget(t)
    m = QLabel(body); m.setWordWrap(True)
    m.setStyleSheet("margin:4px 0 12px 0;")
    v.addWidget(m)
    h = QHBoxLayout(); h.setSpacing(10); h.addStretch()
    result = {"key": ""}
    for key, text, obj_name in buttons:
        b = QPushButton(text)
        if obj_name:
            b.setObjectName(obj_name)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.clicked.connect(lambda _=False, k=key: (result.update(key=k), d.accept()))
        h.addWidget(b)
    v.addLayout(h)
    d.exec()
    return result["key"]


# ─── Descargas ────────────────────────────────────────────────────────────────
class DownloadRow(QFrame):
    def __init__(self, req: QWebEngineDownloadRequest, parent=None):
        super().__init__(parent)
        self.req = req
        self.setStyleSheet("QFrame{border-bottom:1px solid rgba(81,162,255,0.08);}")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(4)

        self._name = QLabel(req.downloadFileName())
        self._name.setToolTip(req.url().toString())
        v.addWidget(self._name)

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        v.addWidget(self._bar)

        h = QHBoxLayout(); h.setSpacing(6)
        self._status = QLabel(""); self._status.setObjectName("muted")
        h.addWidget(self._status, 1)
        self._open = QPushButton("Abrir")
        self._folder = QPushButton("Carpeta")
        self._cancel = QPushButton("Cancelar")
        self._open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.path())))
        self._folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(req.downloadDirectory())))
        self._cancel.clicked.connect(req.cancel)
        for b in (self._open, self._folder, self._cancel):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            h.addWidget(b)
        v.addLayout(h)

        req.receivedBytesChanged.connect(self.refresh)
        req.totalBytesChanged.connect(self.refresh)
        req.stateChanged.connect(self.refresh)
        req.downloadFileNameChanged.connect(self.refresh)
        self.refresh()

    def path(self) -> str:
        return os.path.join(self.req.downloadDirectory(), self.req.downloadFileName())

    def is_active(self) -> bool:
        S = QWebEngineDownloadRequest.DownloadState
        return self.req.state() in (S.DownloadRequested, S.DownloadInProgress)

    def refresh(self, *_):
        S = QWebEngineDownloadRequest.DownloadState
        req = self.req
        state = req.state()
        self._name.setText(req.downloadFileName())
        got, total = req.receivedBytes(), req.totalBytes()
        done = state == S.DownloadCompleted
        active = state in (S.DownloadRequested, S.DownloadInProgress)
        self._bar.setVisible(active)
        self._open.setVisible(done)
        self._folder.setVisible(done)
        self._cancel.setVisible(active)
        if state == S.DownloadInProgress:
            if total > 0:
                self._bar.setRange(0, 100)
                self._bar.setValue(int(got * 100 / total))
                self._status.setText(f"{fmt_bytes(got)} de {fmt_bytes(total)}")
            else:
                self._bar.setRange(0, 0)
                self._status.setText(fmt_bytes(got))
        elif done:
            self._status.setText(f"Completada · {fmt_bytes(got)}")
        elif state == S.DownloadCancelled:
            self._status.setText("Cancelada")
        elif state == S.DownloadInterrupted:
            self._status.setText(f"Error: {req.interruptReasonString()}")
        else:
            self._status.setText("Preparando…")


class DownloadsPanel(QFrame):
    """Panel flotante con el progreso de las descargas (Ctrl+J)."""
    WIDTH = 360

    def __init__(self, parent, notify):
        super().__init__(parent)
        self._notify = notify
        self._rows: list[DownloadRow] = []
        self.setObjectName("panel")
        self.setStyleSheet(PANEL_SS)
        self.setFixedWidth(self.WIDTH)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 8)
        v.setSpacing(4)

        hdr = QHBoxLayout(); hdr.setContentsMargins(12, 0, 8, 4)
        t = QLabel("Descargas"); t.setObjectName("title")
        hdr.addWidget(t, 1)
        b_dir = QPushButton("Abrir carpeta")
        b_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(downloads_dir())))
        b_clear = QPushButton("Limpiar")
        b_clear.setToolTip("Quitar de la lista las descargas terminadas")
        b_clear.clicked.connect(self.clear_finished)
        b_close = QPushButton("✕")
        b_close.clicked.connect(self.hide)
        for b in (b_dir, b_clear, b_close):
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            hdr.addWidget(b)
        v.addLayout(hdr)

        self._empty = QLabel("Sin descargas en esta sesión")
        self._empty.setObjectName("muted")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setContentsMargins(0, 16, 0, 16)
        v.addWidget(self._empty)

        self._list = QWidget()
        self._list.setStyleSheet("background:transparent;")
        self._list_l = QVBoxLayout(self._list)
        self._list_l.setContentsMargins(0, 0, 0, 0)
        self._list_l.setSpacing(0)
        self._list_l.addStretch()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._list)
        self._scroll.setMaximumHeight(360)
        v.addWidget(self._scroll)
        self._sync_empty()
        self.hide()

    def _sync_empty(self):
        has = bool(self._rows)
        self._empty.setVisible(not has)
        self._scroll.setVisible(has)
        self.adjustSize()

    def handle_request(self, req: QWebEngineDownloadRequest):
        """Acepta la descarga en la carpeta de descargas del perfil."""
        req.accept()
        row = DownloadRow(req)
        self._rows.insert(0, row)
        self._list_l.insertWidget(0, row)
        self._sync_empty()
        name = req.downloadFileName()
        self._notify("Descargando", name)

        def on_finished():
            S = QWebEngineDownloadRequest.DownloadState
            if req.state() == S.DownloadCompleted:
                self._notify("Descarga completada", req.downloadFileName())
            elif req.state() == S.DownloadInterrupted:
                self._notify("Descarga fallida", req.interruptReasonString())
        req.isFinishedChanged.connect(on_finished)
        self.show_panel()

    def clear_finished(self):
        for row in [r for r in self._rows if not r.is_active()]:
            self._rows.remove(row)
            self._list_l.removeWidget(row)
            row.deleteLater()
        self._sync_empty()

    def show_panel(self):
        self.show()
        _relayout(self)
        self.raise_()

    def toggle(self):
        self.hide() if self.isVisible() else self.show_panel()


# ─── Permisos ─────────────────────────────────────────────────────────────────
_PERMISSION_TEXT = {
    "MediaAudioCapture": "usar tu micrófono",
    "MediaVideoCapture": "usar tu cámara",
    "MediaAudioVideoCapture": "usar tu cámara y tu micrófono",
    "DesktopVideoCapture": "compartir tu pantalla",
    "DesktopAudioVideoCapture": "compartir tu pantalla y su audio",
    "MouseLock": "ocultar y bloquear el puntero del ratón",
    "Notifications": "mostrarte notificaciones",
    "Geolocation": "conocer tu ubicación",
    "ClipboardReadWrite": "leer tu portapapeles",
    "LocalFontsAccess": "acceder a las fuentes instaladas en tu equipo",
}


def ask_permission(parent, permission: QWebEnginePermission):
    """Pregunta al usuario; Qt guarda la decisión por sitio en el perfil."""
    kind = permission.permissionType().name
    action = _PERMISSION_TEXT.get(kind)
    if not action:
        return
    host = permission.origin().host() or permission.origin().toString()
    remember = QWebEnginePermission.isPersistent(permission.permissionType())
    body = f"{host} quiere {action}."
    if remember:
        body += "\n\nTu decisión se recordará para este sitio."
    choice = _choice_dialog(parent, "Permiso solicitado", body,
                            [("deny", "Bloquear", ""), ("grant", "Permitir", "primary")])
    if choice == "grant":
        permission.grant()
    else:
        permission.deny()


def reset_site_permissions(profile, url: QUrl) -> int:
    origin = QUrl(url.toString(QUrl.UrlFormattingOption.RemovePath |
                               QUrl.UrlFormattingOption.RemoveQuery |
                               QUrl.UrlFormattingOption.RemoveFragment))
    perms = profile.listPermissionsForOrigin(origin)
    for p in perms:
        p.reset()
    return len(perms)


# ─── Errores de certificado ───────────────────────────────────────────────────
def handle_certificate_error(parent, error):
    """Advierte y deja continuar solo si Chromium lo permite (overridable)."""
    if not error.isMainFrame() or not error.isOverridable():
        return  # Chromium bloquea y muestra su página de error
    error.defer()
    host = error.url().host()
    body = (f"Es posible que alguien intente robar tu información de {host} "
            f"(contraseñas, mensajes o tarjetas).\n\nMotivo: {error.description()}")
    choice = _choice_dialog(parent, "La conexión no es privada", body,
                            [("go", "Continuar de todos modos", "danger"),
                             ("back", "Volver a un lugar seguro", "primary")])
    if choice == "go":
        error.acceptCertificate()
    else:
        error.rejectCertificate()


# ─── Búsqueda en la página ────────────────────────────────────────────────────
class FindBar(QFrame):
    """Barra de búsqueda (Ctrl+F): Enter siguiente, Shift+Enter anterior, Esc cierra."""
    WIDTH = 340

    def __init__(self, parent):
        super().__init__(parent)
        self._view = None
        self.setObjectName("panel")
        self.setStyleSheet(PANEL_SS)
        self.setFixedWidth(self.WIDTH)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 6, 6, 6)
        h.setSpacing(4)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Buscar en la página")
        self._input.textChanged.connect(lambda _t: self._find())
        self._input.installEventFilter(self)
        h.addWidget(self._input, 1)
        self._count = QLabel("")
        self._count.setObjectName("muted")
        self._count.setMinimumWidth(44)
        self._count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self._count)
        for text, tip, fn in (("▲", "Anterior (Shift+Enter)", lambda: self._find(backward=True)),
                              ("▼", "Siguiente (Enter)", self._find),
                              ("✕", "Cerrar (Esc)", self.close_bar)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedSize(26, 24)
            b.setStyleSheet("padding:0;")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(fn)
            h.addWidget(b)
        self.adjustSize()
        self.hide()

    def eventFilter(self, obj, e):
        if obj is self._input and e.type() == QEvent.Type.KeyPress:
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._find(backward=bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                return True
            if e.key() == Qt.Key.Key_Escape:
                self.close_bar()
                return True
        return super().eventFilter(obj, e)

    def set_view(self, view):
        """Cambia la pestaña objetivo (al cambiar de pestaña)."""
        if view is self._view:
            return
        if self._view is not None:
            try:
                self._view.page().findTextFinished.disconnect(self._on_result)
                self._view.findText("")
            except (TypeError, RuntimeError):
                pass
        self._view = view
        if view is not None:
            view.page().findTextFinished.connect(self._on_result)
            if self.isVisible() and self._input.text():
                self._find()

    def open_bar(self, view):
        self.set_view(view)
        self.show()
        _relayout(self)
        self.raise_()
        sel = view.selectedText() if view else ""
        if sel and "\n" not in sel:
            self._input.setText(sel)
        self._input.setFocus()
        self._input.selectAll()
        if self._input.text():
            self._find()

    def close_bar(self):
        if self._view is not None:
            try:
                self._view.findText("")
                self._view.setFocus()
            except RuntimeError:
                pass
        self._count.setText("")
        self.hide()
        _relayout(self)

    def _find(self, backward=False):
        if self._view is None:
            return
        text = self._input.text()
        flags = QWebEnginePage.FindFlag.FindBackward if backward else QWebEnginePage.FindFlag(0)
        self._view.findText(text, flags)
        if not text:
            self._count.setText("")

    def _on_result(self, result):
        if not self._input.text():
            self._count.setText("")
            return
        total = result.numberOfMatches()
        self._count.setText(f"{result.activeMatch()}/{total}" if total else "0/0")
        color = "rgba(255,255,255,0.5)" if total else "#ff8a80"
        self._count.setStyleSheet(f"color:{color}; font-size:11px;")


# ─── Pestaña caída ────────────────────────────────────────────────────────────
class CrashOverlay(QFrame):
    """Se superpone a la vista cuando su proceso de renderizado muere."""
    _REASONS = {
        "CrashedTerminationStatus": "El proceso de la página falló.",
        "KilledTerminationStatus": "El proceso de la página fue terminado (posible falta de memoria).",
        "AbnormalTerminationStatus": "La página terminó de forma inesperada.",
    }

    def __init__(self, view: QWebEngineView):
        super().__init__(view)
        self._view = view
        self.setStyleSheet("CrashOverlay{background:#090911;}"
                           "QLabel{color:rgba(255,255,255,0.85); background:transparent;}")
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.setSpacing(10)
        t = QLabel("Esta pestaña dejó de funcionar")
        t.setStyleSheet("font-size:20px; font-weight:bold;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(t)
        self._reason = QLabel("")
        self._reason.setStyleSheet("color:rgba(255,255,255,0.55); font-size:13px;")
        self._reason.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self._reason)
        b = QPushButton("Volver a cargar")
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setStyleSheet("QPushButton{background:rgba(81,162,255,0.85); color:white; border:none;"
                        "border-radius:8px; padding:8px 18px; font-size:13px;}"
                        "QPushButton:hover{background:#51a2ff;}")
        b.clicked.connect(view.reload)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(b); row.addStretch()
        v.addLayout(row)
        self.hide()
        view.installEventFilter(self)
        view.renderProcessTerminated.connect(self._on_terminated)
        view.loadStarted.connect(self.hide)

    def eventFilter(self, obj, e):
        if obj is self._view and e.type() == QEvent.Type.Resize:
            self.setGeometry(self._view.rect())
        return False

    def _on_terminated(self, status, code):
        if status == QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus:
            return
        self._reason.setText(f"{self._REASONS.get(status.name, '')} (código {code})")
        self.setGeometry(self._view.rect())
        self.show()
        self.raise_()


# ─── DevTools ─────────────────────────────────────────────────────────────────
def toggle_devtools(view: QWebEngineView):
    """Abre/cierra las herramientas para desarrolladores de la pestaña (F12)."""
    win = getattr(view, "_devtools_win", None)
    if win is None:
        win = QMainWindow()
        # Ventana auxiliar: no debe mantener viva la app al cerrar la principal.
        win.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        dv = QWebEngineView(view.page().profile(), win)
        win.setCentralWidget(dv)
        win.resize(1100, 720)
        view.page().setDevToolsPage(dv.page())
        view._devtools_win = win
        view.destroyed.connect(win.deleteLater)
    if win.isVisible():
        win.hide()
    else:
        win.setWindowTitle(f"DevTools — {view.title() or view.url().toString()}")
        win.show()
        win.raise_()
        win.activateWindow()


# ─── Impresión / PDF ──────────────────────────────────────────────────────────
def print_page(view: QWebEngineView, parent):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dlg = QPrintDialog(printer, parent)
    dlg.setWindowTitle("Imprimir")
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    view._printer = printer  # vivo hasta printFinished
    view.print(printer)


def _safe_filename(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", title or "").strip()
    return (name[:80] or "pagina") + ".pdf"


def save_pdf(view: QWebEngineView, parent):
    default = os.path.join(downloads_dir(), _safe_filename(view.title()))
    path, _ = QFileDialog.getSaveFileName(parent, "Guardar como PDF", default, "PDF (*.pdf)")
    if not path:
        return
    if not path.lower().endswith(".pdf"):
        path += ".pdf"
    view.printToPdf(path)


def attach_print_feedback(view: QWebEngineView, parent, notify):
    """Conecta avisos de fin de impresión/PDF e impresión pedida por JS."""
    def on_print_done(ok):
        view._printer = None
        notify("Impresión", "Enviada a la impresora" if ok else "No se pudo imprimir")
    view.printFinished.connect(on_print_done)
    view.pdfPrintingFinished.connect(
        lambda path, ok: notify("PDF guardado" if ok else "Error al guardar PDF", os.path.basename(path)))
    view.printRequested.connect(lambda: print_page(view, parent))
