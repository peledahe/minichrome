"""Punto de entrada de Minichrome."""
import os
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from config import DICTIONARIES_DIR
from window import Minichrome
from widgets import Notif
from secure_store import encrypt_legacy_passwords

# ─── Arranque ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                          "--enable-features=WebRTCPipeWireCapturer")
    if os.path.isdir(DICTIONARIES_DIR):
        os.environ.setdefault("QTWEBENGINE_DICTIONARIES_PATH", DICTIONARIES_DIR)
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
    migrated = encrypt_legacy_passwords()
    w = Minichrome()
    w.show()
    if migrated:
        Notif("Contraseñas protegidas", f"{migrated} contraseña(s) cifrada(s) con el llavero del sistema", w)
    sys.exit(app.exec())
