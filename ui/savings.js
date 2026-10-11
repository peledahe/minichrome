// savings.js – Módulo de Ahorros con gráficas SVG, proyección y análisis por moneda

const savingsState = {
    goals: [],
    activeTab: 'projection'
};

// ─── Helpers ──────────────────────────────────────────────────────────────────
function svgFmtNum(n) {
    return Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function svgGetSymbol(currency) {
    if (currency === 'second') return window.currencyState?.secondSymbol || 'US$';
    return window.currencyState?.symbol || 'Q';
}
function svgGetRate() { return Number(window.currencyState?.exchangeRate) || 7.8; }
function svgToLocal(amount, currency) {
    if (currency === 'second') return amount * svgGetRate();
    return amount;
}
function svgConversionLabel(amount, currency) {
    const rate = svgGetRate();
    const secondEnabled = window.currencyState?.secondEnabled;
    if (currency === 'second') {
        return `(${window.currencyState?.symbol || 'Q'} ${svgFmtNum(amount * rate)})`;
    } else {
        if (!secondEnabled) return '';
        return `(${window.currencyState?.secondSymbol || 'US$'} ${svgFmtNum(amount / rate)})`;
    }
}

// Paleta de colores por objetivo
const GOAL_COLORS = ['#a29bfe','#2ed573','#fdcb6e','#74b9ff','#fd79a8','#ff7675','#55efc4','#e17055'];

// ─── Carga y guardado ────────────────────────────────────────────────────────
async function fetchSavings() {
    if (!py) return;
    try {
        const goals = await py.get_savings();
        savingsState.goals = Array.isArray(goals) ? goals : [];
        renderSavingsHeroCards();
        renderSavingsList();
        renderSavingsChartPanel();
    } catch (err) {
        console.error('fetchSavings error:', err);
    }
}

async function saveSavingsState() {
    if (!py) return;
    await py.save_savings(savingsState.goals);
}

// ─── Tarjetas Hero ────────────────────────────────────────────────────────────
function renderSavingsHeroCards() {
    const container = document.getElementById('savings-hero-cards');
    if (!container) return;

    const localSym = window.currencyState?.symbol || 'Q';
    const secSym = window.currencyState?.secondSymbol || 'US$';
    const secondEnabled = window.currencyState?.secondEnabled;

    const totalGoalLocal = savingsState.goals.reduce((s, g) => s + svgToLocal(g.goal, g.currency), 0);
    const totalAccLocal = savingsState.goals.reduce((s, g) => s + svgToLocal(g.accumulated, g.currency), 0);
    const totalMonthlyLocal = savingsState.goals.reduce((s, g) => s + svgToLocal(g.monthlyAmount || 0, g.currency), 0);
    const globalPct = totalGoalLocal > 0 ? Math.min(100, Math.round((totalAccLocal / totalGoalLocal) * 100)) : 0;

    // Objetivo más próximo a completarse (mayor %)
    const closestGoal = [...savingsState.goals].filter(g => g.goal > 0).sort((a, b) => {
        const pctA = (a.accumulated / a.goal);
        const pctB = (b.accumulated / b.goal);
        return pctB - pctA;
    })[0];
    const nextGoalLabel = closestGoal ? `${Math.min(100,Math.round((closestGoal.accumulated/closestGoal.goal)*100))}% – ${escapeHtml(closestGoal.name)}` : '—';

    const cards = [
        { label: 'Total Ahorrado', value: `${localSym} ${svgFmtNum(totalAccLocal)}`, color: '#2ed573', icon: '💰', bg: 'rgba(46,213,115,0.06)', border: 'rgba(46,213,115,0.2)' },
        { label: 'Meta Total', value: `${localSym} ${svgFmtNum(totalGoalLocal)}`, color: '#a29bfe', icon: '🎯', bg: 'rgba(108,92,231,0.06)', border: 'rgba(108,92,231,0.2)' },
        { label: 'Aporte Mensual', value: `${localSym} ${svgFmtNum(totalMonthlyLocal)}`, color: '#fdcb6e', icon: '📅', bg: 'rgba(253,203,110,0.06)', border: 'rgba(253,203,110,0.2)' },
        { label: 'Progreso Global', value: `${globalPct}%`, color: globalPct >= 100 ? '#2ed573' : '#74b9ff', icon: '📈', bg: 'rgba(116,185,255,0.06)', border: 'rgba(116,185,255,0.2)' }
    ];

    container.innerHTML = cards.map(c => `
        <div style="background:${c.bg}; border:1px solid ${c.border}; border-radius:10px; padding:12px 14px; display:flex; align-items:center; gap:12px; transition:transform 0.15s;" onmouseover="this.style.transform='translateY(-2px)'" onmouseout="this.style.transform=''">
            <span style="font-size:1.5rem; flex-shrink:0;">${c.icon}</span>
            <div>
                <div style="font-size:0.72rem; color:var(--ag-text-muted); font-weight:600;">${c.label}</div>
                <div style="font-size:1.05rem; font-weight:800; color:${c.color}; margin-top:2px;">${c.value}</div>
            </div>
        </div>
    `).join('');

    const badge = document.getElementById('savings-count-badge');
    if (badge) badge.textContent = savingsState.goals.length || '';
}

// ─── Lista de Objetivos (mejorada) ────────────────────────────────────────────
function renderSavingsList() {
    const container = document.getElementById('savings-goals-list');
    if (!container) return;

    if (savingsState.goals.length === 0) {
        container.innerHTML = '<div class="ag-empty">No tienes objetivos de ahorro. ¡Crea uno! 🎯</div>';
        return;
    }

    container.innerHTML = savingsState.goals.map((g, idx) => {
        const sym = svgGetSymbol(g.currency);
        const pct = g.goal > 0 ? Math.min(100, Math.round((g.accumulated / g.goal) * 100)) : 0;
        const remaining = Math.max(0, g.goal - g.accumulated);
        const monthsLeft = (g.monthlyAmount > 0 && remaining > 0) ? Math.ceil(remaining / g.monthlyAmount) : null;
        const color = GOAL_COLORS[idx % GOAL_COLORS.length];
        const barColor = pct >= 100 ? '#2ed573' : color;

        // Días hasta fecha meta
        let dateInfo = '';
        if (g.targetDate) {
            const daysLeft = Math.ceil((new Date(g.targetDate + 'T00:00:00') - new Date()) / 86400000);
            const dateStr = new Date(g.targetDate + 'T00:00:00').toLocaleDateString('es-GT', { day:'2-digit', month:'short', year:'2-digit' });
            const urgency = daysLeft < 30 ? '#ff7675' : daysLeft < 90 ? '#fdcb6e' : 'var(--ag-text-muted)';
            dateInfo = `<span style="color:${urgency}; font-size:0.72rem;">📅 ${dateStr} (${daysLeft > 0 ? daysLeft + 'd' : '¡Hoy!'})</span>`;
        }

        return `
        <div class="savings-goal-card" data-id="${g.id}" style="background:var(--ag-card-bg); border:1px solid var(--ag-border); border-left:3px solid ${color}; border-radius:10px; padding:10px 12px; display:flex; flex-direction:column; gap:7px; transition:transform 0.15s;" onmouseover="this.style.transform='translateX(2px)'" onmouseout="this.style.transform=''">
            <!-- Fila 1: nombre + porcentaje + acciones -->
            <div style="display:flex; justify-content:space-between; align-items:center; gap:6px;">
                <div style="flex:1; min-width:0;">
                    <div style="font-weight:700; font-size:0.86rem; color:var(--ag-text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(g.name)}</div>
                    <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-top:2px;">
                        <span style="font-size:0.7rem; background:rgba(255,255,255,0.05); padding:1px 5px; border-radius:3px; color:var(--ag-text-muted);">${sym}</span>
                        ${dateInfo}
                    </div>
                </div>
                <div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">
                    <span style="font-weight:800; color:${barColor}; font-size:0.98rem;">${pct}%</span>
                    <div style="display:flex; gap:2px;">
                        <button class="ag-btn saving-pay-btn" data-id="${g.id}" title="Registrar aporte"
                            style="padding:3px 7px; font-size:0.7rem; background:rgba(46,213,115,0.1); border:1px solid rgba(46,213,115,0.3); color:#2ed573; font-weight:700; cursor:pointer; border-radius:4px;">+Abono</button>
                        <button class="ag-edit-btn saving-edit-btn" data-id="${g.id}" style="background:none;border:none;cursor:pointer;font-size:0.78rem; padding:2px 3px;">✏️</button>
                        <button class="ag-delete-btn saving-delete-btn" data-id="${g.id}" style="background:none;border:none;cursor:pointer;font-size:0.78rem; padding:2px 3px;">🗑️</button>
                    </div>
                </div>
            </div>

            <!-- Fila 2: Barra de progreso con marcador -->
            <div style="position:relative; height:8px; background:rgba(255,255,255,0.06); border-radius:4px; overflow:hidden;">
                <div style="height:100%; width:${pct}%; background:${barColor}; border-radius:4px; transition:width 0.5s ease;"></div>
            </div>

            <!-- Fila 3: Montos y tiempo restante -->
            <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.72rem; color:var(--ag-text-muted);">
                <span><strong style="color:var(--ag-text);">${sym} ${svgFmtNum(g.accumulated)}</strong> de ${sym} ${svgFmtNum(g.goal)}</span>
                <span style="color:${monthsLeft && monthsLeft <= 3 ? '#fdcb6e' : 'var(--ag-text-muted)'};">
                    ${pct >= 100 ? '🎉 ¡Meta lograda!' : (monthsLeft ? `~${monthsLeft} mes${monthsLeft !== 1 ? 'es' : ''}` : '—')}
                </span>
            </div>
        </div>`;
    }).join('');
}

// ─── Panel de Gráficas (con Tabs) ─────────────────────────────────────────────
function renderSavingsChartPanel() {
    const container = document.getElementById('savings-chart-panel');
    if (!container) return;

    if (savingsState.goals.length === 0) {
        container.innerHTML = '<div class="ag-empty">Agrega objetivos para ver el análisis</div>';
        return;
    }

    switch (savingsState.activeTab) {
        case 'projection': renderTabProjection(container); break;
        case 'currency':   renderTabCurrency(container);   break;
        case 'compare':    renderTabCompare(container);    break;
    }
}

// ─── Tab: Proyección de acumulación mes a mes ─────────────────────────────────
function renderTabProjection(container) {
    const localSym = window.currencyState?.symbol || 'Q';
    const goals = savingsState.goals;

    // Calcular proyección global: suma del acumulado total mes a mes
    const totalAcc = goals.reduce((s, g) => s + svgToLocal(g.accumulated, g.currency), 0);
    const totalGoal = goals.reduce((s, g) => s + svgToLocal(g.goal, g.currency), 0);
    const totalMonthly = goals.reduce((s, g) => s + svgToLocal(g.monthlyAmount || 0, g.currency), 0);

    const maxMonths = 60;
    const history = [];
    let acc = totalAcc;
    for (let m = 0; m <= maxMonths && acc < totalGoal; m++) {
        history.push({ month: m, total: Math.min(acc, totalGoal) });
        acc += totalMonthly;
    }
    if (acc >= totalGoal) history.push({ month: history.length, total: totalGoal });

    // SVG de proyección
    const svgHtml = buildProjectionSvg(history, totalGoal, localSym, totalMonthly);

    // Tabla de objetivos individuales con tiempo estimado
    const rows = goals.map((g, idx) => {
        const sym = svgGetSymbol(g.currency);
        const remaining = Math.max(0, g.goal - g.accumulated);
        const monthsLeft = (g.monthlyAmount > 0 && remaining > 0) ? Math.ceil(remaining / g.monthlyAmount) : null;
        const pct = g.goal > 0 ? Math.min(100, Math.round((g.accumulated / g.goal) * 100)) : 0;
        const color = GOAL_COLORS[idx % GOAL_COLORS.length];
        const yr = monthsLeft ? Math.floor(monthsLeft / 12) : 0;
        const mo = monthsLeft ? monthsLeft % 12 : 0;
        const timeStr = monthsLeft === null ? '—' : (pct >= 100 ? '¡Logrado! 🎉' : (yr > 0 ? `${yr}a ${mo}m` : `${mo} mes${mo !== 1 ? 'es' : ''}`));

        // Mini barra
        return `
        <div style="display:flex; align-items:center; gap:10px; padding:8px 10px; background:rgba(255,255,255,0.02); border-radius:7px; border:1px solid rgba(255,255,255,0.04);">
            <span style="width:10px; height:10px; background:${color}; border-radius:50%; flex-shrink:0;"></span>
            <div style="flex:1; min-width:0;">
                <div style="font-size:0.82rem; font-weight:700; color:var(--ag-text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(g.name)}</div>
                <div style="height:3px; background:rgba(255,255,255,0.05); border-radius:2px; margin-top:4px; overflow:hidden;">
                    <div style="width:${pct}%; background:${color}; height:100%; transition:width 0.4s;"></div>
                </div>
            </div>
            <div style="text-align:right; flex-shrink:0;">
                <div style="font-size:0.8rem; font-weight:800; color:${color};">${timeStr}</div>
                <div style="font-size:0.68rem; color:var(--ag-text-muted);">${sym} ${svgFmtNum(g.monthlyAmount || 0)}/mes</div>
            </div>
        </div>`;
    }).join('');

    container.innerHTML = `
        <!-- Gráfica de proyección global -->
        <div style="position:relative; background:rgba(0,0,0,0.12); border-radius:10px; border:1px solid rgba(255,255,255,0.04); padding:10px 6px 4px 6px; margin-bottom:14px;">
            ${svgHtml}
            <div id="savings-proj-tooltip" style="display:none; position:absolute; background:rgba(20,20,30,0.95); border:1px solid rgba(255,255,255,0.1); border-radius:6px; padding:6px 10px; font-size:0.74rem; color:var(--ag-text); pointer-events:none; z-index:10; white-space:nowrap;"></div>
        </div>
        <!-- Resumen por objetivo -->
        <div style="font-size:0.74rem; color:var(--ag-text-muted); font-weight:700; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;">Tiempo estimado por objetivo</div>
        <div style="display:flex; flex-direction:column; gap:6px;">${rows}</div>
    `;

    // Tooltip de la gráfica
    const svg = container.querySelector('.savings-proj-svg');
    const tooltip = container.querySelector('#savings-proj-tooltip');
    if (svg && tooltip) {
        svg.addEventListener('mousemove', e => {
            const t = e.target;
            if (t.classList.contains('savings-proj-hover')) {
                tooltip.textContent = `Mes ${t.dataset.month}: ${t.dataset.sym} ${t.dataset.total}`;
                tooltip.style.display = 'block';
                const rect = svg.parentElement.getBoundingClientRect();
                tooltip.style.left = (e.clientX - rect.left + 10) + 'px';
                tooltip.style.top = (e.clientY - rect.top - 32) + 'px';
            } else {
                tooltip.style.display = 'none';
            }
        });
        svg.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });
    }
}

