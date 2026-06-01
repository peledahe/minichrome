// API migrada a QWebChannel
// DOM Elements
const folderList = document.getElementById('folder-list');
const videoList = document.getElementById('video-list');
const mainPlayer = document.getElementById('main-player');
const currentFolderName = document.getElementById('current-folder-name');
const currentVideoTitle = document.getElementById('current-video-title');
const videoInfo = document.querySelector('.video-info');
const hideBtn = document.getElementById('hide-btn');
const deleteModal = document.getElementById('delete-modal');
const confirmDeleteBtn = document.getElementById('confirm-delete');
const cancelDeleteBtn = document.getElementById('cancel-delete');
const prevBtn = document.getElementById('prev-btn');
const nextBtn = document.getElementById('next-btn');
const toggleSidebarBtn = document.getElementById('toggle-sidebar');
const playlistBtn = document.getElementById('playlist-btn');
const resetPlayerBtn = document.getElementById('reset-player-btn');
const toggleUiBtn = document.getElementById('toggle-ui');
const appContainer = document.querySelector('.app-container');
const playlistSidebar = document.getElementById('playlist-sidebar');
const settingsBtn = document.getElementById('settings-btn');
const sidebar = document.querySelector('.sidebar');
const closeSidebarMobileBtn = document.getElementById('close-sidebar-mobile');

// --- Elementos Cloud ---
const closeAppBtn = document.getElementById('close-app-btn');

// Botón para cerrar la aplicación completamente (solo en videoplayer)
if (closeAppBtn) {
    closeAppBtn.addEventListener('click', () => {
        // Si está en un entorno tipo Electron/QtWebEngine, usar la API expuesta
        if (window.qt && window.qt.closeApp) {
            window.qt.closeApp();
        } else if (window.closeApp) {
            window.closeApp();
        } else if (typeof py !== 'undefined' && py.close_app) {
            py.close_app();
        } else {
            // Fallback: cerrar ventana del navegador (no siempre funcionará)
            window.open('', '_self');
            window.close();
        }
    });
}
const cloudPlaylistList = document.getElementById('cloud-playlist-list');
const newCloudPlaylistBtn = document.getElementById('new-cloud-playlist');
const cloudModal = document.getElementById('cloud-modal');
const closeCloudModalBtn = document.getElementById('close-cloud-modal');
const cancelCloudModalBtn = document.getElementById('cancel-cloud-modal');
const saveCloudModalBtn = document.getElementById('save-cloud-modal');
const cloudUrlInput = document.getElementById('cloud-url-input');
const addToCloudBtn = document.getElementById('add-to-cloud-btn');
const cloudItemsList = document.getElementById('cloud-items-list');
const cloudPlaylistNameInput = document.getElementById('cloud-playlist-name-input');
const externalPlayer = document.getElementById('external-player');

let cloudPlaylists = [];
let activeCloudPlaylistIndex = -1;

// --- Etiquetas ---
const tagsList = document.getElementById('tags-list');
const tagsModal = document.getElementById('tags-modal');
const closeTagsModalBtn = document.getElementById('close-tags-modal');
const doneTagsModalBtn = document.getElementById('done-tags-modal');
const newTagInput = document.getElementById('new-tag-input');
const addTagBtn = document.getElementById('add-tag-btn');
const currentVideoTagsDiv = document.getElementById('current-video-tags');
const allAvailableTagsDiv = document.getElementById('all-available-tags');
const tagsVideoTitle = document.getElementById('tags-video-title');

let videoTags = {};
let currentTaggingVideo = null;
let currentTaggingFolder = null;

const settingsModal = document.getElementById('settings-modal');
const saveSettingsBtn = document.getElementById('save-settings');
const closeSettingsBtn = document.getElementById('close-settings');
const configHomeUrl = document.getElementById('config-home-url');
const configMediaPath = document.getElementById('config-media-path');
const configStartMuted = document.getElementById('config-start-muted');
const clearAllTagsBtn = document.getElementById('clear-all-tags-btn');
const privacyMock = null; // eliminado, ahora es iframe independiente
const browserModal = document.getElementById('browser-modal');
const btnBrowseLocal = document.getElementById('btn-browse-local');
const browserList = document.getElementById('browser-list');
const browserCurrentPath = document.getElementById('browser-current-path');
const selectThisFolder = document.getElementById('select-this-folder');
const closeBrowserBtn = document.getElementById('close-browser');
const sortSelect = document.getElementById('sort-select');
const privacyFrame = document.getElementById('privacy-frame');
const browserScreen = document.getElementById('browser-screen');
let hlsInstance = null;
const STARTUP_VIDEO_URL = new URL('movie.mp4', window.location.href).toString();

// Estado global que en Node/Electron vivia en app.js
let settings = {
    mediaPath: '',
    startMuted: true,
    homeUrl: '',
    sortBy: 'name-asc'
};

const DbManager = {
    dbName: 'DeskioDB',
    dbVersion: 1,
    db: null,

    async init() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.dbVersion);
            request.onerror = (e) => reject(e);
            request.onupgradeneeded = (e) => {
                const db = e.target.result;
                if (!db.objectStoreNames.contains('thumbnails')) {
                    db.createObjectStore('thumbnails', { keyPath: 'url' });
                }
            };
            request.onsuccess = (e) => {
                this.db = e.target.result;
                resolve(this.db);
            };
        });
    },

    async get(storeName, key) {
        if (!this.db) return null;
        return new Promise((resolve) => {
            const tx = this.db.transaction([storeName], 'readonly');
            const store = tx.objectStore(storeName);
            const request = store.get(key);
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => resolve(null);
        });
    },

    async put(storeName, data) {
        if (!this.db) return false;
        return new Promise((resolve) => {
            const tx = this.db.transaction([storeName], 'readwrite');
            const store = tx.objectStore(storeName);
            const request = store.put(data);
            request.onsuccess = () => resolve(true);
            request.onerror = () => resolve(false);
        });
    },

    async delete(storeName, key) {
        if (!this.db) return false;
        return new Promise((resolve) => {
            const tx = this.db.transaction([storeName], 'readwrite');
            const store = tx.objectStore(storeName);
            const request = store.delete(key);
            request.onsuccess = () => resolve(true);
            request.onerror = () => resolve(false);
        });
    },

    async migrate(storeName, oldKey, newKey) {
        const existing = await this.get(storeName, oldKey);
        if (!existing) return;
        existing.url = newKey;
        await this.put(storeName, existing);
        await this.delete(storeName, oldKey);
    }
};

function showNotification(message, type = 'info', sticky = false) {
    let container = document.getElementById('notification-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notification-container';
        document.body.appendChild(container);
    }

    const notification = document.createElement('div');
    notification.className = `notification ${type} ${sticky ? 'sticky' : ''}`;
    const icon = type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️';
    notification.innerHTML = `
        <div style="display:flex; align-items:center; gap:10px;">
            <span>${icon}</span>
            <span style="flex:1;">${message}</span>
            ${sticky ? '<button class="close-notification" style="background:transparent;border:none;color:inherit;cursor:pointer;font-size:1.2rem;">&times;</button>' : ''}
        </div>
    `;

    container.appendChild(notification);
    setTimeout(() => notification.classList.add('active'), 10);

    if (sticky) {
        const closeBtn = notification.querySelector('.close-notification');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                notification.classList.remove('active');
                setTimeout(() => notification.remove(), 400);
            });
        }
    } else {
        setTimeout(() => {
            notification.classList.remove('active');
            setTimeout(() => notification.remove(), 400);
        }, 3500);
    }
}

function updateAgendaMiniIcon() {
    const miniIconContainer = document.getElementById('header-mini-calendar');
    if (!miniIconContainer) return;

    const now = new Date();
    const month = now.toLocaleString('es', { month: 'short' }).replace('.', '');
    const day = now.getDate();

    miniIconContainer.innerHTML = `
        <div class="mini-calendar">
            <div class="cal-month">${month}</div>
            <div class="cal-day">${day}</div>
        </div>
    `;
}

function normalizeFolder(folder) {
    if (!folder || folder === '.') return '';
    return String(folder).replace(/^\/+/, '').replace(/\/+$/, '');
}

function buildLocalMediaUrl(folder, filename) {
    if (!settings.mediaPath) return '';
    const base = settings.mediaPath.replace(/\\/g, '/').replace(/\/+$/, '');
    const relFolder = normalizeFolder(folder);
    const suffix = filename ? `/${filename}` : '';
    const absPath = relFolder ? `${base}/${relFolder}${suffix}` : `${base}${suffix}`;
    const filePrefix = absPath.startsWith('/') ? 'file://' : 'file:///';
    return encodeURI(`${filePrefix}${absPath}`);
}

function setVideoSource(url) {
    // Limpiar instancia previa de HLS si existe
    if (hlsInstance) {
        hlsInstance.destroy();
        hlsInstance = null;
    }

    if (url && url.includes('.m3u8')) {
        if (window.Hls && Hls.isSupported()) {
            hlsInstance = new Hls();
            hlsInstance.loadSource(url);
            hlsInstance.attachMedia(mainPlayer);
        } else if (mainPlayer.canPlayType('application/vnd.apple.mpegurl')) {
            mainPlayer.src = url;
        }
    } else {
        mainPlayer.src = url;
    }
}

function setStartupVideo() {
    setVideoSource(STARTUP_VIDEO_URL);
    mainPlayer.preload = 'auto';
    mainPlayer.load();
    mainPlayer.pause();
    currentVideoTitle.textContent = 'Video de inicio';
    currentFolderName.textContent = 'Pantalla principal';
}

// State
let currentVideos = [];
let currentIndex = -1;
let videoToDelete = null;
let folderPathToDelete = null;
let cloudPlaylistToDelete = null;
let reminderToDelete = null;
let shopItemToDelete = null;
let isDeletingAllTags = false;
let playlistTimeout = null;
let isFirstPlayStarted = false;
let thumbnailQueue = []; // Cola de procesos pendientes
const thumbnailCache = new Map(); // Caché de imágenes (en memoria para velocidad)
const playbackHistory = new Map();

