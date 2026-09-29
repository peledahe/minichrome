"""Ventana principal Minichrome."""
import os
import json
import browser_features as bf
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QSizePolicy, QFrame, QScrollArea, QListWidget, QListWidgetItem, QDialog,
    QStackedLayout, QDateEdit, QMenu
)
from PyQt6.QtCore import (
    QUrl, QUrlQuery, Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QRect, QDate
)
from PyQt6.QtGui import QCursor, QFont, QIcon
from config import BASE, HOME, load_settings, save_settings
from db import clear_history, clear_history_by_dates, clear_history_by_domain, del_fav, del_history, get_config, get_favs, get_history, get_screenshots_dir, get_url_history, save_fav, save_screenshot, set_config
from widgets import BTN_NAV, Notif, _shadow
from browser import WebView, profile

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

        # ── Funciones estándar (descargas, búsqueda, sesión) ──────────────────
        notify = lambda t, b: Notif(t, b, self)
        self._downloads = bf.DownloadsPanel(root, notify)
        self._find_bar = bf.FindBar(root)
        self._closed_tabs: list[str] = []
        profile().downloadRequested.connect(self._downloads.handle_request)
        profile().setNotificationPresenter(self._present_web_notification)
        QApplication.instance().aboutToQuit.connect(self._save_session)

        self._open_initial_tabs()
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
        
        self._fav = self._nb("☆", "Guardar favorito")
        self._fav.clicked.connect(self._save_fav)

        self._shot = QPushButton("◉")
        self._shot.setFixedSize(20, 20)
        self._shot.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._shot.setToolTip("Capturar pantalla (Ctrl+Shift+S)")
        self._shot.setFont(QFont("DejaVu Sans", 10, QFont.Weight.DemiBold))
        self._shot.setStyleSheet("""
            QPushButton{background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1);
                border-radius:6px; color:rgba(255,255,255,0.8); padding:0;}
            QPushButton:hover{background:#6c5ce7; border-color:#8f7bff; color:white;}
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
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(4)
        h.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        w.setStyleSheet("""
            background:rgba(0,0,0,0.42);
            border:1px solid rgba(255,255,255,0.1);
            border-radius:8px;
        """)

        specs = [
            ("◷", "#3498db", self._toggle_hist_panel, "Historial de navegación"),
            ("★", "#9b59b6", self._toggle_fav_panel, "Favoritos guardados"),
            ("⋮", "#51a2ff", self._show_main_menu, "Más opciones"),
            ("—", "#febc2e", self.showMinimized, "Minimizar ventana"),
            ("2x", "#16a085", self._expand_two_screens_left, "Expandir a 2 pantallas desde la izquierda (Ctrl+Shift+2)"),
            ("▢", "#28c840", self._toggle_max, "Maximizar / Restaurar"),
            ("✕", "#ff5f57", self.close, "Cerrar ventana"),
        ]
        for sym, col, fn, tip in specs:
            b = QPushButton(sym)
            b.setFixedSize(20, 20)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setToolTip(tip)
            b.setFont(QFont("DejaVu Sans", 10, QFont.Weight.DemiBold))
            b.setStyleSheet(f"""
                QPushButton{{background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1);
                    border-radius:6px; color:rgba(255,255,255,0.8); padding:0;}}
                QPushButton:hover{{background:{col}; border-color:{col}; color:white;}}
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

    def _expand_two_screens_left(self):
        screens = QApplication.screens()
        if not screens:
            return

        ordered = sorted(screens, key=lambda s: s.availableGeometry().x())
        target = ordered[:2]

        if self.isMaximized() or self.isFullScreen():
            self.showNormal()

        geoms = [s.availableGeometry() for s in target]
        left = min(g.x() for g in geoms)
        top = min(g.y() for g in geoms)
        right = max(g.x() + g.width() for g in geoms)
        bottom = max(g.y() + g.height() for g in geoms)

        self.setGeometry(QRect(left, top, right - left, bottom - top))
        self.raise_()
        self.activateWindow()
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
        self._place_overlays()

    def _place_overlays(self):
        """Barra de búsqueda y panel de descargas, alineados a la derecha."""
        if not hasattr(self, "_find_bar"):
            return
        W = self.width()
        top = (10 + self.TOTAL + 8) if self._bar_open else 12
        self._find_bar.adjustSize()
        self._find_bar.move(W - self._find_bar.width() - 12, top)
        self._find_bar.raise_()
        dl_top = top + (self._find_bar.height() + 8 if self._find_bar.isVisible() else 0)
        self._downloads.adjustSize()
        self._downloads.move(W - self._downloads.width() - 12, dl_top)
        self._downloads.raise_()

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
        self._place_overlays()

    def _hide_bar(self):
        self._bar_open = False
        self._win_ctrl.hide()
        self._place_overlays()
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
        if hasattr(self, "_find_bar"):
            self._find_bar.set_view(self._cur())

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
        closed_url = self._views[idx].url().toString()
        if closed_url:
            self._closed_tabs.append(closed_url)
            del self._closed_tabs[:-25]
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
    # ── Menú "Más opciones" y funciones estándar ──────────────────────────────
    _MENU_SS = """
        QMenu{background:rgba(12,18,35,0.98); border:1px solid rgba(81,162,255,0.25);
          border-radius:8px; padding:6px; color:rgba(255,255,255,0.85); font-size:12px;}
        QMenu::item{padding:6px 24px 6px 12px; border-radius:5px;}
        QMenu::item:selected{background:rgba(81,162,255,0.3); color:white;}
        QMenu::item:disabled{color:rgba(255,255,255,0.3);}
        QMenu::separator{height:1px; background:rgba(255,255,255,0.08); margin:5px 8px;}
        QMenu::indicator{width:12px; height:12px; left:4px;}
    """

    def _show_main_menu(self):
        btn = self.sender()
        v = self._cur()
        is_web = bool(v) and v.url().scheme() in ("http", "https")
        menu = QMenu(self)
        menu.setStyleSheet(self._MENU_SS)

        def add(text, fn, enabled=True):
            act = menu.addAction(text)
            act.triggered.connect(fn)
            act.setEnabled(enabled)
            return act

        add("Nueva pestaña\tCtrl+T", lambda: self.new_tab(HOME))
        add("Reabrir pestaña cerrada\tCtrl+Shift+T", self._reopen_closed_tab, bool(self._closed_tabs))
        menu.addSeparator()
        add("Descargas\tCtrl+J", self._downloads.toggle)
        add("Buscar en la página…\tCtrl+F", self._open_find, bool(v))
        add("Imprimir…\tCtrl+P", lambda: bf.print_page(v, self), bool(v))
        add("Guardar como PDF…", lambda: bf.save_pdf(v, self), bool(v))
        menu.addSeparator()
        add("Herramientas para desarrolladores\tF12", self._toggle_devtools, bool(v))
        add("Restablecer permisos de este sitio", self._reset_site_permissions, is_web)
        menu.addSeparator()
        for text, key, fn in (("Restaurar pestañas al iniciar", "restoreSession", None),
                              ("Corrector ortográfico (español)", "spellCheckEnabled", self._apply_spellcheck)):
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(get_config(key, "0") == "1")
            act.toggled.connect(lambda on, k=key, f=fn: (set_config(k, "1" if on else "0"), f and f(on)))

        pos = btn.mapToGlobal(QPoint(btn.width() - menu.sizeHint().width(), btn.height() + 6)) \
            if isinstance(btn, QWidget) else QCursor.pos()
        menu.exec(pos)

    def _open_find(self):
        v = self._cur()
        if v:
            self._find_bar.open_bar(v)
            self._place_overlays()

    def _toggle_devtools(self):
        v = self._cur()
        if v:
            bf.toggle_devtools(v)

    def _reset_site_permissions(self):
        v = self._cur()
        if not v:
            return
        n = bf.reset_site_permissions(profile(), v.url())
        Notif("Permisos restablecidos", f"{v.url().host()}: {n} permiso(s)" if n else "Este sitio no tenía permisos guardados", self)

    def _apply_spellcheck(self, on):
        profile().setSpellCheckEnabled(bool(on))

    def _present_web_notification(self, notification):
        """Muestra las notificaciones web (sitios con permiso) con el estilo de la app."""
        notification.show()
        host = notification.origin().host()
        Notif(notification.title() or host, notification.message(), self)

    def _reopen_closed_tab(self):
        if self._closed_tabs:
            self.new_tab(self._closed_tabs.pop())

    def _save_session(self):
        tabs = [v.url().toString() for v in self._views if v.url().toString()]
        set_config("lastSessionTabs", json.dumps({"tabs": tabs, "active": self._active}))

    def _open_initial_tabs(self):
        """Por defecto abre la página de inicio; restaura la sesión solo si se activó."""
        if get_config("restoreSession", "0") == "1":
            try:
                data = json.loads(get_config("lastSessionTabs", "") or "{}")
            except ValueError:
                data = {}
            tabs = [u for u in data.get("tabs", []) if isinstance(u, str) and u]
            if tabs:
                for u in tabs:
                    self.new_tab(u)
                active = data.get("active", 0)
                self._switch(active if isinstance(active, int) and 0 <= active < len(tabs) else 0)
                return
        self.new_tab(HOME)

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
        elif m == CS and k == Qt.Key.Key_2:    self._expand_two_screens_left()
        elif m == C and k == Qt.Key.Key_Equal: self._zoom_in_act()   # Ctrl++
        elif m == C and k == Qt.Key.Key_Minus: self._zoom_out_act()  # Ctrl+-
        elif m == C and k == Qt.Key.Key_0:     self._zoom_reset()    # Ctrl+0
        elif k == Qt.Key.Key_F5:               self._go_reload()
        elif k == Qt.Key.Key_Escape:
            self._hide_bar() if self._bar_open else self._show_bar()
        elif k == Qt.Key.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
        elif m == CS and k == Qt.Key.Key_T:    self._reopen_closed_tab()
        elif m == C and k == Qt.Key.Key_J:     self._downloads.toggle(); self._place_overlays()
        elif m == C and k == Qt.Key.Key_F:     self._open_find()
        elif m == C and k == Qt.Key.Key_P:
            if self._cur(): bf.print_page(self._cur(), self)
        elif k == Qt.Key.Key_F12 or (m == CS and k == Qt.Key.Key_I):
            self._toggle_devtools()
        else: super().keyPressEvent(e)
