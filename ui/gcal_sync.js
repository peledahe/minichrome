// gcal_sync.js - Integración de Google Calendar

const gcalState = {
    connected: false,
    syncing: false,
    calendars: [],
    destinationCalendarId: 'primary',
    events: []
};

let cachedAccessToken = null;

// Inicializar estado de Google Calendar
async function initGCalendarSync() {
    if (typeof chrome === 'undefined' || !chrome.storage) return;

    if (window.desktop && typeof window.desktop.getAuthToken === 'function') {
        try {
            const auth = await window.desktop.getAuthToken();
            if (auth && auth.token) {
                cachedAccessToken = auth.token;
                gcalState.connected = true;
                chrome.storage.local.set({ gcal_connected: true, gdrive_token: auth.token });
            }
        } catch (e) {}
    }

    chrome.storage.local.get(['gcal_connected', 'gcal_selected_calendars', 'gcal_destination_calendar'], (result) => {
        if (result.gcal_connected) {
            gcalState.connected = true;
        }
        if (result.gcal_selected_calendars) {
            gcalState.calendars = result.gcal_selected_calendars;
        }
        if (result.gcal_destination_calendar) {
            gcalState.destinationCalendarId = result.gcal_destination_calendar;
        }
        
        updateGCalUI();

        if (gcalState.connected) {
            fetchGCalendars(true); // Cargar calendarios silenciosamente
        }
    });
}

// Conectar con Google Calendar
async function signInGCalendar() {
    gcalState.syncing = true;
    updateGCalUI();

    let token = null;
    if (window.desktop && typeof window.desktop.signInGoogle === 'function') {
        const res = await window.desktop.signInGoogle();
        if (res && res.token) {
            token = res.token;
        } else {
            const err = res && res.error ? res.error : 'No se pudo conectar con Google Calendar';
            window.showToast(err, 'info');
            gcalState.syncing = false;
            gcalState.connected = false;
            updateGCalUI();
            return;
        }
    } else if (window.py && typeof window.py.google_connect === 'function') {
        window.py.google_connect();
        gcalState.syncing = true;
        updateGCalUI();
        return;
    } else if (typeof chrome !== 'undefined' && chrome.identity) {
        if (chrome.identity.getAuthToken) {
            token = await new Promise((resolve) => {
                chrome.identity.getAuthToken({ interactive: true }, (tok) => {
                    if (chrome.runtime.lastError || !tok) {
                        const err = chrome.runtime.lastError?.message || 'Token no recibido';
                        if (err.toLowerCase().includes('sincroniz') || err.toLowerCase().includes('sync') || err.toLowerCase().includes('signed in')) {
                            window.showToast('Para conectar en Chrome, activa la sincronización o inicia sesión en tu perfil de Chrome (chrome://settings/syncSetup).', 'info');
                        } else {
                            window.showToast(`Error al conectar con Google Calendar: ${err}`, 'error');
                        }
                        resolve(null);
                    } else {
                        resolve(tok);
                    }
                });
            });
        }
        
        if (!token && chrome.identity.launchWebAuthFlow && chrome.runtime.getManifest) {
            try {
                const manifest = chrome.runtime.getManifest();
                const clientId = manifest?.oauth2?.client_id;
                const scopes = (manifest?.oauth2?.scopes || ['https://www.googleapis.com/auth/calendar']).join(' ');
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
                console.warn('gcal launchWebAuthFlow fallback:', flowErr);
            }
        }
    }

    gcalState.syncing = false;
    if (token) {
        cachedAccessToken = token;
        gcalState.connected = true;
        chrome.storage.local.set({ gcal_connected: true, gdrive_token: token }, () => {
            window.showToast('Conectado a Google Calendar exitosamente', 'success');
            updateGCalUI();
            fetchGCalendars();
        });
    } else {
        gcalState.connected = false;
        updateGCalUI();
    }
}

// Desconectar Google Calendar
async function signOutGCalendar() {
    gcalState.connected = false;
    gcalState.calendars = [];
    gcalState.events = [];
    window.gcalEvents = [];
    cachedAccessToken = null;

    if (window.desktop && typeof window.desktop.signOutGoogle === 'function') {
        await window.desktop.signOutGoogle();
    }
    
    chrome.storage.local.remove(['gcal_connected', 'gcal_selected_calendars', 'gcal_destination_calendar'], () => {
        window.showToast('Desconectado de Google Calendar.', 'success');
        updateGCalUI();
        if (window.renderCalendar) {
            window.renderCalendar();
        }
    });
}

