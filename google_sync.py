"""Sincronización con Google Calendar (OAuth para apps de escritorio, PKCE).

- El usuario crea su propio ID de cliente OAuth ("App de escritorio") en Google
  Cloud y elige el JSON descargado. Ese cliente y el refresh token viven en el
  llavero del sistema (Secret Service), nunca en archivos del proyecto.
- Google -> Minichrome: eventos de los calendarios visibles de la cuenta se
  copian a la tabla google_events (caché de solo lectura para el calendario).
- Minichrome -> Google: las actividades con fecha (Agenda, Kanban, Compras,
  Ingresos) se reflejan como eventos de día completo en un calendario propio
  "Minichrome". Cada evento lleva extendedProperties.private.mcKey/mcHash, así
  que actualizar, borrar o reconectar no duplica nada. Otros calendarios nunca
  se modifican.
- Todo el trabajo de red corre en hilos; `changed` avisa a la interfaz.
"""
import base64
import hashlib
import html
import http.server
import json
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QObject, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices

import config
from db import get_config, set_config

import os

KEYRING_SERVICE = "minichrome"
CLIENT_ACCOUNT = "google-oauth-client"
TOKEN_ACCOUNT = "google-refresh-token"

DEFAULT_CLIENT_ID = os.environ.get("MINICHROME_GOOGLE_CLIENT_ID", "")
DEFAULT_CLIENT_SECRET = os.environ.get("MINICHROME_GOOGLE_CLIENT_SECRET", "")

SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.file",
]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
API = "https://www.googleapis.com/calendar/v3"

MC_CALENDAR_NAME = "Minichrome"
PULL_PAST_DAYS = 90
PULL_FUTURE_DAYS = 365
CONNECT_TIMEOUT = 300  # segundos para completar el inicio de sesión en el navegador

TYPE_LABELS = {"agenda": "Agenda", "kanban": "Kanban", "shopping": "Compras y pagos", "income": "Ingresos"}
TYPE_COLORS = {"agenda": "3", "kanban": "10", "shopping": "6", "income": "9"}  # colorId de eventos de Google
KANBAN_STATUS = ["Pendiente", "En proceso", "Bloqueada", "Completada"]  # columnas 1..4
KANBAN_PRIORITY = {"high": "Alta", "medium": "Media", "low": "Baja"}


class GoogleError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


# ─── Llavero ──────────────────────────────────────────────────────────────────
def _kr_get(account):
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, account)
    except Exception as ex:
        print(f"[Google] Llavero no disponible: {ex}")
        return None


def _kr_set(account, value):
    import keyring
    keyring.set_password(KEYRING_SERVICE, account, value)


def _kr_del(account):
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, account)
    except Exception:
        pass


# ─── HTTP ─────────────────────────────────────────────────────────────────────
def _http(method, url, *, params=None, form=None, body=None, token=None, timeout=30):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        msg = ""
        try:
            err = json.loads(raw)
            inner = err.get("error")
            msg = inner.get("message", "") if isinstance(inner, dict) else (err.get("error_description") or inner or "")
            if isinstance(inner, str) and inner not in msg:
                msg = f"{inner}: {msg}" if msg else inner
        except ValueError:
            msg = raw[:200]
        raise GoogleError(msg or f"HTTP {e.code}", e.code)
    except urllib.error.URLError as e:
        raise GoogleError(f"Sin conexión con Google ({e.reason})")


def _quote(value):
    return urllib.parse.quote(value, safe="")