function buildProjectionSvg(history, totalGoal, sym, monthlyAdd) {
    if (!history || history.length < 2) {
        return `<svg width="100%" height="100"><text x="50%" y="50%" text-anchor="middle" fill="rgba(255,255,255,0.2)" font-size="12" dominant-baseline="middle">Define aportes mensuales para ver la proyección</text></svg>`;
    }

    const W = 400; // viewBox width
    const H = 100;
    const padL = 52, padR = 12, padT = 8, padB = 22;
    const w = W - padL - padR;
    const h = H - padT - padB;
    const maxM = history[history.length - 1].month || 1;

    const xScale = i => padL + (i / maxM) * w;
    const yScale = v => padT + h - (totalGoal > 0 ? (v / totalGoal) : 0) * h;

    // Grid horizontal
    const grids = [0, 0.25, 0.5, 0.75, 1].map(f => {
        const y = padT + h - f * h;
        const val = f * totalGoal;
        const label = val >= 1000 ? `${(val/1000).toFixed(0)}k` : svgFmtNum(val);
        return `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${padL+w}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,0.04)" stroke-width="1"/>
                <text x="${padL-3}" y="${(y+3).toFixed(1)}" text-anchor="end" fill="rgba(255,255,255,0.28)" font-size="8">${label}</text>`;
    }).join('');

    // X labels
    const step = Math.max(1, Math.ceil(maxM / 6));
    let xLabels = '';
    for (let i = 0; i <= maxM; i += step) {
        xLabels += `<text x="${xScale(i).toFixed(1)}" y="${padT + h + 13}" text-anchor="middle" fill="rgba(255,255,255,0.28)" font-size="8">M${i}</text>`;
    }

    // Línea meta (100%)
    const goalY = padT;
    const goalLineStr = `<line x1="${padL}" y1="${goalY}" x2="${padL+w}" y2="${goalY}" stroke="#2ed573" stroke-width="1" stroke-dasharray="4,4" opacity="0.4"/>
        <text x="${padL+w+2}" y="${goalY+3}" fill="#2ed573" font-size="8" opacity="0.7">Meta</text>`;

    // Path de la curva
    const pts = history.map(p => `${xScale(p.month).toFixed(2)},${yScale(p.total).toFixed(2)}`);
    const linePath = `M ${pts.join(' L ')}`;
    const areaPath = `M ${padL},${padT+h} L ${pts.join(' L ')} L ${xScale(history[history.length-1].month).toFixed(2)},${padT+h} Z`;

    // Puntos hover
    const hoverPts = history.map(p =>
        `<circle cx="${xScale(p.month).toFixed(2)}" cy="${yScale(p.total).toFixed(2)}" r="6" fill="transparent" class="savings-proj-hover"
            data-month="${p.month}" data-total="${svgFmtNum(p.total)}" data-sym="${sym}"/>`
    ).join('');

    return `<svg class="savings-proj-svg" width="100%" viewBox="0 0 ${W} ${H}" style="display:block; overflow:visible;">
        <defs>
            <linearGradient id="savProjGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#2ed573" stop-opacity="0.3"/>
                <stop offset="100%" stop-color="#2ed573" stop-opacity="0.01"/>
            </linearGradient>
        </defs>
        ${grids}${xLabels}${goalLineStr}
        <path d="${areaPath}" fill="url(#savProjGrad)"/>
        <path d="${linePath}" fill="none" stroke="#2ed573" stroke-width="1.8" stroke-linejoin="round"/>
        ${hoverPts}
    </svg>`;
}