// Obtener lista de calendarios
async function fetchGCalendars(silent = false) {
    if (!gcalState.connected) return;

    gcalState.syncing = true;
    updateGCalUI();

    try {
        const response = await fetchWithAuth('https://www.googleapis.com/calendar/v3/users/me/calendarList');
        
        if (!response.ok) {
            throw new Error(`Error API: ${response.status}`);
        }

        const data = await response.json();
        
        // Mapear y preservar el estado 'selected' anterior
        const prevSelected = gcalState.calendars.filter(c => c.selected).map(c => c.id);
        
        gcalState.calendars = (data.items || []).map(item => ({
            id: item.id,
            summary: item.summary || 'Calendario sin título',
            selected: prevSelected.includes(item.id) || (prevSelected.length === 0 && !!item.primary),
            isPrimary: !!item.primary
        }));

        // Si no hay calendario de destino guardado, usar el principal
        if (!gcalState.destinationCalendarId) {
            const primary = gcalState.calendars.find(c => c.isPrimary);
            gcalState.destinationCalendarId = primary ? primary.id : 'primary';
        }

        chrome.storage.local.set({
            gcal_selected_calendars: gcalState.calendars,
            gcal_destination_calendar: gcalState.destinationCalendarId
        });

        if (!silent) window.showToast('Calendarios cargados', 'success');
        
        // Cargar eventos tras obtener los calendarios
        fetchGCalEvents();

    } catch (err) {
        console.error('Error al obtener calendarios:', err);
        if (!silent) window.showToast(`Error al cargar calendarios: ${err.message}`, 'error');
    } finally {
        gcalState.syncing = false;
        updateGCalUI();
    }
}

// Obtener eventos para los calendarios seleccionados
async function fetchGCalEvents() {
    if (!gcalState.connected) return;

    const selectedCalendars = gcalState.calendars.filter(c => c.selected);
    if (selectedCalendars.length === 0) {
        gcalState.events = [];
        window.gcalEvents = [];
        if (window.renderCalendar) window.renderCalendar();
        return;
    }

    try {
        // Rango de tiempo amplio (mes actual y adyacentes)
        const now = new Date();
        const timeMin = new Date(now.getFullYear(), now.getMonth() - 2, 1).toISOString();
        const timeMax = new Date(now.getFullYear(), now.getMonth() + 3, 0).toISOString();

        let allEvents = [];

        for (const cal of selectedCalendars) {
            try {
                const response = await fetchWithAuth(
                    `https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(cal.id)}/events?timeMin=${timeMin}&timeMax=${timeMax}&singleEvents=true&maxResults=250`
                );
                
                if (response.ok) {
                    const data = await response.json();
                    const events = (data.items || []).map(ev => ({
                        id: ev.id,
                        summary: ev.summary || 'Evento sin título',
                        description: ev.description || '',
                        location: ev.location || '',
                        start: ev.start,
                        end: ev.end,
                        calendarName: cal.summary,
                        htmlLink: ev.htmlLink
                    }));
                    allEvents = allEvents.concat(events);
                }
            } catch (e) {
                console.error(`Error al cargar eventos de ${cal.summary}:`, e);
            }
        }

        gcalState.events = allEvents;
        window.gcalEvents = allEvents;

        if (window.renderCalendar) {
            window.renderCalendar();
        }
    } catch (err) {
        console.error('Error al obtener eventos de Google Calendar:', err);
    }
}

// Publicar una tarea específica en Google Calendar
async function publishReminderToGCal(reminder) {
    if (!gcalState.connected) {
        window.showToast('Conecta Google Calendar primero.', 'info');
        return;
    }

    try {
        const dateStr = reminder.dueDate || new Date().toISOString().split('T')[0];
        
        // Calcular el día siguiente para eventos de todo el día
        const parts = dateStr.split('-');
        const dateObj = new Date(parts[0], parts[1] - 1, parts[2]);
        dateObj.setDate(dateObj.getDate() + 1);
        const y = dateObj.getFullYear();
        const m = String(dateObj.getMonth() + 1).padStart(2, '0');
        const d = String(dateObj.getDate()).padStart(2, '0');
        const nextDayStr = `${y}-${m}-${d}`;

        const event = {
            summary: reminder.text,
            description: reminder.notes || 'Publicado desde Mk Organizer',
            start: { date: dateStr },
            end: { date: nextDayStr }
        };

        const response = await fetchWithAuth(
            `https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(gcalState.destinationCalendarId)}/events`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(event)
            }
        );

        if (!response.ok) {
            throw new Error(`Error HTTP: ${response.status}`);
        }

        window.showToast(`Tarea "${reminder.text}" publicada en Google Calendar`, 'success');
        fetchGCalEvents(); // Recargar eventos
    } catch (err) {
        console.error('Error al publicar evento:', err);
        window.showToast(`Error al publicar tarea: ${err.message}`, 'error');
    }
}

