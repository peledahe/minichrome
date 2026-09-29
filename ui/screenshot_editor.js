// Editor de capturas copiado de Mk ScreenShot Desktop (~/Desarrollo/ScreenShot/editor.js).
// Cambios: ruta del logo y lienzo en blanco inicial solo sin captura (?img).
// window.electronAPI lo provee screenshot_bridge.js.
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('status');
const toastContainer = document.getElementById('toast-container');

// Modales
const confirmDialog = document.getElementById('confirm-dialog');
const textDialog = document.getElementById('text-dialog');
const textInput = document.getElementById('text-input');
const aboutDialog = document.getElementById('about-dialog');

let textResolve = null; // Para manejar el prompt de texto de manera asíncrona

const state = {
  tool: 'rect',
  color: '#ff2d55',
  width: 3,
  textSize: 24,
  shapes: [],
  redoStack: [],
  draft: null,
  drawing: false,
  baseImage: null,
  step: 1,
  selection: null,
  zoom: 80, // Escala de visualización inicial a 80%
  offscreenCanvas: null,
  offscreenCtx: null,
  showBrowserLogo: true,
  logoImg: null,
};

// Cargar imagen del logo para la marca de agua
const logoImg = new Image();
logoImg.src = 'screenshot_icon.png';
logoImg.onload = () => {
  state.logoImg = logoImg;
  render();
};

// --- Sistema de Notificaciones Sticky (Toasts) ---
function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  
  const textSpan = document.createElement('span');
  textSpan.textContent = message;
  toast.appendChild(textSpan);
  
  const closeBtn = document.createElement('button');
  closeBtn.className = 'toast-close';
  closeBtn.innerHTML = '&times;';
  closeBtn.onclick = () => {
    toast.classList.add('fade-out');
    setTimeout(() => toast.remove(), 200);
  };
  toast.appendChild(closeBtn);
  
  toastContainer.appendChild(toast);
  
  // Auto-eliminar después de 4 segundos
  setTimeout(() => {
    if (toast.parentNode) {
      toast.classList.add('fade-out');
      setTimeout(() => toast.remove(), 200);
    }
  }, 4000);
}

function setStatus(text) {
  statusEl.textContent = text;
}

function updateNumberBadge() {
  const badge = document.getElementById('num-badge');
  if (badge) badge.textContent = String(state.step);
}

function normRect(a) {
  const x = Math.min(a.x1, a.x2);
  const y = Math.min(a.y1, a.y2);
  const w = Math.max(1, Math.abs(a.x2 - a.x1));
  const h = Math.max(1, Math.abs(a.y2 - a.y1));
  return { x, y, w, h };
}

function setTool(tool) {
  state.tool = tool;
  document.querySelectorAll('.icon-btn').forEach((b) => {
    if (b.id.startsWith('tool-')) b.classList.remove('active');
  });
  const active = document.getElementById(`tool-${tool}`);
  if (active) active.classList.add('active');
  setStatus(`Herramienta activa: ${tool.toUpperCase()}`);
}

function getPos(e) {
  const r = canvas.getBoundingClientRect();
  const scaleX = canvas.width / r.width;
  const scaleY = canvas.height / r.height;
  return { 
    x: (e.clientX - r.left) * scaleX, 
    y: (e.clientY - r.top) * scaleY 
  };
}

// --- Diálogos Personalizados (Evitando Prompts/Alerts) ---
function promptTextCustom() {
  return new Promise((resolve) => {
    textResolve = resolve;
    textInput.value = '';
    textDialog.showModal();
    setTimeout(() => textInput.focus(), 100);
  });
}

document.getElementById('btn-text-submit').onclick = () => {
  if (textResolve) {
    textResolve(textInput.value.trim());
    textResolve = null;
  }
  textDialog.close();
};

document.getElementById('btn-text-cancel').onclick = () => {
  if (textResolve) {
    textResolve(null);
    textResolve = null;
  }
  textDialog.close();
};

