// debts.js - Planificador de Deudas con soporte Multi-moneda y simulación Bola de Nieve / Avalancha

const debtsState = {
    debts: [],
    budget: 0,
    method: localStorage.getItem('debtsMethod') || 'snowball' // 'snowball' | 'avalanche'
};

function debtFmtNum(n) {
    return Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function debtGetSymbol(currency) {
    if (currency === 'second') return window.currencyState?.secondSymbol || 'US$';
    return window.currencyState?.symbol || 'Q';
}

function debtGetRate() {
    return Number(window.currencyState?.exchangeRate) || 7.8;
}

function debtToLocal(amount, currency) {
    if (currency === 'second') return amount * debtGetRate();
    return amount;
}

function debtFromLocal(amount, currency) {
    if (currency === 'second') return amount / debtGetRate();
    return amount;
}

function debtConversionLabel(amount, currency) {
    const rate = debtGetRate();
    const secondEnabled = window.currencyState?.secondEnabled;
    if (currency === 'second') {
        return `(${window.currencyState?.symbol || 'Q'} ${debtFmtNum(amount * rate)})`;
    } else {
        if (!secondEnabled) return '';
        return `(${window.currencyState?.secondSymbol || 'US$'} ${debtFmtNum(amount / rate)})`;
    }
}

// ── Fetch ───────────────────────────────────────────────────────────────────
async function fetchDebts() {
    try {
        if (!py) return;

        const [debtsList, budgetVal] = await Promise.all([
            py.get_debts(),
            py.get_debts_budget()
        ]);

        debtsState.debts = Array.isArray(debtsList) ? debtsList : [];
        debtsState.budget = Number(budgetVal) || 0;

        const budgetInput = document.getElementById('debts-budget-input');
        if (budgetInput) budgetInput.value = debtsState.budget || '';

        const sym = debtGetSymbol('local');
        const budgetSym = document.getElementById('debts-budget-symbol');
        if (budgetSym) budgetSym.textContent = sym;

        renderDebtsSummaryCards();
        renderDebtsList();
        renderSnowballProjection();
    } catch (err) {
        console.error('Error fetching debts:', err);
        const container = document.getElementById('debts-list');
        if (container) container.innerHTML = '<div class="ag-empty">Error al cargar las deudas</div>';
    }
}

async function saveDebtsState() {
    if (!py) return;
    await Promise.all([
        py.save_debts(debtsState.debts),
        py.save_debts_budget(debtsState.budget)
    ]);
}

// ── Tarjetas Hero ────────────────────────────────────────────────────────────
function renderDebtsSummaryCards() {
    const container = document.getElementById('debts-summary-cards');
    if (!container) return;

    const sym = debtGetSymbol('local');
    const totalDebtLocal = debtsState.debts.reduce((s, d) => s + debtToLocal(d.balance, d.currency), 0);
    const totalMinLocal = debtsState.debts.reduce((s, d) => s + debtToLocal(d.minPayment, d.currency), 0);
    const extraLocal = Math.max(0, debtsState.budget - totalMinLocal);

    let monthsEst = 0;
    if (debtsState.debts.length > 0) {
        const sim = runSimulation();
        monthsEst = sim.length > 0 ? sim.length - 1 : 0;
    }
    const yearsEst = Math.floor(monthsEst / 12);
    const moEst = monthsEst % 12;
    const timeLabel = monthsEst === 0 ? '—' : (yearsEst > 0 ? `${yearsEst}a ${moEst}m` : `${moEst} mes${moEst !== 1 ? 'es' : ''}`);

    const cards = [
        { label: 'Total Adeudado', value: `${sym} ${debtFmtNum(totalDebtLocal)}`, color: '#ff7675', icon: '💳', bg: 'rgba(255,118,117,0.06)', border: 'rgba(255,118,117,0.2)' },
        { label: 'Pagos Mínimos Total', value: `${sym} ${debtFmtNum(totalMinLocal)}`, color: '#fdcb6e', icon: '📋', bg: 'rgba(253,203,110,0.06)', border: 'rgba(253,203,110,0.2)' },
        { label: 'Extra Bola de Nieve', value: `${sym} ${debtFmtNum(extraLocal)}`, color: '#a29bfe', icon: '❄️', bg: 'rgba(108,92,231,0.06)', border: 'rgba(108,92,231,0.2)' },
        { label: 'Libre de Deuda en', value: timeLabel, color: '#2ed573', icon: '🏆', bg: 'rgba(46,213,115,0.06)', border: 'rgba(46,213,115,0.2)' }
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
}

// ── Lista de Deudas ──────────────────────────────────────────────────────────
function renderDebtsList() {
    const container = document.getElementById('debts-list');
    if (!container) return;

    const badge = document.getElementById('debts-count-badge');

    if (debtsState.debts.length === 0) {
        container.innerHTML = '<div class="ag-empty">No tienes deudas registradas 🎉</div>';
        if (badge) badge.textContent = '';
        return;
    }

    if (badge) badge.textContent = debtsState.debts.length;

    const sortedDebts = sortDebtsForMethod(debtsState.debts);
    const maxBalanceLocal = Math.max(...sortedDebts.map(d => debtToLocal(d.balance, d.currency)), 1);
    const effectivePayments = computeEffectivePayments();
    const totalMinLocal = sortedDebts.reduce((s, d) => s + debtToLocal(d.minPayment, d.currency), 0);
    const hasExtra = debtsState.budget > totalMinLocal;

    container.innerHTML = sortedDebts.map((d, index) => {
        const dSym = debtGetSymbol(d.currency);
        const balLocal = debtToLocal(d.balance, d.currency);
        const pct = Math.min(100, (balLocal / maxBalanceLocal) * 100);
        const isTarget = index === 0;
        const color = isTarget ? '#a29bfe' : '#ff7675';
        const effective = effectivePayments.get(d.id) || d.minPayment;
        const showExtra = isTarget && hasExtra && debtsState.budget > 0;
        const convBal = debtConversionLabel(d.balance, d.currency);

        return `
        <div class="ag-item debt-item-card" style="background:var(--ag-card-bg); border:1px solid var(--ag-border); border-radius:10px; padding:12px 14px; display:flex; flex-direction:column; gap:8px; transition:transform 0.15s;" onmouseover="this.style.transform='translateX(2px)'" onmouseout="this.style.transform=''">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="display:flex; align-items:center; gap:10px;">
                    <span style="background:${color}; color:#fff; width:22px; height:22px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:0.74rem; font-weight:800; flex-shrink:0;">${index + 1}</span>
                    <div>
                        <div style="font-weight:700; font-size:0.88rem; color:var(--ag-text);">${escapeHtml(d.name)}</div>
                        <div style="font-size:0.73rem; color:var(--ag-text-muted); display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                            <span>Mínimo: <strong style="color:var(--ag-text);">${dSym} ${debtFmtNum(d.minPayment)}</strong></span>
                            ${showExtra ? `<span style="color:#a29bfe; font-weight:700; background:rgba(108,92,231,0.1); padding:1px 6px; border-radius:4px;">→ Abono: ${dSym} ${debtFmtNum(effective)} ❄️</span>` : ''}
                        </div>
                    </div>
                </div>
                <div style="text-align:right; display:flex; align-items:center; gap:8px;">
                    <div>
                        <div style="font-weight:800; color:#ff7675; font-size:0.98rem;">${dSym} ${debtFmtNum(d.balance)}</div>
                        <div style="font-size:0.7rem; color:var(--ag-text-muted);">${convBal ? convBal : 'saldo'}</div>
                    </div>
                    <div style="display:flex; gap:3px;">
                        <button class="ag-btn debt-pay-btn" data-id="${d.id}" title="Registrar abono de ${dSym} ${debtFmtNum(effective)}"
                            style="padding:3px 8px; font-size:0.72rem; background:rgba(46,213,115,0.12); border:1px solid #2ed573; color:#2ed573; font-weight:700; cursor:pointer; border-radius:5px;">Abonar</button>
                        <button class="ag-edit-btn debt-edit-btn" data-id="${d.id}" style="background:none; border:none; cursor:pointer; font-size:0.82rem; padding:2px 4px;">✏️</button>
                        <button class="ag-delete-btn debt-delete-btn" data-id="${d.id}" style="background:none; border:none; cursor:pointer; font-size:0.82rem; padding:2px 4px;">🗑️</button>
                    </div>
                </div>
            </div>
            <div style="height:4px; background:rgba(255,255,255,0.06); border-radius:2px; overflow:hidden;">
                <div style="height:100%; width:${pct.toFixed(1)}%; background:${color}; border-radius:2px; transition:width 0.4s;"></div>
            </div>
        </div>
        `;
    }).join('');
}

// ── Motor de Simulación ─────────────────────────────────────────────────────
function sortDebtsForMethod(debts) {
    const copy = [...debts];
    if (debtsState.method === 'avalanche') {
        // Ordenar por pago mínimo local equivalente (avalancha) desc
        return copy.sort((a, b) => debtToLocal(b.minPayment, b.currency) - debtToLocal(a.minPayment, a.currency));
    }
    // Ordenar por saldo local equivalente desc (bola de nieve) asc
    return copy.sort((a, b) => debtToLocal(a.balance, a.currency) - debtToLocal(b.balance, b.currency));
}

function computeEffectivePayments() {
    const sorted = sortDebtsForMethod(debtsState.debts);
    const totalMinLocal = sorted.reduce((s, d) => s + debtToLocal(d.minPayment, d.currency), 0);
    const extraLocal = debtsState.budget > 0 ? Math.max(0, debtsState.budget - totalMinLocal) : 0;

    const result = new Map();
    sorted.forEach((d, i) => {
        const balLocal = debtToLocal(d.balance, d.currency);
        const minLocal = debtToLocal(d.minPayment, d.currency);

        const baseLocal = Math.min(balLocal, minLocal);
        const bonusLocal = (i === 0 && extraLocal > 0) ? Math.min(balLocal - baseLocal, extraLocal) : 0;

        const totalLocal = baseLocal + bonusLocal;
        const totalOriginal = debtFromLocal(totalLocal, d.currency);

        result.set(d.id, totalOriginal);
    });
    return result;
}

function runSimulation() {
    if (debtsState.debts.length === 0) return [];

    const sortedDebts = sortDebtsForMethod(debtsState.debts);
    const totalMinLocal = sortedDebts.reduce((s, d) => s + debtToLocal(d.minPayment, d.currency), 0);

    const sim = sortedDebts.map(d => ({
        ...d,
        balance: debtToLocal(d.balance, d.currency),
        minPayment: debtToLocal(d.minPayment, d.currency)
    }));

    let month = 0;
    const maxMonths = 120;
    const history = [{ month: 0, total: sim.reduce((s, d) => s + d.balance, 0) }];

    while (sim.some(d => d.balance > 0) && month < maxMonths) {
        month++;
        let availableLocal = debtsState.budget > 0 ? debtsState.budget : totalMinLocal;

        const active = sim.filter(d => d.balance > 0);

        active.forEach(d => {
            const payLocal = Math.min(d.balance, d.minPayment);
            d.balance -= payLocal;
            availableLocal -= payLocal;
        });

        if (availableLocal > 0) {
            const target = sim.find(d => d.balance > 0);
            if (target) {
                const extraLocal = Math.min(target.balance, availableLocal);
                target.balance -= extraLocal;
                availableLocal -= extraLocal;
            }
        }

        const total = sim.reduce((s, d) => s + Math.max(0, d.balance), 0);
        history.push({ month, total });

        sim.forEach(d => {
            if (d.balance <= 0 && !d.monthsToClear) d.monthsToClear = month;
        });
    }

    history._debts = sim;
    return history;
}

// ── Gráfica SVG ─────────────────────────────────────────────────────────────
function renderDebtChart(history) {
    const svg = document.getElementById('debts-chart-svg');
    const tooltip = document.getElementById('debts-chart-tooltip');
    if (!svg) return;

    if (!history || history.length < 2) {
        svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="rgba(255,255,255,0.2)" font-size="13" dominant-baseline="middle">Sin datos suficientes</text>';
        return;
    }

    const W = Math.max(200, svg.parentElement.clientWidth - 12);
    const H = 150;
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);

    const sym = debtGetSymbol('local');
    const maxVal = history[0].total || 1;
    const months = history.length - 1;
    const padL = 52, padR = 12, padT = 10, padB = 28;
    const w = W - padL - padR;
    const h = H - padT - padB;

    const xScale = i => padL + (months > 0 ? (i / months) : 0) * w;
    const yScale = v => padT + h - (v / maxVal) * h;

    const gridLines = [0, 0.25, 0.5, 0.75, 1].map(f => {
        const y = padT + h - f * h;
        const val = f * maxVal;
        const label = val >= 1000 ? `${(val/1000).toFixed(0)}k` : debtFmtNum(val);
        return `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${padL + w}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,0.04)" stroke-width="1"/>
                <text x="${padL - 4}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="rgba(255,255,255,0.3)" font-size="9">${sym}${label}</text>`;
    }).join('');

    const step = Math.max(1, Math.ceil(months / 5));
    let xLabels = '';
    for (let i = 0; i <= months; i += step) {
        xLabels += `<text x="${xScale(i).toFixed(1)}" y="${padT + h + 16}" text-anchor="middle" fill="rgba(255,255,255,0.3)" font-size="9">M${i}</text>`;
    }

    const pts = history.map((p, i) => `${xScale(i).toFixed(2)},${yScale(p.total).toFixed(2)}`);
    const linePath = `M ${pts.join(' L ')}`;
    const areaPath = `M ${padL},${padT + h} L ${pts.join(' L ')} L ${xScale(months).toFixed(2)},${padT + h} Z`;

    const colors = ['#2ed573','#fdcb6e','#a29bfe','#74b9ff','#ff7675','#fd79a8'];
    let debtMarkers = '';
    if (history._debts) {
        history._debts.forEach((d, di) => {
            if (d.monthsToClear && d.monthsToClear <= months) {
                const p = history[d.monthsToClear];
                if (!p) return;
                const cx = xScale(d.monthsToClear).toFixed(2);
                const cy = yScale(p.total).toFixed(2);
                const c = colors[di % colors.length];
                const safeName = (d.name || '').replace(/"/g, '&quot;');
                debtMarkers += `
                    <line x1="${cx}" y1="${cy}" x2="${cx}" y2="${padT + h}" stroke="${c}" stroke-width="1" stroke-dasharray="2,3" opacity="0.5"/>
                    <circle cx="${cx}" cy="${cy}" r="5" fill="${c}" stroke="#1a1a2e" stroke-width="1.5" opacity="0.95"
                        class="debt-chart-marker" data-month="${d.monthsToClear}" data-name="${safeName}" data-total="${debtFmtNum(p.total)}" data-sym="${sym}"/>`;
            }
        });
    }

    const hoverPts = history.map((p, i) => {
        const cx = xScale(i).toFixed(2);
        const cy = yScale(p.total).toFixed(2);
        return `<circle cx="${cx}" cy="${cy}" r="8" fill="transparent" class="debt-chart-hover"
            data-month="${p.month}" data-total="${debtFmtNum(p.total)}" data-sym="${sym}"/>`;
    }).join('');

    svg.innerHTML = `
        <defs>
            <linearGradient id="debtChartGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#a29bfe" stop-opacity="0.3"/>
                <stop offset="100%" stop-color="#a29bfe" stop-opacity="0.01"/>
            </linearGradient>
        </defs>
        ${gridLines}${xLabels}
        <path d="${areaPath}" fill="url(#debtChartGrad)"/>
        <path d="${linePath}" fill="none" stroke="#a29bfe" stroke-width="2" stroke-linejoin="round"/>
        ${debtMarkers}${hoverPts}`;

    const newSvg = svg.cloneNode(true);
    svg.parentNode.replaceChild(newSvg, svg);

    newSvg.addEventListener('mousemove', (e) => {
        const t = e.target;
        if (t.classList.contains('debt-chart-hover')) {
            tooltip.textContent = `Mes ${t.dataset.month}: ${t.dataset.sym} ${t.dataset.total}`;
            tooltip.style.display = 'block';
        } else if (t.classList.contains('debt-chart-marker')) {
            tooltip.textContent = `✅ ${t.dataset.name} — Mes ${t.dataset.month}`;
            tooltip.style.display = 'block';
        } else {
            tooltip.style.display = 'none';
        }
        if (tooltip.style.display !== 'none') {
            const rect = newSvg.parentElement.getBoundingClientRect();
            tooltip.style.left = (e.clientX - rect.left + 10) + 'px';
            tooltip.style.top = (e.clientY - rect.top - 32) + 'px';
        }
    });
    newSvg.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });
}

