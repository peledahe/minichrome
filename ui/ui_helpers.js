// ui_helpers.js - Funciones globales de UI y controladores de clics delegados para cumplir con CSP en Manifest V3

window.showToast = (msg, type = 'success') => {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast-notification ${type}`;
    
    const textSpan = document.createElement('span');
    textSpan.innerText = msg;
    toast.appendChild(textSpan);
    
    const isSticky = (type === 'success');
    
    if (isSticky) {
        const closeBtn = document.createElement('button');
        closeBtn.className = 'toast-close-btn';
        closeBtn.innerText = '✕';
        
        closeBtn.onclick = (e) => {
            e.stopPropagation();
            toast.classList.add('hide');
            setTimeout(() => toast.remove(), 300);
        };
        toast.appendChild(closeBtn);
    }
    
    container.appendChild(toast);
    
    const duration = isSticky ? 10000 : 3000; // 10 segundos para sticky, 3 segundos para normal
    setTimeout(() => {
        if (toast.parentNode) {
            toast.classList.add('hide');
            setTimeout(() => toast.remove(), 300);
        }
    }, duration);
};

window.showConfirm = (msg, callback) => {
    const modal = document.getElementById('global-confirm-modal');
    if (!modal) return;
    
    document.getElementById('global-confirm-msg').innerText = msg;
    modal.classList.add('active');
    
    const okBtn = document.getElementById('global-confirm-ok');
    const cancelBtn = document.getElementById('global-confirm-cancel');
    
    const cleanup = () => {
        modal.classList.remove('active');
        okBtn.replaceWith(okBtn.cloneNode(true));
        cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    };
    
    okBtn.addEventListener('click', () => { cleanup(); callback(true); });
    cancelBtn.addEventListener('click', () => { cleanup(); callback(false); });
};

// Delegación de eventos para evitar event handlers inline (violaciones de CSP en MV3)
document.addEventListener('click', async (e) => {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    
    const action = el.dataset.action;
    
    try {
        switch (action) {
            case 'toggleReminder': {
                const id = parseInt(el.dataset.id);
                const done = el.dataset.done === 'true';
                if (window.toggleReminder) await window.toggleReminder(id, done);
                break;
            }
            case 'saveCapturedCred': {
                const idx = parseInt(el.dataset.idx);
                if (window.saveCapturedCred) window.saveCapturedCred(idx);
                break;
            }
            case 'discardCapturedCred': {
                const idx = parseInt(el.dataset.idx);
                if (window.discardCapturedCred) await window.discardCapturedCred(idx);
                break;
            }
            case 'openObsModal': {
                const tab = el.dataset.tab;
                const id = parseInt(el.dataset.id);
                const notes = el.dataset.notes || '';
                if (window.openObsModal) window.openObsModal(tab, id, notes);
                break;
            }
            case 'openEditModal': {
                const type = el.dataset.type;
                const json = JSON.parse(el.dataset.json || '{}');
                if (window.openEditModal) window.openEditModal(type, json);
                break;
            }
            case 'deleteReminder': {
                const id = parseInt(el.dataset.id);
                if (window.deleteReminder) await window.deleteReminder(id);
                break;
            }
            case 'publishReminderGCal': {
                const json = JSON.parse(el.dataset.json || '{}');
                if (window.publishReminderToGCal) await window.publishReminderToGCal(json);
                break;
            }
            case 'toggleShopping': {
                const id = parseInt(el.dataset.id);
                const done = el.dataset.done === 'true';
                if (window.toggleShopping) await window.toggleShopping(id, done);
                break;
            }
            case 'deleteShopping': {
                const id = parseInt(el.dataset.id);
                if (window.deleteShopping) await window.deleteShopping(id);
                break;
            }
            case 'toggleIncome': {
                const id = parseInt(el.dataset.id);
                const done = el.dataset.done === 'true';
                if (window.toggleIncome) await window.toggleIncome(id, done);
                break;
            }
            case 'deleteIncome': {
                const id = parseInt(el.dataset.id);
                if (window.deleteIncome) await window.deleteIncome(id);
                break;
            }
            case 'removePmDraft': {
                const idx = parseInt(el.dataset.idx);
                if (window.removePmDraft) window.removePmDraft(idx);
                break;
            }
            case 'toggleKbLabel': {
                const label = el.dataset.label;
                if (window.toggleKbLabel) window.toggleKbLabel(label);
                break;
            }
            case 'editKanbanCard': {
                const id = parseInt(el.dataset.id);
                if (window.editKanbanCard) window.editKanbanCard(id);
                break;
            }
            case 'deleteKanbanCard': {
                const id = parseInt(el.dataset.id);
                if (window.deleteKanbanCard) window.deleteKanbanCard(id);
                break;
            }
            case 'toggleKbLabelFilter': {
                const label = el.dataset.label;
                if (window.toggleKbLabelFilter) await window.toggleKbLabelFilter(label);
                break;
            }
            case 'pwCopy': {
                const text = decodeURIComponent(el.dataset.text || '');
                if (window.pwCopy) window.pwCopy(text, el);
                break;
            }
            case 'togglePwVisibility': {
                const id = parseInt(el.dataset.id);
                if (window.togglePwVisibility) window.togglePwVisibility(id);
                break;
            }
            case 'openPasswordModal': {
                const json = JSON.parse(el.dataset.json || '{}');
                if (window.openPasswordModal) window.openPasswordModal(json);
                break;
            }
            case 'deletePassword': {
                const id = parseInt(el.dataset.id);
                if (window.deletePassword) await window.deletePassword(id);
                break;
            }
        }
    } catch (err) {
        console.error(`Error al ejecutar acción delegada ${action}:`, err);
    }
});

// Vincular dinámicamente los botones de formato Kanban, controles de ventana y modal Acerca de
document.addEventListener('DOMContentLoaded', () => {
    const boldBtn = document.getElementById('kb-tool-bold');
    const italicBtn = document.getElementById('kb-tool-italic');
    const codeBtn = document.getElementById('kb-tool-code');
    const linkBtn = document.getElementById('kb-link-tool-btn');
    const listBtn = document.getElementById('kb-tool-list');

    if (boldBtn) boldBtn.addEventListener('click', () => { if (window.kbApplyFormat) window.kbApplyFormat('bold'); });
    if (italicBtn) italicBtn.addEventListener('click', () => { if (window.kbApplyFormat) window.kbApplyFormat('italic'); });
    if (codeBtn) codeBtn.addEventListener('click', () => { if (window.kbApplyFormat) window.kbApplyFormat('code'); });
    if (linkBtn) linkBtn.addEventListener('click', () => { if (window.kbApplyFormat) window.kbApplyFormat('link'); });
    if (listBtn) listBtn.addEventListener('click', () => { if (window.kbApplyFormat) window.kbApplyFormat('list'); });

    // Controles de ventana
    const minBtn = document.getElementById('btn-minimize');
    const maxBtn = document.getElementById('btn-maximize');
    const closeBtn = document.getElementById('btn-close');

    if (minBtn) {
        minBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (window.desktop && window.desktop.minimize) window.desktop.minimize();
            else if (window.py && window.py.window_minimize) window.py.window_minimize();
        });
    }

    if (maxBtn) {
        maxBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (window.desktop && window.desktop.maximize) window.desktop.maximize();
            else if (window.py && window.py.window_maximize) window.py.window_maximize();
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (window.desktop && window.desktop.close) window.desktop.close();
            else if (window.py && window.py.window_close) window.py.window_close();
            else window.close();
        });
    }

    // Modal Acerca de
    const aboutBtn = document.getElementById('btn-about');
    const aboutModal = document.getElementById('organizer-about-modal');
    const aboutCloseBtn = document.getElementById('organizer-about-close-btn');

    if (aboutBtn && aboutModal) {
        aboutBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            aboutModal.style.display = 'flex';
        });
    }

    if (aboutCloseBtn && aboutModal) {
        aboutCloseBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            aboutModal.style.display = 'none';
        });
    }

    if (aboutModal) {
        aboutModal.addEventListener('click', (e) => {
            if (e.target === aboutModal) aboutModal.style.display = 'none';
        });
    }
});

// Función para inicializar inmediatamente los controles
function initHeaderAndWindowControls() {
    const minBtn = document.getElementById('btn-minimize');
    const maxBtn = document.getElementById('btn-maximize');
    const closeBtn = document.getElementById('btn-close');
    const aboutBtn = document.getElementById('btn-about');
    const aboutModal = document.getElementById('organizer-about-modal');
    const aboutCloseBtn = document.getElementById('organizer-about-close-btn');

    if (minBtn) {
        minBtn.onclick = (e) => {
            e.preventDefault();
            if (window.desktop && window.desktop.minimize) window.desktop.minimize();
            else if (window.py && window.py.window_minimize) window.py.window_minimize();
        };
    }
    if (maxBtn) {
        maxBtn.onclick = (e) => {
            e.preventDefault();
            if (window.desktop && window.desktop.maximize) window.desktop.maximize();
            else if (window.py && window.py.window_maximize) window.py.window_maximize();
        };
    }
    if (closeBtn) {
        closeBtn.onclick = (e) => {
            e.preventDefault();
            if (window.desktop && window.desktop.close) window.desktop.close();
            else if (window.py && window.py.window_close) window.py.window_close();
            else window.close();
        };
    }
    if (aboutBtn && aboutModal) {
        aboutBtn.onclick = (e) => {
            e.preventDefault();
            aboutModal.style.display = 'flex';
        };
    }
    if (aboutCloseBtn && aboutModal) {
        aboutCloseBtn.onclick = (e) => {
            e.preventDefault();
            aboutModal.style.display = 'none';
        };
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHeaderAndWindowControls);
} else {
    initHeaderAndWindowControls();
}