// ─── Tab: Por Moneda (Donut SVG) ─────────────────────────────────────────────
function renderTabCurrency(container) {
    const localSym = window.currencyState?.symbol || 'Q';
    const secSym = window.currencyState?.secondSymbol || 'US$';
    const secondEnabled = window.currencyState?.secondEnabled;

    const localGoals = savingsState.goals.filter(g => g.currency === 'local');
    const secondGoals = savingsState.goals.filter(g => g.currency === 'second');

    const sections = [];
    if (localGoals.length > 0) {
        const acc = localGoals.reduce((s, g) => s + g.accumulated, 0);
        const goal = localGoals.reduce((s, g) => s + g.goal, 0);
        sections.push({ label: localSym, acc, goal, color: '#2ed573', goals: localGoals, sym: localSym });
    }
    if (secondGoals.length > 0) {
        const acc = secondGoals.reduce((s, g) => s + g.accumulated, 0);
        const goal = secondGoals.reduce((s, g) => s + g.goal, 0);
        sections.push({ label: secSym, acc, goal, color: '#74b9ff', goals: secondGoals, sym: secSym });
    }

    const donutHtml = sections.map(sec => {
        const pct = sec.goal > 0 ? Math.min(100, Math.round((sec.acc / sec.goal) * 100)) : 0;
        const r = 52, cx = 70, cy = 70;
        const circumference = 2 * Math.PI * r;
        const filled = (pct / 100) * circumference;
        const remaining = circumference - filled;

        return `
        <div style="display:flex; align-items:center; gap:20px; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:10px; padding:14px;">
            <!-- Donut -->
            <svg width="140" height="140" viewBox="0 0 140 140" style="flex-shrink:0;">
                <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="12"/>
                <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${sec.color}" stroke-width="12"
                    stroke-dasharray="${filled.toFixed(2)} ${remaining.toFixed(2)}"
                    stroke-dashoffset="${(circumference / 4).toFixed(2)}"
                    stroke-linecap="round" transform="rotate(-90 ${cx} ${cy})"
                    style="transition:stroke-dasharray 0.6s ease;"/>
                <text x="${cx}" y="${cy - 8}" text-anchor="middle" fill="${sec.color}" font-size="18" font-weight="800">${pct}%</text>
                <text x="${cx}" y="${cy + 10}" text-anchor="middle" fill="rgba(255,255,255,0.5)" font-size="11">${sec.label}</text>
                <text x="${cx}" y="${cy + 24}" text-anchor="middle" fill="rgba(255,255,255,0.35)" font-size="9">${sec.goals.length} objetivo${sec.goals.length !== 1 ? 's' : ''}</text>
            </svg>
            <!-- Datos -->
            <div style="flex:1; display:flex; flex-direction:column; gap:8px;">
                <div>
                    <div style="font-size:0.75rem; color:var(--ag-text-muted); font-weight:600; text-transform:uppercase; letter-spacing:0.04em;">Moneda ${sec.label}</div>
                    <div style="font-size:1.1rem; font-weight:800; color:${sec.color}; margin-top:2px;">${sec.sym} ${svgFmtNum(sec.acc)}</div>
                    <div style="font-size:0.76rem; color:var(--ag-text-muted);">de ${sec.sym} ${svgFmtNum(sec.goal)}</div>
                </div>
                <div style="height:1px; background:rgba(255,255,255,0.05);"></div>
                ${sec.goals.map((g, i) => {
                    const gPct = g.goal > 0 ? Math.min(100, Math.round((g.accumulated/g.goal)*100)) : 0;
                    const c = GOAL_COLORS[savingsState.goals.indexOf(g) % GOAL_COLORS.length];
                    return `<div style="font-size:0.76rem; display:flex; align-items:center; gap:8px;">
                        <span style="width:8px;height:8px;background:${c};border-radius:50%;flex-shrink:0;"></span>
                        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(g.name)}</span>
                        <strong style="color:${c};">${gPct}%</strong>
                    </div>`;
                }).join('')}
            </div>
        </div>`;
    }).join('');

    // Conversión cruzada (si hay segunda moneda)
    let crossHtml = '';
    if (secondEnabled && localGoals.length > 0 && secondGoals.length > 0) {
        const totalLocalAcc = localGoals.reduce((s, g) => s + g.accumulated, 0);
        const totalSecAcc = secondGoals.reduce((s, g) => s + g.accumulated, 0);
        const rate = svgGetRate();
        crossHtml = `
        <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:10px; padding:12px 14px; font-size:0.79rem; display:flex; flex-direction:column; gap:6px;">
            <div style="font-weight:700; color:var(--ag-text-muted); font-size:0.73rem; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:2px;">Equivalencia Total (tasa ${svgFmtNum(rate)})</div>
            <div style="display:flex; justify-content:space-between;">
                <span style="color:var(--ag-text-muted);">Ahorrado en ${localSym}:</span>
                <strong>${localSym} ${svgFmtNum(totalLocalAcc)}</strong>
            </div>
            <div style="display:flex; justify-content:space-between;">
                <span style="color:var(--ag-text-muted);">Ahorrado en ${secSym} → ${localSym}:</span>
                <strong>${localSym} ${svgFmtNum(totalSecAcc * rate)}</strong>
            </div>
            <div style="height:1px;background:rgba(255,255,255,0.06);margin:2px 0;"></div>
            <div style="display:flex; justify-content:space-between;">
                <span style="color:#2ed573; font-weight:700;">Gran Total (${localSym}):</span>
                <strong style="color:#2ed573;">${localSym} ${svgFmtNum(totalLocalAcc + totalSecAcc * rate)}</strong>
            </div>
        </div>`;
    }

    container.innerHTML = sections.length === 0
        ? '<div class="ag-empty">Agrega objetivos para ver el análisis por moneda</div>'
        : `<div style="display:flex; flex-direction:column; gap:12px;">${donutHtml}${crossHtml}</div>`;
}

