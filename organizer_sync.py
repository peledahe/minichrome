"""Sincronización del organizador con Google Drive (mkorganizer_data.json).

Minichrome, Mk Organizer (escritorio) y la extensión Mk Organizer comparten un
mismo archivo en el Drive del usuario, con el formato de la extensión
(chrome.storage: listas de agenda, compras, ingresos, Kanban, notas, claves,
deudas, ahorros y la configuración común). Aquí se convierte ese formato a/desde
las tablas de SQLite y se aplica el mismo algoritmo que Mk Organizer:

  * Drive manda si tiene datos y (se pidió preferir Drive, o este equipo nunca
    sincronizó y no tiene datos, o el archivo es más nuevo que la última
    sincronización). Antes de reemplazar, se guarda una copia de lo local.
  * Si no, se suben los datos locales (antes de pisar un archivo ajeno por
    primera vez, se guarda una copia de lo que había en Drive).

El token sale de google_sync (la cuenta de Google conectada en Minichrome).
Para que las tres apps vean el mismo archivo con el permiso drive.file, sus
clientes OAuth deben pertenecer al mismo proyecto de Google Cloud.
"""
import json
import threading
import time
import urllib.parse

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

import google_sync
from db import _db, get_config, set_config
from secure_store import decrypt, encrypt

DRIVE_FILENAME = "mkorganizer_data.json"
DRIVE_API = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"

# Claves de app_config que son del organizador (no rutas ni ajustes de este equipo)
SHARED_CONFIG_KEYS = (
    "agendaEnabled", "kanbanEnabled", "notesEnabled", "budgetEnabled", "savingsEnabled",
    "debtsEnabled", "passwordsEnabled", "shoppingEnabled", "incomeEnabled",
    "exchangeRate", "paymentMethods", "passwordAutoSavePolicy",
    "budget_limits", "budget_income_targets",
)
# Claves sueltas que la página guarda con chrome.storage (moneda y categorías del
# Presupuesto). En Minichrome viven en app_config como "org:<clave>" (JSON).
EXTRA_KEYS = (
    "budget_currency_symbol", "budget_currency_code", "budget_exchange_rate",
    "budget_second_currency_enabled", "budget_second_currency_symbol",
    "budget_second_currency_code", "budget_categories",
)
EXTRA_PREFIX = "org:"

LAST_SYNC_KEY = "organizerDriveLastSync"
FILE_ID_KEY = "organizerDriveFileId"   # archivo de Drive de la última sincronización
LOCAL_BACKUP_KEY = "organizerBackupBeforeSync"
REMOTE_BACKUP_KEY = "organizerDriveBackupBeforeUpload"

AUTO_SYNC_DELAY_MS = 5000
PERIODIC_SYNC_MS = 10 * 60 * 1000


def _json_config(c, key, default):
    row = c.execute("SELECT val FROM app_config WHERE key=?", (key,)).fetchone()
    if not row or row[0] in (None, ""):
        return default
    try:
        val = json.loads(row[0])
    except ValueError:
        return default
    return val if isinstance(val, type(default)) else default


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v, default=None):
    try:
        f = float(v)
        return int(f) if f.is_integer() else default
    except (TypeError, ValueError):
        return default


class SyncError(Exception):
    pass


def _export_passwords(c):
    out = []
    for r in c.execute("SELECT id, site, username, password, type, url, notes, ts FROM passwords ORDER BY site ASC"):
        plain = decrypt(r[3] or "")
        if r[3] and not plain:
            # Sin llavero no se pueden leer: subirlas vacías las borraría en las tres apps.
            raise SyncError("No se pudieron leer las contraseñas (llavero del sistema no disponible).")
        out.append({"id": r[0], "site": r[1] or "", "username": r[2] or "", "password": plain,
                    "type": r[4] or "web", "url": r[5] or "", "notes": r[6] or "", "ts": r[7] or ""})
    return out