textInput.onkeydown = (e) => {
  if (e.key === 'Enter') {
    document.getElementById('btn-text-submit').click();
  }
};

function confirmClearCustom() {
  return new Promise((resolve) => {
    confirmDialog.showModal();
    document.getElementById('btn-confirm-accept').onclick = () => {
      confirmDialog.close();
      resolve(true);
    };
    document.getElementById('btn-confirm-cancel').onclick = () => {
      confirmDialog.close();
      resolve(false);
    };
  });
}

// --- Funciones de Dibujo en Canvas ---
function drawArrow(shape, context = ctx) {
  const head = Math.max(10, shape.w * 3);
  const dx = shape.x2 - shape.x1;
  const dy = shape.y2 - shape.y1;
  const ang = Math.atan2(dy, dx);

  context.beginPath();
  context.moveTo(shape.x1, shape.y1);
  context.lineTo(shape.x2, shape.y2);
  context.stroke();

  context.beginPath();
  context.moveTo(shape.x2, shape.y2);
  context.lineTo(shape.x2 - head * Math.cos(ang - Math.PI / 6), shape.y2 - head * Math.sin(ang - Math.PI / 6));
  context.lineTo(shape.x2 - head * Math.cos(ang + Math.PI / 6), shape.y2 - head * Math.sin(ang + Math.PI / 6));
  context.closePath();
  context.fillStyle = shape.color;
  context.fill();
}

function wrapText(context, text, maxWidth) {
  const paragraphs = text.split('\n');
  const allLines = [];

  for (const para of paragraphs) {
    if (para === '') {
      allLines.push('');
      continue;
    }
    const words = para.split(' ');
    let currentLine = '';

    for (let i = 0; i < words.length; i++) {
      const testLine = currentLine ? currentLine + ' ' + words[i] : words[i];
      const metrics = context.measureText(testLine);
      if (metrics.width > maxWidth && i > 0) {
        allLines.push(currentLine);
        currentLine = words[i];
      } else {
        currentLine = testLine;
      }
    }
    if (currentLine) {
      allLines.push(currentLine);
    }
  }
  return allLines;
}