// ─── Tab: Comparar objetivos (barras horizontales) ────────────────────────────
function renderTabCompare(container) {
    const goals = savingsState.goals;
    if (goals.length === 0) {
        container.innerHTML = '<div class="ag-empty">No hay objetivos para comparar</div>';
        return;
    }

    // Ordenar por % de progreso desc
    const sorted = [...goals].map(g => ({
        ...g,
        pct: g.goal > 0 ? Math.min(100, (g.accumulated / g.goal) * 100) : 0
    })).sort((a, b) => b.pct - a.pct);

    const maxGoalLocal = Math.max(...sorted.map(g => svgToLocal(g.goal, g.currency)), 1);

    const bars = sorted.map((g, idx) => {
        const sym = svgGetSymbol(g.currency);
        const color = GOAL_COLORS[goals.indexOf(g) % GOAL_COLORS.length];
        const pctDisplay = g.pct.toFixed(1);
        const remaining = Math.max(0, g.goal - g.accumulated);
        const monthsLeft = (g.monthlyAmount > 0 && remaining > 0) ? Math.ceil(remaining / g.monthlyAmount) : null;
        const goalBarPct = Math.min(100, (svgToLocal(g.goal, g.currency) / maxGoalLocal) * 100);

        return `
        <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.04); border-radius:9px; padding:12px 14px; display:flex; flex-direction:column; gap:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="width:28px; height:28px; background:rgba(255,255,255,0.04); border:2px solid ${color}; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:0.72rem; font-weight:800; color:${color}; flex-shrink:0;">${idx+1}</span>
                    <div>
                        <div style="font-weight:700; font-size:0.85rem; color:var(--ag-text);">${escapeHtml(g.name)}</div>
                        <div style="font-size:0.72rem; color:var(--ag-text-muted);">Meta: ${sym} ${svgFmtNum(g.goal)}</div>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-weight:800; color:${color}; font-size:1rem;">${pctDisplay}%</div>
                    <div style="font-size:0.7rem; color:var(--ag-text-muted);">${monthsLeft ? `~${monthsLeft} meses` : (g.pct >= 100 ? '🎉 Logrado' : '—')}</div>
                </div>
            </div>

            <!-- Barra de progreso de acumulado -->
            <div>
                <div style="font-size:0.68rem; color:var(--ag-text-muted); margin-bottom:3px; display:flex; justify-content:space-between;">
                    <span>Progreso: ${sym} ${svgFmtNum(g.accumulated)}</span>
                    <span>Faltan: ${sym} ${svgFmtNum(Math.max(0,g.goal-g.accumulated))}</span>
                </div>
                <div style="height:10px; background:rgba(255,255,255,0.05); border-radius:5px; overflow:hidden; position:relative;">
                    <div style="height:100%; width:${g.pct.toFixed(1)}%; background:${color}; border-radius:5px; transition:width 0.5s;"></div>
                </div>
            </div>

            <!-- Barra de tamaño relativo de meta -->
            <div>
                <div style="font-size:0.68rem; color:var(--ag-text-muted); margin-bottom:3px;">Tamaño relativo de la meta</div>
                <div style="height:5px; background:rgba(255,255,255,0.04); border-radius:3px; overflow:hidden;">
                    <div style="height:100%; width:${goalBarPct.toFixed(1)}%; background:rgba(255,255,255,0.12); border-radius:3px;"></div>
                </div>
            </div>
        </div>`;
    }).join('');

    container.innerHTML = `<div style="display:flex; flex-direction:column; gap:10px;">${bars}</div>`;
}