def parse_client_file(path):
    """Valida el JSON de un ID de cliente OAuth de tipo 'App de escritorio'."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        raise GoogleError("No se pudo leer el archivo: no es un JSON válido.")
    cfg = data.get("installed") if isinstance(data, dict) else None
    if not cfg:
        if isinstance(data, dict) and data.get("web"):
            raise GoogleError("Ese ID de cliente es de tipo «Aplicación web». Crea uno de tipo «App de escritorio».")
        raise GoogleError("El archivo no es un ID de cliente OAuth de Google.")
    if not cfg.get("client_id") or not cfg.get("client_secret"):
        raise GoogleError("Al archivo le faltan client_id o client_secret.")
    return {"client_id": cfg["client_id"], "client_secret": cfg["client_secret"]}


# ─── Servidor local para recibir el código de autorización ───────────────────
def _render_auth_html(success=True, title="", message="", details=""):
    icon_color = "#34d399" if success else "#f87171"
    icon_bg = "rgba(16, 185, 129, 0.2)" if success else "rgba(239, 68, 68, 0.2)"
    icon_border = "rgba(16, 185, 129, 0.4)" if success else "rgba(239, 68, 68, 0.4)"
    icon_svg = (
        '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>'
        if success else
        '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>'
    )
    details_html = f'<p style="font-size:0.8rem; color:#f87171; margin-top:-14px; margin-bottom:18px;">{html.escape(details)}</p>' if details else ''

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Minichrome - Autenticación Google</title>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif; }}
    body {{
      background: #0b1120;
      background-image: radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.15) 0px, transparent 50%), radial-gradient(at 100% 100%, rgba(168, 85, 247, 0.15) 0px, transparent 50%);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #f8fafc;
      padding: 20px;
    }}
    .card {{
      background: rgba(30, 41, 59, 0.7);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 20px;
      padding: 40px 32px;
      max-width: 440px;
      width: 100%;
      text-align: center;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
    }}
    .icon-badge {{
      width: 64px;
      height: 64px;
      margin: 0 auto 20px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      background: {icon_bg};
      border: 1px solid {icon_border};
      color: {icon_color};
      box-shadow: 0 0 24px {icon_bg};
    }}
    h1 {{
      font-size: 1.5rem;
      font-weight: 700;
      margin-bottom: 8px;
      background: linear-gradient(to right, #ffffff, #cbd5e1);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .tag {{
      display: inline-block;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 4px 10px;
      border-radius: 9999px;
      background: rgba(99, 102, 241, 0.2);
      color: #818cf8;
      margin-bottom: 16px;
      border: 1px solid rgba(99, 102, 241, 0.3);
    }}
    p {{
      color: #94a3b8;
      font-size: 0.95rem;
      line-height: 1.5;
      margin-bottom: 24px;
    }}
    .btn {{
      display: inline-block;
      width: 100%;
      padding: 12px 20px;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      color: white;
      font-weight: 600;
      font-size: 0.9rem;
      border: none;
      border-radius: 10px;
      cursor: pointer;
      text-decoration: none;
      transition: all 0.2s ease;
      box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
    }}
    .btn:hover {{
      opacity: 0.95;
      transform: translateY(-1px);
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon-badge">
      {icon_svg}
    </div>
    <span class="tag">Minichrome</span>
    <h1>{html.escape(title)}</h1>
    <p>{message}</p>
    {details_html}
    <button class="btn" id="close-btn" onclick="closeThisTab()">Cerrar esta pestaña</button>
  </div>
  <script>
    function closeThisTab() {{
      fetch('/close').catch(function(){{}});
      try {{ window.close(); }} catch(e) {{}}
    }}
    if ({'true' if success else 'false'}) {{
      setTimeout(function() {{
        closeThisTab();
      }}, 1500);
    }}
  </script>
</body>
</html>"""


