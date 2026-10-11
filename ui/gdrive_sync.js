const syncState = {
    connected: false,
    syncing: false,
    lastSync: 'Nunca',
    accessToken: null
};
window.syncState = syncState;

function notifySync(msg, type) {
    if (typeof window.showToast === 'function') window.showToast(msg, type);
    else if (typeof notify === 'function') notify(msg, type);
}

async function initGDriveSync() {
    if (typeof chrome === 'undefined' || !chrome.storage) return;

    // Si estamos en entorno de escritorio y no hay token en storage, intentar obtenerlo de window.desktop
    if (window.desktop && typeof window.desktop.getAuthToken === 'function') {
        try {
            const auth = await window.desktop.getAuthToken();
            if (auth && auth.token) {
                syncState.accessToken = auth.token;
                syncState.connected = true;
                chrome.storage.local.set({ gdrive_token: auth.token });
            }
        } catch (e) {}
    }

    chrome.storage.local.get(['gdrive_token', 'gdrive_last_sync'], (result) => {
        if (result.gdrive_token) {
            syncState.accessToken = result.gdrive_token;
            syncState.connected = true;
        }
        if (result.gdrive_last_sync) {
            syncState.lastSync = new Date(result.gdrive_last_sync).toLocaleString();
        }
        updateSyncUI();
        checkAndShowBackupOption();

        if (syncState.connected) {
            syncNow(true);
        }
    });
}