// ── Persistencia server-side (compartida entre instancias) ────────────────────
async function loadTags() {
    try {
        const scopePath = (settings.mediaPath || '').trim();
        if (typeof py.get_video_tags_for_path === 'function') {
            videoTags = JSON.parse(await py.get_video_tags_for_path(scopePath));
        } else {
            videoTags = JSON.parse(await py.get_video_tags());
        }

        // Compatibilidad con datos viejos: migrar claves /media/* a file://
        let changed = false;
        for (const key of Object.keys(videoTags)) {
            if (!key.startsWith('/media/')) continue;
            const rel = key.replace('/media/', '');
            const slashIndex = rel.lastIndexOf('/');
            const folder = slashIndex === -1 ? '.' : rel.slice(0, slashIndex);
            const name = slashIndex === -1 ? rel : rel.slice(slashIndex + 1);
            const migratedKey = buildLocalMediaUrl(folder, name);
            if (migratedKey && !videoTags[migratedKey]) {
                videoTags[migratedKey] = videoTags[key];
                changed = true;
            }
            delete videoTags[key];
            changed = true;
        }

        if (changed) {
            if (typeof py.save_video_tags_for_path === 'function') {
                await py.save_video_tags_for_path(scopePath, JSON.stringify(videoTags));
            } else {
                py.save_video_tags(JSON.stringify(videoTags));
            }
        }
    } catch(e) {
        videoTags = {};
    }
    renderTagsList();
}
// ─────────────────────────────────────────────────────────────────────────────

async function loadSettings() {
    try {
        const rawStartMuted = await py.get_config('videoStartMuted');
        const serverSettings = {
            mediaPath: await py.get_media_path(),
            homeUrl: await py.get_config('homeUrl'),
            sortBy: await py.get_config('videoSortBy')
        };
        if (rawStartMuted !== '') {
            serverSettings.startMuted = rawStartMuted === '1';
        }
        settings = { ...settings, ...serverSettings };
        // Migrar desde localStorage si el servidor no tiene datos aún
        if (!serverSettings.mediaPath || !serverSettings.sortBy) {
            const stored = localStorage.getItem('videoStreamSettings');
            if (stored) {
                const local = JSON.parse(stored);
                settings = { ...settings, ...local };
                // Persistir en servidor para futuras instancias
                await saveAppSettings(settings);
            }
        }
    } catch (e) {
        console.error("Error loading settings:", e);
    }
    configMediaPath.value = settings.mediaPath;
    configStartMuted.checked = settings.startMuted;
    if (configHomeUrl) {
        configHomeUrl.value = settings.homeUrl || settings.privacyUrl || '';
    }
    sortSelect.value = settings.sortBy || 'name-asc';

    await fetchFolders();
}

async function saveAppSettings(s) {
    try {
        await py.set_config('mediaPath', s.mediaPath);
        await py.set_config('homeUrl', s.homeUrl || '');
        await py.set_config('videoSortBy', s.sortBy || 'name-asc');
        await py.set_config('videoStartMuted', s.startMuted ? '1' : '0');
    } catch (err) {
        console.error('Error saving app settings:', err);
    }
}

async function savePathToServer(path) {
    try {
        await py.set_config('mediaPath', path);
        fetchFolders();
    } catch (err) {
        console.error('Error syncing path to server:', err);
    }
}

// Settings Logic
settingsBtn.addEventListener('click', () => {
    settingsModal.style.display = 'flex';
});

closeSettingsBtn.addEventListener('click', () => {
    settingsModal.style.display = 'none';
});

saveSettingsBtn.addEventListener('click', async () => {
    settings.mediaPath = configMediaPath.value;
    settings.startMuted = configStartMuted.checked;
    if (configHomeUrl) {
        settings.homeUrl = configHomeUrl.value;
    }

    await saveAppSettings(settings);
    localStorage.setItem('videoStreamSettings', JSON.stringify(settings));

    if (settings.mediaPath) {
        await savePathToServer(settings.mediaPath);
    }

    await loadTags();

    resetPlayer(); // Limpiar el reproductor al cambiar de biblioteca
    settingsModal.style.display = 'none';
    showNotification('Biblioteca reiniciada', 'info');
});

function resetPlayer() {
    mainPlayer.pause();
    setStartupVideo();
    currentIndex = -1;
    currentVideos = [];
    videoList.innerHTML = '<div class="info-text">Selecciona una carpeta para ver videos</div>';
}

// Initialize
// loadSettings se llama ahora solo en DOMContentLoaded para seguridad

/**
 * Fetch and render the list of folders in the media directory
 */
async function fetchFolders() {
    try {
        const folders = JSON.parse(await py.get_video_folders());
        if (Array.isArray(folders)) {
            renderFolders(folders);
        } else {
            console.error('Folders response is not an array:', folders);
            renderFolders([]);
        }
    } catch (err) {
        showNotification('Error al conectar con el servidor', 'error');
    }
}

// --- LÓGICA CLOUD (NUEVO) ---

async function fetchCloudPlaylists() {
    try {
        const data = JSON.parse(await py.get_playlists());
        cloudPlaylists = Array.isArray(data) ? data : [];
        renderCloudPlaylists();
    } catch (e) { console.error('Error fetching cloud playlists', e); }
}

function renderCloudPlaylists() {
    cloudPlaylistList.innerHTML = cloudPlaylists.map((list, index) => `
        <li class="cloud-playlist-item" data-index="${index}">
            <span class="playlist-name">🎬 ${list.name}</span>
            <div class="playlist-actions" style="display:flex; gap:5px;">
                <button class="btn-icon-mini edit-cloud-playlist" data-index="${index}" title="Editar">✏️</button>
                <button class="btn-icon-mini delete-cloud-playlist" data-index="${index}" title="Eliminar">🗑️</button>
            </div>
        </li>
    `).join('');

    cloudPlaylistList.querySelectorAll('.cloud-playlist-item').forEach(item => {
        const idx = parseInt(item.dataset.index);
        item.addEventListener('click', (e) => {
            if (e.target.closest('.playlist-actions')) return;
            openCloudPlaylist(idx);
        });

        item.querySelector('.edit-cloud-playlist').addEventListener('click', () => showCloudModal(idx));

        item.querySelector('.delete-cloud-playlist').addEventListener('click', (e) => {
            e.stopPropagation();
            deleteCloudPlaylist(idx);
        });
    });
}

function openCloudPlaylist(index, autoPlay = true) {
    // Normalizar items: si la URL es un video/stream directo, usar el visor nativo
    const directVideoRe = /\.(mp4|mkv|avi|mov|webm|m3u8|ts|wmv|flv|ogv)$/i;
    currentVideos = cloudPlaylists[index].items.map(item => {
        const isDirectVideo = item.url && (
            directVideoRe.test(item.url) ||
            item.url.startsWith('http://localhost') ||
            item.url.includes('/api/')
        );
        if (isDirectVideo && (item.type === 'embed' || item.type === 'youtube')) {
            const copy = { ...item };
            delete copy.type;
            return copy;
        }
        return item;
    });
    const listName = cloudPlaylists[index].name;
    currentFolderName.textContent = `☁️ ${listName}`;
    renderVideos(currentVideos);
    showNotification(`Lista Cloud "${listName}" cargada`, 'success');
    if (autoPlay && currentVideos.length > 0) playVideo(0);
}

// Asegurar que Ctrl+V (Paste) y Enter funcionen en campos de texto clave
[
    cloudPlaylistNameInput,
    cloudUrlInput,
    document.getElementById('new-tag-input')
].forEach(input => {
    if (input) {
        input.addEventListener('paste', (e) => {
            e.stopPropagation();
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                if (input.id === 'cloud-url-input') {
                    e.preventDefault();
                    addToCloudBtn.click();
                } else if (input.id === 'new-tag-input') {
                    e.preventDefault();
                    const addTagBtn = document.getElementById('add-tag-btn');
                    if (addTagBtn) addTagBtn.click();
                }
            }
        });
    }
});

function showCloudModal(index = -1) {
    activeCloudPlaylistIndex = index;
    const list = index === -1 ? { name: '', items: [] } : cloudPlaylists[index];
    document.getElementById('cloud-modal-title').textContent = index === -1 ? 'Crear Lista Cloud' : `Gestionar: ${list.name}`;
    cloudPlaylistNameInput.value = list.name;
    renderCloudItems(list.items);
    cloudModal.classList.add('active');
}

function renderCloudItems(items) {
    cloudItemsList.innerHTML = items.map((item, idx) => `
        <div class="sortable-item" data-index="${idx}" draggable="true">
            <span class="item-title">☰ ${item.name}</span>
            <div class="item-actions">
                <button class="btn-icon-mini remove-item">❌</button>
            </div>
        </div>
    `).join('');

    let draggedItemIndex = null;

    cloudItemsList.querySelectorAll('.sortable-item').forEach(item => {
        item.addEventListener('dragstart', (e) => {
            draggedItemIndex = parseInt(item.dataset.index);
            e.dataTransfer.effectAllowed = 'move';
            item.style.opacity = '0.5';
        });

        item.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        });

        item.addEventListener('drop', (e) => {
            e.preventDefault();
            const targetIndex = parseInt(item.dataset.index);
            if (draggedItemIndex !== null && draggedItemIndex !== targetIndex) {
                // Reordenar array
                const movedItem = items.splice(draggedItemIndex, 1)[0];
                items.splice(targetIndex, 0, movedItem);
                renderCloudItems(items);
                // Refrescar vista principal si es la activa
                if (activeCloudPlaylistIndex !== -1 && currentFolderName.textContent.includes(cloudPlaylists[activeCloudPlaylistIndex].name)) {
                    renderVideos(items);
                }
            }
        });

        item.addEventListener('dragend', () => {
            item.style.opacity = '1';
            draggedItemIndex = null;
        });

        item.querySelector('.remove-item').onclick = () => {
            items.splice(parseInt(item.dataset.index), 1);
            renderCloudItems(items);
            // Refrescar vista principal si es la activa
            if (activeCloudPlaylistIndex !== -1 && currentFolderName.textContent.includes(cloudPlaylists[activeCloudPlaylistIndex].name)) {
                renderVideos(items);
            }
        };
    });
}