// Publicar todas las tareas en Google Calendar
async function publishAllRemindersToGCal(remindersList) {
    if (!gcalState.connected) {
        window.showToast('Conecta Google Calendar primero.', 'info');
        return;
    }

    if (!remindersList || remindersList.length === 0) {
        window.showToast('No hay tareas para publicar.', 'info');
        return;
    }

    gcalState.syncing = true;
    updateGCalUI();

    let successCount = 0;
    try {
        for (const reminder of remindersList) {
            try {
                const dateStr = reminder.dueDate || new Date().toISOString().split('T')[0];
                const parts = dateStr.split('-');
                const dateObj = new Date(parts[0], parts[1] - 1, parts[2]);
                dateObj.setDate(dateObj.getDate() + 1);
                const y = dateObj.getFullYear();
                const m = String(dateObj.getMonth() + 1).padStart(2, '0');
                const d = String(dateObj.getDate()).padStart(2, '0');
                const nextDayStr = `${y}-${m}-${d}`;

                const event = {
                    summary: reminder.text,
                    description: reminder.notes || 'Publicado desde Mk Organizer',
                    start: { date: dateStr },
                    end: { date: nextDayStr }
                };

                const response = await fetchWithAuth(
                    `https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(gcalState.destinationCalendarId)}/events`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(event)
                    }
                );

                if (response.ok) {
                    successCount++;
                }
            } catch (e) {
                console.error(`Error al publicar tarea: ${reminder.text}:`, e);
            }
        }

        window.showToast(`Se publicaron ${successCount} tareas en Google Calendar`, 'success');
        fetchGCalEvents();
    } catch (err) {
        console.error('Error en publicación masiva:', err);
        window.showToast(`Error al publicar tareas: ${err.message}`, 'error');
    } finally {
        gcalState.syncing = false;
        updateGCalUI();
    }
}

// Obtener token de identidad de Chrome / Escritorio con promesa
async function getAuthTokenPromise() {
    if (cachedAccessToken) {
        return cachedAccessToken;
    }
    if (window.desktop && typeof window.desktop.getAuthToken === 'function') {
        try {
            const auth = await window.desktop.getAuthToken();
            if (auth && auth.token) {
                cachedAccessToken = auth.token;
                return auth.token;
            }
        } catch (e) {}
    }
    return new Promise((resolve) => {
        if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
            chrome.storage.local.get(['gdrive_token'], (res) => {
                if (res && res.gdrive_token) {
                    cachedAccessToken = res.gdrive_token;
                    resolve(res.gdrive_token);
                    return;
                }
                if (typeof chrome !== 'undefined' && chrome.identity && chrome.identity.getAuthToken) {
                    chrome.identity.getAuthToken({ interactive: false }, (tok) => {
                        if (tok) cachedAccessToken = tok;
                        resolve(tok || null);
                    });
                } else {
                    resolve(null);
                }
            });
        } else {
            resolve(null);
        }
    });
}

// Wrapper de fetch que maneja expiración de tokens
async function fetchWithAuth(url, options = {}) {
    let token = await getAuthTokenPromise();
    if (!token) throw new Error('No autorizado');

    options.headers = options.headers || {};
    options.headers['Authorization'] = `Bearer ${token}`;

    let response = await fetch(url, options);

    if (response.status === 401) {
        cachedAccessToken = null;
        // Remover token caducado de la caché de Chrome
        await new Promise((resolve) => {
            chrome.identity.removeCachedAuthToken({ token: token }, resolve);
        });

        // Intentar obtener un token nuevo
        token = await getAuthTokenPromise();
        if (token) {
            options.headers['Authorization'] = `Bearer ${token}`;
            response = await fetch(url, options);
        }
    }
    return response;
}