class _LoopbackServer:
    def __init__(self, state):
        self.state = state
        self.result = None
        self.code_event = threading.Event()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(h):
                parsed = urllib.parse.urlparse(h.path)
                q = urllib.parse.parse_qs(parsed.query)

                if parsed.path == "/close":
                    h.send_response(200)
                    h.send_header("Content-Type", "text/plain")
                    h.send_header("Connection", "close")
                    h.end_headers()
                    try:
                        h.wfile.write(b"OK")
                        h.wfile.flush()
                    except Exception:
                        pass
                    try:
                        manager().close_auth_url.emit()
                    except Exception:
                        pass
                    return

                if "code" not in q and "error" not in q:
                    if parsed.path == "/favicon.ico":
                        h.send_response(204)
                        h.end_headers()
                        return
                    page = _render_auth_html(
                        success=False,
                        title="Esperando Autorización",
                        message="Por favor autoriza los permisos en la ventana de Google…"
                    )
                    body_bytes = page.encode("utf-8")
                    h.send_response(200)
                    h.send_header("Content-Type", "text/html; charset=utf-8")
                    h.send_header("Content-Length", str(len(body_bytes)))
                    h.send_header("Connection", "close")
                    h.end_headers()
                    try:
                        h.wfile.write(body_bytes)
                        h.wfile.flush()
                    except Exception:
                        pass
                    return

                if q.get("state", [""])[0] != outer.state:
                    outer.result = ("error", "state")
                elif "error" in q:
                    outer.result = ("error", q["error"][0])
                else:
                    outer.result = ("code", q["code"][0])

                ok = outer.result[0] == "code"
                if ok:
                    page = _render_auth_html(
                        success=True,
                        title="¡Conexión Exitosa!",
                        message="Tu cuenta de Google se ha conectado correctamente a Minichrome.<br><br>Ya puedes cerrar esta pestaña y volver a la aplicación."
                    )
                else:
                    page = _render_auth_html(
                        success=False,
                        title="Inicio Cancelado",
                        message="No se completó la vinculación con Google.",
                        details=outer.result[1]
                    )

                body_bytes = page.encode("utf-8")
                h.send_response(200)
                h.send_header("Content-Type", "text/html; charset=utf-8")
                h.send_header("Content-Length", str(len(body_bytes)))
                h.send_header("Connection", "close")
                h.end_headers()
                try:
                    h.wfile.write(body_bytes)
                    h.wfile.flush()
                except Exception:
                    pass
                outer.code_event.set()
                if ok:
                    def _auto_close():
                        time.sleep(1.8)
                        try:
                            manager().close_auth_url.emit()
                        except Exception:
                            pass
                    threading.Thread(target=_auto_close, daemon=True).start()

            def log_message(h, *_args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def wait_code(self, timeout, cancel):
        end = time.time() + timeout
        while not self.code_event.is_set():
            if cancel.is_set():
                raise GoogleError("Conexión cancelada.")
            if time.time() > end:
                raise GoogleError("Se agotó el tiempo para iniciar sesión en Google.")
            self.code_event.wait(0.2)

        kind, value = self.result
        if kind != "code":
            if value == "access_denied":
                raise GoogleError("No se concedió el acceso en Google.")
            raise GoogleError(f"Google devolvió un error ({value}).")
        return value

    def close(self):
        def _shutdown():
            time.sleep(2.5)
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
        threading.Thread(target=_shutdown, daemon=True).start()


# ─── Datos locales -> eventos de Google ──────────────────────────────────────
def _iso_date(value):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(value or "").strip())
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def _money(value, currency):
    try:
        txt = f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return ""
    return f"{currency} {txt}".strip() if currency else txt


def parse_kanban_text(text):
    """Mismo formato que la Agenda: Título | Descripción | Vence: … | Prioridad: … | Etiquetas: …"""
    r = {"title": "", "description": [], "due": "", "priority": "medium", "labels": []}
    for part in [p.strip() for p in str(text or "").split(" | ")]:
        if part.startswith("Vence: "):
            r["due"] = part[7:]
        elif part.startswith("Prioridad: "):
            r["priority"] = part[11:].lower()
        elif part.startswith("Etiquetas: "):
            r["labels"] = [l.strip() for l in part[11:].split(",") if l.strip()]
        elif not r["title"]:
            r["title"] = part
        else:
            r["description"].append(part)
    r["description"] = " | ".join(r["description"])
    return r