async function resolveAndAddUrl() {
    const url = cloudUrlInput.value.trim();
    if (!url) return;

    const originalContent = addToCloudBtn.innerHTML;
    addToCloudBtn.disabled = true;
    addToCloudBtn.innerHTML = '<div class="spinner"></div>';

    // showNotification('Analizando fuente... (puede tardar unos segundos)', 'info');
    try {
        const dataStr = await py.resolve_video_url(url);
        const data = JSON.parse(dataStr);

        if (data.error) throw new Error(data.error);

        const currentList = activeCloudPlaylistIndex === -1 ? { name: 'Nueva Lista', items: [] } : cloudPlaylists[activeCloudPlaylistIndex];

        let item;
        if (data.type === 'youtube-direct') {
            item = {
                name: data.name,
                url: data.videoUrl,      // URL proxy para el video
                audioUrl: data.audioUrl, // URL proxy para el audio (si es separado)
                type: 'youtube-direct'
            };
        } else if (data.type === 'youtube') {
            item = {
                name: data.name,
                url: data.embedUrl,
                type: 'youtube'
            };
        } else {
            item = {
                name: data.name,
                url: data.url,
                type: data.type
            };
        }

        currentList.items.push(item);

        if (activeCloudPlaylistIndex === -1) {
            cloudPlaylists.push(currentList);
            activeCloudPlaylistIndex = cloudPlaylists.length - 1;
        }

        cloudUrlInput.value = '';
        renderCloudItems(currentList.items);

        // Si esta es la lista que se está visualizando actualmente en el reproductor, refrescarla
        if (currentFolderName.textContent.includes(currentList.name)) {
            currentVideos = currentList.items;
            renderVideos(currentVideos);
        }

        // showNotification(`Video añadido: ${item.name}`, 'success', true);
    } catch (e) {
        showNotification(e.message || 'Error al analizar URL', 'error');
    } finally {
        addToCloudBtn.disabled = false;
        addToCloudBtn.innerHTML = originalContent;
    }
}

async function saveCloudPlaylistsToServer() {
    const listName = cloudPlaylistNameInput.value.trim() || 'Lista sin nombre';

    if (activeCloudPlaylistIndex === -1) {
        // En teoría no debería pasar si resolveAndAddUrl ya la creó,
        // pero por si acaso si el usuario solo le da a crear lista vacía:
        cloudPlaylists.push({ name: listName, items: [] });
    } else {
        cloudPlaylists[activeCloudPlaylistIndex].name = listName;
    }

    try {
        await py.set_playlists(JSON.stringify(cloudPlaylists));
        // Notificación sticky para guardado
        // showNotification('Listas actualizadas y guardadas correctamente', 'success', true);
        renderCloudPlaylists();
        cloudModal.classList.remove('active');
    } catch (e) {
        showNotification('Error al guardar en el servidor', 'error');
    }
}

function deleteCloudPlaylist(index) {
    cloudPlaylistToDelete = index;
    videoToDelete = null;
    folderPathToDelete = null;
    const modalTitle = deleteModal.querySelector('h3');
    const modalText = deleteModal.querySelector('p');
    modalTitle.textContent = '¿Eliminar Lista Cloud?';
    modalText.innerHTML = `Estás a punto de eliminar la lista <strong>"${cloudPlaylists[index].name}"</strong>.<br>Esta acción no se puede deshacer.`;
    deleteModal.classList.add('active');
}

/**
 * Render folder tree into the sidebar (recursive)
 */
function renderFolders(nodes, container = folderList) {
    if (container === folderList) container.innerHTML = '';

    if (nodes.length === 0 && container === folderList) {
        container.innerHTML = '<li class="info-text">No se encontraron carpetas</li>';
        return;
    }

    nodes.forEach(node => {
        const li = document.createElement('li');
        const hasChildren = node.children && node.children.length > 0;

        li.innerHTML = `
            <div class="folder-item" data-path="${node.path}">
                <div class="folder-header">
                    <span class="toggle-icon">${hasChildren ? '▶' : ''}</span>
                    <span class="icon">📁</span>
                    <span class="name">${node.name}</span>
                </div>
                <div class="folder-actions">
                    <button class="add-subfolder-btn" title="Nueva Subcarpeta">➕</button>
                    <button class="delete-folder-btn" title="Eliminar Carpeta">🗑️</button>
                </div>
            </div>
            ${hasChildren ? '<ul class="sub-folders"></ul>' : ''}
        `;

        container.appendChild(li);

        const item = li.querySelector('.folder-item');
        const header = li.querySelector('.folder-header');
        const toggle = li.querySelector('.toggle-icon');
        const subList = li.querySelector('.sub-folders');
        const addSubBtn = li.querySelector('.add-subfolder-btn');
        const delBtn = li.querySelector('.delete-folder-btn');
        const nameSpan = li.querySelector('.name');

        header.addEventListener('click', (e) => {
            e.stopPropagation();
            selectFolder(node.path, item);
            if (hasChildren) {
                subList.classList.toggle('active');
                toggle.classList.toggle('expanded');
            }
        });

        // Renombrar carpeta
        nameSpan.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            enableFolderRename(nameSpan, node.path);
        });

        // Botón de Añadir Subcarpeta
        addSubBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            handleCreateFolder(node.path);
        });

        delBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openFolderDeleteModal(node.path, node.name);
        });

        if (hasChildren) {
            renderFolders(node.children, subList);
        }

        // Configurar Zona de Drop
        item.addEventListener('dragover', (e) => {
            e.preventDefault(); // Necesario para permitir el drop
            item.classList.add('drag-over');
        });

        item.addEventListener('dragleave', () => {
            item.classList.remove('drag-over');
        });

        item.addEventListener('drop', async (e) => {
            e.preventDefault();
            item.classList.remove('drag-over');

            try {
                const data = JSON.parse(e.dataTransfer.getData('text/plain'));
                const toFolder = node.path;

                if (data.fromFolder === toFolder) {
                    showNotification('El video ya está en esta carpeta', 'info');
                    return;
                }

                await moveVideo(data.filename, data.fromFolder, toFolder);
            } catch (err) {
                console.error('Error al procesar el drop:', err);
            }
        });
    });
}

async function moveVideo(filename, fromFolder, toFolder) {
    // Guardar estado antes de mover
    const indexMoved = currentVideos.findIndex(v => v.name === filename);
    const isPlayingMoved = (indexMoved !== -1 && indexMoved === currentIndex);
    const nextVideo = (isPlayingMoved && indexMoved + 1 < currentVideos.length) ? currentVideos[indexMoved + 1] : null;
    const currentPlaying = (!isPlayingMoved && currentIndex !== -1) ? currentVideos[currentIndex] : null;

    try {
        const success = await py.move_video(filename, fromFolder, toFolder);
        const data = { success };
        if (data.success) {
            // El backend ya migró las etiquetas en SQLite; recargar para sincronizar el objeto JS
            try {
                await loadTags();
            } catch (tagErr) {
                console.warn('[TAGS] Error al recargar etiquetas tras mover:', tagErr);
            }

            const activeFolderItem = document.querySelector('.folder-item.active');
            if (activeFolderItem) {
                await selectFolder(fromFolder, activeFolderItem, false);

                // Restaurar estado de reproducción
                if (isPlayingMoved) {
                    if (nextVideo) {
                        const newIndex = currentVideos.findIndex(v => v.name === nextVideo.name);
                        if (newIndex !== -1) playVideo(newIndex);
                    } else {
                        mainPlayer.pause();
                        mainPlayer.src = '';
                        externalPlayer.src = '';
                        externalPlayer.style.display = 'none';
                        currentVideoTitle.textContent = 'Ningún video seleccionado';
                    }
                } else if (currentPlaying) {
                    currentIndex = currentVideos.findIndex(v => v.name === currentPlaying.name);
                    updateActiveState(currentIndex);
                }
            }
        } else {
            showNotification(data.error || 'Error al mover el archivo', 'error');
        }
    } catch (e) {
        showNotification('Error de conexión al mover archivo', 'error');
    }
}

/**
 * Handle folder selection
 */
async function selectFolder(path, element, autoPlay = true) {
    document.querySelectorAll('.folder-item').forEach(el => el.classList.remove('active'));
    element.classList.add('active');
    currentFolderName.textContent = path;
    videoList.innerHTML = '';

    try {
        currentVideos = JSON.parse(await py.get_videos(path));
        currentIndex = -1; // Reset index when folder changes

        // Aplicar el orden guardado antes de renderizar
        sortVideos(settings.sortBy, false);

        if (autoPlay && currentVideos.length > 0) playVideo(0);

        showNotification(`Ruta "${path}" cargada`, 'success');

        // Show playlist on load and hide after 3 seconds
        showPlaylistTemporarily();
    } catch (err) {
        showNotification('Error al cargar los videos', 'error');
    }
}

function startPlaylistAutoClose() {
    clearTimeout(playlistTimeout);
    playlistTimeout = setTimeout(() => {
        playlistSidebar.classList.remove('active');
    }, 3000);
}

function cancelPlaylistAutoClose() {
    clearTimeout(playlistTimeout);
    playlistTimeout = null;
}

// Mostrar playlist brevemente al cargar y cerrar en 3 segundos
function showPlaylistTemporarily() {
    playlistSidebar.classList.add('active');
    startPlaylistAutoClose();
}

/**
 * Render video items into the grid with dynamic thumbnails
 */
