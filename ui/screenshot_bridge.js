// Adaptador para el editor de ScreenShot (screenshot_editor.js, copiado de la
// app Mk ScreenShot Desktop): expone la misma API que su preload de Electron
// (window.electronAPI), implementada con el bridge `py` de Minichrome.
(function () {
  const originalPath = new URLSearchParams(location.search).get('img') || '';
  let loadCallback = null;

  const pyReady = new Promise((resolve) => {
    try {
      new QWebChannel(qt.webChannelTransport, (ch) => resolve(ch.objects.py || null));
    } catch (_) {
      resolve(null);
    }
  });

  async function call(name, ...args) {
    const py = await pyReady;
    if (!py || typeof py[name] !== 'function') throw new Error(`Función no disponible: ${name}`);
    return py[name](...args);
  }

  async function callJson(name, ...args) {
    try {
      return JSON.parse(await call(name, ...args));
    } catch (err) {
      return { success: false, error: String(err) };
    }
  }

  window.electronAPI = {
    // Nueva captura (F9): selección de área del escritorio hecha en Qt
    takeAreaScreenshot: () => call('start_area_screenshot').catch(() => {}),
    takeScreenshot: () => call('start_area_screenshot').catch(() => {}),

    copyToClipboard: async (dataUrl) => {
      try {
        return { success: !!(await call('copy_annotated_screenshot', dataUrl, originalPath)) };
      } catch (err) {
        return { success: false, error: String(err) };
      }
    },
    saveImage: (dataUrl, defaultDir) => callJson('save_screenshot_as', dataUrl, defaultDir || ''),
    selectDirectory: async () => {
      try {
        const path = await call('select_directory');
        return path ? { success: true, path } : { success: false, canceled: true };
      } catch (err) {
        return { success: false, error: String(err) };
      }
    },
    openImageFile: () => callJson('open_image_file'),

    // Cerrar el editor = cerrar su pestaña (descarta la captura original sin guardar)
    closeEditor: async () => {
      try { await call('discard_screenshot', originalPath); } catch (_) {}
      try { await call('show_browser_bar'); } catch (_) {}
      setTimeout(() => call('close_current_tab').catch(() => {}), 200);
    },
    minimizeEditor: () => call('window_minimize').catch(() => {}),
    maximizeEditor: () => call('window_maximize').catch(() => {}),

    onLoadScreenshot: (callback) => { loadCallback = callback; },
    onLoadOverlay: () => {},
  };

  pyReady.then(async (py) => {
    if (!py) return;
    py.screenshot_ready.connect((dataUrl) => { if (loadCallback) loadCallback(dataUrl); });
    // Captura con la que se abrió el editor (?img=ruta en la carpeta de capturas)
    if (originalPath) {
      const dataUrl = await py.read_screenshot_image(originalPath);
      if (dataUrl && loadCallback) loadCallback(dataUrl);
    }
  });
})();
