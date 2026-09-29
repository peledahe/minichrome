# AGENTS.md

## Project Overview
- Stack: Python desktop app with PyQt6 + QtWebEngine, and UI built with HTML/CSS/JS in `ui/`.
- Main entrypoint: `main.py`.
- Persistence: SQLite database `browser_data.db`.
- Web runtime cache/profile: `web_cache/`.

## Run And Verify
- Runtime: PyQt6/QtWebEngine from PyPI (pinned in `requirements.txt`) inside `.venv`, not the system Qt from apt.
- Setup: `uv venv --python 3.12 .venv && VIRTUAL_ENV=.venv uv pip install -r requirements.txt`
- Run app: `.venv/bin/python main.py` (the desktop launcher `~/.local/share/applications/minibrowser.desktop` uses this interpreter)
- Quick syntax check (no launch): `.venv/bin/python -m py_compile *.py`

## Architecture Map
- Python modules (layered; lower layers never import upper ones):
  - `config.py`: paths (`BASE`, `DB`, `CACHE`, `HOME`, `UI_DIR`), `is_internal_url`, `settings.json`, quick links.
  - `db.py`: DB schema/migrations in `_db()`, `get_config`/`set_config`, favorites/history helpers.
  - `secure_store.py`: password encryption (`encrypt`/`decrypt`, `enc:v1:` prefix). Key lives in the system keyring (service `minichrome`); plaintext rows are still readable and get migrated at startup.
  - `widgets.py`: shared Qt styles, `_shadow`, `Notif`.
  - `bridges.py`: QWebChannel bridges exposed to JS:
    - `py` (`AgendaBridge`) for agenda, shopping, kanban, notes, media config, video/image APIs.
    - `pw` (`PasswordBridge`) for password CRUD and password auto-save policy.
  - `browser.py`: web profile (`profile()`), `WebPage` (password capture/autofill, bridge exposure only on internal pages), `WebView`.
  - `window.py`: main window `Minichrome` (tabs, bar, panels, shortcuts, "⋮" menu).
  - `google_sync.py`: Google Calendar sync (desktop OAuth + PKCE, stdlib HTTP). OAuth client JSON and refresh token live in the system keyring; Google events are cached in `google_events`; dated activities are mirrored (all-day events tagged with `extendedProperties.private.mcKey`) into a dedicated "Minichrome" calendar. Exposed to `ui/newtab.html` (calendar modal) via `py.google_*` slots and the `google_changed` signal.
  - `main.py`: entrypoint only (env flags, `QApplication`, password migration, window).
- `browser_features.py`
  - Standard browser features wired from `browser.py`/`window.py`: downloads panel (Ctrl+J), find bar (Ctrl+F), DevTools (F12), print/PDF (Ctrl+P), per-site permission prompts, certificate-error dialog, crashed-tab overlay.
  - "⋮ Más opciones" menu lives in `Minichrome._show_main_menu`; toggles `restoreSession` and `spellCheckEnabled` (`app_config`, default `'0'`).
  - Internal `ui/` pages skip permission prompts to keep their previous behavior.
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
  - Update bridge methods in `bridges.py`.
  - Update callers in the relevant `ui/*.js` file.
  - Verify UI state refresh paths (for example, `updated` signal hooks).

## Data And Safety Notes
- Do not modify or delete files under `web_cache/` manually unless task explicitly requires cache reset.
- Avoid editing generated/binary artifacts (`browser_data.db`, cache journals, LevelDB files) directly.
- Use SQL migrations in `_db()` for schema changes (additive and backward-compatible).

## Known Project-Specific Pitfalls
- Password UI and browser capture logic are split:
  - Browser capture/autofill logic is in `browser.py` (`WebPage`).
- Never read or write the `passwords.password` column directly: always go through `secure_store.encrypt`/`decrypt`.
  - UI password management exists in both `ui/passwords.*` and Agenda "Llaves" view.
- Internal app pages are loaded via `file://` and communicate with Python only through QWebChannel.
- If adding new settings, ensure both read and write paths are implemented and defaults are inserted with `INSERT OR IGNORE`.

## Suggested Validation After Edits
- If touching Python bridge/API:
  - Run `.venv/bin/python -m py_compile *.py`.
  - Launch app and open the affected internal page to confirm bridge calls work.
- If touching password flows:
  - Verify add/edit/delete on `ui/passwords.html`.
  - Verify Agenda "Llaves" view still syncs and reflects updates.