// Actualizar la interfaz de usuario de Google Calendar
function updateGCalUI() {
    const statusText = document.getElementById('gcal-status-text');
    const connectBtn = document.getElementById('gcal-connect-btn');
    const calListContainer = document.getElementById('gcal-calendars-list');
    const destSelect = document.getElementById('gcal-dest-select');
    const syncControls = document.getElementById('gcal-sync-controls');

    const isEdge = navigator.userAgent.includes('Edg/');

    if (isEdge) {
        if (statusText) {
            statusText.innerText = 'No disponible en Microsoft Edge (API nativa no soportada)';
            statusText.className = 'sync-status disconnected';
            statusText.style.color = '#ff7675';
        }
        if (connectBtn) {
            connectBtn.innerText = 'No soportado en Edge';
            connectBtn.className = 'ag-btn ag-btn-danger';
            connectBtn.disabled = true;
            connectBtn.style.opacity = '0.5';
            connectBtn.style.cursor = 'not-allowed';
            connectBtn.onclick = null;
        }
        if (syncControls) {
            syncControls.style.display = 'none';
        }
        return;
    }

    if (statusText) {
        statusText.innerText = gcalState.connected ? 'Conectado a Google Calendar' : 'Desconectado';
        statusText.className = gcalState.connected ? 'sync-status connected' : 'sync-status disconnected';
    }

    if (connectBtn) {
        connectBtn.innerText = gcalState.connected ? 'Desconectar' : 'Conectar Google Calendar';
        connectBtn.className = gcalState.connected ? 'ag-btn ag-btn-danger' : 'ag-btn ag-btn-primary';
        connectBtn.onclick = gcalState.connected ? signOutGCalendar : signInGCalendar;
    }

    const agendaPublishBtn = document.getElementById('agenda-publish-gcal-btn');
    if (agendaPublishBtn) {
        agendaPublishBtn.style.display = gcalState.connected ? 'inline-block' : 'none';
        agendaPublishBtn.onclick = () => {
            if (window.state && window.state.reminders) {
                publishAllRemindersToGCal(window.state.reminders);
            }
        };
    }

    const configPublishBtn = document.getElementById('gcal-publish-all-btn');
    if (configPublishBtn) {
        configPublishBtn.onclick = () => {
            if (window.state && window.state.reminders) {
                publishAllRemindersToGCal(window.state.reminders);
            }
        };
    }

    if (syncControls) {
        syncControls.style.display = gcalState.connected ? 'block' : 'none';
    }

    // Renderizar lista de calendarios con checkboxes
    if (calListContainer) {
        calListContainer.innerHTML = '';
        if (gcalState.calendars.length === 0 && gcalState.connected) {
            if (gcalState.syncing) {
                calListContainer.innerHTML = '<div style="font-size:0.8rem; color:var(--ag-text-muted);">Cargando calendarios...</div>';
            } else {
                calListContainer.innerHTML = '<div style="font-size:0.82rem; color:#ff7675; cursor:pointer; text-decoration:underline;" onclick="fetchGCalendars()">Error al cargar calendarios. Clic aquí para reintentar.</div>';
            }
        } else {
            gcalState.calendars.forEach(cal => {
                const label = document.createElement('label');
                label.className = 'gcal-list-item';
                label.style.display = 'flex';
                label.style.alignItems = 'center';
                label.style.gap = '8px';
                label.style.fontSize = '0.82rem';
                label.style.margin = '6px 0';
                label.style.cursor = 'pointer';

                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.checked = !!cal.selected;
                checkbox.style.margin = '0';
                checkbox.onchange = () => {
                    cal.selected = checkbox.checked;
                    chrome.storage.local.set({ gcal_selected_calendars: gcalState.calendars }, () => {
                        fetchGCalEvents();
                    });
                };

                const textSpan = document.createElement('span');
                textSpan.innerText = cal.summary + (cal.isPrimary ? ' (Principal)' : '');

                label.appendChild(checkbox);
                label.appendChild(textSpan);
                calListContainer.appendChild(label);
            });
        }
    }

    // Renderizar selector de destino
    if (destSelect) {
        destSelect.innerHTML = '';
        gcalState.calendars.forEach(cal => {
            const opt = document.createElement('option');
            opt.value = cal.id;
            opt.innerText = cal.summary;
            opt.selected = cal.id === gcalState.destinationCalendarId;
            destSelect.appendChild(opt);
        });

        destSelect.onchange = () => {
            gcalState.destinationCalendarId = destSelect.value;
            chrome.storage.local.set({ gcal_destination_calendar: gcalState.destinationCalendarId });
        };
    }

    // Refrescar listado para mostrar/ocultar botones individuales
    if (window.renderReminders) {
        window.renderReminders();
    }
}

// Exponer funciones y variables al ámbito global
window.initGCalendarSync = initGCalendarSync;
window.gcalState = gcalState;
window.signInGCalendar = signInGCalendar;
window.signOutGCalendar = signOutGCalendar;
window.updateGCalUI = updateGCalUI;
window.publishReminderToGCal = publishReminderToGCal;
window.publishAllRemindersToGCal = publishAllRemindersToGCal;
window.fetchGCalEvents = fetchGCalEvents;
window.fetchGCalendars = fetchGCalendars;

document.addEventListener('DOMContentLoaded', () => {
    initGCalendarSync();
});