# ─── SQLite → formato común ───────────────────────────────────────────────────
def export_payload():
    c = _db()
    try:
        payload = {
            "agenda": [
                {"id": r[0], "text": r[1] or "", "dueDate": r[2] or "", "done": bool(r[3]),
                 "notes": r[4] or "", "tag": r[5] or ""}
                for r in c.execute("SELECT id, text, dueDate, done, notes, tag FROM agenda ORDER BY id DESC")
            ],
            "shopping": [
                {"id": r[0], "text": r[1] or "", "value": r[2] or 0, "currency": r[3] or "", "dueDate": r[4] or "",
                 "paymentMethod": r[5] or "", "done": bool(r[6]), "notes": r[7] or "",
                 "category": r[8] or "Otros", "status": r[9] or "projected"}
                for r in c.execute("SELECT id, text, value, currency, dueDate, paymentMethod, done, notes, category, status "
                                   "FROM shopping ORDER BY id DESC")
            ],
            "income": [
                {"id": r[0], "text": r[1] or "", "value": r[2] or 0, "currency": r[3] or "", "dueDate": r[4] or "",
                 "received": bool(r[5]), "notes": r[6] or "", "category": r[7] or "Otros", "status": r[8] or "projected"}
                for r in c.execute("SELECT id, text, value, currency, dueDate, received, notes, category, status "
                                   "FROM income ORDER BY id DESC")
            ],
            "kanban": [],
            "kanban_cards": [
                {"id": r[0], "col_id": r[1], "text": r[2] or "", "pos": r[3] or 0}
                for r in c.execute("SELECT id, col_id, text, pos FROM kanban_cards ORDER BY pos ASC")
            ],
            "notes": [
                {"id": r[0], "content": r[1] or "", "color": r[2] or "yellow", "x": r[3] or 0, "y": r[4] or 0,
                 "width": r[5] or 220, "height": r[6] or 170, "zIndex": r[7] or 1}
                for r in c.execute("SELECT id, content, color, x, y, width, height, z_index FROM notes ORDER BY z_index ASC")
            ],
            "passwords": _export_passwords(c),
            "deudas_list": _json_config(c, "deudas_list", []),
            "deudas_presupuesto": _num(get_config("deudas_presupuesto", "0")),
            "savings_goals": _json_config(c, "savings_goals", []),
        }
        cfg = {}
        for key in SHARED_CONFIG_KEYS:
            row = c.execute("SELECT val FROM app_config WHERE key=?", (key,)).fetchone()
            if row and row[0] is not None:
                cfg[key] = str(row[0])
        payload["app_config"] = cfg
        for key in EXTRA_KEYS:
            row = c.execute("SELECT val FROM app_config WHERE key=?", (EXTRA_PREFIX + key,)).fetchone()
            if row and row[0] not in (None, ""):
                try:
                    payload[key] = json.loads(row[0])
                except ValueError:
                    pass
        return payload
    finally:
        c.close()


def payload_has_data(p):
    if not isinstance(p, dict):
        return False
    lists = ("agenda", "shopping", "income", "kanban", "kanban_cards", "notes", "passwords", "deudas_list", "savings_goals")
    if any(isinstance(p.get(k), list) and p.get(k) for k in lists):
        return True
    if any(isinstance(p.get(k), dict) and p.get(k) for k in ("budget_limits", "budget_income_targets")):
        return True
    return _num(p.get("deudas_presupuesto")) > 0


