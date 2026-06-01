// ============================================================
// agenda.js - Agenda completa (PyQt + QWebChannel + SQLite)
// ============================================================

let py = null;
let pw = null;
const PAGE_SIZE = 20;

const state = {
    reminders: [],
    shopping: [],
    income: [],
    kanbanSearch: '',
    kbEditingId: null,
    kbModalStatus: 'pending',
    kbSelectedLabels: new Set(),
    kbAvailableLabels: [],
    kbActiveLabel: null,
    notes: [],
    passwords: [],
    exchangeRate: 7.8,
    paymentMethods: ['Efectivo', 'Tarjeta', 'Transferencia'],
    page: {
        reminders: 1,
        shopping: 1,
        income: 1
    },
    cfg: {
        videoEnabled: true,
        imagesEnabled: true,
        shoppingEnabled: true,
        incomeEnabled: true,
        kanbanEnabled: true,
        notesEnabled: true,
        arcadeEnabled: true,
        homeUrl: '',
        mediaPath: '',
        videoStartMuted: false,
        videoSortBy: 'name-asc',
        imageMediaPath: '',
        imageSortBy: 'name-asc',
        screenshotsPath: ''
    },
    editModal: {
        mode: null,
        id: null
    },
    pmDraft: [],
    cfgBrowseMode: 'video',
    cfgBrowsingPath: '',
    pwSearch: '',
    pwFilter: 'all',
    pwShowSet: new Set(),
    pwEditId: null,
    pwAutoSavePolicy: 'ask',
    kbModalStatus: 'pending'
};

const DB_LARAVEL_TEMPLATE = {
    site: 'Fundascout DB (Laravel)',
    url: 'https://test.merke.net/fundascout/',
    dbPort: '3306',
    dbName: 'fundascout',
    dbType: 'mysql',
    username: 'perry',
    password: 'password',
    notes: `APP_NAME=Laravel
APP_ENV=production
APP_URL=https://test.merke.net/fundascout/

DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=fundascout
DB_USERNAME=perry
DB_PASSWORD=password`
};

const DB_NOTE_KEYS = ['DB_CONNECTION', 'DB_PORT', 'DB_DATABASE'];

const MODULE_META = {
    shopping: { cfgKey: 'shoppingEnabled', tab: 'shopping' },
    income: { cfgKey: 'incomeEnabled', tab: 'income' },
    kanban: { cfgKey: 'kanbanEnabled', tab: 'kanban' },
    notes: { cfgKey: 'notesEnabled', tab: 'notes' }
};

new QWebChannel(qt.webChannelTransport, (channel) => {
    window.py = channel.objects.py;
    window.pw = channel.objects.pw;
    py = window.py;
    pw = window.pw;
    initApp();
});

async function initApp() {
    bindStaticEvents();
    setupWindowControls();
    renderMainCalendarIcon();

    await loadAppConfig();

    const preferredTab = localStorage.getItem('lastAgendaTab') || 'agenda';
    activateTab(preferredTab);
}

function bindStaticEvents() {
    document.querySelectorAll('.ag-tab').forEach((tab) => {
        tab.addEventListener('click', () => activateTab(tab.dataset.tab));
    });

    const cfgBtn = document.getElementById('btn-config');
    if (cfgBtn) cfgBtn.onclick = () => activateTab('config');

    const addReminderBtn = document.getElementById('add-reminder-btn');
    if (addReminderBtn) addReminderBtn.onclick = addReminder;

    const addShopBtn = document.getElementById('add-shop-btn');
    if (addShopBtn) addShopBtn.onclick = addShopping;

    const addIncomeBtn = document.getElementById('add-income-btn');
    if (addIncomeBtn) addIncomeBtn.onclick = addIncome;

    const notesNewBtn = document.getElementById('notes-new-btn');
    if (notesNewBtn) notesNewBtn.onclick = addNote;

    const cfgSaveBtn = document.getElementById('cfg-save-btn');
    if (cfgSaveBtn) cfgSaveBtn.onclick = saveAppConfig;

    const editSaveBtn = document.getElementById('edit-save-btn');
    if (editSaveBtn) editSaveBtn.onclick = saveEdit;

    const editCancelBtn = document.getElementById('edit-cancel-btn');
    if (editCancelBtn) editCancelBtn.onclick = () => hideEditModal();

    bindPasteButtons();
    bindConfigEvents();
    bindPaymentMethodsEvents();
    bindKanbanEvents();
    bindPasswordEvents();

    window.onclick = (e) => {
        if (e.target.classList.contains('edit-modal-overlay') || e.target.classList.contains('pm-modal-overlay') || e.target.classList.contains('kb-modal-overlay') || e.target.classList.contains('pw-modal-overlay')) {
            e.target.classList.remove('active');
        }
    };
}

function setupWindowControls() {
    const minBtn = document.getElementById('btn-minimize');
    const maxBtn = document.getElementById('btn-maximize');
    const closeBtn = document.getElementById('btn-close');

    if (minBtn) minBtn.onclick = () => py.window_minimize();
    if (maxBtn) maxBtn.onclick = () => py.window_maximize();
    if (closeBtn) closeBtn.onclick = () => py.window_close();
}

function renderMainCalendarIcon() {
    const iconContainer = document.getElementById('main-calendar-icon');
    if (!iconContainer) return;

    const now = new Date();
    const month = now.toLocaleDateString('es-ES', { month: 'short' }).toUpperCase();
    const day = now.getDate();

    iconContainer.className = 'calendar-icon';
    iconContainer.innerHTML = `<div class="cal-month">${month}</div><div class="cal-day">${day}</div>`;
}

function bindPasteButtons() {
    bindPasteButton('paste-reminder', 'new-reminder-input');
    bindPasteButton('paste-shop-item', 'shop-item-input');
    bindPasteButton('cfg-paste-home-url', 'cfg-home-url');
}

function bindPasteButton(btnId, inputId) {
    const btn = document.getElementById(btnId);
    const input = document.getElementById(inputId);
    if (!btn || !input) return;

    btn.addEventListener('click', async () => {
        try {
            const clip = await navigator.clipboard.readText();
            input.value = clip || '';
        } catch (_err) {
            notify('No se pudo leer el portapapeles', 'info');
        }
    });
}

function bindConfigEvents() {
    const cfgToggleIds = [
        'cfg-video-enabled',
        'cfg-images-enabled',
        'cfg-shopping-enabled',
        'cfg-income-enabled',
        'cfg-kanban-enabled',
        'cfg-notes-enabled',
        'cfg-arcade-enabled'
    ];

    cfgToggleIds.forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('change', () => {
            syncCfgFromInputs();
            applyModuleFilters();
        });
    });

    const browseVideoBtn = document.getElementById('cfg-browse-folder');
    if (browseVideoBtn) {
        browseVideoBtn.addEventListener('click', () => openCfgFolderBrowser('video'));
    }

    const browseImageBtn = document.getElementById('cfg-image-browse-folder');
    if (browseImageBtn) {
        browseImageBtn.addEventListener('click', () => openCfgFolderBrowser('image'));
    }

    const browseScreenshotsBtn = document.getElementById('cfg-screenshots-browse-folder');
    if (browseScreenshotsBtn) {
        browseScreenshotsBtn.addEventListener('click', () => openCfgFolderBrowser('screenshots'));
    }

    const closeBtn = document.getElementById('cfg-folder-close');
    const cancelBtn = document.getElementById('cfg-folder-cancel');
    const selectBtn = document.getElementById('cfg-folder-select');

    if (closeBtn) closeBtn.addEventListener('click', closeCfgFolderBrowser);
    if (cancelBtn) cancelBtn.addEventListener('click', closeCfgFolderBrowser);
    if (selectBtn) {
        selectBtn.addEventListener('click', () => {
            if (state.cfgBrowseMode === 'image') {
                const imageInput = document.getElementById('cfg-image-media-path');
                if (imageInput) imageInput.value = state.cfgBrowsingPath;
            } else if (state.cfgBrowseMode === 'screenshots') {
                const screenshotsInput = document.getElementById('cfg-screenshots-path');
                if (screenshotsInput) screenshotsInput.value = state.cfgBrowsingPath;
            } else {
                const videoInput = document.getElementById('cfg-media-path');
                if (videoInput) videoInput.value = state.cfgBrowsingPath;
            }
            closeCfgFolderBrowser();
        });
    }
}

function bindPaymentMethodsEvents() {
    const pmModal = document.getElementById('pm-modal');
    const openBtn = document.getElementById('btn-payment-methods');
    const cancelBtn = document.getElementById('pm-cancel-btn');
    const saveBtn = document.getElementById('pm-save-btn');
    const addBtn = document.getElementById('pm-add-method-btn');
    const newInput = document.getElementById('pm-new-method-input');

    if (openBtn) openBtn.addEventListener('click', openPmModal);
    if (cancelBtn) cancelBtn.addEventListener('click', () => pmModal?.classList.remove('active'));
    if (saveBtn) saveBtn.addEventListener('click', savePmModal);
    if (addBtn) addBtn.addEventListener('click', addPmDraft);

    if (newInput) {
        newInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') addPmDraft();
        });
    }
}

function bindKanbanEvents() {
    const kbSearch = document.getElementById('kb-search');
    if (kbSearch) {
        kbSearch.addEventListener('input', async (e) => {
            state.kanbanSearch = (e.target.value || '').toLowerCase();
            await fetchKanban();
        });
    }

    document.querySelectorAll('.kb-col-add').forEach((btn) => {
        btn.onclick = () => {
            const status = btn.dataset.status || 'pending';
            openKanbanModal(status);
        };
    });

    const kbCancelBtn = document.getElementById('kb-modal-cancel');
    const kbSaveBtn = document.getElementById('kb-modal-save');
    const kbAddLabelBtn = document.getElementById('kb-add-label-btn');
    const kbLinkInsertBtn = document.getElementById('kb-link-insert');
    const kbLinkCancelBtn = document.getElementById('kb-link-cancel');
    const kbLinkUrlInput = document.getElementById('kb-link-url');
    const kbLinkLabelInput = document.getElementById('kb-link-label');
    const kbDescTools = document.querySelectorAll('.kb-desc-tool');
    kbBindToolbarSync();
    kbBindModalSizeSync();

    if (kbCancelBtn) kbCancelBtn.onclick = () => closeKanbanModal();
    if (kbSaveBtn) kbSaveBtn.onclick = saveKanbanCard;
    if (kbAddLabelBtn) kbAddLabelBtn.onclick = () => {
        const input = document.getElementById('kb-new-label-input');
        if (!input || !input.value.trim()) return;
        const newLabel = input.value.trim();
        if (!state.kbAvailableLabels.includes(newLabel)) {
            state.kbAvailableLabels.push(newLabel);
        }
        state.kbSelectedLabels.add(newLabel);
        input.value = '';
        renderKbLabelSelector();
    };

    kbDescTools.forEach((btn) => {
        btn.addEventListener('mousedown', (e) => {
            e.preventDefault();
        });
    });

    if (kbLinkInsertBtn) kbLinkInsertBtn.onclick = kbInsertLinkFromPopover;
    if (kbLinkCancelBtn) kbLinkCancelBtn.onclick = kbCloseLinkPopover;

    if (kbLinkUrlInput) {
        kbLinkUrlInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                kbInsertLinkFromPopover();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                kbCloseLinkPopover();
            }
        });
    }

    if (kbLinkLabelInput) {
        kbLinkLabelInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                kbInsertLinkFromPopover();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                kbCloseLinkPopover();
            }
        });
    }

    document.addEventListener('click', (e) => {
        const pop = document.getElementById('kb-link-popover');
        if (!pop || !pop.classList.contains('active')) return;

        const linkTool = document.getElementById('kb-link-tool-btn');
        if (pop.contains(e.target) || (linkTool && linkTool.contains(e.target))) return;
        kbCloseLinkPopover();
    });

    kbSyncDescToolbarState();
}

function bindPasswordEvents() {
    const search = document.getElementById('pw-search');
    const addBtn = document.getElementById('pw-add-btn');
    const cancelBtn = document.getElementById('pw-modal-cancel');
    const saveBtn = document.getElementById('pw-modal-save');
    const toggleBtn = document.getElementById('pw-modal-toggle');
    const genBtn = document.getElementById('pw-modal-gen');

    if (search) {
        search.addEventListener('input', (e) => {
            state.pwSearch = (e.target.value || '').toLowerCase();
            renderPasswords();
        });
    }

    document.querySelectorAll('.pw-filter').forEach((btn) => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.pw-filter').forEach((b) => b.classList.remove('active'));
            btn.classList.add('active');
            state.pwFilter = btn.dataset.filter || 'all';
            renderPasswords();
        });
    });

    if (addBtn) addBtn.addEventListener('click', () => openPasswordModal(null));
    if (cancelBtn) cancelBtn.addEventListener('click', closePasswordModal);
    if (saveBtn) saveBtn.addEventListener('click', savePassword);

    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            const input = document.getElementById('pw-password');
            if (!input) return;
            input.type = input.type === 'password' ? 'text' : 'password';
        });
    }

    if (genBtn) {
        genBtn.addEventListener('click', () => {
            const input = document.getElementById('pw-password');
            if (!input) return;
            input.value = generatePassword(16);
        });
    }

    document.querySelectorAll('.pw-type-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            setActivePwType(btn.dataset.type || 'web', true);
        });
    });

    const autoSavePolicySelect = document.getElementById('pw-autosave-policy-agenda');
    if (autoSavePolicySelect) {
        autoSavePolicySelect.addEventListener('change', async (e) => {
            if (!pw || typeof pw.set_auto_save_policy !== 'function') return;
            const nextPolicy = String(e.target.value || 'ask').toLowerCase();
            state.pwAutoSavePolicy = ['ask', 'always', 'never'].includes(nextPolicy) ? nextPolicy : 'ask';
            await pw.set_auto_save_policy(state.pwAutoSavePolicy);
            const label = state.pwAutoSavePolicy === 'always'
                ? 'Autoguardado: siempre'
                : state.pwAutoSavePolicy === 'never'
                    ? 'Autoguardado: nunca'
                    : 'Autoguardado: preguntar';
            notify(`${label}. Manual siempre permitido`, 'success');
        });
    }
}