def _event_body(kind, key, title, day, done, lines):
    desc = "\n".join(l for l in lines if l)
    desc = (desc + "\n\n" if desc else "") + f"— {TYPE_LABELS[kind]} · sincronizado desde Minichrome"
    body = {
        "summary": (("✔ " if done else "") + (title or "(sin título)"))[:250],
        "description": desc,
        "start": {"date": day.isoformat()},
        "end": {"date": (day + timedelta(days=1)).isoformat()},
        "colorId": TYPE_COLORS[kind],
        "transparency": "transparent",
        "extendedProperties": {"private": {"mcKey": key}},
    }
    digest = hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    body["extendedProperties"]["private"]["mcHash"] = digest
    return body


def collect_local_items(db_path=None):
    """{mcKey: cuerpo del evento} para todas las actividades con fecha válida."""
    c = sqlite3.connect(db_path or config.DB)
    items = {}
    try:
        for i, text, due, done, tag, notes in c.execute(
                "SELECT id, text, dueDate, done, COALESCE(tag,''), COALESCE(notes,'') FROM agenda"):
            day = _iso_date(due)
            if day:
                items[f"agenda:{i}"] = _event_body("agenda", f"agenda:{i}", text, day, bool(done), [
                    "Estado: " + ("Completada" if done else "Pendiente"),
                    f"Etiqueta: {tag}" if tag else "", notes])
        for i, text, val, cur, due, pm, done, notes in c.execute(
                "SELECT id, text, value, currency, dueDate, paymentMethod, done, COALESCE(notes,'') FROM shopping"):
            day = _iso_date(due)
            if day:
                items[f"shopping:{i}"] = _event_body("shopping", f"shopping:{i}", text, day, bool(done), [
                    "Estado: " + ("Pagado" if done else "Pendiente de pago"),
                    f"Monto: {_money(val, cur)}" if val is not None else "",
                    f"Método de pago: {pm}" if pm else "", notes])
        for i, text, val, cur, due, received, notes in c.execute(
                "SELECT id, text, value, currency, dueDate, received, COALESCE(notes,'') FROM income"):
            day = _iso_date(due)
            if day:
                items[f"income:{i}"] = _event_body("income", f"income:{i}", text, day, bool(received), [
                    "Estado: " + ("Recibido" if received else "Por recibir"),
                    f"Monto: {_money(val, cur)}" if val is not None else "", notes])
        for i, col, text in c.execute("SELECT id, col_id, text FROM kanban_cards"):
            k = parse_kanban_text(text)
            day = _iso_date(k["due"])
            if day:
                status = KANBAN_STATUS[col - 1] if 1 <= (col or 0) <= 4 else ""
                items[f"kanban:{i}"] = _event_body("kanban", f"kanban:{i}", k["title"], day, col == 4, [
                    f"Estado: {status}" if status else "",
                    f"Prioridad: {KANBAN_PRIORITY.get(k['priority'], '')}",
                    f"Etiquetas: {', '.join(k['labels'])}" if k["labels"] else "", k["description"]])
    finally:
        c.close()
    return items


def _plain_text(value):
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", value or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _event_row(ev, cal):
    start, end = ev.get("start", {}), ev.get("end", {})
    all_day = "date" in start
    if all_day:
        s_day = date.fromisoformat(start["date"])
        e_day = date.fromisoformat(end.get("date", start["date"])) - timedelta(days=1)  # fin exclusivo
        s_time = e_time = ""
    else:
        s_dt = datetime.fromisoformat(start["dateTime"]).astimezone()
        e_dt = datetime.fromisoformat(end.get("dateTime", start["dateTime"])).astimezone()
        s_day, s_time = s_dt.date(), s_dt.strftime("%H:%M")
        # un evento que termina justo a medianoche pertenece al día anterior
        e_day = (e_dt - timedelta(seconds=1)).date() if e_dt > s_dt else s_dt.date()
        e_time = e_dt.strftime("%H:%M")
    e_day = max(e_day, s_day)
    return (
        f"{cal.get('id', '')}|{ev.get('id', '')}",
        cal.get("summaryOverride") or cal.get("summary") or "",
        ev.get("summary") or "(sin título)",
        s_day.isoformat(), e_day.isoformat(), s_time, e_time, int(all_day),
        ev.get("location") or "", _plain_text(ev.get("description"))[:2000],
        ev.get("htmlLink") or "", cal.get("backgroundColor") or "",
    )