# ─── formato común → SQLite ──────────────────────────────────────────────────
def import_payload(remote):
    """Reemplaza en SQLite lo que traiga el archivo (solo las claves presentes)."""
    c = _db()
    try:
        c.execute("BEGIN")

        def replace(table, key, sql, row_fn):
            items = remote.get(key)
            if not isinstance(items, list):
                return
            c.execute(f"DELETE FROM {table}")
            for it in items:
                if isinstance(it, dict):
                    c.execute(sql, row_fn(it))

        replace("agenda", "agenda",
                "INSERT INTO agenda(id, text, dueDate, done, notes, tag) VALUES(?,?,?,?,?,?)",
                lambda a: (_int(a.get("id")), a.get("text", ""), a.get("dueDate", "") or "", int(bool(a.get("done"))),
                           a.get("notes", "") or "", a.get("tag", "") or ""))
        replace("shopping", "shopping",
                "INSERT INTO shopping(id, text, value, currency, dueDate, paymentMethod, done, notes, category, status) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                lambda s: (_int(s.get("id")), s.get("text", ""), _num(s.get("value")), s.get("currency", "") or "",
                           s.get("dueDate", "") or "", s.get("paymentMethod", "") or "", int(bool(s.get("done"))),
                           s.get("notes", "") or "", s.get("category") or "Otros", s.get("status") or "projected"))
        replace("income", "income",
                "INSERT INTO income(id, text, value, currency, dueDate, received, notes, category, status) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                lambda i: (_int(i.get("id")), i.get("text", ""), _num(i.get("value")), i.get("currency", "") or "",
                           i.get("dueDate", "") or "", int(bool(i.get("received"))), i.get("notes", "") or "",
                           i.get("category") or "Otros", i.get("status") or "projected"))
        replace("kanban_cards", "kanban_cards",
                "INSERT INTO kanban_cards(id, col_id, text, pos) VALUES(?,?,?,?)",
                lambda k: (_int(k.get("id")), _int(k.get("col_id"), 1), k.get("text", ""), _num(k.get("pos"))))
        replace("notes", "notes",
                "INSERT INTO notes(id, content, color, x, y, z_index, width, height) VALUES(?,?,?,?,?,?,?,?)",
                lambda n: (_int(n.get("id")), n.get("content", "") or "", n.get("color") or "yellow",
                           _int(n.get("x"), 20), _int(n.get("y"), 20), _int(n.get("zIndex"), 1),
                           _int(n.get("width"), 220), _int(n.get("height"), 170)))
        replace("passwords", "passwords",
                "INSERT INTO passwords(id, site, username, password, ts, type, url, notes) VALUES(?,?,?,?,?,?,?,?)",
                lambda p: (_int(p.get("id")), p.get("site", ""), p.get("username", ""),
                           encrypt(p.get("password", "") or ""), p.get("ts", "") or "",
                           p.get("type") or "web", p.get("url", "") or "", p.get("notes", "") or ""))

        def put(key, val):
            c.execute("INSERT OR REPLACE INTO app_config(key, val) VALUES(?, ?)", (key, val))

        for key in ("deudas_list", "savings_goals"):
            if isinstance(remote.get(key), list):
                put(key, json.dumps(remote[key], ensure_ascii=False))
        if "deudas_presupuesto" in remote:
            put("deudas_presupuesto", str(_num(remote.get("deudas_presupuesto"))))
        cfg = remote.get("app_config")
        if isinstance(cfg, dict):
            for key in SHARED_CONFIG_KEYS:
                if key in cfg and cfg[key] is not None:
                    val = cfg[key]
                    put(key, val if isinstance(val, str) else json.dumps(val, ensure_ascii=False))
        for key in EXTRA_KEYS:
            if key in remote:
                put(EXTRA_PREFIX + key, json.dumps(remote[key], ensure_ascii=False))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


# ─── Google Drive ────────────────────────────────────────────────────────────
def _find_file(token):
    q = urllib.parse.quote(f"name='{DRIVE_FILENAME}' and trashed=false", safe="")
    res = google_sync._http("GET", f"{DRIVE_API}?q={q}&spaces=drive&orderBy=modifiedTime%20desc"
                                   "&pageSize=10&fields=files(id,name,modifiedTime)", token=token)
    files = res.get("files") or []
    return files[0]["id"] if files else None


def _download(token, file_id):
    return google_sync._http("GET", f"{DRIVE_API}/{file_id}?alt=media", token=token)


def _upload(token, file_id, payload):
    google_sync._http("PATCH", f"{DRIVE_UPLOAD}/{file_id}?uploadType=media", body=payload, token=token)


def _create(token, payload):
    meta = google_sync._http("POST", DRIVE_API, body={"name": DRIVE_FILENAME, "mimeType": "application/json"}, token=token)
    _upload(token, meta["id"], payload)
    return meta["id"]