function drawShape(shape, context = ctx) {
  context.strokeStyle = shape.color;
  context.fillStyle = shape.color;
  context.lineWidth = shape.w;
  context.lineCap = 'round';
  context.lineJoin = 'round';

  if (shape.type === 'rect') {
    const r = normRect(shape);
    context.strokeRect(r.x, r.y, r.w, r.h);
  } else if (shape.type === 'rect-fill') {
    const r = normRect(shape);
    context.fillRect(r.x, r.y, r.w, r.h);
  } else if (shape.type === 'highlight') {
    const r = normRect(shape);
    context.save();
    context.fillStyle = shape.color || '#ffe600';
    context.globalAlpha = 0.38;
    context.fillRect(r.x, r.y, r.w, r.h);
    context.restore();
  } else if (shape.type === 'blur') {
    const r = normRect(shape);
    if (r.w > 2 && r.h > 2 && state.baseImage) {
      const blurPx = 10;
      const margin = blurPx * 2;
      
      const sx = Math.max(0, r.x - margin);
      const sy = Math.max(0, r.y - margin);
      const sw = Math.min(state.baseImage.naturalWidth - sx, r.w + (r.x - sx) + margin);
      const sh = Math.min(state.baseImage.naturalHeight - sy, r.h + (r.y - sy) + margin);

      context.save();
      context.beginPath();
      context.rect(r.x, r.y, r.w, r.h);
      context.clip();
      
      const tempCanvas = document.createElement('canvas');
      tempCanvas.width = sw;
      tempCanvas.height = sh;
      const tCtx = tempCanvas.getContext('2d');
      
      tCtx.drawImage(state.baseImage, sx, sy, sw, sh, 0, 0, sw, sh);
      
      context.filter = `blur(${blurPx}px)`;
      context.drawImage(tempCanvas, sx, sy);
      context.filter = 'none';
      context.restore();
      
      context.save();
      context.strokeStyle = 'rgba(255, 255, 255, 0.15)';
      context.lineWidth = 1;
      context.strokeRect(r.x, r.y, r.w, r.h);
      context.restore();
    }
  } else if (shape.type === 'circle') {
    const r = normRect(shape);
    context.beginPath();
    context.ellipse(r.x + r.w / 2, r.y + r.h / 2, r.w / 2, r.h / 2, 0, 0, Math.PI * 2);
    context.stroke();
  } else if (shape.type === 'line') {
    context.beginPath();
    context.moveTo(shape.x1, shape.y1);
    context.lineTo(shape.x2, shape.y2);
    context.stroke();
  } else if (shape.type === 'curve') {
    if (shape.points && shape.points.length > 0) {
      let pts = shape.points;
      for (let pass = 0; pass < 2; pass++) {
        if (pts.length >= 3) {
          const temp = [pts[0]];
          for (let i = 1; i < pts.length - 1; i++) {
            temp.push({
              x: (pts[i - 1].x + pts[i].x + pts[i + 1].x) / 3,
              y: (pts[i - 1].y + pts[i].y + pts[i + 1].y) / 3
            });
          }
          temp.push(pts[pts.length - 1]);
          pts = temp;
        }
      }

      context.beginPath();
      context.moveTo(pts[0].x, pts[0].y);
      if (pts.length === 1) {
        context.lineTo(pts[0].x, pts[0].y);
      } else if (pts.length === 2) {
        context.lineTo(pts[1].x, pts[1].y);
      } else {
        for (let i = 1; i < pts.length - 1; i++) {
          const xc = (pts[i].x + pts[i + 1].x) / 2;
          const yc = (pts[i].y + pts[i + 1].y) / 2;
          context.quadraticCurveTo(pts[i].x, pts[i].y, xc, yc);
        }
        context.lineTo(pts[pts.length - 1].x, pts[pts.length - 1].y);
      }
      context.stroke();
    }
  } else if (shape.type === 'arrow') {
    drawArrow(shape, context);
  } else if (shape.type === 'text') {
    if (!shape.text) return;
    const fontSize = shape.size || 24;
    const lineHeight = fontSize * 1.25;
    const w = shape.w || 200;
    const h = shape.h || 60;

    context.save();
    context.beginPath();
    context.rect(shape.x1, shape.y1, w, h);
    context.clip();

    context.fillStyle = shape.color;
    context.font = `bold ${fontSize}px Inter, Arial, sans-serif`;
    context.textBaseline = 'top';

    const lines = wrapText(context, shape.text, w);
    let currentY = shape.y1;

    for (const line of lines) {
      if (currentY + lineHeight > shape.y1 + h + lineHeight) break;
      context.fillText(line, shape.x1, currentY);
      currentY += lineHeight;
    }

    context.restore();
  } else if (shape.type === 'number') {
    const radius = shape.size || Math.max(14, shape.w * 5);
    context.save();
    context.beginPath();
    context.arc(shape.x1, shape.y1, radius, 0, Math.PI * 2);
    context.fillStyle = shape.color;
    context.fill();
    context.lineWidth = 2;
    context.strokeStyle = '#ffffff';
    context.stroke();
    
    context.fillStyle = '#ffffff';
    context.font = `bold ${Math.max(11, radius * 0.9)}px Inter, Arial, sans-serif`;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(String(shape.n), shape.x1, shape.y1 + 1);
    context.restore();
  } else if (shape.type === 'pencil' || shape.type === 'eraser') {
    if (shape.points && shape.points.length > 0) {
      context.beginPath();
      context.moveTo(shape.points[0].x, shape.points[0].y);
      for (let i = 1; i < shape.points.length; i++) {
        context.lineTo(shape.points[i].x, shape.points[i].y);
      }
      context.stroke();
    }
  }
}

