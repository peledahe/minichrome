# AGENTS.md

## Project Overview
- Stack: Python desktop app with PyQt6 + QtWebEngine, and UI built with HTML/CSS/JS in `ui/`.
- Main entrypoint: `main.py`.
- Persistence: SQLite database `browser_data.db`.
- Web runtime cache/profile: `web_cache/`.

## Run And Verify
- Run app: `python main.py`
- Quick syntax check (no launch): `python -m py_compile main.py`

## Architecture Map
- `main.py`
  - Bootstraps Qt app and main window (`Minichrome`).
  - Defines DB schema/migrations in `_db()`.
  - Exposes bridges to JS via QWebChannel:
    - `py` (`AgendaBridge`) for agenda, shopping, kanban, notes, media config, video/image APIs.
    - `pw` (`PasswordBridge`) for password CRUD and password auto-save policy.
- `ui/agenda.html` + `ui/agenda.js`
  - Multi-view app (Agenda, Compras, Ingresos, Kanban, Notas, Configuracion, Llaves).
  - Uses both bridges: `py` and `pw`.
- `ui/newtab.html`
  - New tab/start page; reads shared settings and opens internal apps.
- `ui/videoplayer.html` + `ui/videoplayer.js`
  - Uses QWebChannel `py` APIs for folders, videos, tags, playback, playlists.
- `ui/imageplayer.html` + `ui/imageplayer.js`
  - Uses QWebChannel `py` APIs for image browsing and file operations.
- `ui/passwords.html` + `ui/passwords.js`
  - Dedicated password manager page using `pw` bridge.

## Conventions For Changes
- Prefer small, surgical edits; preserve existing UI behavior and naming.
- Keep bridge contracts stable:
  - If JS calls `py.*` or `pw.*`, ensure corresponding `@pyqtSlot` methods exist and signatures stay compatible.
  - Do not move password methods from `pw` to `py`.
- Shared config lives in `app_config` and is consumed across pages; keep keys consistent.
- For features that touch both Python and JS:
  - Update bridge methods in `main.py`.
  - Update callers in the relevant `ui/*.js` file.
  - Verify UI state refresh paths (for example, `updated` signal hooks).

## Data And Safety Notes
- Do not modify or delete files under `web_cache/` manually unless task explicitly requires cache reset.
- Avoid editing generated/binary artifacts (`browser_data.db`, cache journals, LevelDB files) directly.
- Use SQL migrations in `_db()` for schema changes (additive and backward-compatible).

## Known Project-Specific Pitfalls
- Password UI and browser capture logic are split:
  - Browser capture/autofill logic is in `main.py` (`WebPage`).
  - UI password management exists in both `ui/passwords.*` and Agenda "Llaves" view.
- Internal app pages are loaded via `file://` and communicate with Python only through QWebChannel.
- If adding new settings, ensure both read and write paths are implemented and defaults are inserted with `INSERT OR IGNORE`.

## Suggested Validation After Edits
- If touching Python bridge/API:
  - Run `python -m py_compile main.py`.
  - Launch app and open the affected internal page to confirm bridge calls work.
- If touching password flows:
  - Verify add/edit/delete on `ui/passwords.html`.
  - Verify Agenda "Llaves" view still syncs and reflects updates.