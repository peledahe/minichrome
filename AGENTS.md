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
  - `db.py`: DB schema/migrations in `_db()`, `get_config`/`set_config`, favorites/history helpers. Favorites can live in one-level folders (`fav_folders`, `fav.folder_id` NULL = no folder); the favorites panel in `window.py` (`_FavTree`, `_refresh_favs`, `_fav_*`) manages them.
  - `secure_store.py`: password encryption (`encrypt`/`decrypt`, `enc:v1:` prefix). Key lives in the system keyring (service `minichrome`); plaintext rows are still readable and get migrated at startup.
  - `widgets.py`: shared Qt styles, `_shadow`, `Notif`.
  - `bridges.py`: QWebChannel bridges exposed to JS:
    - `py` (`AgendaBridge`) for agenda, shopping, kanban, notes, media config, video/image APIs.
    - `pw` (`PasswordBridge`) for password CRUD and password auto-save policy.
  - `browser.py`: web profile (`profile()`), `WebPage` (password capture/autofill, bridge exposure: `py`/`pw` only on internal pages, `mcmedia` only on `chrome-extension://` pages), `WebView`.
  - `window.py`: main window `Minichrome` (tabs, bar, panels, shortcuts, "⋮" menu).
  - `screen_capture.py`: desktop area selection overlay (F9), Qt port of the ScreenShot app overlay.
  - `google_sync.py`: Google Calendar sync (desktop OAuth + PKCE, stdlib HTTP). OAuth client JSON and refresh token live in the system keyring; Google events are cached in `google_events`; dated activities are mirrored (all-day events tagged with `extendedProperties.private.mcKey`) into a dedicated "Minichrome" calendar. Exposed to `ui/newtab.html` (calendar modal) via `py.google_*` slots and the `google_changed` signal.
  - `native_video.py` + `native_video.qml`: native QtMultimedia player for local videos in `ui/videoplayer.html` that QtWebEngine can't decode (the PyPI build has no proprietary codecs: H.264/H.265/AAC); WebM VP9/AV1 stay in the page's `<video>` (Qt's FFmpeg only decodes AV1 in hardware). `NativeVideoPlayer` is a transparent `QQuickWidget` (`WA_AlwaysStackOnTop`) child of the `WebView`; the QML cuts the holes with `MultiEffect` because QWidget masks are ignored when a QQuickWidget is composited on screen (they still route clicks to the page), overlaid on `#main-player`; the page sends its rect, object-fit and the "holes" where page elements sit on top via `py.native_video_layout`, and receives `video_event` (time/playing/paused/ended/activity/action). `playback_mode()` probes codecs with `ffprobe`; thumbnails for undecodable videos come from `ffmpeg` (`py.request_video_thumbnail` + `video_thumbnail_ready`). Cinema mode falls back to `py.set_window_fullscreen` when the Fullscreen API has no user gesture.
  - `extensions.py`: Chrome extensions (MV3 only) on QtWebEngine's native `QWebEngineExtensionManager` (real `chrome-extension://` pages, service worker, storage, content scripts). The `extensions` table lists the original folders; each one is copied to `installed_extensions/.runtime/<id>` with `ui/extension_shim.js` injected into its service worker (`minichrome-sw.js` wrapper) and HTML pages, filling the `chrome.*` APIs Qt lacks (tabs.query, commands, contextMenus, action, storage.sync…). The extension UI opens in a right-side sliding panel (`ExtensionPanel`): the manifest `side_panel.default_path` page if any (fluid, full height), else the action popup sized to its own box (width and, when it has one, height) built on the same `browser.WebView` as tabs (no QGraphicsEffect on it: it breaks QWebEngineView painting/input); it exposes `mcext` (`ExtensionTabBridge`) over QWebChannel for active-tab operations.
    - Extension pages get `minichrome-qwebchannel.js` + the shim staged as files (their CSP blocks `qrc:`); the shim owns the QWebChannel and exposes `window.minichrome.objects` (`mcext` in the panel, `mcmedia` everywhere). `mcmedia` (`bridges.ExtensionMediaBridge`) plays H.264/H.265/AAC with `NativeVideoPlayer` for files inside folders the user granted to that extension through the File System Access API (`WebPage._handle_file_system_access` records them in `app_config` `extFsDirs`); used by Mk VideoPlayer (`~/Desarrollo/ChromeExtensions/VideoPlayer`).
    - Iframes refused by X-Frame-Options/frame-ancestors inside extension pages (Black Menu's Google services) can't be fixed in Qt: `WebPage.javaScriptConsoleMessage` spots the refusal and the shim covers the iframe with an "open in a tab" button.
    - Pitfalls: native `declarativeNetRequest` segfaults on `updateSessionRules` and ignores static rulesets in Qt 6.11, so `stage_extension` strips the DNR permissions (the shim stubs the API). Never call `setPersistentStoragePath()` on the profile (`setExtensionEnabled` segfaults); `browser._new_profile()` points Qt's default path to `web_cache/` with a symlink instead. `QWebEngineExtensionInfo` from signals dies with the slot: re-fetch it by ID and call `setExtensionEnabled` outside `loadFinished`.
  - `organizer_sync.py`: two-way sync of the organizer (agenda, shopping, income, Kanban, notes, passwords, debts, savings, shared `app_config` keys, budget currency/categories as `org:<key>`) with `mkorganizer_data.json` in Google Drive, the same file and format used by Mk Organizer (Electron, `~/Desarrollo/Organizer`) and its Chrome extension. Same algorithm as Organizer's `src/main/gdrive.js` and the extension's `gdrive_sync.js` (Drive wins if newer; otherwise upload, skipped when content is identical; the first sync with a given Drive file id — `organizerDriveFileId` — merges both sides by record signature instead of replacing). Token from `google_sync`; runs in a worker thread, serialized; triggered on page open (`desktop.syncDrive` in `ui/storage_bridge.js`), 5 s after any `AgendaBridge.updated`, on Google connect and every 10 min. Passwords travel decrypted in that file (shared format) and are re-encrypted on import. With the `drive.file` scope all three apps' OAuth clients must belong to the same Google Cloud project.
  - `slack_sync.py` + `slack_panel.py`: right-side "Slack" panel (💬 in the window controls) listing recent messages of the channels the user belongs to (public + private), with search, channel filter, click-to-open permalink in a new tab, ✕ to hide a message locally (`app_config` `slackDismissed`) and a composer to post as the user (`chat.postMessage`, ↩ replies in thread; text escaped with `slack_escape`). Sending needs the `chat:write` user scope: `can_send()` reads the granted scopes from Slack's `x-oauth-scopes` response header and the panel offers re-authorization when it is missing. Official Web API with a user token (`xoxp-`). The app is created from `SLACK_APP_MANIFEST` (read-only user scopes) with `apps.manifest.create` when the user pastes an app configuration token (`xoxe…`, not stored); its client id/secret go to the keyring (`minichrome` / `slack-app-client`). Connecting is OAuth v2: the authorize URL opens in a tab and `browser.WebPage.acceptNavigationRequest` intercepts `slack_sync.REDIRECT_URI` (`https://localhost/minichrome-slack-oauth`, never loaded), validates `state` and exchanges the code; the user token goes to `minichrome` / `slack-user-token`. Fetching runs in a thread (`auth.test`, `users.list` cached 1 h, `users.conversations`, `conversations.history`); refreshes on open and every 60 s while open. Message mrkdwn is converted to Qt rich text in `mrkdwn_to_html` (Slack already escapes `&<>`; only http/https/mailto links are made clickable).
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
- `ui/screenshot_editor.html` + `ui/screenshot_editor.js` + `ui/screenshot_editor.css`
  - Screenshot editor copied from the ScreenShot app (`~/Desarrollo/ScreenShot`, `index.html`/`editor.js`/`editor.css`) with minimal changes.
  - `ui/screenshot_bridge.js` provides the `window.electronAPI` the editor expects, backed by `py` slots (`copy_annotated_screenshot`, `save_screenshot_as`, `open_image_file`, `select_directory`, `start_area_screenshot` + `screenshot_ready` signal, `read_screenshot_image`, `discard_screenshot`).
  - To sync with upstream ScreenShot changes, re-copy `editor.js`/`editor.css` and keep the two marked edits at the top of `screenshot_editor.js`.
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