function drawSelectionBox(rect) {
  if (!rect || rect.w < 2 || rect.h < 2) return;
  ctx.save();
  ctx.setLineDash([6, 3]);
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = 2;
  ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
  ctx.fillStyle = 'rgba(37, 99, 235, 0.08)';
  ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
  ctx.restore();
}

function render(forExport = false) {
  if (!state.baseImage) return;
  
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(state.baseImage, 0, 0, canvas.width, canvas.height);
  
  const oCanvas = state.offscreenCanvas;
  const oCtx = state.offscreenCtx;
  if (oCanvas && oCtx) {
    oCtx.clearRect(0, 0, oCanvas.width, oCanvas.height);
    
    state.shapes.forEach(shape => {
      if (shape.type === 'eraser') {
        oCtx.save();
        oCtx.globalCompositeOperation = 'destination-out';
        drawShape(shape, oCtx);
        oCtx.restore();
      } else {
        drawShape(shape, oCtx);
      }
    });
    
    if (state.draft && state.tool !== 'select') {
      if (state.draft.type === 'eraser') {
        oCtx.save();
        oCtx.globalCompositeOperation = 'destination-out';
        drawShape(state.draft, oCtx);
        oCtx.restore();
      } else {
        drawShape(state.draft, oCtx);
      }
    }
    
    ctx.drawImage(oCanvas, 0, 0);
  } else {
    state.shapes.forEach(shape => drawShape(shape, ctx));
    if (state.draft && state.tool !== 'select' && state.draft.type !== 'text') {
      drawShape(state.draft, ctx);
    }
  }
  
  // Marca de agua
  if (state.showBrowserLogo && state.logoImg) {
    const size = 32;
    const padding = 16;
    
    let lx, ly;
    if (state.selection && state.selection.w > (size + padding * 2) && state.selection.h > (size + padding * 2)) {
      lx = state.selection.x + state.selection.w - size - padding;
      ly = state.selection.y + state.selection.h - size - padding;
    } else {
      lx = canvas.width - size - padding;
      ly = canvas.height - size - padding;
    }
    
    ctx.save();
    ctx.globalAlpha = 0.75;
    ctx.beginPath();
    ctx.arc(lx + size / 2, ly + size / 2, size / 2 + 4, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.shadowColor = 'rgba(0, 0, 0, 0.3)';
    ctx.shadowBlur = 6;
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 2;
    ctx.fill();
    
    ctx.drawImage(state.logoImg, lx, ly, size, size);
    ctx.restore();
  }
  
  if (forExport) return;

  if (state.selection) {
    drawSelectionBox(state.selection);
  }
  if (state.draft && state.tool === 'select') {
    drawSelectionBox(normRect(state.draft));
  }
  if (state.draft && state.tool === 'text') {
    const r = normRect(state.draft);
    ctx.save();
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = state.color || '#0076ff';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(r.x, r.y, r.w, r.h);
    ctx.restore();
  }
}

// --- Editor de Texto Interactivo (Inline) ---
const inlineEditor = document.getElementById('inline-text-editor');
const canvasWrap = document.getElementById('canvas-wrap');
let activeTextRect = null;

function openInlineTextEditor(rect) {
  activeTextRect = rect;
  
  const canvasRect = canvas.getBoundingClientRect();
  const wrapRect = canvasWrap.getBoundingClientRect();
  
  const canvasOffsetLeft = canvasRect.left - wrapRect.left + canvasWrap.scrollLeft;
  const canvasOffsetTop = canvasRect.top - wrapRect.top + canvasWrap.scrollTop;
  
  const scaleX = canvasRect.width / canvas.width;
  const scaleY = canvasRect.height / canvas.height;
  
  const screenLeft = canvasOffsetLeft + rect.x * scaleX;
  const screenTop = canvasOffsetTop + rect.y * scaleY;
  const screenWidth = Math.max(120, rect.w * scaleX);
  const screenHeight = Math.max(50, rect.h * scaleY);
  const fontSize = Math.max(12, state.textSize * scaleY);

  inlineEditor.value = '';
  inlineEditor.style.left = `${screenLeft}px`;
  inlineEditor.style.top = `${screenTop}px`;
  inlineEditor.style.width = `${screenWidth}px`;
  inlineEditor.style.height = `${screenHeight}px`;
  inlineEditor.style.fontSize = `${fontSize}px`;
  inlineEditor.style.color = state.color;
  inlineEditor.style.display = 'block';
  
  setTimeout(() => {
    inlineEditor.focus();
  }, 50);
}

function finalizeInlineText() {
  if (!inlineEditor || inlineEditor.style.display === 'none' || !activeTextRect) return;
  
  const text = inlineEditor.value.trim();
  
  const canvasRect = canvas.getBoundingClientRect();
  const scaleX = canvasRect.width / canvas.width;
  const scaleY = canvasRect.height / canvas.height;
  
  const finalW = Math.max(30, inlineEditor.offsetWidth / scaleX);
  const finalH = Math.max(20, inlineEditor.offsetHeight / scaleY);

  if (text) {
    state.shapes.push({
      type: 'text',
      text: text,
      x1: activeTextRect.x,
      y1: activeTextRect.y,
      w: finalW,
      h: finalH,
      color: state.color,
      size: state.textSize
    });
    state.redoStack = [];
    showToast('Texto agregado', 'info');
  }

  inlineEditor.style.display = 'none';
  activeTextRect = null;
  render();
}

if (inlineEditor) {
  inlineEditor.addEventListener('blur', () => {
    finalizeInlineText();
  });

  inlineEditor.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      inlineEditor.value = '';
      inlineEditor.blur();
    }
  });
}