function normalizePwType(type, site = '', notes = '') {
    const raw = String(type || '').trim().toLowerCase();
    if (raw === 'web' || raw === 'app' || raw === 'db') return raw;
    if (['database', 'base de datos', 'basedatos', 'base_de_datos'].includes(raw)) return 'db';
    const hint = `${site || ''}\n${notes || ''}`.toLowerCase();
    if (/(db_|database|mysql|postgres|sqlserver|sqlite|mariadb)/.test(hint)) return 'db';
    return String(site || '').includes('.') ? 'web' : 'app';
}

function getPwTypeLabel(type) {
    if (type === 'web') return 'WEB';
    if (type === 'app') return 'APP';
    return 'DB';
}

function getActivePwType() {
    return normalizePwType(document.querySelector('.pw-type-btn.active')?.dataset.type || 'web');
}

function canPrefillDbTemplate() {
    if (state.pwEditId) return false;
    const name = (document.getElementById('pw-name')?.value || '').trim();
    const url = (document.getElementById('pw-url')?.value || '').trim();
    const user = (document.getElementById('pw-username')?.value || '').trim();
    const pass = (document.getElementById('pw-password')?.value || '').trim();
    const notes = (document.getElementById('pw-notes')?.value || '').trim();
    const dbPort = (document.getElementById('pw-db-port')?.value || '').trim();
    const dbName = (document.getElementById('pw-db-name')?.value || '').trim();
    const dbType = (document.getElementById('pw-db-type')?.value || '').trim();
    return !name && !url && !user && !pass && !notes && !dbPort && !dbName && !dbType;
}

function parseDbFieldsFromNotes(notes) {
    const raw = String(notes || '');
    const pick = (key) => {
        const m = raw.match(new RegExp(`^${key}\\s*=\\s*(.+)$`, 'mi'));
        return m ? m[1].trim() : '';
    };
    const dbType = pick('DB_CONNECTION').toLowerCase();
    return {
        dbPort: pick('DB_PORT'),
        dbName: pick('DB_DATABASE'),
        dbType: dbType || ''
    };
}

function mergeDbFieldsIntoNotes(notes, dbFields) {
    const raw = String(notes || '');
    const lines = raw ? raw.split(/\r?\n/) : [];
    const filtered = lines.filter((line) => !DB_NOTE_KEYS.some((key) => new RegExp(`^${key}\\s*=`, 'i').test(line.trim())));

    const clean = filtered.join('\n').replace(/\n{3,}/g, '\n\n').trim();
    const out = [];
    if (clean) out.push(clean);
    if (dbFields.dbType) out.push(`DB_CONNECTION=${dbFields.dbType}`);
    if (dbFields.dbPort) out.push(`DB_PORT=${dbFields.dbPort}`);
    if (dbFields.dbName) out.push(`DB_DATABASE=${dbFields.dbName}`);
    return out.join('\n').trim();
}

function fillDbFields(values) {
    const dbPort = document.getElementById('pw-db-port');
    const dbName = document.getElementById('pw-db-name');
    const dbType = document.getElementById('pw-db-type');
    if (dbPort) dbPort.value = values.dbPort || '';
    if (dbName) dbName.value = values.dbName || '';
    if (dbType) {
        const nextType = (values.dbType || '').toLowerCase();
        const exists = Array.from(dbType.options || []).some((opt) => opt.value === nextType);
        dbType.value = exists ? nextType : 'other';
    }
}

function maybePrefillDbTemplate() {
    if (!canPrefillDbTemplate()) return;
    const name = document.getElementById('pw-name');
    const url = document.getElementById('pw-url');
    const user = document.getElementById('pw-username');
    const pass = document.getElementById('pw-password');
    const notes = document.getElementById('pw-notes');

    if (name) name.value = DB_LARAVEL_TEMPLATE.site;
    if (url) url.value = DB_LARAVEL_TEMPLATE.url;
    if (user) user.value = DB_LARAVEL_TEMPLATE.username;
    if (pass) pass.value = DB_LARAVEL_TEMPLATE.password;
    if (notes) notes.value = DB_LARAVEL_TEMPLATE.notes;
    fillDbFields(DB_LARAVEL_TEMPLATE);
}

function setActivePwType(rawType, allowDbPrefill = false) {
    const type = normalizePwType(rawType);
    document.querySelectorAll('.pw-type-btn').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.type === type);
    });

    const nameLabel = document.getElementById('pw-name-label');
    const userLabel = document.getElementById('pw-username-label');
    const nameInput = document.getElementById('pw-name');
    const userInput = document.getElementById('pw-username');
    const urlRow = document.getElementById('pw-url-row');
    const dbPortRow = document.getElementById('pw-db-port-row');
    const dbNameRow = document.getElementById('pw-db-name-row');
    const dbTypeRow = document.getElementById('pw-db-type-row');

    if (nameLabel) {
        nameLabel.textContent = type === 'web' ? 'Nombre *' : type === 'app' ? 'Aplicación *' : 'Servidor / Proyecto *';
    }
    if (userLabel) {
        userLabel.textContent = type === 'db' ? 'Usuario DB *' : 'Usuario / Correo *';
    }
    if (nameInput && !nameInput.value) {
        nameInput.placeholder = type === 'web' ? 'ej: Google, Netflix, Banco…' : type === 'app' ? 'ej: Steam, Photoshop…' : 'ej: Fundascout Producción';
    }
    if (userInput && !userInput.value) {
        userInput.placeholder = type === 'db' ? 'ej: root, perry' : 'usuario@ejemplo.com';
    }

    if (urlRow) {
        urlRow.style.display = (type === 'web' || type === 'db') ? '' : 'none';
    }
    if (dbPortRow) dbPortRow.style.display = type === 'db' ? '' : 'none';
    if (dbNameRow) dbNameRow.style.display = type === 'db' ? '' : 'none';
    if (dbTypeRow) dbTypeRow.style.display = type === 'db' ? '' : 'none';

    if (type === 'db' && allowDbPrefill) {
        maybePrefillDbTemplate();
    }
}

async function pwLoadAutoSavePolicy() {
    if (!pw || typeof pw.get_auto_save_policy !== 'function') return;
    try {
        const policy = String(await pw.get_auto_save_policy() || 'ask').toLowerCase();
        state.pwAutoSavePolicy = ['ask', 'always', 'never'].includes(policy) ? policy : 'ask';
    } catch (_err) {
        state.pwAutoSavePolicy = 'ask';
    }

    const autoSavePolicySelect = document.getElementById('pw-autosave-policy-agenda');
    if (autoSavePolicySelect) autoSavePolicySelect.value = state.pwAutoSavePolicy;
}

function notify(msg, type = 'success') {
    if (window.showToast) window.showToast(msg, type);
}