// ─── Modal ────────────────────────────────────────────────────────────────────
function openSavingModal(id = null) {
    const modal = document.getElementById('saving-editor-modal');
    if (!modal) return;

    document.getElementById('saving-modal-title').textContent = id ? 'Editar Objetivo' : 'Nuevo Objetivo de Ahorro';
    document.getElementById('saving-id-hidden').value = id || '';

    if (id) {
        const g = savingsState.goals.find(g => g.id === id);
        if (!g) return;
        document.getElementById('saving-name-input').value = g.name;
        document.getElementById('saving-currency-select').value = g.currency;
        document.getElementById('saving-goal-input').value = g.goal;
        document.getElementById('saving-accumulated-input').value = g.accumulated;
        document.getElementById('saving-monthly-input').value = g.monthlyAmount;
        document.getElementById('saving-date-input').value = g.targetDate || '';
        document.getElementById('saving-notes-input').value = g.notes || '';
    } else {
        document.getElementById('saving-name-input').value = '';
        document.getElementById('saving-currency-select').value = 'local';
        document.getElementById('saving-goal-input').value = '';
        document.getElementById('saving-accumulated-input').value = '';
        document.getElementById('saving-monthly-input').value = '';
        document.getElementById('saving-date-input').value = '';
        document.getElementById('saving-notes-input').value = '';
    }

    modal.classList.add('active');
    setTimeout(() => document.getElementById('saving-name-input')?.focus(), 50);
}

