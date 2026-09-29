"""Captura de área del escritorio (equivalente al overlay de ScreenShot).

Minimiza Minichrome, captura la pantalla donde está la ventana y muestra una
capa a pantalla completa para arrastrar el área: fondo oscurecido, el área
elegida en claro con borde azul discontinuo, medidas en px y Esc para cancelar.
"""
from PyQt6.QtCore import Qt, QRect, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QGuiApplication, QPixmap
from PyQt6.QtWidgets import QWidget

HINT_BEFORE = "📸  Haz clic sostenido y arrastra para seleccionar el área"


class AreaSelector(QWidget):
    def __init__(self, pixmap: QPixmap, geometry: QRect, on_done):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(geometry)
        self._pix = pixmap
        self._on_done = on_done
        self._start = None
        self._end = None
        self._finished = False

    def _rect(self) -> QRect:
        if not self._start or not self._end:
            return QRect()
        # Igual que ScreenShot: ancho/alto = diferencia exacta (QRect(p1, p2) incluye el píxel final)
        x, y = min(self._start.x(), self._end.x()), min(self._start.y(), self._end.y())
        return QRect(x, y, abs(self._end.x() - self._start.x()), abs(self._end.y() - self._start.y()))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self._pix)
        p.fillRect(self.rect(), QColor(0, 0, 0, 115))  # oscurecido (0.45)
        r = self._rect()
        if r.width() > 0 and r.height() > 0:
            p.drawPixmap(r, self._pix, self._source_rect(r))
            pen = QPen(QColor("#3b82f6"), 2, Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([3, 2])
            p.setPen(pen)
            p.drawRect(r)
            p.setPen(QPen(QColor(255, 255, 255, 204), 1))
            p.drawRect(r.adjusted(-1, -1, 1, 1))
            self._draw_badge(p, r)
        else:
            self._draw_hint(p)
        p.end()

    def _source_rect(self, r: QRect) -> QRect:
        sx = self._pix.width() / max(1, self.width())
        sy = self._pix.height() / max(1, self.height())
        return QRect(round(r.x() * sx), round(r.y() * sy), round(r.width() * sx), round(r.height() * sy))

    def _draw_hint(self, p: QPainter):
        # "📸 Haz clic… área [Esc] para cancelar", con Esc como tecla (igual que ScreenShot)
        f = QFont("Inter", 10)
        f.setWeight(QFont.Weight.Medium)
        p.setFont(f)
        fm = p.fontMetrics()
        before, key, after = HINT_BEFORE, "Esc", "para cancelar"
        kf = QFont("Inter", 8)
        kf.setWeight(QFont.Weight.Bold)
        kfm = QFontMetrics(kf)
        key_w = kfm.horizontalAdvance(key) + 14
        gap = 10
        total = fm.horizontalAdvance(before) + gap + key_w + 6 + fm.horizontalAdvance(after) + 40
        box = QRect((self.width() - total) // 2, 24, total, 36)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 41), 1))
        p.setBrush(QColor(18, 18, 28, 224))
        p.drawRoundedRect(box, 18, 18)
        x = box.x() + 20
        p.setPen(QColor("#f1f5f9"))
        p.drawText(QRect(x, box.y(), fm.horizontalAdvance(before), box.height()), Qt.AlignmentFlag.AlignVCenter, before)
        x += fm.horizontalAdvance(before) + gap
        key_rect = QRect(x, box.y() + 8, key_w, box.height() - 16)
        p.setPen(QPen(QColor(255, 255, 255, 64), 1))
        p.setBrush(QColor(255, 255, 255, 38))
        p.drawRoundedRect(key_rect, 6, 6)
        p.setFont(kf)
        p.setPen(QColor("#ffffff"))
        p.drawText(key_rect, Qt.AlignmentFlag.AlignCenter, key)
        p.setFont(f)
        p.setPen(QColor("#f1f5f9"))
        x += key_w + 6
        p.drawText(QRect(x, box.y(), fm.horizontalAdvance(after) + 4, box.height()), Qt.AlignmentFlag.AlignVCenter, after)

    def _draw_badge(self, p: QPainter, r: QRect):
        text = f"{r.width()} x {r.height()} px"
        f = QFont("Inter", 9)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(text) + 20
        x, y = r.right() + 8, r.bottom() + 8
        if x + w > self.width():
            x = r.right() - w - 5
        if y + 26 > self.height():
            y = r.bottom() - 31
        badge = QRect(max(8, x), max(8, y), w, 24)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3b82f6"))
        p.drawRoundedRect(badge, 6, 6)
        p.setPen(QColor("#ffffff"))
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = self._end = e.position().toPoint()
            self.update()

    def mouseMoveEvent(self, e):
        if self._start is not None:
            self._end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._end = e.position().toPoint()
        r = self._rect()
        if r.width() > 8 and r.height() > 8:
            self._finish(self._pix.copy(self._source_rect(r)))
        else:  # clic sin arrastrar: volver a mostrar la pista
            self._start = self._end = None
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._finish(None)

    def closeEvent(self, e):
        if not self._finished:
            self._finished = True
            self._on_done(None)
        super().closeEvent(e)

    def _finish(self, pixmap):
        if self._finished:
            return
        self._finished = True
        self.close()
        self._on_done(pixmap)


_active = None


def capture_area(window, on_done, delay_ms=350):
    """Minimiza `window`, captura su pantalla y deja elegir un área.

    on_done(QPixmap | None) se llama con el recorte, o None si se canceló.
    La ventana se restaura en ambos casos.
    """
    if _active is not None:
        return
    was_max, was_full = window.isMaximized(), window.isFullScreen()
    screen = window.screen() or QGuiApplication.primaryScreen()

    def restore():
        if was_full:
            window.showFullScreen()
        elif was_max:
            window.showMaximized()
        else:
            window.showNormal()
        window.raise_()
        window.activateWindow()

    def done(pixmap):
        global _active
        _active = None
        restore()
        on_done(pixmap)

    def grab():
        global _active
        pix = screen.grabWindow(0)
        if pix.isNull():
            restore()
            on_done(None)
            return
        _active = AreaSelector(pix, screen.geometry(), done)
        _active.showFullScreen()
        _active.activateWindow()
        _active.raise_()

    window.showMinimized()
    QTimer.singleShot(delay_ms, grab)  # dar tiempo a que la ventana desaparezca
