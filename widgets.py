"""Estilos y widgets Qt compartidos."""
from PyQt6.QtWidgets import QVBoxLayout, QLabel, QFrame, QGraphicsDropShadowEffect
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor

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