// ── Proyección / Timeline ────────────────────────────────────────────────────
function renderSnowballProjection() {
    const container = document.getElementById('debts-projection-timeline');
    if (!container) return;

    if (debtsState.debts.length === 0) {
        container.innerHTML = '<div class="ag-empty">Agrega deudas para ver la proyección</div>';
        renderDebtChart(null);
        return;
    }

    const sym = debtGetSymbol('local');
    const sortedDebts = sortDebtsForMethod(debtsState.debts);
    const totalMinPaymentLocal = sortedDebts.reduce((s, d) => s + debtToLocal(d.minPayment, d.currency), 0);

    if (debtsState.budget > 0 && debtsState.budget < totalMinPaymentLocal) {
        container.innerHTML = `
            <div style="background:rgba(255,118,117,0.08); border:1px solid rgba(255,118,117,0.3); border-radius:8px; padding:14px; color:#ff7675; font-size:0.86rem; display:flex; align-items:flex-start; gap:10px;">
                <span style="font-size:1.2rem; flex-shrink:0;">⚠️</span>
                <div>
                    <strong>Presupuesto insuficiente:</strong><br>
                    Tu presupuesto <em>(${sym} ${debtFmtNum(debtsState.budget)})</em> no cubre los pagos mínimos <em>(${sym} ${debtFmtNum(totalMinPaymentLocal)})</em>.<br>
                    Aumenta el presupuesto mensual para activar el simulador.
                </div>
            </div>`;
        renderDebtChart(null);
        return;
    }

    const history = runSimulation();
    const simDebts = history._debts || [];
    const totalMonths = history.length - 1;

    renderDebtChart(history);

    const colors = ['#2ed573','#fdcb6e','#a29bfe','#74b9ff','#ff7675','#fd79a8'];
    const rows = simDebts.map((d, i) => {
        const dSym = debtGetSymbol(d.currency);
        const mo = d.monthsToClear || totalMonths;
        const yr = Math.floor(mo / 12);
        const rem = mo % 12;
        const timeStr = yr > 0 ? `${yr}a ${rem}m` : `${rem} mes${rem !== 1 ? 'es' : ''}`;
        const c = colors[i % colors.length];
        return `
        <div style="display:flex; align-items:center; gap:10px; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.04); border-radius:8px; padding:10px 12px;">
            <span style="width:10px; height:10px; background:${c}; border-radius:50%; flex-shrink:0;"></span>
            <div style="flex:1; min-width:0;">
                <div style="font-weight:700; font-size:0.84rem; color:var(--ag-text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(d.name)}</div>
                <div style="font-size:0.73rem; color:var(--ag-text-muted);">Mínimo: ${dSym} ${debtFmtNum(d.minPayment)}</div>
            </div>
            <div style="text-align:right; flex-shrink:0;">
                <div style="font-weight:800; color:${c}; font-size:0.9rem;">${timeStr}</div>
                <div style="font-size:0.7rem; color:var(--ag-text-muted);">Mes ${mo}</div>
            </div>
        </div>`;
    }).join('');

    container.innerHTML = `
        <div style="font-size:0.75rem; color:var(--ag-text-muted); font-weight:700; margin-bottom:8px; text-transform:uppercase; letter-spacing:0.05em;">Orden de liquidación</div>
        <div style="display:flex; flex-direction:column; gap:6px;">${rows}</div>`;
}