function toBool(v, fallback = true) {
    if (v === '' || v === null || v === undefined) return fallback;
    return v === '1' || v === 'true' || v === true;
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function fmtNum(n) {
    return Number(n || 0).toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

function pmBadgeClass(method) {
    if (!method) return 'pm-badge-default';
    const key = method.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    if (key === 'efectivo') return 'pm-badge-efectivo';
    if (key === 'tarjeta') return 'pm-badge-tarjeta';
    if (key.startsWith('transfer')) return 'pm-badge-transferencia';
    return 'pm-badge-default';
}

function parseJSON(value, fallback) {
    try {
        return JSON.parse(value);
    } catch (_err) {
        return fallback;
    }
}

function jsonStr(obj) {
    return JSON.stringify(obj).replace(/'/g, '&#39;');
}

function updateConfigHighlight(tabName) {
    const cfgBtn = document.getElementById('btn-config');
    if (cfgBtn) cfgBtn.style.color = tabName === 'config' ? '#a29bfe' : '';
}

function getTabFromCfgKey(cfgKey) {
    if (cfgKey === 'shoppingEnabled') return 'shopping';
    if (cfgKey === 'incomeEnabled') return 'income';
    if (cfgKey === 'kanbanEnabled') return 'kanban';
    if (cfgKey === 'notesEnabled') return 'notes';
    return '';
}

function isTabVisible(tabName) {
    if (tabName === 'shopping') return state.cfg.shoppingEnabled;
    if (tabName === 'income') return state.cfg.incomeEnabled;
    if (tabName === 'kanban') return state.cfg.kanbanEnabled;
    if (tabName === 'notes') return state.cfg.notesEnabled;
    return true;
}

function applyModuleFilters() {
    Object.values(MODULE_META).forEach((meta) => {
        const tabEl = document.querySelector(`.ag-tab[data-tab="${meta.tab}"]`);
        if (!tabEl) return;
        tabEl.style.display = state.cfg[meta.cfgKey] ? '' : 'none';
    });

    localStorage.setItem('deskio_app_settings', JSON.stringify({
        videoEnabled: state.cfg.videoEnabled,
        imagesEnabled: state.cfg.imagesEnabled,
        shoppingEnabled: state.cfg.shoppingEnabled,
        incomeEnabled: state.cfg.incomeEnabled,
        kanbanEnabled: state.cfg.kanbanEnabled,
        notesEnabled: state.cfg.notesEnabled,
        arcadeEnabled: state.cfg.arcadeEnabled,
        homeUrl: state.cfg.homeUrl
    }));

    const activeTab = document.querySelector('.ag-tab.active')?.dataset.tab;
    if (activeTab && !isTabVisible(activeTab)) {
        activateTab('agenda');
    }
}

function syncCfgFromInputs() {
    state.cfg.videoEnabled = !!document.getElementById('cfg-video-enabled')?.checked;
    state.cfg.imagesEnabled = !!document.getElementById('cfg-images-enabled')?.checked;
    state.cfg.shoppingEnabled = !!document.getElementById('cfg-shopping-enabled')?.checked;
    state.cfg.incomeEnabled = !!document.getElementById('cfg-income-enabled')?.checked;
    state.cfg.kanbanEnabled = !!document.getElementById('cfg-kanban-enabled')?.checked;
    state.cfg.notesEnabled = !!document.getElementById('cfg-notes-enabled')?.checked;
    state.cfg.arcadeEnabled = !!document.getElementById('cfg-arcade-enabled')?.checked;

    state.cfg.homeUrl = (document.getElementById('cfg-home-url')?.value || '').trim();
    state.cfg.mediaPath = (document.getElementById('cfg-media-path')?.value || '').trim();
    state.cfg.videoStartMuted = !!document.getElementById('cfg-start-muted')?.checked;
    state.cfg.videoSortBy = document.getElementById('cfg-sort-by')?.value || 'name-asc';

    state.cfg.imageMediaPath = (document.getElementById('cfg-image-media-path')?.value || '').trim();
    state.cfg.imageSortBy = document.getElementById('cfg-image-sort-by')?.value || 'name-asc';
    state.cfg.screenshotsPath = (document.getElementById('cfg-screenshots-path')?.value || '').trim();
}

async function loadAppConfig() {
    try {
        const [
            videoEnabled,
            imagesEnabled,
            shoppingEnabled,
            incomeEnabled,
            kanbanEnabled,
            notesEnabled,
            arcadeEnabled,
            homeUrl,
            mediaPath,
            videoStartMuted,
            videoSortBy,
            exchangeRate,
            paymentMethods,
            imageSettingsRaw,
            mediaPathResolved,
            screenshotsPath
        ] = await Promise.all([
            py.get_config('videoEnabled'),
            py.get_config('imagesEnabled'),
            py.get_config('shoppingEnabled'),
            py.get_config('incomeEnabled'),
            py.get_config('kanbanEnabled'),
            py.get_config('notesEnabled'),
            py.get_config('arcadeEnabled'),
            py.get_config('homeUrl'),
            py.get_config('mediaPath'),
            py.get_config('videoStartMuted'),
            py.get_config('videoSortBy'),
            py.get_config('exchangeRate'),
            py.get_config('paymentMethods'),
            py.get_image_settings(),
            py.get_media_path(),
            py.get_config('screenshotsPath')
        ]);

        state.cfg.videoEnabled = toBool(videoEnabled, true);
        state.cfg.imagesEnabled = toBool(imagesEnabled, true);
        state.cfg.shoppingEnabled = toBool(shoppingEnabled, true);
        state.cfg.incomeEnabled = toBool(incomeEnabled, true);
        state.cfg.kanbanEnabled = toBool(kanbanEnabled, true);
        state.cfg.notesEnabled = toBool(notesEnabled, true);
        state.cfg.arcadeEnabled = toBool(arcadeEnabled, true);

        state.cfg.homeUrl = homeUrl || '';
        state.cfg.mediaPath = mediaPath || mediaPathResolved || '';
        state.cfg.videoStartMuted = toBool(videoStartMuted, false);
        state.cfg.videoSortBy = videoSortBy || 'name-asc';

        state.exchangeRate = Number(exchangeRate) > 0 ? Number(exchangeRate) : 7.8;
        state.paymentMethods = parseJSON(paymentMethods, state.paymentMethods);
        if (!Array.isArray(state.paymentMethods) || state.paymentMethods.length === 0) {
            state.paymentMethods = ['Efectivo', 'Tarjeta', 'Transferencia'];
        }

        const imageSettings = parseJSON(imageSettingsRaw, {
            imageMediaPath: '',
            sortBy: 'name-asc'
        });
        state.cfg.imageMediaPath = imageSettings.imageMediaPath || '';
        state.cfg.imageSortBy = imageSettings.sortBy || 'name-asc';
        state.cfg.screenshotsPath = screenshotsPath || '';

        fillConfigInputs();
        populatePaymentMethodSelects();
        applyModuleFilters();
    } catch (err) {
        console.error('Error loading config:', err);
        notify('No se pudo cargar la configuracion', 'info');
    }
}

function fillConfigInputs() {
    const setChecked = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.checked = !!value;
    };

    setChecked('cfg-video-enabled', state.cfg.videoEnabled);
    setChecked('cfg-images-enabled', state.cfg.imagesEnabled);
    setChecked('cfg-shopping-enabled', state.cfg.shoppingEnabled);
    setChecked('cfg-income-enabled', state.cfg.incomeEnabled);
    setChecked('cfg-kanban-enabled', state.cfg.kanbanEnabled);
    setChecked('cfg-notes-enabled', state.cfg.notesEnabled);
    setChecked('cfg-arcade-enabled', state.cfg.arcadeEnabled);

    const cfgHomeUrl = document.getElementById('cfg-home-url');
    const cfgMediaPath = document.getElementById('cfg-media-path');
    const cfgStartMuted = document.getElementById('cfg-start-muted');
    const cfgSortBy = document.getElementById('cfg-sort-by');
    const cfgImagePath = document.getElementById('cfg-image-media-path');
    const cfgImageSort = document.getElementById('cfg-image-sort-by');
    const cfgScreenshotsPath = document.getElementById('cfg-screenshots-path');

    if (cfgHomeUrl) cfgHomeUrl.value = state.cfg.homeUrl;
    if (cfgMediaPath) cfgMediaPath.value = state.cfg.mediaPath;
    if (cfgStartMuted) cfgStartMuted.checked = state.cfg.videoStartMuted;
    if (cfgSortBy) cfgSortBy.value = state.cfg.videoSortBy;
    if (cfgImagePath) cfgImagePath.value = state.cfg.imageMediaPath;
    if (cfgImageSort) cfgImageSort.value = state.cfg.imageSortBy;
    if (cfgScreenshotsPath) cfgScreenshotsPath.value = state.cfg.screenshotsPath;

    const pmExchangeRate = document.getElementById('pm-exchange-rate');
    if (pmExchangeRate) pmExchangeRate.value = String(state.exchangeRate);
}

async function saveAppConfig() {
    try {
        syncCfgFromInputs();

        const writes = [
            py.set_config('videoEnabled', state.cfg.videoEnabled ? '1' : '0'),
            py.set_config('imagesEnabled', state.cfg.imagesEnabled ? '1' : '0'),
            py.set_config('shoppingEnabled', state.cfg.shoppingEnabled ? '1' : '0'),
            py.set_config('incomeEnabled', state.cfg.incomeEnabled ? '1' : '0'),
            py.set_config('kanbanEnabled', state.cfg.kanbanEnabled ? '1' : '0'),
            py.set_config('notesEnabled', state.cfg.notesEnabled ? '1' : '0'),
            py.set_config('arcadeEnabled', state.cfg.arcadeEnabled ? '1' : '0'),
            py.set_config('homeUrl', state.cfg.homeUrl),
            py.set_config('mediaPath', state.cfg.mediaPath),
            py.set_config('videoStartMuted', state.cfg.videoStartMuted ? '1' : '0'),
            py.set_config('videoSortBy', state.cfg.videoSortBy),
            py.set_config('imageMediaPath', state.cfg.imageMediaPath),
            py.set_config('imageSortBy', state.cfg.imageSortBy),
            py.set_config('screenshotsPath', state.cfg.screenshotsPath)
        ];

        await Promise.all(writes);
        applyModuleFilters();
        notify('Configuracion guardada', 'success');
    } catch (err) {
        console.error('Error saving config:', err);
        notify('No se pudo guardar la configuracion', 'info');
    }
}

async function openCfgFolderBrowser(mode) {
    const modal = document.getElementById('cfg-folder-modal');
    if (!modal) return;

    state.cfgBrowseMode = mode;

    const startPath = mode === 'image'
        ? (document.getElementById('cfg-image-media-path')?.value || '').trim()
        : mode === 'screenshots'
            ? (document.getElementById('cfg-screenshots-path')?.value || '').trim()
        : (document.getElementById('cfg-media-path')?.value || '').trim();

    try {
        let raw = '';
        if (mode === 'image' || mode === 'screenshots') raw = await py.browse_local_path(startPath);
        else raw = await py.browse_folders(startPath);

        const data = parseJSON(raw, {});
        if (data.error) {
            notify('No se pudo abrir el explorador', 'info');
            return;
        }

        renderCfgFolderBrowser(data);
        modal.classList.add('active');
    } catch (err) {
        console.error('Error browsing folders:', err);
        notify('Error al explorar carpetas', 'info');
    }
}

function renderCfgFolderBrowser(data) {
    const pathLabel = document.getElementById('cfg-folder-path');
    const list = document.getElementById('cfg-folder-list');
    if (!pathLabel || !list) return;

    state.cfgBrowsingPath = data.currentPath || '/';
    pathLabel.textContent = state.cfgBrowsingPath;
    pathLabel.title = state.cfgBrowsingPath;

    list.innerHTML = '';

    const parentItem = document.createElement('div');
    parentItem.className = 'cfg-folder-item parent';
    parentItem.innerHTML = '<span>⬆️</span><span>Subir un nivel</span>';
    parentItem.onclick = async () => {
        const raw = state.cfgBrowseMode === 'image'
            ? await py.browse_local_path(data.parentPath || state.cfgBrowsingPath)
            : await py.browse_folders(data.parentPath || state.cfgBrowsingPath);
        renderCfgFolderBrowser(parseJSON(raw, {}));
    };
    list.appendChild(parentItem);

    (data.folders || []).forEach((name) => {
        const row = document.createElement('div');
        row.className = 'cfg-folder-item';
        row.innerHTML = `<span>📁</span><span>${escapeHtml(name)}</span>`;
        row.onclick = async () => {
            const nextPath = `${state.cfgBrowsingPath.replace(/\/+$/, '')}/${name}`;
            const raw = state.cfgBrowseMode === 'image'
                ? await py.browse_local_path(nextPath)
                : await py.browse_folders(nextPath);
            renderCfgFolderBrowser(parseJSON(raw, {}));
        };
        list.appendChild(row);
    });
}

function closeCfgFolderBrowser() {
    const modal = document.getElementById('cfg-folder-modal');
    if (modal) modal.classList.remove('active');
}

function openEditModal(mode, item) {
    state.editModal.mode = mode;
    state.editModal.id = item.id;

    const title = document.getElementById('edit-modal-title');
    const text = document.getElementById('edit-text');
    const date = document.getElementById('edit-date');
    const valRow = document.getElementById('edit-value-row');
    const pmRow = document.getElementById('edit-payment-method-row');

    if (title) {
        if (mode === 'reminder') title.textContent = 'Editar tarea';
        else if (mode === 'shopping') title.textContent = 'Editar gasto';
        else title.textContent = 'Editar ingreso';
    }

    if (text) text.value = item.text || '';
    if (date) date.value = item.dueDate || '';

    if (mode === 'reminder') {
        if (valRow) valRow.style.display = 'none';
        if (pmRow) pmRow.style.display = 'none';
    } else {
        if (valRow) valRow.style.display = 'flex';
        const editValue = document.getElementById('edit-value');
        const editCurrency = document.getElementById('edit-currency');
        if (editValue) editValue.value = item.value || '';
        if (editCurrency) editCurrency.value = item.currency || 'Q';

        if (mode === 'shopping') {
            if (pmRow) pmRow.style.display = 'flex';
            populatePaymentMethodSelects();
            const editPayment = document.getElementById('edit-payment-method');
            if (editPayment) editPayment.value = item.paymentMethod || '';
        } else if (pmRow) {
            pmRow.style.display = 'none';
        }
    }

    document.getElementById('edit-modal')?.classList.add('active');
}

function hideEditModal() {
    document.getElementById('edit-modal')?.classList.remove('active');
}

async function saveEdit() {
    const mode = state.editModal.mode;
    const id = state.editModal.id;
    if (!mode || id === null) return;

    const text = (document.getElementById('edit-text')?.value || '').trim();
    const date = document.getElementById('edit-date')?.value || '';
    if (!text) return;

    try {
        if (mode === 'reminder') {
            await py.update_agenda(id, text, date || '');
            await fetchReminders(false);
        } else if (mode === 'shopping') {
            const val = parseFloat(document.getElementById('edit-value')?.value || '0') || 0;
            const cur = document.getElementById('edit-currency')?.value || 'Q';
            const pm = document.getElementById('edit-payment-method')?.value || '';
            await py.update_shopping(id, text, val, cur, date || '', pm);
            await fetchShoppingList(false);
        } else if (mode === 'income') {
            const val = parseFloat(document.getElementById('edit-value')?.value || '0') || 0;
            const cur = document.getElementById('edit-currency')?.value || 'Q';
            await py.update_income(id, text, val, cur, date || '');
            await fetchIncomeList(false);
        }

        hideEditModal();
        notify('Cambios guardados', 'success');
    } catch (err) {
        console.error('Error saving edit:', err);
        notify('No se pudo guardar', 'info');
    }
}

async function activateTab(tabName) {
    const target = isTabVisible(tabName) ? tabName : 'agenda';
    localStorage.setItem('lastAgendaTab', target);

    if (target === 'passwords' && py?.hide_browser_bar) {
        py.hide_browser_bar();
    }

    document.querySelectorAll('.ag-tab').forEach((t) => {
        t.classList.toggle('active', t.dataset.tab === target);
    });

    document.querySelectorAll('.ag-view').forEach((v) => {
        v.classList.toggle('active', v.id === `view-${target}`);
    });

    const kbSearch = document.getElementById('kb-search');
    if (kbSearch) kbSearch.style.display = target === 'kanban' ? '' : 'none';

    updateConfigHighlight(target);

    if (target === 'agenda') await fetchReminders();
    else if (target === 'shopping') await fetchShoppingList();
    else if (target === 'income') await fetchIncomeList();
    else if (target === 'kanban') await fetchKanban();
    else if (target === 'notes') await fetchNotes();
    else if (target === 'passwords') await pwLoad();
    else if (target === 'config') fillConfigInputs();
}

async function fetchReminders(resetPage = true) {
    if (resetPage) state.page.reminders = 1;

    try {
        state.reminders = await py.get_agenda();
        renderReminders();
    } catch (err) {
        console.error('Error fetching reminders:', err);
        document.getElementById('reminders-list').innerHTML = '<div class="ag-empty">Error al cargar tareas</div>';
    }
}

function renderReminders() {
    const list = document.getElementById('reminders-list');
    const pag = document.getElementById('reminders-pagination');
    if (!list || !pag) return;

    if (!state.reminders.length) {
        list.innerHTML = '<div class="ag-empty">No hay tareas pendientes</div>';
        pag.style.display = 'none';
        return;
    }

    const totalPages = Math.max(1, Math.ceil(state.reminders.length / PAGE_SIZE));
    if (state.page.reminders > totalPages) state.page.reminders = totalPages;

    const start = (state.page.reminders - 1) * PAGE_SIZE;
    const chunk = state.reminders.slice(start, start + PAGE_SIZE);

    list.innerHTML = '';
    chunk.forEach((r) => {
        const due = r.dueDate ? new Date(r.dueDate) : null;
        const dateStr = due ? due.toLocaleDateString('es', { day: '2-digit', month: 'short' }) : '';

        const row = document.createElement('div');
        row.className = `ag-item ${r.done ? 'ag-item-paid' : ''}`;
        row.innerHTML = `
            <button class="ag-check-btn ${r.done ? 'checked' : ''}" onclick="toggleReminder(${r.id}, ${r.done ? 'true' : 'false'})" title="Marcar completada">
                <span class="ag-check-box"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="white" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg></span>
            </button>
            <span class="ag-item-text">${escapeHtml(r.text)}</span>
            <div class="ag-item-meta">
                ${dateStr ? `<span class="ag-badge">📅 ${dateStr}</span>` : ''}
                <button class="ag-notes-btn ${r.notes ? 'has-notes' : ''}" onclick='openObsModal("agenda", ${r.id}, ${JSON.stringify(r.notes || '')})' title="Observaciones">📝</button>
                <button class="ag-edit-btn" onclick='openEditModal("reminder", ${jsonStr(r)})'>✏️</button>
                <button class="ag-delete-btn" onclick="deleteReminder(${r.id})">🗑️</button>
            </div>`;
        list.appendChild(row);
    });

    renderPagination(pag, state.page.reminders, totalPages, (next) => {
        state.page.reminders = next;
        renderReminders();
    });
}

function renderPagination(container, page, totalPages, onChange) {
    if (!container) return;
    if (totalPages <= 1) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';
    container.innerHTML = `
        <button class="ag-page-btn" ${page <= 1 ? 'disabled' : ''}>Anterior</button>
        <span class="ag-page-label">Pagina ${page} de ${totalPages}</span>
        <button class="ag-page-btn" ${page >= totalPages ? 'disabled' : ''}>Siguiente</button>`;

    const [prevBtn, , nextBtn] = container.children;
    prevBtn.onclick = () => onChange(Math.max(1, page - 1));
    nextBtn.onclick = () => onChange(Math.min(totalPages, page + 1));
}

async function addReminder() {
    const textEl = document.getElementById('new-reminder-input');
    const dateEl = document.getElementById('new-reminder-date');
    const txt = (textEl?.value || '').trim();
    const date = dateEl?.value || '';
    if (!txt) return;

    await py.add_agenda(txt, date);
    if (textEl) textEl.value = '';
    notify('Tarea guardada', 'success');
    fetchReminders();
}

async function toggleReminder(id, currentDone) {
    await py.toggle_agenda(id, !currentDone);
    fetchReminders(false);
}

async function deleteReminder(id) {
    window.showConfirm('¿Borrar esta tarea?', async (ok) => {
        if (!ok) return;
        await py.delete_agenda(id);
        fetchReminders(false);
    });
}

async function fetchShoppingList(resetPage = true) {
    if (resetPage) state.page.shopping = 1;

    try {
        const [shopping, exchangeRate, paymentMethods, income] = await Promise.all([
            py.get_shopping(),
            py.get_config('exchangeRate'),
            py.get_config('paymentMethods'),
            py.get_income()
        ]);

        state.shopping = shopping || [];
        state.income = income || [];

        const ex = Number(exchangeRate);
        state.exchangeRate = ex > 0 ? ex : 7.8;

        const pm = parseJSON(paymentMethods, state.paymentMethods);
        state.paymentMethods = Array.isArray(pm) && pm.length ? pm : ['Efectivo', 'Tarjeta', 'Transferencia'];

        populatePaymentMethodSelects();
        renderShopping();
    } catch (err) {
        console.error('Error fetching shopping:', err);
        document.getElementById('shopping-list').innerHTML = '<div class="ag-empty">Error al cargar gastos</div>';
    }
}

function populatePaymentMethodSelects() {
    ['shop-payment-method-select', 'edit-payment-method'].forEach((id) => {
        const sel = document.getElementById(id);
        if (!sel) return;

        const prev = sel.value;
        sel.innerHTML = '<option value="">Sin asignar</option>';
        state.paymentMethods.forEach((method) => {
            const opt = document.createElement('option');
            opt.value = method;
            opt.textContent = method;
            sel.appendChild(opt);
        });

        if (prev && state.paymentMethods.includes(prev)) sel.value = prev;
    });
}

function renderShopping() {
    const list = document.getElementById('shopping-list');
    const pag = document.getElementById('shopping-pagination');
    if (!list || !pag) return;

    if (!state.shopping.length) {
        list.innerHTML = '<div class="ag-empty">No hay gastos registrados</div>';
        pag.style.display = 'none';
        renderShoppingTotals();
        renderPaymentSummary();
        return;
    }

    const totalPages = Math.max(1, Math.ceil(state.shopping.length / PAGE_SIZE));
    if (state.page.shopping > totalPages) state.page.shopping = totalPages;

    const start = (state.page.shopping - 1) * PAGE_SIZE;
    const chunk = state.shopping.slice(start, start + PAGE_SIZE);

    list.innerHTML = '';
    chunk.forEach((r) => {
        const row = document.createElement('div');
        row.className = `ag-item ${r.done ? 'ag-item-paid' : ''}`;
        row.innerHTML = `
            <button class="ag-check-btn ${r.done ? 'checked' : ''}" onclick="toggleShopping(${r.id}, ${r.done ? 'true' : 'false'})" title="Marcar pagado">
                <span class="ag-check-box"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="white" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg></span>
            </button>
            <span class="ag-item-text">${escapeHtml(r.text)}</span>
            <div class="ag-item-meta">
                <span style="font-weight:700; color:#ff7f50;">${r.currency}${fmtNum(r.value)}</span>
                <span class="pm-badge ${pmBadgeClass(r.paymentMethod)}">${escapeHtml(r.paymentMethod || 'Pendiente')}</span>
                <button class="ag-notes-btn ${r.notes ? 'has-notes' : ''}" onclick='openObsModal("shopping", ${r.id}, ${JSON.stringify(r.notes || '')})' title="Observaciones">📝</button>
                <button class="ag-edit-btn" onclick='openEditModal("shopping", ${jsonStr(r)})'>✏️</button>
                <button class="ag-delete-btn" onclick="deleteShopping(${r.id})">🗑️</button>
            </div>`;
        list.appendChild(row);
    });

    renderPagination(pag, state.page.shopping, totalPages, (next) => {
        state.page.shopping = next;
        renderShopping();
    });

    renderShoppingTotals();
    renderPaymentSummary();
}

function renderShoppingTotals() {
    let expQ = 0;
    let expD = 0;
    state.shopping.forEach((r) => {
        if (r.done) return;
        if (r.currency === '$') expD += Number(r.value || 0);
        else expQ += Number(r.value || 0);
    });

    let incQ = 0;
    let incD = 0;
    state.income.forEach((r) => {
        if (r.received) return;
        if (r.currency === '$') incD += Number(r.value || 0);
        else incQ += Number(r.value || 0);
    });

    const setTxt = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = fmtNum(value);
    };

    setTxt('total-gtq', expQ);
    setTxt('total-usd', expD);
    setTxt('total-income-gtq', incQ);
    setTxt('total-income-usd', incD);
    setTxt('income-mini-gtq', incQ);
    setTxt('income-mini-usd', incD);

    const net = (incQ + incD * state.exchangeRate) - (expQ + expD * state.exchangeRate);
    const combined = document.getElementById('total-combined');
    if (combined) {
        combined.textContent = `Q ${fmtNum(net)}`;
        combined.classList.remove('saldo-positive', 'saldo-negative');
        combined.classList.add(net >= 0 ? 'saldo-positive' : 'saldo-negative');
    }
}

function renderPaymentSummary() {
    const box = document.getElementById('payment-summary');
    if (!box) return;

    const sums = {};
    state.shopping.forEach((item) => {
        if (item.done) return;
        const key = item.paymentMethod || 'Sin asignar';
        if (!sums[key]) sums[key] = { Q: 0, USD: 0 };
        if (item.currency === '$') sums[key].USD += Number(item.value || 0);
        else sums[key].Q += Number(item.value || 0);
    });

    const methods = Object.keys(sums);
    if (!methods.length) {
        box.style.display = 'none';
        box.innerHTML = '';
        return;
    }

    box.style.display = 'block';
    box.innerHTML = `<div class="payment-summary-title">Resumen por metodo de pago</div>${methods.map((method) => `
        <div class="payment-summary-row">
            <div class="payment-summary-label">${escapeHtml(method)}</div>
            <div class="payment-summary-amount gtq">Q ${fmtNum(sums[method].Q)}</div>
            <div class="payment-summary-amount usd">$ ${fmtNum(sums[method].USD)}</div>
        </div>`).join('')}`;
}

async function addShopping() {
    const text = (document.getElementById('shop-item-input')?.value || '').trim();
    const val = parseFloat(document.getElementById('shop-value-input')?.value || '');
    const cur = document.getElementById('shop-currency-select')?.value || 'Q';
    const pm = document.getElementById('shop-payment-method-select')?.value || '';
    const date = document.getElementById('shop-date-input')?.value || '';

    if (!text || Number.isNaN(val)) return;

    await py.add_shopping(text, val, cur, date, pm);

    document.getElementById('shop-item-input').value = '';
    document.getElementById('shop-value-input').value = '';
    notify('Gasto registrado', 'success');
    fetchShoppingList();
}

async function toggleShopping(id, currentDone) {
    await py.toggle_shopping(id, !currentDone);
    fetchShoppingList(false);
}

async function deleteShopping(id) {
    window.showConfirm('¿Borrar gasto?', async (ok) => {
        if (!ok) return;
        await py.delete_shopping(id);
        fetchShoppingList(false);
    });
}

async function fetchIncomeList(resetPage = true) {
    if (resetPage) state.page.income = 1;

    try {
        state.income = await py.get_income();
        renderIncome();
    } catch (err) {
        console.error('Error fetching income:', err);
        document.getElementById('income-list').innerHTML = '<div class="ag-empty">Error al cargar ingresos</div>';
    }
}

function renderIncome() {
    const list = document.getElementById('income-list');
    const pag = document.getElementById('income-pagination');
    if (!list || !pag) return;

    if (!state.income.length) {
        list.innerHTML = '<div class="ag-empty">No hay ingresos registrados</div>';
        pag.style.display = 'none';
        renderShoppingTotals();
        return;
    }

    const totalPages = Math.max(1, Math.ceil(state.income.length / PAGE_SIZE));
    if (state.page.income > totalPages) state.page.income = totalPages;

    const start = (state.page.income - 1) * PAGE_SIZE;
    const chunk = state.income.slice(start, start + PAGE_SIZE);

    list.innerHTML = '';
    chunk.forEach((r) => {
        const row = document.createElement('div');
        row.className = `ag-item income-item ${r.received ? 'received' : ''}`;
        row.innerHTML = `
            <button class="ag-check-btn ${r.received ? 'checked' : ''}" onclick="toggleIncome(${r.id}, ${r.received ? 'true' : 'false'})" title="Marcar recibido">
                <span class="ag-check-box"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="white" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg></span>
            </button>
            <span class="ag-item-text">${escapeHtml(r.text)}</span>
            <div class="ag-item-meta">
                <span style="font-weight:700; color:#2ed573;">${r.currency}${fmtNum(r.value)}</span>
                <button class="ag-notes-btn ${r.notes ? 'has-notes' : ''}" onclick='openObsModal("income", ${r.id}, ${JSON.stringify(r.notes || '')})' title="Observaciones">📝</button>
                <button class="ag-edit-btn" onclick='openEditModal("income", ${jsonStr(r)})'>✏️</button>
                <button class="ag-delete-btn" onclick="deleteIncome(${r.id})">🗑️</button>
            </div>`;
        list.appendChild(row);
    });

    renderPagination(pag, state.page.income, totalPages, (next) => {
        state.page.income = next;
        renderIncome();
    });

    renderShoppingTotals();
}

async function addIncome() {
    const text = (document.getElementById('income-item-input')?.value || '').trim();
    const val = parseFloat(document.getElementById('income-value-input')?.value || '');
    const cur = document.getElementById('income-currency-select')?.value || 'Q';
    const date = document.getElementById('income-date-input')?.value || '';

    if (!text || Number.isNaN(val)) return;

    await py.add_income(text, val, cur, date);
    document.getElementById('income-item-input').value = '';
    document.getElementById('income-value-input').value = '';
    notify('Ingreso registrado', 'success');
    fetchIncomeList();
}

async function toggleIncome(id, currentReceived) {
    await py.toggle_income(id, !currentReceived);
    fetchIncomeList(false);
}

async function deleteIncome(id) {
    window.showConfirm('¿Borrar ingreso?', async (ok) => {
        if (!ok) return;
        await py.delete_income(id);
        fetchIncomeList(false);
    });
}

function openPmModal() {
    state.pmDraft = [...state.paymentMethods];
    renderPmList();
    const input = document.getElementById('pm-new-method-input');
    if (input) input.value = '';

    const rateInput = document.getElementById('pm-exchange-rate');
    if (rateInput) rateInput.value = String(state.exchangeRate);

    document.getElementById('pm-modal')?.classList.add('active');
}

function renderPmList() {
    const list = document.getElementById('pm-method-list');
    if (!list) return;

    if (!state.pmDraft.length) {
        list.innerHTML = '<div style="color:#777; font-size:0.86rem;">Sin metodos definidos</div>';
        return;
    }

    list.innerHTML = state.pmDraft.map((m, idx) => `
        <div class="pm-method-item">
            <span>${escapeHtml(m)}</span>
            <div class="pm-method-actions">
                <button class="pm-remove-btn" onclick="removePmDraft(${idx})" title="Eliminar">🗑️</button>
            </div>
        </div>`).join('');
}

function addPmDraft() {
    const input = document.getElementById('pm-new-method-input');
    if (!input) return;
    const val = (input.value || '').trim();
    if (!val || state.pmDraft.includes(val)) return;

    state.pmDraft.push(val);
    input.value = '';
    renderPmList();
}

function removePmDraft(index) {
    state.pmDraft.splice(index, 1);
    renderPmList();
}

async function savePmModal() {
    const rateInput = document.getElementById('pm-exchange-rate');
    const newRate = Number(rateInput?.value || 0);
    state.exchangeRate = newRate > 0 ? newRate : state.exchangeRate;

    state.paymentMethods = state.pmDraft.length ? [...state.pmDraft] : ['Efectivo', 'Tarjeta', 'Transferencia'];
    await py.set_config('paymentMethods', JSON.stringify(state.paymentMethods));
    await py.set_config('exchangeRate', String(state.exchangeRate));

    populatePaymentMethodSelects();
    document.getElementById('pm-modal')?.classList.remove('active');
    notify('Metodos de pago guardados', 'success');

    if (document.getElementById('view-shopping')?.classList.contains('active')) {
        fetchShoppingList(false);
    }
}

function parseKanbanCardText(text) {
    // Formato: Title | Description | Vence: YYYY-MM-DD | Prioridad: high|medium|low | Etiquetas: tag1, tag2
    const parts = (text || '').split(' | ').map(p => p.trim());
    const result = { title: '', description: '', due: '', priority: 'medium', labels: [] };
    const descParts = [];
    let titleSet = false;
    
    for (const part of parts) {
        if (part.startsWith('Vence: ')) {
            result.due = part.replace('Vence: ', '');
        } else if (part.startsWith('Prioridad: ')) {
            const p = part.replace('Prioridad: ', '').toLowerCase();
            if (['high', 'medium', 'low'].includes(p)) result.priority = p;
        } else if (part.startsWith('Etiquetas: ')) {
            const labels = part.replace('Etiquetas: ', '').split(',').map(l => l.trim()).filter(l => l);
            result.labels = labels;
        } else if (!titleSet) {
            result.title = part;
            titleSet = true;
        } else {
            descParts.push(part);
        }
    }

    result.description = descParts.join(' | ');
    return result;
}

function sanitizeKbHtml(raw) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(`<div>${raw || ''}</div>`, 'text/html');
    const root = doc.body.firstElementChild;
    if (!root) return '';

    const allowedTags = new Set(['B', 'STRONG', 'I', 'EM', 'U', 'S', 'CODE', 'BR', 'UL', 'OL', 'LI', 'A', 'DIV', 'P']);

    const cleanNode = (node) => {
        if (node.nodeType === Node.TEXT_NODE) {
            return doc.createTextNode(node.textContent || '');
        }

        if (node.nodeType !== Node.ELEMENT_NODE) {
            return doc.createTextNode('');
        }

        const tag = (node.tagName || '').toUpperCase();
        if (!allowedTags.has(tag)) {
            const frag = doc.createDocumentFragment();
            Array.from(node.childNodes).forEach((child) => frag.appendChild(cleanNode(child)));
            return frag;
        }

        const el = doc.createElement(tag.toLowerCase());
        if (tag === 'A') {
            let href = (node.getAttribute('href') || '').trim();
            if (!/^https?:\/\//i.test(href)) href = '';
            if (href) {
                el.setAttribute('href', href);
                el.setAttribute('target', '_blank');
                el.setAttribute('rel', 'noopener noreferrer');
            }
        }

        Array.from(node.childNodes).forEach((child) => el.appendChild(cleanNode(child)));
        return el;
    };

    const out = doc.createElement('div');
    Array.from(root.childNodes).forEach((child) => out.appendChild(cleanNode(child)));
    return out.innerHTML;
}

function legacyMarkdownToKbHtml(text) {
    if (!text) return '';
    let html = escapeHtml(text).replace(/\r\n?/g, '\n');
    html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    html = html.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/gi, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(?!\*)([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
    html = html.split('\n').map((line) => {
        if (line.startsWith('- ')) return `&bull; ${line.slice(2)}`;
        return line;
    }).join('<br>');
    return html;
}

function renderKbDescription(text) {
    if (!text) return '';
    const hasHtml = /<\/?[a-z][\s\S]*>/i.test(text);
    return hasHtml ? sanitizeKbHtml(text) : legacyMarkdownToKbHtml(text);
}

function getKbDescEditor() {
    return document.getElementById('kb-card-desc');
}

function setKbDescEditorContent(text) {
    const editor = getKbDescEditor();
    if (!editor) return;
    editor.innerHTML = renderKbDescription(text || '');
    kbSyncDescToolbarState();
}

function getKbDescEditorContent() {
    const editor = getKbDescEditor();
    if (!editor) return '';
    return sanitizeKbHtml(editor.innerHTML || '').trim();
}

let kbSavedSelectionRange = null;
let kbToolbarSyncBound = false;
let kbModalSizeObserver = null;
let kbEditorDefaultSize = null;
let kbSizingSyncBusy = false;

function kbEnsureEditorDefaultSize() {
    const editor = getKbDescEditor();
    if (!editor || kbEditorDefaultSize) return;

    const rect = editor.getBoundingClientRect();
    const width = Math.round(rect.width || editor.offsetWidth || 0);
    const height = Math.round(rect.height || editor.offsetHeight || 0);
    if (width <= 0 || height <= 0) return;

    kbEditorDefaultSize = {
        width,
        height
    };
}

function kbClampEditorToModalLimits() {
    if (kbSizingSyncBusy) return;

    const modal = document.getElementById('kb-modal');
    const box = modal?.querySelector('.kb-modal-box');
    const editor = getKbDescEditor();
    if (!modal || !box || !editor) return;
    if (!modal.classList.contains('active')) return;

    kbEnsureEditorDefaultSize();
    if (!kbEditorDefaultSize) return;

    kbSizingSyncBusy = true;
    try {
        const chromePadding = 56;
        const viewportMaxModalW = Math.floor(window.innerWidth * 0.94);
        const maxEditorWidth = Math.max(320, viewportMaxModalW - chromePadding);
        const minEditorWidth = Math.min(kbEditorDefaultSize.width, maxEditorWidth);

        const currentWidth = Math.round(editor.getBoundingClientRect().width || editor.offsetWidth || minEditorWidth);
        const clampedWidth = Math.min(maxEditorWidth, Math.max(minEditorWidth, currentWidth));

        editor.style.minWidth = `${minEditorWidth}px`;
        editor.style.maxWidth = `${maxEditorWidth}px`;
        if (Math.abs(clampedWidth - currentWidth) > 1) {
            editor.style.width = `${clampedWidth}px`;
        }

        const maxModalHeight = Math.floor(window.innerHeight * 0.94);
        const boxHeight = Math.round(box.getBoundingClientRect().height || box.offsetHeight || 0);
        const editorHeight = Math.round(editor.getBoundingClientRect().height || editor.offsetHeight || kbEditorDefaultSize.height);
        const nonEditorHeight = Math.max(0, boxHeight - editorHeight);

        const availableEditorHeight = Math.max(140, maxModalHeight - nonEditorHeight - 2);
        const minEditorHeight = Math.min(kbEditorDefaultSize.height, availableEditorHeight);
        const maxEditorHeight = Math.max(minEditorHeight, availableEditorHeight);

        const currentHeight = Math.round(editor.getBoundingClientRect().height || editor.offsetHeight || minEditorHeight);
        const clampedHeight = Math.min(maxEditorHeight, Math.max(minEditorHeight, currentHeight));

        editor.style.minHeight = `${minEditorHeight}px`;
        editor.style.maxHeight = `${maxEditorHeight}px`;
        if (Math.abs(clampedHeight - currentHeight) > 1) {
            editor.style.height = `${clampedHeight}px`;
        }
    } finally {
        kbSizingSyncBusy = false;
    }
}

function kbUpdateModalSizeFromEditor() {
    const modal = document.getElementById('kb-modal');
    const box = modal?.querySelector('.kb-modal-box');
    const editor = getKbDescEditor();
    if (!modal || !box || !editor) return;
    if (!modal.classList.contains('active')) return;

    kbClampEditorToModalLimits();

    const viewportMax = Math.floor(window.innerWidth * 0.94);
    const chromePadding = 56;
    const measuredEditorWidth = Math.round(editor.offsetWidth || 0);
    const desiredWidth = Math.max(760, measuredEditorWidth + chromePadding);
    box.style.width = `${Math.min(viewportMax, desiredWidth)}px`;
}

function kbBindModalSizeSync() {
    if (kbModalSizeObserver) return;

    const editor = getKbDescEditor();
    if (!editor || !window.ResizeObserver) return;

    kbModalSizeObserver = new ResizeObserver(() => {
        kbUpdateModalSizeFromEditor();
    });
    kbModalSizeObserver.observe(editor);
    window.addEventListener('resize', kbUpdateModalSizeFromEditor);
}

function kbSaveSelectionRange() {
    const editor = getKbDescEditor();
    const sel = window.getSelection();
    if (!editor || !sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    if (!editor.contains(range.startContainer) || !editor.contains(range.endContainer)) return;
    kbSavedSelectionRange = range.cloneRange();
}

function kbRestoreSelectionRange() {
    const sel = window.getSelection();
    if (!sel) return;
    sel.removeAllRanges();
    if (kbSavedSelectionRange) sel.addRange(kbSavedSelectionRange);
}

function kbNodeInTag(editor, tagName) {
    const sel = window.getSelection();
    if (!editor || !sel || !sel.rangeCount) return false;

    const anchor = sel.anchorNode;
    if (!anchor) return false;
    let node = anchor.nodeType === Node.ELEMENT_NODE ? anchor : anchor.parentElement;

    while (node && node !== editor) {
        if ((node.tagName || '').toUpperCase() === tagName) return true;
        node = node.parentElement;
    }
    return false;
}

function kbSyncDescToolbarState() {
    const editor = getKbDescEditor();
    if (!editor) return;

    const sel = window.getSelection();
    const inEditor = !!(sel && sel.rangeCount && editor.contains(sel.anchorNode));

    const btnBold = document.getElementById('kb-tool-bold');
    const btnItalic = document.getElementById('kb-tool-italic');
    const btnCode = document.getElementById('kb-tool-code');
    const btnLink = document.getElementById('kb-link-tool-btn');
    const btnList = document.getElementById('kb-tool-list');

    const setActive = (btn, active) => {
        if (!btn) return;
        btn.classList.toggle('active', !!active);
    };

    if (!inEditor) {
        setActive(btnBold, false);
        setActive(btnItalic, false);
        setActive(btnCode, false);
        setActive(btnLink, false);
        setActive(btnList, false);
        return;
    }

    let isBold = false;
    let isItalic = false;
    let isList = false;
    try {
        isBold = !!document.queryCommandState('bold');
        isItalic = !!document.queryCommandState('italic');
        isList = !!document.queryCommandState('insertUnorderedList');
    } catch (_err) {
        // Ignorar en motores donde queryCommandState no esté disponible.
    }

    const isCode = kbNodeInTag(editor, 'CODE');
    const isLink = kbNodeInTag(editor, 'A');

    setActive(btnBold, isBold);
    setActive(btnItalic, isItalic);
    setActive(btnCode, isCode);
    setActive(btnLink, isLink);
    setActive(btnList, isList);
}

function kbBindToolbarSync() {
    if (kbToolbarSyncBound) return;

    const editor = getKbDescEditor();
    if (!editor) return;
    kbToolbarSyncBound = true;

    editor.addEventListener('keyup', kbSyncDescToolbarState);
    editor.addEventListener('mouseup', kbSyncDescToolbarState);
    editor.addEventListener('input', kbSyncDescToolbarState);
    editor.addEventListener('focus', kbSyncDescToolbarState);
    document.addEventListener('selectionchange', kbSyncDescToolbarState);
}

function kbOpenLinkPopover() {
    const pop = document.getElementById('kb-link-popover');
    const labelInput = document.getElementById('kb-link-label');
    const urlInput = document.getElementById('kb-link-url');
    const editor = getKbDescEditor();
    if (!pop || !labelInput || !urlInput || !editor) return;

    kbSaveSelectionRange();
    let selected = '';
    const sel = window.getSelection();
    if (sel && sel.rangeCount) selected = (sel.toString() || '').trim();

    labelInput.value = selected && !/^https?:\/\//i.test(selected) ? selected : '';
    urlInput.value = /^https?:\/\//i.test(selected) ? selected : 'https://';
    pop.classList.add('active');

    if (urlInput.value === 'https://') {
        urlInput.focus();
        urlInput.setSelectionRange(urlInput.value.length, urlInput.value.length);
    } else {
        labelInput.focus();
        labelInput.select();
    }
}

function kbCloseLinkPopover() {
    const pop = document.getElementById('kb-link-popover');
    const editor = getKbDescEditor();
    if (pop) pop.classList.remove('active');
    if (editor) editor.focus();
    kbSyncDescToolbarState();
}

function kbInsertLinkFromPopover() {
    const labelInput = document.getElementById('kb-link-label');
    const urlInput = document.getElementById('kb-link-url');
    const editor = getKbDescEditor();
    if (!labelInput || !urlInput || !editor) return;

    let url = (urlInput.value || '').trim();
    if (!url) return;
    if (!/^https?:\/\//i.test(url)) url = `https://${url.replace(/^\/+/, '')}`;

    kbRestoreSelectionRange();
    const sel = window.getSelection();
    const selected = sel ? (sel.toString() || '').trim() : '';
    const label = (labelInput.value || '').trim() || selected || 'enlace';
    const safeLabel = escapeHtml(label);
    const safeUrl = escapeHtml(url);

    document.execCommand('insertHTML', false, `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeLabel}</a>`);
    kbSavedSelectionRange = null;
    kbCloseLinkPopover();
    kbSyncDescToolbarState();
}

function kbApplyFormat(kind) {
    const editor = getKbDescEditor();
    if (!editor) return;
    editor.focus();

    if (kind === 'list') {
        document.execCommand('insertUnorderedList', false);
        kbSyncDescToolbarState();
        return;
    }

    if (kind === 'link') {
        kbOpenLinkPopover();
        return;
    }

    if (kind === 'bold') {
        document.execCommand('bold', false);
        kbSyncDescToolbarState();
        return;
    }

    if (kind === 'italic') {
        document.execCommand('italic', false);
        kbSyncDescToolbarState();
        return;
    }

    if (kind === 'code') {
        kbSaveSelectionRange();
        kbRestoreSelectionRange();
        const sel = window.getSelection();
        const selectedText = sel ? sel.toString() : '';
        const safe = escapeHtml(selectedText || 'codigo');
        document.execCommand('insertHTML', false, `<code>${safe}</code>`);
        kbSyncDescToolbarState();
    }
}

function renderKbLabelSelector() {
    const container = document.getElementById('kb-label-selector');
    if (!container) return;
    
    container.innerHTML = state.kbAvailableLabels.map(label => `
        <div class="kb-modal-label-chip ${state.kbSelectedLabels.has(label) ? 'selected' : ''}" 
             onclick="toggleKbLabel('${escapeHtml(label)}')"
             style="cursor:pointer;">
            ${escapeHtml(label)}
        </div>
    `).join('');
}

function toggleKbLabel(label) {
    if (state.kbSelectedLabels.has(label)) {
        state.kbSelectedLabels.delete(label);
    } else {
        state.kbSelectedLabels.add(label);
    }
    renderKbLabelSelector();
}

function getKbDueInfo(dueStr, status) {
    if (!dueStr) return null;
    try {
        const due = new Date(dueStr + 'T00:00:00');
        const now = new Date();
        now.setHours(0, 0, 0, 0);
        const diff = Math.floor((due - now) / (1000 * 60 * 60 * 24));
        
        if (diff < -30) return { cls: 'overdue', dot: '🔴', label: 'Vencida' };
        if (diff < 0) return { cls: 'red', dot: '🔴', label: `Vencida hace ${-diff}d` };
        if (diff === 0) return { cls: 'red', dot: '🔴', label: 'Vence hoy' };
        if (diff <= 3) return { cls: 'red', dot: '🔴', label: `Vence en ${diff}d` };
        if (diff <= 7) return { cls: 'yellow', dot: '🟡', label: `Vence en ${diff}d` };
        return { cls: 'green', dot: '🟢', label: `${diff}d restantes` };
    } catch (_) {
        return null;
    }
}

// Variable global para el drag and drop
let kbDragId = null;
let kbDropZonesReady = false;

function kbInitDropZones() {
    ['pending', 'inprogress', 'blocked', 'done'].forEach(status => {
        const col = document.getElementById(`cards-${status}`);
        if (!col) return;

        col.addEventListener('dragover', e => {
            e.preventDefault();
            col.classList.add('drag-over');
        });

        col.addEventListener('dragleave', e => {
            if (!col.contains(e.relatedTarget)) col.classList.remove('drag-over');
        });

        col.addEventListener('drop', async e => {
            e.preventDefault();
            col.classList.remove('drag-over');
            const draggedId = kbDragId; // capturar antes de limpiar
            if (!draggedId) return;
            kbDragId = null;

            const colMap = { pending: 1, inprogress: 2, blocked: 3, done: 4 };
            const newCol = colMap[status];
            if (!newCol) return;

            // Buscar tarjeta en todas las columnas
            for (let c = 1; c <= 4; c++) {
                const cards = await py.get_kanban_cards(c);
                // Usar == para comparación flexible de tipo (Python int vs JS number)
                const found = cards.find(card => card.id == draggedId);
                if (found) {
                    await py.update_kanban_card(found.id, newCol, found.text);
                    await fetchKanban();
                    return;
                }
            }
        });
    });
    kbDropZonesReady = true;
}

async function fetchKanban() {
    // Inicializar drop zones solo una vez
    if (!kbDropZonesReady) kbInitDropZones();

    const statusOrder = ['pending', 'inprogress', 'blocked', 'done'];
    const statusMeta = {
        pending: 'Pendiente',
        inprogress: 'En proceso',
        blocked: 'Bloqueada',
        done: 'Completada'
    };
    const priorityLabels = { high: '🔺 Alta', medium: '🔸 Media', low: '🔹 Baja' };

    // Cargar etiquetas para filtro
    await loadKbLabels();
    kbRenderLabelFilter();

    for (let i = 0; i < statusOrder.length; i += 1) {
        const status = statusOrder[i];
        const cards = await py.get_kanban_cards(i + 1);
        
        const filtered = (cards || []).filter((c) => {
            const text = (c.text || '').toLowerCase();
            const matchSearch = text.includes(state.kanbanSearch);
            if (!matchSearch) return false;
            if (state.kbActiveLabel) {
                const parsed = parseKanbanCardText(c.text);
                return parsed.labels.includes(state.kbActiveLabel);
            }
            return true;
        });

        const container = document.getElementById(`cards-${status}`);
        const countEl = document.getElementById(`count-${status}`);
        if (!container || !countEl) continue;

        countEl.textContent = String(filtered.length);
        container.innerHTML = filtered.map((card) => {
            const parsed = parseKanbanCardText(card.text);
            const shortId = String(card.id || '').slice(-6);
            const dueInfo = getKbDueInfo(parsed.due, status);
            const dueLiClass = dueInfo ? `due-${dueInfo.cls}` : '';
            const labelsHtml = parsed.labels.length > 0 
                ? `<div class="kb-card-labels">${parsed.labels.map(l => `<span class="kb-label">${escapeHtml(l)}</span>`).join('')}</div>`
                : '';
            
            return `
            <div class="kb-card ${dueLiClass}" draggable="true" data-id="${card.id}"
                 ondragstart="kbDragStart(event, ${card.id})"
                 ondragend="kbDragEnd(event)">
                <div class="kb-card-top">
                    <span class="kb-card-id">#${escapeHtml(shortId || '------')}</span>
                    <span class="kb-status-chip ${escapeHtml(status)}">${escapeHtml(statusMeta[status] || 'Pendiente')}</span>
                </div>
                <div class="kb-card-title">${escapeHtml(parsed.title)}</div>
                ${parsed.description ? `<div class="kb-card-desc">${renderKbDescription(parsed.description)}</div>` : ''}
                ${labelsHtml}
                <div class="kb-card-meta">
                    <span class="kb-priority ${parsed.priority}">${priorityLabels[parsed.priority]}</span>
                    ${dueInfo ? `<div class="kb-due ${dueInfo.cls}">${dueInfo.dot} ${dueInfo.label}</div>` : ''}
                </div>
                <div class="kb-card-actions">
                    <button class="kb-card-btn" onclick="editKanbanCard(${card.id})">✏️</button>
                    <button class="kb-card-btn del" onclick="deleteKanbanCard(${card.id})">🗑️</button>
                </div>
            </div>`;
        }).join('');
    }
}

function kbDragStart(event, cardId) {
    kbDragId = cardId;
    setTimeout(() => {
        const el = document.querySelector(`.kb-card[data-id="${cardId}"]`);
        if (el) el.classList.add('dragging');
    }, 0);
}

function kbDragEnd(event) {
    document.querySelectorAll('.kb-card.dragging').forEach(el => el.classList.remove('dragging'));
    document.querySelectorAll('.kb-cards.drag-over').forEach(el => el.classList.remove('drag-over'));
}

async function loadKbLabels() {
    // Cargar todas las etiquetas únicas de todas las tarjetas
    const allLabels = new Set();
    for (let col = 1; col <= 4; col += 1) {
        const cards = await py.get_kanban_cards(col);
        cards.forEach(card => {
            const parsed = parseKanbanCardText(card.text);
            parsed.labels.forEach(label => allLabels.add(label));
        });
    }
    state.kbAvailableLabels = Array.from(allLabels).sort();
}

function kbRenderLabelFilter() {
    const container = document.getElementById('kb-label-filter');
    if (!container) return;
    
    if (state.kbAvailableLabels.length === 0) {
        container.innerHTML = '';
        return;
    }
    
    container.innerHTML = state.kbAvailableLabels.map(label => `
        <div class="kb-label-chip ${state.kbActiveLabel === label ? 'active' : ''}" 
             onclick="toggleKbLabelFilter('${escapeHtml(label)}')"
             style="cursor:pointer;">
            ${escapeHtml(label)}
        </div>
    `).join('');
}

async function toggleKbLabelFilter(label) {
    state.kbActiveLabel = state.kbActiveLabel === label ? null : label;
    kbRenderLabelFilter();
    await fetchKanban();
}

async function openKanbanModal(status) {
    state.kbModalStatus = status;
    state.kbEditingId = null;
    state.kbSelectedLabels.clear();
    document.getElementById('kb-modal-title').textContent = 'Nueva tarjeta';
    
    // Cargar etiquetas disponibles
    await loadKbLabels();
    
    const statusInput = document.getElementById('kb-card-status');
    if (statusInput) statusInput.value = status;

    const title = document.getElementById('kb-card-title');
    const desc = getKbDescEditor();
    const due = document.getElementById('kb-card-due');
    const prio = document.getElementById('kb-card-priority');
    const newLabel = document.getElementById('kb-new-label-input');

    if (title) title.value = '';
    if (desc) setKbDescEditorContent('');
    if (due) due.value = '';
    if (prio) prio.value = 'medium';
    if (newLabel) newLabel.value = '';

    const linkLabel = document.getElementById('kb-link-label');
    const linkUrl = document.getElementById('kb-link-url');
    if (linkLabel) linkLabel.value = '';
    if (linkUrl) linkUrl.value = 'https://';
    kbCloseLinkPopover();

    renderKbLabelSelector();
    document.getElementById('kb-modal')?.classList.add('active');
    requestAnimationFrame(kbUpdateModalSizeFromEditor);
}

async function editKanbanCard(cardId) {
    const colMap = { 1: 'pending', 2: 'inprogress', 3: 'blocked', 4: 'done' };
    let targetCard = null;
    let targetCol = null;
    
    for (let col = 1; col <= 4; col += 1) {
        const cards = await py.get_kanban_cards(col);
        const found = cards.find(c => c.id === cardId);
        if (found) {
            targetCard = found;
            targetCol = col;
            break;
        }
    }
    
    if (!targetCard) return;
    
    state.kbEditingId = cardId;
    const parsed = parseKanbanCardText(targetCard.text);
    
    // Cargar todas las etiquetas disponibles y preseleccionar las de esta tarjeta
    await loadKbLabels();
    state.kbSelectedLabels.clear();
    parsed.labels.forEach(label => state.kbSelectedLabels.add(label));
    
    document.getElementById('kb-modal-title').textContent = 'Editar tarjeta';
    document.getElementById('kb-card-title').value = parsed.title;
    setKbDescEditorContent(parsed.description || '');
    document.getElementById('kb-card-due').value = parsed.due || '';
    document.getElementById('kb-card-priority').value = parsed.priority;
    document.getElementById('kb-card-status').value = colMap[targetCol] || 'pending';
    document.getElementById('kb-new-label-input').value = '';
    const linkLabel = document.getElementById('kb-link-label');
    const linkUrl = document.getElementById('kb-link-url');
    if (linkLabel) linkLabel.value = '';
    if (linkUrl) linkUrl.value = 'https://';
    kbCloseLinkPopover();
    
    renderKbLabelSelector();
    document.getElementById('kb-modal')?.classList.add('active');
    requestAnimationFrame(kbUpdateModalSizeFromEditor);
}

function closeKanbanModal() {
    kbCloseLinkPopover();
    const box = document.querySelector('#kb-modal .kb-modal-box');
    if (box) box.style.width = '';
    document.getElementById('kb-modal')?.classList.remove('active');
}

async function saveKanbanCard() {
    const title = (document.getElementById('kb-card-title')?.value || '').trim();
    if (!title) return;

    const status = document.getElementById('kb-card-status')?.value || state.kbModalStatus;
    const desc = getKbDescEditorContent();
    const due = (document.getElementById('kb-card-due')?.value || '').trim();
    const priority = (document.getElementById('kb-card-priority')?.value || 'medium').trim();

    const fragments = [title];
    if (desc) fragments.push(desc);
    if (due) fragments.push(`Vence: ${due}`);
    if (priority) fragments.push(`Prioridad: ${priority}`);
    if (state.kbSelectedLabels.size > 0) {
        fragments.push(`Etiquetas: ${Array.from(state.kbSelectedLabels).join(', ')}`);
    }
    const text = fragments.join(' | ');

    const colMap = { pending: 1, inprogress: 2, blocked: 3, done: 4 };
    const col = colMap[status] || 1;

    if (state.kbEditingId) {
        await py.update_kanban_card(state.kbEditingId, col, text);
        notify('Tarjeta actualizada', 'success');
    } else {
        await py.add_kanban_card(col, text, Date.now());
        notify('Tarjeta creada', 'success');
    }
    
    state.kbEditingId = null;
    state.kbSelectedLabels.clear();
    closeKanbanModal();
    await fetchKanban();
}

async function deleteKanbanCard(id) {
    window.showConfirm('¿Borrar tarjeta?', async (ok) => {
        if (!ok) return;
        await py.delete_kanban_card(id);
        await fetchKanban();
    });
}

// ── Notas Adhesivas ──────────────────────────────────────────────────────────
const NOTE_COLORS = {
    yellow: { bg: '#ffeaa7', header: '#fdcb6e' },
    green:  { bg: '#c3f4e4', header: '#81ecec' },
    blue:   { bg: '#c4dfff', header: '#74b9ff' },
    pink:   { bg: '#ffcee8', header: '#fd79a8' },
    purple: { bg: '#ddd4fe', header: '#a29bfe' },
    orange: { bg: '#ffe4c0', header: '#fab1a0' },
    white:  { bg: '#f0f0f5', header: '#dde0e8' },
};

const NOTE_MIN_WIDTH = 220;
const NOTE_MIN_HEIGHT = 170;
const noteSizeSaveTimers = new Map();

let notesData = [];
let notesLoaded = false;

async function fetchNotes() {
    if (notesLoaded) { renderNotes(); return; }
    try {
        notesData = await py.get_notes();
        notesLoaded = true;
        renderNotes();
    } catch (e) {
        console.error('Error al cargar notas', e);
    }
}

function updateNotesCount() {
    const badge = document.getElementById('notes-total');
    if (badge) badge.textContent = notesData.length;
}

function isNotesViewVisible() {
    const view = document.getElementById('view-notes');
    const board = document.getElementById('notes-board');
    return !!(view && board && view.classList.contains('active') && board.clientWidth > 40 && board.clientHeight > 40);
}

function schedulePersistNoteSize(noteId, width, height) {
    if (!py || typeof py.update_note_size !== 'function') return;

    const w = Math.max(NOTE_MIN_WIDTH, Math.round(Number(width) || NOTE_MIN_WIDTH));
    const h = Math.max(NOTE_MIN_HEIGHT, Math.round(Number(height) || NOTE_MIN_HEIGHT));
    const key = String(noteId);

    const prevTimer = noteSizeSaveTimers.get(key);
    if (prevTimer) clearTimeout(prevTimer);

    const timer = setTimeout(() => {
        noteSizeSaveTimers.delete(key);
        py.update_note_size(Number(noteId), w, h).catch(() => {});
    }, 180);

    noteSizeSaveTimers.set(key, timer);
}

function autoArrangeNotes() {
    const board  = document.getElementById('notes-board');
    const canvas = document.getElementById('notes-canvas');
    if (!board || !canvas || !notesData.length) return;

    const NOTE_W = 220;
    const GAP    = 14;
    const bw     = board.clientWidth - GAP * 2;
    const cols   = Math.max(1, Math.floor((bw + GAP) / (NOTE_W + GAP)));

    const elements = notesData.map(note =>
        canvas.querySelector(`.sticky-note[data-id="${note.id}"]`)
    );

    const numRows = Math.ceil(notesData.length / cols);
    const rowH = Array.from({ length: numRows }, (_, r) => {
        let max = 170;
        for (let c = 0; c < cols; c++) {
            const el = elements[r * cols + c];
            if (el) max = Math.max(max, el.offsetHeight || 170);
        }
        return max;
    });

    const rowY = [GAP];
    for (let r = 1; r < numRows; r++) rowY.push(rowY[r - 1] + rowH[r - 1] + GAP);

    notesData.forEach((note, i) => {
        const el = elements[i];
        const col = i % cols;
        const row = Math.floor(i / cols);
        note.x = GAP + col * (NOTE_W + GAP);
        note.y = rowY[row];
        if (el) { el.style.left = note.x + 'px'; el.style.top = note.y + 'px'; }
        py.update_note_pos(note.id, note.x, note.y).catch(() => {});
    });

    updateCanvasSize();
}

function renderNotes() {
    const canvas = document.getElementById('notes-canvas');
    if (!canvas) return;
    const hint = document.getElementById('notes-hint');
    canvas.innerHTML = '';
    if (hint) canvas.appendChild(hint);

    if (notesData.length === 0) {
        if (hint) hint.style.display = '';
    } else {
        if (hint) hint.style.display = 'none';
        notesData.forEach(note => canvas.appendChild(buildNote(note)));
    }
    updateCanvasSize();
    updateNotesCount();
}

function updateCanvasSize() {
    const canvas = document.getElementById('notes-canvas');
    const board  = document.getElementById('notes-board');
    if (!canvas || !board) return;
    const notes = canvas.querySelectorAll('.sticky-note');
    if (!notes.length) {
        canvas.style.width  = '';
        canvas.style.height = '';
        return;
    }
    let maxRight = 0, maxBottom = 0;
    notes.forEach(el => {
        maxRight  = Math.max(maxRight,  (parseInt(el.style.left) || 0) + (el.offsetWidth  || 220));
        maxBottom = Math.max(maxBottom, (parseInt(el.style.top)  || 0) + (el.offsetHeight || 170));
    });
    const pad = 14;
    canvas.style.width  = Math.max(maxRight  + pad, board.clientWidth)  + 'px';
    canvas.style.height = Math.max(maxBottom + pad, board.clientHeight) + 'px';
}

function buildNote(note) {
    const div = document.createElement('div');
    div.className = 'sticky-note';
    div.dataset.id = note.id;
    div.dataset.color = note.color || 'yellow';
    const left = note.x ?? 20;
    const top = note.y ?? 20;
    const width = Math.max(NOTE_MIN_WIDTH, Number(note.width ?? NOTE_MIN_WIDTH));
    const height = Math.max(NOTE_MIN_HEIGHT, Number(note.height ?? NOTE_MIN_HEIGHT));
    const zIndex = note.zIndex ?? 1;
    div.style.cssText = `left:${left}px; top:${top}px; width:${width}px; height:${height}px; z-index:${zIndex};`;

    div.innerHTML = `
        <div class="note-header">
            <div class="note-colors">
                ${Object.entries(NOTE_COLORS).map(([k, c]) =>
                    `<span class="note-color-dot${note.color === k ? ' active' : ''}" data-color="${k}" style="background:${c.header};" title="${k}"></span>`
                ).join('')}
            </div>
            <button class="note-delete" title="Eliminar nota">&times;</button>
        </div>
        <div class="note-body">
            <textarea placeholder="Escribe una nota...">${escapeHtml(note.content || '')}</textarea>
        </div>`;

    // Drag desde el header
    div.querySelector('.note-header').addEventListener('mousedown', noteStartDrag);

    // Traer al frente al hacer clic
    div.addEventListener('mousedown', () => noteBringToFront(div, note.id));

    // Eliminar
    div.querySelector('.note-delete').addEventListener('click', async (e) => {
        e.stopPropagation();
        if (div._resizeObserver) {
            div._resizeObserver.disconnect();
            div._resizeObserver = null;
        }
        const timerKey = String(note.id);
        const pending = noteSizeSaveTimers.get(timerKey);
        if (pending) {
            clearTimeout(pending);
            noteSizeSaveTimers.delete(timerKey);
        }
        notesData = notesData.filter(n => n.id !== note.id);
        div.style.transition = 'opacity 0.2s, transform 0.2s';
        div.style.opacity = '0';
        div.style.transform = 'scale(0.85)';
        setTimeout(() => {
            div.remove();
            updateCanvasSize();
            updateNotesCount();
        }, 200);
        if (notesData.length === 0) {
            const hint = document.getElementById('notes-hint');
            if (hint) hint.style.display = '';
        }
        await py.delete_note(note.id);
    });

    // Cambiar color
    div.querySelectorAll('.note-color-dot').forEach(dot => {
        dot.addEventListener('click', async (e) => {
            e.stopPropagation();
            const color = dot.dataset.color;
            note.color = color;
            div.dataset.color = color;
            div.querySelectorAll('.note-color-dot').forEach(d =>
                d.classList.toggle('active', d.dataset.color === color)
            );
            const idx = notesData.findIndex(n => n.id === note.id);
            if (idx !== -1) notesData[idx].color = color;
            await py.update_note_color(note.id, color).catch(() => {});
        });
    });

    // Autoguardado de contenido
    const textarea = div.querySelector('textarea');
    let saveTimer = null;
    let lastSaved = note.content || '';

    async function saveContent() {
        clearTimeout(saveTimer);
        saveTimer = null;
        const content = textarea.value;
        if (content === lastSaved) return;
        lastSaved = content;
        note.content = content;
        const idx = notesData.findIndex(n => n.id === note.id);
        if (idx !== -1) notesData[idx].content = content;
        await py.update_note_content(note.id, content).catch(() => {});
    }

    textarea.addEventListener('input', () => {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(saveContent, 400);
    });

    textarea.addEventListener('blur', () => {
        clearTimeout(saveTimer);
        const content = textarea.value;
        if (content !== lastSaved) {
            lastSaved = content;
            note.content = content;
            const idx = notesData.findIndex(n => n.id === note.id);
            if (idx !== -1) notesData[idx].content = content;
            py.update_note_content(note.id, content).catch(() => {});
        }
    });

    // Evitar que clicks en el textarea inicien drag
    textarea.addEventListener('mousedown', e => e.stopPropagation());

    if (window.ResizeObserver) {
        const resizeObserver = new ResizeObserver(() => {
            if (!isNotesViewVisible()) return;
            const nextW = Math.max(NOTE_MIN_WIDTH, Math.round(div.offsetWidth || NOTE_MIN_WIDTH));
            const nextH = Math.max(NOTE_MIN_HEIGHT, Math.round(div.offsetHeight || NOTE_MIN_HEIGHT));
            note.width = nextW;
            note.height = nextH;
            const idx = notesData.findIndex(n => n.id === note.id);
            if (idx !== -1) {
                notesData[idx].width = nextW;
                notesData[idx].height = nextH;
            }
            schedulePersistNoteSize(note.id, nextW, nextH);
            updateCanvasSize();
        });
        resizeObserver.observe(div);
        div._resizeObserver = resizeObserver;
    }

    return div;
}

function noteBringToFront(noteEl, id) {
    if (!notesData.length) return;
    const maxZ = Math.max(...notesData.map(n => n.zIndex || 1));
    const note = notesData.find(n => n.id == id);
    if (!note || (note.zIndex || 1) >= maxZ) return;
    note.zIndex = maxZ + 1;
    noteEl.style.zIndex = maxZ + 1;
    py.update_note_zindex(id, maxZ + 1).catch(() => {});
}

function noteStartDrag(e) {
    if (e.button !== 0) return;
    const noteEl = e.currentTarget.closest('.sticky-note');
    if (!noteEl) return;
    e.preventDefault();

    const startX = e.clientX - noteEl.offsetLeft;
    const startY = e.clientY - noteEl.offsetTop;
    noteEl.classList.add('dragging');

    function onMove(ev) {
        const x = Math.max(0, ev.clientX - startX);
        const y = Math.max(0, ev.clientY - startY);
        noteEl.style.left = x + 'px';
        noteEl.style.top  = y + 'px';
    }

    function onUp() {
        noteEl.classList.remove('dragging');
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);

        const id = parseInt(noteEl.dataset.id);
        const x = parseInt(noteEl.style.left);
        const y = parseInt(noteEl.style.top);
        const note = notesData.find(n => n.id == id);
        if (note) { note.x = x; note.y = y; }
        updateCanvasSize();
        py.update_note_pos(id, x, y).catch(() => {});
    }

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

async function addNote(x, y) {
    const offset = (notesData.length % 10) * 22;
    const nx = x !== undefined ? x : 20 + offset;
    const ny = y !== undefined ? y : 20 + offset;
    const nw = NOTE_MIN_WIDTH;
    const nh = NOTE_MIN_HEIGHT;
    const maxZ = notesData.length ? Math.max(...notesData.map(n => n.zIndex || 1)) + 1 : 1;
    try {
        const nid = await py.add_note('yellow', nx, ny, maxZ);
        const note = { id: nid, content: '', color: 'yellow', x: nx, y: ny, width: nw, height: nh, zIndex: maxZ };
        notesData.push(note);
        py.update_note_pos(nid, nx, ny).catch(() => {});
        schedulePersistNoteSize(nid, nw, nh);
        const canvas = document.getElementById('notes-canvas');
        const hint = document.getElementById('notes-hint');
        if (hint) hint.style.display = 'none';
        const noteEl = buildNote(note);
        noteEl.style.opacity = '0';
        noteEl.style.transform = 'scale(0.8)';
        canvas.appendChild(noteEl);
        requestAnimationFrame(() => {
            noteEl.style.transition = 'opacity 0.2s, transform 0.2s';
            noteEl.style.opacity = '1';
            noteEl.style.transform = 'scale(1)';
            updateCanvasSize();
            updateNotesCount();
        });
        setTimeout(() => {
            const ta = noteEl.querySelector('textarea');
            if (ta) ta.focus();
        }, 220);
    } catch (e) {
        console.error('Error al crear nota', e);
    }
}

// Doble clic en pizarra para crear nota en esa posición
document.getElementById('notes-board').addEventListener('dblclick', (e) => {
    if (!e.target.classList.contains('notes-canvas') && !e.target.classList.contains('notes-board')) return;
    const board = document.getElementById('notes-board');
    const rect = board.getBoundingClientRect();
    const x = Math.max(0, e.clientX - rect.left + board.scrollLeft - 110);
    const y = Math.max(0, e.clientY - rect.top + board.scrollTop - 85);
    addNote(x, y);
});

// Reposicionar notas fuera del área visible al redimensionar
(function () {
    const board = document.getElementById('notes-board');
    if (!board || !window.ResizeObserver) return;
    let resizeTimer;
    new ResizeObserver(() => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (!isNotesViewVisible()) return;
            const bw = board.clientWidth  - 10;
            const bh = board.clientHeight - 10;
            const displaced = [];
            board.querySelectorAll('.sticky-note').forEach(el => {
                const noteW = el.offsetWidth  || 220;
                const noteH = el.offsetHeight || 170;
                const x = parseInt(el.style.left) || 0;
                const y = parseInt(el.style.top)  || 0;
                if (x + noteW > bw || y + noteH > bh) {
                    displaced.push({ el, noteW, noteH });
                }
            });

            const gap = 14;
            let curX = gap, curY = gap, rowH = 0;
            displaced.forEach(({ el, noteW, noteH }) => {
                if (curX + noteW + gap > bw && curX > gap) {
                    curX = gap; curY += rowH + gap; rowH = 0;
                }
                const newX = Math.min(curX, Math.max(0, bw - noteW));
                const newY = Math.min(curY, Math.max(0, bh - noteH));
                el.style.left = newX + 'px';
                el.style.top  = newY + 'px';
                const id = parseInt(el.dataset.id);
                const note = notesData.find(n => n.id == id);
                if (note) { note.x = newX; note.y = newY; }
                py.update_note_pos(id, newX, newY).catch(() => {});
                curX += noteW + gap;
                rowH  = Math.max(rowH, noteH);
            });
            updateCanvasSize();
        }, 300);
    }).observe(board);
})();

async function pwLoad() {
    try {
        if (!pw) return;
        const [rows] = await Promise.all([
            pw.get_passwords(),
            pwLoadAutoSavePolicy()
        ]);
        state.passwords = (rows || []).map((p) => ({
            ...p,
            type: normalizePwType(p.type, p.site, p.notes),
            url: p.url || '',
            notes: p.notes || ''
        }));
        renderPasswords();
    } catch (err) {
        console.error('Error loading passwords:', err);
    }
}

const PW_SVG_COPY = '<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>';
const PW_SVG_EYE = '<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>';
const PW_SVG_EYEOFF = '<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M12 7c2.76 0 5 2.24 5 5 0 .65-.13 1.26-.36 1.83l2.92 2.92c1.51-1.26 2.7-2.89 3.43-4.75C21.27 7.11 17 4 12 4c-1.3 0-2.55.25-3.65.7l2.16 2.16C11.04 6.96 11.49 7 12 7zm-7.07.27L7.1 9.44C6.51 10.23 6 11.07 6 12c0 2.76 2.24 5 5 5 .93 0 1.79-.26 2.56-.67l3.48 3.47 1.41-1.41L5.34 5.86 4.93 6.27zm8.25 8.25L10.5 12.84C10.33 12.57 10 12.31 10 12c0-1.1.9-2 2-2 .31 0 .57.33.84.5l2.68 2.68c-.52.39-1.15.62-1.84.62-.93 0-1.79-.38-2.43-.98z"/></svg>';
const PW_SVG_EDIT = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>';
const PW_SVG_DEL = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>';

function renderPasswords() {
    const list = document.getElementById('pw-list');
    if (!list) return;

    const filtered = state.passwords.filter((p) => {
        const pType = normalizePwType(p.type, p.site, p.notes);
        const termOk = !state.pwSearch || (p.site || '').toLowerCase().includes(state.pwSearch) || (p.username || '').toLowerCase().includes(state.pwSearch);
        const filterOk = state.pwFilter === 'all' ? true : pType === state.pwFilter;
        return termOk && filterOk;
    });

    if (!filtered.length) {
        list.innerHTML = '<div class="pw-empty"><div class="pw-empty-icon">🔑</div>No hay contraseñas guardadas</div>';
        return;
    }

    list.innerHTML = filtered.map((p) => {
        const safeType = normalizePwType(p.type, p.site, p.notes);
        const visible = state.pwShowSet.has(p.id);
        const passView = visible ? escapeHtml(p.password || '') : '••••••••';
        return `
        <div class="pw-card">
            <div class="pw-card-info">
                <div class="pw-card-name-row">
                    <div class="pw-card-name">${escapeHtml(p.site || '')}</div>
                    <span class="pw-type-badge ${safeType}">${getPwTypeLabel(safeType)}</span>
                </div>
                ${(safeType === 'web' || safeType === 'db') && p.url ? `<div class="pw-card-url">${escapeHtml(p.url)}</div>` : ''}
                <div class="pw-field-row">
                    <span class="pw-field-label">Usuario</span>
                    <span class="pw-field-value">${escapeHtml(p.username || '')}</span>
                    <span class="pw-field-actions">
                        <button class="pw-copy-btn" title="Copiar usuario" aria-label="Copiar usuario" onclick="pwCopy('${encodeURIComponent(p.username || '')}', this)">${PW_SVG_COPY}</button>
                    </span>
                </div>
                <div class="pw-field-row">
                    <span class="pw-field-label">Password</span>
                    <span class="pw-field-value ${visible ? '' : 'masked'}">${passView}</span>
                    <span class="pw-field-actions">
                        <button class="pw-show-btn" title="${visible ? 'Ocultar password' : 'Mostrar password'}" aria-label="${visible ? 'Ocultar password' : 'Mostrar password'}" onclick="togglePwVisibility(${p.id})">${visible ? PW_SVG_EYEOFF : PW_SVG_EYE}</button>
                        <button class="pw-copy-btn" title="Copiar password" aria-label="Copiar password" onclick="pwCopy('${encodeURIComponent(p.password || '')}', this)">${PW_SVG_COPY}</button>
                    </span>
                </div>
                ${p.notes ? `<div class="pw-field-row"><span class="pw-field-label">Notas</span><span class="pw-field-value">${escapeHtml(p.notes)}</span></div>` : ''}
            </div>
            <div class="pw-card-actions">
                <button class="pw-action-btn" title="Editar" aria-label="Editar" onclick='openPasswordModal(${jsonStr(p)})'>${PW_SVG_EDIT}</button>
                <button class="pw-action-btn del" title="Eliminar" aria-label="Eliminar" onclick="deletePassword(${p.id})">${PW_SVG_DEL}</button>
            </div>
        </div>`;
    }).join('');
}

function togglePwVisibility(id) {
    if (state.pwShowSet.has(id)) state.pwShowSet.delete(id);
    else state.pwShowSet.add(id);
    renderPasswords();
}

async function pwCopy(raw, btn) {
    const text = decodeURIComponent(raw || '');
    try {
        await navigator.clipboard.writeText(text);
        if (btn) {
            btn.classList.add('copied');
            setTimeout(() => btn.classList.remove('copied'), 1200);
        }
        notify('Copiado al portapapeles', 'success');
    } catch (_err) {
        notify('No se pudo copiar', 'info');
    }
}

function openPasswordModal(item) {
    state.pwEditId = item?.id || null;

    const title = document.getElementById('pw-modal-title');
    const name = document.getElementById('pw-name');
    const url = document.getElementById('pw-url');
    const username = document.getElementById('pw-username');
    const password = document.getElementById('pw-password');
    const notes = document.getElementById('pw-notes');
    const parsedDb = parseDbFieldsFromNotes(item?.notes || '');

    const defaultType = normalizePwType(item?.type || 'web', item?.site || '', item?.notes || '');

    if (title) title.textContent = item ? 'Editar contraseña' : 'Nueva contraseña';
    if (name) name.value = item?.site || '';
    if (url) url.value = item?.url || '';
    if (username) username.value = item?.username || '';
    if (password) password.value = item?.password || '';
    if (notes) notes.value = item?.notes || '';
    fillDbFields(parsedDb);

    setActivePwType(defaultType, !item);

    document.getElementById('pw-modal')?.classList.add('active');
}

function closePasswordModal() {
    document.getElementById('pw-modal')?.classList.remove('active');
}

async function savePassword() {
    const site = (document.getElementById('pw-name')?.value || '').trim();
    const url = (document.getElementById('pw-url')?.value || '').trim();
    const username = (document.getElementById('pw-username')?.value || '').trim();
    const password = (document.getElementById('pw-password')?.value || '').trim();
    let notes = (document.getElementById('pw-notes')?.value || '').trim();
    const type = getActivePwType();
    const dbPort = (document.getElementById('pw-db-port')?.value || '').trim();
    const dbName = (document.getElementById('pw-db-name')?.value || '').trim();
    const dbType = (document.getElementById('pw-db-type')?.value || '').trim().toLowerCase();

    if (!site || !username || !password) {
        notify('Completa los campos obligatorios', 'info');
        return;
    }

    if (type === 'db') {
        notes = mergeDbFieldsIntoNotes(notes, {
            dbPort,
            dbName,
            dbType
        });
    }

    if (!pw) return;
    await pw.upsert_password(state.pwEditId || 0, site, username, password, type, url, notes);
    closePasswordModal();
    notify('Contraseña guardada', 'success');
    pwLoad();
}

async function deletePassword(id) {
    window.showConfirm('¿Borrar contraseña?', async (ok) => {
        if (!ok) return;
        if (!pw) return;
        await pw.delete_password(id);
        pwLoad();
    });
}

function generatePassword(length) {
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%*+-?';
    let out = '';
    for (let i = 0; i < length; i += 1) {
        out += chars[Math.floor(Math.random() * chars.length)];
    }
    return out;
}

// ─── Modal de Observaciones ────────────────────────────────────────────────
const _obsState = { table: '', id: 0 };

function openObsModal(table, id, currentNotes) {
    _obsState.table = table;
    _obsState.id = id;
    const ta = document.getElementById('obs-textarea');
    if (ta) ta.value = currentNotes || '';
    document.getElementById('obs-modal')?.classList.add('active');
    setTimeout(() => ta?.focus(), 80);
}

async function saveObsModal() {
    const notes = (document.getElementById('obs-textarea')?.value || '');
    await py.set_item_notes(_obsState.table, _obsState.id, notes);
    closeObsModal();
    // Refrescar la vista activa
    if (_obsState.table === 'agenda') fetchReminders(false);
    else if (_obsState.table === 'shopping') fetchShoppingList(false);
    else if (_obsState.table === 'income') fetchIncomeList(false);
    notify('Observaciones guardadas', 'success');
}

function closeObsModal() {
    document.getElementById('obs-modal')?.classList.remove('active');
}

// Listeners del modal de observaciones
document.getElementById('obs-save-btn')?.addEventListener('click', saveObsModal);
document.getElementById('obs-cancel-btn')?.addEventListener('click', closeObsModal);
document.getElementById('obs-close-btn')?.addEventListener('click', closeObsModal);
document.getElementById('obs-modal')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeObsModal();
});

window.openEditModal = openEditModal;
window.toggleReminder = toggleReminder;
window.deleteReminder = deleteReminder;
window.toggleShopping = toggleShopping;
window.deleteShopping = deleteShopping;
window.toggleIncome = toggleIncome;
window.deleteIncome = deleteIncome;
window.removePmDraft = removePmDraft;
window.deleteKanbanCard = deleteKanbanCard;
window.kbApplyFormat = kbApplyFormat;
window.updateNoteText = updateNoteText;
window.deleteNote = deleteNote;
window.togglePwVisibility = togglePwVisibility;
window.pwCopy = pwCopy;
window.openPasswordModal = openPasswordModal;
window.deletePassword = deletePassword;
window.openObsModal = openObsModal;
