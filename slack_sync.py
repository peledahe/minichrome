"""Mensajes de Slack para el panel lateral de Minichrome (API oficial).

Usa un token de usuario (xoxp-) de una app de Slack creada por el usuario en su
espacio de trabajo (ver SLACK_APP_MANIFEST). El token vive en el llavero del
sistema, igual que la cuenta de Google. Solo lectura: canales en los que está el
usuario (públicos y privados) y sus mensajes recientes.

Las llamadas HTTP corren en un hilo; la interfaz escucha `changed`.
"""
import html
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import keyring
from PyQt6.QtCore import QObject, pyqtSignal

from db import get_config, set_config

KEYRING_SERVICE = "minichrome"
TOKEN_ACCOUNT = "slack-user-token"
APP_ACCOUNT = "slack-app-client"   # {"app_id", "client_id", "client_secret"} de la app creada
API = "https://slack.com/api/"
AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
# Slack exige HTTPS en el redirect. Minichrome intercepta esta dirección antes de
# cargarla (browser.WebPage.acceptNavigationRequest), así que nunca sale a la red.
REDIRECT_URI = "https://localhost/minichrome-slack-oauth"

MAX_CHANNELS = 40          # canales consultados por actualización
MESSAGES_PER_CHANNEL = 20
MAX_MESSAGES = 300         # total que se muestra en el panel
USERS_TTL = 3600           # segundos que se reutiliza la lista de usuarios
DISMISSED_KEY = "slackDismissed"   # app_config: ids "canal:ts" ocultados por el usuario
MAX_DISMISSED = 3000

USER_SCOPES = ["channels:history", "channels:read", "chat:write", "groups:history", "groups:read", "users:read"]

SLACK_APP_MANIFEST = json.dumps({
    "display_information": {
        "name": "Minichrome",
        "description": "Mensajes de Slack en el panel lateral de Minichrome",
    },
    "oauth_config": {"redirect_urls": [REDIRECT_URI], "scopes": {"user": USER_SCOPES}},
    "settings": {"org_deploy_enabled": False, "socket_mode_enabled": False, "token_rotation_enabled": False},
}, indent=2, ensure_ascii=False)

# Mensajes de sistema que no aportan a la lista
_SKIP_SUBTYPES = {"channel_join", "channel_leave", "channel_topic", "channel_purpose", "channel_name",
                  "channel_archive", "channel_unarchive", "group_join", "group_leave", "pinned_item",
                  "unpinned_item", "bot_add", "bot_remove"}


class SlackError(Exception):
    pass


def _kr_get():
    try:
        return keyring.get_password(KEYRING_SERVICE, TOKEN_ACCOUNT)
    except Exception:
        return None


def _kr_app():
    try:
        raw = keyring.get_password(KEYRING_SERVICE, APP_ACCOUNT)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _post(method, form, token=None):
    """POST de formulario a la Web API (apps.manifest.create, oauth.v2.access)."""
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + method, data=urllib.parse.urlencode(form).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SlackError(f"Slack respondió HTTP {e.code}")
    except urllib.error.URLError as e:
        raise SlackError(f"Sin conexión con Slack ({e.reason})")
    if not data.get("ok"):
        err = data.get("error", "error desconocido")
        detail = "; ".join(f"{x.get('pointer', '')} {x.get('message', '')}".strip() for x in data.get("errors") or [])
        raise SlackError({
            "invalid_auth": "El token de configuración no es válido o ya caducó (duran 12 horas).",
            "token_expired": "El token de configuración caducó: genera otro en api.slack.com/apps.",
            "ratelimited": "Slack no deja crear apps tan seguido; espera unos minutos.",
            "invalid_code": "La autorización de Slack caducó; vuelve a pulsar «Conectar con Slack».",
            "bad_redirect_uri": "La dirección de regreso de la app no coincide; vuelve a crear la app.",
        }.get(err, f"Slack: {err}" + (f" ({detail})" if detail else "")))
    return data


