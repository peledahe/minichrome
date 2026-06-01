let pyBridge = null;
let pwBridge = null;
let allPasswords = [];
let currentEditId = null;
let deleteId = null;
let autoSavePolicy = 'ask';

const pwdModal = document.getElementById('pwd-modal');
const confirmModal = document.getElementById('confirm-modal');
const searchInput = document.getElementById('search-input');
const autoSavePolicySelect = document.getElementById('pw-autosave-policy');

function normalizePolicy(policy) {
    const val = String(policy || 'ask').toLowerCase();
    return ['ask', 'always', 'never'].includes(val) ? val : 'ask';
}

function policyMessage(policy) {
    if (policy === 'always') return 'Autoguardado: siempre guardar sin preguntar';
    if (policy === 'never') return 'Autoguardado: nunca guardar automaticamente';
    return 'Autoguardado: preguntar antes de guardar';
}

function escapeHtml(str) {
    return String(str || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function mapTypeLabel(type) {
    return type === 'app' ? 'APP' : 'WEB';
}

function updateTypeUi(type) {
    const siteLabel = document.getElementById('input-site-label');
    const siteInput = document.getElementById('input-site');
    const urlRow = document.getElementById('input-url-row');

    if (siteLabel) siteLabel.textContent = type === 'app' ? 'Aplicación' : 'Sitio Web';
    if (siteInput) siteInput.placeholder = type === 'app' ? 'ej: Steam, Spotify, Photoshop' : 'ej: google.com';
    if (urlRow) urlRow.style.display = type === 'web' ? '' : 'none';

    document.querySelectorAll('.pw-type-btn').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.type === type);
    });
}

function setBrowserBarVisible(visible) {
    if (!pyBridge) return;
    if (!visible && typeof pyBridge.hide_browser_bar === 'function') {
        pyBridge.hide_browser_bar();
    }
}

// Inicializar QWebChannel
new QWebChannel(qt.webChannelTransport, (channel) => {
    pyBridge = channel.objects.py;
    pwBridge = channel.objects.pw;
    if (pwBridge && pwBridge.updated && typeof pwBridge.updated.connect === 'function') {
        pwBridge.updated.connect(() => {
            loadPasswords();
        });
    }
    wireEvents();
    loadAutoSavePolicy();
    loadPasswords();
    setBrowserBarVisible(false);
});

window.addEventListener('pageshow', () => {
    loadPasswords();
});

document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        loadPasswords();
    }
});

window.addEventListener('focus', () => {
    loadPasswords();
});

function wireEvents() {
    document.getElementById('btn-add-pwd').onclick = () => {
        currentEditId = null;
        document.getElementById('modal-title').textContent = 'Agregar Clave';
        document.getElementById('input-site').value = '';
        document.getElementById('input-url').value = '';
        document.getElementById('input-user').value = '';
        document.getElementById('input-pass').value = '';
        document.getElementById('input-notes').value = '';
        updateTypeUi('web');
        pwdModal.classList.add('active');
    };

    document.getElementById('btn-modal-cancel').onclick = () => pwdModal.classList.remove('active');

    document.getElementById('btn-modal-save').onclick = savePassword;

    document.getElementById('btn-confirm-cancel').onclick = () => confirmModal.classList.remove('active');

    document.getElementById('btn-confirm-ok').onclick = async () => {
        if (!deleteId || !pwBridge) return;
        await pwBridge.delete_password(deleteId);
        confirmModal.classList.remove('active');
        showStickyNotification('Clave eliminada');
        loadPasswords();
    };

    document.getElementById('btn-back-home').onclick = () => {
        window.location.href = 'newtab.html';
    };

    document.querySelectorAll('.pw-type-btn').forEach((btn) => {
        btn.addEventListener('click', () => updateTypeUi(btn.dataset.type || 'web'));
    });

    searchInput.addEventListener('input', (e) => {
        const term = (e.target.value || '').toLowerCase();
        const filtered = allPasswords.filter((p) => {
            return (p.site || '').toLowerCase().includes(term)
                || (p.username || '').toLowerCase().includes(term)
                || (p.url || '').toLowerCase().includes(term)
                || (p.notes || '').toLowerCase().includes(term);
        });
        renderPasswords(filtered);
    });

    if (autoSavePolicySelect) {
        autoSavePolicySelect.addEventListener('change', async (e) => {
            if (!pwBridge || typeof pwBridge.set_auto_save_policy !== 'function') return;
            autoSavePolicy = normalizePolicy(e.target.value);
            await pwBridge.set_auto_save_policy(autoSavePolicy);
            showStickyNotification(`${policyMessage(autoSavePolicy)}. Manual siempre permitido.`);
        });
    }
}

async function loadAutoSavePolicy() {
    if (!pwBridge || typeof pwBridge.get_auto_save_policy !== 'function') return;
    try {
        const policy = await pwBridge.get_auto_save_policy();
        autoSavePolicy = normalizePolicy(policy);
        if (autoSavePolicySelect) autoSavePolicySelect.value = autoSavePolicy;
    } catch (_err) {
        autoSavePolicy = 'ask';
        if (autoSavePolicySelect) autoSavePolicySelect.value = autoSavePolicy;
    }
}

async function loadPasswords() {
    if (!pwBridge) return;
    allPasswords = await pwBridge.get_passwords();
    renderPasswords(allPasswords);
}

