// Visor de Imagenes - migrado a Python/QWebChannel + SQLite (app_config)
(function () {
    'use strict';

    let py = null;

    const state = {
        images: [],
        filtered: [],
        currentPath: null,
        lbIndex: 0,
        zoom: 1,
        panX: 0,
        panY: 0,
        dragging: false,
        dragStart: null,
        observer: null,
        selectionMode: false,
        selectedPaths: new Set(),
        settings: {
            imageMediaPath: '',
            sortBy: 'name-asc',
            lastFolder: '.'
        },
        moveTarget: null,
        moveDestPath: null
    };

    const q = (id) => document.getElementById(id);

    let contextImagePath = null;

    function closeContextMenu() {
        const menu = q('ip-ctx-menu');
        if (menu) menu.classList.remove('active');
        contextImagePath = null;
    }

    function getContextImageFromTarget(_target) {
        if (q('ip-lightbox').classList.contains('active')) {
            return state.filtered[state.lbIndex] || null;
        }
        return null;
    }

    function openContextMenu(clientX, clientY, img) {
        const menu = q('ip-ctx-menu');
        if (!menu || !img) return;
        contextImagePath = img.path;

        menu.classList.add('active');
        menu.style.left = '0px';
        menu.style.top = '0px';

        const rect = menu.getBoundingClientRect();
        const maxX = window.innerWidth - rect.width - 8;
        const maxY = window.innerHeight - rect.height - 8;
        const x = Math.max(8, Math.min(clientX, maxX));
        const y = Math.max(8, Math.min(clientY, maxY));
        menu.style.left = `${x}px`;
        menu.style.top = `${y}px`;
    }

    function bindContextMenu() {
        const menu = q('ip-ctx-menu');
        if (!menu) return;

        document.addEventListener('click', (e) => {
            if (!menu.classList.contains('active')) return;
            if (!e.target.closest('#ip-ctx-menu')) closeContextMenu();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeContextMenu();
        });

        const targetSelectors = ['ip-lb-stage', 'ip-lb-img-wrap', 'ip-lb-img'];
        targetSelectors.forEach((id) => {
            const el = q(id);
            if (!el) return;
            el.addEventListener('contextmenu', (e) => {
                const img = getContextImageFromTarget(e.target);
                if (!img) return;
                e.preventDefault();
                openContextMenu(e.clientX, e.clientY, img);
            });
        });

        q('ip-ctx-close').addEventListener('click', closeContextMenu);

        q('ip-ctx-wallpaper').addEventListener('click', async () => {
            if (!contextImagePath || !py || !py.set_image_wallpaper) {
                showNotification('No disponible en este entorno', 'error');
                closeContextMenu();
                return;
            }
            try {
                const ok = await py.set_image_wallpaper(contextImagePath);
                showNotification(ok ? 'Fondo de pantalla aplicado' : 'No se pudo aplicar el fondo', ok ? 'success' : 'error');
            } catch (_e) {
                showNotification('Error al aplicar fondo', 'error');
            }
            closeContextMenu();
        });

        q('ip-ctx-rename').addEventListener('click', () => {
            const img = state.filtered.find((i) => i.path === contextImagePath);
            closeContextMenu();
            if (!img) return;
            const card = document.querySelector(`.ip-thumb[data-path="${CSS.escape(img.path)}"]`);
            const nameEl = card ? card.querySelector('.ip-thumb-name') : null;
            showRenameImage(img, nameEl, card);
        });

        q('ip-ctx-move').addEventListener('click', async () => {
            const img = state.filtered.find((i) => i.path === contextImagePath);
            closeContextMenu();
            if (!img) return;
            const card = document.querySelector(`.ip-thumb[data-path="${CSS.escape(img.path)}"]`);
            await showMoveImage(img, card);
        });

        q('ip-ctx-delete').addEventListener('click', () => {
            const img = state.filtered.find((i) => i.path === contextImagePath);
            closeContextMenu();
            if (!img) return;
            const card = document.querySelector(`.ip-thumb[data-path="${CSS.escape(img.path)}"]`);
            confirmDeleteImage(img, card);
        });
    }

    function showNotification(msg, type = 'success') {
        const container = q('toast-container');
        if (!container) return;
        const toast = document.createElement('div');
        toast.style.padding = '10px 20px';
        toast.style.background = type === 'success' ? 'rgba(0,184,148,0.9)' : 'rgba(214,48,49,0.9)';
        if (type === 'info') toast.style.background = 'rgba(108,92,231,0.9)';
        toast.style.color = '#fff';
        toast.style.borderRadius = '8px';
        toast.style.boxShadow = '0 4px 12px rgba(0,0,0,0.3)';
        toast.style.fontSize = '0.85rem';
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(20px)';
        toast.style.transition = 'all 0.3s ease';
        toast.innerText = msg;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        }, 10);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(20px)';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    async function setConfig(key, val) {
        try {
            await py.set_config(key, String(val));
        } catch (_e) {
            // Ignorar errores no criticos de persistencia
        }
    }

    function updateToolbarState() {
        const count = q('ip-count');
        const toggleBtn = q('ip-bulk-toggle');
        const selectAllBtn = q('ip-bulk-select-all');
        const deleteBtn = q('ip-bulk-delete');

        const visibleCount = state.filtered.length;
        const selectedVisible = state.filtered.filter((img) => state.selectedPaths.has(img.path)).length;
        const allVisibleSelected = visibleCount > 0 && selectedVisible === visibleCount;

        if (count) {
            const base = `${visibleCount} imagen${visibleCount === 1 ? '' : 'es'}`;
            count.textContent = state.selectionMode ? `${base} · ${selectedVisible} seleccionada${selectedVisible === 1 ? '' : 's'}` : base;
        }

        if (toggleBtn) toggleBtn.textContent = state.selectionMode ? 'Cancelar seleccion' : 'Seleccionar';
        if (selectAllBtn) {
            selectAllBtn.disabled = visibleCount === 0;
            selectAllBtn.textContent = allVisibleSelected ? 'Quitar todas' : 'Seleccionar todo';
        }
        if (deleteBtn) {
            deleteBtn.disabled = selectedVisible === 0;
            deleteBtn.textContent = selectedVisible > 0 ? `Eliminar (${selectedVisible})` : 'Eliminar seleccionadas';
        }
    }

    function syncSelectionWithVisibleImages() {
        const visible = new Set(state.filtered.map((img) => img.path));
        state.selectedPaths = new Set([...state.selectedPaths].filter((path) => visible.has(path)));
    }

    function clearSelection(render = false) {
        state.selectedPaths.clear();
        if (render) renderGallery();
        else updateToolbarState();
    }

    function toggleSelectionMode(forceValue) {
        state.selectionMode = typeof forceValue === 'boolean' ? forceValue : !state.selectionMode;
        if (!state.selectionMode) {
            clearSelection(true);
            return;
        }
        renderGallery();
    }

    function toggleImageSelection(imgPath, card) {
        if (state.selectedPaths.has(imgPath)) state.selectedPaths.delete(imgPath);
        else state.selectedPaths.add(imgPath);

        if (card) card.classList.toggle('selected', state.selectedPaths.has(imgPath));
        updateToolbarState();
    }

    function toggleSelectAllVisible() {
        const visiblePaths = state.filtered.map((img) => img.path);
        if (visiblePaths.length === 0) return;

        const allSelected = visiblePaths.every((path) => state.selectedPaths.has(path));
        visiblePaths.forEach((path) => {
            if (allSelected) state.selectedPaths.delete(path);
            else state.selectedPaths.add(path);
        });
        renderGallery();
    }

    async function bootstrap() {
        try {
            const raw = await py.get_image_settings();
            const settings = JSON.parse(raw || '{}');
            state.settings.imageMediaPath = settings.imageMediaPath || '';
            state.settings.sortBy = settings.sortBy || 'name-asc';
            state.settings.lastFolder = settings.lastFolder || '.';
        } catch (_e) {
            // fallback silencioso
        }

        const pathLabel = q('ip-media-path-label');
        if (pathLabel) {
            pathLabel.textContent = state.settings.imageMediaPath || '';
            pathLabel.title = state.settings.imageMediaPath || '';
        }
        const cfgPath = q('ip-cfg-path-input');
        if (cfgPath) cfgPath.value = state.settings.imageMediaPath || '';

        const sortEl = q('ip-sort');
        if (sortEl) sortEl.value = state.settings.sortBy || 'name-asc';

        await fetchFolders();
    }

    async function fetchFolders() {
        const tree = q('ip-folder-tree');
        if (!tree) return;

        tree.innerHTML = '<div style="padding:20px 14px; font-size:0.8rem; color:rgba(255,255,255,0.2); text-align:center;">Cargando...</div>';

        try {
            const data = JSON.parse(await py.get_image_folders());
            renderTree(Array.isArray(data) ? data : [], tree, 0);
            if (!Array.isArray(data) || data.length === 0) {
                tree.innerHTML = '<div style="padding:20px 14px; font-size:0.8rem; color:rgba(255,255,255,0.2); text-align:center; line-height:1.7;">Sin carpetas.<br>Configura la carpeta raiz.</div>';
                renderEmpty('Selecciona una carpeta del panel izquierdo');
                return;
            }

            if (state.settings.lastFolder && state.settings.lastFolder !== '.') {
                const node = findNodeByPath(data, state.settings.lastFolder);
                if (node) {
                    await selectFolder(node);
                    return;
                }
            }
        } catch (_e) {
            tree.innerHTML = '<div style="padding:20px 14px; font-size:0.8rem; color:#ff7675; text-align:center;">Error al cargar carpetas</div>';
        }
    }

    function findNodeByPath(nodes, path) {
        for (const node of nodes) {
            if (node.path === path) return node;
            if (node.children && node.children.length) {
                const found = findNodeByPath(node.children, path);
                if (found) return found;
            }
        }
        return null;
    }

    function renderTree(nodes, container, level) {
        container.innerHTML = '';
        nodes.forEach((node) => {
            const wrap = document.createElement('div');
            const item = document.createElement('div');
            item.className = 'ip-folder-item';
            item.dataset.path = node.path;
            item.style.paddingLeft = `${level * 14 + 12}px`;

            const arrow = document.createElement('span');
            arrow.className = 'ip-folder-arrow';
            arrow.textContent = node.children && node.children.length ? '▶' : '';

            const icon = document.createElement('span');
            icon.textContent = '📁 ';
            icon.style.fontSize = '0.88em';

            const label = document.createElement('span');
            label.className = 'ip-folder-label';
            label.textContent = node.name;

            const actions = document.createElement('div');
            actions.className = 'ip-folder-actions';

            const btnAdd = document.createElement('button');
            btnAdd.className = 'ip-fld-btn';
            btnAdd.title = 'Nueva subcarpeta';
            btnAdd.textContent = '+';
            btnAdd.addEventListener('click', (e) => {
                e.stopPropagation();
                showCreateFolder(node.path);
            });

            const btnRen = document.createElement('button');
            btnRen.className = 'ip-fld-btn';
            btnRen.title = 'Renombrar carpeta';
            btnRen.innerHTML = '<svg viewBox="0 0 24 24" width="11" height="11" fill="currentColor"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>';
            btnRen.addEventListener('click', (e) => {
                e.stopPropagation();
                showRenameFolder(node);
            });

            const btnDel = document.createElement('button');
            btnDel.className = 'ip-fld-btn del';
            btnDel.title = 'Eliminar carpeta';
            btnDel.innerHTML = '<svg viewBox="0 0 24 24" width="11" height="11" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>';
            btnDel.addEventListener('click', (e) => {
                e.stopPropagation();
                confirmDeleteFolder(node);
            });

            actions.appendChild(btnAdd);
            actions.appendChild(btnRen);
            actions.appendChild(btnDel);

            item.appendChild(arrow);
            item.appendChild(icon);
            item.appendChild(label);
            item.appendChild(actions);
            wrap.appendChild(item);

            let sub = null;
            if (node.children && node.children.length) {
                sub = document.createElement('div');
                sub.className = 'ip-folder-children';
                sub.style.display = 'none';
                renderTree(node.children, sub, level + 1);
                wrap.appendChild(sub);

                arrow.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const open = sub.style.display !== 'none';
                    sub.style.display = open ? 'none' : 'block';
                    arrow.textContent = open ? '▶' : '▼';
                    icon.textContent = open ? '📁 ' : '📂 ';
                });
            }

            item.addEventListener('click', async () => {
                await selectFolder(node);
            });

            container.appendChild(wrap);
        });
    }

    async function selectFolder(node) {
        document.querySelectorAll('.ip-folder-item').forEach((el) => {
            el.classList.toggle('active', el.dataset.path === node.path);
        });

        state.currentPath = node.path;
        q('ip-folder-path').textContent = node.path === '.' ? 'Raiz' : node.path;

        await setConfig('imageLastFolder', node.path);

        renderLoading();
        try {
            const items = JSON.parse(await py.get_images(node.path));
            state.images = Array.isArray(items) ? items : [];
            state.selectionMode = false;
            state.selectedPaths.clear();
            applyFilter();
        } catch (_e) {
            renderEmpty('Error al cargar imagenes');
        }
    }

    function renderLoading() {
        const gallery = q('ip-gallery');
        if (gallery) gallery.innerHTML = '<div class="ip-loading"><div class="ip-spinner"></div>Cargando imagenes...</div>';
        const count = q('ip-count');
        if (count) count.textContent = '';
    }

    function renderEmpty(text) {
        const gallery = q('ip-gallery');
        if (gallery) {
            gallery.innerHTML = `<div class="ip-gallery-empty"><div class="ep-icon">📂</div><div>${text}</div></div>`;
        }
        syncSelectionWithVisibleImages();
        updateToolbarState();
    }

    function applyFilter() {
        const search = (q('ip-search').value || '').toLowerCase().trim();
        const sort = q('ip-sort').value;

        state.settings.sortBy = sort;
        setConfig('imageSortBy', sort);

        let list = search
            ? state.images.filter((i) => i.name.toLowerCase().includes(search))
            : [...state.images];

        list.sort((a, b) => {
            if (sort === 'name-asc') return a.name.localeCompare(b.name);
            if (sort === 'name-desc') return b.name.localeCompare(a.name);
            if (sort === 'date-desc') return Number(b.mtime || 0) - Number(a.mtime || 0);
            if (sort === 'date-asc') return Number(a.mtime || 0) - Number(b.mtime || 0);
            if (sort === 'size-desc') return Number(b.size || 0) - Number(a.size || 0);
            return 0;
        });

        state.filtered = list;
        syncSelectionWithVisibleImages();
        renderGallery();
    }

    function renderGallery() {
        const gallery = q('ip-gallery');
        const count = q('ip-count');
        if (!gallery) return;

        if (state.observer) {
            state.observer.disconnect();
            state.observer = null;
        }

        if (state.filtered.length === 0) {
            const msg = state.images.length === 0 ? 'Esta carpeta no tiene imagenes' : 'Sin resultados';
            gallery.innerHTML = `<div class="ip-gallery-empty"><div class="ep-icon">${state.images.length === 0 ? '📂' : '🔍'}</div><div>${msg}</div></div>`;
            updateToolbarState();
            return;
        }

        gallery.innerHTML = '';
        updateToolbarState();

        state.filtered.forEach((img, idx) => {
            const card = document.createElement('div');
            card.className = 'ip-thumb';
            card.dataset.path = img.path;
            card.classList.toggle('selecting', state.selectionMode);
            card.classList.toggle('selected', state.selectedPaths.has(img.path));

            const selectBtn = document.createElement('button');
            selectBtn.className = 'ip-thumb-select';
            selectBtn.type = 'button';
            selectBtn.title = state.selectedPaths.has(img.path) ? 'Quitar de la seleccion' : 'Seleccionar imagen';
            selectBtn.textContent = '✓';
            selectBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleImageSelection(img.path, card);
                selectBtn.title = state.selectedPaths.has(img.path) ? 'Quitar de la seleccion' : 'Seleccionar imagen';
            });

            const imageEl = document.createElement('img');
            imageEl.dataset.src = img.url;
            imageEl.alt = img.name;
            imageEl.loading = 'lazy';

            const overlay = document.createElement('div');
            overlay.className = 'ip-thumb-overlay';

            const nameEl = document.createElement('span');
            nameEl.className = 'ip-thumb-name';
            nameEl.textContent = img.name;

            const acts = document.createElement('div');
            acts.className = 'ip-thumb-act';

            const btnRen = document.createElement('button');
            btnRen.className = 'ip-act-btn';
            btnRen.title = 'Renombrar';
            btnRen.innerHTML = '<svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>';
            btnRen.addEventListener('click', (e) => {
                e.stopPropagation();
                showRenameImage(img, nameEl, card);
            });

            const btnMov = document.createElement('button');
            btnMov.className = 'ip-act-btn';
            btnMov.title = 'Mover a carpeta';
            btnMov.innerHTML = '<svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M20 6h-8l-2-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm0 12H4V6h5.17l2 2H20v10z"/></svg>';
            btnMov.addEventListener('click', (e) => {
                e.stopPropagation();
                showMoveImage(img, card);
            });

            const btnDel = document.createElement('button');
            btnDel.className = 'ip-act-btn del';
            btnDel.title = 'Eliminar imagen';
            btnDel.innerHTML = '<svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>';
            btnDel.addEventListener('click', (e) => {
                e.stopPropagation();
                confirmDeleteImage(img, card);
            });

            acts.appendChild(btnRen);
            acts.appendChild(btnMov);
            acts.appendChild(btnDel);
            card.appendChild(selectBtn);
            overlay.appendChild(nameEl);
            overlay.appendChild(acts);
            card.appendChild(imageEl);
            card.appendChild(overlay);
            card.addEventListener('click', () => {
                if (state.selectionMode) {
                    toggleImageSelection(img.path, card);
                    selectBtn.title = state.selectedPaths.has(img.path) ? 'Quitar de la seleccion' : 'Seleccionar imagen';
                    return;
                }
                openLightbox(idx);
            });
            gallery.appendChild(card);
        });

        state.observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                const img = entry.target.querySelector('img[data-src]');
                if (!img) return;
                img.src = img.dataset.src;
                img.removeAttribute('data-src');
                img.addEventListener('load', () => img.classList.add('loaded'), { once: true });
                img.addEventListener('error', () => {
                    img.style.opacity = '0.3';
                }, { once: true });
                state.observer.unobserve(entry.target);
            });
        }, { rootMargin: '300px' });

        gallery.querySelectorAll('.ip-thumb').forEach((t) => state.observer.observe(t));
    }

    function openLightbox(idx) {
        state.lbIndex = idx;
        state.zoom = 1;
        state.panX = 0;
        state.panY = 0;
        q('ip-lightbox').classList.add('active');
        renderLightbox();
        buildFilmstrip();
        document.addEventListener('keydown', onLbKeydown);
    }

    function closeLightbox() {
        q('ip-lightbox').classList.remove('active');
        document.removeEventListener('keydown', onLbKeydown);
        state.zoom = 1;
        state.panX = 0;
        state.panY = 0;
        applyTransform();
    }

    function onLbKeydown(e) {
        if (e.key === 'Escape') {
            closeLightbox();
            return;
        }
        if (e.key === 'ArrowLeft' && state.lbIndex > 0) {
            state.lbIndex -= 1;
            state.zoom = 1;
            state.panX = 0;
            state.panY = 0;
            renderLightbox();
            return;
        }
        if (e.key === 'ArrowRight' && state.lbIndex < state.filtered.length - 1) {
            state.lbIndex += 1;
            state.zoom = 1;
            state.panX = 0;
            state.panY = 0;
            renderLightbox();
            return;
        }
        if (e.key === '+' || e.key === '=') {
            zoomBy(0.25);
            return;
        }
        if (e.key === '-') {
            zoomBy(-0.25);
            return;
        }
        if (e.key === '0') {
            state.zoom = 1;
            state.panX = 0;
            state.panY = 0;
            applyTransform();
        }
    }

    function renderLightbox() {
        const img = state.filtered[state.lbIndex];
        if (!img) return;

        q('ip-lb-title').textContent = img.name;
        q('ip-lb-counter').textContent = `${state.lbIndex + 1} / ${state.filtered.length}`;

        const sizeMb = (Number(img.size || 0) / 1048576).toFixed(1);
        const date = new Date(Number(img.mtime || 0) * 1000).toLocaleDateString('es', {
            day: '2-digit',
            month: 'short',
            year: 'numeric'
        });
        q('ip-lb-meta').textContent = `${sizeMb} MB · ${date}`;

        const el = q('ip-lb-img');
        el.style.opacity = '0';
        el.src = img.url;
        el.onload = () => {
            el.style.opacity = '1';
            state.zoom = 1;
            state.panX = 0;
            state.panY = 0;
            applyTransform();
        };

        q('ip-lb-prev').disabled = state.lbIndex === 0;
        q('ip-lb-next').disabled = state.lbIndex === state.filtered.length - 1;

        document.querySelectorAll('.ip-lb-thumb').forEach((t, i) => {
            t.classList.toggle('active', i === state.lbIndex);
        });

        const strip = q('ip-lb-filmstrip');
        const active = strip.children[state.lbIndex];
        if (active) active.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }

    function buildFilmstrip() {
        const strip = q('ip-lb-filmstrip');
        strip.innerHTML = '';
        state.filtered.forEach((img, i) => {
            const t = document.createElement('div');
            t.className = `ip-lb-thumb${i === state.lbIndex ? ' active' : ''}`;
            t.innerHTML = `<img src="${img.url}" alt="${img.name}" loading="lazy">`;
            t.addEventListener('click', () => {
                state.lbIndex = i;
                state.zoom = 1;
                state.panX = 0;
                state.panY = 0;
                renderLightbox();
            });
            strip.appendChild(t);
        });
    }

    function zoomBy(delta, cx, cy) {
        const oldZoom = state.zoom;
        state.zoom = Math.min(8, Math.max(0.5, state.zoom + delta));
        if (state.zoom < 1) {
            state.zoom = 1;
            state.panX = 0;
            state.panY = 0;
        }

        if (cx !== undefined && oldZoom !== state.zoom) {
            const wrap = q('ip-lb-img-wrap');
            const rect = wrap.getBoundingClientRect();
            const offsetX = cx - (rect.left + rect.width / 2);
            const offsetY = cy - (rect.top + rect.height / 2);
            state.panX += (offsetX / oldZoom) * (oldZoom - state.zoom);
            state.panY += (offsetY / oldZoom) * (oldZoom - state.zoom);
        }

        applyTransform();
    }

    function applyTransform() {
        const el = q('ip-lb-img');
        if (!el) return;
        if (state.zoom <= 1) {
            state.panX = 0;
            state.panY = 0;
        }
        el.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
        el.style.cursor = state.zoom > 1 ? 'grab' : 'default';
        q('ip-lb-zoom-pct').textContent = `${Math.round(state.zoom * 100)}%`;
    }

    function removeImageFromState(imgPath) {
        state.images = state.images.filter((i) => i.path !== imgPath);
        state.filtered = state.filtered.filter((i) => i.path !== imgPath);
        state.selectedPaths.delete(imgPath);
    }

    function confirmDeleteSelectedImages() {
        const selected = state.filtered.filter((img) => state.selectedPaths.has(img.path));
        if (selected.length === 0) {
            showNotification('No hay imagenes seleccionadas', 'info');
            return;
        }

        q('ip-confirm-title').textContent = '¿Eliminar imagenes seleccionadas?';
        q('ip-confirm-desc').textContent = `Se eliminaran permanentemente ${selected.length} imagenes seleccionadas. Esta accion no se puede deshacer.`;
        q('ip-confirm-modal').classList.add('active');

        const okBtn = q('ip-confirm-ok');
        const newOk = okBtn.cloneNode(true);
        okBtn.parentNode.replaceChild(newOk, okBtn);

        newOk.addEventListener('click', async () => {
            try {
                let deleted = 0;
                for (const img of selected) {
                    const ok = await py.delete_image(img.path);
                    if (!ok) continue;
                    deleted += 1;
                    removeImageFromState(img.path);
                }

                q('ip-confirm-modal').classList.remove('active');
                if (deleted === 0) throw new Error('No se pudo eliminar ninguna');
                renderGallery();
                showNotification(
                    deleted === selected.length
                        ? `${deleted} imagen${deleted === 1 ? '' : 'es'} eliminada${deleted === 1 ? '' : 's'}`
                        : `Se eliminaron ${deleted} de ${selected.length} imagenes`,
                    deleted === selected.length ? 'success' : 'info'
                );
            } catch (_e) {
                showNotification('Error al eliminar seleccion', 'error');
            }
        });
    }

    function showRenameImage(img, nameEl, card) {
        const input = q('ip-rename-input');
        input.value = img.name;
        q('ip-rename-modal').classList.add('active');
        input.select();

        const saveBtn = q('ip-rename-save');
        const newSave = saveBtn.cloneNode(true);
        saveBtn.parentNode.replaceChild(newSave, saveBtn);

        newSave.addEventListener('click', async () => {
            const newName = input.value.trim();
            if (!newName || newName === img.name) {
                q('ip-rename-modal').classList.remove('active');
                return;
            }

            try {
                const res = JSON.parse(await py.rename_image(img.path, newName));
                if (!res.success) throw new Error(res.error || 'No se pudo renombrar');

                const oldPath = img.path;
                img.name = newName;
                img.path = res.newPath;
                if (nameEl) nameEl.textContent = newName;
                if (card) card.dataset.path = res.newPath;

                const idx = state.images.findIndex((i) => i.path === oldPath);
                if (idx !== -1) {
                    state.images[idx].name = newName;
                    state.images[idx].path = res.newPath;
                }
                if (state.selectedPaths.has(oldPath)) {
                    state.selectedPaths.delete(oldPath);
                    state.selectedPaths.add(res.newPath);
                }

                q('ip-rename-modal').classList.remove('active');
                renderLightbox();
                showNotification('Imagen renombrada', 'success');
            } catch (_e) {
                showNotification('Error al renombrar', 'error');
            }
        });
    }

    async function showMoveImage(img, card) {
        state.moveTarget = { img, card };
        state.moveDestPath = null;
        q('ip-move-dest-label').textContent = '—';
        q('ip-move-modal').classList.add('active');

        const tree = q('ip-move-tree');
        tree.innerHTML = '<div style="padding:12px; font-size:0.8rem; color:rgba(255,255,255,0.3);">Cargando...</div>';

        try {
            const folders = JSON.parse(await py.get_image_folders());
            tree.innerHTML = '';

            const rootItem = document.createElement('div');
            rootItem.className = 'ip-browse-item';
            rootItem.textContent = '📸 Raiz';
            rootItem.addEventListener('click', () => {
                state.moveDestPath = '.';
                q('ip-move-dest-label').textContent = 'Raiz';
                tree.querySelectorAll('.ip-browse-item').forEach((el) => {
                    el.style.background = '';
                });
                rootItem.style.background = 'rgba(108,92,231,0.25)';
            });
            tree.appendChild(rootItem);

            const build = (nodes, level) => {
                nodes.forEach((n) => {
                    const item = document.createElement('div');
                    item.className = 'ip-browse-item';
                    item.style.paddingLeft = `${level * 14 + 12}px`;
                    item.textContent = `📁 ${n.name}`;
                    item.addEventListener('click', () => {
                        state.moveDestPath = n.path;
                        q('ip-move-dest-label').textContent = n.path;
                        tree.querySelectorAll('.ip-browse-item').forEach((el) => {
                            el.style.background = '';
                        });
                        item.style.background = 'rgba(108,92,231,0.25)';
                    });
                    tree.appendChild(item);
                    if (n.children && n.children.length) build(n.children, level + 1);
                });
            };

            build(Array.isArray(folders) ? folders : [], 0);
        } catch (_e) {
            tree.innerHTML = '<div style="padding:12px; color:#ff7675;">Error al cargar carpetas</div>';
        }

        const saveBtn = q('ip-move-save');
        const newSave = saveBtn.cloneNode(true);
        saveBtn.parentNode.replaceChild(newSave, saveBtn);

        newSave.addEventListener('click', async () => {
            if (!state.moveTarget) return;
            if (state.moveDestPath === null) {
                showNotification('Selecciona una carpeta destino', 'info');
                return;
            }

            const { img: moveImg, card: moveCard } = state.moveTarget;
            try {
                const ok = await py.move_image(moveImg.path, state.moveDestPath);
                if (!ok) throw new Error('No se pudo mover');

                q('ip-move-modal').classList.remove('active');
                removeImageFromState(moveImg.path);
                if (moveCard) {
                    moveCard.style.transition = 'opacity 0.2s, transform 0.2s';
                    moveCard.style.opacity = '0';
                    moveCard.style.transform = 'scale(0.8)';
                    setTimeout(() => {
                        moveCard.remove();
                        q('ip-count').textContent = `${state.filtered.length} imagen${state.filtered.length === 1 ? '' : 'es'}`;
                    }, 200);
                } else {
                    renderGallery();
                }
                showNotification('Imagen movida', 'success');
            } catch (_e) {
                showNotification('Error al mover imagen', 'error');
            }
        });
    }

    function confirmDeleteImage(img, card) {
        q('ip-confirm-title').textContent = '¿Eliminar imagen?';
        q('ip-confirm-desc').textContent = `Se eliminara permanentemente "${img.name}". Esta accion no se puede deshacer.`;
        q('ip-confirm-modal').classList.add('active');

        const okBtn = q('ip-confirm-ok');
        const newOk = okBtn.cloneNode(true);
        okBtn.parentNode.replaceChild(newOk, okBtn);

        newOk.addEventListener('click', async () => {
            try {
                const ok = await py.delete_image(img.path);
                if (!ok) throw new Error('No se pudo eliminar');
                q('ip-confirm-modal').classList.remove('active');
                removeImageFromState(img.path);
                if (card) {
                    card.style.transition = 'opacity 0.2s, transform 0.2s';
                    card.style.opacity = '0';
                    card.style.transform = 'scale(0.8)';
                    setTimeout(() => {
                        card.remove();
                        q('ip-count').textContent = `${state.filtered.length} imagen${state.filtered.length === 1 ? '' : 'es'}`;
                    }, 200);
                } else {
                    renderGallery();
                }
                closeLightbox();
                showNotification('Imagen eliminada', 'success');
            } catch (_e) {
                showNotification('Error al eliminar', 'error');
            }
        });
    }

    async function openImageAdminModal() {
        const img = state.filtered[state.lbIndex];
        if (!img) return;

        q('ip-admin-name').value = img.name || '';
        q('ip-admin-relpath').value = img.path || '';

        try {
            const abs = await py.get_image_absolute_path(img.path);
            q('ip-admin-abspath').value = abs || '';
        } catch (_e) {
            q('ip-admin-abspath').value = '';
        }

        q('ip-admin-modal').classList.add('active');
    }

    function showCreateFolder(parentPath) {
        q('ip-folder-modal-title').textContent = '📁 Nueva carpeta';
        q('ip-folder-modal-desc').textContent = parentPath === '.' ? 'Crear en la carpeta raiz' : `Crear en: ${parentPath}`;
        q('ip-folder-modal-save').textContent = 'Crear';
        q('ip-folder-name-input').value = '';
        q('ip-folder-modal').classList.add('active');

        setTimeout(() => q('ip-folder-name-input').focus(), 50);

        const saveBtn = q('ip-folder-modal-save');
        const newSave = saveBtn.cloneNode(true);
        saveBtn.parentNode.replaceChild(newSave, saveBtn);

        newSave.addEventListener('click', async () => {
            const name = q('ip-folder-name-input').value.trim();
            if (!name) return;
            const newDir = parentPath === '.' ? name : `${parentPath}/${name}`;
            try {
                const ok = await py.create_image_folder(newDir);
                if (!ok) throw new Error('No se pudo crear');
                q('ip-folder-modal').classList.remove('active');
                await fetchFolders();
                showNotification('Carpeta creada', 'success');
            } catch (_e) {
                showNotification('Error al crear carpeta', 'error');
            }
        });
    }

    function showRenameFolder(node) {
        q('ip-folder-modal-title').textContent = '✏️ Renombrar carpeta';
        q('ip-folder-modal-desc').textContent = `Nombre actual: ${node.name}`;
        q('ip-folder-name-input').value = node.name;
        q('ip-folder-modal-save').textContent = 'Renombrar';
        q('ip-folder-modal').classList.add('active');

        setTimeout(() => {
            const input = q('ip-folder-name-input');
            input.focus();
            input.select();
        }, 50);

        const saveBtn = q('ip-folder-modal-save');
        const newSave = saveBtn.cloneNode(true);
        saveBtn.parentNode.replaceChild(newSave, saveBtn);

        newSave.addEventListener('click', async () => {
            const newName = q('ip-folder-name-input').value.trim();
            if (!newName || newName === node.name) {
                q('ip-folder-modal').classList.remove('active');
                return;
            }
            try {
                const ok = await py.rename_image_folder(node.path, newName);
                if (!ok) throw new Error('No se pudo renombrar');
                q('ip-folder-modal').classList.remove('active');

                if (state.currentPath === node.path) {
                    const parent = node.path.includes('/') ? node.path.slice(0, node.path.lastIndexOf('/')) : '.';
                    state.currentPath = parent === '.' ? newName : `${parent}/${newName}`;
                    await setConfig('imageLastFolder', state.currentPath);
                }

                await fetchFolders();
                showNotification('Carpeta renombrada', 'success');
            } catch (_e) {
                showNotification('Error al renombrar carpeta', 'error');
            }
        });
    }

    function confirmDeleteFolder(node) {
        q('ip-confirm-title').textContent = '¿Eliminar carpeta?';
        q('ip-confirm-desc').textContent = `Se eliminara "${node.name}" y todo su contenido permanentemente.`;
        q('ip-confirm-modal').classList.add('active');

        const okBtn = q('ip-confirm-ok');
        const newOk = okBtn.cloneNode(true);
        okBtn.parentNode.replaceChild(newOk, okBtn);

        newOk.addEventListener('click', async () => {
            try {
                const ok = await py.delete_image_folder(node.path);
                if (!ok) throw new Error('No se pudo eliminar carpeta');
                q('ip-confirm-modal').classList.remove('active');

                if (state.currentPath === node.path) {
                    state.currentPath = null;
                    state.images = [];
                    state.filtered = [];
                    renderEmpty('Selecciona una carpeta del panel izquierdo');
                    q('ip-folder-path').textContent = 'Selecciona una carpeta';
                    await setConfig('imageLastFolder', '.');
                }

                await fetchFolders();
                showNotification('Carpeta eliminada', 'success');
            } catch (_e) {
                showNotification('Error al eliminar carpeta', 'error');
            }
        });
    }

    async function openConfigModal() {
        q('ip-cfg-modal').classList.add('active');
        await browseConfigPath();
    }

    async function browseConfigPath() {
        const input = q('ip-cfg-path-input');
        const browseEl = q('ip-cfg-browse');
        const target = (input.value || '').trim() || '/home';

        try {
            const data = JSON.parse(await py.browse_local_path(target));
            if (data.error) throw new Error(data.error);

            browseEl.innerHTML = '';

            const parentItem = document.createElement('div');
            parentItem.className = 'ip-browse-item parent';
            parentItem.textContent = `↑ ${data.parentPath}`;
            parentItem.addEventListener('click', () => {
                input.value = data.parentPath;
                browseConfigPath();
            });
            browseEl.appendChild(parentItem);

            const selfItem = document.createElement('div');
            selfItem.className = 'ip-browse-item';
            selfItem.style.color = '#a29bfe';
            selfItem.textContent = `✓ ${data.currentPath}  (seleccionar esta)`;
            selfItem.addEventListener('click', () => {
                input.value = data.currentPath;
                browseConfigPath();
            });
            browseEl.appendChild(selfItem);

            (data.folders || []).forEach((folder) => {
                const item = document.createElement('div');
                item.className = 'ip-browse-item';
                item.textContent = `📁 ${folder}`;
                item.addEventListener('click', () => {
                    input.value = `${data.currentPath.replace(/\/+$/, '')}/${folder}`;
                    browseConfigPath();
                });
                browseEl.appendChild(item);
            });
        } catch (_e) {
            browseEl.innerHTML = '<div style="padding:12px; color:#ff7675;">No se pudo explorar esta ruta</div>';
        }
    }

    async function saveConfig() {
        const path = (q('ip-cfg-path-input').value || '').trim();
        if (!path) return;

        try {
            await setConfig('imageMediaPath', path);
            state.settings.imageMediaPath = path;
            q('ip-cfg-modal').classList.remove('active');

            const pathLabel = q('ip-media-path-label');
            if (pathLabel) {
                pathLabel.textContent = path;
                pathLabel.title = path;
            }

            await fetchFolders();
            showNotification('Carpeta de imagenes guardada', 'success');
        } catch (_e) {
            showNotification('Error al guardar carpeta', 'error');
        }
    }

    function bindEvents() {
        const navBrowser = q('ip-nav-browser');
        if (navBrowser) {
            navBrowser.addEventListener('click', () => {
                window.location.href = 'newtab.html';
            });
        }

        const navAgenda = q('ip-nav-agenda');
        if (navAgenda) {
            navAgenda.addEventListener('click', () => {
                window.location.href = 'agenda.html';
            });
        }

        const navVideo = q('ip-nav-video');
        if (navVideo) {
            navVideo.addEventListener('click', () => {
                window.location.href = 'videoplayer.html';
            });
        }

        q('ip-search').addEventListener('input', applyFilter);
        q('ip-sort').addEventListener('change', applyFilter);
        q('ip-bulk-toggle').addEventListener('click', () => toggleSelectionMode());
        q('ip-bulk-select-all').addEventListener('click', toggleSelectAllVisible);
        q('ip-bulk-delete').addEventListener('click', confirmDeleteSelectedImages);

        q('ip-cfg-btn').addEventListener('click', openConfigModal);
        q('ip-cfg-save').addEventListener('click', saveConfig);
        document.querySelectorAll('.ip-modal-close[data-close-modal]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const modalId = btn.getAttribute('data-close-modal');
                const modal = modalId ? q(modalId) : null;
                if (modal) modal.classList.remove('active');
            });
        });
        q('ip-cfg-cancel').addEventListener('click', () => q('ip-cfg-modal').classList.remove('active'));
        q('ip-cfg-modal').addEventListener('click', (e) => {
            if (e.target === q('ip-cfg-modal')) q('ip-cfg-modal').classList.remove('active');
        });
        q('ip-cfg-path-input').addEventListener('input', browseConfigPath);

        q('ip-new-root-folder-btn').addEventListener('click', () => showCreateFolder('.'));

        q('ip-lb-close').addEventListener('click', closeLightbox);
        q('ip-lb-prev').addEventListener('click', () => {
            if (state.lbIndex > 0) {
                state.lbIndex -= 1;
                state.zoom = 1;
                state.panX = 0;
                state.panY = 0;
                renderLightbox();
            }
        });
        q('ip-lb-next').addEventListener('click', () => {
            if (state.lbIndex < state.filtered.length - 1) {
                state.lbIndex += 1;
                state.zoom = 1;
                state.panX = 0;
                state.panY = 0;
                renderLightbox();
            }
        });

        q('ip-lb-zoom-in').addEventListener('click', () => zoomBy(0.25));
        q('ip-lb-zoom-out').addEventListener('click', () => zoomBy(-0.25));
        q('ip-lb-zoom-pct').addEventListener('click', () => {
            state.zoom = 1;
            state.panX = 0;
            state.panY = 0;
            applyTransform();
        });
        q('ip-lb-fit').addEventListener('click', () => {
            state.zoom = 1;
            state.panX = 0;
            state.panY = 0;
            applyTransform();
        });

        q('ip-lb-admin').addEventListener('click', async () => {
            await openImageAdminModal();
        });

        q('ip-lb-rename').addEventListener('click', () => {
            const img = state.filtered[state.lbIndex];
            if (!img) return;
            const card = document.querySelector(`.ip-thumb[data-path="${CSS.escape(img.path)}"]`);
            const nameEl = card ? card.querySelector('.ip-thumb-name') : null;
            showRenameImage(img, nameEl, card);
        });

        q('ip-lb-move').addEventListener('click', async () => {
            const img = state.filtered[state.lbIndex];
            if (!img) return;
            const card = document.querySelector(`.ip-thumb[data-path="${CSS.escape(img.path)}"]`);
            await showMoveImage(img, card);
        });

        q('ip-lb-delete').addEventListener('click', () => {
            const img = state.filtered[state.lbIndex];
            if (!img) return;
            const card = document.querySelector(`.ip-thumb[data-path="${CSS.escape(img.path)}"]`);
            confirmDeleteImage(img, card);
        });

        q('ip-lb-stage').addEventListener('wheel', (e) => {
            e.preventDefault();
            zoomBy(e.deltaY < 0 ? 0.15 : -0.15, e.clientX, e.clientY);
        }, { passive: false });

        const wrap = q('ip-lb-img-wrap');
        wrap.addEventListener('mousedown', (e) => {
            if (state.zoom <= 1) return;
            state.dragging = true;
            state.dragStart = { x: e.clientX - state.panX, y: e.clientY - state.panY };
            q('ip-lb-img').classList.add('panning');
        });

        document.addEventListener('mousemove', (e) => {
            if (!state.dragging) return;
            state.panX = e.clientX - state.dragStart.x;
            state.panY = e.clientY - state.dragStart.y;
            applyTransform();
        });

        document.addEventListener('mouseup', () => {
            if (!state.dragging) return;
            state.dragging = false;
            q('ip-lb-img').classList.remove('panning');
        });

        q('ip-lb-stage').addEventListener('click', (e) => {
            if (e.target === q('ip-lb-stage') || e.target === q('ip-lb-img-wrap')) {
                closeLightbox();
            }
        });

        q('ip-rename-cancel').addEventListener('click', () => q('ip-rename-modal').classList.remove('active'));
        q('ip-rename-modal').addEventListener('click', (e) => {
            if (e.target === q('ip-rename-modal')) q('ip-rename-modal').classList.remove('active');
        });

        q('ip-move-cancel').addEventListener('click', () => q('ip-move-modal').classList.remove('active'));
        q('ip-move-modal').addEventListener('click', (e) => {
            if (e.target === q('ip-move-modal')) q('ip-move-modal').classList.remove('active');
        });

        q('ip-folder-modal-cancel').addEventListener('click', () => q('ip-folder-modal').classList.remove('active'));
        q('ip-folder-modal').addEventListener('click', (e) => {
            if (e.target === q('ip-folder-modal')) q('ip-folder-modal').classList.remove('active');
        });

        q('ip-confirm-cancel').addEventListener('click', () => q('ip-confirm-modal').classList.remove('active'));
        q('ip-confirm-modal').addEventListener('click', (e) => {
            if (e.target === q('ip-confirm-modal')) q('ip-confirm-modal').classList.remove('active');
        });

        q('ip-rename-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') q('ip-rename-save').click();
        });
        q('ip-folder-name-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') q('ip-folder-modal-save').click();
        });

        q('ip-admin-close').addEventListener('click', () => {
            q('ip-admin-modal').classList.remove('active');
        });

        q('ip-admin-modal').addEventListener('click', (e) => {
            if (e.target === q('ip-admin-modal')) q('ip-admin-modal').classList.remove('active');
        });

        q('ip-admin-copy-path').addEventListener('click', async () => {
            const path = q('ip-admin-abspath').value || q('ip-admin-relpath').value;
            if (!path) return;
            try {
                await navigator.clipboard.writeText(path);
                showNotification('Ruta copiada', 'success');
            } catch (_e) {
                showNotification('No se pudo copiar la ruta', 'error');
            }
        });

        q('ip-admin-rename').addEventListener('click', () => {
            const img = state.filtered[state.lbIndex];
            if (!img) return;
            const card = document.querySelector(`.ip-thumb[data-path="${CSS.escape(img.path)}"]`);
            const nameEl = card ? card.querySelector('.ip-thumb-name') : null;
            q('ip-admin-modal').classList.remove('active');
            showRenameImage(img, nameEl, card);
        });

        q('ip-admin-move').addEventListener('click', async () => {
            const img = state.filtered[state.lbIndex];
            if (!img) return;
            const card = document.querySelector(`.ip-thumb[data-path="${CSS.escape(img.path)}"]`);
            q('ip-admin-modal').classList.remove('active');
            await showMoveImage(img, card);
        });

        q('ip-admin-delete').addEventListener('click', () => {
            const img = state.filtered[state.lbIndex];
            if (!img) return;
            const card = document.querySelector(`.ip-thumb[data-path="${CSS.escape(img.path)}"]`);
            q('ip-admin-modal').classList.remove('active');
            confirmDeleteImage(img, card);
        });
    }

    window.addEventListener('DOMContentLoaded', () => {
        if (typeof qt === 'undefined') return;
        new QWebChannel(qt.webChannelTransport, async (channel) => {
            py = channel.objects.py;
            bindEvents();
            bindContextMenu();
            await bootstrap();
        });
    });
})();