// Eventos de Dibujo
canvas.addEventListener('mousedown', async (e) => {
  if (!state.baseImage) return;

  if (inlineEditor && inlineEditor.style.display !== 'none') {
    finalizeInlineText();
  }

  const p = getPos(e);

  if (state.tool === 'number') {
    state.shapes.push({
      type: 'number',
      n: state.step,
      x1: p.x,
      y1: p.y,
      color: state.color,
      w: state.width,
      size: state.textSize
    });
    state.redoStack = [];
    state.step++;
    updateNumberBadge();
    render();
    showToast(`Paso #${state.step - 1} colocado`, 'info');
    return;
  }

  state.drawing = true;
  if (state.tool === 'pencil' || state.tool === 'eraser' || state.tool === 'curve') {
    state.draft = {
      type: state.tool,
      color: state.color,
      w: state.width * (state.tool === 'eraser' ? 4 : 1),
      points: [p]
    };
  } else {
    state.draft = {
      type: state.tool,
      color: state.tool === 'highlight' ? '#ffe600' : state.color,
      w: state.width,
      x1: p.x,
      y1: p.y,
      x2: p.x,
      y2: p.y
    };
  }
});

canvas.addEventListener('mousemove', (e) => {
  if (!state.drawing || !state.draft) return;
  const p = getPos(e);
  if (state.tool === 'pencil' || state.tool === 'eraser' || state.tool === 'curve') {
    state.draft.points.push(p);
  } else {
    state.draft.x2 = p.x;
    state.draft.y2 = p.y;
  }
  render();
});

canvas.addEventListener('mouseup', () => {
  if (!state.drawing || !state.draft) return;
  state.drawing = false;
  
  if (state.tool === 'text') {
    const rect = normRect(state.draft);
    state.draft = null;
    if (rect.w < 30 || rect.h < 20) {
      rect.w = 200;
      rect.h = 60;
    }
    render();
    openInlineTextEditor(rect);
  } else if (state.tool === 'select') {
    state.selection = normRect(state.draft);
    state.draft = null;
    setStatus(`Recorte activo: ${Math.round(state.selection.w)} x ${Math.round(state.selection.h)} px`);
    showToast('Área de recorte seleccionada', 'info');
    render();
  } else {
    state.shapes.push(state.draft);
    state.redoStack = [];
    state.draft = null;
    render();
  }
});