async function signInGDrive() {
    syncState.syncing = true;
    updateSyncUI();

    let token = null;
    if (window.desktop && typeof window.desktop.signInGoogle === 'function') {
        const res = await window.desktop.signInGoogle();
        if (res && res.token) {
            token = res.token;
        } else {
            const err = res && res.error ? res.error : 'No se pudo conectar con Google. La app sigue funcionando en local.';
            notifySync(err, 'info');
            syncState.syncing = false;
            syncState.connected = false;
            updateSyncUI();
            return;
        }
    } else if (window.py && typeof window.py.google_connect === 'function') {
        window.py.google_connect();
        syncState.syncing = true;
        updateSyncUI();
        return;
    } else if (typeof chrome !== 'undefined' && chrome.identity) {
        if (chrome.identity.getAuthToken) {
            token = await new Promise((resolve) => {
                chrome.identity.getAuthToken({ interactive: true }, (tok) => {
                    if (chrome.runtime && chrome.runtime.lastError) {
                        const err = chrome.runtime.lastError.message || 'Token no recibido';
                        if (err.toLowerCase().includes('sincroniz') || err.toLowerCase().includes('sync') || err.toLowerCase().includes('signed in')) {
                            notifySync(`Para conectar en Chrome, activa la sincronización o inicia sesión con tu cuenta de Google en el perfil de tu navegador (chrome://settings/syncSetup).`, 'info');
                        } else {
                            notifySync(`Error al conectar con Google: ${err}`, 'error');
                        }
                        resolve(null);
                    } else {
                        resolve(tok || null);
                    }
                });
            });
        }
        
        // Si getAuthToken falló o no está disponible, intentar launchWebAuthFlow si hay client_id
        if (!token && chrome.identity.launchWebAuthFlow && chrome.runtime.getManifest) {
            try {
                const manifest = chrome.runtime.getManifest();
                const clientId = manifest?.oauth2?.client_id;
                const scopes = (manifest?.oauth2?.scopes || ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/calendar']).join(' ');
                if (clientId) {
                    const redirectUri = chrome.identity.getRedirectURL ? chrome.identity.getRedirectURL() : `https://${chrome.runtime.id}.chromiumapp.org/`;
                    const authUrl = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${encodeURIComponent(clientId)}&response_type=token&redirect_uri=${encodeURIComponent(redirectUri)}&scope=${encodeURIComponent(scopes)}`;
                    
                    const responseUrl = await new Promise((resolve) => {
                        chrome.identity.launchWebAuthFlow({ url: authUrl, interactive: true }, (url) => {
                            if (chrome.runtime.lastError || !url) resolve(null);
                            else resolve(url);
                        });
                    });
                    
                    if (responseUrl) {
                        const m = responseUrl.match(/access_token=([^&]+)/);
                        if (m && m[1]) {
                            token = decodeURIComponent(m[1]);
                        }
                    }
                }
            } catch (flowErr) {
                console.warn('launchWebAuthFlow fallback warning:', flowErr);
            }
        }
    } else {
        notifySync('La capa de escritorio o identidad no está disponible.', 'error');
        syncState.syncing = false;
        updateSyncUI();
        return;
    }

    syncState.syncing = false;
    if (token) {
        syncState.accessToken = token;
        syncState.connected = true;
        chrome.storage.local.set({ gdrive_token: token, gdrive_force_download: true }, () => {
            notifySync('Conectado a Google Drive exitosamente', 'success');
            updateSyncUI();
            syncNow(true, true);
        });
    } else {
        syncState.connected = false;
        updateSyncUI();
    }
}

async function signOutGDrive() {
    if (window.desktop && window.desktop.signOutGoogle) {
        await window.desktop.signOutGoogle();
    }
    syncState.accessToken = null;
    syncState.connected = false;
    chrome.storage.local.remove(['gdrive_token'], () => {
        notifySync('Desconectado de Google Drive. Los datos permanecen locales.', 'success');
        updateSyncUI();
    });
}

async function findFileInGDrive(token) {
    const q = encodeURIComponent("name='mkorganizer_data.json' and trashed=false");
    const response = await fetch(
        `https://www.googleapis.com/drive/v3/files?q=${q}&spaces=drive&orderBy=modifiedTime desc&pageSize=10&fields=files(id,name,modifiedTime)`,
        { headers: { Authorization: `Bearer ${token}` } }
    );
    const data = await response.json();
    if (data.files && data.files.length > 0) return data.files[0].id;
    return null;
}

async function downloadFromGDrive(token, fileId) {
    const response = await fetch(
        `https://www.googleapis.com/drive/v3/files/${fileId}?alt=media`,
        { headers: { Authorization: `Bearer ${token}` } }
    );
    return await response.json();
}

async function uploadToGDrive(token, fileId, payload) {
    await fetch(
        `https://www.googleapis.com/upload/drive/v3/files/${fileId}?uploadType=media`,
        {
            method: 'PATCH',
            headers: {
                Authorization: `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        }
    );
}

async function createInGDrive(token, payload) {
    const boundary = '-------314159265358979323846';
    const delimiter = `\r\n--${boundary}\r\n`;
    const closeDelim = `\r\n--${boundary}--`;
    const metadata = JSON.stringify({ name: 'mkorganizer_data.json', mimeType: 'application/json' });
    const data = JSON.stringify(payload);
    const body = delimiter +
        'Content-Type: application/json; charset=UTF-8\r\n\r\n' +
        metadata +
        delimiter +
        'Content-Type: application/json\r\n\r\n' +
        data +
        closeDelim;

    await fetch(
        'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart',
        {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${token}`,
                'Content-Type': `multipart/related; boundary=${boundary}`
            },
            body: body
        }
    );
}

async function syncNow(auto = false, preferDrive = false) {
    if (!syncState.connected && !auto) {
        notifySync('Conéctate a Google Drive primero', 'info');
        return;
    }

    syncState.syncing = true;
    updateSyncUI();

    try {
        if (window.desktop && typeof window.desktop.syncDrive === 'function') {
            const result = await window.desktop.syncDrive({ auto: !!auto, preferDrive: !!preferDrive });
            if (!result || !result.ok) {
                throw new Error((result && result.error) || 'Fallo en la sincronización');
            }
            if (result.action === 'download') {
                notifySync('Datos de Google Drive aplicados. Recargando…', 'success');
                setTimeout(() => location.reload(), 800);
                return;
            }
            if (!auto) {
                notifySync(result.action === 'create' ? 'Se creó mkorganizer_data.json en Google Drive con tus datos.' : 'Sincronización con Google Drive completada', 'success');
            }
        } else {
            const token = syncState.accessToken;
            if (!token) throw new Error('No hay sesión de Google activa');

            const keys = [
                'agenda', 'shopping', 'income', 'kanban', 'kanban_cards', 'notes', 'passwords', 'app_config', 
                'deudas_list', 'deudas_presupuesto', 'savings_goals', 'budget_limits', 'budget_income_targets',
                'budget_currency_symbol', 'budget_currency_code', 'budget_second_currency_enabled',
                'budget_second_currency_symbol', 'budget_second_currency_code', 'budget_exchange_rate'
            ];

            const localData = await new Promise((res) => chrome.storage.local.get(keys, res));
            const lastSync = await new Promise((res) => chrome.storage.local.get(['gdrive_last_sync'], (r) => res(r && r.gdrive_last_sync ? r.gdrive_last_sync : 0)));

            const fileId = await findFileInGDrive(token);
            if (fileId) {
                const remoteData = await downloadFromGDrive(token, fileId);
                const hasRemote = remoteData && typeof remoteData === 'object' && Object.keys(remoteData).length > 0;
                const remoteTs = Number(remoteData && remoteData.timestamp) || 0;
                const hasLocal = Object.keys(localData).length > 0;

                const driveIsSource = hasRemote && (preferDrive || (!lastSync && !hasLocal) || (remoteTs > (lastSync + 2000)));

                if (driveIsSource) {
                    if (hasLocal) {
                        await new Promise((res) => chrome.storage.local.set({ backup_before_sync: { ...localData } }, res));
                    }
                    await new Promise((res) => chrome.storage.local.set(remoteData, res));
                    await new Promise((res) => chrome.storage.local.set({ gdrive_last_sync: Math.max(Date.now(), remoteTs) }, res));
                    notifySync('Datos descargados de Google Drive. Actualizando…', 'success');
                    setTimeout(() => location.reload(), 800);
                    return;
                } else {
                    localData.timestamp = Date.now();
                    await uploadToGDrive(token, fileId, localData);
                    await new Promise((res) => chrome.storage.local.set({ gdrive_last_sync: Date.now() }, res));
                    if (!auto) notifySync('Sincronización con Google Drive completada', 'success');
                }
            } else {
                localData.timestamp = Date.now();
                await createInGDrive(token, localData);
                await new Promise((res) => chrome.storage.local.set({ gdrive_last_sync: Date.now() }, res));
                if (!auto) notifySync('Se creó mkorganizer_data.json en Google Drive con tus datos locales.', 'success');
            }
        }
        finishSync();
    } catch (err) {
        console.error('Error durante la sincronización:', err);
        if (!auto) {
            const msg = String(err.message || err);
            if (msg.includes('Google Drive API has not been used') || msg.includes('disabled')) {
                // Google indica el proyecto del cliente OAuth: se muestra para saber dónde activarla.
                const project = (msg.match(/project[ =](\d+)/) || [])[1];
                notifySync(project
                    ? `La Google Drive API está desactivada en el proyecto ${project} de Google Cloud. Actívala en console.cloud.google.com/apis/library/drive.googleapis.com?project=${project}`
                    : 'Falta habilitar la Google Drive API en tu proyecto de Google Cloud.', 'error');
            } else {
                notifySync(`Fallo en la sincronización: ${err.message || 'Error'}`, 'info');
            }
        }
        syncState.syncing = false;
        updateSyncUI();
    }
}

function finishSync() {
    syncState.syncing = false;
    syncState.lastSync = new Date().toLocaleString();
    updateSyncUI();
}

async function restoreFromLocalBackup() {
    chrome.storage.local.get(['backup_before_sync'], (result) => {
        if (!result.backup_before_sync) {
            notifySync('No hay backup disponible para restaurar', 'info');
            return;
        }

        window.showConfirm('¿Deseas restaurar los datos del backup local anterior?', (confirm) => {
            if (!confirm) return;
            const backup = result.backup_before_sync;
            const skip = new Set(['gdrive_token', 'gdrive_refresh_token', 'gdrive_token_expiry', 'gdrive_last_sync', 'backup_before_sync']);
            const cleanData = { local_data_modified: true };
            Object.keys(backup).forEach((k) => {
                if (!skip.has(k) && backup[k] !== undefined) cleanData[k] = backup[k];
            });
            chrome.storage.local.set(cleanData, () => {
                notifySync('Datos restaurados desde backup. Recargando…', 'success');
                setTimeout(() => location.reload(), 800);
            });
        });
    });
}

function checkAndShowBackupOption() {
    chrome.storage.local.get(['backup_before_sync'], (result) => {
        if (result.backup_before_sync) {
            const syncStatusDiv = document.getElementById('sync-status-text');
            if (syncStatusDiv && !document.getElementById('restore-backup-btn')) {
                const restoreBtn = document.createElement('button');
                restoreBtn.id = 'restore-backup-btn';
                restoreBtn.className = 'ag-btn ag-btn-primary';
                restoreBtn.style.marginTop = '12px';
                restoreBtn.textContent = 'Restaurar Backup';
                restoreBtn.onclick = restoreFromLocalBackup;
                syncStatusDiv.parentElement.insertBefore(restoreBtn, syncStatusDiv.nextElementSibling);
            }
        }
    });
}

function updateSyncUI() {
    const statusText = document.getElementById('sync-status-text');
    const connectBtn = document.getElementById('sync-connect-btn');
    const syncBtn = document.getElementById('sync-now-btn');
    const lastSyncEl = document.getElementById('sync-last-time');

    if (statusText) {
        statusText.innerText = syncState.connected ? 'Conectado a Google Drive' : 'Desconectado de la nube';
        statusText.className = syncState.connected ? 'sync-status connected' : 'sync-status disconnected';
    }

    if (connectBtn) {
        connectBtn.innerText = syncState.connected ? 'Desconectar' : 'Conectar Google Drive';
        connectBtn.onclick = syncState.connected ? signOutGDrive : signInGDrive;
        connectBtn.className = syncState.connected ? 'ag-btn ag-btn-danger' : 'ag-btn ag-btn-primary';
    }

    if (syncBtn) {
        syncBtn.style.display = syncState.connected ? 'inline-block' : 'none';
        syncBtn.disabled = syncState.syncing;
        syncBtn.onclick = () => syncNow(false);

        const svgIcon = `
            <svg class="${syncState.syncing ? 'ag-spin' : ''}" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle; margin-left: 6px; display: inline-block;">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l.73-.73"/>
            </svg>
        `;

        if (syncState.syncing) {
            syncBtn.innerHTML = `Sincronizando ${svgIcon}`;
        } else {
            syncBtn.innerHTML = `Sincronizar ahora ${svgIcon}`;
        }
    }

    if (lastSyncEl) {
        lastSyncEl.innerText = syncState.lastSync;
    }
}

window.initGDriveSync = initGDriveSync;
window.syncNow = syncNow;
window.signInGDrive = signInGDrive;
window.signOutGDrive = signOutGDrive;
window.updateSyncUI = updateSyncUI;

document.addEventListener('DOMContentLoaded', () => {
    initGDriveSync();
});

let syncDebounceTimeout = null;
if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.onChanged) {
    chrome.storage.onChanged.addListener((changes, areaName) => {
        if (areaName === 'local' && syncState.connected && !syncState.syncing) {
            const keys = Object.keys(changes);
            const isInternal = keys.every((k) => 
                k.startsWith('gdrive_') || 
                k.startsWith('gcal_') || 
                k === 'backup_before_sync' || 
                k === 'local_data_modified'
            );
            if (isInternal) return;

            if (syncDebounceTimeout) clearTimeout(syncDebounceTimeout);
            syncDebounceTimeout = setTimeout(() => {
                syncNow(true);
            }, 5000);
        }
    });
}
