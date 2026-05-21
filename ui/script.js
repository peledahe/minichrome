const navContainer = document.getElementById('nav-container');
const toggleBtn = document.getElementById('toggle-nav');
const urlInput = document.getElementById('url-input');
const tabsBar = document.getElementById('tabs-bar');
const newTabBtn = document.getElementById('new-tab-btn');
const favoriteBtn = document.getElementById('favorite-btn');

let activeTabId = null;

// --- Lógica de Interfaz ---
toggleBtn.addEventListener('click', () => {
    navContainer.classList.toggle('hidden');
});

urlInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        let url = urlInput.value.trim();
        if (url) {
            if (!url.startsWith('http')) {
                url = 'https://www.google.com/search?q=' + encodeURIComponent(url);
            }
            if (window.python_api) window.python_api.load_url(url);
        }
    }
});

// --- Lógica de Pestañas y Favoritos ---
newTabBtn.addEventListener('click', () => {
    if (window.python_api) window.python_api.new_tab("https://www.google.com");
});

favoriteBtn.addEventListener('click', () => {
    if (window.python_api) {
        window.python_api.add_favorite(document.title, urlInput.value);
    }
});

window.add_tab_to_ui = (tabId, title) => {
    const tabEl = document.createElement('div');
    tabEl.className = 'tab';
    tabEl.id = `tab-${tabId}`;
    tabEl.innerText = title || "Nueva Pestaña";
    tabEl.onclick = () => switchTab(tabId);
    tabsBar.appendChild(tabEl);
    switchTab(tabId);
};

function switchTab(tabId) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    const activeTab = document.getElementById(`tab-${tabId}`);
    if (activeTab) activeTab.classList.add('active');
    activeTabId = tabId;
    if (window.python_api) window.python_api.switch_tab(tabId);
}

// --- Controles de Navegación ---
document.getElementById('back-btn').onclick = () => window.python_api?.go_back();
document.getElementById('forward-btn').onclick = () => window.python_api?.go_forward();
document.getElementById('refresh-btn').onclick = () => window.python_api?.reload();

window.update_ui_tab_title = (tabId, title) => {
    const tabEl = document.getElementById(`tab-${tabId}`);
    if (tabEl) tabEl.innerText = title;
};

window.update_url_bar = (url) => {
    urlInput.value = url;
    
    // Lista de aplicaciones internas que deben ocultar la barra de URL
    const appPages = ['arcade.html', 'videoplayer.html', 'imageplayer.html', 'agenda.html'];
    
    // Verificar si la URL actual es una de las aplicaciones
    const isApp = appPages.some(page => url.includes(page));
    
    if (isApp) {
        navContainer.classList.add('hidden');
    } else {
        navContainer.classList.remove('hidden');
    }
};