// ── Modal ─────────────────────────────────────────────────────────────────────
function openDebtModal(id = null) {
    const modal = document.getElementById('debt-editor-modal');
    if (!modal) return;

    const title = document.getElementById('debt-modal-title');
    const nameInput = document.getElementById('debt-name-input');
    const balanceInput = document.getElementById('debt-balance-input');
    const minPayInput = document.getElementById('debt-minpay-input');
    const idInput = document.getElementById('debt-id-hidden');
    const currencySelect = document.getElementById('debt-currency-select');

    if (id) {
        const debt = debtsState.debts.find(d => d.id === id);
        if (!debt) return;
        title.textContent = 'Editar Deuda';
        nameInput.value = debt.name;
        balanceInput.value = debt.balance;
        minPayInput.value = debt.minPayment;
        idInput.value = debt.id;
        if (currencySelect) currencySelect.value = debt.currency || 'local';
    } else {
        title.textContent = 'Nueva Deuda';
        nameInput.value = '';
        balanceInput.value = '';
        minPayInput.value = '';
        idInput.value = '';
        if (currencySelect) currencySelect.value = 'local';
    }

    modal.classList.add('active');
}

async function saveDebt() {
    const name = (document.getElementById('debt-name-input')?.value || '').trim();
    const balance = parseFloat(document.getElementById('debt-balance-input')?.value || '0');
    const minPayment = parseFloat(document.getElementById('debt-minpay-input')?.value || '0');
    const currency = document.getElementById('debt-currency-select')?.value || 'local';
    const id = document.getElementById('debt-id-hidden')?.value;

    if (!name || Number.isNaN(balance) || Number.isNaN(minPayment) || balance < 0 || minPayment < 0) {
        window.showToast('Por favor completa todos los campos con valores válidos', 'error');
        return;
    }

    if (id) {
        const debt = debtsState.debts.find(d => d.id === Number(id));
        if (debt) {
            debt.name = name;
            debt.balance = balance;
            debt.minPayment = minPayment;
            debt.currency = currency;
        }
    } else {
        const newId = debtsState.debts.length > 0 ? Math.max(...debtsState.debts.map(d => d.id)) + 1 : 1;
        debtsState.debts.push({ id: newId, name, balance, minPayment, currency });
    }

    await saveDebtsState();
    document.getElementById('debt-editor-modal')?.classList.remove('active');
    window.showToast('Deuda guardada exitosamente', 'success');
    fetchDebts();
}

