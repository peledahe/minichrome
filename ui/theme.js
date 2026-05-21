(() => {
    const THEME_KEY = 'minichrome-theme';
    const VALID_THEMES = new Set(['dark', 'light']);

    let memoryTheme = 'dark';

    function safeGet(key) {
        try {
            return window.localStorage.getItem(key);
        } catch (_) {
            return null;
        }
    }

    function safeSet(key, value) {
        try {
            window.localStorage.setItem(key, value);
        } catch (_) {
            // Ignorar si el storage no esta permitido en este contexto.
        }
    }

    function getStoredTheme() {
        const theme = safeGet(THEME_KEY) || memoryTheme;
        return VALID_THEMES.has(theme) ? theme : 'dark';
    }

    function applyTheme(theme) {
        const resolved = VALID_THEMES.has(theme) ? theme : 'dark';
        memoryTheme = resolved;
        document.documentElement.setAttribute('data-theme', resolved);
        safeSet(THEME_KEY, resolved);

        const toggleBtn = document.getElementById('mc-theme-toggle');
        if (toggleBtn) {
            const nextTheme = resolved === 'dark' ? 'claro' : 'oscuro';
            toggleBtn.textContent = resolved === 'dark' ? '☀' : '☾';
            toggleBtn.title = `Cambiar a modo ${nextTheme}`;
            toggleBtn.setAttribute('aria-label', `Cambiar a modo ${nextTheme}`);
        }
    }

    function toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme') || getStoredTheme();
        applyTheme(currentTheme === 'dark' ? 'light' : 'dark');
    }

    function ensureToggleButton() {
        if (document.getElementById('mc-theme-toggle')) return;

        const btn = document.createElement('button');
        btn.id = 'mc-theme-toggle';
        btn.className = 'mc-theme-toggle';
        btn.type = 'button';
        btn.addEventListener('click', toggleTheme);
        document.body.appendChild(btn);

        applyTheme(document.documentElement.getAttribute('data-theme') || getStoredTheme());
    }

    const initialTheme = getStoredTheme();
    document.documentElement.setAttribute('data-theme', initialTheme);

    document.addEventListener('DOMContentLoaded', () => {
        ensureToggleButton();
    });

    window.addEventListener('storage', (event) => {
        if (event.key === THEME_KEY && VALID_THEMES.has(event.newValue)) {
            applyTheme(event.newValue);
        }
    });

    window.setMinichromeTheme = applyTheme;
})();
