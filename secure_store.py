"""Cifrado de las contraseñas guardadas.

La clave (Fernet: AES-128-CBC + HMAC-SHA256) vive en el llavero del sistema
(Secret Service / GNOME Keyring); la base de datos solo guarda "enc:v1:<token>".
Los valores sin prefijo son texto plano heredado y se siguen leyendo igual.
Si el llavero no está disponible se conserva el comportamiento previo
(texto plano) para no perder contraseñas.
"""
import os
import sqlite3

from config import DB

PREFIX = "enc:v1:"
_SERVICE = "minichrome"
_ACCOUNT = "passwords-key"
BACKUP_SUFFIX = ".antes-de-cifrar.bak"

_fernet = None
_unavailable = False


def _db_has_encrypted() -> bool:
    try:
        c = sqlite3.connect(DB)
        row = c.execute("SELECT 1 FROM passwords WHERE password LIKE ? LIMIT 1", (PREFIX + "%",)).fetchone()
        c.close()
        return bool(row)
    except sqlite3.Error:
        return False


def _cipher():
    """Fernet con la clave del llavero, o None si no hay llavero utilizable."""
    global _fernet, _unavailable
    if _fernet is not None or _unavailable:
        return _fernet
    try:
        import keyring
        from cryptography.fernet import Fernet
        key = keyring.get_password(_SERVICE, _ACCOUNT)
        if not key:
            # Nunca crear una clave nueva si ya hay datos cifrados: quedarían ilegibles.
            if _db_has_encrypted():
                raise RuntimeError("falta la clave en el llavero y hay contraseñas cifradas")
            key = Fernet.generate_key().decode()
            keyring.set_password(_SERVICE, _ACCOUNT, key)
            if keyring.get_password(_SERVICE, _ACCOUNT) != key:
                raise RuntimeError("el llavero no conservó la clave")
        _fernet = Fernet(key.encode())
    except Exception as ex:
        _unavailable = True
        print(f"[Contraseñas] Llavero no disponible, no se cifrará: {ex}")
    return _fernet


def is_available() -> bool:
    return _cipher() is not None


def encrypt(plain: str) -> str:
    if not plain or plain.startswith(PREFIX):
        return plain or ""
    f = _cipher()
    if f is None:
        return plain
    return PREFIX + f.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    """Texto plano heredado pasa tal cual; lo cifrado ilegible devuelve ""."""
    if not value or not value.startswith(PREFIX):
        return value or ""
    f = _cipher()
    if f is None:
        return ""
    try:
        from cryptography.fernet import InvalidToken
        try:
            return f.decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
        except InvalidToken:
            print("[Contraseñas] No se pudo descifrar un registro (clave distinta)")
            return ""
    except Exception as ex:
        print(f"[Contraseñas] Error al descifrar: {ex}")
        return ""


def encrypt_legacy_passwords() -> int:
    """Cifra las contraseñas guardadas en texto plano. Devuelve cuántas cifró.

    Antes de la primera migración deja una copia de la BD (permisos 600) junto
    a ella, para poder recuperarse si algo falla; conviene borrarla después.
    """
    if _cipher() is None:
        return 0
    c = sqlite3.connect(DB)
    try:
        rows = c.execute(
            "SELECT id, password FROM passwords "
            "WHERE password IS NOT NULL AND password<>'' AND password NOT LIKE ?",
            (PREFIX + "%",)
        ).fetchall()
        if not rows:
            return 0
        backup = DB + BACKUP_SUFFIX
        if not os.path.exists(backup):
            dst = sqlite3.connect(backup)
            c.backup(dst)
            dst.close()
            os.chmod(backup, 0o600)
        # Sobrescribe con ceros las páginas liberadas para no dejar restos en claro.
        c.execute("PRAGMA secure_delete=ON")
        for pid, pwd in rows:
            c.execute("UPDATE passwords SET password=? WHERE id=?", (encrypt(pwd), pid))
        c.commit()
        return len(rows)
    finally:
        c.close()
