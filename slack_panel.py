"""Panel lateral "Slack": lista de mensajes recientes de los canales del usuario.

Los datos vienen de slack_sync.client() (API oficial, token de usuario en el
llavero). Clic en un mensaje → se abre en Slack en una pestaña nueva; los
enlaces del mensaje también se abren en pestañas de Minichrome.
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QGuiApplication
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

import slack_sync

PANEL_WIDTH = 440
REFRESH_MS = 60_000      # mientras el panel está abierto
SLACK_APPS_URL = "https://api.slack.com/apps?new_app=1"

CARD_STYLE = """
    #slack_card{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(18,24,42,0.985), stop:1 rgba(12,16,30,0.985));
      border:1px solid rgba(120,160,255,0.18); border-radius:16px;}
    QLabel{background:transparent;}
    QLineEdit{background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.08);
      border-radius:10px; padding:8px 12px; color:#e8ecf8; font-size:12px;
      selection-background-color:rgba(81,162,255,0.45);}
    QLineEdit:focus{border-color:rgba(81,162,255,0.6); background:rgba(255,255,255,0.07);}
    QComboBox{background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.08);
      border-radius:10px; padding:6px 10px; color:#e8ecf8; font-size:12px;}
    QComboBox QAbstractItemView{background:#1a2033; color:#e8ecf8; selection-background-color:#3b4a7a;
      border:1px solid rgba(255,255,255,0.12);}
    QScrollArea{background:transparent; border:none;}
    QScrollBar:vertical{background:transparent; width:6px; margin:4px 0;}
    QScrollBar::handle:vertical{background:rgba(255,255,255,0.12); border-radius:3px; min-height:30px;}
    QScrollBar::handle:vertical:hover{background:rgba(255,255,255,0.25);}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0;}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{background:transparent;}