def _carry_over(local, remote):
    """Conserva en lo que se sube lo que Drive tiene y Minichrome no maneja
    (claves de otras apps, ajustes de app_config que aquí no se comparten)."""
    if not isinstance(remote, dict):
        return local
    out = dict(local)
    for key, val in remote.items():
        if key != "timestamp" and key not in out:
            out[key] = val
    r_cfg = remote.get("app_config") if isinstance(remote.get("app_config"), dict) else {}
    out["app_config"] = {**{k: v for k, v in r_cfg.items() if k not in SHARED_CONFIG_KEYS}, **(local.get("app_config") or {})}
    return out


def _same_content(local, remote):
    """¿El archivo ya tiene exactamente lo que se subiría? (sin contar la fecha)"""
    if not isinstance(remote, dict):
        return False
    def norm(v):
        if isinstance(v, bool) or v is None or isinstance(v, str):
            return v
        if isinstance(v, (int, float)):
            return int(v) if float(v).is_integer() else float(v)   # 100.0 == 100 (JS)
        if isinstance(v, list):
            return [norm(x) for x in v]
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items()}
        return v
    canon = lambda v: json.dumps(norm(v), sort_keys=True, ensure_ascii=False)
    return all(canon(local[k]) == canon(remote.get(k)) for k in local if k != "timestamp")


# Para combinar sin duplicar: qué hace "igual" a un registro en cada lista.
_SIGNATURES = {
    "agenda": lambda x: (x.get("text"), x.get("dueDate") or ""),
    "shopping": lambda x: (x.get("text"), _num(x.get("value")), x.get("dueDate") or ""),
    "income": lambda x: (x.get("text"), _num(x.get("value")), x.get("dueDate") or ""),
    "kanban_cards": lambda x: (x.get("text"),),
    "notes": lambda x: (x.get("content"),),
    "passwords": lambda x: (x.get("site"), x.get("username")),
    "deudas_list": lambda x: (x.get("name"),),
    "savings_goals": lambda x: (x.get("name"),),
}


def merge_payloads(remote, local):
    """Une Drive y este equipo la primera vez que se sincroniza: nada se pierde.

    Las listas se combinan (lo local que no esté en Drive se añade con un ID
    nuevo); en lo demás manda Drive si lo tiene.
    """
    merged = json.loads(json.dumps(remote))
    for key, sig in _SIGNATURES.items():
        r_items = merged.get(key) if isinstance(merged.get(key), list) else []
        seen = {sig(x) for x in r_items if isinstance(x, dict)}
        next_id = max([_int(x.get("id"), 0) or 0 for x in r_items if isinstance(x, dict)] + [0]) + 1
        for item in local.get(key) or []:
            if not isinstance(item, dict) or sig(item) in seen:
                continue
            item = dict(item, id=next_id)
            next_id += 1
            seen.add(sig(item))
            r_items.append(item)
        merged[key] = r_items
    cfg = dict(local.get("app_config") or {})
    cfg.update(merged.get("app_config") or {})
    merged["app_config"] = cfg
    for key, val in local.items():
        if key not in merged or merged.get(key) in (None, "", 0, [], {}):
            merged[key] = val
    return merged