async function deleteDebt(id) {
    window.showConfirm('¿Borrar esta deuda permanentemente?', async (ok) => {
        if (!ok) return;
        debtsState.debts = debtsState.debts.filter(d => d.id !== id);
        await saveDebtsState();
        window.showToast('Deuda eliminada exitosamente', 'success');
        fetchDebts();
    });
}

async function payDebtQuota(id) {
    const debtIndex = debtsState.debts.findIndex(d => d.id === id);
    if (debtIndex === -1) return;

    const debt = debtsState.debts[debtIndex];
    const effectivePayments = computeEffectivePayments();
    const finalPayment = effectivePayments.get(id) || Math.min(debt.balance, debt.minPayment);
    const dSym = debtGetSymbol(debt.currency);

    window.showConfirm(`¿Registrar abono de ${dSym} ${debtFmtNum(finalPayment)} a "${debt.name}"?`, async (ok) => {
        if (!ok) return;
        debt.balance = Math.max(0, debt.balance - finalPayment);

        if (py?.add_shopping) {
            await py.add_shopping(`Abono: ${debt.name}`, finalPayment, debt.currency || 'local',
                new Date().toISOString().split('T')[0], '', 'Deudas');
        }

        if (debt.balance === 0) {
            window.showToast(`🎉 ¡"${debt.name}" liquidada! El presupuesto extra ahora se aplica a la siguiente deuda.`, 'success');
        } else {
            window.showToast(`Abono de ${dSym} ${debtFmtNum(finalPayment)} registrado exitosamente`, 'success');
        }

        await saveDebtsState();
        fetchDebts();
        if (document.getElementById('view-budget')?.classList.contains('active')) {
            if (window.fetchBudget) window.fetchBudget();
        }
    });
}