function renderVideos(videos) {
    const playlistCount = document.getElementById('playlist-count');
    if (playlistCount) playlistCount.textContent = videos.length;

    if (videos.length === 0) {
        videoList.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">🎞️</span>
                <p>Esta carpeta está vacía</p>
                <small>No se encontraron videos compatibles</small>
            </div>
        `;
        return;
    }

    videoList.innerHTML = videos.map((video, index) => {
        const cachedThumb = thumbnailCache.get(video.url);
        const thumbContent = cachedThumb ? `<img src="${cachedThumb}" class="real-thumb">` : '🎬';
        const videoId = video.url || video.name;
        const hasTags = videoTags[videoId] && videoTags[videoId].tags.length > 0;
        const tagChips = hasTags
            ? `<div class="video-tag-chips">${videoTags[videoId].tags.map(t => `<span class="video-tag-chip">${t}</span>`).join('')}</div>`
            : '';

        // Determinar si este video es el que está sonando actualmente
        const isActive = index === currentIndex;

        // Mostrar tamaño debajo del nombre
        let sizeInfo = '';
        if (typeof video.size === 'number' && !isNaN(video.size)) {
            let sizeStr = '';
            if (video.size >= 1024 * 1024 * 1024) {
                sizeStr = (video.size / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
            } else if (video.size >= 1024 * 1024) {
                sizeStr = (video.size / (1024 * 1024)).toFixed(2) + ' MB';
            } else if (video.size >= 1024) {
                sizeStr = (video.size / 1024).toFixed(2) + ' KB';
            } else {
                sizeStr = video.size + ' B';
            }
            sizeInfo = `<div class="video-size" style="font-size:0.85em; color:var(--text-secondary); margin-top:2px;">${sizeStr}</div>`;
        }

        return `
            <div class="video-card ${isActive ? 'active' : ''}" data-index="${index}" draggable="true">
                <div class="video-thumbnail-container">
                    <div class="video-thumbnail" id="thumb-${index}">${thumbContent}</div>
                </div>
                <div class="video-details">
                    <span class="video-name" title="Doble clic para renombrar">${video.name}</span>
                    ${sizeInfo}
                    ${tagChips}
                    ${video.type ? `<span class="badge cloud-badge" style="background: var(--accent); color: white; font-size: 0.65rem; padding: 2px 6px; border-radius: 4px; margin-top: 4px; display: inline-block; width: fit-content;">☁️ ${video.type.toUpperCase()}</span>` : ''}
                </div>
                <button class="tag-btn ${hasTags ? 'active' : ''}" data-index="${index}" title="Etiquetas">🏷️</button>
                <button class="delete-btn" data-index="${index}">🗑️</button>
            </div>
        `;
    }).join('');

    // Solo iniciamos miniaturas si ya cargó el primer video principal
    if (isFirstPlayStarted) {
        startThumbnailQueue(videos);
    }

    document.querySelectorAll('.video-card').forEach(card => {
        card.addEventListener('dragstart', (e) => {
            const index = card.dataset.index;
            const video = currentVideos[index];

            // Si estamos en vista de etiqueta, obtener la carpeta real del video
            const folderName = currentFolderName.textContent;
            const isTagView = folderName.startsWith('🏷️');
            let realFolder = folderName;
            if (isTagView) {
                const videoId = video.url || video.name;
                realFolder = (videoTags[videoId] && videoTags[videoId].lastKnownFolder) || '';
            }

            e.dataTransfer.setData('text/plain', JSON.stringify({
                filename: video.name,
                fromFolder: realFolder
            }));

            card.classList.add('dragging');
            // Hacer que la imagen de arrastre sea pequeña
            const ghost = card.cloneNode(true);
            ghost.style.width = '200px';
            ghost.style.position = 'absolute';
            ghost.style.top = '-1000px';
            document.body.appendChild(ghost);
            e.dataTransfer.setDragImage(ghost, 10, 10);
            setTimeout(() => ghost.remove(), 0);
        });

        card.addEventListener('dragend', () => {
            card.classList.remove('dragging');
        });

        card.addEventListener('click', (e) => {
            if (e.target.closest('.delete-btn') || e.target.closest('.rename-input') || e.target.closest('.tag-btn')) return;
            playVideo(parseInt(card.dataset.index));
        });
    });

    document.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            openDeleteModal(parseInt(btn.dataset.index));
        });
    });

    document.querySelectorAll('.tag-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const video = currentVideos[parseInt(btn.dataset.index)];
            openTagsModal(video, currentFolderName.textContent);
        });
    });

    // Nueva funcionalidad: Renombrar con Doble Clic
    document.querySelectorAll('.video-name').forEach(nameSpan => {
        nameSpan.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            const index = parseInt(nameSpan.closest('.video-card').dataset.index);
            enableRename(nameSpan, index);
        });
    });
}

function enableRename(span, index) {
    const originalName = span.textContent;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'rename-input';
    input.value = originalName;

    span.parentNode.replaceChild(input, span);
    input.focus();
    input.select();

    let isDone = false;
    const finishRename = async () => {
        if (isDone) return;
        isDone = true;

        const newName = input.value.trim();
        if (newName && newName !== originalName) {
            const success = await renameVideoAsync(originalName, newName);
            if (success) {
                // Migrar caché de miniatura para evitar re-procesamiento
                const folder = currentFolderName.textContent;
                const oldUrl = buildLocalMediaUrl(folder, originalName);
                const newUrl = buildLocalMediaUrl(folder, newName);

                if (thumbnailCache.has(oldUrl)) {
                    const thumbData = thumbnailCache.get(oldUrl);
                    thumbnailCache.set(newUrl, thumbData);
                    thumbnailCache.delete(oldUrl);
                }

                // Refrescar carpeta actual
                const activeItem = document.querySelector('.folder-item.active');
                if (activeItem) {
                    selectFolder(folder, activeItem);
                }
            } else {
                if (input.parentNode) input.parentNode.replaceChild(span, input);
            }
        } else {
            if (input.parentNode) input.parentNode.replaceChild(span, input);
        }
    };

    input.addEventListener('blur', finishRename);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); finishRename(); }
        if (e.key === 'Escape') { isDone = true; if (input.parentNode) input.parentNode.replaceChild(span, input); }
    });
}

async function renameVideoAsync(oldName, newName) {
    const folder = currentFolderName.textContent;
    const oldUrl = buildLocalMediaUrl(folder, oldName);
    const newUrl = buildLocalMediaUrl(folder, newName);

    try {
        const success = await py.rename_video(`${folder}/${oldName}`, newName);
                const data = { success };
        if (data.success) {
            // Sincronizar Caché de Miniaturas
            if (thumbnailCache.has(oldUrl)) {
                const thumbData = thumbnailCache.get(oldUrl);
                thumbnailCache.set(newUrl, thumbData);
                thumbnailCache.delete(oldUrl);
                await DbManager.migrate('thumbnails', oldUrl, newUrl);
            }

            // Sincronizar Historial de Reproducción
            if (playbackHistory.has(oldUrl)) {
                const time = playbackHistory.get(oldUrl);
                playbackHistory.set(newUrl, time);
                playbackHistory.delete(oldUrl);
                // Playback migration can be done in python, or simply skipped for tags sync
            }

            // showNotification(`Renombrado a "${newName}"`, 'success', true);
            return true;
        } else {
            showNotification(data.error || 'Error al renombrar', 'error');
            return false;
        }
    } catch (e) {
        showNotification('Error de conexión', 'error');
        return false;
    }
}

// Función para capturar un frame del video (segundo 15)
async function captureThumbnail(url, index) {
    // 1. Intentar cargar desde memoria
    if (thumbnailCache.has(url)) return Promise.resolve();

    // 2. Intentar cargar desde IndexedDB
    const persistentThumb = await DbManager.get('thumbnails', url);
    if (persistentThumb) {
        thumbnailCache.set(url, persistentThumb.dataUrl);
        updateThumbUI(index, persistentThumb.dataUrl);
        return Promise.resolve();
    }

    const thumbDiv = document.getElementById(`thumb-${index}`);
    if (!thumbDiv) return Promise.resolve();

    return new Promise((resolve) => {
        try {
            const video = document.createElement('video');
            video.src = url + "#t=15";
            video.crossOrigin = "anonymous";
            video.muted = true;

            video.addEventListener('loadeddata', () => {
                setTimeout(() => {
                    const canvas = document.createElement('canvas');
                    canvas.width = 160;
                    canvas.height = 90;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                    const dataUrl = canvas.toDataURL('image/jpeg', 0.5);

                    thumbnailCache.set(url, dataUrl);
                    DbManager.put('thumbnails', { url, dataUrl }); // Persistir imagen
                    updateThumbUI(index, dataUrl);
                    video.remove();
                    resolve();
                }, 500);
            });

            video.onerror = () => {
                video.remove();
                resolve();
            };
            video.load();
        } catch (e) {
            console.warn(e);
            resolve();
        }
    });
}

let activeQueueTimeout = null;
let queueIndex = 0;

function startThumbnailQueue(videos) {
    if (!videos || videos.length === 0) return;

    stopThumbnailQueue();
    queueIndex = 0;

    // Iniciamos la cadena de generación pausada
    activeQueueTimeout = setTimeout(() => {
        processNextInQueue(videos);
    }, 5000); // 5 segundos iniciales de calma absoluta
}

async function processNextInQueue(videos) {
    if (queueIndex >= videos.length) return;

    // Mientras encontremos videos en CACHÉ, los actualizamos rápido y pasamos al siguiente
    while(queueIndex < videos.length && thumbnailCache.has(videos[queueIndex].url)) {
        const dataUrl = thumbnailCache.get(videos[queueIndex].url);
        updateThumbUI(queueIndex, dataUrl);
        queueIndex++;
    }

    // Si ya terminamos todos (porque estaban en caché), salimos
    if (queueIndex >= videos.length) return;

    // Si llegamos aquí, es que el videos[queueIndex] NO está en caché y necesita captura real
    await captureThumbnail(videos[queueIndex].url, queueIndex);
    queueIndex++;

    // DESCANSO: Solo esperamos si tuvimos que hacer una captura pesada
    activeQueueTimeout = setTimeout(() => {
        processNextInQueue(videos);
    }, 3000);
}

function updateThumbUI(index, dataUrl) {
    const thumbDiv = document.getElementById(`thumb-${index}`);
    if (thumbDiv) thumbDiv.innerHTML = `<img src="${dataUrl}" class="real-thumb">`;
}

function stopThumbnailQueue() {
    if (activeQueueTimeout) clearTimeout(activeQueueTimeout);
    queueIndex = 999999; // Detiene cualquier proceso recursivo en marcha
}

// Lógica de Ordenamiento
sortSelect.addEventListener('change', () => {
    sortVideos(sortSelect.value);
});

function sortVideos(criteria, notify = true) {
    if (currentVideos.length === 0) return;

    // Guardar preferencia
    settings.sortBy = criteria;
    localStorage.setItem('videoStreamSettings', JSON.stringify(settings));
    saveAppSettings(settings);

    currentVideos.sort((a, b) => {
        switch(criteria) {
            case 'name-asc': return a.name.localeCompare(b.name);
            case 'name-desc': return b.name.localeCompare(a.name);
            case 'date-desc': return new Date(b.mtime) - new Date(a.mtime);
            case 'date-asc': return new Date(a.mtime) - new Date(b.mtime);
            case 'size-desc': return b.size - a.size;
            case 'size-asc': return a.size - b.size;
            default: return a.name.localeCompare(b.name);
        }
    });

    renderVideos(currentVideos);
    // Traducir criterio para la notificación
    const map = {
        'name-asc': 'Nombre (A-Z)', 'name-desc': 'Nombre (Z-A)',
        'date-desc': 'Más recientes', 'date-asc': 'Más antiguos',
        'size-desc': 'Más pesados', 'size-asc': 'Más ligeros'
    };
    // if (notify) showNotification(`Ordenado por ${map[criteria] || criteria}`, 'info');
}

function openDeleteModal(index) {
    videoToDelete = index;
    folderPathToDelete = null;
    const video = currentVideos[index];
    const modalTitle = deleteModal.querySelector('h3');
    const modalText = deleteModal.querySelector('p');
    modalTitle.textContent = '¿Eliminar Video?';
    modalText.innerHTML = `Estás a punto de eliminar <strong>"${video.name}"</strong>.<br>Esta acción no se puede deshacer.`;
    deleteModal.classList.add('active');
}

function openFolderDeleteModal(path, name) {
    folderPathToDelete = path;
    videoToDelete = null;
    const modalTitle = deleteModal.querySelector('h3');
    const modalText = deleteModal.querySelector('p');
    modalTitle.textContent = '¿Eliminar Carpeta?';
    modalText.innerHTML = `Estás a punto de eliminar la carpeta <strong>"${name}"</strong>.<br><br><span style="color:#ff4757">⚠️ ADVERTENCIA: Se eliminarán todos los videos y subcarpetas.</span>`;
    deleteModal.classList.add('active');
}

function closeDeleteModal() {
    deleteModal.classList.remove('active');
    videoToDelete = null;
    folderPathToDelete = null;
    cloudPlaylistToDelete = null;
    reminderToDelete = null;
    shopItemToDelete = null;
    isDeletingAllTags = false;
}

cancelDeleteBtn.addEventListener('click', closeDeleteModal);

confirmDeleteBtn.addEventListener('click', async () => {
    if (videoToDelete !== null) {
        await deleteVideo();
    } else if (folderPathToDelete !== null) {
        await deleteFolderAsync();
    } else if (reminderToDelete !== null) {
        await deleteReminderConfirmed();
    } else if (shopItemToDelete !== null) {
        await deleteShopItemConfirmed();
    } else if (isDeletingAllTags) {
        await clearAllTagsConfirmed();
    } else if (cloudPlaylistToDelete !== null) {
        cloudPlaylists.splice(cloudPlaylistToDelete, 1);
        try {
            await py.set_playlists(JSON.stringify(cloudPlaylists));
            // showNotification('Lista Cloud eliminada', 'success');
            renderCloudPlaylists();
        } catch (e) {
            showNotification('Error al eliminar lista', 'error');
        }
        closeDeleteModal();
    }
});

async function deleteVideo() {
    const video = currentVideos[videoToDelete];
    const folderRaw = currentFolderName.textContent;

    // En vista de etiqueta, obtener la carpeta real del videoTags
    const isTagView = folderRaw.startsWith('🏷️');
    const videoId = video.url || video.name;
    const folder = isTagView
        ? ((videoTags[videoId] && videoTags[videoId].lastKnownFolder) || '')
        : folderRaw;

    // Guardar estado antes de eliminar
    const isPlayingDeleted = (videoToDelete === currentIndex);
    const nextVideo = (isPlayingDeleted && videoToDelete + 1 < currentVideos.length) ? currentVideos[videoToDelete + 1] : null;
    const currentPlaying = (!isPlayingDeleted && currentIndex !== -1) ? currentVideos[currentIndex] : null;

    if (folder.startsWith('☁️ ')) {
        const cloudName = folder.replace('☁️ ', '').trim();
        const playlistIndex = cloudPlaylists.findIndex(p => p.name === cloudName);

        if (playlistIndex !== -1) {
            cloudPlaylists[playlistIndex].items.splice(videoToDelete, 1);
            try {
                await py.set_playlists(JSON.stringify(cloudPlaylists));
                // showNotification(`Enlace "${video.name}" eliminado`, 'success');
                openCloudPlaylist(playlistIndex, false); // Refrescar la vista sin auto-reproducir el 1ro

                // Restaurar estado de reproducción
                if (isPlayingDeleted) {
                    if (nextVideo) {
                        const newIndex = currentVideos.findIndex(v => v.url === nextVideo.url);
                        if (newIndex !== -1) playVideo(newIndex);
                    } else {
                        mainPlayer.pause();
                        mainPlayer.src = '';
                        externalPlayer.src = '';
                        externalPlayer.style.display = 'none';
                        currentVideoTitle.textContent = 'Ningún video seleccionado';
                    }
                } else if (currentPlaying) {
                    currentIndex = currentVideos.findIndex(v => v.url === currentPlaying.url);
                    updateActiveState(currentIndex);
                }
            } catch (err) {
                showNotification('Error al actualizar lista', 'error');
            }
        }
        closeDeleteModal();
        return;
    }

    try {
        const relPath = folder === '.' || !folder ? video.name : `${folder}/${video.name}`;
        const success = await py.delete_video(relPath);

        if (success) {
            // Limpiar etiquetas del video eliminado
            if (videoTags[videoId]) {
                delete videoTags[videoId];
                saveTags();
            }

            if (isTagView) {
                // En vista de etiqueta: quitar de la lista en memoria y re-renderizar
                currentVideos.splice(videoToDelete, 1);
                renderVideos(currentVideos);
                if (isPlayingDeleted) {
                    if (currentVideos.length > 0) {
                        const nextIdx = Math.min(videoToDelete, currentVideos.length - 1);
                        playVideo(nextIdx);
                    } else {
                        mainPlayer.pause();
                        mainPlayer.src = '';
                        externalPlayer.src = '';
                        externalPlayer.style.display = 'none';
                        currentVideoTitle.textContent = 'Ningún video seleccionado';
                    }
                } else if (currentPlaying) {
                    currentIndex = currentVideos.findIndex(v => (v.url || v.name) === (currentPlaying.url || currentPlaying.name));
                    updateActiveState(currentIndex);
                }
            } else {
                // En vista de carpeta: recargar la carpeta
                const activeItem = document.querySelector('.folder-item.active');
                if (activeItem) {
                    await selectFolder(folder, activeItem, false);

                    if (isPlayingDeleted) {
                        if (nextVideo) {
                            const newIndex = currentVideos.findIndex(v => v.name === nextVideo.name);
                            if (newIndex !== -1) playVideo(newIndex);
                        } else {
                            mainPlayer.pause();
                            mainPlayer.src = '';
                            externalPlayer.src = '';
                            externalPlayer.style.display = 'none';
                            currentVideoTitle.textContent = 'Ningún video seleccionado';
                        }
                    } else if (currentPlaying) {
                        currentIndex = currentVideos.findIndex(v => v.name === currentPlaying.name);
                        updateActiveState(currentIndex);
                    }
                }
            }
        } else {
            showNotification('Error al eliminar el archivo', 'error');
        }
    } catch (err) {
        showNotification('Error de conexión con el servidor', 'error');
    } finally {
        closeDeleteModal();
    }
}

async function deleteFolderAsync() {
    if (!folderPathToDelete) return;

    try {
        const success = await py.delete_folder(folderPathToDelete);
        if (success) {
            // showNotification('Carpeta eliminada', 'success');

            // Si era la carpeta activa, limpiar visor
            if (currentFolderName.textContent === folderPathToDelete) {
                currentVideos = [];
                renderVideos([]);
                mainPlayer.pause();
                mainPlayer.src = '';
                currentVideoTitle.textContent = 'Ningún video seleccionado';
            }

            fetchFolders();
        } else {
            showNotification('Error al eliminar', 'error');
        }
    } catch (e) {
        showNotification('Error de conexión', 'error');
    } finally {
        closeDeleteModal();
    }
}

async function deleteReminderConfirmed() {
    try {
        
        
        // showNotification('Recordatorio eliminado', 'info');
    } catch (e) {
        showNotification('Error al eliminar recordatorio', 'error');
    } finally {
        closeDeleteModal();
    }
}

async function deleteShopItemConfirmed() {
    try {
        
        
        // showNotification('Registro eliminado', 'info');
    } catch (e) {
        showNotification('Error al eliminar registro', 'error');
    } finally {
        closeDeleteModal();
    }
}

async function clearAllTagsConfirmed() {
    try {
        const scopePath = (settings.mediaPath || '').trim();

        if (typeof py.clear_video_tags_for_path === 'function') {
            await py.clear_video_tags_for_path(scopePath);
            await loadTags();
        } else {
            // Fallback para versiones antiguas del bridge.
            videoTags = {};
            saveTags();
        }

        renderTagsList();
        updateVideoQuickActions();
        updatePlayerTagChips();
    } catch (e) {
        showNotification('Error al borrar etiquetas de la biblioteca actual', 'error');
    } finally {
        closeDeleteModal();
    }
}


/**
 * Play a specific video by index
 */
function updateVideoQuickActions() {
    const overlay = document.getElementById('video-quick-actions');
    if (!overlay) return;

    if (currentIndex === -1 || !currentVideos[currentIndex]) {
        overlay.style.display = 'none';
        return;
    }

    const video  = currentVideos[currentIndex];
    const folder = currentFolderName.textContent;
    const videoId = video.url || video.name;
    const hasTags = videoTags[videoId] && videoTags[videoId].tags.length > 0;

    overlay.style.display = 'flex';

    const tagBtn = document.getElementById('vqa-tag');
    const delBtn = document.getElementById('vqa-delete');

    tagBtn.classList.toggle('active', hasTags);

    // Reemplazar listeners sin acumulación
    const newTag = tagBtn.cloneNode(true);
    const newDel = delBtn.cloneNode(true);

    newTag.addEventListener('click', (e) => { e.stopPropagation(); openTagsModal(video, folder); });
    newDel.addEventListener('click', (e) => { e.stopPropagation(); openDeleteModal(currentIndex); });

    tagBtn.replaceWith(newTag);
    delBtn.replaceWith(newDel);
}

function playVideo(index) {
    if (index < 0 || index >= currentVideos.length) return;

    const playerLoader = document.getElementById('player-loader');
    if (playerLoader) playerLoader.style.display = 'flex';

    const previousIndex = currentIndex;
    const previousVideo = (previousIndex >= 0 && previousIndex < currentVideos.length)
        ? currentVideos[previousIndex]
        : null;

    currentIndex = index;
    updateActiveState(index);

    setTimeout(async () => {
        // Guardar progreso del video anterior si era nativo
        if (previousVideo && !mainPlayer.paused && !previousVideo.type) {
            const time = mainPlayer.currentTime;
            playbackHistory.set(previousVideo.url, time);
            py.save_playback(previousVideo.url, time.toString());
        }

        const video = currentVideos[index];

        // Función interna para iniciar la reproducción y configurar UI
        const startPlayback = () => {
            mainPlayer.play().then(() => {
                isFirstPlayStarted = true;
                startThumbnailQueue(currentVideos);

                const savedTime = playbackHistory.get(video.url) || 0;
                if (savedTime > 0) {
                    mainPlayer.currentTime = savedTime;
                    // showNotification(`Continuando desde ${formatTime(savedTime)}`, 'info');
                } else if (!video.url.includes('.m3u8')) {
                    mainPlayer.currentTime = 5;
                }
                mainPlayer.classList.remove('player-fading');
            }).catch(e => {
                if (e.name !== 'NotAllowedError') {
                    console.error('Error playing video:', e);
                    showNotification('Error al reproducir el video', 'error');
                    mainPlayer.pause();
                }
                mainPlayer.classList.remove('player-fading');
            });
        };

        // --- LÓGICA DE REPRODUCTORES ---
        if (video.type === 'youtube' || video.type === 'embed') {
            mainPlayer.style.display = 'none';
            mainPlayer.pause();
            externalPlayer.src = video.url;
            externalPlayer.style.display = 'block';
            externalPlayer.classList.remove('player-fading');
            currentVideoTitle.textContent = formatVideoTitleWithSize(video);
            updatePlayerTagChips(video);
        } else {
            // Reproductor Nativo (Local o Direct Stream)
            externalPlayer.style.display = 'none';
            externalPlayer.src = '';
            mainPlayer.style.display = 'block';
            mainPlayer.muted = settings.startMuted;
            currentVideoTitle.textContent = formatVideoTitleWithSize(video);
            updatePlayerTagChips(video);

            setVideoSource(video.url);

            // Subtítulos
            const tracks = mainPlayer.querySelectorAll('track');
            tracks.forEach(t => t.remove());
            if (video.subtitle) {
                const track = document.createElement('track');
                track.kind = 'subtitles';
                track.label = 'Español';
                track.srclang = 'es';
                track.src = video.subtitle;
                track.default = true;
                mainPlayer.appendChild(track);
            }

            stopThumbnailQueue();

            // Si usamos HLS, esperamos al evento; si no, directo
            if (hlsInstance) {
                hlsInstance.once(Hls.Events.MANIFEST_PARSED, () => startPlayback());
            } else {
                startPlayback();
            }
        }
// Formatea el nombre del video con el tamaño legible si está disponible
function formatVideoTitleWithSize(video) {
    let name = video.name || '';
    if (typeof video.size === 'number' && !isNaN(video.size)) {
        let size = video.size;
        let sizeStr = '';
        if (size >= 1024 * 1024 * 1024) {
            sizeStr = (size / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
        } else if (size >= 1024 * 1024) {
            sizeStr = (size / (1024 * 1024)).toFixed(2) + ' MB';
        } else if (size >= 1024) {
            sizeStr = (size / 1024).toFixed(2) + ' KB';
        } else {
            sizeStr = size + ' B';
        }
        return `${name} (${sizeStr})`;
    }
    return name;
}

        // showNotification(`Reproduciendo: ${video.name}`, 'info');
        if (playerLoader) playerLoader.style.display = 'none';

        videoInfo.classList.add('active');
        setTimeout(() => videoInfo.classList.remove('active'), 3000);

        updateVideoQuickActions();
    }, 500);
}



function updateActiveState(index) {
    document.querySelectorAll('.video-card').forEach((el, i) => {
        el.classList.toggle('active', i === index);
    });

    const activeCard = document.querySelector('.video-card.active');
    if (activeCard) {
        activeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

function formatTime(seconds) {
    const min = Math.floor(seconds / 60);
    const sec = Math.floor(seconds % 60);
    return `${min}:${sec < 10 ? '0' : ''}${sec}`;
}

/**
 * Auto-play next logic
 */
mainPlayer.onended = () => {
    if (currentIndex + 1 < currentVideos.length) {
        setTimeout(() => {
            playVideo(currentIndex + 1);
        }, 1000); // Short delay between videos
    } else {
        // showNotification('Lista de reproducción finalizada', 'success');
    }
};

const addRootFolderBtn = document.getElementById('add-root-folder-btn');
addRootFolderBtn.addEventListener('click', (e) => {
    e.preventDefault();
    handleCreateFolder('');
});

async function handleCreateFolder(parentPath) {
    let container;

    if (parentPath === '' || parentPath === '.') {
        // En la raíz
        container = folderList;
    } else {
        // Buscar el <ul> de la carpeta padre
        const parentItem = document.querySelector(`.folder-item[data-path="${parentPath}"]`);
        if (!parentItem) return;

        let subList = parentItem.nextElementSibling;
        if (!subList || !subList.classList.contains('sub-folders')) {
            // Si no tiene sublista, la creamos
            subList = document.createElement('ul');
            subList.className = 'sub-folders active';
            parentItem.parentNode.appendChild(subList);
            const toggle = parentItem.querySelector('.toggle-icon');
            if (toggle) {
                toggle.textContent = '▼';
                toggle.classList.add('expanded');
            }
        } else {
            subList.classList.add('active');
        }
        container = subList;
    }

    // Crear elemento temporal para el input
    const li = document.createElement('li');
    li.innerHTML = `
        <div class="folder-item editing">
            <div class="folder-header">
                <span class="icon">📁</span>
                <input type="text" class="rename-input" id="temp-folder-input" value="Nueva Carpeta">
            </div>
        </div>
    `;

    container.prepend(li);
    const input = li.querySelector('#temp-folder-input');
    input.focus();
    input.select();

    const finish = async () => {
        const folderName = input.value.trim();
        if (folderName) {
            try {
                const success = await py.create_folder(parentPath || '.', folderName);
                if (success) {
                    // showNotification(`Carpeta "${folderName}" creada`, 'success', true);
                } else {
                    showNotification('Error al crear', 'error');
                }
            } catch (e) { showNotification('Error de conexión', 'error'); }
        }
        fetchFolders(); // Refrescar en cualquier caso para limpiar el temporal
    };

    input.addEventListener('blur', () => {
        // Pequeño delay para no interferir con el click de guardado si existiera
        setTimeout(finish, 100);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') finish();
        if (e.key === 'Escape') fetchFolders();
    });
}

// --- Event Listeners Cloud ---
newCloudPlaylistBtn.addEventListener('click', () => showCloudModal(-1));
closeCloudModalBtn.addEventListener('click', () => cloudModal.classList.remove('active'));
cancelCloudModalBtn.addEventListener('click', () => cloudModal.classList.remove('active'));
addToCloudBtn.addEventListener('click', resolveAndAddUrl);
saveCloudModalBtn.addEventListener('click', saveCloudPlaylistsToServer);

// Cerrar modal al hacer click fuera del contenido
cloudModal.addEventListener('click', (e) => {
    if (e.target === cloudModal) cloudModal.classList.remove('active');
});

// Privacy toggle
// --- Lógica de Modo Privacidad ---
function togglePrivacyMode() {
    const isActive = document.body.classList.toggle('privacy-active');

    if (isActive) {
        // Lógica de Modo Privacidad aislada en iframe
        privacyFrame.style.display = 'block';
        privacyFrame.src = 'agenda.html';
        mainPlayer.pause();
    } else {
        privacyFrame.src = 'about:blank';

        // Reanudar reproducción si hay un video seleccionado
        if (currentIndex !== -1) {
            const video = currentVideos[currentIndex];
            if (video.type === 'youtube' || video.type === 'embed') {
                // Para embeds, usualmente el estado se mantiene o requiere recarga,
                // pero al menos nos aseguramos de que el video nativo se reanude si aplica.
                // Intentamos reanudar el reproductor externo si es posible
                externalPlayer.contentWindow.postMessage('{"event":"command","func":"playVideo","args":""}', '*');
            } else {
                mainPlayer.play().catch(() => {});
            }
        }

        // showNotification('Modo Privado desactivado', 'info');
    }
}

// Botón de Privacidad (Agenda)
hideBtn.addEventListener('click', togglePrivacyMode);
// fb-close vive dentro de agenda.html; comunicación via postMessage


// Listeners de pestañas movidos a DOMContentLoaded principal

// Atajo de teclado: ESC para Modo Privacidad
window.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    const browserIsOpen = browserScreen && browserScreen.style.display !== 'none';

    if (browserIsOpen) {
        if (typeof toggleBrowserBar === 'function') toggleBrowserBar();
    } else {
        togglePrivacyMode();
    }
});

// Sistema de Exploración Local
let currentExploringPath = '';

btnBrowseLocal.addEventListener('click', () => {
    openBrowser(configMediaPath.value || '');
});

async function openBrowser(targetPath) {
    browserModal.style.display = 'flex';
    try {
        const data = JSON.parse(await py.browse_folders(targetPath || ''));

        if (data.error) {
            showNotification('Error: ' + data.error, 'error');
            return;
        }

        renderBrowser(data);
    } catch (e) {
        showNotification('No se pudo acceder a esa ruta', 'error');
    }
}

function renderBrowser(data) {
    currentExploringPath = data.currentPath;
    browserCurrentPath.textContent = data.currentPath;

    browserList.innerHTML = '';

    // Botón para subir nivel
    const parentBox = document.createElement('div');
    parentBox.className = 'folder-box parent';
    parentBox.innerHTML = '<span class="icon">⬆️</span><span class="name">Subir un nivel</span>';
    parentBox.onclick = () => openBrowser(data.parentPath);
    browserList.appendChild(parentBox);

    data.folders.forEach(folder => {
        const box = document.createElement('div');
        box.className = 'folder-box';
        box.innerHTML = `<span class="icon">📁</span><span class="name">${folder}</span>`;
        box.onclick = () => openBrowser(data.currentPath + '/' + folder);
        browserList.appendChild(box);
    });
}

selectThisFolder.addEventListener('click', () => {
    configMediaPath.value = currentExploringPath;
    browserModal.style.display = 'none';
});

closeBrowserBtn.addEventListener('click', () => {
    browserModal.style.display = 'none';
});

// (El listener de ESC ya fue definido arriba)

// Botones de Pegar (Cloud URL y Home URL)
// Agenda maneja sus propios paste en agenda.js
const pasteCloudUrlBtn = document.getElementById('paste-cloud-url');
const handlePasteToInput = async (targetId) => {
    try {
        const text = await navigator.clipboard.readText();
        const input = document.getElementById(targetId);
        if (text && input) input.value = text;
    } catch (err) {
        showNotification('Acceso al portapapeles denegado', 'error');
    }
};
const pasteHomeUrlBtn = document.getElementById('btn-paste-home-url');
if (pasteHomeUrlBtn) pasteHomeUrlBtn.addEventListener('click', () => handlePasteToInput('config-home-url'));

if (pasteCloudUrlBtn) {
    pasteCloudUrlBtn.addEventListener('click', async () => {
        try {
            const text = await navigator.clipboard.readText();
            if (text) {
                cloudUrlInput.value = text;
                // showNotification('URL pegada del portapapeles', 'info');
            }
        } catch (err) {
            showNotification('No se pudo leer el portapapeles. Intenta Ctrl+V.', 'error');
        }
    });
}

// Navigation Listeners
prevBtn.addEventListener('click', () => {
    if (currentIndex > 0) {
        playVideo(currentIndex - 1);
    } else {
        showNotification('Primer video alcanzado', 'info');
    }
});

nextBtn.addEventListener('click', () => {
    if (currentIndex + 1 < currentVideos.length) {
        playVideo(currentIndex + 1);
    } else {
        showNotification('Último video alcanzado', 'info');
    }
});

// Sidebar Toggle Logic (Izquierda)
toggleSidebarBtn.addEventListener('click', () => {
    if (window.innerWidth <= 768) {
        sidebar.classList.toggle('active');
    } else {
        appContainer.classList.toggle('sidebar-collapsed');
    }
});

if (closeSidebarMobileBtn) {
    closeSidebarMobileBtn.addEventListener('click', () => {
        sidebar.classList.remove('active');
    });
}

// Playlist Sidebar Control (Derecha) - Nuevo Botón dedicado
playlistBtn.addEventListener('click', () => {
    const wasActive = playlistSidebar.classList.contains('active');
    playlistSidebar.classList.toggle('active');
    if (!wasActive) {
        startPlaylistAutoClose();
    } else {
        cancelPlaylistAutoClose();
    }
});

// Cerrar playlist al hacer clic fuera de ella
document.addEventListener('click', (e) => {
    if (!playlistSidebar.classList.contains('active')) return;
    if (playlistSidebar.contains(e.target)) return;
    if (e.target === playlistBtn || playlistBtn.contains(e.target)) return;
    playlistSidebar.classList.remove('active');
});

if (resetPlayerBtn) {
    resetPlayerBtn.addEventListener('click', () => {
        resetPlayer();
        // showNotification('Reproductor reiniciado', 'info');
    });
}

// Pausar auto-cierre cuando el cursor está sobre la playlist
playlistSidebar.addEventListener('mouseenter', cancelPlaylistAutoClose);
playlistSidebar.addEventListener('mouseleave', () => {
    if (playlistSidebar.classList.contains('active')) {
        startPlaylistAutoClose();
    }
});

// Full UI / Cinema Mode Toggle (🚀 Restaurado)
toggleUiBtn.addEventListener('click', () => {
    const isCinemaMode = document.body.classList.toggle('ui-collapsed');
    const docElm = document.documentElement;

    if (isCinemaMode) {
        if (appContainer) appContainer.classList.add('sidebar-collapsed');

        // Intentar pantalla completa con alta compatibilidad
        try {
            if (docElm.requestFullscreen) docElm.requestFullscreen();
            else if (docElm.mozRequestFullScreen) docElm.mozRequestFullScreen();
            else if (docElm.webkitRequestFullscreen) docElm.webkitRequestFullscreen();
            else if (docElm.msRequestFullscreen) docElm.msRequestFullscreen();
        } catch (e) {
            console.warn("Fullscreen denegado o no soportado");
        }
        // showNotification('Modo Cine activado', 'success');
    } else {
        if (appContainer) appContainer.classList.remove('sidebar-collapsed');

        // Salir de pantalla completa con alta compatibilidad
        try {
            if (document.exitFullscreen) document.exitFullscreen();
            else if (document.mozCancelFullScreen) document.mozCancelFullScreen();
            else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
            else if (document.msExitFullscreen) document.msExitFullscreen();
        } catch (e) {
            console.warn("Error al salir de Fullscreen");
        }
        // showNotification('Interfaz restaurada', 'success');
    }

    toggleUiBtn.innerHTML = isCinemaMode
        ? '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/></svg>'
        : '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>';
});

// Sincronizar si el usuario sale manualmente (ej. tecla ESC)
const syncFullscreenState = () => {
    const isFullscreen = document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement;

    if (!isFullscreen && document.body.classList.contains('ui-collapsed')) {
        document.body.classList.remove('ui-collapsed');
        if (appContainer) appContainer.classList.remove('sidebar-collapsed');
        toggleUiBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>';
        // showNotification('Interfaz restaurada', 'info');
    }
};

document.addEventListener('fullscreenchange', syncFullscreenState);
document.addEventListener('webkitfullscreenchange', syncFullscreenState);
document.addEventListener('mozfullscreenchange', syncFullscreenState);
document.addEventListener('MSFullscreenChange', syncFullscreenState);

// --- Lógica de Etiquetas ---
function openTagsModal(video, folder) {
    currentTaggingVideo = video;
    currentTaggingFolder = folder;
    const videoId = video.url || video.name;

    tagsVideoTitle.textContent = video.name;

    // Iniciar registro si no existe
    if (!videoTags[videoId]) {
        videoTags[videoId] = { tags: [], data: video, lastKnownFolder: folder };
    }

    renderTagsModal();
    tagsModal.classList.add('active');
}

function closeTagsModal() {
    tagsModal.classList.remove('active');
    currentTaggingVideo = null;
    currentTaggingFolder = null;
    renderVideos(currentVideos); // Para actualizar el color del botón 🏷️ si cambió
}

closeTagsModalBtn.addEventListener('click', closeTagsModal);
doneTagsModalBtn.addEventListener('click', closeTagsModal);

function renderTagsModal() {
    if (!currentTaggingVideo) return;
    const videoId = currentTaggingVideo.url || currentTaggingVideo.name;
    const currentTags = (videoTags[videoId] && videoTags[videoId].tags) ? videoTags[videoId].tags : [];

    // Renderizar tags actuales del video
    currentVideoTagsDiv.innerHTML = currentTags.map(tag => `
        <div class="tag-chip active">
            ${tag} <span class="remove-tag" data-tag="${tag}">×</span>
        </div>
    `).join('');

    currentVideoTagsDiv.querySelectorAll('.remove-tag').forEach(span => {
        span.addEventListener('click', (e) => {
            e.stopPropagation();
            const btn = e.currentTarget;
            const tag = btn.dataset.tag;
            videoTags[videoId].tags = videoTags[videoId].tags.filter(t => t !== tag);
            saveTags();
            renderTagsModal();
        });
    });

    // Encontrar todos los tags únicos disponibles en la app
    const allTagsSet = new Set();
    Object.values(videoTags).forEach(v => {
        if(v.tags) v.tags.forEach(t => allTagsSet.add(t));
    });

    const allTags = Array.from(allTagsSet).filter(t => !currentTags.includes(t)).sort();

    allAvailableTagsDiv.innerHTML = allTags.map(tag => `
        <div class="tag-chip add-existing-tag" data-tag="${tag}">
            ${tag} +
        </div>
    `).join('');

    if (allTags.length === 0) {
        allAvailableTagsDiv.innerHTML = '<span style="color:var(--text-secondary); font-size:0.8rem;">No hay otras etiquetas.</span>';
    }

    allAvailableTagsDiv.querySelectorAll('.add-existing-tag').forEach(chip => {
        chip.addEventListener('click', (e) => {
            const tag = e.currentTarget.dataset.tag;
            videoTags[videoId].tags.push(tag);
            saveTags();
            renderTagsModal();
        });
    });
}

addTagBtn.addEventListener('click', () => {
    const newTag = newTagInput.value.trim().toLowerCase();
    if (!newTag || !currentTaggingVideo) return;

    const videoId = currentTaggingVideo.url || currentTaggingVideo.name;
    if (!videoTags[videoId].tags.includes(newTag)) {
        videoTags[videoId].tags.push(newTag);
        saveTags();
        renderTagsModal();
    }
    newTagInput.value = '';
});

newTagInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') addTagBtn.click();
});

function updatePlayerTagChips(video) {
    const container = document.getElementById('current-player-tags');
    if (!container) return;
    const vid = video || (currentIndex !== -1 ? currentVideos[currentIndex] : null);
    if (!vid) { container.innerHTML = ''; return; }
    const videoId = vid.url || vid.name;
    const tags = (videoTags[videoId] && videoTags[videoId].tags) || [];
    container.innerHTML = '';
    tags.forEach(t => {
        const chip = document.createElement('span');
        chip.className = 'player-tag-chip';
        chip.innerHTML = `${t}<button class="player-tag-remove" title="Quitar etiqueta">×</button>`;
        chip.addEventListener('click', (e) => {
            if (!e.target.classList.contains('player-tag-remove')) {
                playVideosByTag(t);
            }
        });
        chip.querySelector('.player-tag-remove').addEventListener('click', (e) => {
            e.stopPropagation();
            if (videoTags[videoId]) {
                videoTags[videoId].tags = videoTags[videoId].tags.filter(tag => tag !== t);
                saveTags();
            }
        });
        container.appendChild(chip);
    });
}

function saveTags() {
    const scopePath = (settings.mediaPath || '').trim();
    if (typeof py.save_video_tags_for_path === 'function') {
        py.save_video_tags_for_path(scopePath, JSON.stringify(videoTags));
    } else {
        py.save_video_tags(JSON.stringify(videoTags));
    }
    renderTagsList();
    updateVideoQuickActions();
    updatePlayerTagChips();
}

function renderTagsList() {
    if (!tagsList) return;

    // Obtener etiquetas únicas
    const tagCounts = {};
    Object.values(videoTags).forEach(v => {
        if(v.tags) v.tags.forEach(t => tagCounts[t] = (tagCounts[t] || 0) + 1);
    });

    const uniqueTags = Object.keys(tagCounts).sort();

    if (uniqueTags.length === 0) {
        tagsList.innerHTML = '<li class="info-text" style="font-size:0.8rem; opacity:0.5; text-align:center; margin-top:10px;">Aún no hay etiquetas</li>';
        return;
    }

    tagsList.innerHTML = uniqueTags.map(tag => `
        <li class="tag-chip tag-nav-item" data-tag="${tag}" style="display:flex; align-items:center; gap:4px;">
            <span class="tag-nav-label" style="flex:1; cursor:pointer;">${tag} <span style="opacity:0.6; font-size:0.7rem;">(${tagCounts[tag]})</span></span>
            <button class="tag-nav-delete" data-tag="${tag}" title="Eliminar etiqueta" style="background:transparent; border:none; cursor:pointer; color:var(--danger,#e05); font-size:0.85rem; line-height:1; padding:0 2px; opacity:0.7; flex-shrink:0;">✕</button>
        </li>
    `).join('');

    tagsList.querySelectorAll('.tag-nav-item').forEach(item => {
        item.querySelector('.tag-nav-label').addEventListener('click', () => {
            const tag = item.dataset.tag;
            playVideosByTag(tag);
        });

        item.querySelector('.tag-nav-delete').addEventListener('click', (e) => {
            e.stopPropagation();
            const tag = item.dataset.tag;
            // Eliminar la etiqueta de todos los videos
            Object.values(videoTags).forEach(v => {
                if (v.tags) v.tags = v.tags.filter(t => t !== tag);
            });
            saveTags();
            renderTagsList();
            showNotification(`Etiqueta "${tag}" eliminada`, 'info');
        });
    });
}

if (clearAllTagsBtn) {
    clearAllTagsBtn.addEventListener('click', () => {
        isDeletingAllTags = true;
        videoToDelete = null;
        folderPathToDelete = null;
        cloudPlaylistToDelete = null;
        reminderToDelete = null;
        shopItemToDelete = null;

        const modalTitle = deleteModal.querySelector('h3');
        const modalText = deleteModal.querySelector('p');
        const activeLibraryPath = (configMediaPath.value || settings.mediaPath || '').trim();
        modalTitle.textContent = '¿Borrar Todas las Etiquetas?';
        modalText.innerHTML = `Esta acción eliminará las etiquetas de la biblioteca actual.<br><br><span style="opacity:0.8; font-size:0.86rem;">Ruta: <strong>${activeLibraryPath || '(sin ruta configurada)'}</strong></span>`;

        deleteModal.classList.add('active');
    });
}

async function playVideosByTag(tag) {
    // Recopilar todos los videos que tienen este tag
    const taggedVideosData = [];

    for (const [key, val] of Object.entries(videoTags)) {
        if (val.tags && val.tags.includes(tag)) {
            const folder = val.lastKnownFolder || "";
            // Detección robusta: por icono en nombre de carpeta o por tener tipo definido (Cloud)
            const isCloud = folder.includes('☁️') || (val.data && val.data.type);

            if (!isCloud) {
                // Es Local: Verificar rápido si el archivo parece seguir en su carpeta
                try {
                    const res = { json: async () => JSON.parse(await py.get_videos(folder)) };
                    const vids = await res.json();
                    const currentVid = vids.find(v => v.name === val.data.name);

                    if (currentVid) {
                        taggedVideosData.push(currentVid);
                    } else {
                        // El archivo se movió, intentar auto-reconectar
                        const searchRes = { json: async () => JSON.parse(await py.search_video(val.data.name)) };
                        const searchData = await searchRes.json();
                        if (searchData.found) {
                            val.lastKnownFolder = searchData.folder;
                            val.data.url = searchData.url;
                            taggedVideosData.push({...val.data});
                            saveTags();
                        }
                    }
                } catch(e) { console.warn(e); }
            } else {
                // Es de la nube: Agregar directo (clonando para evitar referencias)
                taggedVideosData.push({...val.data});
            }
        }
    }

    if (taggedVideosData.length > 0) {
        currentVideos = taggedVideosData;
        currentFolderName.textContent = `🏷️ Etiqueta: ${tag}`;
        renderVideos(currentVideos);
        playVideo(0);
        showNotification(`Reproduciendo etiqueta: ${tag}`, 'success');
    } else {
        showNotification('No se encontraron videos con esta etiqueta', 'error');
    }
}

function enableFolderRename(span, oldPath) {
    const originalName = span.textContent;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'rename-input folder-rename';
    input.value = originalName;

    span.parentNode.replaceChild(input, span);
    input.focus();
    input.select();

    let isDone = false;
    const finishRename = async () => {
        if (isDone) return;
        isDone = true;

        const newName = input.value.trim();
        if (newName && newName !== originalName) {
            const success = await renameFolderAsync(oldPath, newName);
            if (success) {
                // MIGRACIÓN MASIVA DE CACHÉ DE IMÁGENES
                const oldPrefix = `${buildLocalMediaUrl(oldPath, '')}/`;
                const parentPath = oldPath.split('/').slice(0, -1).join('/');
                const newFolderPath = parentPath ? `${parentPath}/${newName}` : newName;
                const newPrefix = `${buildLocalMediaUrl(newFolderPath, '')}/`;

                thumbnailCache.forEach((value, key) => {
                    if (key.startsWith(oldPrefix)) {
                        const newKey = key.replace(oldPrefix, newPrefix);
                        thumbnailCache.set(newKey, value);
                        thumbnailCache.delete(key);
                    }
                });

                fetchFolders(); // Refrescar árbol completo
            } else {
                if (input.parentNode) input.parentNode.replaceChild(span, input);
            }
        } else {
            if (input.parentNode) input.parentNode.replaceChild(span, input);
        }
    };

    input.addEventListener('blur', finishRename);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); finishRename(); }
        if (e.key === 'Escape') { isDone = true; if (input.parentNode) input.parentNode.replaceChild(span, input); }
    });
}

async function renameFolderAsync(oldPath, newName) {
    try {
        const success = await py.rename_folder(oldPath, newName);
        if (success) {
            // showNotification(`Carpeta renombrada a "${newName}"`, 'success', true);
            return true;
        } else {
            showNotification('Error al renombrar carpeta', 'error');
            return false;
        }
    } catch (e) {
        showNotification('Error de conexión', 'error');
        return false;
    }
}

// --- Manejo del Loader Global ---
const playerLoader = document.getElementById('player-loader');
if (playerLoader) {
    const hideLoader = () => playerLoader.style.display = 'none';
    mainPlayer.addEventListener('loadeddata', hideLoader);
    mainPlayer.addEventListener('playing', hideLoader);
    mainPlayer.addEventListener('error', () => {
        hideLoader();
        if (currentIndex !== -1 && currentVideos[currentIndex]) {
            showNotification('Error al reproducir el video', 'error');
            mainPlayer.pause();
        }
    });
    externalPlayer.addEventListener('load', hideLoader);
}

// --- Navegación Interna Minichrome ---
const openBrowserBtn = document.getElementById('open-browser-btn');
if (openBrowserBtn) {
    openBrowserBtn.addEventListener('click', () => {
        window.location.href = 'newtab.html';
    });
}

const openImagesBtn = document.getElementById('open-images-btn');
if (openImagesBtn) {
    openImagesBtn.addEventListener('click', () => {
        window.location.href = 'imageplayer.html';
    });
}

let _videoPlayerBootstrapped = false;
async function bootstrapVideoPlayer() {
    if (_videoPlayerBootstrapped) return;
    _videoPlayerBootstrapped = true;

    try {
        updateAgendaMiniIcon();
        // Refresco ligero para cambio de fecha sin reiniciar la app.
        setInterval(updateAgendaMiniIcon, 60000);

        // Evitar pantalla en blanco mientras carga biblioteca/carpetas.
        setStartupVideo();

        await DbManager.init();

        try {
            const playbackMap = JSON.parse(await py.get_playback_history());
            Object.entries(playbackMap || {}).forEach(([url, time]) => playbackHistory.set(url, time));
        } catch (_e) {
            // Si no hay historial previo, continuamos silenciosamente.
        }

        await loadSettings();
        await loadTags();
        await fetchCloudPlaylists();
        renderTagsList();
    } catch (e) {
        console.error('Error durante inicializacion de videoplayer:', e);
        showNotification('Error al iniciar VideoPlayer', 'error');
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapVideoPlayer);
} else {
    bootstrapVideoPlayer();
}

// Reemplazar la funcionalidad original de privacidad con una redirección a la Agenda
if (hideBtn) {
    hideBtn.removeEventListener('click', togglePrivacyMode);
    hideBtn.addEventListener('click', () => {
        window.location.href = 'agenda.html';
    });
}
