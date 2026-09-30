"""Reproductor nativo (QtMultimedia) para videos que QtWebEngine no decodifica.

El QtWebEngine de PyPI se compila sin códecs propietarios (H.264, H.265, AAC...),
así que la mayoría de los .mp4 fallan en el <video> de la página. QtMultimedia trae
su propio FFmpeg y sí los reproduce: el visor de videos superpone este widget sobre
el <video> cuando `playback_mode()` dice "native".

La interfaz (video + controles) está en native_video.qml. Se usa QQuickWidget y no
QVideoWidget porque este último es una ventana nativa: no admite controles encima
ni transparencia. El QQuickWidget es transparente y el QML recorta los "huecos" donde
la página queda sobre el video (lista, avisos, cabecera del modo cine).
"""
import json
import os
import shutil
import subprocess

from PyQt6.QtCore import Q_ARG, QMetaObject, QRect, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QRegion
from PyQt6.QtQuickWidgets import QQuickWidget

# Lo que decodifica el Chromium de QtWebEngine sin códecs propietarios.
WEB_VIDEO_CODECS = {"vp8", "vp9", "av1", "theora"}
WEB_AUDIO_CODECS = {"opus", "vorbis", "mp3", "flac"}
# El FFmpeg de QtMultimedia solo decodifica AV1 por hardware (VAAPI); sin GPU compatible falla.
NATIVE_UNSUPPORTED_VIDEO = {"av1"}

QML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "native_video.qml")

_probe_cache: dict = {}


def probe(path):
    """Códecs y duración vía ffprobe; None si ffprobe no está o falla."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_mtime, st.st_size)
    if key in _probe_cache:
        return _probe_cache[key]
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,codec_name:format=duration", "-of", "json", path],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(out.stdout or "{}")
    except (subprocess.SubprocessError, ValueError):
        return None
    info = {"video": None, "audio": None, "duration": 0.0}
    for s in data.get("streams", []):
        kind = s.get("codec_type")
        if kind in ("video", "audio") and not info[kind]:
            info[kind] = (s.get("codec_name") or "").lower()
    try:
        info["duration"] = float(data.get("format", {}).get("duration") or 0)
    except ValueError:
        pass
    _probe_cache[key] = info
    return info


def playback_mode(path):
    """"web" si QtWebEngine puede reproducirlo, "native" si hace falta QtMultimedia."""
    info = probe(path)
    if not info:
        return "web"  # sin ffprobe: la página intenta y cae a nativo si da error
    v, a = info["video"], info["audio"]
    if v in NATIVE_UNSUPPORTED_VIDEO:
        return "web"  # mejor sin audio en la página que sin imagen en el nativo
    if v and v not in WEB_VIDEO_CODECS:
        return "native"
    if a and a not in WEB_AUDIO_CODECS and not a.startswith("pcm_"):
        return "native"
    return "web"


def thumbnail_args(path):
    """Argumentos de ffmpeg para una miniatura JPEG 160x90 por stdout."""
    info = probe(path) or {}
    duration = info.get("duration") or 0
    at = min(15.0, duration * 0.1) if duration else 0
    return ["-v", "error", "-ss", f"{at:.2f}", "-i", path, "-frames:v", "1",
            "-vf", "scale=160:90", "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "6", "pipe:1"]


class NativeVideoPlayer(QQuickWidget):
    """Video + controles (QML), hijo del WebView y superpuesto sobre #main-player."""

    media_event = pyqtSignal(str)  # JSON {type: playing|paused|time|ended|error|activity|action, ...}

    def __init__(self, view):
        super().__init__(view)
        self._view = view
        self._layout = None
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        # Transparente y compuesto encima: en los huecos del QML se ve la página de debajo.
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop)
        self.setClearColor(QColor(Qt.GlobalColor.transparent))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSource(QUrl.fromLocalFile(QML_PATH))
        self._root = self.rootObject()
        if self._root is None:
            raise RuntimeError("; ".join(e.toString() for e in self.errors()))
        self._root.mediaEvent.connect(self.media_event)
        view.loadStarted.connect(self.stop)  # navegar o recargar reinicia el estado de la página
        self.hide()

    # ─── API usada por el bridge ─────────────────────────────────────────────
    def play(self, path, start, muted):
        QMetaObject.invokeMethod(self._root, "load", Q_ARG(str, QUrl.fromLocalFile(path).toString()),
                                 Q_ARG(float, max(0.0, float(start or 0))), Q_ARG(bool, bool(muted)))
        self._apply()

    def command(self, cmd):
        if cmd == "stop":
            self.stop()
            return
        QMetaObject.invokeMethod(self._root, "command", Q_ARG(str, cmd))
        if cmd == "focus" and self.isVisible():
            self.setFocus()

    def stop(self):
        QMetaObject.invokeMethod(self._root, "stopPlayback")
        self._layout = None
        self.hide()

    def set_layout(self, data):
        """data (px CSS, relativos al viewport): x, y, w, h, visible, cover, cinema, title,
        holes = [[x, y, w, h], ...] zonas donde la página queda encima del video."""
        self._layout = data
        for prop in ("cover", "cinema"):
            self._root.setProperty(prop, bool(data.get(prop)))
        self._root.setProperty("title", str(data.get("title") or ""))
        self._apply()

    # ─── Internos ────────────────────────────────────────────────────────────
    def _apply(self):
        d = self._layout
        if not d or not d.get("visible") or not self._root.property("active"):
            self.hide()
            return
        z = self._view.zoomFactor() or 1.0
        px = lambda v: round(float(v) * z)
        x, y = px(d["x"]), px(d["y"])
        rect = QRect(x, y, px(d["w"]), px(d["h"]))
        if rect.isEmpty():
            self.hide()
            return
        self.setGeometry(rect)
        holes = [[px(hx) - x, px(hy) - y, px(hw), px(hh)] for hx, hy, hw, hh in d.get("holes") or []]
        self._root.setProperty("holes", holes)  # recorte visual (QML)
        # La máscara de QWidget no afecta al pintado de un QQuickWidget, pero sí a los clics:
        # en los huecos el ratón llega a la página.
        region = QRegion(0, 0, rect.width(), rect.height())
        for h in holes:
            region -= QRegion(*h)
        if holes:
            self.setMask(region)
        else:
            self.clearMask()
        was_hidden = not self.isVisible()
        self.show()
        self.raise_()
        if was_hidden:
            self.setFocus()
