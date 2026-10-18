/* Minichrome: completa las APIs chrome.* que QtWebEngine no implementa.
 *
 * QtWebEngine solo trae runtime, storage, i18n, alarms, management y un tabs
 * mínimo (sin query). Muchas extensiones llaman a otras APIs al arrancar
 * (commands, contextMenus, action…) y su service worker muere con un
 * TypeError. Este archivo se carga antes que el código de la extensión, tanto
 * en el service worker (envoltorio generado por extensions.py) como en cada
 * página HTML de la extensión, y solo rellena lo que falta.
 *
 * En el popup, Minichrome expone el objeto `mcext` por QWebChannel para las
 * operaciones sobre la pestaña activa (tabs.query, captureVisibleTab,
 * scripting…). Fuera del popup esas llamadas devuelven valores neutros.
 */
(function () {
    'use strict';
    var g = typeof globalThis !== 'undefined' ? globalThis : self;
    if (g.addEventListener) {
        g.addEventListener('error', function (e) {
            console.error('[UNCAUGHT ERROR]', e.message, e.filename, e.lineno, e.error);
        });
        g.addEventListener('unhandledrejection', function (e) {
            console.error('[UNHANDLED REJECTION]', e.reason && (e.reason.stack || e.reason.message) || e.reason);
        });
    }

    // Mock seguro de DOM para Service Workers migrados de MV2 que llaman a document.*
    if (typeof document === 'undefined') {
        var dummyElement = function () {
            return {
                style: {},
                dataset: {},
                classList: { add: function () {}, remove: function () {}, toggle: function () {}, contains: function () { return false; } },
                setAttribute: function () {},
                getAttribute: function () { return ''; },
                removeAttribute: function () {},
                addEventListener: function (evt, fn) { if (evt === 'load') setTimeout(fn, 10); },
                removeEventListener: function () {},
                appendChild: function (c) { return c; },
                removeChild: function (c) { return c; },
                replaceWith: function () {},
                querySelector: function () { return null; },
                querySelectorAll: function () { return []; },
                width: 16, height: 16,
                set src(v) { this._src = v; },
                get src() { return this._src || ''; }
            };
        };
        g.document = {
            createElement: dummyElement,
            createElementNS: dummyElement,
            createDocumentFragment: dummyElement,
            getElementById: function () { return null; },
            querySelector: function () { return null; },
            querySelectorAll: function () { return []; },
            head: dummyElement(),
            body: dummyElement(),
            documentElement: dummyElement(),
            addEventListener: function () {},
            removeEventListener: function () {}
        };
    } else {
        // En ventanas/popups, evitar que verificaciones de visibilidad bloqueen el renderizado
        try {
            Object.defineProperty(document, 'hidden', { get: function () { return false; }, configurable: true });
            Object.defineProperty(document, 'visibilityState', { get: function () { return 'visible'; }, configurable: true });
        } catch (e) {}
    }

    if (g.__minichromeShim || typeof chrome === 'undefined' || !chrome.runtime) return;
    g.__minichromeShim = true;

    var EXT_ID = chrome.runtime.id;
    var noConnection = 'Could not establish connection. Receiving end does not exist.';

    // Función con soporte de callback (estilo MV2) y de promesa (estilo MV3).
    function api(fn) {
        return function () {
            var args = Array.prototype.slice.call(arguments);
            var cb = typeof args[args.length - 1] === 'function' ? args.pop() : null;
            var p = new Promise(function (resolve) { resolve(fn.apply(null, args)); });
            if (!cb) return p;
            p.then(function (r) { cb(r); }, function (e) {
                console.warn('[minichrome] ' + (e && e.message || e));
                cb(undefined);
            });
        };
    }
    function fail(msg) { return api(function () { throw new Error(msg); }); }
    function ok(value) { return api(function () { return value; }); }
    function makeEvent() {
        var ls = [];
        return {
            addListener: function (fn) { if (ls.indexOf(fn) < 0) ls.push(fn); },
            removeListener: function (fn) { var i = ls.indexOf(fn); if (i >= 0) ls.splice(i, 1); },
            hasListener: function (fn) { return ls.indexOf(fn) >= 0; },
            hasListeners: function () { return ls.length > 0; },
            _dispatch: function () {
                var args = arguments;
                ls.slice().forEach(function (fn) {
                    try { fn.apply(null, args); } catch (e) { console.error(e); }
                });
            }
        };
    }
    function setProp(obj, key, value) {
        try { obj[key] = value; if (obj[key] === value) return; } catch (e) {}
        try { Object.defineProperty(obj, key, { value: value, configurable: true, writable: true, enumerable: true }); return; } catch (e) {}
        try {
            var proto = Object.getPrototypeOf(obj);
            if (proto) Object.defineProperty(proto, key, { value: value, configurable: true, writable: true, enumerable: true });
        } catch (e) {}
    }
    function ns(name) {
        if (!chrome[name]) setProp(chrome, name, {});
        return chrome[name];
    }
    function fill(obj, members) {
        Object.keys(members).forEach(function (k) {
            if (obj[k] === undefined) setProp(obj, k, members[k]);
        });
    }

    // ── Puente con Minichrome ────────────────────────────────────────────────
    // mcext solo existe en el popup; mcmedia (reproductor nativo) en cualquier
    // página de extensión. El shim es el único que abre el QWebChannel: el
    // código de la extensión usa los objetos con `await minichrome.objects`.
    var bridge = null;
    var channelObjects = new Promise(function (resolve) {
        if (typeof QWebChannel === 'undefined' || typeof qt === 'undefined' || !qt.webChannelTransport) {
            resolve(null);
            return;
        }
        new QWebChannel(qt.webChannelTransport, function (channel) { resolve(channel.objects); });
        setTimeout(function () { resolve(null); }, 2000);
    });
    if (typeof window !== 'undefined') g.minichrome = { objects: channelObjects };
    var bridgeReady = new Promise(function (resolve) {
        channelObjects.then(function (objects) {
            bridge = objects && objects.mcext || null;
            if (bridge) {
                bridge.scriptResult.connect(function (reqId, json) {
                    var p = pending[reqId];
                    if (!p) return;
                    delete pending[reqId];
                    var res = JSON.parse(json || '{}');
                    if (res.error) p.reject(new Error(res.error)); else p.resolve(res.result);
                });
            }
            resolve(bridge);
        });
    });
    var pending = {};
    var reqSeq = 0;
    function call(method) {
        var args = Array.prototype.slice.call(arguments, 1);
        return bridgeReady.then(function (b) {
            if (!b) return null;
            return new Promise(function (resolve) { b[method].apply(b, args.concat([resolve])); });
        });
    }
    function callAsync(method) {
        var args = Array.prototype.slice.call(arguments, 1);
        return bridgeReady.then(function (b) {
            if (!b) throw new Error('No disponible fuera del popup en Minichrome');
            var id = ++reqSeq;
            return new Promise(function (resolve, reject) {
                pending[id] = { resolve: resolve, reject: reject };
                b[method].apply(b, [id].concat(args));
            });
        });
    }
    function activeTab() {
        return call('activeTab').then(function (json) { return json ? JSON.parse(json) : null; });
    }
    function openUrl(url) {
        url = url ? new URL(url, location.href).href : 'about:blank';
        return bridgeReady.then(function (b) {
            if (b) b.openTab(url);
            else if (typeof clients !== 'undefined' && clients.openWindow) return clients.openWindow(url).catch(function () {});
            else if (typeof g.open === 'function') g.open(url, '_blank');
        });
    }

    // ── iframes que el sitio no deja incrustar ───────────────────────────────
    // En Chrome la extensión quita X-Frame-Options/frame-ancestors con
    // declarativeNetRequest (Black Menu: Gemini, Gmail, Calendar…). QtWebEngine
    // no puede; WebPage.javaScriptConsoleMessage detecta el rechazo y llama a
    // esta función, que tapa el iframe con un acceso para abrirlo en una pestaña.
    if (typeof document !== 'undefined' && document.createElement) {
        var siteOf = function (host) { return host.split('.').slice(-2).join('.'); };
        var cleanFrameUrl = function (src) {
            try {
                var u = new URL(src);
                Array.from(u.searchParams.keys()).forEach(function (k) {
                    if (/^bm_/.test(k)) u.searchParams.delete(k); // parámetros internos de Black Menu
                });
                return u.href;
            } catch (e) { return src; }
        };
        var restoreFrame = function (frame) {
            if (frame.__mcBlocked) {
                frame.__mcBlocked.replaceWith(frame);
                frame.__mcBlocked = null;
            }
        };
        var coverFrame = function (frame) {
            if (frame.__mcBlocked) return;
            var url = cleanFrameUrl(frame.src);
            var box = document.createElement('div');
            box.className = frame.className;
            box.style.cssText = 'flex:1 1 auto;align-self:stretch;width:100%;height:100%;min-height:160px;' +
                'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;' +
                'padding:24px;box-sizing:border-box;text-align:center;font:13px/1.5 sans-serif;color:inherit;';
            var msg = document.createElement('div');
            msg.textContent = new URL(url).host + ' no permite mostrarse dentro de la extensión en Minichrome.';
            msg.style.opacity = '0.75';
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = 'Abrir en una pestaña';
            btn.style.cssText = 'padding:8px 18px;border:none;border-radius:8px;cursor:pointer;' +
                'background:#1a73e8;color:#fff;font:600 13px sans-serif;';
            btn.addEventListener('click', function () { openUrl(url); });
            box.appendChild(msg);
            box.appendChild(btn);
            // Se saca del documento (no basta con ocultarlo: el frame rechazado
            // seguía vivo y QtWebEngine caía con otra pestaña del mismo sitio).
            frame.replaceWith(box);
            frame.__mcBlocked = box;
            // La extensión suele reutilizar el iframe para otro servicio: al
            // cambiar de src vuelve a su sitio y se intenta de nuevo.
            new MutationObserver(function (_m, obs) { obs.disconnect(); restoreFrame(frame); })
                .observe(frame, { attributes: true, attributeFilter: ['src'] });
        };
        g.__minichromeFrameBlocked = function (blockedUrl) {
            var blocked;
            try { blocked = new URL(blockedUrl); } catch (e) { return; }
            var frames = Array.prototype.filter.call(document.querySelectorAll('iframe'), function (f) {
                return /^https?:/.test(f.src || '');
            });
            // La URL rechazada puede ser la de una redirección (inicio de sesión,
            // consentimiento): primero el mismo origen, luego el mismo sitio.
            var match = frames.filter(function (f) { return new URL(f.src).origin === blocked.origin; });
            if (!match.length) {
                match = frames.filter(function (f) { return siteOf(new URL(f.src).hostname) === siteOf(blocked.hostname); });
            }
            if (!match.length && frames.length === 1) match = frames;
            match.forEach(coverFrame);
        };
    }

    // ── storage: sync y managed ──────────────────────────────────────────────
    // QtWebEngine declara storage.sync pero responde "sync is not available";
    // se guarda en storage.local con prefijo para no mezclar claves.
    var st = chrome.storage;
    if (st && st.local) {
        var SYNC = '__mc_sync__:';
        var local = st.local;
        var nGet = local.get.bind(local), nSet = local.set.bind(local), nRemove = local.remove.bind(local);
        var isSync = function (k) { return k.indexOf(SYNC) === 0; };
        var keyList = function (keys) { return typeof keys === 'string' ? [keys] : Array.isArray(keys) ? keys : Object.keys(keys); };

        var syncArea = {
            QUOTA_BYTES: 102400, QUOTA_BYTES_PER_ITEM: 8192, MAX_ITEMS: 512,
            get: api(function (keys) {
                if (keys === null || keys === undefined) {
                    return nGet(null).then(function (all) {
                        var out = {};
                        Object.keys(all).forEach(function (k) { if (isSync(k)) out[k.slice(SYNC.length)] = all[k]; });
                        return out;
                    });
                }
                var defaults = (typeof keys === 'object' && !Array.isArray(keys)) ? keys : {};
                return nGet(keyList(keys).map(function (k) { return SYNC + k; })).then(function (raw) {
                    var out = {};
                    keyList(keys).forEach(function (k) {
                        if ((SYNC + k) in raw) out[k] = raw[SYNC + k];
                        else if (k in defaults) out[k] = defaults[k];
                    });
                    return out;
                });
            }),
            set: api(function (items) {
                var out = {};
                Object.keys(items || {}).forEach(function (k) { out[SYNC + k] = items[k]; });
                return nSet(out);
            }),
            remove: api(function (keys) { return nRemove(keyList(keys).map(function (k) { return SYNC + k; })); }),
            clear: api(function () {
                return nGet(null).then(function (all) { return nRemove(Object.keys(all).filter(isSync)); });
            }),
            getBytesInUse: ok(0),
            setAccessLevel: ok(undefined),
            onChanged: makeEvent()
        };

        // local no debe ver las claves de sync.
        setProp(local, 'get', api(function (keys) {
            return nGet(keys === undefined ? null : keys).then(function (all) {
                if (keys === null || keys === undefined) {
                    Object.keys(all).forEach(function (k) { if (isSync(k)) delete all[k]; });
                }
                return all;
            });
        }));
        setProp(local, 'clear', api(function () {
            return nGet(null).then(function (all) {
                return nRemove(Object.keys(all).filter(function (k) { return !isSync(k); }));
            });
        }));

        // Reparte los cambios de local entre los eventos de local y de sync.
        var allChanged = makeEvent();
        var localChanged = makeEvent();
        st.onChanged.addListener(function (changes, area) {
            if (area !== 'local') { allChanged._dispatch(changes, area); return; }
            var l = {}, s = {}, hasL = false, hasS = false;
            Object.keys(changes).forEach(function (k) {
                if (isSync(k)) { s[k.slice(SYNC.length)] = changes[k]; hasS = true; }
                else { l[k] = changes[k]; hasL = true; }
            });
            if (hasL) { allChanged._dispatch(l, 'local'); localChanged._dispatch(l); }
            if (hasS) { allChanged._dispatch(s, 'sync'); syncArea.onChanged._dispatch(s); }
        });
        setProp(st, 'onChanged', allChanged);
        setProp(local, 'onChanged', localChanged);
        setProp(st, 'sync', syncArea);

        if (!st.managed || !st.managed.get) setProp(st, 'managed', {});
        fill(st.managed, { get: ok({}), getBytesInUse: ok(0), onChanged: makeEvent() });
        // Siempre vacío: no hay políticas administradas en Minichrome.
        setProp(st.managed, 'get', ok({}));
    }

    // ── runtime ──────────────────────────────────────────────────────────────
    fill(chrome.runtime, {
        setUninstallURL: ok(undefined),
        openOptionsPage: api(function () {
            var mf = chrome.runtime.getManifest();
            var page = (mf.options_ui && mf.options_ui.page) || mf.options_page;
            if (!page) throw new Error('La extensión no tiene página de opciones');
            return openUrl(chrome.runtime.getURL(page));
        }),
        getPlatformInfo: api(function () {
            return { os: 'linux', arch: 'x86-64', nacl_arch: 'x86-64' };
        }),
        ContextType: {
            BACKGROUND: 'BACKGROUND',
            POPUP: 'POPUP',
            SIDE_PANEL: 'SIDE_PANEL',
            TAB: 'TAB',
            OFFSCREEN_DOCUMENT: 'OFFSCREEN_DOCUMENT'
        },
        getContexts: api(function () { return []; }),
        onMessageExternal: makeEvent(),
        onStartup: makeEvent(),
        onInstalled: makeEvent(),
        onSuspend: makeEvent(),
        onUpdateAvailable: makeEvent()
    });

    // ── tabs ─────────────────────────────────────────────────────────────────
    var tabs = ns('tabs');
    function asList(t) { return t ? [t] : []; }
    fill(tabs, {
        query: api(function () { return activeTab().then(asList); }),
        get: api(function () { return activeTab(); }),
        getCurrent: api(function () { return undefined; }),
        create: api(function (props) {
            props = props || {};
            return openUrl(props.url).then(function () { return { id: -1, url: props.url || '', active: true }; });
        }),
        update: api(function (tabId, props) { return activeTab(); }),
        remove: ok(undefined),
        reload: ok(undefined),
        sendMessage: fail(noConnection),
        connect: function () { throw new Error(noConnection); },
        captureVisibleTab: api(function (windowId, options) {
            if (windowId && typeof windowId === 'object') options = windowId;
            var fmt = (options && options.format) || 'jpeg';
            var quality = (options && options.quality) || 90;
            return call('captureVisibleTab', fmt, quality).then(function (url) {
                if (!url) throw new Error('No se pudo capturar la pestaña');
                return url;
            });
        }),
        onActivated: makeEvent(), onUpdated: makeEvent(), onCreated: makeEvent(),
        onRemoved: makeEvent(), onReplaced: makeEvent(), onHighlighted: makeEvent()
    });

    // ── scripting (se ejecuta en la pestaña activa, mundo aislado) ───────────
    var scripting = ns('scripting');
    fill(scripting, {
        executeScript: api(function (inj) {
            inj = inj || {};
            var code;
            if (inj.func) {
                code = '(' + inj.func.toString() + ').apply(null, ' + JSON.stringify(inj.args || []) + ')';
                return callAsync('executeScript', code, '').then(function (r) { return [{ frameId: 0, result: r }]; });
            }
            if (inj.files && inj.files.length) {
                return callAsync('executeScript', '', JSON.stringify(inj.files)).then(function (r) { return [{ frameId: 0, result: r }]; });
            }
            throw new Error('executeScript requiere func o files');
        }),
        insertCSS: api(function (inj) {
            inj = inj || {};
            return callAsync('insertCSS', inj.css || '', JSON.stringify(inj.files || [])).then(function () { return undefined; });
        }),
        removeCSS: ok(undefined),
        registerContentScripts: ok(undefined),
        unregisterContentScripts: ok(undefined),
        getRegisteredContentScripts: ok([])
    });

    // ── windows (Minichrome tiene una sola ventana) ──────────────────────────
    var WIN = { id: 1, focused: true, incognito: false, alwaysOnTop: false, state: 'normal', type: 'normal', left: 0, top: 0, width: 1280, height: 800 };
    var windows = ns('windows');
    fill(windows, {
        WINDOW_ID_NONE: -1, WINDOW_ID_CURRENT: -2,
        get: ok(WIN), getCurrent: ok(WIN), getLastFocused: ok(WIN), getAll: ok([WIN]),
        create: api(function (data) {
            var url = data && data.url;
            if (Array.isArray(url)) url = url[0];
            return openUrl(url).then(function () { return WIN; });
        }),
        update: ok(WIN),
        remove: ok(undefined),
        onCreated: makeEvent(), onRemoved: makeEvent(), onFocusChanged: makeEvent(), onBoundsChanged: makeEvent()
    });

    // ── APIs de interfaz sin equivalente en Minichrome ───────────────────────
    var action = ns('action');
    fill(action, {
        setBadgeText: ok(undefined), getBadgeText: ok(''),
        setBadgeBackgroundColor: ok(undefined), getBadgeBackgroundColor: ok([0, 0, 0, 0]),
        setBadgeTextColor: ok(undefined), setTitle: ok(undefined), getTitle: ok(''),
        setIcon: ok(undefined), setPopup: ok(undefined), getPopup: ok(''),
        enable: ok(undefined), disable: ok(undefined), isEnabledInTab: ok(true),
        openPopup: fail('openPopup no está disponible en Minichrome'),
        getUserSettings: ok({ isOnToolbar: true }),
        onClicked: makeEvent()
    });
    if (!chrome.browserAction) setProp(chrome, 'browserAction', action);

    fill(ns('commands'), { getAll: ok([]), onCommand: makeEvent() });

    var menus = ns('contextMenus');
    fill(menus, {
        create: function (props, cb) { if (typeof cb === 'function') setTimeout(cb, 0); return (props && props.id) || 0; },
        update: ok(undefined), remove: ok(undefined), removeAll: ok(undefined),
        onClicked: makeEvent()
    });

    fill(ns('sidePanel'), {
        open: fail('El panel lateral no está disponible en Minichrome'),
        setOptions: ok(undefined), getOptions: ok({ enabled: false }),
        setPanelBehavior: ok(undefined), getPanelBehavior: ok({ openPanelOnActionClick: false }),
        onOpened: makeEvent()
    });

    fill(ns('notifications'), {
        create: api(function (id) { return typeof id === 'string' ? id : 'mc-' + Date.now(); }),
        clear: ok(true), getAll: ok({}), update: ok(true),
        onClicked: makeEvent(), onClosed: makeEvent(), onButtonClicked: makeEvent()
    });

    // ── permissions: lo declarado en el manifest se considera concedido ──────
    var mfPerms = (function () {
        var mf = chrome.runtime.getManifest() || {};
        return { permissions: (mf.permissions || []).concat(mf.optional_permissions || []), origins: (mf.host_permissions || []).concat(mf.optional_host_permissions || []) };
    })();
    fill(ns('permissions'), {
        contains: ok(true), request: ok(true), remove: ok(true), getAll: ok(mfPerms),
        onAdded: makeEvent(), onRemoved: makeEvent()
    });

    // ── identity: sin cuentas de Chrome ──────────────────────────────────────
    fill(ns('identity'), {
        getRedirectURL: function (path) { return 'https://' + EXT_ID + '.chromiumapp.org/' + (path || ''); },
        getAuthToken: fail('chrome.identity.getAuthToken no está disponible en Minichrome'),
        removeCachedAuthToken: ok(undefined),
        clearAllCachedAuthTokens: ok(undefined),
        launchWebAuthFlow: fail('chrome.identity.launchWebAuthFlow no está disponible en Minichrome'),
        getProfileUserInfo: ok({ email: '', id: '' }),
        onSignInChanged: makeEvent()
    });

    // ── extension: compatibilidad histórica MV2/MV3 (getViews, getURL…) ──────
    var extApi = ns('extension');
    fill(extApi, {
        getViews: function (fetchProperties) {
            if (typeof window !== 'undefined') return [window];
            return [];
        },
        getBackgroundPage: function () { return null; },
        isAllowedIncognitoAccess: ok(false),
        isAllowedFileSchemeAccess: ok(false),
        inIncognitoContext: false,
        getURL: function (path) { return chrome.runtime.getURL(path); },
        onRequest: makeEvent(),
        onRequestExternal: makeEvent(),
        sendRequest: ok(undefined)
    });

    // ── declarativeNetRequest: reglas de red ─────────────────────────────────
    var dnr = ns('declarativeNetRequest');
    fill(dnr, {
        getDynamicRules: ok([]),
        updateDynamicRules: ok(undefined),
        getSessionRules: ok([]),
        updateSessionRules: ok(undefined),
        getEnabledRulesets: ok([]),
        updateEnabledRulesets: ok(undefined)
    });
})();