def sync_with_drive(prefer_drive=False):
    """Una sincronización completa; devuelve {"action": "create"|"upload"|"download"}."""
    token = google_sync.manager().get_access_token()
    if not token:
        raise google_sync.GoogleError("No hay una cuenta de Google conectada.")
    local = export_payload()
    has_local = payload_has_data(local)
    last_sync = int(_num(get_config(LAST_SYNC_KEY, "0")))

    file_id = _find_file(token)
    if not file_id:
        local["timestamp"] = int(time.time() * 1000)
        set_config(FILE_ID_KEY, _create(token, local))
        set_config(LAST_SYNC_KEY, str(local["timestamp"]))
        return {"action": "create"}

    remote = _download(token, file_id)
    has_remote = payload_has_data(remote)
    remote_ts = int(_num((remote or {}).get("timestamp")))
    local = _carry_over(local, remote)

    first_with_file = not last_sync or get_config(FILE_ID_KEY, "") != file_id
    if first_with_file and has_local and has_remote and not prefer_drive:
        # Primera vez con este archivo (nunca se sincronizó o antes se usaba otro)
        # y hay datos en ambos lados: combinar en lugar de reemplazar.
        set_config(LOCAL_BACKUP_KEY, json.dumps(local, ensure_ascii=False))
        set_config(REMOTE_BACKUP_KEY, json.dumps(remote, ensure_ascii=False))
        merged = merge_payloads(remote, local)
        import_payload(merged)
        merged["timestamp"] = int(time.time() * 1000)
        _upload(token, file_id, merged)
        set_config(FILE_ID_KEY, file_id)
        set_config(LAST_SYNC_KEY, str(merged["timestamp"]))
        return {"action": "download"}  # la página se recarga para mostrar lo combinado
    drive_is_source = has_remote and (prefer_drive or (not last_sync and not has_local)
                                      or remote_ts > last_sync + 2000)
    if drive_is_source:
        if has_local:
            set_config(LOCAL_BACKUP_KEY, json.dumps(local, ensure_ascii=False))
        import_payload(remote)
        set_config(FILE_ID_KEY, file_id)
        set_config(LAST_SYNC_KEY, str(max(int(time.time() * 1000), remote_ts)))
        return {"action": "download"}

    if _same_content(local, remote):
        # Nada que subir: no se cambia la fecha del archivo, así los otros
        # equipos no creen que hay datos nuevos.
        set_config(FILE_ID_KEY, file_id)
        set_config(LAST_SYNC_KEY, str(max(last_sync, remote_ts)))
        return {"action": "nochange"}

    if not last_sync and has_remote:
        # Primera vez que este equipo pisa un archivo que ya tenía datos.
        set_config(REMOTE_BACKUP_KEY, json.dumps(remote, ensure_ascii=False))
    local["timestamp"] = int(time.time() * 1000)
    _upload(token, file_id, local)
    set_config(FILE_ID_KEY, file_id)
    set_config(LAST_SYNC_KEY, str(local["timestamp"]))
    return {"action": "upload"}


class OrganizerDriveSync(QObject):
    """Ejecuta las sincronizaciones de una en una, fuera del hilo de la interfaz."""
    finished = pyqtSignal(dict)   # {"ok", "action"|"error", "reqId"}

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._running = False
        self._pending = None          # prefer_drive de una petición en espera
        self._waiting_ids = []
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(lambda: self.request())
        self._periodic = QTimer(self)
        self._periodic.timeout.connect(lambda: self.request())

    def connected(self):
        return bool(google_sync.manager().status().get("connected"))

    def start_periodic(self):
        self._periodic.start(PERIODIC_SYNC_MS)
        QTimer.singleShot(3000, lambda: self.request())

    def schedule(self):
        """Tras un cambio local: sincroniza cuando dejen de llegar cambios."""
        if self.connected():
            self._debounce.start(AUTO_SYNC_DELAY_MS)

    def request(self, prefer_drive=False, req_id=None):
        if not self.connected():
            if req_id is not None:
                self.finished.emit({"ok": False, "error": "No hay una cuenta de Google conectada.", "reqId": req_id})
            return
        with self._lock:
            if req_id is not None:
                self._waiting_ids.append(req_id)
            if self._running:
                self._pending = bool(prefer_drive) or bool(self._pending)
                return
            self._running = True
        threading.Thread(target=self._run, args=(bool(prefer_drive),), daemon=True).start()

    def _run(self, prefer_drive):
        while True:
            with self._lock:
                ids, self._waiting_ids = self._waiting_ids, []
            try:
                result = {"ok": True, **sync_with_drive(prefer_drive)}
            except Exception as ex:
                result = {"ok": False, "error": str(ex)}
            for rid in ids or [None]:
                try:
                    self.finished.emit({**result, "reqId": rid})
                except Exception:
                    pass
            with self._lock:
                if self._pending is None:
                    self._running = False
                    return
                prefer_drive, self._pending = self._pending, None


_manager = None


def manager() -> OrganizerDriveSync:
    global _manager
    if _manager is None:
        _manager = OrganizerDriveSync()
    return _manager