// ── Listeners ─────────────────────────────────────────────────────────────────
function initDebtsListeners() {
    document.getElementById('btn-add-debt-dialog')?.addEventListener('click', () => openDebtModal());

    document.getElementById('debts-list')?.addEventListener('click', (e) => {
        const payBtn = e.target.closest('.debt-pay-btn');
        if (payBtn) { payDebtQuota(Number(payBtn.getAttribute('data-id'))); return; }
        const editBtn = e.target.closest('.debt-edit-btn');
        if (editBtn) { openDebtModal(Number(editBtn.getAttribute('data-id'))); return; }
        const deleteBtn = e.target.closest('.debt-delete-btn');
        if (deleteBtn) { deleteDebt(Number(deleteBtn.getAttribute('data-id'))); return; }
    });

    document.getElementById('save-debts-budget-btn')?.addEventListener('click', () => {
        const input = document.getElementById('debts-budget-input');
        if (input) {
            debtsState.budget = Number(input.value) || 0;
            saveDebtsState();
            window.showToast('Presupuesto de deudas actualizado', 'success');
            fetchDebts();
            if (window.fetchBudget) window.fetchBudget();
        }
    });

    // Selector de método
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.debt-method-btn');
        if (!btn) return;
        const method = btn.getAttribute('data-method');
        debtsState.method = method;
        localStorage.setItem('debtsMethod', method);

        document.querySelectorAll('.debt-method-btn').forEach(b => {
            const isActive = b.getAttribute('data-method') === method;
            b.style.background = isActive ? 'rgba(108,92,231,0.2)' : 'none';
            b.style.border = isActive ? '1px solid rgba(108,92,231,0.4)' : '1px solid transparent';
            b.style.color = isActive ? '#a29bfe' : 'var(--ag-text-muted)';
        });

        const label = document.getElementById('debts-sim-label');
        if (label) label.textContent = method === 'snowball' ? 'Bola de Nieve' : 'Avalancha';

        renderDebtsSummaryCards();
        renderDebtsList();
        renderSnowballProjection();
    });

    document.getElementById('save-debt-modal-btn')?.addEventListener('click', saveDebt);
    document.getElementById('close-debt-modal-cancel')?.addEventListener('click', () => {
        document.getElementById('debt-editor-modal')?.classList.remove('active');
    });
    document.getElementById('close-debt-modal-x')?.addEventListener('click', () => {
        document.getElementById('debt-editor-modal')?.classList.remove('active');
    });

    window.addEventListener('resize', () => {
        if (debtsState.debts.length > 0) renderDebtChart(runSimulation());
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDebtsListeners);
} else {
    initDebtsListeners();
}

window.fetchDebts = fetchDebts;
window.openDebtModal = openDebtModal;
window.saveDebt = saveDebt;
window.deleteDebt = deleteDebt;
window.payDebtQuota = payDebtQuota;