def create_app(config_token):
    """Crea la app «Minichrome» con el manifiesto usando un token de configuración
    (xoxe.xoxp-…) y guarda sus credenciales en el llavero. Devuelve el app_id."""
    data = _post("apps.manifest.create", {"manifest": SLACK_APP_MANIFEST}, token=config_token)
    cred = data.get("credentials") or {}
    app = {"app_id": data.get("app_id", ""), "client_id": cred.get("client_id", ""),
           "client_secret": cred.get("client_secret", "")}
    if not app["client_id"] or not app["client_secret"]:
        raise SlackError("Slack creó la app pero no devolvió sus credenciales.")
    keyring.set_password(KEYRING_SERVICE, APP_ACCOUNT, json.dumps(app))
    return app["app_id"]


_GRANTED_SCOPES = {}   # token -> permisos que Slack dice que tiene (cabecera x-oauth-scopes)


def update_app(config_token):
    """Actualiza la app existente al manifiesto actual (p. ej. permisos nuevos)."""
    app = _kr_app()
    if not app or not app.get("app_id"):
        return create_app(config_token)
    _post("apps.manifest.update", {"app_id": app["app_id"], "manifest": SLACK_APP_MANIFEST}, token=config_token)
    return app["app_id"]


def slack_escape(text):
    """Slack interpreta &, < y > como marcas: el texto del usuario va escapado."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _call(method, token, **params):
    """GET a la Web API de Slack; devuelve el JSON o lanza SlackError."""
    url = API + method + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read() or b"{}")
                scopes = resp.headers.get("x-oauth-scopes")
                if scopes is not None:
                    _GRANTED_SCOPES[token] = {x.strip() for x in scopes.split(",") if x.strip()}
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:   # límite de peticiones: esperar lo que indique Slack
                time.sleep(min(30, int(e.headers.get("Retry-After", "5") or 5)))
                continue
            raise SlackError(f"Slack respondió HTTP {e.code}")
        except urllib.error.URLError as e:
            raise SlackError(f"Sin conexión con Slack ({e.reason})")
        if not data.get("ok"):
            err = data.get("error", "error desconocido")
            raise SlackError({
                "invalid_auth": "El token de Slack no es válido.",
                "not_authed": "Falta el token de Slack.",
                "token_revoked": "El token de Slack fue revocado.",
                "account_inactive": "La cuenta de Slack está desactivada.",
                "missing_scope": "Al token le faltan permisos: " + data.get("needed", ""),
            }.get(err, f"Slack: {err}"))
        return data
    raise SlackError("Slack está limitando las peticiones; inténtalo en un momento.")


def _paged(method, token, key, **params):
    out, cursor = [], ""
    while True:
        data = _call(method, token, limit=200, **params, **({"cursor": cursor} if cursor else {}))
        out += data.get(key) or []
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            return out


# ─── Texto de Slack (mrkdwn) → HTML simple de Qt ──────────────────────────────
_TOKEN_RE = re.compile(r"<([^<>]+)>")


def mrkdwn_to_html(text, users, channels):
    """Slack ya escapa &, < y > en el texto; solo se interpretan sus marcas <...>."""
    def token(m):
        body = m.group(1)
        target, _, label = body.partition("|")
        if target.startswith("@"):
            name = users.get(target[1:], {}).get("name") or label or target[1:]
            return f"<b style='color:#9ec5ff'>@{html.escape(name)}</b>"
        if target.startswith("#"):
            name = label or channels.get(target[1:], target[1:])
            return f"<b style='color:#9ec5ff'>#{html.escape(name)}</b>"
        if target.startswith("!"):
            word = label or target[1:].split("^")[0]
            return f"<b style='color:#ffd479'>@{html.escape(word)}</b>"
        url = html.unescape(target)
        if not re.match(r"^(https?|mailto):", url, re.I):
            return html.escape(body)
        shown = label or html.escape(url)   # la etiqueta ya viene escapada por Slack
        return f"<a href=\"{html.escape(url, quote=True)}\" style='color:#7fb2ff'>{shown}</a>"

    parts, last = [], 0
    for m in _TOKEN_RE.finditer(text or ""):
        parts.append(("t", (text or "")[last:m.start()]))
        parts.append(("h", token(m)))
        last = m.end()
    parts.append(("t", (text or "")[last:]))

    def fmt(s):
        s = re.sub(r"```(.+?)```", r"<code>\1</code>", s, flags=re.S)
        s = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", s)
        s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<b>\1</b>", s)
        s = re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<i>\1</i>", s)
        s = re.sub(r"(?<![\w~])~([^~\n]+)~(?![\w~])", r"<s>\1</s>", s)
        return s

    out = "".join(fmt(v) if k == "t" else v for k, v in parts)
    return out.replace("\n", "<br>")


def _plain(text, users, channels):
    """Texto sin formato para la búsqueda."""
    def token(m):
        target, _, label = m.group(1).partition("|")
        if target.startswith("@"):
            return "@" + (users.get(target[1:], {}).get("name") or label or "")
        if target.startswith("#"):
            return "#" + (label or channels.get(target[1:], ""))
        return label or target
    return html.unescape(_TOKEN_RE.sub(token, text or ""))


class SlackClient(QObject):
    changed = pyqtSignal()
    app_created = pyqtSignal(bool)   # create_app_and_connect terminó (True = lista para autorizar)
    sent = pyqtSignal(bool, str)     # resultado de send(): (ok, error)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._busy = False
        self._error = ""
        self._team = {}            # {"name", "url", "user", "user_id"}
        self._channels = []        # [{"id", "name", "private"}]
        self._messages = []
        self._users = {}
        self._users_ts = 0.0
        self._last_refresh = 0.0
        self._dismissed = self._load_dismissed()

    # ── Estado ───────────────────────────────────────────────────────────────
    def connected(self):
        return bool(_kr_get())

    def state(self):
        return {"connected": self.connected(), "busy": self._busy, "error": self._error,
                "team": self._team.get("name", ""), "user": self._team.get("user", ""),
                "lastRefresh": self._last_refresh}

    def channels(self):
        return list(self._channels)

    def can_send(self):
        """¿El token tiene chat:write? Si aún no se sabe, se asume que sí (Slack lo dirá al enviar)."""
        granted = _GRANTED_SCOPES.get(_kr_get() or "")
        return granted is None or "chat:write" in granted

    def send(self, channel_id, text, thread_ts=None):
        """Publica como el usuario en un canal (o en el hilo de thread_ts)."""
        token = _kr_get()
        text = (text or "").strip()
        if not token or not channel_id or not text:
            self.sent.emit(False, "Elige un canal y escribe un mensaje.")
            return

        def work():
            try:
                form = {"channel": channel_id, "text": slack_escape(text)}
                if thread_ts:
                    form["thread_ts"] = thread_ts
                _post("chat.postMessage", form, token=token)
            except Exception as ex:
                msg = str(ex)
                if "missing_scope" in msg:
                    _GRANTED_SCOPES.setdefault(token, set()).discard("chat:write")
                    msg = "Falta el permiso para enviar: pulsa «Volver a autorizar»."
                elif "not_in_channel" in msg:
                    msg = "No eres miembro de ese canal."
                self.sent.emit(False, msg)
                self.changed.emit()
                return
            self.sent.emit(True, "")
            self.refresh()
        threading.Thread(target=work, daemon=True).start()

    def messages(self):
        return [m for m in self._messages if m["id"] not in self._dismissed]

    # ── Mensajes ocultos (solo en Minichrome; en Slack no se borra nada) ─────
    @staticmethod
    def _load_dismissed():
        try:
            ids = json.loads(get_config(DISMISSED_KEY, "") or "[]")
            return set(ids) if isinstance(ids, list) else set()
        except ValueError:
            return set()

    def _save_dismissed(self):
        # Los más antiguos (por ts, al final del id "canal:ts") se descartan primero.
        ids = sorted(self._dismissed, key=lambda i: i.rsplit(":", 1)[-1])[-MAX_DISMISSED:]
        self._dismissed = set(ids)
        set_config(DISMISSED_KEY, json.dumps(ids))

    def dismiss(self, msg_id):
        self._dismissed.add(msg_id)
        self._save_dismissed()

    def dismissed_count(self):
        return sum(1 for m in self._messages if m["id"] in self._dismissed)

    def restore_dismissed(self):
        self._dismissed.clear()
        self._save_dismissed()
        self.changed.emit()

    # ── Cuenta ───────────────────────────────────────────────────────────────
    def has_app(self):
        return bool(_kr_app())

    def start_oauth(self):
        """Abre la autorización de Slack; devuelve la URL a cargar en una pestaña o None."""
        app = _kr_app()
        if not app:
            self._error = "Primero hay que crear la app de Slack."
            self.changed.emit()
            return None
        self._oauth_state = secrets.token_urlsafe(24)
        self._error = ""
        self.changed.emit()
        return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
            "client_id": app["client_id"], "user_scope": ",".join(USER_SCOPES),
            "redirect_uri": REDIRECT_URI, "state": self._oauth_state})

    def handle_redirect(self, url):
        """Llamado al navegar a REDIRECT_URI: cambia el código por el token xoxp-."""
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        state, self._oauth_state = getattr(self, "_oauth_state", None), None
        if q.get("error"):
            self._error = "Autorización cancelada en Slack." if q["error"] == "access_denied" else f"Slack: {q['error']}"
            self.changed.emit()
            return
        if not state or q.get("state") != state or not q.get("code"):
            self._error = "La respuesta de Slack no corresponde a esta conexión; inténtalo de nuevo."
            self.changed.emit()
            return
        app = _kr_app() or {}

        def work():
            try:
                data = _post("oauth.v2.access", {"client_id": app.get("client_id", ""),
                                                 "client_secret": app.get("client_secret", ""),
                                                 "code": q["code"], "redirect_uri": REDIRECT_URI})
                token = (data.get("authed_user") or {}).get("access_token", "")
                if not token.startswith("xoxp-"):
                    raise SlackError("Slack no entregó un token de usuario.")
                keyring.set_password(KEYRING_SERVICE, TOKEN_ACCOUNT, token)
                self._error = ""
            except Exception as ex:
                self._error = str(ex)
                self.changed.emit()
                return
            self.refresh()
        threading.Thread(target=work, daemon=True).start()

    def create_app_and_connect(self, config_token):
        """Con un token de configuración (xoxe…): crea la app y abre la autorización."""
        self._error = ""
        self._busy = True
        self.changed.emit()

        def work():
            try:
                update_app(config_token) if _kr_app() else create_app(config_token)
                self._error = ""
            except Exception as ex:
                self._error = str(ex)
            finally:
                self._busy = False
            self.app_created.emit(not self._error)
        threading.Thread(target=work, daemon=True).start()

    def connect(self, token):
        """Valida el token (auth.test) en segundo plano y lo guarda si sirve."""
        token = (token or "").strip()
        if token.startswith("xoxb-"):
            self._error = ("Ese es un token de bot (xoxb-). Se necesita el «User OAuth Token» (xoxp-), "
                           "que está justo arriba en OAuth & Permissions.")
            self.changed.emit()
            return
        if not token.startswith("xoxp-"):
            self._error = "Pega el «User OAuth Token» de tu app de Slack (empieza con xoxp-)."
            self.changed.emit()
            return

        def work():
            try:
                _call("auth.test", token)
                keyring.set_password(KEYRING_SERVICE, TOKEN_ACCOUNT, token)
                self._error = ""
            except Exception as ex:
                self._error = str(ex)
                self.changed.emit()
                return
            self.refresh()
        threading.Thread(target=work, daemon=True).start()

    def disconnect(self):
        """Olvida el token del usuario (la app creada se conserva para reconectar)."""
        try:
            keyring.delete_password(KEYRING_SERVICE, TOKEN_ACCOUNT)
        except Exception:
            pass
        with self._lock:
            self._team, self._channels, self._messages, self._users = {}, [], [], {}
            self._error, self._last_refresh = "", 0.0
        self.changed.emit()

    # ── Actualización ────────────────────────────────────────────────────────
    def refresh(self):
        token = _kr_get()
        if not token:
            return
        with self._lock:
            if self._busy:
                return
            self._busy = True
        self.changed.emit()
        threading.Thread(target=self._refresh, args=(token,), daemon=True).start()

    def _refresh(self, token):
        try:
            auth = _call("auth.test", token)
            team = {"name": auth.get("team", ""), "url": auth.get("url", ""),
                    "user": auth.get("user", ""), "user_id": auth.get("user_id", "")}

            if time.time() - self._users_ts > USERS_TTL or not self._users:
                users = {}
                for u in _paged("users.list", token, "members"):
                    p = u.get("profile") or {}
                    users[u["id"]] = {"name": p.get("display_name") or p.get("real_name") or u.get("name", "")}
                self._users, self._users_ts = users, time.time()
            users = self._users

            convs = _paged("users.conversations", token, "channels",
                           types="public_channel,private_channel", exclude_archived="true")
            convs = [c for c in convs if not c.get("is_archived")][:MAX_CHANNELS]
            chan_names = {c["id"]: c.get("name", c["id"]) for c in convs}
            channels = sorted(({"id": c["id"], "name": c.get("name", c["id"]), "private": bool(c.get("is_private"))}
                               for c in convs), key=lambda c: c["name"])

            messages = []
            for c in convs:
                hist = _call("conversations.history", token, channel=c["id"], limit=MESSAGES_PER_CHANNEL)
                for m in hist.get("messages") or []:
                    if m.get("subtype") in _SKIP_SUBTYPES:
                        continue
                    messages.append(self._message(m, c, team, users, chan_names))
            messages.sort(key=lambda m: m["ts"], reverse=True)

            with self._lock:
                self._team, self._channels, self._messages = team, channels, messages[:MAX_MESSAGES]
                self._error, self._last_refresh = "", time.time()
        except Exception as ex:
            self._error = str(ex)
        finally:
            self._busy = False
            self.changed.emit()

    @staticmethod
    def _message(m, chan, team, users, chan_names):
        uid = m.get("user") or ""
        author = (users.get(uid, {}).get("name") or m.get("username")
                  or (m.get("bot_profile") or {}).get("name") or "Slack")
        text = m.get("text") or ""
        extras = []
        for f in m.get("files") or []:
            extras.append(f"📎 {html.escape(f.get('title') or f.get('name') or 'archivo')}")
        for a in m.get("attachments") or []:
            title = a.get("title") or a.get("fallback")
            if title and title not in text:
                extras.append(f"🔗 {html.escape(title)}")
        ts = float(m.get("ts", "0") or 0)
        body = mrkdwn_to_html(text, users, chan_names)
        if extras:
            body += ("<br>" if body else "") + "<br>".join(f"<span style='color:#9aa6c8'>{e}</span>" for e in extras)
        base = (team.get("url") or "https://slack.com/").rstrip("/")
        return {
            "id": f"{chan['id']}:{m.get('ts')}",
            "ts": ts,
            "time": datetime.fromtimestamp(ts).strftime("%d/%m %H:%M") if ts else "",
            "channel_id": chan["id"],
            "channel": chan.get("name", chan["id"]),
            "private": bool(chan.get("is_private")),
            "author": author,
            "html": body,
            "search": " ".join([author, "#" + chan.get("name", ""), _plain(text, users, chan_names)]
                               + [html.unescape(re.sub(r"<[^>]+>", "", e)) for e in extras]).lower(),
            "replies": int(m.get("reply_count") or 0),
            "slack_ts": m.get("thread_ts") or m.get("ts") or "",
            "permalink": f"{base}/archives/{chan['id']}/p{(m.get('ts') or '').replace('.', '')}",
        }


_client = None


def client() -> SlackClient:
    global _client
    if _client is None:
        _client = SlackClient()
    return _client