async function saveSavingGoal() {
    const name = (document.getElementById('saving-name-input')?.value || '').trim();
    const currency = document.getElementById('saving-currency-select')?.value || 'local';
    const goal = parseFloat(document.getElementById('saving-goal-input')?.value || '0');
    const accumulated = parseFloat(document.getElementById('saving-accumulated-input')?.value || '0');
    const monthlyAmount = parseFloat(document.getElementById('saving-monthly-input')?.value || '0');
    const targetDate = document.getElementById('saving-date-input')?.value || '';
    const notes = (document.getElementById('saving-notes-input')?.value || '').trim();
    const idVal = document.getElementById('saving-id-hidden')?.value;

    if (!name || isNaN(goal) || goal <= 0) {
        window.showToast('Completa al menos el nombre y la meta del objetivo', 'error');
        return;
    }

    if (idVal) {
        const g = savingsState.goals.find(g => g.id === Number(idVal));
        if (g) Object.assign(g, { name, currency, goal, accumulated, monthlyAmount, targetDate, notes });
    } else {
        const newId = savingsState.goals.length > 0 ? Math.max(...savingsState.goals.map(g => g.id)) + 1 : 1;
        savingsState.goals.push({ id: newId, name, currency, goal, accumulated, monthlyAmount, targetDate, notes });
    }

    await saveSavingsState();
    document.getElementById('saving-editor-modal')?.classList.remove('active');
    window.showToast(idVal ? 'Objetivo actualizado exitosamente' : 'Objetivo de ahorro creado', 'success');
    fetchSavings();
}