// Aplicar Zoom
function applyZoom(pct) {
  state.zoom = pct;
  const scale = pct / 100;
  canvas.style.width = `${canvas.width * scale}px`;
  canvas.style.height = `${canvas.height * scale}px`;
  document.getElementById('zoom-value').textContent = `${pct}%`;
}

// Carga de imagen base
function loadBaseImage(dataUrl) {
  const img = new Image();
  img.onload = () => {
    state.baseImage = img;
    state.shapes = [];
    state.redoStack = [];
    state.selection = null;
    state.step = 1;
    updateNumberBadge();
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;

    state.offscreenCanvas = document.createElement('canvas');
    state.offscreenCanvas.width = canvas.width;
    state.offscreenCanvas.height = canvas.height;
    state.offscreenCtx = state.offscreenCanvas.getContext('2d');

    applyZoom(state.zoom);
    render();
    setStatus(`Captura cargada: ${canvas.width} x ${canvas.height} px`);
    showToast('Nueva captura cargada en el editor', 'success');
  };
  img.src = dataUrl;
}

// Exportar Canvas (con o sin recorte)
function getExportDataUrl() {
  if (!state.baseImage) return null;
  
  // Renderizar lienzo limpio sin overlay azul ni bordes punteados de selección
  render(true);
  
  let exportUrl;
  if (state.selection && state.selection.w > 2 && state.selection.h > 2) {
    const sel = state.selection;
    const croppedCanvas = document.createElement('canvas');
    croppedCanvas.width = sel.w;
    croppedCanvas.height = sel.h;
    const cCtx = croppedCanvas.getContext('2d');
    cCtx.drawImage(canvas, sel.x, sel.y, sel.w, sel.h, 0, 0, sel.w, sel.h);
    exportUrl = croppedCanvas.toDataURL('image/png');
  } else {
    exportUrl = canvas.toDataURL('image/png');
  }

  // Restaurar la vista interactiva UI en pantalla
  render(false);

  return exportUrl;
}

// Listeners de UI
document.querySelectorAll('.icon-btn').forEach((btn) => {
  if (btn.id.startsWith('tool-')) {
    btn.onclick = () => setTool(btn.id.replace('tool-', ''));
  }
});

document.getElementById('clear-selection').onclick = () => {
  state.selection = null;
  render();
  setStatus('Selección de recorte eliminada.');
  showToast('Selección eliminada', 'info');
};

document.getElementById('color').oninput = (e) => {
  state.color = e.target.value;
};

document.getElementById('width').oninput = (e) => {
  state.width = Number(e.target.value);
};

document.getElementById('text-size').oninput = (e) => {
  state.textSize = Number(e.target.value);
};

document.getElementById('zoom-range').oninput = (e) => {
  applyZoom(Number(e.target.value));
};

document.getElementById('toggle-logo').onchange = (e) => {
  state.showBrowserLogo = e.target.checked;
  render();
  showToast(state.showBrowserLogo ? 'Marca de agua activada' : 'Marca de agua desactivada', 'info');
};

document.getElementById('undo').onclick = () => {
  if (state.shapes.length > 0) {
    const popped = state.shapes.pop();
    state.redoStack.push(popped);
    if (popped.type === 'number' && state.step > 1) {
      state.step--;
      updateNumberBadge();
    }
    render();
    setStatus('Última acción deshecha.');
    showToast('Acción deshecha', 'info');
  }
};

document.getElementById('redo').onclick = () => {
  if (state.redoStack.length > 0) {
    const restored = state.redoStack.pop();
    state.shapes.push(restored);
    if (restored.type === 'number') {
      state.step++;
      updateNumberBadge();
    }
    render();
    setStatus('Acción rehecha.');
    showToast('Acción rehecha', 'info');
  }
};

