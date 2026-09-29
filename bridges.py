"""Bridges QWebChannel: `py` (AgendaBridge) y `pw` (PasswordBridge)."""
import os
import json
import base64
import shutil
import subprocess
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QFileDialog
from PyQt6.QtCore import QUrl, QObject, pyqtSlot, pyqtSignal, QStandardPaths, QBuffer, QIODevice
from PyQt6.QtGui import QImage
from secure_store import encrypt, decrypt
import google_sync
from db import _db, cleanup_original_screenshot, get_screenshots_dir, save_screenshot

# ─── Puente Agenda (Python <=> JS) ───────────────────────────────────────────
class AgendaBridge(QObject):

    updated = pyqtSignal()
    google_changed = pyqtSignal()  # estado o datos de Google Calendar cambiaron

    @pyqtSlot()
    def close_app(self):
        QApplication.quit()

    def __init__(self, parent=None):
        super().__init__(parent)
        google_sync.manager().changed.connect(self.google_changed)

    # ─── Google Calendar (google_sync.py) ─────────────────────────────────────
    @pyqtSlot(result=str)
    def google_status(self):
        return json.dumps(google_sync.manager().status())

    @pyqtSlot()
    def google_select_credentials(self):
        start = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        path, _ = QFileDialog.getOpenFileName(self.parent(), "Credenciales OAuth de Google (JSON)",
                                              start, "JSON (*.json)")
        if path:
            google_sync.manager().set_client_file(path)

    @pyqtSlot()
    def google_connect(self):
        google_sync.manager().connect()

    @pyqtSlot()
    def google_cancel_connect(self):
        google_sync.manager().cancel_connect()

    @pyqtSlot()
    def google_sync(self):
        google_sync.manager().sync()

    @pyqtSlot()
    def google_disconnect(self):
        google_sync.manager().disconnect()

    @pyqtSlot(result=str)
    def get_google_events(self):
        return json.dumps(google_sync.manager().events())

    @pyqtSlot(result=list)
    def get_agenda(self):
        c = _db(); res = c.execute("SELECT id, text, dueDate, done, COALESCE(notes,''), COALESCE(tag,'') FROM agenda ORDER BY id DESC").fetchall(); c.close()
        return [{"id":r[0],"text":r[1],"dueDate":r[2],"done":bool(r[3]),"notes":r[4],"tag":r[5]} for r in res]

    @pyqtSlot(str, str)
    @pyqtSlot(str, str, str)
    def add_agenda(self, text, date, tag=''):
        c = _db(); c.execute("INSERT INTO agenda(text, dueDate, tag) VALUES(?,?,?)", (text, date, (tag or '').strip())); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, str, str)
    @pyqtSlot(int, str, str, str)
    def update_agenda(self, aid, text, date, tag=None):
        c = _db()
        if tag is None:
            c.execute("UPDATE agenda SET text=?, dueDate=? WHERE id=?", (text, date, aid))
        else:
            c.execute("UPDATE agenda SET text=?, dueDate=?, tag=? WHERE id=?", (text, date, (tag or '').strip(), aid))
        c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int)
    def delete_agenda(self, aid):
        c = _db(); c.execute("DELETE FROM agenda WHERE id=?", (aid,)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, bool)
    def toggle_agenda(self, aid, done):
        c = _db(); c.execute("UPDATE agenda SET done=? WHERE id=?", (int(done), aid)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(str, int, str)
    def set_item_notes(self, table, item_id, notes):
        allowed = {'agenda', 'shopping', 'income'}
        if table not in allowed:
            return
        c = _db(); c.execute(f"UPDATE {table} SET notes=? WHERE id=?", (notes, item_id)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(result=list)
    def get_shopping(self):
        c = _db(); res = c.execute("SELECT id, text, value, currency, dueDate, paymentMethod, done, COALESCE(notes,'') FROM shopping ORDER BY id DESC").fetchall(); c.close()
        return [{"id":r[0],"text":r[1],"value":r[2],"currency":r[3],"dueDate":r[4],"paymentMethod":r[5],"done":bool(r[6]),"notes":r[7]} for r in res]

    @pyqtSlot(str, float, str, str, str)
    def add_shopping(self, text, val, cur, date, pm):
        c = _db(); c.execute("INSERT INTO shopping(text, value, currency, dueDate, paymentMethod) VALUES(?,?,?,?,?)", (text, val, cur, date, pm)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, str, float, str, str, str)
    def update_shopping(self, sid, text, val, cur, date, pm):
        c = _db(); c.execute("UPDATE shopping SET text=?, value=?, currency=?, dueDate=?, paymentMethod=? WHERE id=?", (text, val, cur, date, pm, sid)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int)
    def delete_shopping(self, sid):
        c = _db(); c.execute("DELETE FROM shopping WHERE id=?", (sid,)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, bool)
    def toggle_shopping(self, sid, done):
        c = _db(); c.execute("UPDATE shopping SET done=? WHERE id=?", (int(done), sid)); c.commit(); c.close()
        self.updated.emit()


    @pyqtSlot(result=list)
    def get_income(self):
        c = _db(); res = c.execute("SELECT id, text, value, currency, dueDate, received, COALESCE(notes,'') FROM income ORDER BY id DESC").fetchall(); c.close()
        return [{"id":r[0],"text":r[1],"value":r[2],"currency":r[3],"dueDate":r[4],"received":bool(r[5]),"notes":r[6]} for r in res]

    @pyqtSlot(str, float, str, str)
    def add_income(self, text, val, cur, date):
        c = _db(); c.execute("INSERT INTO income(text, value, currency, dueDate) VALUES(?,?,?,?)", (text, val, cur, date)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, bool)
    def toggle_income(self, iid, received):
        c = _db(); c.execute("UPDATE income SET received=? WHERE id=?", (int(received), iid)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, str, float, str, str)
    def update_income(self, iid, text, val, cur, date):
        c = _db(); c.execute("UPDATE income SET text=?, value=?, currency=?, dueDate=? WHERE id=?", (text, val, cur, date, iid)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int)
    def delete_income(self, iid):
        c = _db(); c.execute("DELETE FROM income WHERE id=?", (iid,)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int)
    def delete_kanban_card(self, cid):
        c = _db(); c.execute("DELETE FROM kanban_cards WHERE id=?", (cid,)); c.commit(); c.close()
        self.updated.emit()


    @pyqtSlot(str, result=str)
    def get_config(self, key):
        c = _db(); r = c.execute("SELECT val FROM app_config WHERE key=?", (key,)).fetchone(); c.close()
        return r[0] if r else ""

    @pyqtSlot(str, str)
    def set_config(self, key, val):
        c = _db(); c.execute("INSERT OR REPLACE INTO app_config(key,val) VALUES(?,?)", (key, val)); c.commit(); c.close()
        self.updated.emit()

    # ─── API de Videos (Sistema de archivos y yt-dlp) ─────────────────────────
    @pyqtSlot(result=str)
    def get_media_path(self):
        c = _db(); r = c.execute("SELECT val FROM app_config WHERE key='mediaPath'").fetchone(); c.close()
        path = r[0] if r else os.path.expanduser("~/Videos")
        return path if os.path.exists(path) else os.path.expanduser("~")

    def _normalize_rel(self, rel_path):
        if not rel_path or rel_path in (".", "/"):
            return ""
        return os.path.normpath(rel_path).replace("\\", "/")

    def _safe_media_path(self, rel_path):
        # Resolve the base media directory and target safely, allowing symlinks within the media path.
        base = os.path.realpath(self.get_media_path())
        rel_norm = self._normalize_rel(rel_path)
        target = os.path.realpath(os.path.join(base, rel_norm))
        # Ensure the resolved target is still inside the base directory.
        if os.path.commonpath([target, base]) != base:
            raise ValueError("Ruta fuera de la biblioteca")
        return target

    def _rel_to_media_url(self, rel_path):
        abs_path = self._safe_media_path(rel_path)
        return QUrl.fromLocalFile(abs_path).toString()

    def _legacy_media_url(self, rel_path):
        rel_norm = self._normalize_rel(rel_path)
        return f"/media/{rel_norm}" if rel_norm else "/media"

    def _normalize_media_scope(self, media_path):
        if not media_path:
            return ""
        return os.path.abspath(str(media_path)).replace("\\", "/").rstrip("/")

    def _media_scope_file_prefix(self, media_scope):
        scope_norm = self._normalize_media_scope(media_scope)
        if not scope_norm:
            return ""
        scope_url = QUrl.fromLocalFile(scope_norm).toString()
        return scope_url if scope_url.endswith("/") else scope_url + "/"

    def _migrate_video_metadata(self, old_rel, new_rel):
        old_url = self._rel_to_media_url(old_rel)
        new_url = self._rel_to_media_url(new_rel)
        old_legacy = self._legacy_media_url(old_rel)

        c = _db()
        playback_rows = c.execute(
            "SELECT url, time FROM video_playback WHERE url IN (?, ?)",
            (old_url, old_legacy)
        ).fetchall()
        for _old, t in playback_rows:
            c.execute(
                "INSERT OR REPLACE INTO video_playback(url, time) VALUES(?, ?)",
                (new_url, t)
            )
        c.execute("DELETE FROM video_playback WHERE url IN (?, ?)", (old_url, old_legacy))

        tag_rows = c.execute(
            "SELECT url, data FROM video_tags WHERE url IN (?, ?)",
            (old_url, old_legacy)
        ).fetchall()
        for _old, data in tag_rows:
            c.execute(
                "INSERT OR REPLACE INTO video_tags(url, data) VALUES(?, ?)",
                (new_url, data)
            )
        c.execute("DELETE FROM video_tags WHERE url IN (?, ?)", (old_url, old_legacy))

        c.commit()
        c.close()

    def _migrate_folder_metadata(self, old_rel_folder, new_rel_folder):
        old_rel = self._normalize_rel(old_rel_folder)
        new_rel = self._normalize_rel(new_rel_folder)
        if not old_rel or not new_rel:
            return

        old_file_prefix = self._rel_to_media_url(old_rel)
        new_file_prefix = self._rel_to_media_url(new_rel)
        if not old_file_prefix.endswith("/"):
            old_file_prefix += "/"
        if not new_file_prefix.endswith("/"):
            new_file_prefix += "/"

        old_legacy_prefix = self._legacy_media_url(old_rel)
        new_legacy_prefix = self._legacy_media_url(new_rel)
        if not old_legacy_prefix.endswith("/"):
            old_legacy_prefix += "/"
        if not new_legacy_prefix.endswith("/"):
            new_legacy_prefix += "/"

        c = _db()
        for table in ("video_playback", "video_tags"):
            rows = c.execute(f"SELECT url FROM {table}").fetchall()
            for (url_val,) in rows:
                new_url = url_val
                if url_val.startswith(old_file_prefix):
                    new_url = new_file_prefix + url_val[len(old_file_prefix):]
                elif url_val.startswith(old_legacy_prefix):
                    new_url = new_legacy_prefix + url_val[len(old_legacy_prefix):]

                if new_url != url_val:
                    c.execute(f"UPDATE {table} SET url=? WHERE url=?", (new_url, url_val))

        c.commit()
        c.close()

    def _purge_folder_metadata(self, rel_folder):
        rel_norm = self._normalize_rel(rel_folder)
        if not rel_norm:
            return

        file_prefix = self._rel_to_media_url(rel_norm)
        legacy_prefix = self._legacy_media_url(rel_norm)
        if not file_prefix.endswith("/"):
            file_prefix += "/"
        if not legacy_prefix.endswith("/"):
            legacy_prefix += "/"

        c = _db()
        c.execute("DELETE FROM video_playback WHERE url LIKE ? OR url LIKE ?", (f"{file_prefix}%", f"{legacy_prefix}%"))
        c.execute("DELETE FROM video_tags WHERE url LIKE ? OR url LIKE ?", (f"{file_prefix}%", f"{legacy_prefix}%"))
        c.commit()
        c.close()

    @pyqtSlot(result=str)
    def get_video_folders(self):
        import json
        base = os.path.abspath(self.get_media_path())

        video_exts = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4v', '.wmv', '.flv', '.ogv', '.m3u8', '.ts')
        
        def _build_tree(dir_path):
            nodes = []
            try:
                for entry in os.scandir(dir_path):
                    if entry.is_dir() and not entry.name.startswith('.'):
                        nodes.append({
                            "name": entry.name,
                            "path": os.path.relpath(entry.path, base),
                            "children": _build_tree(entry.path)
                        })
            except Exception:
                pass
            return sorted(nodes, key=lambda x: x['name'].lower())
            
        tree = _build_tree(base)
        
        # Verificar si hay videos en la raíz
        try:
            root_videos = [e.name for e in os.scandir(base) if e.is_file() and e.name.lower().endswith(video_exts)]
            if root_videos:
                tree.insert(0, {"name": "[Raíz de Biblioteca]", "path": ".", "children": []})
        except: pass
        
        return json.dumps(tree)

    @pyqtSlot(str, result=str)
    def get_videos(self, rel_path):
        import json
        rel_clean = self._normalize_rel(rel_path)
        target = self._safe_media_path(rel_clean)
        videos = []
        exts = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4v', '.wmv', '.flv', '.ogv', '.m3u8', '.ts')
        try:
            for entry in os.scandir(target):
                if entry.is_file() and entry.name.lower().endswith(exts):
                    rel_file = entry.name if not rel_clean else f"{rel_clean}/{entry.name}"
                    st = entry.stat()
                    video_data = {
                        "name": entry.name,
                        "url": self._rel_to_media_url(rel_file),
                        "size": st.st_size,
                        "mtime": st.st_mtime
                    }

                    base_name = os.path.splitext(entry.name)[0]
                    for sub_ext in ('.vtt', '.srt'):
                        sub_file = os.path.join(target, base_name + sub_ext)
                        if os.path.exists(sub_file):
                            rel_sub = (base_name + sub_ext) if not rel_clean else f"{rel_clean}/{base_name + sub_ext}"
                            video_data["subtitle"] = self._rel_to_media_url(rel_sub)
                            break

                    videos.append(video_data)
        except Exception:
            pass
        return json.dumps(sorted(videos, key=lambda x: x['name'].lower()))

    @pyqtSlot(str, str, result=bool)
    def rename_video(self, old_path, new_name):
        try:
            if not new_name:
                return False

            safe_name = os.path.basename(new_name.strip())
            if not safe_name:
                return False

            op = self._safe_media_path(old_path)
            np = os.path.join(os.path.dirname(op), safe_name)

            base = os.path.realpath(self.get_media_path())
            np_abs = os.path.realpath(np)
            if os.path.commonpath([np_abs, base]) != base:
                return False

            old_rel = os.path.relpath(op, base).replace("\\", "/")
            new_rel = os.path.relpath(np_abs, base).replace("\\", "/")

            os.rename(op, np_abs)

            # También renombrar subtítulos
            old_base = os.path.splitext(op)[0]
            new_base = os.path.splitext(np_abs)[0]
            for ext in ['.srt', '.vtt']:
                if os.path.exists(old_base + ext):
                    os.rename(old_base + ext, new_base + ext)

            self._migrate_video_metadata(old_rel, new_rel)
            return True
        except: return False

    @pyqtSlot(str, result=bool)
    def delete_video(self, rel_path):
        try:
            abs_video = self._safe_media_path(rel_path)
            if not os.path.isfile(abs_video):
                return False

            os.remove(abs_video)

            # Eliminar subtítulos asociados si existen
            base_no_ext = os.path.splitext(abs_video)[0]
            for ext in ('.srt', '.vtt'):
                sub_path = base_no_ext + ext
                if os.path.exists(sub_path):
                    os.remove(sub_path)

            rel_norm = self._normalize_rel(rel_path)
            file_url = self._rel_to_media_url(rel_norm)
            legacy_url = self._legacy_media_url(rel_norm)
            c = _db()
            c.execute("DELETE FROM video_playback WHERE url IN (?, ?)", (file_url, legacy_url))
            c.execute("DELETE FROM video_tags WHERE url IN (?, ?)", (file_url, legacy_url))
            c.commit()
            c.close()
            return True
        except: return False

    @pyqtSlot(str, str, str, result=bool)
    def move_video(self, filename, from_folder, to_folder):
        try:
            base = os.path.abspath(self.get_media_path())
            from_rel = self._normalize_rel(from_folder)
            to_rel = self._normalize_rel(to_folder)

            old_rel = filename if not from_rel else f"{from_rel}/{filename}"
            new_rel = filename if not to_rel else f"{to_rel}/{filename}"

            op = self._safe_media_path(old_rel)
            np = self._safe_media_path(new_rel)

            os.makedirs(os.path.dirname(np), exist_ok=True)
            shutil.move(op, np)

            # Mover subtítulos junto al video
            old_base = os.path.splitext(op)[0]
            new_base = os.path.splitext(np)[0]
            for ext in ('.srt', '.vtt'):
                old_sub = old_base + ext
                new_sub = new_base + ext
                if os.path.exists(old_sub):
                    os.makedirs(os.path.dirname(new_sub), exist_ok=True)
                    shutil.move(old_sub, new_sub)

            self._migrate_video_metadata(old_rel, new_rel)
            return True
        except: return False

    @pyqtSlot(str, str, result=bool)
    def create_folder(self, parent_path, folder_name):
        try:
            name = os.path.basename((folder_name or "").strip())
            if not name:
                return False

            parent_abs = self._safe_media_path(parent_path)
            new_folder = os.path.realpath(os.path.join(parent_abs, name))
            base = os.path.realpath(self.get_media_path())
            if os.path.commonpath([new_folder, base]) != base:
                return False

            os.makedirs(new_folder, exist_ok=True)
            return True
        except:
            return False

    @pyqtSlot(str, str, result=bool)
    def rename_folder(self, old_path, new_name):
        try:
            old_rel = self._normalize_rel(old_path)
            if not old_rel:
                return False

            safe_name = os.path.basename((new_name or "").strip())
            if not safe_name:
                return False

            old_abs = self._safe_media_path(old_rel)
            parent_abs = os.path.dirname(old_abs)
            new_abs = os.path.realpath(os.path.join(parent_abs, safe_name))
            base = os.path.realpath(self.get_media_path())
            if os.path.commonpath([new_abs, base]) != base:
                return False

            parent_rel = os.path.dirname(old_rel).replace("\\", "/")
            new_rel = safe_name if not parent_rel else f"{parent_rel}/{safe_name}"

            os.rename(old_abs, new_abs)
            self._migrate_folder_metadata(old_rel, new_rel)
            return True
        except:
            return False

    @pyqtSlot(str, result=bool)
    def delete_folder(self, folder_path):
        try:
            rel = self._normalize_rel(folder_path)
            if not rel:
                return False

            abs_folder = self._safe_media_path(rel)
            if not os.path.isdir(abs_folder):
                return False

            shutil.rmtree(abs_folder)
            self._purge_folder_metadata(rel)
            return True
        except:
            return False

    @pyqtSlot(str, result=str)
    def browse_folders(self, target_path):
        import json
        try:
            requested = (target_path or "").strip()
            if not requested:
                current = os.path.abspath(self.get_media_path())
            else:
                current = os.path.abspath(os.path.expanduser(requested))

            if not os.path.isdir(current):
                current = os.path.abspath(self.get_media_path())

            parent = os.path.dirname(current)
            if not parent:
                parent = current

            folders = []
            for entry in os.scandir(current):
                if entry.is_dir() and not entry.name.startswith('.'):
                    folders.append(entry.name)

            return json.dumps({
                "currentPath": current,
                "parentPath": parent,
                "folders": sorted(folders, key=lambda n: n.lower())
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @pyqtSlot(str, result=str)
    def search_video(self, filename):
        import json
        try:
            if not filename:
                return json.dumps({"found": False})

            base = os.path.abspath(self.get_media_path())
            for root, _dirs, files in os.walk(base):
                if filename in files:
                    rel_folder = os.path.relpath(root, base).replace("\\", "/")
                    rel_folder = "." if rel_folder == "." else rel_folder
                    rel_file = filename if rel_folder == "." else f"{rel_folder}/{filename}"
                    return json.dumps({
                        "found": True,
                        "folder": rel_folder,
                        "url": self._rel_to_media_url(rel_file)
                    })

            return json.dumps({"found": False})
        except Exception as e:
            return json.dumps({"found": False, "error": str(e)})

    # ─── API de Imagenes (Python + SQLite via app_config) ───────────────────
    @pyqtSlot(result=str)
    def get_image_media_path(self):
        c = _db(); r = c.execute("SELECT val FROM app_config WHERE key='imageMediaPath'").fetchone(); c.close()
        path = r[0] if r and r[0] else os.path.expanduser("~/Pictures")
        if not os.path.isdir(path):
            path = os.path.expanduser("~")
        return path

    def _safe_image_path(self, rel_path):
        base = os.path.abspath(self.get_image_media_path())
        rel_norm = self._normalize_rel(rel_path)
        target = os.path.abspath(os.path.join(base, rel_norm))
        if os.path.commonpath([target, base]) != base:
            raise ValueError("Ruta fuera de la biblioteca de imagenes")
        return target

    @pyqtSlot(result=str)
    def get_image_settings(self):
        import json
        c = _db()
        rows = c.execute("SELECT key, val FROM app_config WHERE key IN ('imageMediaPath', 'imageSortBy', 'imageLastFolder')").fetchall()
        c.close()
        data = {k: v for k, v in rows}
        return json.dumps({
            "imageMediaPath": data.get("imageMediaPath", self.get_image_media_path()),
            "sortBy": data.get("imageSortBy", "name-asc"),
            "lastFolder": data.get("imageLastFolder", ".")
        })

    @pyqtSlot(result=str)
    def get_image_folders(self):
        import json
        base = os.path.abspath(self.get_image_media_path())

        def _build_tree(dir_path):
            nodes = []
            try:
                for entry in os.scandir(dir_path):
                    if entry.is_dir() and not entry.name.startswith('.'):
                        rel = os.path.relpath(entry.path, base).replace("\\", "/")
                        nodes.append({
                            "name": entry.name,
                            "path": rel,
                            "children": _build_tree(entry.path)
                        })
            except Exception:
                pass
            return sorted(nodes, key=lambda x: x['name'].lower())

        return json.dumps(_build_tree(base))

    @pyqtSlot(str, result=str)
    def get_images(self, rel_path):
        import json
        image_exts = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif', '.tiff')
        rel = self._normalize_rel(rel_path)
        target = self._safe_image_path(rel)
        images = []
        try:
            for entry in os.scandir(target):
                if entry.is_file() and entry.name.lower().endswith(image_exts):
                    st = entry.stat()
                    rel_file = entry.name if not rel else f"{rel}/{entry.name}"
                    images.append({
                        "name": entry.name,
                        "path": rel_file,
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        "url": QUrl.fromLocalFile(os.path.abspath(entry.path)).toString()
                    })
        except Exception:
            pass
        return json.dumps(sorted(images, key=lambda x: x['name'].lower()))

    @pyqtSlot(str, result=str)
    def get_image_absolute_path(self, rel_path):
        return self._safe_image_path(rel_path)

    @pyqtSlot(str, str, result=str)
    def rename_image(self, rel_path, new_name):
        import json
        try:
            safe_name = os.path.basename((new_name or '').strip())
            if not safe_name:
                return json.dumps({"success": False, "error": "Nombre invalido"})

            old_abs = self._safe_image_path(rel_path)
            new_abs = os.path.join(os.path.dirname(old_abs), safe_name)
            base = os.path.abspath(self.get_image_media_path())
            new_abs = os.path.abspath(new_abs)
            if os.path.commonpath([new_abs, base]) != base:
                return json.dumps({"success": False, "error": "Ruta invalida"})

            os.rename(old_abs, new_abs)
            new_rel = os.path.relpath(new_abs, base).replace("\\", "/")
            return json.dumps({"success": True, "newPath": new_rel})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @pyqtSlot(str, str, result=bool)
    def move_image(self, rel_path, dest_folder):
        try:
            src = self._safe_image_path(rel_path)
            dst_dir = self._safe_image_path(dest_folder)
            if not os.path.isdir(dst_dir):
                return False
            dst = os.path.join(dst_dir, os.path.basename(src))
            shutil.move(src, dst)
            return True
        except Exception:
            return False

    @pyqtSlot(str, result=bool)
    def delete_image(self, rel_path):
        try:
            abs_path = self._safe_image_path(rel_path)
            if not os.path.isfile(abs_path):
                return False
            os.remove(abs_path)
            return True
        except Exception:
            return False

    @pyqtSlot(str, result=bool)
    def create_image_folder(self, rel_path):
        try:
            abs_path = self._safe_image_path(rel_path)
            os.makedirs(abs_path, exist_ok=True)
            return True
        except Exception:
            return False

    @pyqtSlot(str, str, result=bool)
    def rename_image_folder(self, old_rel_path, new_name):
        try:
            safe_name = os.path.basename((new_name or '').strip())
            if not safe_name:
                return False
            old_abs = self._safe_image_path(old_rel_path)
            new_abs = os.path.abspath(os.path.join(os.path.dirname(old_abs), safe_name))
            base = os.path.abspath(self.get_image_media_path())
            if os.path.commonpath([new_abs, base]) != base:
                return False
            os.rename(old_abs, new_abs)
            return True
        except Exception:
            return False

    @pyqtSlot(str, result=bool)
    def delete_image_folder(self, rel_path):
        try:
            abs_path = self._safe_image_path(rel_path)
            if not os.path.isdir(abs_path):
                return False
            shutil.rmtree(abs_path)
            return True
        except Exception:
            return False

    @pyqtSlot(str, result=str)
    def browse_local_path(self, target_path):
        import json
        try:
            requested = (target_path or '').strip()
            current = os.path.abspath(os.path.expanduser(requested if requested else self.get_image_media_path()))
            if not os.path.isdir(current):
                current = os.path.abspath(self.get_image_media_path())

            parent = os.path.dirname(current)
            if not parent:
                parent = current

            folders = []
            for entry in os.scandir(current):
                if entry.is_dir() and not entry.name.startswith('.'):
                    folders.append(entry.name)

            return json.dumps({
                "currentPath": current,
                "parentPath": parent,
                "folders": sorted(folders, key=lambda n: n.lower())
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @pyqtSlot(str, result=bool)
    def set_image_wallpaper(self, rel_path):
        """Aplica una imagen de la biblioteca como fondo de pantalla (Linux)."""
        try:
            abs_path = self._safe_image_path(rel_path)
            if not os.path.isfile(abs_path):
                return False

            file_uri = QUrl.fromLocalFile(abs_path).toString()
            desktop = (os.environ.get('XDG_CURRENT_DESKTOP', '') or '').lower()

            # GNOME / Ubuntu / Cinnamon (gsettings)
            if shutil.which('gsettings') and any(x in desktop for x in ['gnome', 'ubuntu', 'cinnamon']):
                subprocess.run(['gsettings', 'set', 'org.gnome.desktop.background', 'picture-uri', file_uri], check=False)
                subprocess.run(['gsettings', 'set', 'org.gnome.desktop.background', 'picture-uri-dark', file_uri], check=False)
                return True

            # XFCE (xfconf-query)
            if shutil.which('xfconf-query') and 'xfce' in desktop:
                # Ruta comun para fondo en XFCE; si falla, simplemente devuelve False
                subprocess.run([
                    'xfconf-query', '-c', 'xfce4-desktop',
                    '-p', '/backdrop/screen0/monitor0/image-path', '-s', abs_path
                ], check=False)
                return True

            # Fallback generico con feh (si existe)
            if shutil.which('feh'):
                subprocess.run(['feh', '--bg-fill', abs_path], check=False)
                return True

            return False
        except Exception:
            return False

    @pyqtSlot(str, result=str)
    def resolve_video_url(self, url):
        """Usa yt-dlp nativamente para resolver la URL de streaming."""
        import subprocess, json
        yt_dlp_path = '/home/perry/.local/bin/yt-dlp'
        try:
            # Determinamos si es youtube u otra cosa
            site = "YouTube" if "youtu" in url else "Externo"
            if "xhamster" in url: site = "xHamster"
            elif "pornhub" in url: site = "Pornhub"
            
            res = subprocess.run([
                yt_dlp_path, '-f', 'best[ext=mp4][protocol=https]/best',
                '--get-url', '--get-title', '--no-playlist', 
                '--add-header', 'Cookie:parental-control=yes; AgeGate=1', url
            ], capture_output=True, text=True, timeout=15)
            
            if res.returncode == 0:
                lines = [l for l in res.stdout.strip().split('\n') if l]
                title = lines[0] if len(lines) > 0 else "Video"
                vurl = lines[1] if len(lines) > 1 else None
                aurl = lines[2] if len(lines) > 2 else None
                
                if vurl:
                    return json.dumps({
                        "type": "youtube-direct",
                        "videoUrl": vurl, # Devolvemos directo, luego hacemos proxy si es necesario
                        "audioUrl": aurl,
                        "name": f"{site} - {title}",
                        "videoId": url.split('=')[-1] if '=' in url else url.split('/')[-1]
                    })
            
            # Fallback a embed si falla yt-dlp
            vid = url.split('/')[-1].split('=')[-1]
            return json.dumps({
                "type": "embed", "id": vid, "url": url, "name": f"{site} - Video"
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── Cloud Playlists, Playback y Tags ──────────────────────────────────────
    @pyqtSlot(result=str)
    def get_playlists(self):
        c = _db(); res = c.execute("SELECT id, name, items FROM video_playlists ORDER BY id ASC").fetchall(); c.close()
        import json
        return json.dumps([{"id": r[0], "name": r[1], "items": json.loads(r[2])} for r in res])

    @pyqtSlot(str)
    def set_playlists(self, data_json):
        import json
        lists = json.loads(data_json)
        c = _db()
        c.execute("DELETE FROM video_playlists")
        for i, lst in enumerate(lists):
            c.execute("INSERT INTO video_playlists(id, name, items) VALUES(?,?,?)", (i, lst.get('name',''), json.dumps(lst.get('items',[]))))
        c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(str, str)
    def save_playback(self, url, time_str):
        c = _db(); c.execute("INSERT OR REPLACE INTO video_playback(url, time) VALUES(?,?)", (url, float(time_str))); c.commit(); c.close()

    @pyqtSlot(result=str)
    def get_playback_history(self):
        import json
        c = _db(); res = c.execute("SELECT url, time FROM video_playback").fetchall(); c.close()
        return json.dumps({r[0]: r[1] for r in res})

    @pyqtSlot(result=str)
    def get_video_tags(self):
        import json
        c = _db(); res = c.execute("SELECT url, data FROM video_tags").fetchall(); c.close()
        return json.dumps({r[0]: json.loads(r[1]) for r in res})

    @pyqtSlot(str, result=str)
    def get_video_tags_for_path(self, media_path):
        import json
        scope = self._normalize_media_scope(media_path)
        c = _db()

        rows = c.execute(
            "SELECT url, data FROM video_tags WHERE COALESCE(scope, '') = ?",
            (scope,)
        ).fetchall()

        tags_map = {}
        for url, data in rows:
            try:
                tags_map[url] = json.loads(data)
            except Exception:
                tags_map[url] = {}

        # Compatibilidad: si habia etiquetas antiguas sin scope, migrarlas al scope actual.
        file_prefix = self._media_scope_file_prefix(scope)
        if scope and file_prefix:
            legacy_rows = c.execute(
                "SELECT url, data FROM video_tags WHERE COALESCE(scope, '') = '' AND url LIKE ?",
                (f"{file_prefix}%",)
            ).fetchall()

            migrated = False
            for url, data in legacy_rows:
                if url not in tags_map:
                    try:
                        tags_map[url] = json.loads(data)
                    except Exception:
                        tags_map[url] = {}
                c.execute("UPDATE video_tags SET scope=? WHERE url=?", (scope, url))
                migrated = True

            if migrated:
                c.commit()

        c.close()
        return json.dumps(tags_map)

    @pyqtSlot(str)
    def save_video_tags(self, data_json):
        # Compatibilidad con clientes viejos: guardar en scope vacio.
        self.save_video_tags_for_path("", data_json)

    @pyqtSlot(str, str)
    def save_video_tags_for_path(self, media_path, data_json):
        import json
        scope = self._normalize_media_scope(media_path)
        tags_map = json.loads(data_json)
        if not isinstance(tags_map, dict):
            tags_map = {}

        c = _db()
        c.execute("DELETE FROM video_tags WHERE COALESCE(scope, '') = ?", (scope,))
        for url, data in tags_map.items():
            c.execute(
                "INSERT OR REPLACE INTO video_tags(url, data, scope) VALUES(?,?,?)",
                (url, json.dumps(data), scope)
            )
        c.commit(); c.close()

    @pyqtSlot(str)
    def clear_video_tags_for_path(self, media_path):
        scope = self._normalize_media_scope(media_path)
        c = _db()
        c.execute("DELETE FROM video_tags WHERE COALESCE(scope, '') = ?", (scope,))
        c.commit(); c.close()

    @pyqtSlot(result=list)
    def get_kanban_cols(self):
        c = _db(); res = c.execute("SELECT id, title, pos FROM kanban_cols ORDER BY pos ASC").fetchall(); c.close()
        return [{"id":r[0],"title":r[1],"pos":r[2]} for r in res]

    @pyqtSlot(int, result=list)
    def get_kanban_cards(self, col_id):
        c = _db(); res = c.execute("SELECT id, col_id, text, pos FROM kanban_cards WHERE col_id=? ORDER BY pos ASC", (col_id,)).fetchall(); c.close()
        return [{"id":r[0],"col_id":r[1],"text":r[2],"pos":r[3]} for r in res]

    @pyqtSlot(str, int)
    def add_kanban_col(self, title, pos):
        c = _db(); c.execute("INSERT INTO kanban_cols(title, pos) VALUES(?,?)", (title, pos)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, str, int)
    def add_kanban_card(self, col_id, text, pos):
        c = _db(); c.execute("INSERT INTO kanban_cards(col_id, text, pos) VALUES(?,?,?)", (col_id, text, pos)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, int, int)
    def move_kanban_card(self, card_id, new_col_id, new_pos):
        c = _db(); c.execute("UPDATE kanban_cards SET col_id=?, pos=? WHERE id=?", (new_col_id, new_pos, card_id)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, int, str)
    def update_kanban_card(self, card_id, col_id, text):
        c = _db(); c.execute("UPDATE kanban_cards SET col_id=?, text=? WHERE id=?", (col_id, text, card_id)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(result=list)
    def get_notes(self):
        c = _db(); res = c.execute("SELECT id, content, color, x, y, width, height, z_index FROM notes ORDER BY z_index ASC").fetchall(); c.close()
        return [{"id":r[0],"content":r[1] or '',"color":r[2] or 'yellow',"x":r[3] if r[3] is not None else 20,"y":r[4] if r[4] is not None else 20,"width":r[5] if r[5] is not None else 220,"height":r[6] if r[6] is not None else 170,"zIndex":r[7] or 1} for r in res]

    @pyqtSlot(str, int, int, int, result=int)
    def add_note(self, color, x, y, z_index):
        c = _db()
        cur = c.execute("INSERT INTO notes(content, color, x, y, z_index) VALUES('',?,?,?,?)", (color, x, y, z_index))
        c.commit()
        nid = cur.lastrowid
        c.close()
        return nid

    @pyqtSlot(int, str)
    def update_note_content(self, nid, content):
        c = _db(); c.execute("UPDATE notes SET content=? WHERE id=?", (content, nid)); c.commit(); c.close()

    @pyqtSlot(int, str)
    def update_note_color(self, nid, color):
        c = _db(); c.execute("UPDATE notes SET color=? WHERE id=?", (color, nid)); c.commit(); c.close()

    @pyqtSlot(int, int, int)
    def update_note_pos(self, nid, x, y):
        c = _db(); c.execute("UPDATE notes SET x=?, y=? WHERE id=?", (x, y, nid)); c.commit(); c.close()

    @pyqtSlot(int, int, int)
    def update_note_size(self, nid, width, height):
        width = max(220, int(width or 220))
        height = max(170, int(height or 170))
        c = _db(); c.execute("UPDATE notes SET width=?, height=? WHERE id=?", (width, height, nid)); c.commit(); c.close()

    @pyqtSlot(int, int)
    def update_note_zindex(self, nid, z_index):
        c = _db(); c.execute("UPDATE notes SET z_index=? WHERE id=?", (z_index, nid)); c.commit(); c.close()

    @pyqtSlot(int)
    def delete_note(self, nid):
        c = _db(); c.execute("DELETE FROM notes WHERE id=?", (nid,)); c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(str, str, result=str)
    def save_annotated_screenshot(self, data_url, original_path):
        try:
            if not data_url or not data_url.startswith("data:image/"):
                return ""
            payload = data_url.split(",", 1)[1]
            raw = base64.b64decode(payload)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            screenshots_dir = get_screenshots_dir()
            path = os.path.join(screenshots_dir, f"shot_annotated_{stamp}.png")
            with open(path, "wb") as f:
                f.write(raw)
            save_screenshot(path, "annotated")
            cleanup_original_screenshot(original_path, screenshots_dir)
            return path
        except Exception as ex:
            print(f"[Screenshot] Error al guardar anotacion: {ex}")
            return ""

    @pyqtSlot(str, str, result=bool)
    def copy_annotated_screenshot(self, data_url, original_path):
        try:
            if not data_url or not data_url.startswith("data:image/"):
                return False
            payload = data_url.split(",", 1)[1]
            raw = base64.b64decode(payload)
            image = QImage()
            if not image.loadFromData(raw, "PNG"):
                return False
            QApplication.clipboard().setImage(image)
            cleanup_original_screenshot(original_path, get_screenshots_dir())
            return True
        except Exception as ex:
            print(f"[Screenshot] Error al copiar anotacion: {ex}")
            return False

    # ─── Editor de capturas (misma API que usa el editor de ScreenShot) ──────
    screenshot_ready = pyqtSignal(str)  # data URL de una nueva captura de área

    @staticmethod
    def _image_data_url(path):
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = {"png": "image/png", "webp": "image/webp", "gif": "image/gif",
                "bmp": "image/bmp"}.get(ext, "image/jpeg")
        with open(path, "rb") as f:
            return f"data:{mime};base64,{base64.b64encode(f.read()).decode('ascii')}"

    @pyqtSlot(str, result=str)
    def read_screenshot_image(self, path):
        """Data URL de una captura de Minichrome (solo archivos de la carpeta de capturas)."""
        try:
            src = QUrl(path).toLocalFile() if path.startswith("file://") else path
            base = os.path.realpath(get_screenshots_dir())
            real = os.path.realpath(src)
            if not real.startswith(base + os.sep) or not os.path.isfile(real):
                return ""
            return self._image_data_url(real)
        except Exception as ex:
            print(f"[Screenshot] No se pudo leer la captura: {ex}")
            return ""

    @pyqtSlot(str, str, result=str)
    def save_screenshot_as(self, data_url, default_dir):
        """Diálogo 'Guardar como' (igual que ScreenShot). Devuelve JSON {success, filePath, canceled}."""
        try:
            if not data_url.startswith("data:image/"):
                return json.dumps({"success": False})
            target = default_dir if default_dir and os.path.isdir(default_dir) else get_screenshots_dir()
            name = f"ScreenShot_{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.png"
            path, _ = QFileDialog.getSaveFileName(self.parent(), "Guardar Captura de Pantalla",
                                                  os.path.join(target, name), "Imágenes PNG (*.png)")
            if not path:
                return json.dumps({"success": False, "canceled": True})
            if not path.lower().endswith(".png"):
                path += ".png"
            with open(path, "wb") as f:
                f.write(base64.b64decode(data_url.split(",", 1)[1]))
            save_screenshot(path, "annotated")
            return json.dumps({"success": True, "filePath": path})
        except Exception as ex:
            print(f"[Screenshot] Error al guardar: {ex}")
            return json.dumps({"success": False, "error": str(ex)})

    @pyqtSlot(result=str)
    def select_directory(self):
        path = QFileDialog.getExistingDirectory(self.parent(), "Seleccionar Carpeta para Guardar Capturas",
                                                get_screenshots_dir())
        return path or ""

    @pyqtSlot(result=str)
    def open_image_file(self):
        """Diálogo 'Abrir imagen'. Devuelve JSON {success, dataUrl, canceled}."""
        start = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        path, _ = QFileDialog.getOpenFileName(self.parent(), "Abrir Imagen para Editar", start,
                                              "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if not path:
            return json.dumps({"success": False, "canceled": True})
        try:
            return json.dumps({"success": True, "dataUrl": self._image_data_url(path), "filePath": path})
        except Exception as ex:
            return json.dumps({"success": False, "error": str(ex)})

    @pyqtSlot()
    def start_area_screenshot(self):
        """Nueva captura (F9): selección de área del escritorio; emite screenshot_ready."""
        import screen_capture
        mw = self.parent().main_win

        def done(pixmap):
            if pixmap is None or pixmap.isNull():
                return
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buf, "PNG")
            self.screenshot_ready.emit("data:image/png;base64," + base64.b64encode(bytes(buf.data())).decode("ascii"))

        screen_capture.capture_area(mw, done)

    @pyqtSlot(str, result=bool)
    def discard_screenshot(self, original_path):
        try:
            cleanup_original_screenshot(original_path, get_screenshots_dir())
            return True
        except Exception as ex:
            print(f"[Screenshot] Error al descartar captura: {ex}")
            return False

    @pyqtSlot()
    def close_current_tab(self):
        self.parent().main_win._close_tab_safe(self.parent().main_win._active)

    @pyqtSlot()
    def window_minimize(self):
        self.parent().main_win.showMinimized()

    @pyqtSlot()
    def window_maximize(self):
        mw = self.parent().main_win
        if mw.isMaximized(): mw.showNormal()
        else: mw.showMaximized()

    @pyqtSlot()
    def window_close(self):
        # Cerramos solo la pestaña actual si es la agenda
        self.parent().main_win._close_tab_safe(self.parent().main_win._active)

    @pyqtSlot()
    def hide_browser_bar(self):
        mw = self.parent().main_win
        if mw and mw._bar_open:
            mw._hide_bar()

    @pyqtSlot()
    def show_browser_bar(self):
        mw = self.parent().main_win
        if mw and not mw._bar_open:
            mw._show_bar()

    @pyqtSlot(result=bool)
    def is_browser_bar_open(self):
        mw = self.parent().main_win
        return bool(mw and mw._bar_open)


class PasswordBridge(QObject):
    updated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

    def _normalize_type(self, site, pwd_type):
        t = (pwd_type or '').strip().lower()
        if t in ('web', 'app', 'db'):
            return t
        if t in ('database', 'base de datos', 'basedatos', 'base_de_datos'):
            return 'db'
        return 'web' if '.' in (site or '') else 'app'

    def _find_existing_id(self, c, site, user, exclude_id=None):
        base_sql = (
            "SELECT id FROM passwords "
            "WHERE lower(trim(site))=lower(trim(?)) "
            "AND lower(trim(username))=lower(trim(?))"
        )
        params = [site, user]
        if exclude_id:
            base_sql += " AND id<>?"
            params.append(int(exclude_id))
        row = c.execute(base_sql + " ORDER BY id ASC LIMIT 1", tuple(params)).fetchone()
        return int(row[0]) if row else None

    def _normalize_policy(self, policy):
        val = (policy or 'ask').strip().lower()
        return val if val in ('ask', 'always', 'never') else 'ask'

    @pyqtSlot(result=str)
    def get_auto_save_policy(self):
        c = _db()
        row = c.execute("SELECT val FROM app_config WHERE key='passwordAutoSavePolicy'").fetchone()
        c.close()
        return self._normalize_policy(row[0] if row else 'ask')

    @pyqtSlot(str)
    def set_auto_save_policy(self, policy):
        val = self._normalize_policy(policy)
        c = _db()
        c.execute("INSERT OR REPLACE INTO app_config(key,val) VALUES(?,?)", ('passwordAutoSavePolicy', val))
        c.commit()
        c.close()
        self.updated.emit()

    @pyqtSlot(result=list)
    def get_passwords(self):
        c = _db()
        res = c.execute(
            "SELECT id, site, username, password, type, url, notes, ts FROM passwords ORDER BY site ASC"
        ).fetchall()
        c.close()
        return [
            {
                "id": r[0],
                "site": r[1],
                "username": r[2],
                "password": decrypt(r[3]),
                "type": r[4] or self._normalize_type(r[1], ''),
                "url": r[5] or '',
                "notes": r[6] or '',
                "ts": r[7]
            }
            for r in res
        ]

    @pyqtSlot(str, str, str)
    def save_password(self, site, user, pwd):
        site = (site or '').strip()
        user = (user or '').strip()
        pwd = pwd or ''
        if not site or not user or not pwd:
            return

        c = _db()
        existing_id = self._find_existing_id(c, site, user)
        pwd_type = self._normalize_type(site, '')
        if existing_id:
            c.execute(
                "UPDATE passwords SET password=?, type=?, ts=CURRENT_TIMESTAMP WHERE id=?",
                (encrypt(pwd), pwd_type, existing_id)
            )
        else:
            c.execute(
                "INSERT INTO passwords(site, username, password, type, url, notes) VALUES(?,?,?,?,?,?)",
                (site, user, encrypt(pwd), pwd_type, '', '')
            )
        c.commit(); c.close()
        self.updated.emit()

    @pyqtSlot(int, str, str, str, str, str, str, result=int)
    def upsert_password(self, pid, site, user, pwd, pwd_type, url, notes):
        site = (site or '').strip()
        user = (user or '').strip()
        pwd = pwd or ''
        if not site or not user or not pwd:
            return 0

        c = _db()
        norm_type = self._normalize_type(site, pwd_type)
        row = c.execute("SELECT id FROM passwords WHERE id=?", (pid,)).fetchone() if pid else None

        if row:
            duplicate_id = self._find_existing_id(c, site, user, exclude_id=pid)
            if duplicate_id:
                # Unificar en un solo registro cuando una edición colisiona con otro ya existente.
                c.execute(
                    "UPDATE passwords SET site=?, username=?, password=?, type=?, url=?, notes=?, ts=CURRENT_TIMESTAMP WHERE id=?",
                    (site, user, encrypt(pwd), norm_type, url or '', notes or '', duplicate_id)
                )
                c.execute("DELETE FROM passwords WHERE id=?", (pid,))
                new_id = duplicate_id
            else:
                c.execute(
                    "UPDATE passwords SET site=?, username=?, password=?, type=?, url=?, notes=?, ts=CURRENT_TIMESTAMP WHERE id=?",
                    (site, user, encrypt(pwd), norm_type, url or '', notes or '', pid)
                )
                new_id = pid
        else:
            existing_id = self._find_existing_id(c, site, user)
            if existing_id:
                c.execute(
                    "UPDATE passwords SET password=?, type=?, url=?, notes=?, ts=CURRENT_TIMESTAMP WHERE id=?",
                    (encrypt(pwd), norm_type, url or '', notes or '', existing_id)
                )
                new_id = existing_id
            else:
                c.execute(
                    "INSERT INTO passwords(site, username, password, type, url, notes) VALUES(?,?,?,?,?,?)",
                    (site, user, encrypt(pwd), norm_type, url or '', notes or '')
                )
                new_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

        c.commit(); c.close()
        self.updated.emit()
        return int(new_id)

    @pyqtSlot(int)
    def delete_password(self, pid):
        c = _db(); c.execute("DELETE FROM passwords WHERE id=?", (pid,)); c.commit(); c.close()
        self.updated.emit()