async function deleteSavingGoal(id) {
    window.showConfirm('¿Eliminar este objetivo de ahorro permanentemente?', async (ok) => {
        if (!ok) return;
        savingsState.goals = savingsState.goals.filter(g => g.id !== id);
        await saveSavingsState();
        window.showToast('Objetivo eliminado', 'success');
        fetchSavings();
    });
}

async function paySavingQuota(id) {
    const g = savingsState.goals.find(g => g.id === id);
    if (!g) return;
    const sym = svgGetSymbol(g.currency);
    const amount = g.monthlyAmount;
    if (!amount || amount <= 0) {
        window.showToast('Define un monto mensual para este objetivo primero', 'error');
        return;
    }

    window.showConfirm(`¿Registrar aporte de ${sym} ${svgFmtNum(amount)} a "${g.name}"?`, async (ok) => {
        if (!ok) return;
        g.accumulated = Math.min(g.goal, g.accumulated + amount);

        if (py?.add_shopping) {
            await py.add_shopping(`Ahorro: ${g.name}`, amount, g.currency,
                new Date().toISOString().split('T')[0], '', 'Ahorros');
        }

        await saveSavingsState();

        if (g.accumulated >= g.goal) {
            window.showToast(`🎉 ¡Meta "${g.name}" completada! Felicidades.`, 'success');
        } else {
            window.showToast(`Aporte de ${sym} ${svgFmtNum(amount)} registrado`, 'success');
        }

        fetchSavings();

        if (document.getElementById('view-budget')?.classList.contains('active')) {
            if (window.fetchBudget) window.fetchBudget();
        }
    });
}