document.getElementById('clear').onclick = async () => {
  const confirmed = await confirmClearCustom();
  if (confirmed) {
    state.shapes = [];
    state.redoStack = [];
    state.selection = null;
    state.step = 1;
    updateNumberBadge();
    render();
    setStatus('Anotaciones limpiadas.');
    showToast('Anotaciones eliminadas correctamente', 'warning');
  }
};

document.getElementById('new-screenshot').onclick = () => {
  if (window.electronAPI) {
    window.electronAPI.takeAreaScreenshot();
  }
};

function createBlankCanvas(width = 800, height = 600) {
  const tempCanvas = document.createElement('canvas');
  tempCanvas.width = width;
  tempCanvas.height = height;
  const tCtx = tempCanvas.getContext('2d');
  
  tCtx.fillStyle = '#ffffff';
  tCtx.fillRect(0, 0, width, height);

  const dataUrl = tempCanvas.toDataURL('image/png');
  loadBaseImage(dataUrl);
  setStatus(`Lienzo en blanco listo: ${width} x ${height} px`);
}

function resetEditorState() {
  state.shapes = [];
  state.selection = null;
  state.step = 1;
  state.draft = null;
  state.drawing = false;
  updateNumberBadge();
  createBlankCanvas(800, 600);
}

document.getElementById('open-file').onclick = async () => {
  if (window.electronAPI) {
    const res = await window.electronAPI.openImageFile();
    if (res.success && res.dataUrl) {
      loadBaseImage(res.dataUrl);
      showToast('Imagen cargada correctamente para edición', 'success');
    } else if (!res.canceled && res.error) {
      showToast('Error al abrir la imagen', 'warning');
    }
  }
};

document.getElementById('copy').onclick = async () => {
  const dataUrl = getExportDataUrl();
  if (dataUrl && window.electronAPI) {
    const res = await window.electronAPI.copyToClipboard(dataUrl);
    if (res.success) {
      showToast('Imagen copiada al portapapeles con éxito', 'success');
      setStatus('Captura copiada al portapapeles.');
      setTimeout(() => {
        resetEditorState();
        window.electronAPI.closeEditor();
      }, 250);
    } else {
      showToast('Error al copiar al portapapeles', 'warning');
    }
  }
};

// Modal de Configuración
const settingsDialog = document.getElementById('settings-dialog');
const savePathInput = document.getElementById('save-path-input');
const themeDarkBtn = document.getElementById('theme-dark');
const themeLightBtn = document.getElementById('theme-light');

const appConfig = {
  theme: localStorage.getItem('screenshot_theme') || 'dark',
  defaultSavePath: localStorage.getItem('screenshot_save_path') || ''
};

let tempTheme = appConfig.theme;

function applyTheme(theme) {
  appConfig.theme = theme;
  if (theme === 'light') {
    document.body.classList.add('theme-light');
    if (themeLightBtn) themeLightBtn.classList.add('active-theme');
    if (themeDarkBtn) themeDarkBtn.classList.remove('active-theme');
  } else {
    document.body.classList.remove('theme-light');
    if (themeDarkBtn) themeDarkBtn.classList.add('active-theme');
    if (themeLightBtn) themeLightBtn.classList.remove('active-theme');
  }
}

// Aplicar tema inicial al cargar
applyTheme(appConfig.theme);

if (themeDarkBtn) {
  themeDarkBtn.onclick = () => {
    tempTheme = 'dark';
    themeDarkBtn.classList.add('active-theme');
    themeLightBtn.classList.remove('active-theme');
  };
}

if (themeLightBtn) {
  themeLightBtn.onclick = () => {
    tempTheme = 'light';
    themeLightBtn.classList.add('active-theme');
    themeDarkBtn.classList.remove('active-theme');
  };
}