function renderPasswords(passwords) {
    const list = document.getElementById('password-list');
    if (!passwords.length) {
        list.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1;">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
                <p>No tienes claves guardadas aún.</p>
            </div>
        `;
        return;
    }

    list.innerHTML = '';
    passwords.forEach((p) => {
        const card = document.createElement('div');
        card.className = 'password-card';
        const safeType = (p.type === 'app' || p.type === 'web') ? p.type : (String(p.site || '').includes('.') ? 'web' : 'app');
        const faviconDomain = safeType === 'web' ? (p.site || p.url || '') : 'app.local';
        const favicon = `https://www.google.com/s2/favicons?domain=${encodeURIComponent(faviconDomain)}&sz=64`;
        const encodedUser = encodeURIComponent(p.username || '');
        const encodedPass = encodeURIComponent(p.password || '');
        const jsonArg = JSON.stringify({
            id: p.id,
            site: p.site || '',
            username: p.username || '',
            password: p.password || '',
            type: safeType,
            url: p.url || '',
            notes: p.notes || ''
        }).replace(/"/g, '&quot;');

        card.innerHTML = `
            <div class="card-header">
                <div class="site-icon">
                    <img src="${favicon}" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%236c5ce7%22 stroke-width=%222%22><rect x=%223%22 y=%2211%22 width=%2218%22 height=%2211%22 rx=%222%22 ry=%222%22></rect><path d=%22M7 11V7a5 5 0 0 1 10 0v4%22></path></svg>'">
                </div>
                <div class="site-info">
                    <h3>${escapeHtml(p.site)} <span class="type-badge">${mapTypeLabel(safeType)}</span></h3>
                    <p>${safeType === 'web' ? 'Sitio web' : 'Aplicación'}</p>
                </div>
            </div>
            ${safeType === 'web' && p.url ? `<div class="field-url">${escapeHtml(p.url)}</div>` : ''}
            <div class="field">
                <div class="field-label">Usuario</div>
                <div class="field-value-wrap">
                    <div class="field-value">${escapeHtml(p.username)}</div>
                    <div class="field-action" onclick="copyToClipboard('${encodedUser}', 'Usuario copiado')">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                    </div>
                </div>
            </div>
            <div class="field">
                <div class="field-label">Contraseña</div>
                <div class="field-value-wrap">
                    <div class="field-value" id="pass-${p.id}">••••••••</div>
                    <div style="display: flex; gap: 8px;">
                        <div class="field-action" onclick="togglePassVisibility(${p.id}, '${encodedPass}')">
                            <svg id="eye-${p.id}" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                        </div>
                        <div class="field-action" onclick="copyToClipboard('${encodedPass}', 'Clave copiada')">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                        </div>
                    </div>
                </div>
            </div>
            ${p.notes ? `<div class="field"><div class="field-label">Notas</div><div class="field-value-wrap"><div class="field-value">${escapeHtml(p.notes)}</div></div></div>` : ''}
            <div class="card-actions">
                <button class="action-btn" onclick="editPassword(${jsonArg})">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                </button>
                <button class="action-btn delete" onclick="askDeletePassword(${p.id})">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
            </div>
        `;
        list.appendChild(card);
    });
}

function togglePassVisibility(id, encodedPass) {
    const el = document.getElementById(`pass-${id}`);
    const eye = document.getElementById(`eye-${id}`);
    if (!el || !eye) return;

    if (el.textContent === '••••••••') {
        el.textContent = decodeURIComponent(encodedPass || '');
        eye.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line>';
    } else {
        el.textContent = '••••••••';
        eye.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle>';
    }
}

function copyToClipboard(encodedText, msg) {
    const text = decodeURIComponent(encodedText || '');
    navigator.clipboard.writeText(text).then(() => {
        showStickyNotification(msg);
    });
}

function showStickyNotification(msg) {
    const container = document.getElementById('notification-container');
    const notif = document.createElement('div');
    notif.className = 'notification';
    notif.innerHTML = `
        <div style="display: flex; align-items: center; gap: 10px;">
            <div style="background: var(--accent); border-radius: 50%; padding: 4px; display: flex;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>
            </div>
            <span>${escapeHtml(msg)}</span>
        </div>
    `;
    container.appendChild(notif);
    setTimeout(() => {
        notif.style.opacity = '0';
        notif.style.transform = 'translateX(20px)';
        notif.style.transition = 'all 0.3s ease';
        setTimeout(() => notif.remove(), 300);
    }, 3000);
}

function editPassword(p) {
    currentEditId = p.id;
    document.getElementById('modal-title').textContent = 'Editar Clave';
    document.getElementById('input-site').value = p.site || '';
    document.getElementById('input-url').value = p.url || '';
    document.getElementById('input-user').value = p.username || '';
    document.getElementById('input-pass').value = p.password || '';
    document.getElementById('input-notes').value = p.notes || '';
    updateTypeUi(p.type || 'web');
    pwdModal.classList.add('active');
}

async function savePassword() {
    const site = document.getElementById('input-site').value.trim();
    const user = document.getElementById('input-user').value.trim();
    const pass = document.getElementById('input-pass').value.trim();
    const type = document.querySelector('.pw-type-btn.active')?.dataset.type || 'web';
    const url = document.getElementById('input-url').value.trim();
    const notes = document.getElementById('input-notes').value.trim();

    if (!site || !user || !pass) return;
    if (!pwBridge) return;

    await pwBridge.upsert_password(currentEditId || 0, site, user, pass, type, url, notes);
    pwdModal.classList.remove('active');
    showStickyNotification(currentEditId ? 'Clave actualizada' : 'Clave guardada');
    loadPasswords();
}

function askDeletePassword(id) {
    deleteId = id;
    confirmModal.classList.add('active');
}

window.togglePassVisibility = togglePassVisibility;
window.copyToClipboard = copyToClipboard;
window.editPassword = editPassword;
window.askDeletePassword = askDeletePassword;