"""
HDR_BTN = ("QPushButton{background:transparent; border:none; border-radius:15px;"
           "color:rgba(255,255,255,0.55); font-size:13px;}"
           "QPushButton:hover{background:rgba(255,255,255,0.08); color:white;}")
ACTION_BTN = ("QPushButton{font-size:12px; background:rgba(255,255,255,0.05);"
              "border:1px solid rgba(255,255,255,0.08); border-radius:9px; color:rgba(230,236,255,0.85); padding:7px 10px;}"
              "QPushButton:hover{background:rgba(74,21,75,0.55); color:white; border-color:rgba(224,30,90,0.45);}")


class MessageCard(QFrame):
    def __init__(self, msg, open_url, on_dismiss, on_reply=None):
        super().__init__()
        self.msg = msg
        self._open_url = open_url
        self.setObjectName("msg")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Abrir en Slack")
        self.setStyleSheet("#msg{background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.05);"
                           "border-radius:12px;} #msg:hover{background:rgba(255,255,255,0.07);}")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 9)
        v.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        letter = (msg["author"][:1] or "?").upper()
        hue = sum(map(ord, msg["author"])) % 360
        av = QLabel(letter)
        av.setFixedSize(26, 26)
        av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        av.setStyleSheet(f"background:{QColor.fromHsl(hue, 140, 105).name()}; border-radius:7px;"
                         "color:white; font-size:12px; font-weight:600;")
        top.addWidget(av)
        who = QLabel(f"<b style='color:#eef1fb'>{_esc(msg['author'])}</b>"
                     f" <span style='color:rgba(190,200,230,0.55)'>{'🔒' if msg['private'] else '#'}"
                     f"{_esc(msg['channel'])}</span>")
        who.setStyleSheet("font-size:12px;")
        top.addWidget(who, 1)
        if msg["replies"]:
            r = QLabel(f"💬 {msg['replies']}")
            r.setToolTip("Respuestas en el hilo")
            r.setStyleSheet("color:#8fc0ff; font-size:11px;")
            top.addWidget(r)
        t = QLabel(msg["time"])
        t.setStyleSheet("color:rgba(190,200,230,0.45); font-size:11px;")
        top.addWidget(t)
        if on_reply:
            rb = QPushButton("↩")
            rb.setFixedSize(20, 20)
            rb.setToolTip("Responder en el hilo")
            rb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            rb.setStyleSheet("QPushButton{background:transparent; border:none; border-radius:10px;"
                             "color:rgba(255,255,255,0.32); font-size:12px;}"
                             "QPushButton:hover{background:rgba(81,162,255,0.18); color:#8fc0ff;}")
            rb.clicked.connect(lambda: on_reply(self))
            top.addWidget(rb)
        x = QPushButton("✕")
        x.setFixedSize(20, 20)
        x.setToolTip("Quitar de la lista (en Slack no se borra)")
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.setStyleSheet("QPushButton{background:transparent; border:none; border-radius:10px;"
                        "color:rgba(255,255,255,0.28); font-size:10px;}"
                        "QPushButton:hover{background:rgba(255,95,87,0.18); color:#ff6b62;}")
        x.clicked.connect(lambda: on_dismiss(self))
        top.addWidget(x)
        v.addLayout(top)

        body = QLabel(msg["html"] or "<i style='color:#8a93ad'>(sin texto)</i>")
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        body.setOpenExternalLinks(False)
        body.linkActivated.connect(self._open_url)
        body.setStyleSheet("color:#d8deef; font-size:12.5px;")
        v.addWidget(body)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._open_url(self.msg["permalink"])
        super().mouseReleaseEvent(e)


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SlackPanel(QFrame):
    def __init__(self, parent, open_url, on_close):
        super().__init__(parent)
        self.setObjectName("slack_card")
        self.setFixedWidth(PANEL_WIDTH)
        self.setStyleSheet(CARD_STYLE)
        self._open_url = open_url
        self.client = slack_sync.client()
        self.client.changed.connect(self._on_changed)
        self.client.app_created.connect(self._on_app_created)
        self.client.sent.connect(self._on_sent)
        self._reply_to = None   # mensaje al que se responde en hilo
        self._cards = []
        self._shown = None   # qué hay pintado: (conectado, error, ids de mensajes)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 12, 14)
        v.setSpacing(10)

        # Encabezado
        hdr = QHBoxLayout(); hdr.setSpacing(12)
        ico = QLabel("💬")
        ico.setFixedSize(38, 38)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #4a154b, stop:1 #e01e5a);"
                          "border-radius:11px; color:white; font-size:18px;")
        texts = QVBoxLayout(); texts.setSpacing(1)
        title = QLabel("Slack")
        title.setStyleSheet("color:#ffffff; font-size:15px; font-weight:600;")
        self.status = QLabel("")
        self.status.setStyleSheet("color:rgba(200,210,240,0.55); font-size:11px;")
        texts.addWidget(title); texts.addWidget(self.status)
        hdr.addWidget(ico); hdr.addLayout(texts, 1)
        for text, tip, slot in (("↻", "Actualizar", self.refresh), ("⚙", "Cuenta de Slack", self._account_menu),
                                ("✕", "Cerrar", on_close)):
            b = QPushButton(text)
            b.setFixedSize(30, 30)
            b.setToolTip(tip)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setStyleSheet(HDR_BTN)
            b.clicked.connect(slot)
            hdr.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
            if text == "⚙":
                self._gear = b
        v.addLayout(hdr)

        # Filtros
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en los mensajes…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.channel = QComboBox()
        self.channel.currentIndexChanged.connect(self._apply_filter)
        filt = QHBoxLayout(); filt.setSpacing(8)
        filt.addWidget(self.search, 3); filt.addWidget(self.channel, 2)
        self.filters = QWidget(); self.filters.setLayout(filt)
        filt.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.filters)

        # Lista
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_host.setStyleSheet("background:transparent;")
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 4, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch()
        self.scroll.setWidget(self.list_host)
        v.addWidget(self.scroll, 1)
        v.addWidget(self._build_composer())

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._render()

    # ── Ciclo de vida ────────────────────────────────────────────────────────
    def opened(self):
        self._timer.start(REFRESH_MS)
        if self.client.connected() and not self.client.state()["busy"]:
            self.refresh()
        self._render()

    def closed(self):
        self._timer.stop()

    def refresh(self):
        self.client.refresh()

    def _on_changed(self):
        self._render()

    # ── Pintado ──────────────────────────────────────────────────────────────
    def _clear(self):
        while self.list_lay.count() > 1:
            w = self.list_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._cards = []

    def _render(self):
        st = self.client.state()
        connected = st["connected"]
        self.filters.setVisible(connected)
        self.composer.setVisible(connected)
        self.perm_bar.setVisible(connected and not self.client.can_send())
        self.send_row.setVisible(connected and self.client.can_send())
        if st["busy"]:
            self.status.setText("Actualizando…")
        elif st["error"]:
            self.status.setText("⚠ " + st["error"])
        elif connected and st["team"]:
            self.status.setText(f"{st['team']} · {st['user']}")
        else:
            self.status.setText("Sin conectar" if not connected else "")
        self.status.setToolTip(st["error"])

        msgs = self.client.messages()
        key = (connected, st["error"] if not connected else "", tuple(m["id"] for m in msgs),
               tuple(c["id"] for c in self.client.channels()), bool(st["busy"]) and not msgs)
        if key == self._shown:
            return   # solo cambió el estado (actualizando…): no se reconstruye la lista
        self._shown = key
        scroll = self.scroll.verticalScrollBar().value()

        self._clear()
        if not connected:
            self.list_lay.insertWidget(0, self._setup_widget(st["error"]))
            return

        # Filtro de canales (conserva la selección)
        current = self.channel.currentData()
        self.channel.blockSignals(True)
        self.channel.clear()
        self.channel.addItem("Todos los canales", "")
        for c in self.client.channels():
            self.channel.addItem(("🔒 " if c["private"] else "# ") + c["name"], c["id"])
        idx = self.channel.findData(current)
        self.channel.setCurrentIndex(idx if idx >= 0 else 0)
        self.channel.blockSignals(False)
        # Canales para enviar (mismo orden; conserva la selección)
        cur_send = self.send_channel.currentData()
        self.send_channel.blockSignals(True)
        self.send_channel.clear()
        for c in self.client.channels():
            self.send_channel.addItem(("🔒 " if c["private"] else "# ") + c["name"], c["id"])
        idx = self.send_channel.findData(cur_send or self.channel.currentData())
        self.send_channel.setCurrentIndex(max(idx, 0))
        self.send_channel.blockSignals(False)

        if not msgs:
            self.list_lay.insertWidget(0, self._note("Cargando mensajes…" if st["busy"] else
                                                     "No hay mensajes recientes en tus canales."))
            return
        for i, m in enumerate(msgs):
            card = MessageCard(m, self._open_url, self._dismiss, self._reply)
            self._cards.append(card)
            self.list_lay.insertWidget(i, card)
        self._apply_filter()
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(scroll))

    def _apply_filter(self):
        q = self.search.text().strip().lower()
        chan = self.channel.currentData() or ""
        if chan and not self._reply_to:   # al filtrar un canal, se escribe en ese canal
            i = self.send_channel.findData(chan)
            if i >= 0:
                self.send_channel.setCurrentIndex(i)
        for card in self._cards:
            card.setVisible((not q or q in card.msg["search"]) and (not chan or card.msg["channel_id"] == chan))

    @staticmethod
    def _note(text):
        l = QLabel(text)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.setWordWrap(True)
        l.setStyleSheet("color:rgba(200,210,240,0.45); font-size:12px; padding:24px 8px;")
        return l

    def _setup_widget(self, error):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(10)
        has_app = self.client.has_app()
        if has_app:
            text = ("<b style='color:#eef1fb'>Conecta tu espacio de trabajo de Slack</b><br><br>"
                    "<span style='color:#c8d0e8'>Pulsa <b>Conectar con Slack</b>: se abrirá Slack en una pestaña; "
                    "elige tu espacio de trabajo y pulsa <b>Permitir</b>. Minichrome guarda el acceso y "
                    "cierra la pestaña solo.</span><br><br>"
                    "<span style='color:rgba(200,210,240,0.5); font-size:11px'>Permisos de solo lectura: canales, "
                    "sus mensajes y nombres de usuario. El acceso se guarda en el llavero del sistema.</span>")
        else:
            text = ("<b style='color:#eef1fb'>Conecta tu espacio de trabajo de Slack</b><br><br>"
                    "<span style='color:#c8d0e8'>Minichrome puede crear su app de Slack por ti:<br>"
                    "1. Abre <b>api.slack.com/apps</b> y, en <i>Your App Configuration Tokens</i>, pulsa "
                    "<i>Generate Token</i> (o <i>Copy</i> junto a <i>Access Token</i>).<br>"
                    "2. Pega ese token (empieza con <code>xoxe.xoxp-</code>) aquí abajo y pulsa <b>Crear app y conectar</b>.<br>"
                    "3. En la pestaña que se abre, pulsa <b>Permitir</b>.</span><br><br>"
                    "<span style='color:rgba(200,210,240,0.5); font-size:11px'>El token de configuración solo se usa "
                    "para crear la app y no se guarda. Si ya tienes un «User OAuth Token» (xoxp-), también "
                    "puedes pegarlo.</span>")
        steps = QLabel(text)
        steps.setWordWrap(True)
        steps.setStyleSheet("font-size:12px;")
        v.addWidget(steps)
        if error:
            e = QLabel("⚠ " + _esc(error))
            e.setWordWrap(True)
            e.setStyleSheet("color:#ff8a80; font-size:12px;")
            v.addWidget(e)

        primary = ("QPushButton{background:#4a154b; border:1px solid rgba(224,30,90,0.5); border-radius:9px;"
                   "color:white; font-size:12px; font-weight:600; padding:8px;}"
                   "QPushButton:hover{background:#611f69;} QPushButton:disabled{color:rgba(255,255,255,0.4);}")
        if has_app:
            b = QPushButton("Conectar con Slack")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setStyleSheet(primary)
            b.clicked.connect(self._start_oauth)
            v.addWidget(b)
        else:
            b = QPushButton("🌐  Abrir api.slack.com/apps")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setStyleSheet(ACTION_BTN)
            b.clicked.connect(lambda: self._open_url("https://api.slack.com/apps"))
            v.addWidget(b)

        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText("xoxp-… (opcional)" if has_app else "xoxe.xoxp-… o xoxp-…")
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.returnPressed.connect(self._connect)
        v.addWidget(self.token_edit)
        b2 = QPushButton("Usar token" if has_app else "Crear app y conectar")
        b2.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b2.setStyleSheet(ACTION_BTN if has_app else primary)
        b2.setEnabled(not self.client.state()["busy"])
        b2.clicked.connect(self._connect)
        v.addWidget(b2)
        return w

    # ── Envío ────────────────────────────────────────────────────────────────
    def _build_composer(self):
        self.composer = QWidget()
        v = QVBoxLayout(self.composer)
        v.setContentsMargins(0, 2, 0, 0)
        v.setSpacing(6)

        self.reply_bar = QWidget()
        rb = QHBoxLayout(self.reply_bar); rb.setContentsMargins(4, 0, 0, 0); rb.setSpacing(6)
        self.reply_lbl = QLabel()
        self.reply_lbl.setStyleSheet("color:#8fc0ff; font-size:11px;")
        cancel = QPushButton("✕")
        cancel.setFixedSize(18, 18)
        cancel.setToolTip("Cancelar respuesta")
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setStyleSheet(HDR_BTN)
        cancel.clicked.connect(self._cancel_reply)
        rb.addWidget(self.reply_lbl, 1); rb.addWidget(cancel)
        self.reply_bar.hide()
        v.addWidget(self.reply_bar)

        self.perm_bar = QWidget()
        pb = QHBoxLayout(self.perm_bar); pb.setContentsMargins(0, 0, 0, 0); pb.setSpacing(8)
        pl = QLabel("Para enviar mensajes, Slack pide autorizar el permiso nuevo una vez.")
        pl.setWordWrap(True)
        pl.setStyleSheet("color:#ffd479; font-size:11px;")
        pbtn = QPushButton("Volver a autorizar")
        pbtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        pbtn.setStyleSheet(ACTION_BTN)
        pbtn.clicked.connect(self._start_oauth)
        pb.addWidget(pl, 1); pb.addWidget(pbtn)
        v.addWidget(self.perm_bar)

        self.send_row = QWidget()
        row = QHBoxLayout(self.send_row); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(6)
        self.send_channel = QComboBox()
        self.send_channel.setToolTip("Canal donde se envía")
        self.send_channel.setFixedWidth(130)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Escribe un mensaje…")
        self.input.returnPressed.connect(self._send)
        self.send_btn = QPushButton("➤")
        self.send_btn.setFixedSize(36, 34)
        self.send_btn.setToolTip("Enviar (Enter)")
        self.send_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.send_btn.setStyleSheet("QPushButton{background:#4a154b; border:1px solid rgba(224,30,90,0.5);"
                                    "border-radius:10px; color:white; font-size:14px;}"
                                    "QPushButton:hover{background:#611f69;}"
                                    "QPushButton:disabled{color:rgba(255,255,255,0.35);}")
        self.send_btn.clicked.connect(self._send)
        row.addWidget(self.send_channel); row.addWidget(self.input, 1); row.addWidget(self.send_btn)
        v.addWidget(self.send_row)
        self.send_note = QLabel()
        self.send_note.setWordWrap(True)
        self.send_note.hide()
        v.addWidget(self.send_note)
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(self.send_note.hide)
        return self.composer

    def _show_send_note(self, text, ok):
        self.send_note.setText(text)
        self.send_note.setStyleSheet(f"color:{'#5fd38d' if ok else '#ff8a80'}; font-size:11px; padding-left:4px;")
        self.send_note.show()
        self._note_timer.stop()
        if ok:
            self._note_timer.start(4000)

    def _reply(self, card):
        self._reply_to = card.msg
        i = self.send_channel.findData(card.msg["channel_id"])
        if i >= 0:
            self.send_channel.setCurrentIndex(i)
        self.send_channel.setEnabled(False)
        self.reply_lbl.setText(f"↩ Respondiendo en el hilo de {_esc(card.msg['author'])} en #{_esc(card.msg['channel'])}")
        self.reply_bar.show()
        self.input.setPlaceholderText("Escribe tu respuesta…")
        self.input.setFocus()

    def _cancel_reply(self):
        self._reply_to = None
        self.send_channel.setEnabled(True)
        self.reply_bar.hide()
        self.input.setPlaceholderText("Escribe un mensaje…")

    def _send(self):
        text = self.input.text().strip()
        if not text:
            return
        reply = self._reply_to
        channel = reply["channel_id"] if reply else self.send_channel.currentData()
        self.input.setEnabled(False)
        self.send_btn.setEnabled(False)
        self._show_send_note("Enviando…", True)
        self._note_timer.stop()
        self.client.send(channel, text, reply["slack_ts"] if reply else None)

    def _on_sent(self, ok, error):
        self.input.setEnabled(True)
        self.send_btn.setEnabled(True)
        if ok:
            self.input.clear()
            self._cancel_reply()
            self._show_send_note("✓ Mensaje enviado", True)
        else:
            self._show_send_note("⚠ " + error, False)   # el texto se conserva para reintentar
            can = self.client.can_send()
            self.perm_bar.setVisible(not can)
            self.send_row.setVisible(can)
        self.input.setFocus()

    # ── Acciones ─────────────────────────────────────────────────────────────
    def _copy_manifest(self):
        QGuiApplication.clipboard().setText(slack_sync.SLACK_APP_MANIFEST)
        self.status.setText("Manifiesto copiado al portapapeles")

    def _connect(self):
        token = self.token_edit.text().strip() if hasattr(self, "token_edit") else ""
        if token.startswith("xoxe"):
            self.status.setText("Creando la app de Slack…")
            self.client.create_app_and_connect(token)
            return
        self.status.setText("Verificando el token…")
        self.client.connect(token)

    def _dismiss(self, card):
        self.client.dismiss(card.msg["id"])
        if card in self._cards:
            self._cards.remove(card)
        card.hide()
        card.deleteLater()
        self._shown = None   # la próxima actualización vuelve a pintar sin ese mensaje
        if not self._cards:
            self.list_lay.insertWidget(0, self._note("No quedan mensajes en la lista."))

    def _start_oauth(self):
        url = self.client.start_oauth()
        if url:
            self.status.setText("Autoriza a Minichrome en la pestaña de Slack…")
            self._open_url(url)

    def _on_app_created(self, ok):
        self._shown = None
        self._render()
        if ok:
            self._start_oauth()

    def _account_menu(self):
        m = QMenu(self)
        if self.client.connected():
            m.addAction("Actualizar ahora", self.refresh)
            m.addAction("Abrir Slack en una pestaña", lambda: self._open_url("https://app.slack.com/client"))
            hidden = self.client.dismissed_count()
            act = m.addAction(f"Mostrar mensajes quitados ({hidden})", self.client.restore_dismissed)
            act.setEnabled(hidden > 0)
            m.addSeparator()
            m.addAction("Desconectar Slack", self.client.disconnect)
        else:
            if self.client.has_app():
                m.addAction("Conectar con Slack", self._start_oauth)
            m.addAction("Copiar manifiesto de la app", self._copy_manifest)
            m.addAction("Abrir api.slack.com", lambda: self._open_url(SLACK_APPS_URL))
        m.exec(self._gear.mapToGlobal(self._gear.rect().bottomLeft()))