// ─── Compat: savings-summary-panel (si queda referencia antigua) ───────────────
function renderSavingsSummary() {
    // Re-renderizar el panel actual por compatibilidad
    renderSavingsChartPanel();
}

// ─── Init ─────────────────────────────────────────────────────────────────────
function initSavingsListeners() {
    document.getElementById('open-new-saving-btn')?.addEventListener('click', () => openSavingModal());

    document.getElementById('savings-goals-list')?.addEventListener('click', (e) => {
        const payBtn = e.target.closest('.saving-pay-btn');
        if (payBtn) { paySavingQuota(Number(payBtn.getAttribute('data-id'))); return; }
        const editBtn = e.target.closest('.saving-edit-btn');
        if (editBtn) { openSavingModal(Number(editBtn.getAttribute('data-id'))); return; }
        const deleteBtn = e.target.closest('.saving-delete-btn');
        if (deleteBtn) { deleteSavingGoal(Number(deleteBtn.getAttribute('data-id'))); return; }
    });

    document.getElementById('save-saving-modal-btn')?.addEventListener('click', saveSavingGoal);
    document.getElementById('close-saving-modal-cancel')?.addEventListener('click', () =>
        document.getElementById('saving-editor-modal')?.classList.remove('active'));
    document.getElementById('close-saving-modal-x')?.addEventListener('click', () =>
        document.getElementById('saving-editor-modal')?.classList.remove('active'));

    // Tabs de visualización
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.savings-tab-btn');
        if (!btn) return;
        const tab = btn.getAttribute('data-tab');
        savingsState.activeTab = tab;

        document.querySelectorAll('.savings-tab-btn').forEach(b => {
            const isActive = b.getAttribute('data-tab') === tab;
            b.style.background = isActive ? 'rgba(46,213,115,0.2)' : 'none';
            b.style.border = isActive ? '1px solid rgba(46,213,115,0.4)' : '1px solid transparent';
            b.style.color = isActive ? '#2ed573' : 'var(--ag-text-muted)';
        });

        renderSavingsChartPanel();
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSavingsListeners);
} else {
    initSavingsListeners();
}

window.fetchSavings = fetchSavings;
window.openSavingModal = openSavingModal;
window.saveSavingGoal = saveSavingGoal;
window.deleteSavingGoal = deleteSavingGoal;
window.paySavingQuota = paySavingQuota;