# ─── Gestor ───────────────────────────────────────────────────────────────────
class GoogleCalendarSync(QObject):
    changed = pyqtSignal()
    open_auth_url = pyqtSignal(str)
    close_auth_url = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._busy = ""       # "", "connecting" o "syncing"
        self._error = ""
        self._access = (None, 0.0)
        self._cancel = None

    # ── Estado ────────────────────────────────────────────────────────────────
    def _client(self):
        raw = _kr_get(CLIENT_ACCOUNT)
        if raw:
            try:
                return json.loads(raw)
            except ValueError:
                pass
        candidates = [
            os.path.join(config.BASE, "google-oauth.json"),
            "/home/perry/Desarrollo/Organizer/google-oauth.json",
        ]
        for path in candidates:
            if os.path.exists(path):
                try:
                    cfg = parse_client_file(path)
                    _kr_set(CLIENT_ACCOUNT, json.dumps(cfg))
                    return cfg
                except Exception:
                    pass
        if DEFAULT_CLIENT_ID and DEFAULT_CLIENT_SECRET:
            cfg = {"client_id": DEFAULT_CLIENT_ID, "client_secret": DEFAULT_CLIENT_SECRET}
            _kr_set(CLIENT_ACCOUNT, json.dumps(cfg))
            return cfg
        return None

    def status(self):
        client = self._client()
        c = sqlite3.connect(config.DB)
        try:
            events = c.execute("SELECT COUNT(*) FROM google_events").fetchone()[0]
        except sqlite3.Error:
            events = 0
        finally:
            c.close()
        return {
            "configured": bool(client),
            "clientId": (client or {}).get("client_id", "")[:24],
            "connected": bool(_kr_get(TOKEN_ACCOUNT)),
            "email": get_config("googleEmail", ""),
            "lastSync": get_config("googleLastSync", ""),
            "pushed": int(get_config("googleLastPushCount", "0") or 0),
            "events": events,
            "busy": self._busy,
            "error": self._error,
        }

    def _set(self, busy=None, error=None):
        if busy is not None:
            self._busy = busy
        if error is not None:
            self._error = error
        self.changed.emit()

    # ── Configuración y conexión ──────────────────────────────────────────────
    def set_client_file(self, path):
        try:
            cfg = parse_client_file(path)
            _kr_set(CLIENT_ACCOUNT, json.dumps(cfg))
            self._set(error="")
        except GoogleError as ex:
            self._set(error=str(ex))
        except Exception as ex:
            self._set(error=f"No se pudo guardar en el llavero: {ex}")

    def connect(self):
        """Abre el inicio de sesión de Google en el navegador del sistema."""
        with self._lock:
            if self._busy:
                return
            cfg = self._client()
            if not cfg:
                self._error = "Primero elige el archivo de credenciales (JSON)."
                self.changed.emit()
                return
            self._busy = "connecting"
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(24)
        try:
            server = _LoopbackServer(state)
        except OSError as ex:
            self._set(busy="", error=f"No se pudo abrir el puerto local: {ex}")
            return
        redirect = f"http://127.0.0.1:{server.port}"
        url = AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": cfg["client_id"], "redirect_uri": redirect, "response_type": "code",
            "scope": " ".join(SCOPES), "code_challenge": challenge, "code_challenge_method": "S256",
            "state": state, "access_type": "offline", "prompt": "consent",
        })
        self._cancel = threading.Event()
        self._set(error="")
        threading.Thread(target=self._finish_connect, args=(server, cfg, verifier, redirect, self._cancel),
                         daemon=True).start()
        self.open_auth_url.emit(url)

    def cancel_connect(self):
        if self._cancel:
            self._cancel.set()

    def _finish_connect(self, server, cfg, verifier, redirect, cancel):
        try:
            code = server.wait_code(CONNECT_TIMEOUT, cancel)
            tok = _http("POST", TOKEN_URL, form={
                "code": code, "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier,
            })
            refresh = tok.get("refresh_token")
            if not refresh:
                raise GoogleError("Google no entregó un token de acceso permanente. Inténtalo de nuevo.")
            _kr_set(TOKEN_ACCOUNT, refresh)
            self._access = (tok.get("access_token"), time.time() + int(tok.get("expires_in", 3600)) - 60)
            try:
                info = _http("GET", USERINFO_URL, token=self._access[0])
                set_config("googleEmail", info.get("email", ""))
            except GoogleError:
                set_config("googleEmail", "")
            self._set(busy="", error="")
            self.sync()
        except Exception as ex:
            self._set(busy="", error=str(ex))
        finally:
            server.close()

    def disconnect(self):
        """Olvida la cuenta (revoca el token). El calendario 'Minichrome' queda en Google."""
        self.cancel_connect()
        refresh = _kr_get(TOKEN_ACCOUNT)
        _kr_del(TOKEN_ACCOUNT)
        self._access = (None, 0.0)
        set_config("googleEmail", "")
        set_config("googleLastSync", "")
        c = sqlite3.connect(config.DB)
        c.execute("DELETE FROM google_events")
        c.commit()
        c.close()
        if refresh:
            threading.Thread(target=lambda: self._try_revoke(refresh), daemon=True).start()
        self._set(busy="", error="")

    @staticmethod
    def _try_revoke(token):
        try:
            _http("POST", REVOKE_URL, form={"token": token}, timeout=10)
        except GoogleError:
            pass

    def _token(self):
        tok, exp = self._access
        if tok and time.time() < exp:
            return tok
        refresh, cfg = _kr_get(TOKEN_ACCOUNT), self._client()
        if not refresh or not cfg:
            raise GoogleError("No hay una cuenta de Google conectada.")
        try:
            r = _http("POST", TOKEN_URL, form={
                "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                "refresh_token": refresh, "grant_type": "refresh_token",
            })
        except GoogleError as ex:
            if "invalid_grant" in str(ex):
                _kr_del(TOKEN_ACCOUNT)
                raise GoogleError("La autorización de Google caducó o fue revocada. Vuelve a conectar.")
            raise
        self._access = (r["access_token"], time.time() + int(r.get("expires_in", 3600)) - 60)
        return self._access[0]

    def get_access_token(self):
        try:
            return self._token()
        except Exception:
            return None

    # ── Sincronización ────────────────────────────────────────────────────────
    def sync(self):
        with self._lock:
            if self._busy:
                return False
            self._busy = "syncing"
        self.changed.emit()
        threading.Thread(target=self._sync_worker, daemon=True).start()
        return True

    def _sync_worker(self):
        error = ""
        try:
            token = self._token()
            cal_id = self._ensure_calendar(token)
            self._pull(token, cal_id)
            pushed = self._push(token, cal_id)
            set_config("googleLastPushCount", str(pushed))
            set_config("googleLastSync", datetime.now().isoformat(timespec="seconds"))
        except Exception as ex:
            error = str(ex)
            print(f"[Google] Error al sincronizar: {ex}")
        self._set(busy="", error=error)

    def _paged(self, token, url, params):
        items, page = [], None
        while True:
            p = dict(params)
            if page:
                p["pageToken"] = page
            r = _http("GET", url, params=p, token=token)
            items.extend(r.get("items", []))
            page = r.get("nextPageToken")
            if not page:
                return items

    def _ensure_calendar(self, token):
        cal_id = get_config("googleCalendarId", "")
        if cal_id:
            try:
                _http("GET", f"{API}/calendars/{_quote(cal_id)}", token=token)
                return cal_id
            except GoogleError as ex:
                if ex.status not in (403, 404, 410):
                    raise
        cal = _http("POST", f"{API}/calendars", token=token, body={
            "summary": MC_CALENDAR_NAME,
            "description": "Actividades sincronizadas desde Minichrome (Agenda, Kanban, Compras e Ingresos).",
        })
        set_config("googleCalendarId", cal["id"])
        return cal["id"]

    def _pull(self, token, own_cal_id):
        now = datetime.now().astimezone()
        window = {
            "timeMin": (now - timedelta(days=PULL_PAST_DAYS)).isoformat(),
            "timeMax": (now + timedelta(days=PULL_FUTURE_DAYS)).isoformat(),
            "singleEvents": "true", "orderBy": "startTime", "maxResults": 2500,
        }
        rows = []
        for cal in self._paged(token, f"{API}/users/me/calendarList", {"minAccessRole": "reader"}):
            if cal.get("id") == own_cal_id or not cal.get("selected") or cal.get("deleted"):
                continue
            for ev in self._paged(token, f"{API}/calendars/{_quote(cal['id'])}/events", window):
                if ev.get("status") == "cancelled":
                    continue
                if ev.get("extendedProperties", {}).get("private", {}).get("mcKey"):
                    continue  # copia de una actividad de Minichrome
                try:
                    rows.append(_event_row(ev, cal))
                except (KeyError, ValueError):
                    continue
        c = sqlite3.connect(config.DB)
        try:
            c.execute("DELETE FROM google_events")
            c.executemany("INSERT OR REPLACE INTO google_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            c.commit()
        finally:
            c.close()
        return len(rows)

    def _push(self, token, cal_id):
        base = f"{API}/calendars/{_quote(cal_id)}/events"
        remote = {}
        for ev in self._paged(token, base, {"maxResults": 2500, "showDeleted": "false"}):
            key = ev.get("extendedProperties", {}).get("private", {}).get("mcKey")
            if not key:
                continue  # eventos creados a mano en ese calendario: no se tocan
            if key in remote:  # duplicado accidental
                _http("DELETE", f"{base}/{_quote(ev['id'])}", token=token)
                continue
            remote[key] = ev
        items = collect_local_items()
        for key, body in items.items():
            ev = remote.pop(key, None)
            if ev and ev.get("extendedProperties", {}).get("private", {}).get("mcHash") == \
                    body["extendedProperties"]["private"]["mcHash"]:
                continue
            if ev:
                _http("PUT", f"{base}/{_quote(ev['id'])}", token=token, body=body)
            else:
                _http("POST", base, token=token, body=body)
        for ev in remote.values():  # borrados o sin fecha en Minichrome
            try:
                _http("DELETE", f"{base}/{_quote(ev['id'])}", token=token)
            except GoogleError as ex:
                if ex.status not in (404, 410):
                    raise
        return len(items)

    def events(self):
        c = sqlite3.connect(config.DB)
        try:
            rows = c.execute("SELECT id, calendar, title, start_date, end_date, start_time, end_time, all_day, "
                             "location, description, link, color FROM google_events ORDER BY start_date, start_time").fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            c.close()
        keys = ("id", "calendar", "title", "start", "end", "startTime", "endTime", "allDay",
                "location", "description", "link", "color")
        return [dict(zip(keys, r)) for r in rows]


_manager = None


def manager() -> GoogleCalendarSync:
    global _manager
    if _manager is None:
        _manager = GoogleCalendarSync()
    return _manager