const btnSettings = document.getElementById('btn-settings');
if (btnSettings) {
  btnSettings.onclick = () => {
    tempTheme = appConfig.theme;
    savePathInput.value = appConfig.defaultSavePath;
    applyTheme(tempTheme);
    settingsDialog.showModal();
  };
}

const btnBrowseFolder = document.getElementById('btn-browse-folder');
if (btnBrowseFolder) {
  btnBrowseFolder.onclick = async () => {
    if (window.electronAPI) {
      const res = await window.electronAPI.selectDirectory();
      if (res.success && res.path) {
        savePathInput.value = res.path;
      }
    }
  };
}

const btnSettingsSave = document.getElementById('btn-settings-save');
if (btnSettingsSave) {
  btnSettingsSave.onclick = () => {
    appConfig.theme = tempTheme;
    appConfig.defaultSavePath = savePathInput.value.trim();
    
    localStorage.setItem('screenshot_theme', appConfig.theme);
    localStorage.setItem('screenshot_save_path', appConfig.defaultSavePath);
    
    applyTheme(appConfig.theme);
    settingsDialog.close();
    showToast('Configuración guardada correctamente', 'success');
  };
}

const btnSettingsCancel = document.getElementById('btn-settings-cancel');
if (btnSettingsCancel) {
  btnSettingsCancel.onclick = () => {
    settingsDialog.close();
    applyTheme(appConfig.theme);
  };
}

document.getElementById('save').onclick = async () => {
  const dataUrl = getExportDataUrl();
  if (dataUrl && window.electronAPI) {
    const res = await window.electronAPI.saveImage(dataUrl, appConfig.defaultSavePath);
    if (res.success) {
      showToast(`Captura guardada con éxito en: ${res.filePath}`, 'success');
      setStatus(`Guardado en: ${res.filePath}`);
    } else if (!res.canceled) {
      showToast('Error al guardar la imagen', 'warning');
    }
  }
};

document.getElementById('minimize-window').onclick = () => {
  if (window.electronAPI) {
    window.electronAPI.minimizeEditor();
  }
};

document.getElementById('maximize-window').onclick = () => {
  if (window.electronAPI) {
    window.electronAPI.maximizeEditor();
  }
};

document.getElementById('cancel').onclick = () => {
  if (window.electronAPI) {
    resetEditorState();
    window.electronAPI.closeEditor();
  }
};

document.getElementById('logo-about').onclick = () => {
  aboutDialog.style.display = 'flex';
};

document.getElementById('btn-about-close').onclick = () => {
  aboutDialog.style.display = 'none';
};

// Listener de Teclado (F9, PrintScreen, Ctrl+Z, Ctrl+Y, Ctrl+Shift+Z, Ctrl+C)
window.addEventListener('keydown', (e) => {
  const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
  if (activeTag === 'input' || activeTag === 'textarea') {
    if (e.key === 'Escape' && document.activeElement.id === 'inline-text-editor') {
      document.activeElement.blur();
    }
    return;
  }

  if (e.key === 'F9' || e.key === 'PrintScreen' || e.code === 'PrintScreen') {
    e.preventDefault();
    if (window.electronAPI) {
      window.electronAPI.takeAreaScreenshot();
    }
  } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'Z' || e.key === 'z')) {
    e.preventDefault();
    document.getElementById('redo').click();
  } else if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || e.key === 'Y')) {
    e.preventDefault();
    document.getElementById('redo').click();
  } else if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
    e.preventDefault();
    document.getElementById('undo').click();
  } else if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C')) {
    e.preventDefault();
    document.getElementById('copy').click();
  }
});

// Escuchar capturas entrantes de Electron
if (window.electronAPI) {
  window.electronAPI.onLoadScreenshot((dataUrl) => {
    loadBaseImage(dataUrl);
  });
}

// Inicializar lienzo en blanco de forma predeterminada
// (Minichrome: solo si el editor se abre sin captura; si no, se vería un aviso de más)
if (!new URLSearchParams(location.search).get('img')) createBlankCanvas(800, 600);
